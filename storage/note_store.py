import re
import shutil
from datetime import datetime
from pathlib import Path

import config


def _sanitize(title: str) -> str:
    """Replace non-alphanumeric chars (except - and _) with _."""
    return re.sub(r"[^\w\-]", "_", title).strip("_") or "note"


def save_note(
    content: str,
    title: str | None = None,
    *,
    notes_dir: Path | None = None,
) -> Path:
    """Save content as a .md file. Returns the saved Path."""
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stem = _sanitize(title) if title else datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"{stem}.md"
    counter = 1
    while path.exists():
        path = directory / f"{stem}_{counter}.md"
        counter += 1
    path.write_text(content, encoding="utf-8")
    return path


def save_raw_file(
    source: Path,
    *,
    notes_dir: Path | None = None,
) -> Path:
    """Copy *source* into notes_dir, preserving its extension with dedup."""
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stem = _sanitize(source.stem)
    suffix = source.suffix.lower()
    dest = directory / f"{stem}{suffix}"
    counter = 1
    while dest.exists():
        dest = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    shutil.copy2(source, dest)
    return dest


def list_notes(*, notes_dir: Path | None = None) -> list[Path]:
    """Return all files in notes_dir, sorted by name."""
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    return sorted(directory.glob("*.*"))


def delete_note(path: Path) -> None:
    """Delete a note file; silently ignore if not found."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
