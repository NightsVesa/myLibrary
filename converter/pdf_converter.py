from pathlib import Path

import pdfplumber


def pdf_to_markdown(path: Path) -> str:
    """Convert a PDF file to Markdown string using pdfplumber."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"<!-- page {i} -->\n{text.strip()}")

    return "\n\n".join(pages)
