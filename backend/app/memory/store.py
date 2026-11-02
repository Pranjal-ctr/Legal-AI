"""Session store on SQLite (stdlib ``sqlite3``); the schema is portable to PostgreSQL.

Message texts and the user's facts are encrypted (they can reveal religion, family situation,
violence). Only routing metadata is plaintext: role, kind, language, timestamps. Sessions
expire ``ttl_days`` after their last activity and are purged on open and on session creation.
"""

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.agents.understanding import UserFacts
from app.memory.crypto import Cipher

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    facts       BLOB
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    kind        TEXT NOT NULL,
    language    TEXT NOT NULL,
    payload     BLOB NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS ix_sessions_updated ON sessions(updated_at);
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    rating      TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    language    TEXT NOT NULL,
    payload     BLOB NOT NULL,
    created_at  REAL NOT NULL
);
"""

# Each history entry is truncated so a long answer cannot crowd the understanding prompt.
HISTORY_CHARS = 600


@dataclass(frozen=True)
class StoredMessage:
    role: str  # user | assistant
    kind: str  # question | answer | out_of_scope
    language: str
    text: str  # as shown to the user
    text_en: str  # English (the standalone question / the verified answer)
    created_at: float


@dataclass(frozen=True)
class SessionInfo:
    id: str
    created_at: float
    updated_at: float
    facts: UserFacts


def new_session_id() -> str:
    return secrets.token_hex(16)  # 128-bit, unguessable: the id is the access capability


class SessionStore:
    def __init__(self, path: Path, cipher: Cipher, ttl_days: int = 30) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = cipher
        self._ttl_s = ttl_days * 86400.0
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)
        self.purge_expired()

    # ---- sessions ------------------------------------------------------------------------

    def create(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        self.purge_expired(now)
        session_id = new_session_id()
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (id, created_at, updated_at, facts) VALUES (?, ?, ?, NULL)",
                (session_id, now, now),
            )
        return session_id

    def get(self, session_id: str, now: float | None = None) -> SessionInfo | None:
        """The session, or None if it does not exist or has expired."""
        now = time.time() if now is None else now
        with self._lock:
            row = self._db.execute(
                "SELECT id, created_at, updated_at, facts FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None or row[2] < now - self._ttl_s:
            return None
        facts = (
            UserFacts.model_validate_json(self._cipher.decrypt(row[3])) if row[3] else UserFacts()
        )
        return SessionInfo(id=row[0], created_at=row[1], updated_at=row[2], facts=facts)

    def set_facts(self, session_id: str, facts: UserFacts) -> None:
        blob = self._cipher.encrypt(facts.model_dump_json(exclude_none=True))
        with self._lock:
            self._db.execute("UPDATE sessions SET facts = ? WHERE id = ?", (blob, session_id))

    def delete(self, session_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    def purge_expired(self, now: float | None = None) -> int:
        cutoff = (time.time() if now is None else now) - self._ttl_s
        with self._lock:
            cursor = self._db.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        return cursor.rowcount

    # ---- messages ------------------------------------------------------------------------

    def append_turn(
        self,
        session_id: str,
        *,
        question: str,
        question_en: str,
        answer: str,
        answer_en: str,
        kind: str,
        language: str,
        now: float | None = None,
    ) -> None:
        now = time.time() if now is None else now
        rows = [
            ("user", "question", question, question_en),
            ("assistant", kind, answer, answer_en),
        ]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for role, row_kind, text, text_en in rows:
                    payload = self._cipher.encrypt(json.dumps({"text": text, "text_en": text_en}))
                    self._db.execute(
                        "INSERT INTO messages (session_id, role, kind, language, payload, "
                        "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (session_id, role, row_kind, language, payload, now),
                    )
                self._db.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def messages(self, session_id: str, limit: int | None = None) -> list[StoredMessage]:
        """Messages oldest first; ``limit`` keeps only the most recent ones."""
        query = (
            "SELECT role, kind, language, payload, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id DESC"
        )
        params: tuple[object, ...] = (session_id,)
        if limit is not None:
            query += " LIMIT ?"
            params = (session_id, limit)
        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        out = []
        for role, kind, language, payload, created_at in reversed(rows):
            data = json.loads(self._cipher.decrypt(payload))
            out.append(
                StoredMessage(role, kind, language, data["text"], data["text_en"], created_at)
            )
        return out

    def history(self, session_id: str, turns: int) -> list[tuple[str, str]]:
        """The last ``turns`` question/answer pairs in English, as (role, text), oldest first."""
        if turns <= 0:
            return []
        return [
            (m.role, m.text_en[:HISTORY_CHARS]) for m in self.messages(session_id, limit=2 * turns)
        ]

    # ---- feedback (Phase 11; read by evaluation) ---------------------------------------

    def add_feedback(
        self,
        session_id: str,
        *,
        rating: str,
        language: str,
        question: str,
        answer_en: str,
        comment: str = "",
        now: float | None = None,
    ) -> None:
        """Deleted with its session (the user's erase request covers feedback too)."""
        payload = self._cipher.encrypt(
            json.dumps({"question": question, "answer_en": answer_en, "comment": comment})
        )
        with self._lock:
            self._db.execute(
                "INSERT INTO feedback (session_id, rating, language, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, rating, language, payload, time.time() if now is None else now),
            )

    def feedback(self) -> list[dict[str, object]]:
        """All feedback, oldest first, decrypted (for evaluation reports)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT rating, language, payload, created_at FROM feedback ORDER BY id"
            ).fetchall()
        return [
            {"rating": r, "language": lang, "created_at": at, **json.loads(self._cipher.decrypt(p))}
            for r, lang, p, at in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._db.close()
