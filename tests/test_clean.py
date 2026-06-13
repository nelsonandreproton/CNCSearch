"""Tests for cncsearch.ingest.clean.clean_lyrics.

Cases are grounded in REAL OCR noise observed in data/cncsearch.db and
scripts/ocr_test.txt (page numbers, stray symbols/single chars, blank-line
runs, Unicode form). The cleaner must be conservative: remove only
unambiguous noise, never real lyric lines, parenthetical performance markers,
or scripture/subtitle references.
"""

from __future__ import annotations

import unicodedata

import pytest

from cncsearch.ingest.clean import clean_lyrics


# ── Page-number removal ──────────────────────────────────────────────────────

def test_standalone_page_number_line_removed():
    raw = "104\nSalmo 51 (50)\nA. MISERICÓRDIA, Ó DEUS.\n104"
    out = clean_lyrics(raw)
    assert "104" not in out.splitlines()
    # the scripture reference and lyric line survive
    assert "Salmo 51 (50)" in out
    assert "A. MISERICÓRDIA, Ó DEUS." in out


def test_multi_digit_page_numbers_removed_top_and_bottom():
    raw = "127\nHino\nA. PARA TI, MORADA SANTA\n127"
    lines = clean_lyrics(raw).splitlines()
    assert "127" not in lines
    assert "Hino" in lines  # subtitle kept


def test_number_inside_a_lyric_line_is_kept():
    # digits that are part of real text must never be touched
    raw = "Eram 5 pães e 2 peixes"
    assert clean_lyrics(raw) == "Eram 5 pães e 2 peixes"


# ── Stray symbol / single-char garbage removal ───────────────────────────────

def test_pipe_only_line_removed():
    raw = "teu sangue nos limpará.\n|\nAmen, aleluia."
    out = clean_lyrics(raw).splitlines()
    assert "|" not in out
    assert "teu sangue nos limpará." in out
    assert "Amen, aleluia." in out


def test_single_letter_garbage_line_removed():
    # isolated 'I' / 'E' OCR artifacts seen in the DB
    raw = "PARA TI, TERRA DO SALVADOR,\nI\nPEREGRINOS, CAMINHANTES,"
    out = clean_lyrics(raw).splitlines()
    assert "I" not in out
    assert "PARA TI, TERRA DO SALVADOR," in out
    assert "PEREGRINOS, CAMINHANTES," in out


def test_symbol_plus_single_char_garbage_removed():
    raw = "Kyrie eleison\n| a\nChriste eleison"
    out = clean_lyrics(raw).splitlines()
    assert "| a" not in out
    assert "Kyrie eleison" in out


# ── Things that must be KEPT (false-positive guards) ─────────────────────────

def test_bis_marker_kept():
    raw = "A. PARA TI, MORADA SANTA,\n(BIS)\nVAMOS PARA TI."
    assert "(BIS)" in clean_lyrics(raw).splitlines()


@pytest.mark.parametrize("marker", ["(R)", "(A)", "(S)", "(BIS A)"])
def test_single_letter_parenthetical_marker_kept(marker):
    # '(R)' has a symbol-stripped core of 'R' that looks like lone-letter
    # garbage, but it is a liturgical performance cue and must survive.
    raw = f"verso\n{marker}\noutro verso"
    assert marker in clean_lyrics(raw).splitlines()


def test_scripture_reference_kept():
    raw = "JESUS PERCORRIA TODAS AS CIDADES\nLucas 1, 28ss\nS. Jesus percorria"
    assert "Lucas 1, 28ss" in clean_lyrics(raw)


def test_short_real_lyric_line_kept():
    raw = "Se tu amas a Jesus\nbusca a sua paz"
    assert clean_lyrics(raw) == "Se tu amas a Jesus\nbusca a sua paz"


# ── Whitespace / blank-line handling ─────────────────────────────────────────

def test_collapses_runs_of_blank_lines():
    raw = "verso um\n\n\n\nverso dois"
    out = clean_lyrics(raw)
    assert "\n\n\n" not in out
    assert out == "verso um\n\nverso dois"


def test_trailing_whitespace_stripped_per_line():
    raw = "verso um   \nverso dois\t"
    assert clean_lyrics(raw) == "verso um\nverso dois"


def test_leading_and_trailing_blank_lines_stripped():
    raw = "\n\nverso\n\n"
    assert clean_lyrics(raw) == "verso"


# ── Unicode normalization (NFC) ──────────────────────────────────────────────

def test_output_is_nfc_normalized():
    # 'ã' as base 'a' + combining tilde (NFD) -> single composed char (NFC)
    nfd = "cora" + "c" + "̧" + "ao"  # ç decomposed
    out = clean_lyrics(nfd)
    assert out == unicodedata.normalize("NFC", out)
    assert "̧" not in out  # no lone combining marks


def test_replacement_char_not_fabricated():
    # The cleaner must NOT invent or strip the U+FFFD that already-corrupted
    # DB rows contain in a way that mangles surrounding text; it just leaves
    # the (lost) char alone. We only assert it doesn't crash and keeps text.
    raw = "M�e de Deus"
    out = clean_lyrics(raw)
    assert "de Deus" in out


# ── Contract: idempotency + no-op on clean text ──────────────────────────────

def test_idempotent():
    raw = "104\nA. MISERICÓRDIA, Ó DEUS.\n|\n\n\nverso final\n104"
    once = clean_lyrics(raw)
    assert clean_lyrics(once) == once


@pytest.mark.parametrize(
    "clean",
    [
        "Senhor, eu não sou digno\nde que entreis em minha morada",
        "A. ALELUIA, ALELUIA\nS. Louvai o Senhor",
        "Magnificat\nLucas 1, 46-55\nA minha alma engrandece o Senhor",
    ],
)
def test_noop_on_already_clean_text(clean):
    assert clean_lyrics(clean) == clean


def test_empty_string():
    assert clean_lyrics("") == ""
