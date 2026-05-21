import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

from llm.client import LLMConfig
from llm.wiki_engine import ingest_note, _parse_ingest_response, _update_index, _append_log


@pytest.fixture
def wiki_dir(tmp_path):
    d = tmp_path / "wiki"
    d.mkdir()
    return d


@pytest.fixture
def notes_dir(tmp_path):
    d = tmp_path / "notes"
    d.mkdir()
    return d


@pytest.fixture
def config():
    return LLMConfig(api_base="https://fake/v1", api_key="k", model="m")


def test_parse_ingest_response_extracts_summary():
    raw = """## Summary
This is about Python testing.

## Entities
- pytest
- unittest

## Connections
- Related to CI/CD
"""
    result = _parse_ingest_response(raw)
    assert "Python testing" in result.summary
    assert "pytest" in result.entities
    assert len(result.entities) == 2


def test_parse_ingest_response_handles_minimal():
    raw = "## Summary\nShort note.\n\n## Entities\n- one\n\n## Connections\n- none"
    result = _parse_ingest_response(raw)
    assert "Short note" in result.summary
    assert result.entities == ["one"]


def test_update_index_creates_file(wiki_dir):
    _update_index(wiki_dir, "test_page.md", "Test Page", "A brief description")
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "Test Page" in index
    assert "test_page.md" in index


def test_update_index_appends(wiki_dir):
    _update_index(wiki_dir, "a.md", "Page A", "First page")
    _update_index(wiki_dir, "b.md", "Page B", "Second page")
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "Page A" in index
    assert "Page B" in index


def test_update_index_replaces_existing(wiki_dir):
    _update_index(wiki_dir, "a.md", "Page A", "Old description")
    _update_index(wiki_dir, "a.md", "Page A", "New description")
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert index.count("Page A") == 1
    assert "New description" in index


def test_append_log_creates_file(wiki_dir):
    _append_log(wiki_dir, "ingest", "My Note", "Created summary_of_my_note.md")
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "My Note" in log


def test_ingest_note_creates_wiki_page(wiki_dir, notes_dir, config):
    note = notes_dir / "test.md"
    note.write_text("# Test\nSome content about AI.", encoding="utf-8")

    llm_response = """## Summary
This note discusses AI concepts.

## Entities
- AI

## Connections
- none
"""
    with patch("llm.wiki_engine.chat", return_value=llm_response):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    assert result.exists()
    assert result.parent == wiki_dir
    content = result.read_text(encoding="utf-8")
    assert "AI concepts" in content
    assert (wiki_dir / "index.md").exists()
    assert (wiki_dir / "log.md").exists()
