import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agents.orchestrator import ChatResult, Orchestrator, StepCallback
from app.agents.understanding import UserFacts
from app.core.config import Settings
from app.core.deps import OrchestratorDep, SessionStoreDep, SettingsDep
from app.core.security import rate_limit
from app.memory.crypto import DecryptionError
from app.memory.store import SessionInfo, SessionStore
from app.providers.llm import LLMError
from app.schemas.chat import (
    AnalysisOut,
    ChatRequest,
    ChatResponse,
    ClarificationOut,
    ClarifyOptionOut,
    Source,
    TraceStepOut,
    ValidationOut,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


def to_response(result: ChatResult, session_id: str) -> ChatResponse:
    cited = set(result.cited)
    analysis = result.analysis
    return ChatResponse(
        session_id=session_id,
        kind=result.kind,
        answer=result.answer,
        answer_en=result.answer_en,
        grounded=result.grounded,
        sources=[
            Source(
                n=item.n,
                chunk_id=item.unit.chunk_id,
                matched_chunk_ids=item.matched_chunk_ids,
                doc_id=item.document.doc_id,
                doc_type=item.document.doc_type,
                title=item.document.title,
                label=item.unit.label,
                court=item.document.court,
                citation=item.document.citation,
                decision_date=item.document.decision_date,
                page_start=item.unit.page_start,
                page_end=item.unit.page_end,
                text=item.unit.text,
                score=round(item.score, 4),
                cited=item.n in cited,
            )
            for item in result.evidence
        ],
        model=result.model,
        language=result.language,
        romanized=result.romanized,
        english_query=result.english_query,
        notices=[n for n in result.notices if n],
        emergency=result.emergency,
        clarification=(
            ClarificationOut(
                question=result.clarification.question,
                options=[
                    ClarifyOptionOut(field=o.field, value=o.value, label=o.label)
                    for o in result.clarification.options
                ],
            )
            if result.clarification
            else None
        ),
        analysis=(
            AnalysisOut(
                topic=analysis.topic,
                religion=analysis.religion,
                marriage_type=analysis.marriage_type,
                in_scope=analysis.in_scope,
                applicability=result.applicability.decision if result.applicability else None,
            )
            if analysis
            else None
        ),
        validation=ValidationOut(**result.validation.__dict__),
        rounds=result.rounds,
        trace=[TraceStepOut(step=s.step, ms=s.ms, detail=s.detail) for s in result.trace],
    )


def _open_session(
    store: SessionStore, session_id: str | None, history_turns: int
) -> tuple[SessionInfo | None, list[tuple[str, str]]]:
    """The existing session and its recent history, or (None, []) to start a new one."""
    if session_id is None:
        return None, []
    try:
        session = store.get(session_id)
        if session is None:
            return None, []
        return session, store.history(session.id, history_turns)
    except DecryptionError:
        logger.warning("session_unreadable", reason="decryption failed; starting a new session")
        return None, []


def _updated_profile(profile: UserFacts, stated: UserFacts | None) -> UserFacts | None:
    """Explicit answers (clarification buttons) are remembered; question facts are not, as a
    question may describe someone else's situation."""
    if stated is None:
        return None
    changes = stated.model_dump(exclude_none=True)
    return profile.model_copy(update=changes) if changes else None


async def _run_turn(
    body: ChatRequest,
    orchestrator: Orchestrator,
    store: SessionStore,
    settings: Settings,
    on_step: StepCallback | None = None,
) -> ChatResponse:
    """One conversation turn: load the session, answer, remember. Raises ``LLMError``."""
    session, history = _open_session(store, body.session_id, settings.session_history_turns)
    session_id = session.id if session else store.create()
    profile = session.facts if session else UserFacts()
    result = await orchestrator.answer(
        body.message,
        body.language,
        body.facts,
        history=history,
        profile=profile if profile.model_dump(exclude_none=True) else None,
        on_step=on_step,
    )
    new_profile = _updated_profile(profile, body.facts)
    if new_profile is not None:
        store.set_facts(session_id, new_profile)
    # A clarification is a detour: the question is stored once, with its eventual answer.
    if result.kind != "clarification":
        store.append_turn(
            session_id,
            question=body.message,
            question_en=result.english_query,
            answer=result.answer,
            answer_en=result.answer_en,
            kind=result.kind,
            language=result.language,
        )
    return to_response(result, session_id)


def _llm_unavailable(exc: LLMError) -> str:
    return f"Language model unavailable: {exc}"


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit("chat"))])
async def chat(
    body: ChatRequest,
    orchestrator: OrchestratorDep,
    store: SessionStoreDep,
    settings: SettingsDep,
) -> ChatResponse:
    """Source-grounded answer in English, Hindi or Kannada; may ask a clarifying question.

    Turns are remembered per session: follow-ups are resolved against recent history, and
    answers to clarifying questions are not asked again.
    """
    try:
        return await _run_turn(body, orchestrator, store, settings)
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _llm_unavailable(exc)) from exc


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.post(
    "/chat/stream",
    dependencies=[Depends(rate_limit("chat"))],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_stream(
    body: ChatRequest,
    orchestrator: OrchestratorDep,
    store: SessionStoreDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Same as ``POST /chat`` as Server-Sent Events: ``step`` events (``{"step": name}``) as
    each stage starts, then one ``result`` (a ChatResponse) or ``error``
    (``{"status", "detail"}``). Setup errors (503) and invalid input (422) are plain JSON.
    """
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    async def on_step(step: str) -> None:
        await queue.put(("step", json.dumps({"step": step})))

    async def run() -> None:
        try:
            response = await _run_turn(body, orchestrator, store, settings, on_step)
            await queue.put(("result", response.model_dump_json()))
        except LLMError as exc:
            await queue.put(("error", json.dumps({"status": 503, "detail": _llm_unavailable(exc)})))
        except Exception:
            logger.exception("chat_stream_failed")
            await queue.put(("error", json.dumps({"status": 500, "detail": "Internal error."})))

    async def events() -> AsyncIterator[str]:
        task = asyncio.create_task(run())
        try:
            while True:
                event, data = await queue.get()
                yield _sse(event, data)
                if event != "step":
                    break
        finally:
            if not task.done():  # client went away: stop working on the answer
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
