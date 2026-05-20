import pytest
from pathlib import Path

from converter.pdf_converter import pdf_to_markdown


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
