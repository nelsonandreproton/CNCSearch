"""Integration tests: cleaning is applied at the repository write boundary.

Proves that every write path (create, update, CSV import) stores cleaned
lyrics, and that update_cantico returns the cleaned text so callers embed the
same text that is stored.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from cncsearch.database.repository import Repository

# Real OCR noise: page numbers top+bottom, a stray pipe line.
NOISY = "104\nA. MISERICÓRDIA, Ó DEUS.\n|\nS. Compadecei-Vos de mim\n104"
CLEANED = "A. MISERICÓRDIA, Ó DEUS.\nS. Compadecei-Vos de mim"


@pytest.fixture()
def repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = Repository(path)
    r.init_database()
    yield r
    r.engine.dispose()
    os.unlink(path)


def test_create_cantico_stores_cleaned_lyrics(repo):
    c = repo.create_cantico("Miserere", NOISY, None)
    assert c.lyrics == CLEANED


def test_update_cantico_returns_cleaned_lyrics(repo):
    c = repo.create_cantico("Miserere", "placeholder", None)
    returned = repo.update_cantico(c.id, "Miserere", NOISY, None)
    assert returned == CLEANED
    # and what is stored matches what was returned (so embedding == storage)
    reread = repo.get_cantico(c.id)
    assert reread.lyrics == returned


def test_update_cantico_missing_returns_none(repo):
    assert repo.update_cantico(99999, "x", "y", None) is None


def test_update_cantico_invalidates_embedding(repo):
    c = repo.create_cantico("Miserere", "placeholder", None)
    repo.update_embedding(c.id, b"fake-embedding-bytes")
    repo.update_cantico(c.id, "Miserere", NOISY, None)
    reread = repo.get_cantico(c.id)
    assert reread.embedding is None


def test_csv_import_stores_cleaned_lyrics(repo):
    csv_text = "title,lyrics\n" 'Miserere,"104\\nA. MISERICÓRDIA, Ó DEUS.\\n|\\nS. Compadecei-Vos de mim\\n104"\n'
    result = repo.import_csv(csv_text)
    assert result["imported"] == 1
    c = repo.get_cantico_by_title("Miserere")
    assert c.lyrics == CLEANED
