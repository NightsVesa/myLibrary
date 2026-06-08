from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from converter.ocr_converter import OCRUnavailableError, ocr_image


def _paragraph_image_rids(para) -> list[str]:
    rids: list[str] = []
    for run in para.runs:
        for node in run._element.iter():
            if not node.tag.endswith("}blip"):
                continue
            rid = node.get(qn("r:embed"))
            if rid:
                rids.append(rid)
    return rids


def _ocr_docx_image(doc, rid: str) -> list[str]:
    part = doc.part.related_parts.get(rid)
    if part is None:
        return []
    if not getattr(part, "content_type", "").startswith("image/"):
        return []
    try:
        with Image.open(BytesIO(part.blob)) as img:
            return ocr_image(img)
    except OCRUnavailableError:
        return []
    except Exception:
        return []


def _append_image_ocr(lines: list[str], ocr_lines: list[str]) -> None:
    cleaned = [line.strip() for line in ocr_lines if line.strip()]
    if not cleaned:
        return
    lines.append(f"> [图片文字] {cleaned[0]}")
    for line in cleaned[1:]:
        lines.append(f"> {line}")


def docx_to_markdown(path: Path) -> str:
    """Convert a DOCX file to Markdown string."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    doc = Document(str(path))
    lines: list[str] = []
    seen_rids: set[str] = set()

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
        else:
            style = para.style.name
            if style.startswith("Heading"):
                try:
                    level = int(style.split()[-1])
                except ValueError:
                    level = 1
                lines.append(f"{'#' * level} {text}")
            else:
                lines.append(text)

        for rid in _paragraph_image_rids(para):
            if rid in seen_rids:
                continue
            seen_rids.add(rid)
            _append_image_ocr(lines, _ocr_docx_image(doc, rid))

    return "\n".join(lines)
