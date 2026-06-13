"""Column geometry for song-sheet OCR (#3).

Pure leaf: PIL + numpy only, no Tesseract, no DB, no IO beyond reading the
PIL.Image it is handed. This makes the geometry unit-testable independently of
the OCR engine.

The Resucito song sheets are mostly two-column. The previous importer ran OCR
on the full width with --psm 6, which reads left and right columns interleaved
line-by-line and SCRAMBLES verse order — the most serious ingestion defect.
This module detects whether a sheet has one or two columns and, if two, where
the gutter is, so the caller can crop and OCR each column top-to-bottom.

Thresholds were calibrated against all 466 cached sheets (see project memory
"ocr-column-split-calibration"): 342 two-column, 124 one-column; gutter median
0.481, std 0.054 — i.e. NOT reliably width/2, so content detection is required.
The single-column trap case (a sheet whose right ~40% is whitespace, e.g.
"A Ti levanto os meus olhos") is rejected by requiring real ink mass on BOTH
sides before splitting.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

# ── Calibrated thresholds (Phase 1, all 466 sheets) ─────────────────────────
_GUTTER_SEARCH_LO = 0.30   # search the central band [30%, 70%] for the gutter
_GUTTER_SEARCH_HI = 0.70
_MIN_SIDE_MASS = 0.18      # each column must carry >= this fraction of total ink
_MIN_GUTTER_EMPTINESS = 0.45  # gutter strip must be this much emptier than page
_INK_LUMINANCE_MAX = 140   # pixel darker than this (and not red) counts as ink


@dataclass(frozen=True)
class ColumnLayout:
    """Result of column detection for one sheet."""

    columns: int            # 1 or 2
    gutter_x: int           # pixel x of the gutter (only meaningful if columns == 2)
    gutter_frac: float      # gutter_x / width
    left_mass: float        # fraction of ink left of the gutter
    right_mass: float       # fraction of ink right of the gutter
    gutter_emptiness: float # 1 - (ink in gutter strip / page-average ink)


def _ink_mask(img: Image.Image) -> np.ndarray:
    """Boolean mask of 'ink' pixels: dark, and not red chord annotations.

    Red chords are excluded so they never drive the gutter detection; the
    background (white sheets, the occasional green Spanish sheet) is excluded
    via a luminance threshold.
    """
    arr = np.array(img.convert("RGB")).astype(int)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red = (r - g > 60) & (r - b > 60) & (r > 120)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    dark = luminance < _INK_LUMINANCE_MAX
    return dark & ~red


def detect_columns(img: Image.Image) -> ColumnLayout:
    """Detect 1 vs 2 columns via a vertical ink projection.

    Two-column iff: both sides carry real ink mass AND the candidate gutter is
    genuinely emptier than the rest of the page. Otherwise single-column.
    """
    mask = _ink_mask(img)
    h, w = mask.shape
    col_ink = mask.sum(axis=0).astype(float)  # ink per pixel-column

    lo, hi = int(w * _GUTTER_SEARCH_LO), int(w * _GUTTER_SEARCH_HI)
    band = col_ink[lo:hi]
    # Smooth so a single stray dark column does not win the argmin.
    k = max(5, w // 200)
    kernel = np.ones(k) / k
    smoothed = np.convolve(band, kernel, mode="same")
    gutter_x = lo + int(np.argmin(smoothed))
    gutter_frac = gutter_x / w

    total = col_ink.sum() or 1.0
    left_mass = float(col_ink[:gutter_x].sum() / total)
    right_mass = float(col_ink[gutter_x:].sum() / total)

    strip = max(8, w // 100)
    gutter_ink = float(col_ink[gutter_x - strip : gutter_x + strip].mean())
    nonzero = col_ink[col_ink > 0]
    page_ink = float(nonzero.mean()) if nonzero.size else 1.0
    gutter_emptiness = 1.0 - (gutter_ink / page_ink) if page_ink else 0.0

    is_two_col = (
        right_mass > _MIN_SIDE_MASS
        and left_mass > _MIN_SIDE_MASS
        and gutter_emptiness > _MIN_GUTTER_EMPTINESS
    )

    return ColumnLayout(
        columns=2 if is_two_col else 1,
        gutter_x=gutter_x,
        gutter_frac=round(gutter_frac, 4),
        left_mass=round(left_mass, 4),
        right_mass=round(right_mass, 4),
        gutter_emptiness=round(gutter_emptiness, 4),
    )


def split_columns(img: Image.Image, layout: ColumnLayout) -> list[Image.Image]:
    """Crop *img* into reading-order column images.

    Returns [whole_image] for single-column, [left, right] for two-column.
    """
    if layout.columns == 1:
        return [img]
    w, h = img.size
    left = img.crop((0, 0, layout.gutter_x, h))
    right = img.crop((layout.gutter_x, 0, w, h))
    return [left, right]
