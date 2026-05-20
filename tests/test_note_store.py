import pytest
from pathlib import Path

from storage.note_store import save_note, list_notes, delete_note


@pytest.fixture
def tmp_notes(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "NOTES_DIR", tmp_path)
    return tmp_path


def test_save_note_creates_file(tmp_notes):
    path = save_note("hello world", "test-note", notes_dir=tmp_notes)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello world"


def test_save_note_sanitizes_title(tmp_notes):
    path = save_note("content", "title with spaces & symbols!", notes_dir=tmp_notes)
    assert " " not in path.name
    assert "&" not in path.name


def test_save_note_auto_title(tmp_notes):
    path = save_note("content", notes_dir=tmp_notes)
    assert path.suffix == ".md"


def test_list_notes_returns_md_files(tmp_notes):
    (tmp_notes / "a.md").write_text("a")
    (tmp_notes / "b.md").write_text("b")
    (tmp_notes / "c.txt").write_text("c")
    notes = list_notes(notes_dir=tmp_notes)
    assert len(notes) == 2
    assert all(n.suffix == ".md" for n in notes)


def test_delete_note(tmp_notes):
    p = tmp_notes / "del.md"
    p.write_text("bye")
    delete_note(p)
    assert not p.exists()


def test_delete_note_missing_is_noop(tmp_notes):
    delete_note(tmp_notes / "ghost.md")  # should not raise
