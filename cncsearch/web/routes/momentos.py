"""Momentos litúrgicos CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..deps import require_login

router = APIRouter(prefix="/momentos")
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def list_momentos(request: Request, success: str = "", error: str = ""):
    if r := require_login(request):
        return r
    repo = request.app.state.repo
    moments = repo.get_moments()
    # Attach cantico count to each moment
    moments_with_count = [
        {"moment": m, "count": repo.count_canticos_for_moment(m.id)}
        for m in moments
    ]
    return templates.TemplateResponse(
        "momentos/list.html",
        {
            "request": request,
            "moments_with_count": moments_with_count,
            "success": success,
            "error": error,
        },
    )


@router.post("/new")
async def create_momento(request: Request, name: str = Form(...)):
    if r := require_login(request):
        return r
    name = name.strip()
    if not name:
        return RedirectResponse("/momentos?error=Nome+obrigatório", status_code=303)
    if len(name) > 100:
        return RedirectResponse("/momentos?error=Nome+demasiado+longo+(máx.+100+caracteres)", status_code=303)
    repo = request.app.state.repo
    if repo.get_moment_by_name(name):
        return RedirectResponse(f"/momentos?error=Momento+{name}+já+existe", status_code=303)
    repo.create_moment(name)
    return RedirectResponse("/momentos?success=Momento+criado", status_code=303)


@router.post("/{moment_id}/edit")
async def update_momento(request: Request, moment_id: int, name: str = Form(...)):
    if r := require_login(request):
        return r
    name = name.strip()
    if not name:
        return RedirectResponse("/momentos?error=Nome+obrigatório", status_code=303)
    if len(name) > 100:
        return RedirectResponse("/momentos?error=Nome+demasiado+longo+(máx.+100+caracteres)", status_code=303)
    request.app.state.repo.update_moment(moment_id, name)
    return RedirectResponse("/momentos?success=Momento+actualizado", status_code=303)


@router.post("/{moment_id}/delete")
async def delete_momento(request: Request, moment_id: int):
    if r := require_login(request):
        return r
    repo = request.app.state.repo
    count = repo.count_canticos_for_moment(moment_id)
    if count > 0:
        return RedirectResponse(
            f"/momentos?error=Não+é+possível+eliminar:+{count}+cântico(s)+associado(s)",
            status_code=303,
        )
    repo.delete_moment(moment_id)
    return RedirectResponse("/momentos?success=Momento+eliminado", status_code=303)
