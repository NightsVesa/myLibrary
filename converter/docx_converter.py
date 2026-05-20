from pathlib import Path

from docx import Document


def docx_to_markdown(path: Path) -> str:
    """Convert a DOCX file to Markdown string."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    doc = Document(str(path))
    lines: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        style = para.style.name
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 1
            lines.append(f"{'#' * level} {text}")
        else:
            lines.append(text)

    return "\n".join(lines)
