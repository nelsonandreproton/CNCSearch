"""Test search route (web UI)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..deps import require_login

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    if r := require_login(request):
        return r
    repo = request.app.state.repo
    moments = repo.get_moments()
    settings = repo.get_all_settings()
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "moments": moments,
            "results": None,
            "query": "",
            "settings": settings,
            "selected_source": "",
            "error": "",
        },
    )


@router.post("/search", response_class=HTMLResponse)
async def search_submit(
    request: Request,
    query: str = Form(...),
    top_n: str = Form(""),
    moment_id: str = Form(""),
    source: str = Form(""),
):
    if r := require_login(request):
        return r

    repo = request.app.state.repo
    search = request.app.state.search
    moments = repo.get_moments()
    settings = repo.get_all_settings()

    raw_n = int(top_n) if top_n.strip().isdigit() else int(settings.get("top_n", "3"))
    n = max(1, min(20, raw_n))
    min_sim = float(settings.get("min_similarity", "0.40"))
    mid = int(moment_id) if moment_id.strip().isdigit() else None
    src = source.strip() or None

    try:
        results = await asyncio.to_thread(
            search.search, query.strip(), n, min_sim, mid, None, src
        )
        moment_map = {m.id: m.name for m in moments}
        for r in results:
            names = [moment_map[mid] for mid in r.get("moment_ids", []) if mid in moment_map]
            r["moment_name"] = ", ".join(names)
        error = ""
    except Exception:
        results = []
        error = "Erro ao pesquisar. Verifica as configurações e tenta novamente."

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "moments": moments,
            "results": results,
            "query": query,
            "settings": settings,
            "selected_source": src or "",
            "error": error,
        },
    )
