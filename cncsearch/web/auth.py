"""Session authentication helpers."""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pre-computed hash used as a constant-time dummy target.
# verify_password always calls bcrypt, preventing timing-based user enumeration.
_DUMMY_HASH = _pwd_ctx.hash("timing-safety-dummy-cncsearch")

SESSION_COOKIE = "cncsearch_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    # Always run bcrypt — never short-circuit on empty hash to prevent timing attacks.
    result = _pwd_ctx.verify(plain, hashed if hashed else _DUMMY_HASH)
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
