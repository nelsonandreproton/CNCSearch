"""Canticos CRUD routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..deps import require_login

router = APIRouter(prefix="/canticos")
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

_CSV_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


@router.get("", response_class=HTMLResponse)
async def list_canticos(request: Request, success: str = "", error: str = ""):
    if r := require_login(request):
        return r
    canticos = request.app.state.repo.get_canticos()
    return templates.TemplateResponse(
        "canticos/list.html",
        {"request": request, "canticos": canticos, "success": success, "error": error},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_cantico_form(request: Request):
    if r := require_login(request):
        return r
    moments = request.app.state.repo.get_moments()
    return templates.TemplateResponse(
        "canticos/form.html",
        {"request": request, "cantico": None, "moments": moments, "error": ""},
    )


@router.post("/new")
async def create_cantico(
    request: Request,
    title: str = Form(...),
    lyrics: str = Form(...),
    sheet_url: str = Form(""),
    moment_id: str = Form(""),
):
    if r := require_login(request):
        return r

    repo = request.app.state.repo
    search = request.app.state.search

    mid = int(moment_id) if moment_id else None
    if mid is not None and not repo.get_moment(mid):
        moments = repo.get_moments()
        return templates.TemplateResponse(
            "canticos/form.html",
            {"request": request, "cantico": None, "moments": moments, "error": "Momento litúrgico inválido."},
            status_code=400,
        )

    cantico = repo.create_cantico(title, lyrics, sheet_url or None, mid)

    try:
        await asyncio.to_thread(search.embed_and_store, cantico.id, title, lyrics)
        return RedirectResponse("/canticos?success=Cântico+criado+com+sucesso", status_code=303)
    except Exception as exc:
        logger.error("Embedding failed for cantico %d: %s", cantico.id, exc, exc_info=True)
        return RedirectResponse(
            "/canticos?success=Cântico+criado"
            "&error=Embedding+falhou+-+usa+Re-indexar+em+Definições",
            status_code=303,
        )


@router.get("/import", response_class=HTMLResponse)
async def import_form(request: Request, success: str = "", error: str = ""):
    if r := require_login(request):
        return r
    return templates.TemplateResponse(
        "canticos/import.html",
        {"request": request, "result": None, "success": success, "error": error},
    )


@router.post("/import")
async def import_csv(request: Request, file: UploadFile):
    if r := require_login(request):
        return r

    repo = request.app.state.repo
    search = request.app.state.search

    raw = await file.read()
    if len(raw) > _CSV_MAX_BYTES:
        return templates.TemplateResponse(
            "canticos/import.html",
            {"request": request, "result": None, "success": "", "error": "Ficheiro demasiado grande (máx. 5 MB)."},
            status_code=400,
        )

    content = raw.decode("utf-8-sig")  # handle BOM
    result = repo.import_csv(content)

    # Embed newly imported canticos
    try:
        await asyncio.to_thread(search.reindex_all)
    except Exception as exc:
        logger.error("Reindex after import failed: %s", exc, exc_info=True)
        result["embedding_warning"] = "Embedding falhou — usa Re-indexar em Definições."

    return templates.TemplateResponse(
        "canticos/import.html",
        {"request": request, "result": result, "success": "", "error": ""},
    )


@router.get("/{cantico_id}/edit", response_class=HTMLResponse)
async def edit_cantico_form(request: Request, cantico_id: int):
    if r := require_login(request):
        return r
    repo = request.app.state.repo
    cantico = repo.get_cantico(cantico_id)
    if not cantico:
        return RedirectResponse("/canticos?error=Cântico+não+encontrado", status_code=302)
    moments = repo.get_moments()
    return templates.TemplateResponse(
        "canticos/form.html",
        {"request": request, "cantico": cantico, "moments": moments, "error": ""},
    )


@router.post("/{cantico_id}/edit")
async def update_cantico(
    request: Request,
    cantico_id: int,
    title: str = Form(...),
    lyrics: str = Form(...),
    sheet_url: str = Form(""),
    moment_id: str = Form(""),
):
    if r := require_login(request):
        return r

    repo = request.app.state.repo
    search = request.app.state.search

    mid = int(moment_id) if moment_id else None
    if mid is not None and not repo.get_moment(mid):
        cantico = repo.get_cantico(cantico_id)
        moments = repo.get_moments()
        return templates.TemplateResponse(
            "canticos/form.html",
            {"request": request, "cantico": cantico, "moments": moments, "error": "Momento litúrgico inválido."},
            status_code=400,
        )

    updated = repo.update_cantico(cantico_id, title, lyrics, sheet_url or None, mid)
    if not updated:
        return RedirectResponse("/canticos?error=Cântico+não+encontrado", status_code=302)

    try:
        await asyncio.to_thread(search.embed_and_store, cantico_id, title, lyrics)
        return RedirectResponse("/canticos?success=Cântico+actualizado", status_code=303)
    except Exception as exc:
        logger.error("Embedding failed for cantico %d: %s", cantico_id, exc, exc_info=True)
        return RedirectResponse(
            "/canticos?success=Cântico+actualizado"
            "&error=Embedding+falhou+-+usa+Re-indexar+em+Definições",
            status_code=303,
        )


@router.post("/{cantico_id}/delete")
async def delete_cantico(request: Request, cantico_id: int):
    if r := require_login(request):
        return r
    request.app.state.repo.delete_cantico(cantico_id)
    return RedirectResponse("/canticos?success=Cântico+eliminado", status_code=303)
