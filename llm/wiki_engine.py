from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator

import threading

import config as app_config
from llm.client import LLMConfig, Message, chat, chat_stream
from llm.prompts import INGEST_SYSTEM, QUERY_SYSTEM, INDEX_ENTRY_TEMPLATE, LOG_ENTRY_TEMPLATE


@dataclass(frozen=True)
class IngestResult:
    summary: str
    entities: list[str]
    connections: list[str]


def _parse_ingest_response(raw: str) -> IngestResult:
    summary = ""
    entities: list[str] = []
    connections: list[str] = []
    current_section = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Summary"):
            current_section = "summary"
            continue
        elif stripped.startswith("## Entities"):
            current_section = "entities"
            continue
        elif stripped.startswith("## Connections"):
            current_section = "connections"
            continue

        if current_section == "summary":
            summary += line + "\n"
        elif current_section == "entities" and stripped.startswith("- "):
            entities.append(stripped[2:].strip())
        elif current_section == "connections" and stripped.startswith("- "):
            connections.append(stripped[2:].strip())

    return IngestResult(
        summary=summary.strip(),
        entities=entities,
        connections=connections,
    )


def _update_index(wiki_dir: Path, filename: str, title: str, summary: str) -> None:
    index_path = wiki_dir / "index.md"
    header = "# Wiki Index\n\n"
    entries: list[str] = []

    if index_path.exists():
        text = index_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("- [") and f"]({filename})" not in line:
                entries.append(line + "\n")

    one_line = summary.split("\n")[0][:80]
    entries.append(INDEX_ENTRY_TEMPLATE.format(
        title=title, filename=filename, summary=one_line,
    ))
    index_path.write_text(header + "".join(sorted(entries)), encoding="utf-8")


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

    messages = [
        Message(role="system", content=INGEST_SYSTEM),
        Message(
            role="user",
            content=f"Source note title: {title}\n\n---\n\n{source_text}",
        ),
    ]
    raw = chat(config, messages)
    result = _parse_ingest_response(raw)

    filename = _wiki_filename(note_path.name)
    page_path = wiki / filename

    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"entities: {result.entities}\n---\n\n"
    )
    page_path.write_text(
        frontmatter + f"# {title}\n\n{result.summary}\n",
        encoding="utf-8",
    )

    one_line = result.summary.split("\n")[0][:80]
    _update_index(wiki, filename, title, one_line)
    _append_log(wiki, "ingest", title, f"Created {filename}")

    return page_path


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

    q_words = set(question.lower().split())
    scored: list[tuple[float, Path]] = []

    for md in wiki.glob("summary_*.md"):
        text = md.read_text(encoding="utf-8").lower()
        hits = sum(1 for w in q_words if w in text)
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
