import pytest
from pathlib import Path

from storage.note_store import save_note, save_raw_file, list_notes, delete_note


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


def test_list_notes_returns_all_files(tmp_notes):
    (tmp_notes / "a.md").write_text("a")
    (tmp_notes / "b.docx").write_text("b")
    notes = list_notes(notes_dir=tmp_notes)
    names = [n.name for n in notes]
    assert "a.md" in names
    assert "b.docx" in names


def test_save_raw_file_copies_with_dedup(tmp_path):
    src_file = tmp_path / "source.docx"
    src_file.write_bytes(b"hello docx")
    out_dir = tmp_path / "notes"
    out_dir.mkdir()
    dest1 = save_raw_file(src_file, notes_dir=out_dir)
    assert dest1.exists()
    assert dest1.suffix == ".docx"
    assert dest1.read_bytes() == b"hello docx"

    # Same file again → dedup with _1 suffix
    dest2 = save_raw_file(src_file, notes_dir=out_dir)
    assert dest2 != dest1
    assert dest2.exists()
    assert "_1.docx" in dest2.name


def test_save_raw_file_sanitizes_stem(tmp_path):
    src_file = tmp_path / "bad name!.docx"
    src_file.write_bytes(b"x")
    out_dir = tmp_path / "notes"
    out_dir.mkdir()
    dest = save_raw_file(src_file, notes_dir=out_dir)
    assert " " not in dest.name
    assert "!" not in dest.name


def test_delete_note(tmp_notes):
    p = tmp_notes / "del.md"
    p.write_text("bye")
    delete_note(p)
    assert not p.exists()


def test_delete_note_missing_is_noop(tmp_notes):
    delete_note(tmp_notes / "ghost.md")  # should not raise
