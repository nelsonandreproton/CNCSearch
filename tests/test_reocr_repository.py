"""Integration tests for the re-OCR apply path (#3, #4) at the repository level.

Covers the needs_review migration, title-matched lyric replacement, embedding
invalidation, and the review-list query.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from cncsearch.database.repository import Repository


@pytest.fixture()
def repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = Repository(path)
    r.init_database()
    yield r
    r.engine.dispose()
    os.unlink(path)


def test_needs_review_defaults_to_zero_on_create(repo):
    c = repo.create_cantico("Sião", "letra", None)
    reread = repo.get_cantico(c.id)
    assert reread.needs_review == 0


def test_reocr_replace_by_title_matches_case_insensitively(repo):
    repo.create_cantico("Sião, mãe dos povos", "old scrambled", None, source="caminho")
    result = repo.reocr_replace_by_title("sião, MÃE dos povos", "new ordered", needs_review=False)
    assert result == "new ordered"
    reread = repo.get_cantico_by_title("Sião, mãe dos povos")
    assert reread.lyrics == "new ordered"


def test_reocr_replace_sets_needs_review_flag(repo):
    c = repo.create_cantico("Sião", "old", None)
    repo.reocr_replace_by_title("Sião", "new low-confidence text", needs_review=True)
    reread = repo.get_cantico(c.id)
    assert reread.needs_review == 1


def test_reocr_replace_invalidates_embedding(repo):
    c = repo.create_cantico("Sião", "old", None)
    repo.update_embedding(c.id, b"fake-embedding")
    repo.reocr_replace_by_title("Sião", "new", needs_review=False)
    reread = repo.get_cantico(c.id)
    assert reread.embedding is None


def test_reocr_replace_preserves_source(repo):
    repo.create_cantico("Sião", "old", None, source="caminho")
    repo.reocr_replace_by_title("Sião", "new", needs_review=False)
    reread = repo.get_cantico_by_title("Sião")
    assert reread.source == "caminho"


def test_reocr_replace_cleans_lyrics(repo):
    # page-number noise must be stripped on store, same as every write path
    repo.create_cantico("Sião", "old", None)
    repo.reocr_replace_by_title("Sião", "104\nverso bom\n104", needs_review=False)
    reread = repo.get_cantico_by_title("Sião")
    assert reread.lyrics == "verso bom"


def test_reocr_replace_unknown_title_returns_none(repo):
    assert repo.reocr_replace_by_title("Inexistente", "x", needs_review=False) is None


def test_get_canticos_needing_review(repo):
    repo.create_cantico("Bom", "ok", None)
    repo.create_cantico("Mau", "ok", None)
    repo.reocr_replace_by_title("Mau", "low conf", needs_review=True)
    review = repo.get_canticos_needing_review()
    assert [c.title for c in review] == ["Mau"]
