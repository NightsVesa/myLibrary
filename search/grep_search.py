from pathlib import Path
from typing import TypedDict
import os
import time

import config

# ── Simple mtime-based file content cache ─────────────────────────────────
_cache: dict[Path, tuple[float, str]] = {}
_CACHE_MAX = 200


def _cached_read(path: Path) -> str:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    entry = _cache.get(path)
    if entry is not None and entry[0] == mtime:
        return entry[1]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[path] = (mtime, text)
    return text


class SearchResult(TypedDict):
    file: Path
    snippet: str


def search_notes(
    query: str,
    *,
    notes_dir: Path | None = None,
) -> list[SearchResult]:
    """Case-insensitive plain-text search over all .md files.

    Returns list of {file, snippet} dicts. LLM-powered search can replace
    this function later — the signature is the contract.
    """
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    results: list[SearchResult] = []
    lower_query = query.lower()

    for md_file in sorted(directory.glob("*.md")):
        text = _cached_read(md_file)
        if lower_query not in text.lower():
            continue
        snippet = text[:120].strip()
        for line in text.splitlines():
            if lower_query in line.lower():
                snippet = line.strip()[:120]
                break
        results.append({"file": md_file, "snippet": snippet})

    return results


def _tokenize(text: str) -> list[str]:
    """Tokenize text into ASCII words (>=2 chars) and CJK bigrams."""
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isascii() and ch.isalpha():
            start = i
            while i < len(text) and text[i].isascii() and text[i].isalpha():
                i += 1
            word = text[start:i].lower()
            if len(word) >= 2:
                tokens.append(word)
        elif '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            if i + 1 < len(text):
                tokens.append(text[i:i + 2])
            i += 1
        else:
            i += 1
    return tokens


def tokenize(text: str) -> set[str]:
    """Tokenize text into a set of ASCII words (>=2 chars) and CJK bigrams."""
    return set(_tokenize(text))


def search_notes_ranked(
    query: str,
    *,
    notes_dir: Path | None = None,
) -> list[SearchResult]:
    """Like search_notes(), but sorted by relevance score.

    Scoring:
      - Exact query in filename/stem: +3
      - Query in first # heading: +2
      - Per occurrence in body (capped at 10): +1
      - Token overlap bonus: +0.5 per overlapping token
      - Modified within 7 days: +0.5
    """
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    lower_query = query.lower()
    query_tokens = set(_tokenize(query))
    now = time.time()
    week = 7 * 86400
    scored: list[tuple[float, Path, str]] = []

    for md_file in sorted(directory.glob("*.md")):
        text = _cached_read(md_file)
        lower_text = text.lower()
        if lower_query not in lower_text:
            continue

        score = 0.0

        if lower_query == md_file.stem.lower():
            score += 3.0

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                if lower_query in stripped.lower():
                    score += 2.0
                break

        body_hits = lower_text.count(lower_query)
        score += min(body_hits, 10) * 1.0

        if query_tokens:
            text_tokens = set(_tokenize(text))
            overlap = query_tokens & text_tokens
            score += len(overlap) * 0.5

        try:
            mtime = os.path.getmtime(md_file)
            if now - mtime < week:
                score += 0.5
        except OSError:
            pass

        snippet = text[:120].strip()
        for line in text.splitlines():
            if lower_query in line.lower():
                snippet = line.strip()[:120]
                break

        scored.append((score, md_file, snippet))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"file": path, "snippet": snippet}
        for _score, path, snippet in scored
    ]
