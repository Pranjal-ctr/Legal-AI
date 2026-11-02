import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.agents.understanding import UserFacts
from app.core.config import Settings
from app.memory.crypto import KEY_FILE, Cipher, DecryptionError, load_key
from app.memory.store import HISTORY_CHARS, SessionStore

DAY = 86400.0


def _store(tmp_path: Path, key: bytes | None = None, ttl_days: int = 30) -> SessionStore:
    return SessionStore(tmp_path / "s.db", Cipher(key or Fernet.generate_key()), ttl_days)


def _turn(store: SessionStore, sid: str, n: int, now: float | None = None) -> None:
    store.append_turn(
        sid,
        question=f"प्रश्न {n}",
        question_en=f"question {n}",
        answer=f"उत्तर {n}",
        answer_en=f"answer {n}",
        kind="answer",
        language="hi",
        now=now,
    )


def test_turns_round_trip_and_history_is_english_and_recent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    for n in range(4):
        _turn(store, sid, n)

    messages = store.messages(sid)
    assert [(m.role, m.text) for m in messages[:2]] == [("user", "प्रश्न 0"), ("assistant", "उत्तर 0")]
    assert store.history(sid, 2) == [
        ("user", "question 2"),
        ("assistant", "answer 2"),
        ("user", "question 3"),
        ("assistant", "answer 3"),
    ]
    assert store.history(sid, 0) == []


def test_history_entries_are_truncated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    store.append_turn(
        sid, question="q", question_en="q", answer="a", answer_en="x" * 5000,
        kind="answer", language="en",
    )  # fmt: skip

    assert len(store.history(sid, 1)[1][1]) == HISTORY_CHARS


def test_content_and_facts_are_encrypted_at_rest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    _turn(store, sid, 7)
    store.set_facts(sid, UserFacts(religion="muslim"))
    store.close()

    raw = sqlite3.connect(tmp_path / "s.db")
    dump = "\n".join(raw.iterdump())
    raw.close()
    for secret in ("question 7", "answer 7", "muslim", "प्रश्न"):
        assert secret not in dump


def test_facts_persist(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    info = store.get(sid)
    assert info is not None
    assert info.facts == UserFacts()

    store.set_facts(sid, UserFacts(religion="hindu", marriage_type="hindu_rites"))

    info = store.get(sid)
    assert info is not None
    assert info.facts == UserFacts(religion="hindu", marriage_type="hindu_rites")


def test_delete_cascades_to_messages(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    _turn(store, sid, 1)

    assert store.delete(sid)
    assert store.get(sid) is None
    assert store.messages(sid) == []
    assert not store.delete(sid)


def test_sessions_expire_after_inactivity(tmp_path: Path) -> None:
    store = _store(tmp_path, ttl_days=1)
    t0 = 1_000_000.0
    old = store.create(now=t0)
    active = store.create(now=t0)
    _turn(store, active, 1, now=t0 + 0.9 * DAY)  # activity extends the session

    assert store.get(old, now=t0 + 1.5 * DAY) is None
    assert store.get(active, now=t0 + 1.5 * DAY) is not None
    assert store.purge_expired(now=t0 + 1.5 * DAY) == 1
    assert store.messages(active)  # untouched


def test_wrong_key_cannot_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = store.create()
    _turn(store, sid, 1)
    store.close()

    other = _store(tmp_path)  # same file, different key
    with pytest.raises(DecryptionError):
        other.messages(sid)


def test_generated_key_is_persisted_and_reused(tmp_path: Path) -> None:
    first = load_key(None, tmp_path / "sessions")
    second = load_key(None, tmp_path / "sessions")

    assert first == second
    assert (tmp_path / "sessions" / KEY_FILE).exists()


def test_configured_key_is_validated(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    assert load_key(key.decode(), tmp_path) == key
    with pytest.raises(ValueError):
        load_key("not-a-key", tmp_path)


def test_production_requires_a_session_key() -> None:
    with pytest.raises(ValidationError, match="LEGALAI_SESSION_KEY"):
        Settings(_env_file=None, environment="production")  # type: ignore[call-arg]
