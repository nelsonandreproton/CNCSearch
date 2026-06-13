"""Shared lyric-cleaning module (#1).

Applied at every write path (OCR import, docx import, CSV import, manual edit)
via the repository write boundary, so stored lyrics — and therefore the
embeddings computed from them — are free of OCR noise.

Design constraints:
  * Pure leaf: no DB / PIL / network / filesystem imports.
  * Conservative: remove only *unambiguous* noise. Never drop a real lyric
    line, a parenthetical performance marker ((BIS), (BIS A)), or a
    scripture / subtitle reference.
  * Idempotent: clean_lyrics(clean_lyrics(x)) == clean_lyrics(x).
  * No-op on already-clean, hand-typed text.

The noise patterns targeted are grounded in the real data/cncsearch.db corpus:
standalone page numbers (top/bottom of each sheet), stray single-character or
symbol-only lines left by OCR (e.g. '|', 'I', '| a'), trailing whitespace, and
runs of blank lines. Unicode is normalized to NFC.
"""

from __future__ import annotations

import re
import unicodedata

# A line consisting only of digits (optionally with surrounding punctuation/
# whitespace) is a page number. Real lyric numerals always sit inside a wider
# line of text, so a *whole-line* match is safe.
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")

# A line with no letters and no digits — only symbols/punctuation/whitespace —
# is OCR garbage (e.g. '|', '||', '. .'). Lines like '(BIS)' contain letters
# and are therefore preserved.
_SYMBOLS_ONLY_RE = re.compile(r"^[^\w]*$", re.UNICODE)

# A line that is a single ASCII letter, optionally trailed by stray symbols
# (e.g. 'I', 'E', '| a' collapses to this after symbol stripping). Single CJK
# or accented words are not targeted — only the isolated-letter OCR artifact.
_LONE_LETTER_RE = re.compile(r"^[A-Za-z]$")

# A parenthesised marker of one or more letters (e.g. '(R)', '(A)', '(BIS)') is
# a liturgical performance cue and must be preserved, even though its
# symbol-stripped core can look like an isolated letter.
_PAREN_MARKER_RE = re.compile(r"^\([A-Za-z]+\)$")


def _is_noise_line(line: str) -> bool:
    """True if a line is unambiguous OCR noise and should be dropped."""
    stripped = line.strip()
    if stripped == "":
        return False  # blank lines handled separately (run-collapsing)
    if _PAGE_NUMBER_RE.match(stripped):
        return True
    if _SYMBOLS_ONLY_RE.match(stripped):
        return True
    if _PAREN_MARKER_RE.match(stripped):
        return False  # parenthetical performance marker — preserve
    # '| a' / 'a |' style: strip non-word chars, if what remains is one letter
    # it was an isolated-letter artifact dressed up with a stray pipe.
    core = re.sub(r"[^\w]", "", stripped)
    if _LONE_LETTER_RE.match(core):
        return True
    return False


def clean_lyrics(text: str) -> str:
    """Return a cleaned copy of *text*. Never mutates the input.

    Pipeline:
      1. Normalize to Unicode NFC.
      2. Per line: strip trailing whitespace; drop unambiguous noise lines.
      3. Collapse runs of >1 blank line to a single blank line.
      4. Strip leading/trailing blank lines.
    """
    if not text:
        return text

    text = unicodedata.normalize("NFC", text)

    kept: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if _is_noise_line(line):
            continue
        kept.append(line)

    # Collapse blank-line runs.
    collapsed: list[str] = []
    blank_run = 0
    for line in kept:
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                collapsed.append(line)
        else:
            blank_run = 0
            collapsed.append(line)

    return "\n".join(collapsed).strip()
