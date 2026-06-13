"""Column-aware OCR for song sheets (#3) with confidence flagging (#4).

Orchestrates Tesseract over the column geometry from columns.py:
  1. mask red chord annotations (so they don't pollute the lyrics);
  2. detect 1 vs 2 columns; crop into reading order;
  3. OCR each column top-to-bottom and concatenate (fixes scrambled verses);
  4. compute mean word confidence via image_to_data; flag low-confidence
     sheets for manual review.

Unlike columns.py this module is NOT a pure leaf — it requires Tesseract and
therefore runs LOCALLY only (the production container has neither Tesseract
nor the cached PNGs). It reuses clean_lyrics so OCR output gets the same
text normalisation as every other ingestion path.

Design note (#4): low-confidence tokens are NOT deleted. Silently dropping
text is worse than leaving noise — the needs_review flag is the safety net,
surfaced in the Web UI for a human to fix.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .clean import clean_lyrics
from .columns import detect_columns, split_columns

# Tesseract config: --psm 6 assumes a uniform block of text, which is correct
# AFTER we have isolated a single column.
_TESS_CONFIG = "--psm 6 --oem 3"
_TESS_LANG = "por"

# Mean confidence below this marks the sheet for manual review.
_REVIEW_CONFIDENCE = 70.0


@dataclass(frozen=True)
class OcrResult:
    lyrics: str
    columns: int
    mean_confidence: float
    needs_review: bool


def _configure_tesseract():
    """Return the pytesseract module, pointing at the Windows binary if needed."""
    import pytesseract

    win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if sys.platform == "win32" and Path(win_path).exists():
        pytesseract.pytesseract.tesseract_cmd = win_path
    return pytesseract


def _mask_red_chords(img: Image.Image) -> Image.Image:
    """White out red chord annotations so OCR only sees the lyrics."""
    arr = np.array(img.convert("RGB"))
    a = arr.astype(int)
    red = (
        (a[:, :, 0] - a[:, :, 1] > 60)
        & (a[:, :, 0] - a[:, :, 2] > 60)
        & (a[:, :, 0] > 120)
    )
    arr[red] = [255, 255, 255]
    return Image.fromarray(arr)


def _ocr_one(pytesseract, img: Image.Image) -> tuple[str, list[float]]:
    """OCR a single (already column-isolated) image.

    Returns (text, confidences). Confidences are per-word values in [0, 100]
    for non-empty tokens, from image_to_data.
    """
    text = pytesseract.image_to_string(img, lang=_TESS_LANG, config=_TESS_CONFIG)

    data = pytesseract.image_to_data(
        img, lang=_TESS_LANG, config=_TESS_CONFIG,
        output_type=pytesseract.Output.DICT,
    )
    confidences: list[float] = []
    for conf, word in zip(data["conf"], data["text"]):
        if word.strip() == "":
            continue
        try:
            c = float(conf)
        except (TypeError, ValueError):
            continue
        if c >= 0:  # tesseract uses -1 for non-text regions
            confidences.append(c)
    return text, confidences


def ocr_sheet(img: Image.Image) -> OcrResult:
    """Run column-aware OCR over a song-sheet image.

    Reads columns left-to-right, each top-to-bottom, so verse order is
    preserved. Lyrics are cleaned with clean_lyrics. Mean word confidence
    drives the needs_review flag.
    """
    pytesseract = _configure_tesseract()

    masked = _mask_red_chords(img)
    layout = detect_columns(masked)
    parts = split_columns(masked, layout)

    texts: list[str] = []
    all_conf: list[float] = []
    for part in parts:
        text, confs = _ocr_one(pytesseract, part)
        if text.strip():
            texts.append(text.strip())
        all_conf.extend(confs)

    lyrics = clean_lyrics("\n".join(texts))
    mean_conf = float(np.mean(all_conf)) if all_conf else 0.0
    needs_review = mean_conf < _REVIEW_CONFIDENCE or not lyrics.strip()

    return OcrResult(
        lyrics=lyrics,
        columns=layout.columns,
        mean_confidence=round(mean_conf, 1),
        needs_review=needs_review,
    )
