"""Tests for cncsearch.ingest.columns — column geometry detection.

Grounded in the real cached song sheets (Phase 1 calibration). The images live
in scripts/resucito_images/ which is gitignored, so each test skips cleanly
when the fixture image is absent (e.g. on CI or a fresh checkout).
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from cncsearch.ingest.columns import detect_columns, split_columns  # noqa: E402

_IMAGES = Path(__file__).resolve().parent.parent / "scripts" / "resucito_images"


def _img(name: str) -> Image.Image:
    path = _IMAGES / name
    if not path.exists():
        pytest.skip(f"fixture image not available: {name}")
    return Image.open(path)


# ── Two-column sheets must be detected as 2 columns ──────────────────────────

@pytest.mark.parametrize(
    "name",
    [
        "a_espada.png",
        "magnificat.png",
        "como_a_corca_anseia.png",
        "jesus_percorria_todas_as_cidades.png",  # the 0.45-threshold case
        "siao_mae_dos_povos.png",                # the reported failing song
    ],
)
def test_two_column_sheets(name):
    layout = detect_columns(_img(name))
    assert layout.columns == 2, f"{name} should be two-column, got {layout}"
    # gutter near the middle, with real mass on both sides
    assert 0.30 <= layout.gutter_frac <= 0.70
    assert layout.left_mass > 0.18
    assert layout.right_mass > 0.18


# ── Single-column sheet (the trap) must NOT be split ─────────────────────────

def test_single_column_trap_not_split():
    # right ~40% is whitespace; a naive whitest-band splitter would cut it
    layout = detect_columns(_img("a_ti_levanto_os_meus_olhos.png"))
    assert layout.columns == 1, f"expected single column, got {layout}"


# ── split_columns crops in reading order ─────────────────────────────────────

def test_split_two_column_returns_left_then_right():
    img = _img("a_espada.png")
    layout = detect_columns(img)
    parts = split_columns(img, layout)
    assert len(parts) == 2
    left, right = parts
    # left ends at the gutter; right starts at the gutter; widths sum to full
    assert left.size[0] == layout.gutter_x
    assert right.size[0] == img.size[0] - layout.gutter_x
    assert left.size[1] == img.size[1] == right.size[1]


def test_split_single_column_returns_whole_image():
    img = _img("a_ti_levanto_os_meus_olhos.png")
    layout = detect_columns(img)
    parts = split_columns(img, layout)
    assert len(parts) == 1
    assert parts[0].size == img.size
