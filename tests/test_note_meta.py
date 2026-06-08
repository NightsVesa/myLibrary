from storage.note_meta import (
    add_recent,
    all_tags,
    get_tags,
    is_favorite,
    list_favorites,
    list_by_tag,
    list_recent,
    normalize_tags,
    set_favorite,
    set_tags,
    toggle_favorite,
)


def test_normalize_tags_splits_and_dedupes():
    assert normalize_tags(" ai, #Python，AI  笔记") == ["ai", "Python", "笔记"]


def test_set_and_get_tags(tmp_path):
    note = tmp_path / "a.md"
    note.write_text("a", encoding="utf-8")

    saved = set_tags(note, "one two,three", notes_dir=tmp_path)

    assert saved == ["one", "two", "three"]
    assert get_tags(note, notes_dir=tmp_path) == ["one", "two", "three"]
    assert all_tags(notes_dir=tmp_path) == ["one", "three", "two"]


def test_favorite_toggle_and_list(tmp_path):
    note = tmp_path / "a.md"
    note.write_text("a", encoding="utf-8")

    assert not is_favorite(note, notes_dir=tmp_path)
    assert toggle_favorite(note, notes_dir=tmp_path) is True
    assert is_favorite(note, notes_dir=tmp_path)
    assert list_favorites(notes_dir=tmp_path) == [note]
    assert set_favorite(note, False, notes_dir=tmp_path) is False
    assert list_favorites(notes_dir=tmp_path) == []


def test_recent_dedupes_and_skips_missing(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    add_recent(a, notes_dir=tmp_path)
    add_recent(b, notes_dir=tmp_path)
    add_recent(a, notes_dir=tmp_path)
    b.unlink()

    assert list_recent(notes_dir=tmp_path) == [a]


def test_list_by_tag(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    set_tags(a, "AI", notes_dir=tmp_path)
    set_tags(b, "other", notes_dir=tmp_path)

    assert list_by_tag("ai", notes_dir=tmp_path) == [a]


def test_bad_metadata_file_is_ignored(tmp_path):
    note = tmp_path / "a.md"
    note.write_text("a", encoding="utf-8")
    (tmp_path / ".note_meta.json").write_text("{bad json", encoding="utf-8")

    assert get_tags(note, notes_dir=tmp_path) == []
    assert not is_favorite(note, notes_dir=tmp_path)
