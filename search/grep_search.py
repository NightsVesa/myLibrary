from pathlib import Path
from typing import TypedDict

import config


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
        text = md_file.read_text(encoding="utf-8")
        if lower_query not in text.lower():
            continue
        snippet = text[:120].strip()
        for line in text.splitlines():
            if lower_query in line.lower():
                snippet = line.strip()[:120]
                break
        results.append({"file": md_file, "snippet": snippet})

    return results
