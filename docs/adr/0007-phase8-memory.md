# ADR 0007: Phase 8 conversation memory with encrypted SQLite sessions

- **Status:** Accepted (Phase 8, 2026-11-01)

## Context

Follow-up questions ("and maintenance while that case is pending?") need the earlier turns.
Answers to clarifying questions should not be asked again. The architecture puts messages
(encrypted) in PostgreSQL and hot state in Redis. Neither is installed yet, and this prototype
runs on one laptop.

## Decision

- **Store:** `app/memory/store.py` uses stdlib `sqlite3` (`data/sessions/sessions.db`,
  git-ignored), with the tables `sessions(id, created_at, updated_at, facts)` and
  `messages(session_id → CASCADE, role, kind, language, payload, created_at)`. The SQL is
  portable, so moving to PostgreSQL in Phase 14 means swapping the connection and keeping the
  schema. No ORM dependency. Redis is deferred until there are several workers.
- **Encryption at rest:** message texts (shown and English) and the facts are Fernet-encrypted
  (`cryptography`). Only routing metadata (role, kind, language, timestamps) is plaintext. The key
  comes from `LEGALAI_SESSION_KEY`, and **production refuses to start without it**. In
  development a key is generated once into `data/sessions/secret.key`. If the key changes, old
  sessions can't be read, and a new session starts silently.
- **Session id** = 128-bit random hex. Until Phase 12 adds authentication it is the access
  capability. An unknown or expired id starts a new session (the response returns the id).
- **Retention:** sessions expire 30 days after their last activity (`LEGALAI_SESSION_TTL_DAYS`)
  and are purged on open and on create. `DELETE /api/v1/sessions/{id}` erases them at once, and
  the UI's "New conversation" button calls it (privacy by default).
- **What the orchestrator gets:** the last `LEGALAI_SESSION_HISTORY_TURNS` (3) Q/A pairs in
  English (the standalone question and the verified answer, truncated to 600 characters each).
  They are used only by query understanding to write the standalone question, which then drives
  retrieval and generation.
- **Facts precedence** (`applicability.fill_facts`): this request's facts (a clarification
  answer) > what the current question states > the session profile. **Only explicit clarification
  answers are saved to the profile.** Facts extracted from a question are not saved, because a
  question may describe someone else ("my friend is Muslim…") and gating on them later would
  apply the wrong law.
- Clarification turns are not stored. The question is stored once, with its answer.

## Consequences

- Live check (`reports/live_memory.py`): clarification → answer → English follow-up → Hindi
  follow-up all in one session, no repeated clarification, no plaintext in the DB, delete
  works. Follow-up latency is unchanged (~13–25 s).
- Observed retrieval gap (not a memory issue): "maintenance while the divorce case is pending"
  did not retrieve HMA s.24 (maintenance pendente lite). This is tracked for Phase 13
  evaluation and gold-query expansion.
- SQLite writes are serialised by a lock. That is fine for one process, not for many workers
  (Phase 14).
