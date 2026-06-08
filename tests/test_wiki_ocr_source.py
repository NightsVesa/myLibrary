from pathlib import Path

from converter import ocr_converter
from llm.wiki_engine import _read_note_source


def test_read_note_source_enriches_markdown_images(tmp_path, monkeypatch):
    note = tmp_path / "note.md"
    note.write_text("raw", encoding="utf-8")

    def enrich(source, base_dir):
        assert source == "raw"
        assert base_dir == tmp_path
        return "enriched"

    monkeypatch.setattr(ocr_converter, "enrich_markdown_images", enrich)

    assert _read_note_source(note) == "enriched"


def test_read_note_source_supports_image_files(tmp_path, monkeypatch):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake")

    def convert(path: Path):
        assert path == image
        return "image markdown"

    monkeypatch.setattr(ocr_converter, "image_to_markdown", convert)

    assert _read_note_source(image) == "image markdown"
