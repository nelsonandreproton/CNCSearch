"""FastAPI shared dependencies."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from .auth import SESSION_COOKIE, verify_session


def check_auth(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    secret = request.app.state.config.web_secret_key
    return verify_session(token, secret)


def require_login(request: Request) -> RedirectResponse | None:
    """Return a redirect to /login if not authenticated, else None."""
    if not check_auth(request):
        return RedirectResponse("/login", status_code=302)
    return None
