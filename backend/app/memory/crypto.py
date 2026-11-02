"""Encryption at rest for conversation content (Fernet: AES-128-CBC + HMAC-SHA256).

The key comes from ``LEGALAI_SESSION_KEY``. Without one (development/test only; production
refuses to start, see ``Settings``), a key is generated once into ``<sessions_dir>/secret.key``,
which is git-ignored together with the database.
"""

from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)

KEY_FILE = "secret.key"


class DecryptionError(RuntimeError):
    """Stored data cannot be decrypted (wrong or rotated key, or corrupted data)."""


class Cipher:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, text: str) -> bytes:
        return self._fernet.encrypt(text.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise DecryptionError("cannot decrypt stored session data (key changed?)") from exc


def load_key(configured: str | None, sessions_dir: Path) -> bytes:
    """The configured key, else a persisted generated one (created on first use)."""
    if configured:
        key = configured.encode("ascii")
        Fernet(key)  # validates format: fail fast on a malformed key
        return key
    path = sessions_dir / KEY_FILE
    if path.exists():
        return path.read_bytes().strip()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    logger.warning("session_key_generated", path=str(path), hint="set LEGALAI_SESSION_KEY")
    return key
