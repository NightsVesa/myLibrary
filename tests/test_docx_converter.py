import pytest
from pathlib import Path
from docx import Document

from converter.docx_converter import docx_to_markdown


@pytest.fixture
def sample_docx(tmp_path):
    doc = Document()
    doc.add_heading("Test Heading", level=1)
    doc.add_paragraph("First paragraph.")
    doc.add_paragraph("Second paragraph.")
    path = tmp_path / "sample.docx"
    doc.save(str(path))
    return path


def test_extracts_heading(sample_docx):
    result = docx_to_markdown(sample_docx)
    assert "# Test Heading" in result


def test_extracts_paragraphs(sample_docx):
    result = docx_to_markdown(sample_docx)
    assert "First paragraph." in result
    assert "Second paragraph." in result


def test_returns_string(sample_docx):
    assert isinstance(docx_to_markdown(sample_docx), str)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        docx_to_markdown(Path("/nonexistent/file.docx"))
