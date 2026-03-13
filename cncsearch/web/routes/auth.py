"""Login / logout routes."""

from __future__ import annotations

import collections
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import SESSION_COOKIE, create_session, verify_password

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# ── Rate limiting (in-memory, single-process) ─────────────────────────────────
_login_attempts: dict[str, list[float]] = collections.defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # 5 minutes


def _is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    window = _login_attempts[ip]
    window[:] = [t for t in window if now - t < _WINDOW_SECONDS]
    if len(window) >= _MAX_ATTEMPTS:
        return True
    window.append(now)
    return False


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": error}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Demasiadas tentativas. Tenta novamente em 5 minutos."},
            status_code=429,
        )

    repo = request.app.state.repo
    stored_user = repo.get_setting("web_username", "admin")
    stored_hash = repo.get_setting("web_password_hash", "")

    if username != stored_user or not verify_password(password, stored_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Utilizador ou palavra-passe incorrectos."},
            status_code=401,
        )

    secret = request.app.state.config.web_secret_key
    token = create_session(secret)
    response = RedirectResponse("/canticos", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
