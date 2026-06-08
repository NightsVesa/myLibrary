from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config


META_FILENAME = ".note_meta.json"
RECENT_LIMIT = 20


def _notes_dir(notes_dir: Path | None = None) -> Path:
    return notes_dir if notes_dir is not None else config.NOTES_DIR


def _meta_path(notes_dir: Path | None = None) -> Path:
    return _notes_dir(notes_dir) / META_FILENAME


def _path_key(path: Path, notes_dir: Path | None = None) -> str:
    path = Path(path).resolve()
    base = _notes_dir(notes_dir).resolve()
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _path_from_key(key: str, notes_dir: Path | None = None) -> Path:
    path = Path(key)
    if path.is_absolute():
        return path
    return _notes_dir(notes_dir) / path


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "notes": {}, "recent": []}


def _load(notes_dir: Path | None = None) -> dict[str, Any]:
    path = _meta_path(notes_dir)
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("version", 1)
    data.setdefault("notes", {})
    data.setdefault("recent", [])
    if not isinstance(data["notes"], dict):
        data["notes"] = {}
    if not isinstance(data["recent"], list):
        data["recent"] = []
    return data


def _save(data: dict[str, Any], notes_dir: Path | None = None) -> None:
    directory = _notes_dir(notes_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _meta_path(notes_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _entry(data: dict[str, Any], key: str) -> dict[str, Any]:
    notes = data.setdefault("notes", {})
    item = notes.setdefault(key, {})
    if not isinstance(item, dict):
        item = {}
        notes[key] = item
    item.setdefault("favorite", False)
    item.setdefault("tags", [])
    return item


def normalize_tags(raw: str | list[str] | tuple[str, ...]) -> list[str]:
    """Normalize user-entered tags, preserving first spelling."""
    if isinstance(raw, str):
        parts = raw.replace("，", ",").replace("、", ",").replace(" ", ",").split(",")
    else:
        parts = list(raw)
    tags: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = str(part).strip().lstrip("#").strip()
        if not tag:
            continue
        folded = tag.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        tags.append(tag)
    return tags


def get_tags(path: Path, *, notes_dir: Path | None = None) -> list[str]:
    data = _load(notes_dir)
    item = data.get("notes", {}).get(_path_key(path, notes_dir), {})
    tags = item.get("tags", []) if isinstance(item, dict) else []
    return [str(t) for t in tags if str(t).strip()]


def set_tags(path: Path, tags: str | list[str] | tuple[str, ...], *, notes_dir: Path | None = None) -> list[str]:
    data = _load(notes_dir)
    key = _path_key(path, notes_dir)
    normalized = normalize_tags(tags)
    _entry(data, key)["tags"] = normalized
    _save(data, notes_dir)
    return normalized


def is_favorite(path: Path, *, notes_dir: Path | None = None) -> bool:
    data = _load(notes_dir)
    item = data.get("notes", {}).get(_path_key(path, notes_dir), {})
    return bool(item.get("favorite")) if isinstance(item, dict) else False


def set_favorite(path: Path, value: bool, *, notes_dir: Path | None = None) -> bool:
    data = _load(notes_dir)
    key = _path_key(path, notes_dir)
    _entry(data, key)["favorite"] = bool(value)
    _save(data, notes_dir)
    return bool(value)


def toggle_favorite(path: Path, *, notes_dir: Path | None = None) -> bool:
    return set_favorite(path, not is_favorite(path, notes_dir=notes_dir), notes_dir=notes_dir)


def add_recent(path: Path, *, notes_dir: Path | None = None, limit: int = RECENT_LIMIT) -> None:
    data = _load(notes_dir)
    key = _path_key(path, notes_dir)
    recent = [k for k in data.get("recent", []) if isinstance(k, str) and k != key]
    recent.insert(0, key)
    data["recent"] = recent[:limit]
    _entry(data, key)["last_opened"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(data, notes_dir)


def list_recent(*, notes_dir: Path | None = None, limit: int = RECENT_LIMIT) -> list[Path]:
    data = _load(notes_dir)
    out: list[Path] = []
    for key in data.get("recent", []):
        if not isinstance(key, str):
            continue
        path = _path_from_key(key, notes_dir)
        if path.exists():
            out.append(path)
        if len(out) >= limit:
            break
    return out


def list_favorites(*, notes_dir: Path | None = None) -> list[Path]:
    data = _load(notes_dir)
    out: list[Path] = []
    for key, item in data.get("notes", {}).items():
        if not isinstance(item, dict) or not item.get("favorite"):
            continue
        path = _path_from_key(key, notes_dir)
        if path.exists():
            out.append(path)
    return sorted(out, key=lambda p: p.name.lower())


def all_tags(*, notes_dir: Path | None = None) -> list[str]:
    data = _load(notes_dir)
    tags: dict[str, str] = {}
    for item in data.get("notes", {}).values():
        if not isinstance(item, dict):
            continue
        for tag in item.get("tags", []):
            text = str(tag).strip()
            if text:
                tags.setdefault(text.casefold(), text)
    return sorted(tags.values(), key=str.casefold)


def list_by_tag(tag: str, *, notes_dir: Path | None = None) -> list[Path]:
    wanted = normalize_tags(tag)
    if not wanted:
        return []
    target = wanted[0].casefold()
    data = _load(notes_dir)
    out: list[Path] = []
    for key, item in data.get("notes", {}).items():
        if not isinstance(item, dict):
            continue
        tags = {str(t).casefold() for t in item.get("tags", [])}
        if target not in tags:
            continue
        path = _path_from_key(key, notes_dir)
        if path.exists():
            out.append(path)
    return sorted(out, key=lambda p: p.name.lower())
