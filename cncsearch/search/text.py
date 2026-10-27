"""Literal word/phrase search over titles and lyrics.

Complements the semantic search: finds canticos that contain specific words
or an exact phrase. Matching is case- and accent-insensitive ("coracao"
matches "Coração") and whole-word ("dia" does not match "diante"). Phrases
match across line breaks and punctuation ("Senhor, tem piedade" matches
"Senhor\\ntem piedade").

Query syntax:
    palavra outra          -> both words must appear (any order)
    "frase exacta"         -> the words must appear consecutively
    amor "pão da vida"     -> mixes both
Curly quotes (“ ” « ») are accepted, since phone keyboards insert them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Protocol

_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "«": '"', "»": '"'})
_TOKEN_RE = re.compile(r'"([^"]*)"?|(\S+)')
_CONTEXT = 60  # max chars of plain text kept around a snippet match


class _CanticoLike(Protocol):
    id: int
    title: str
    lyrics: str


@dataclass
class TextMatch:
    cantico: _CanticoLike
    title_hits: int
    lyrics_hits: int
    snippet: list[tuple[str, bool]]  # [(text, is_match), ...] of one lyrics line


def normalize(text: str) -> str:
    """Lowercase, strip accents, turn non-alphanumerics into spaces.

    Maps character by character so the result has the same length as the
    input — match offsets in the normalized text are valid in the original.
    """
    out = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[0].lower()[:1] or " "
        out.append(base if base.isalnum() else " ")
    return "".join(out)


def tokenize(query: str) -> list[tuple[str, bool]]:
    """Split a raw query into (token, was_quoted) pairs."""
    tokens = []
    for m in _TOKEN_RE.finditer(query.translate(_QUOTES)):
        if m.group(1) is not None:
            if m.group(1).strip():
                tokens.append((m.group(1), True))
        else:
            tokens.append((m.group(2), False))
    return tokens


def build_patterns(terms: Iterable[str]) -> list[re.Pattern]:
    """One regex per term (word or phrase), to run against normalized text."""
    patterns = []
    for term in terms:
        words = normalize(term).split()
        if not words:
            continue
        body = r"\s+".join(re.escape(w) for w in words)
        patterns.append(re.compile(rf"(?<![^\W_]){body}(?![^\W_])"))
    return patterns


def text_search(
    canticos: Iterable[_CanticoLike],
    terms: list[str],
    limit: int | None = None,
) -> tuple[list[TextMatch], int]:
    """Return (matches, total_count). Every term must match title or lyrics.

    Ranked by title hits, then lyrics hits, then title.
    """
    patterns = build_patterns(terms)
    if not patterns:
        return [], 0

    matches: list[TextMatch] = []
    for c in canticos:
        norm_title = normalize(c.title or "")
        norm_lyrics = normalize(c.lyrics or "")
        title_hits = lyrics_hits = 0
        for p in patterns:
            t = len(p.findall(norm_title))
            ly = len(p.findall(norm_lyrics))
            if not t and not ly:
                break
            title_hits += t
            lyrics_hits += ly
        else:
            matches.append(
                TextMatch(c, title_hits, lyrics_hits, _snippet(c.lyrics or "", norm_lyrics, patterns))
            )

    matches.sort(key=lambda m: (-m.title_hits, -m.lyrics_hits, normalize(m.cantico.title)))
    total = len(matches)
    return (matches[:limit] if limit is not None else matches), total


def _snippet(lyrics: str, norm_lyrics: str, patterns: list[re.Pattern]) -> list[tuple[str, bool]]:
    """The lyrics lines around the first match, split into plain/matched parts."""
    first = None
    for p in patterns:
        m = p.search(norm_lyrics)
        if m and (first is None or m.start() < first.start()):
            first = m
    if first is None:
        return []

    # Expand to whole lines (a phrase may span a line break).
    start = lyrics.rfind("\n", 0, first.start()) + 1
    end = lyrics.find("\n", first.end())
    end = len(lyrics) if end == -1 else end

    spans = sorted(
        (m.start(), m.end())
        for p in patterns
        for m in p.finditer(norm_lyrics, start, end)
    )
    parts: list[tuple[str, bool]] = []
    pos = start
    for s, e in spans:
        if s < pos:
            continue
        if s > pos:
            parts.append((lyrics[pos:s], False))
        parts.append((lyrics[s:e], True))
        pos = e
    if pos < end:
        parts.append((lyrics[pos:end], False))
    parts = [(re.sub(r"\s+", " ", t), hit) for t, hit in parts]
    # Keep long lines readable: trim plain text before the first / after the last match.
    if parts and not parts[0][1] and len(parts[0][0]) > _CONTEXT:
        parts[0] = ("…" + parts[0][0][-_CONTEXT:].lstrip(), False)
    if parts and not parts[-1][1] and len(parts[-1][0]) > _CONTEXT:
        parts[-1] = (parts[-1][0][:_CONTEXT].rstrip() + "…", False)
    return parts
