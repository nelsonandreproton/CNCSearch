"""Session authentication helpers."""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Lazy-computed dummy hash for constant-time verification.
# Not computed at import time to avoid triggering bcrypt backend initialisation too early.
_dummy_hash: str = ""

SESSION_COOKIE = "cncsearch_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def _get_dummy_hash() -> str:
    """Return a cached bcrypt hash used as a constant-time dummy target."""
    global _dummy_hash
    if not _dummy_hash:
        _dummy_hash = _pwd_ctx.hash("x")
    return _dummy_hash


def verify_password(plain: str, hashed: str) -> bool:
    # Always run bcrypt — never short-circuit on empty hash to prevent timing attacks.
    result = _pwd_ctx.verify(plain, hashed if hashed else _get_dummy_hash())
    return result and bool(hashed)


def create_session(secret_key: str) -> str:
    s = URLSafeTimedSerializer(secret_key)
    return s.dumps({"ok": True})


def verify_session(token: str, secret_key: str) -> bool:
    s = URLSafeTimedSerializer(secret_key)
    try:
        s.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False
