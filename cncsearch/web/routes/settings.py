"""Settings and reindex routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import hash_password, verify_password
from ..deps import require_login

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, success: str = "", error: str = ""):
    if r := require_login(request):
        return r
    repo = request.app.state.repo
    settings = repo.get_all_settings()
    total = repo.count_canticos()
    without_emb = repo.count_canticos_without_embedding()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "total_canticos": total,
            "without_embedding": without_emb,
            "success": success,
            "error": error,
        },
    )


@router.post("/settings")
async def update_settings(
    request: Request,
    top_n: str = Form(...),
    min_similarity: str = Form(...),
    web_username: str = Form(...),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
):
    if r := require_login(request):
        return r

    repo = request.app.state.repo

    # Parse and validate numeric fields gracefully
    try:
        top_n_int = int(top_n)
        min_sim_float = float(min_similarity)
    except ValueError:
        return RedirectResponse("/settings?error=Valores+numéricos+inválidos", status_code=303)

    if top_n_int < 1 or top_n_int > 20:
        return RedirectResponse("/settings?error=top_n+deve+estar+entre+1+e+20", status_code=303)
    if not (0.0 <= min_sim_float <= 1.0):
        return RedirectResponse("/settings?error=Similaridade+mínima+deve+estar+entre+0+e+1", status_code=303)

    repo.set_setting("top_n", str(top_n_int))
    repo.set_setting("min_similarity", f"{min_sim_float:.2f}")
    repo.set_setting("web_username", web_username.strip())

    # Password change (optional)
    if new_password:
        if new_password != confirm_password:
            return RedirectResponse("/settings?error=As+palavras-passe+não+coincidem", status_code=303)
        stored_hash = repo.get_setting("web_password_hash", "")
        if not verify_password(current_password, stored_hash):
            return RedirectResponse("/settings?error=Palavra-passe+actual+incorrecta", status_code=303)
        repo.set_setting("web_password_hash", hash_password(new_password))

    return RedirectResponse("/settings?success=Configurações+guardadas", status_code=303)


@router.post("/reindex")
async def reindex(request: Request):
    if r := require_login(request):
        return r
    search = request.app.state.search
    try:
        count = await asyncio.to_thread(search.reindex_all)
        return RedirectResponse(f"/settings?success={count}+cânticos+re-indexados", status_code=303)
    except Exception:
        return RedirectResponse("/settings?error=Erro+na+re-indexação.+Consulta+os+logs.", status_code=303)
