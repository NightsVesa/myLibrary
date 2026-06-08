from __future__ import annotations

import contextlib
import os
import re
import threading
import warnings
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

from PIL import Image

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
OCR_BLOCK_START = "<!-- ocr -->"
OCR_BLOCK_END = "<!-- /ocr -->"

_ocr_instance: Any | None = None
_ocr_lock = threading.Lock()


class OCRUnavailableError(RuntimeError):
    """Raised when OCR dependencies are unavailable."""


@contextlib.contextmanager
def _quiet_paddle_init():
    """Silence known Paddle import noise without hiding real OCR errors."""
    devnull_fd = None
    saved_stderr_fd = None
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stderr_fd = os.dup(2)
        os.dup2(devnull_fd, 2)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"No ccache found\..*",
                category=UserWarning,
            )
            warnings.filterwarnings(
                "ignore",
                message=r"urllib3 .* or chardet .*doesn't match a supported version!",
                category=Warning,
            )
            yield
    finally:
        if saved_stderr_fd is not None:
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stderr_fd)
        if devnull_fd is not None:
            os.close(devnull_fd)


def is_image_file(path: Path) -> bool:
    """Return True when *path* has a supported image suffix."""
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def _get_ocr() -> Any:
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance

    with _ocr_lock:
        if _ocr_instance is not None:
            return _ocr_instance
        try:
            with _quiet_paddle_init():
                from paddleocr import PaddleOCR
        except Exception as exc:
            raise OCRUnavailableError(
                "图片 OCR 需要安装 paddleocr 和 paddlepaddle"
            ) from exc

        try:
            with _quiet_paddle_init():
                _ocr_instance = PaddleOCR(
                    use_angle_cls=True, lang="ch", show_log=False,
                )
        except (TypeError, ValueError):
            try:
                with _quiet_paddle_init():
                    _ocr_instance = PaddleOCR(lang="ch", show_log=False)
            except (TypeError, ValueError):
                with _quiet_paddle_init():
                    _ocr_instance = PaddleOCR(lang="ch")
        except Exception as exc:
            raise OCRUnavailableError(f"OCR 初始化失败: {exc}") from exc
        return _ocr_instance


def _extract_texts(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key in ("rec_texts", "texts"):
            texts = value.get(key)
            if isinstance(texts, list):
                for text in texts:
                    if isinstance(text, str):
                        yield text
        for key in ("text", "transcription"):
            text = value.get(key)
            if isinstance(text, str):
                yield text
        return

    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[0], str):
            yield value[0]
            return
        if (
            len(value) >= 2
            and isinstance(value[1], (list, tuple))
            and value[1]
            and isinstance(value[1][0], str)
        ):
            yield value[1][0]
            return
        for item in value:
            yield from _extract_texts(item)


def _format_ocr_lines(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    return "\n".join(cleaned)


def _blockquote(body: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in body.splitlines())


def ocr_image(img: Image.Image) -> list[str]:
    """Run OCR on one PIL image and return recognized text lines."""
    ocr = _get_ocr()
    try:
        import numpy as np
    except Exception as exc:
        raise OCRUnavailableError("图片 OCR 需要 numpy 支持") from exc

    rgb = img.convert("RGB")
    data = np.array(rgb)
    try:
        result = ocr.ocr(data, cls=True)
    except TypeError:
        result = ocr.ocr(data)

    lines: list[str] = []
    seen: set[str] = set()
    for text in _extract_texts(result):
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return lines


def image_to_markdown(path: Path) -> str:
    """Convert an image file to Markdown containing OCR text."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not is_image_file(path):
        raise ValueError(f"unsupported image format: {path.suffix}")

    with Image.open(path) as img:
        lines = ocr_image(img)

    body = _format_ocr_lines(lines)
    if not body:
        body = "[未识别到图片文字]"
    return f"# {path.stem}\n\n<!-- ocr-source: {path.name} -->\n\n{body}"


_IMAGE_LINK_RE = re.compile(r"!\[[^\]\n]*\]\(([^)\n]+)\)")


def _clean_markdown_image_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        target = target[1:target.index(">")]
    else:
        match = re.match(r"(.+?)\s+(['\"]).*\2\s*$", target)
        if match:
            target = match.group(1).strip()
    return unquote(target.strip())


def _is_remote_or_data_uri(target: str) -> bool:
    lower = target.lower()
    return lower.startswith(("http://", "https://", "data:"))


def _resolve_local_image(target: str, base_dir: Path) -> Path | None:
    if not target or _is_remote_or_data_uri(target):
        return None
    clean = target.split("#", 1)[0].split("?", 1)[0]
    path = Path(clean)
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if not path.exists() or not is_image_file(path):
        return None
    return path


def _has_following_ocr_block(source: str, pos: int) -> bool:
    return source[pos:].lstrip().startswith(OCR_BLOCK_START)


def enrich_markdown_images(source: str, base_dir: Path) -> str:
    """Insert OCR text after local Markdown image references."""
    base_dir = Path(base_dir)
    out: list[str] = []
    last = 0

    for match in _IMAGE_LINK_RE.finditer(source):
        out.append(source[last:match.end()])
        last = match.end()

        if _has_following_ocr_block(source, match.end()):
            continue

        target = _clean_markdown_image_target(match.group(1))
        image_path = _resolve_local_image(target, base_dir)
        if image_path is None:
            continue

        try:
            with Image.open(image_path) as img:
                body = _format_ocr_lines(ocr_image(img))
        except OCRUnavailableError:
            continue
        except Exception:
            continue

        if body:
            out.append(f"\n{OCR_BLOCK_START}\n{_blockquote(body)}\n{OCR_BLOCK_END}")

    out.append(source[last:])
    return "".join(out)
