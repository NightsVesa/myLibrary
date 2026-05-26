from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator

import logging as _logging
import queue
import re as _re
import threading

import config as app_config
from llm.client import LLMConfig, Message, chat, chat_stream
from llm.prompts import (
    INGEST_DISCUSS_SYSTEM,
    ingest_extract_system,
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


def _canonical_slug(proposed: str, existing: set[str]) -> str:
    """Return an existing slug if *proposed* differs only in punctuation/case."""
    if not proposed or proposed in existing:
        return proposed
    norm = "".join(
        ch.lower() for ch in proposed if ch.isalnum() or "一" <= ch <= "鿿"
    )
    if not norm:
        return proposed
    for es in existing:
        es_norm = "".join(
            ch.lower() for ch in es if ch.isalnum() or "一" <= ch <= "鿿"
        )
        if norm == es_norm:
            return es
    return proposed


@dataclass(frozen=True)
class ExtractResult:
    summary: str
    entities: list[dict]
    concepts: list[dict]


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
        return ExtractResult("", [], [])
    return ExtractResult(
        summary=str(data.get("summary", "")),
        entities=list(data.get("entities", [])),
        concepts=list(data.get("concepts", [])),
    )


_MANAGED_HEADINGS = frozenset({"## Sources", "## 来源", "## Related"})


def _strip_managed_sections(text: str) -> str:
    """Remove YAML frontmatter and trailing ## Sources / ## 来源 / ## Related."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                lines = lines[i + 1:]
                break
    cut_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip() in _MANAGED_HEADINGS:
            cut_idx = i
            break
    return "\n".join(lines[:cut_idx]).strip()


def _collect_sources_from_page(target: Path) -> list[str]:
    """Read existing source entries from a page's ## Sources / ## 来源."""
    if not target.exists():
        return []
    entries: list[str] = []
    in_sources = False
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped in ("## Sources", "## 来源"):
            in_sources = True
            continue
        if in_sources and stripped.startswith("## "):
            break
        if in_sources and stripped.startswith("- "):
            entries.append(stripped)
    return entries


def _build_sources_section(existing_entries: list[str], new_source: str) -> str:
    new_entry = f"- [[{new_source}]]"
    if new_entry not in existing_entries:
        existing_entries = [*existing_entries, new_entry]
    return "## Sources\n\n" + "\n".join(existing_entries) + "\n"


def _build_related_section(related: list[tuple[str, str]]) -> str:
    if not related:
        return ""
    lines = ["## Related\n"]
    for name, filename in related:
        lines.append(f"- [{name}]({filename})")
    return "\n".join(lines) + "\n"


def _merge_page(
    target: Path,
    *,
    page_title: str,
    contribution: str,
    source_filename: str,
    config: LLMConfig,
    related: list[tuple[str, str]] | None = None,
) -> None:
    existing_raw = target.read_text(encoding="utf-8")
    existing_sources = _collect_sources_from_page(target)
    prose_only = _strip_managed_sections(existing_raw)
    user_content = (
        f"Page title: {page_title}\n"
        f"New source: {source_filename}\n\n"
        f"=== Existing page content ===\n{prose_only}\n\n"
        f"=== New contribution from this source ===\n{contribution}\n"
    )
    messages = [
        Message(role="system", content=MERGE_PAGE_SYSTEM),
        Message(role="user", content=user_content),
    ]
    updated_prose = _strip_managed_sections(chat(config, messages))
    sources_section = _build_sources_section(existing_sources, source_filename)
    related_section = _build_related_section(related or [])
    full = updated_prose.rstrip() + "\n\n" + sources_section
    if related_section:
        full += "\n" + related_section
    target.write_text(full, encoding="utf-8")


def _new_page(
    target: Path,
    *,
    page_title: str,
    contribution: str,
    source_filename: str,
    page_type: str,
    related: list[tuple[str, str]] | None = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d")
    related_section = _build_related_section(related or [])
    body = (
        "---\n"
        f"type: {page_type}\n"
        f"created: {now}\n"
        f"updated: {now}\n"
        f"sources:\n  - {source_filename}\n"
        "---\n\n"
        f"# {page_title}\n\n"
        f"{contribution}\n\n"
        "## Sources\n\n"
        f"- [[{source_filename}]]\n"
    )
    if related_section:
        body += "\n" + related_section
    target.write_text(body, encoding="utf-8")


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
    return f"sources/summary_{stem}.md"


def _ensure_subdirs(wiki_dir: Path) -> None:
    for name in ("sources", "entities", "concepts"):
        (wiki_dir / name).mkdir(parents=True, exist_ok=True)


def _index_catalog_for_prompt(wiki_dir: Path) -> str:
    idx = wiki_dir / "index.md"
    if not idx.exists():
        return "(wiki is empty)"
    body = idx.read_text(encoding="utf-8")
    # Strip the relative dir prefix from filenames in links for brevity,
    # so the LLM sees  [Title](summary_x.md)  instead of  [Title](sources/summary_x.md).
    out_lines: list[str] = []
    for line in body.splitlines():
        for prefix in ("sources/", "entities/", "concepts/"):
            line = line.replace(f"]({prefix}", "](")
        out_lines.append(line)
    return "\n".join(out_lines)


def _collect_existing_slugs(wiki_dir: Path) -> tuple[set[str], set[str]]:
    entity_slugs: set[str] = set()
    concept_slugs: set[str] = set()
    for prefix, target in (("entities", entity_slugs), ("concepts", concept_slugs)):
        d = wiki_dir / prefix
        if d.exists():
            for f in d.iterdir():
                if f.suffix == ".md":
                    target.add(f.stem)
    return entity_slugs, concept_slugs


def _slug_list_for_prompt(
    entity_slugs: set[str], concept_slugs: set[str],
) -> str:
    parts: list[str] = []
    if entity_slugs:
        parts.append(f"Existing entity slugs: [{', '.join(sorted(entity_slugs))}]")
    if concept_slugs:
        parts.append(f"Existing concept slugs: [{', '.join(sorted(concept_slugs))}]")
    if parts:
        parts.append(
            "If your entity/concept matches one listed above, "
            "you MUST reuse the exact same slug."
        )
    return "\n".join(parts)


def _read_note_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return path.read_text(encoding="utf-8")
    if suffix == ".docx":
        from converter.docx_converter import docx_to_markdown
        return docx_to_markdown(path)
    if suffix == ".pdf":
        from converter.pdf_converter import pdf_to_markdown
        return pdf_to_markdown(path)
    raise ValueError(f"unsupported note format: {suffix}")


def ingest_note(
    note_path: Path,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
) -> Path:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    _ensure_subdirs(wiki)

    source_text = _read_note_source(note_path)
    title = note_path.stem.replace("_", " ")
    catalog = _index_catalog_for_prompt(wiki)
    entity_slugs_on_disk, concept_slugs_on_disk = _collect_existing_slugs(wiki)
    slug_list = _slug_list_for_prompt(entity_slugs_on_disk, concept_slugs_on_disk)

    user_parts = [
        f"Source note title: {title}",
        "",
        f"=== Source ===\n{source_text}",
        f"=== Current wiki index ===\n{catalog}",
    ]
    if slug_list:
        user_parts.append(slug_list)

    extract_messages = [
        Message(role="system", content=ingest_extract_system(app_config.WIKI_MAX_EXTRACT_ITEMS)),
        Message(role="user", content="\n\n".join(user_parts)),
    ]
    extracted = _parse_extract(chat(config, extract_messages))

    source_filename = _wiki_filename(note_path.name)
    source_page = wiki / source_filename
    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
    )

    def _resolve_slug(item: dict, prefix: str) -> str:
        existing = entity_slugs_on_disk if prefix == "entities" else concept_slugs_on_disk
        raw = _slugify(item.get("slug") or item.get("name", ""))
        slug = _canonical_slug(raw, existing)
        if slug:
            existing.add(slug)
        return slug

    # Pre-resolve all items so each page knows its peers.
    resolved: list[tuple[dict, str, str]] = []  # (item, slug, filename)
    for item in extracted.entities:
        slug = _resolve_slug(item, "entities")
        if slug:
            resolved.append((item, slug, f"entities/{slug}.md"))
    for item in extracted.concepts:
        slug = _resolve_slug(item, "concepts")
        if slug:
            resolved.append((item, slug, f"concepts/{slug}.md"))

    # Source page's ## Related lists all entities + concepts.
    source_related = [
        (it.get("name", sl), fn) for it, sl, fn in resolved
    ]
    related_section = _build_related_section(source_related)
    if related_section:
        related_section = "\n" + related_section

    source_page.write_text(
        frontmatter + f"# {title}\n\n{extracted.summary}\n" + related_section,
        encoding="utf-8",
    )

    sources, entities_idx, concepts_idx = _read_index_entries(wiki)
    sources = [e for e in sources if e.filename != source_filename]
    sources.append(IndexEntry(
        title=title,
        filename=source_filename,
        summary=(extracted.summary.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN] or "(no summary)"),
    ))

    for item, slug, filename in resolved:
        prefix = filename.split("/")[0]
        registry = entities_idx if prefix == "entities" else concepts_idx
        # Related: source page + peer items from the same batch.
        page_related: list[tuple[str, str]] = [(title, source_filename)]
        for peer_item, peer_slug, peer_fn in resolved:
            if peer_fn != filename:
                page_related.append((peer_item.get("name", peer_slug), peer_fn))
        target = wiki / filename
        try:
            if target.exists():
                _merge_page(
                    target,
                    page_title=item.get("name", slug),
                    contribution=item.get("contribution", ""),
                    source_filename=source_filename,
                    config=config,
                    related=page_related,
                )
            else:
                _new_page(
                    target,
                    page_title=item.get("name", slug),
                    contribution=item.get("contribution", ""),
                    source_filename=source_filename,
                    page_type=prefix.rstrip("s"),
                    related=page_related,
                )
        except Exception:
            _logging.exception("merge failed for %s", filename)
            continue
        registry[:] = [e for e in registry if e.filename != filename]
        registry.append(IndexEntry(
            title=item.get("name", slug),
            filename=filename,
            summary=(item.get("contribution", "").split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]),
        ))

    _write_index(wiki, sources=sources, entities=entities_idx, concepts=concepts_idx)
    _append_log(
        wiki, "ingest", title,
        f"Created {source_filename}; touched {len(extracted.entities)} entities, "
        f"{len(extracted.concepts)} concepts",
    )

    return source_page


# ─── migration ───────────────────────────────────────────────────────────

def migrate_wiki_to_subdirs(wiki_dir: Path | None = None) -> int:
    """One-shot: move flat files into subdirs, stripping prefix from filename.

    Old layout (flat):                New layout (subdirs):
      summary_*.md                  → sources/summary_*.md
      entity_<slug>.md              → entities/<slug>.md  (prefix stripped)
      concept_<slug>.md             → concepts/<slug>.md  (prefix stripped)

    Also fixes up files already moved into subdirs by a prior buggy migration
    that kept the prefix (e.g. entities/entity_openai.md → entities/openai.md).
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    if not wiki.exists():
        return 0
    _ensure_subdirs(wiki)
    moved = 0

    def _strip_prefix(prefix: str, name: str) -> str:
        return name[len(prefix):]

    # Pass 1: flat files in wiki root.
    for f in list(wiki.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        name = f.name
        if name.startswith("summary_"):
            f.rename(wiki / "sources" / name)
            moved += 1
        elif name.startswith("entity_"):
            f.rename(wiki / "entities" / _strip_prefix("entity_", name))
            moved += 1
        elif name.startswith("concept_"):
            f.rename(wiki / "concepts" / _strip_prefix("concept_", name))
            moved += 1

    # Pass 2: files already inside subdirs that still carry the prefix
    # (from a prior migration that omitted the strip step).
    for prefix, sub in (("entity_", "entities"), ("concept_", "concepts")):
        sd = wiki / sub
        if not sd.exists():
            continue
        for f in list(sd.iterdir()):
            if f.name.startswith(prefix):
                stripped = _strip_prefix(prefix, f.name)
                target = sd / stripped
                if target.exists():
                    # A newer ingest already created the correctly named file.
                    # Delete the stale prefixed copy.
                    f.unlink()
                else:
                    f.rename(target)
                moved += 1

    if moved:
        idx = wiki / "index.md"
        if idx.exists():
            text = idx.read_text(encoding="utf-8")
            # Normalize all links to the canonical subdir form.
            for prefix, sub in (
                ("entity_", "entities/"),
                ("concept_", "concepts/"),
            ):
                # Both "entities/entity_" and bare "entity_" → "entities/"
                text = text.replace(
                    f"]({sub}{prefix}", f"]({sub}"
                )
                text = text.replace(
                    f"]({prefix}", f"]({sub}"
                )
            # Sources: bare "summary_" → "sources/summary_"
            text = text.replace("](summary_", "](sources/summary_")
            idx.write_text(text, encoding="utf-8")

    # Pass 3: fix old-format links inside page content.
    for sub in ("sources", "entities", "concepts"):
        sd = wiki / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            updated = text
            for old_prefix, new_prefix in (
                ("entity_", "entities/"),
                ("concept_", "concepts/"),
            ):
                updated = updated.replace(f"]({old_prefix}", f"]({new_prefix}")
            if updated != text:
                f.write_text(updated, encoding="utf-8")
                moved += 1

    return moved


# ─── query ───────────────────────────────────────────────────────────────

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
    top_n: int | None = None,
) -> list[Path]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    idx = wiki / "index.md"
    if not idx.exists():
        return []

    effective_n = top_n if top_n is not None else app_config.WIKI_RETRIEVAL_TOP_N

    q_tokens = _tokenize(question)
    if not q_tokens:
        return []
    scored: list[tuple[float, Path]] = []

    candidates: list[Path] = []
    for pattern in ("sources/*.md", "entities/*.md", "concepts/*.md"):
        candidates.extend(wiki.glob(pattern))
    # Also check legacy flat files (pre-migration).
    for pattern in ("summary_*.md", "entity_*.md", "concept_*.md"):
        candidates.extend(wiki.glob(pattern))

    for md in candidates:
        text = md.read_text(encoding="utf-8").lower()
        hits = sum(1 for t in q_tokens if t in text)
        if hits > 0:
            scored.append((hits, md))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [path for _, path in scored[:effective_n]]


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
            _logging.exception("background ingest failed for %s", note_path)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _build_discuss_messages(source_text: str, history: list[dict[str, str]]) -> list[Message]:
    msgs = [Message(role="system", content=INGEST_DISCUSS_SYSTEM)]
    msgs.append(Message(
        role="user",
        content=f"=== Source document ===\n{source_text}\n\n"
                f"Please read this source and discuss your findings with me.",
    ))
    for entry in history:
        msgs.append(Message(role=entry["role"], content=entry["content"]))
    return msgs


def discuss_and_ingest(
    note_path: Path,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
    chat_q: queue.Queue[str],
    user_q: queue.Queue[str],
) -> Path | None:
    """Interactive ingest: discuss source with user, then extract + merge.

    Runs on a worker thread.  Sends LLM text chunks to *chat_q* and blocks
    on *user_q* for replies.  When discussion is done, runs the standard
    ingest_note pipeline.
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    source_text = _read_note_source(note_path)

    history: list[dict[str, str]] = []

    # ── Discussion loop ─────────────────────────────────────────────────
    while True:
        messages = _build_discuss_messages(source_text, history)
        full_reply: list[str] = []
        for chunk in chat_stream(config, messages):
            full_reply.append(chunk)
            chat_q.put(chunk)
        reply_text = "".join(full_reply)
        history.append({"role": "assistant", "content": reply_text})

        if "[READY_TO_INGEST]" in reply_text:
            chat_q.put("__READY__")
            # Wait for user confirmation.
            confirm = user_q.get()
            if confirm == "__CANCEL__":
                chat_q.put("__DONE__")
                return None
            break  # proceed to ingest phase

        # Wait for user reply.
        user_input = user_q.get()
        if user_input == "__CANCEL__":
            chat_q.put("__DONE__")
            return None
        history.append({"role": "user", "content": user_input})

    # ── Ingest phase ────────────────────────────────────────────────────
    chat_q.put("\n\n正在提取并写入 Wiki...\n")
    try:
        result = ingest_note(note_path, config, wiki_dir=wiki)
        chat_q.put("\n✅ Wiki 更新完成\n")
        chat_q.put("__DONE__")
        return result
    except Exception:
        _logging.exception("ingest failed for %s", note_path)
        chat_q.put("\n❌ 提取失败\n")
        chat_q.put("__ERROR__")
        return None
