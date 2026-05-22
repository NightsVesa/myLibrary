from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator

import re as _re
import threading

import config as app_config
from llm.client import LLMConfig, Message, chat, chat_stream
from llm.prompts import (
    INGEST_EXTRACT_SYSTEM,
    MERGE_PAGE_SYSTEM,
    QUERY_SYSTEM,
    LOG_ENTRY_TEMPLATE,
)


def _slugify(name: str) -> str:
    text = name.strip().lower()
    out_chars: list[str] = []
    for ch in text:
        if ch.isalnum() or "一" <= ch <= "鿿":
            out_chars.append(ch)
        else:
            out_chars.append("-")
    slug = "".join(out_chars)
    slug = _re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


@dataclass(frozen=True)
class ExtractResult:
    summary: str
    entities: list[dict]
    concepts: list[dict]
    update_targets: list[str]


@dataclass(frozen=True)
class IndexEntry:
    title: str
    filename: str
    summary: str


def _parse_extract(raw: str) -> ExtractResult:
    import json
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return ExtractResult("", [], [], [])
    return ExtractResult(
        summary=str(data.get("summary", "")),
        entities=list(data.get("entities", [])),
        concepts=list(data.get("concepts", [])),
        update_targets=list(data.get("update_targets", [])),
    )


def _merge_page(
    target: Path,
    *,
    page_title: str,
    contribution: str,
    source_filename: str,
    config: LLMConfig,
) -> None:
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    user_content = (
        f"Page title: {page_title}\n"
        f"New source: {source_filename}\n\n"
        f"=== Existing page content ===\n{existing or '(empty — this is a new page)'}\n\n"
        f"=== New contribution from this source ===\n{contribution}\n"
    )
    messages = [
        Message(role="system", content=MERGE_PAGE_SYSTEM),
        Message(role="user", content=user_content),
    ]
    updated = chat(config, messages)
    target.write_text(updated.rstrip() + "\n", encoding="utf-8")


def _write_index(
    wiki_dir: Path,
    *,
    sources: list[IndexEntry],
    entities: list[IndexEntry],
    concepts: list[IndexEntry],
) -> None:
    def _section(name: str, entries: list[IndexEntry]) -> str:
        if not entries:
            return f"## {name}\n\n_(none yet)_\n\n"
        lines = [f"## {name}\n"]
        for e in sorted(entries, key=lambda x: x.title.lower()):
            lines.append(f"- [{e.title}]({e.filename}) — {e.summary}\n")
        lines.append("\n")
        return "".join(lines)

    body = (
        "# Wiki Index\n\n"
        + _section("Sources", sources)
        + _section("Entities", entities)
        + _section("Concepts", concepts)
    )
    (wiki_dir / "index.md").write_text(body, encoding="utf-8")


def _read_index_entries(
    wiki_dir: Path,
) -> tuple[list[IndexEntry], list[IndexEntry], list[IndexEntry]]:
    sources: list[IndexEntry] = []
    entities: list[IndexEntry] = []
    concepts: list[IndexEntry] = []
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return sources, entities, concepts
    current: list[IndexEntry] | None = None
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Sources"):
            current = sources
        elif line.startswith("## Entities"):
            current = entities
        elif line.startswith("## Concepts"):
            current = concepts
        elif current is not None and line.startswith("- ["):
            try:
                title = line[line.index("[") + 1:line.index("](")]
                filename = line[line.index("](") + 2:line.index(")")]
                summary = line.split("— ", 1)[1] if "— " in line else ""
                current.append(IndexEntry(title, filename, summary))
            except ValueError:
                continue
    return sources, entities, concepts


def _append_log(wiki_dir: Path, operation: str, title: str, details: str) -> None:
    log_path = wiki_dir / "log.md"
    header = "# Wiki Log\n\n"
    existing = ""
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        if existing.startswith(header):
            existing = existing[len(header):]

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = LOG_ENTRY_TEMPLATE.format(
        date=date, operation=operation, title=title, details=details,
    )
    log_path.write_text(header + entry + existing, encoding="utf-8")


def _wiki_filename(note_name: str) -> str:
    stem = Path(note_name).stem
    return f"summary_{stem}.md"


def _index_catalog_for_prompt(wiki_dir: Path) -> str:
    idx = wiki_dir / "index.md"
    if not idx.exists():
        return "(wiki is empty)"
    return idx.read_text(encoding="utf-8")


def ingest_note(
    note_path: Path,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
) -> Path:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    wiki.mkdir(parents=True, exist_ok=True)

    source_text = note_path.read_text(encoding="utf-8")
    title = note_path.stem.replace("_", " ")
    catalog = _index_catalog_for_prompt(wiki)

    extract_messages = [
        Message(role="system", content=INGEST_EXTRACT_SYSTEM),
        Message(
            role="user",
            content=(
                f"Source note title: {title}\n\n"
                f"=== Source ===\n{source_text}\n\n"
                f"=== Current wiki index ===\n{catalog}\n"
            ),
        ),
    ]
    extracted = _parse_extract(chat(config, extract_messages))

    source_filename = _wiki_filename(note_path.name)
    source_page = wiki / source_filename
    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
    )
    source_page.write_text(
        frontmatter + f"# {title}\n\n{extracted.summary}\n",
        encoding="utf-8",
    )

    sources, entities, concepts = _read_index_entries(wiki)
    sources = [e for e in sources if e.filename != source_filename]
    sources.append(IndexEntry(
        title=title,
        filename=source_filename,
        summary=(extracted.summary.split("\n")[0][:80] or "(no summary)"),
    ))

    def _merge_and_register(
        items: list[dict], prefix: str, registry: list[IndexEntry],
    ) -> None:
        for item in items:
            slug = _slugify(item.get("slug") or item.get("name", ""))
            if not slug:
                continue
            filename = f"{prefix}_{slug}.md"
            target = wiki / filename
            try:
                _merge_page(
                    target,
                    page_title=item.get("name", slug),
                    contribution=item.get("contribution", ""),
                    source_filename=source_filename,
                    config=config,
                )
            except Exception:
                continue
            registry[:] = [e for e in registry if e.filename != filename]
            registry.append(IndexEntry(
                title=item.get("name", slug),
                filename=filename,
                summary=(item.get("contribution", "").split("\n")[0][:80]),
            ))

    _merge_and_register(extracted.entities, "entity", entities)
    _merge_and_register(extracted.concepts, "concept", concepts)

    _write_index(wiki, sources=sources, entities=entities, concepts=concepts)
    _append_log(
        wiki, "ingest", title,
        f"Created {source_filename}; touched {len(extracted.entities)} entities, "
        f"{len(extracted.concepts)} concepts",
    )

    return source_page


def _tokenize(text: str) -> set[str]:
    import re
    tokens: set[str] = set()
    for word in re.findall(r'[a-zA-Z0-9]{2,}', text.lower()):
        tokens.add(word)
    cjk = [ch for ch in text if '一' <= ch <= '鿿']
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i] + cjk[i + 1])
    return tokens


def _pick_relevant_pages(
    question: str,
    *,
    wiki_dir: Path | None = None,
    top_n: int = 5,
) -> list[Path]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    index_path = wiki / "index.md"
    if not index_path.exists():
        return []

    q_tokens = _tokenize(question)
    if not q_tokens:
        return []
    scored: list[tuple[float, Path]] = []

    candidates: list[Path] = []
    for pattern in ("summary_*.md", "entity_*.md", "concept_*.md"):
        candidates.extend(wiki.glob(pattern))

    for md in candidates:
        text = md.read_text(encoding="utf-8").lower()
        hits = sum(1 for t in q_tokens if t in text)
        if hits > 0:
            scored.append((hits, md))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [path for _, path in scored[:top_n]]


def query_wiki(
    question: str,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
) -> Generator[str, None, None]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR

    pages = _pick_relevant_pages(question, wiki_dir=wiki)
    if not pages:
        yield "Wiki is empty — no pages to search."
        return

    context_parts: list[str] = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        context_parts.append(f"=== {p.name} ===\n{text}\n")
    context = "\n".join(context_parts)

    messages = [
        Message(role="system", content=QUERY_SYSTEM),
        Message(
            role="user",
            content=f"Wiki pages:\n\n{context}\n\n---\n\nQuestion: {question}",
        ),
    ]
    yield from chat_stream(config, messages)


def background_ingest(note_path: Path) -> None:
    if not app_config.LLM_API_KEY:
        return
    config = LLMConfig(
        api_base=app_config.LLM_API_BASE,
        api_key=app_config.LLM_API_KEY,
        model=app_config.LLM_MODEL,
    )

    def _worker():
        try:
            ingest_note(note_path, config)
        except Exception:
            pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
