from pathlib import Path

import pdfplumber


class PDFConversionError(RuntimeError):
    """Raised when a PDF cannot be converted to text markdown."""


def pdf_to_markdown(path: Path) -> str:
    """Convert a PDF file to Markdown string using pdfplumber."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    pages: list[str] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                except Exception as exc:
                    raise PDFConversionError(
                        f"PDF page {i} text extraction failed for {path.name}: {exc}"
                    ) from exc
                if text.strip():
                    pages.append(f"<!-- page {i} -->\n{text.strip()}")
    except PDFConversionError:
        raise
    except Exception as exc:
        raise PDFConversionError(
            f"PDF open/read failed for {path.name}: {exc}"
        ) from exc

    return "\n\n".join(pages)
