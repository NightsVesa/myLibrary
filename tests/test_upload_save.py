from pathlib import Path

from ui import upload_tab
from ui.upload_tab import _find_uningested_notes, _read_inbox_preview, save_supported_upload


def test_save_supported_upload_converts_image_to_markdown(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(upload_tab, "image_to_markdown", lambda path: "ocr text")
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake")

    saved = save_supported_upload(image)

    assert saved.suffix == ".md"
    content = saved.read_text(encoding="utf-8")
    assert "![](.assets/shot.png)" in content
    assert "ocr text" in content


def test_save_supported_upload_saves_enriched_markdown(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(upload_tab, "_md_passthrough", lambda path: "enriched md")
    source = tmp_path / "note.md"
    source.write_text("raw md", encoding="utf-8")

    saved = save_supported_upload(source)

    assert saved.suffix == ".md"
    assert saved.read_text(encoding="utf-8") == "enriched md"


def test_save_supported_upload_keeps_docx_raw(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "NOTES_DIR", tmp_path / "notes")
    source = tmp_path / "doc.docx"
    source.write_bytes(b"docx bytes")

    saved = save_supported_upload(source)

    assert saved.suffix == ".docx"
    assert saved.read_bytes() == b"docx bytes"


def test_find_uningested_notes_includes_raw_supported_files(tmp_path, monkeypatch):
    import config

    notes_dir = tmp_path / "notes"
    wiki_dir = tmp_path / "wiki"
    sources_dir = wiki_dir / "sources"
    notes_dir.mkdir()
    sources_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "NOTES_DIR", notes_dir)
    monkeypatch.setattr(config, "WIKI_DIR", wiki_dir)

    (notes_dir / "note.md").write_text("markdown", encoding="utf-8")
    (notes_dir / "doc.docx").write_bytes(b"docx")
    (notes_dir / "paper.pdf").write_bytes(b"pdf")
    (notes_dir / ".note_meta.json").write_text("{}", encoding="utf-8")
    (sources_dir / "summary_doc.md").write_text("# Doc", encoding="utf-8")

    names = {p.name for p in _find_uningested_notes()}

    assert "note.md" in names
    assert "paper.pdf" in names
    assert "doc.docx" not in names
    assert ".note_meta.json" not in names


def test_read_inbox_preview_does_not_decode_raw_files(tmp_path):
    raw = tmp_path / "paper.pdf"
    raw.write_bytes(b"\xff\xfe\x00")
    md = tmp_path / "note.md"
    md.write_text("hello", encoding="utf-8")

    assert "原始文件: paper.pdf" in _read_inbox_preview(raw)
    assert _read_inbox_preview(md) == "hello"
