import pytest
from pathlib import Path

from converter.pdf_converter import pdf_to_markdown
from converter.ocr_converter import OCRUnavailableError


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        pdf_to_markdown(Path("/nonexistent/file.pdf"))


def test_returns_string(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    p = tmp_path / "test.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(100, 750, "Hello PDF World")
    c.save()
    result = pdf_to_markdown(p)
    assert isinstance(result, str)
    assert "Hello PDF World" in result


class _FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeImage:
    original = object()


class _FakePage:
    def __init__(self, text):
        self._text = text
        self.to_image_called = False

    def extract_text(self):
        return self._text

    def to_image(self, resolution=200):
        self.to_image_called = True
        return _FakeImage()


def test_scanned_page_uses_ocr_when_text_is_empty(tmp_path, monkeypatch):
    from converter import pdf_converter

    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF")
    page = _FakePage("")
    monkeypatch.setattr(pdf_converter.pdfplumber, "open", lambda _path: _FakePDF([page]))
    monkeypatch.setattr(pdf_converter, "ocr_image", lambda _img: ["扫描文字"])

    result = pdf_to_markdown(p)

    assert page.to_image_called
    assert "<!-- ocr-page -->" in result
    assert "扫描文字" in result


def test_text_page_does_not_use_ocr(tmp_path, monkeypatch):
    from converter import pdf_converter

    p = tmp_path / "text.pdf"
    p.write_bytes(b"%PDF")
    page = _FakePage("normal text")
    monkeypatch.setattr(pdf_converter.pdfplumber, "open", lambda _path: _FakePDF([page]))
    monkeypatch.setattr(pdf_converter, "ocr_image", lambda _img: pytest.fail("OCR should not run"))

    result = pdf_to_markdown(p)

    assert not page.to_image_called
    assert "normal text" in result


def test_scanned_page_skips_when_ocr_unavailable(tmp_path, monkeypatch):
    from converter import pdf_converter

    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF")
    page = _FakePage("")
    monkeypatch.setattr(pdf_converter.pdfplumber, "open", lambda _path: _FakePDF([page]))

    def fail(_img):
        raise OCRUnavailableError("missing")

    monkeypatch.setattr(pdf_converter, "ocr_image", fail)

    assert pdf_to_markdown(p) == ""
