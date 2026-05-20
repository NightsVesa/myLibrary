import pytest
from pathlib import Path

from search.grep_search import search_notes


@pytest.fixture
def note_dir(tmp_path):
    (tmp_path / "alpha.md").write_text("# Alpha\nThis is about apples.", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta\nThis is about bananas.", encoding="utf-8")
    (tmp_path / "gamma.md").write_text("# Gamma\nNothing relevant here.", encoding="utf-8")
    return tmp_path


def test_finds_matching_notes(note_dir):
    results = search_notes("apples", notes_dir=note_dir)
    assert len(results) == 1
    assert results[0]["file"].name == "alpha.md"


def test_returns_snippet(note_dir):
    results = search_notes("bananas", notes_dir=note_dir)
    assert "bananas" in results[0]["snippet"]


def test_no_match_returns_empty(note_dir):
    assert search_notes("zzznomatch", notes_dir=note_dir) == []


def test_case_insensitive(note_dir):
    results = search_notes("APPLES", notes_dir=note_dir)
    assert len(results) == 1


def test_returns_list_of_dicts(note_dir):
    results = search_notes("alpha", notes_dir=note_dir)
    assert isinstance(results, list)
    assert all("file" in r and "snippet" in r for r in results)
