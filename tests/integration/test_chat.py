import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.deps import get_orchestrator
from app.main import create_app
from tests.fakes import FakeLLM, make_orchestrator, scripted_llm


def _client_with(app: FastAPI, llm: FakeLLM) -> TestClient:
    orchestrator = make_orchestrator(llm)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    return TestClient(app)


def test_chat_returns_cited_answer_with_sources_and_trace(app: FastAPI) -> None:
    with _client_with(app, scripted_llm(answer="Alpha grounds apply [1].")) as client:
        response = client.post("/api/v1/chat", json={"message": "  what alpha grounds apply  "})

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "answer"
    assert body["answer"] == body["answer_en"] == "Alpha grounds apply [1]."
    assert body["grounded"] is True
    assert body["language"] == "en"
    assert body["english_query"] == "what alpha grounds apply"
    assert body["analysis"]["applicability"] == "applies"
    assert body["rounds"] == 1
    assert [s["step"] for s in body["trace"]] == ["understand", "retrieve_1", "assess", "generate"]
    first = body["sources"][0]
    assert (first["n"], first["cited"], first["chunk_id"]) == (1, True, "act1:s2")
    assert first["matched_chunk_ids"][0] == "act1:s2:ss1"
    assert first["text"].startswith("2. Grounds.")
    assert body["validation"]["translation_ok"] is True


def test_chat_asks_for_clarification_then_answers_with_facts(app: FastAPI) -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})
    with _client_with(app, llm) as client:
        first = client.post("/api/v1/chat", json={"message": "alpha grounds?"}).json()
        second = client.post(
            "/api/v1/chat",
            json={"message": "alpha grounds?", "facts": {"religion": "hindu"}},
        ).json()

    assert first["kind"] == "clarification"
    assert first["sources"] == []
    values = [o["value"] for o in first["clarification"]["options"]]
    assert values == [
        "hindu",
        "muslim",
        "christian",
        "parsi",
        "special_marriage_act",
        "unspecified",
    ]
    assert second["kind"] == "answer"
    assert second["analysis"]["applicability"] == "applies"


def test_chat_answers_in_hindi_via_english(app: FastAPI) -> None:
    llm = scripted_llm(
        query_en="what alpha grounds apply",
        translated_answer="अल्फा आधार लागू होते हैं [1]।",
    )
    with _client_with(app, llm) as client:
        body = client.post("/api/v1/chat", json={"message": "अल्फा आधार क्या हैं?"}).json()

    assert body["language"] == "hi"
    assert body["english_query"] == "what alpha grounds apply"
    assert body["answer"] == "अल्फा आधार लागू होते हैं [1]।"
    assert body["answer_en"] == "Alpha grounds apply [1]."
    assert "act1:s2" in [src["chunk_id"] for src in body["sources"]]


def test_chat_validates_request(app: FastAPI) -> None:
    with _client_with(app, scripted_llm()) as client:
        assert client.post("/api/v1/chat", json={"message": "   "}).status_code == 422
        assert client.post("/api/v1/chat", json={"message": "x" * 2001}).status_code == 422
        assert client.post("/api/v1/chat", json={}).status_code == 422
        bad_language = {"message": "x", "language": "fr"}
        assert client.post("/api/v1/chat", json=bad_language).status_code == 422
        bad_facts = {"message": "x", "facts": {"religion": "martian"}}
        assert client.post("/api/v1/chat", json=bad_facts).status_code == 422


def test_chat_returns_503_when_llm_is_down(app: FastAPI) -> None:
    # Understanding and assessment degrade gracefully; generation cannot.
    with _client_with(app, scripted_llm(fail=True)) as client:
        response = client.post("/api/v1/chat", json={"message": "Hindu alpha grounds"})

    assert response.status_code == 503
    assert "Language model unavailable" in response.json()["detail"]


def test_chat_returns_503_with_setup_hint_when_corpus_missing(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="test",
        data_dir=tmp_path,
        index_dir=tmp_path / "index",
        sessions_dir=tmp_path / "sessions",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/chat", json={"message": "alpha"})

    assert response.status_code == 503
    assert "scripts.ingest" in response.json()["detail"]


# ---- memory (Phase 8) -----------------------------------------------------------------------


def test_session_remembers_clarification_answer_and_history(app: FastAPI) -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})
    with _client_with(app, llm) as client:
        first = client.post("/api/v1/chat", json={"message": "alpha grounds?"}).json()
        sid = first["session_id"]
        answered = client.post(
            "/api/v1/chat",
            json={"message": "alpha grounds?", "facts": {"religion": "hindu"}, "session_id": sid},
        ).json()
        follow_up = client.post(
            "/api/v1/chat", json={"message": "and beta waiting period?", "session_id": sid}
        ).json()
        session = client.get(f"/api/v1/sessions/{sid}").json()

    assert first["kind"] == "clarification"
    assert answered["session_id"] == follow_up["session_id"] == sid
    assert follow_up["kind"] == "answer"  # not asked again: remembered from the profile
    assert follow_up["analysis"]["applicability"] == "applies"
    assert session["facts"] == {"religion": "hindu", "marriage_type": None}
    # the clarification detour is not stored: 2 turns = 4 messages
    assert [(m["role"], m["text"]) for m in session["messages"]][::2] == [
        ("user", "alpha grounds?"),
        ("user", "and beta waiting period?"),
    ]
    last_understanding = [p for s, p in llm.calls if s.startswith("You analyse")][-1]
    assert "user: alpha grounds?" in last_understanding


def test_unknown_session_id_starts_a_new_session(app: FastAPI) -> None:
    with _client_with(app, scripted_llm(answer="Alpha grounds apply [1].")) as client:
        body = client.post(
            "/api/v1/chat", json={"message": "what alpha grounds apply", "session_id": "0" * 32}
        ).json()

    assert body["session_id"] != "0" * 32
    assert len(body["session_id"]) == 32


def test_delete_session_erases_it(app: FastAPI) -> None:
    with _client_with(app, scripted_llm(answer="Alpha grounds apply [1].")) as client:
        sid = client.post("/api/v1/chat", json={"message": "what alpha grounds apply"}).json()[
            "session_id"
        ]
        assert client.get(f"/api/v1/sessions/{sid}").status_code == 200
        assert client.delete(f"/api/v1/sessions/{sid}").status_code == 204
        assert client.get(f"/api/v1/sessions/{sid}").status_code == 404
        assert client.delete(f"/api/v1/sessions/{sid}").status_code == 204  # idempotent
        assert client.get("/api/v1/sessions/not-a-valid-id").status_code == 422


# ---- streaming (live progress) ----------------------------------------------------------------


def _events(text: str) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_stream_sends_steps_then_the_result(app: FastAPI) -> None:
    with _client_with(app, scripted_llm(answer="Alpha grounds apply [1].")) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "what alpha grounds apply"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [e for e, _ in events] == ["step", "step", "step", "step", "result"]
    assert [d["step"] for _, d in events[:-1]] == ["understand", "retrieve_1", "assess", "generate"]
    result = events[-1][1]
    assert result["answer"] == "Alpha grounds apply [1]."
    assert len(result["session_id"]) == 32


def test_chat_stream_reports_llm_failure_as_error_event(app: FastAPI) -> None:
    with _client_with(app, FakeLLM(fail=True)) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "what alpha grounds apply"})

    event, data = _events(response.text)[-1]
    assert event == "error"
    assert data["status"] == 503
    assert "Language model unavailable" in data["detail"]


def test_chat_stream_validates_input_as_json(app: FastAPI) -> None:
    with _client_with(app, scripted_llm()) as client:
        assert client.post("/api/v1/chat/stream", json={"message": ""}).status_code == 422


# ---- feedback (Phase 11) ----------------------------------------------------------------------


def test_feedback_is_stored_with_the_session_and_erased_with_it(app: FastAPI) -> None:
    with _client_with(app, scripted_llm(answer="Alpha grounds apply [1].")) as client:
        sid = client.post("/api/v1/chat", json={"message": "what alpha grounds apply"}).json()[
            "session_id"
        ]
        body = {
            "session_id": sid,
            "rating": "down",
            "language": "en",
            "question": "what alpha grounds apply",
            "answer_en": "Alpha grounds apply [1].",
            "comment": "too short",
        }
        assert client.post("/api/v1/feedback", json=body).status_code == 204
        store = app.state.session_store
        assert store.feedback()[0]["comment"] == "too short"
        assert store.feedback()[0]["rating"] == "down"

        client.delete(f"/api/v1/sessions/{sid}")
        assert store.feedback() == []
        gone = client.post("/api/v1/feedback", json=body)
        assert gone.status_code == 404
        bad = client.post("/api/v1/feedback", json={**body, "rating": "meh"})
        assert bad.status_code == 422


# ---- abuse protection (Phase 12) ---------------------------------------------------------------


def test_chat_is_rate_limited_per_client(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="test",
        sessions_dir=tmp_path / "s",
        rate_limit_chat_per_min=2,
    )
    app = create_app(settings)
    with _client_with(app, scripted_llm(answer="Alpha grounds apply [1].")) as client:
        codes = [
            client.post("/api/v1/chat", json={"message": "what alpha grounds apply"}).status_code
            for _ in range(3)
        ]
        blocked = client.post("/api/v1/chat/stream", json={"message": "alpha"})

    assert codes == [200, 200, 429]
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_oversized_bodies_are_rejected_before_parsing(app: FastAPI) -> None:
    with _client_with(app, scripted_llm()) as client:
        response = client.post(
            "/api/v1/chat",
            content=b"{" + b" " * (300 * 1024) + b"}",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413


def test_security_headers_and_production_csp(tmp_path: Path) -> None:
    with _client_with(
        create_app(Settings(_env_file=None, environment="test", sessions_dir=tmp_path)),
        scripted_llm(),
    ) as client:  # type: ignore[call-arg]
        dev = client.get("/api/v1/health")
    assert dev.headers["X-Content-Type-Options"] == "nosniff"
    assert dev.headers["X-Frame-Options"] == "DENY"
    assert "microphone=(self)" in dev.headers["Permissions-Policy"]
    assert "Content-Security-Policy" not in dev.headers

    prod = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="production",
        session_key="Hj2bWq7mT1qkqfJ0Yt3fAqjA1pX0d0V1c9nYkzQfR3U=",
        sessions_dir=tmp_path,
    )
    with TestClient(create_app(prod)) as client:
        response = client.get("/api/v1/health")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
