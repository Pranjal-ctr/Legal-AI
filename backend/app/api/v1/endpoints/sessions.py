"""Conversation sessions: read back or delete (the user's right to erase their data)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.core.deps import SessionStoreDep
from app.schemas.chat import FeedbackRequest, SessionMessage, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])

SessionIdPath = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: SessionIdPath, store: SessionStoreDep) -> SessionOut:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found or expired.")
    return SessionOut(
        session_id=session.id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        facts=session.facts,
        messages=[
            SessionMessage.model_validate(m, from_attributes=True)
            for m in store.messages(session.id)
        ],
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: SessionIdPath, store: SessionStoreDep) -> Response:
    """Deletes the session and all its messages. Idempotent."""
    store.delete(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


feedback_router = APIRouter(tags=["feedback"])


@feedback_router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
def add_feedback(body: FeedbackRequest, store: SessionStoreDep) -> Response:
    """Thumbs up/down on an answer, kept (encrypted) with the session for evaluation."""
    if store.get(body.session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found or expired.")
    store.add_feedback(
        body.session_id,
        rating=body.rating,
        language=body.language,
        question=body.question,
        answer_en=body.answer_en,
        comment=body.comment,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
