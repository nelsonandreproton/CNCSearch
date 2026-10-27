"""Literal word/phrase search (cncsearch/search/text.py)."""

from __future__ import annotations

from dataclasses import dataclass

from cncsearch.search.text import normalize, text_search, tokenize


@dataclass
class C:
    id: int
    title: str
    lyrics: str


CANTICOS = [
    C(1, "Eu sou o pão da vida", "Eu sou o pão da vida,\nquem vem a mim não terá fome."),
    C(2, "Coração de Jesus", "O meu coração exulta\nno Senhor, tem piedade."),
    C(3, "Diante do trono", "Todo o dia te louvarei\ndiante do teu altar."),
    C(4, "Amor", "O amor é paciente, o pão partilhado\nda vida eterna."),
]


def titles(matches):
    return [m.cantico.title for m in matches]


def test_normalize_keeps_length_and_strips_accents():
    s = "Coração, ÉS tu!"
    assert normalize(s) == "coracao  es tu "
    assert len(normalize(s)) == len(s)


def test_tokenize_quotes_and_curly_quotes():
    assert tokenize('amor "pão da vida"') == [("amor", False), ("pão da vida", True)]
    assert tokenize("“pão da vida” x") == [("pão da vida", True), ("x", False)]
    assert tokenize('"sem fecho') == [("sem fecho", True)]


def test_accent_and_case_insensitive():
    matches, total = text_search(CANTICOS, ["CORACAO"])
    assert titles(matches) == ["Coração de Jesus"] and total == 1


def test_whole_word_only():
    matches, _ = text_search(CANTICOS, ["dia"])
    assert titles(matches) == ["Diante do trono"]  # via "Todo o dia", not "Diante"
    matches, _ = text_search(CANTICOS, ["diant"])
    assert matches == []


def test_all_words_required():
    matches, _ = text_search(CANTICOS, ["pão", "fome"])
    assert titles(matches) == ["Eu sou o pão da vida"]


def test_phrase_is_consecutive_and_crosses_lines_and_punctuation():
    matches, _ = text_search(CANTICOS, ["pão da vida"])
    assert titles(matches) == ["Eu sou o pão da vida"]  # cantico 4 has "pão partilhado da vida"
    matches, _ = text_search(CANTICOS, ["exulta no senhor tem piedade"])
    assert titles(matches) == ["Coração de Jesus"]


def test_title_hits_rank_first_and_limit_reports_total():
    matches, total = text_search(CANTICOS, ["amor"])
    assert titles(matches) == ["Amor"]
    matches, total = text_search(CANTICOS, ["o"], limit=2)
    assert total == 4 and len(matches) == 2


def test_snippet_highlights_original_text():
    (m,), _ = text_search(CANTICOS, ["coracao exulta"])
    assert m.snippet == [("O meu ", False), ("coração exulta", True)]
    (m,), _ = text_search(CANTICOS, ["exulta no senhor"])
    assert m.snippet == [
        ("O meu coração ", False),
        ("exulta no Senhor", True),
        (", tem piedade.", False),
    ]


def test_empty_terms():
    assert text_search(CANTICOS, ["", "  ", "!!"]) == ([], 0)
