"""Public-facing Parish Hymns directory — no authentication required."""

from __future__ import annotations

import logging
import unicodedata

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/paroquia")
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)


def _normalize_first_letter(title: str) -> str:
    """Return the base ASCII letter for a title's first character.

    Strips accents so 'Á' → 'A', 'Ç' → 'C', etc.
    Non-alpha first chars return '#'.
    """
    if not title:
        return "#"
    ch = title[0].upper()
    # NFD decomposes 'Á' into 'A' + combining accent; take the base char
    nfd = unicodedata.normalize("NFD", ch)
    base = nfd[0]
    return base if base.isalpha() else "#"


@router.get("", response_class=HTMLResponse)
async def paroquia_index(request: Request):
    """Public directory of parish hymns, ordered alphabetically."""
    canticos = request.app.state.repo.get_canticos(source="paroquia")  # alphabetical

    songs = []
    letters_seen: set[str] = set()
    for i, c in enumerate(canticos):
        norm = _normalize_first_letter(c.title)
        letters_seen.add(norm)
        songs.append({"cantico": c, "norm_first": norm, "seq": i + 1})

    az_letters = sorted(letters_seen)

    return templates.TemplateResponse(
        "paroquia/index.html",
        {
            "request": request,
            "songs": songs,
            "az_letters": az_letters,
            "total": len(songs),
        },
    )


@router.get("/{cantico_id}", response_class=HTMLResponse)
async def paroquia_song(request: Request, cantico_id: int):
    """Public page for a single parish hymn with prev/next navigation."""
    cantico = request.app.state.repo.get_cantico(cantico_id)
    if not cantico or cantico.source != "paroquia":
        return RedirectResponse("/paroquia", status_code=302)

    neighbors = request.app.state.repo.get_paroquia_neighbors(cantico_id)

    return templates.TemplateResponse(
        "paroquia/song.html",
        {
            "request": request,
            "cantico": cantico,
            **neighbors,
        },
    )
