from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator

import logging as _logging
import posixpath
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
    QUERY_TYPE_INSTRUCTIONS,
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


@dataclass(frozen=True)
class IndexCatalog:
    sources: list[IndexEntry]
    entities: list[IndexEntry]
    concepts: list[IndexEntry]
    synthesis: list[IndexEntry]


@dataclass(frozen=True)
class QueryCandidate:
    path: str
    title: str
    kind: str
    reason: str
    score: float
    source: str


@dataclass(frozen=True)
class QueryResultMeta:
    question: str
    answer_type: str
    used_pages: list[str]
    raw_sources: list[str]
    suggested_save_title: str


@dataclass(frozen=True)
class IngestCandidate:
    kind: str          # "entity" | "concept"
    path: str          # e.g. "entities/openai.md"
    title: str
    reason: str
    confidence: float  # 0.0–1.0
    default_selected: bool
    action_hint: str   # "create" | "update" | "light_link"


@dataclass(frozen=True)
class IngestWriteAction:
    action: str        # "create" | "update" | "light_link" | "skip" | "source_check"
    path: str          # e.g. "entities/openai.md"
    title: str
    reason: str
    contribution: str  # text to merge into the page


@dataclass(frozen=True)
class IngestWritePlan:
    source_summary: str
    source_filename: str
    actions: list[IngestWriteAction]
    user_focus: list[str]                  # paths the user selected for deep review
    referenced_source_summaries: list[str] # paths of source summaries read during deep review


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def _parse_extract(raw: str) -> ExtractResult:
    import json
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return ExtractResult("", [], [])
    return ExtractResult(
        summary=str(data.get("summary", "")),
        entities=list(data.get("entities", [])),
        concepts=list(data.get("concepts", [])),
    )


def _parse_candidates(raw: str) -> tuple[str, list[IngestCandidate]]:
    import json
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return "", []
    summary = str(data.get("summary", ""))
    candidates: list[IngestCandidate] = []
    for item in data.get("candidates", []):
        kind = str(item.get("kind", "entity"))
        slug = str(item.get("slug", ""))
        prefix = "entities" if kind == "entity" else "concepts"
        candidates.append(IngestCandidate(
            kind=kind,
            path=f"{prefix}/{slug}.md" if slug else "",
            title=str(item.get("name", slug)),
            reason=str(item.get("reason", "")),
            confidence=float(item.get("confidence", 0.5)),
            default_selected=float(item.get("confidence", 0.5)) >= 0.3,
            action_hint=str(item.get("action_hint", "create")),
        ))
    return summary, candidates


def _parse_write_plan(raw: str) -> list[IngestWriteAction]:
    import json
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    actions: list[IngestWriteAction] = []
    for item in data.get("actions", []):
        actions.append(IngestWriteAction(
            action=str(item.get("action", "skip")),
            path=str(item.get("path", "")),
            title=str(item.get("title", "")),
            reason=str(item.get("reason", "")),
            contribution=str(item.get("contribution", "")),
        ))
    return actions


def _execute_write_plan(
    plan: IngestWritePlan,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
    related_map: dict[str, list[tuple[str, str]]] | None = None,
) -> tuple[int, int, list[str]]:
    """Execute all actions in a write plan.

    Returns (ok_count, fail_count, flagged_paths).
    flagged_paths contains paths of source_check actions.
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    _ensure_subdirs(wiki)

    sources_idx, entities_idx, concepts_idx = _read_index_entries(wiki)
    ok, failed = 0, 0
    flagged: list[str] = []

    for act in plan.actions:
        if act.action == "skip":
            continue

        target = wiki / act.path
        prefix = act.path.split("/")[0]
        page_type = prefix[:-1] if prefix.endswith("s") else prefix
        registry = entities_idx if prefix == "entities" else concepts_idx
        page_related = related_map.get(act.path) if related_map else None

        try:
            if act.action == "source_check":
                # Add source link but don't modify prose; flag for manual review
                if target.exists():
                    existing_sources = _collect_sources_from_page(target)
                    sources_section = _build_sources_section(
                        existing_sources, plan.source_filename,
                        from_filename=act.path,
                    )
                    text = target.read_text(encoding="utf-8")
                    lines = text.splitlines()
                    cut_idx = len(lines)
                    for i, line in enumerate(lines):
                        if line.strip() in _MANAGED_HEADINGS:
                            cut_idx = i
                            break
                    prose = "\n".join(lines[:cut_idx]).rstrip()
                    target.write_text(
                        prose + "\n\n" + sources_section, encoding="utf-8",
                    )
                flagged.append(f"{act.title} ({act.path}): {act.reason}")
                continue

            if act.action == "create":
                _new_page(
                    target,
                    page_title=act.title,
                    contribution=act.contribution,
                    source_filename=plan.source_filename,
                    page_type=page_type,
                    related=page_related,
                )
                ok += 1
            elif act.action == "update":
                if not target.exists():
                    _new_page(
                        target,
                        page_title=act.title,
                        contribution=act.contribution,
                        source_filename=plan.source_filename,
                        page_type=page_type,
                        related=page_related,
                    )
                else:
                    _merge_page(
                        target,
                        page_title=act.title,
                        contribution=act.contribution,
                        source_filename=plan.source_filename,
                        config=config,
                        related=page_related,
                    )
                ok += 1
            elif act.action == "light_link":
                if target.exists():
                    existing_sources = _collect_sources_from_page(target)
                    sources_section = _build_sources_section(
                        existing_sources, plan.source_filename,
                        from_filename=act.path,
                    )
                    text = target.read_text(encoding="utf-8")
                    lines = text.splitlines()
                    cut_idx = len(lines)
                    for i, line in enumerate(lines):
                        if line.strip() in _MANAGED_HEADINGS:
                            cut_idx = i
                            break
                    prose = "\n".join(lines[:cut_idx]).rstrip()
                    target.write_text(
                        prose + "\n\n" + sources_section, encoding="utf-8",
                    )
                ok += 1
            else:
                continue

            registry[:] = [e for e in registry if e.filename != act.path]
            registry.append(IndexEntry(
                title=act.title,
                filename=act.path,
                summary=(
                    act.contribution.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]
                    if act.contribution else "(linked)"
                ),
            ))
        except Exception:
            _logging.exception("write plan action failed for %s", act.path)
            failed += 1

    _write_index(wiki, sources=sources_idx, entities=entities_idx, concepts=concepts_idx)

    action_summary = ", ".join(
        f"{a.action} {a.path}" for a in plan.actions if a.action != "skip"
    )
    flag_summary = ""
    if flagged:
        flag_summary = f"; source_check: {', '.join(flagged)}"
    _append_log(
        wiki, "ingest", plan.source_filename,
        f"Executed write plan: {action_summary or '(no actions)'}; "
        f"ok={ok}, failed={failed}{flag_summary}",
    )
    return ok, failed, flagged


def _build_ingest_extract_messages(
    source_text: str,
    source_title: str,
    history: list[dict[str, str]],
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
) -> list[Message]:
    from llm.prompts import INGEST_CANDIDATE_SYSTEM
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR

    catalog = _index_catalog_for_prompt(wiki)
    entity_slugs, concept_slugs = _collect_existing_slugs(wiki)
    slug_list = _slug_list_for_prompt(entity_slugs, concept_slugs)

    user_parts = [
        f"Source note title: {source_title}",
        "",
        f"=== Source ===\n{source_text}",
        f"=== Current wiki index ===\n{catalog}",
    ]
    if slug_list:
        user_parts.append(slug_list)
    if history:
        chat_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
            for h in history
        )
        user_parts.append(f"=== Discussion context ===\n{chat_text}")

    return [
        Message(role="system", content=INGEST_CANDIDATE_SYSTEM),
        Message(role="user", content="\n\n".join(user_parts)),
    ]


def _build_write_plan(
    source_summary: str,
    candidates: list[IngestCandidate],
    selected_paths: list[str],
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
    extra_source_summaries: list[tuple[str, str]] | None = None,
    user_requested_source_read: bool = False,
) -> list[list[Message]]:
    """Build LLM messages for write plan generation.

    Returns a list of message batches. When all candidates fit within the
    character budget, a single batch is returned. When the budget is exceeded,
    candidates are split into multiple batches so each gets a separate Plan
    Review LLM call.
    """
    from llm.prompts import INGEST_PLAN_SYSTEM
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    budget = app_config.WIKI_DEEP_READ_MAX_CHARS
    max_deep = app_config.WIKI_DEEP_READ_MAX

    # ── Determine which pages need source summary reads ───────────────
    auto_source_summaries: list[tuple[str, str]] = []
    if not extra_source_summaries:
        extra_source_summaries = []

    deep_read_count = 0
    for path in selected_paths:
        if deep_read_count >= max_deep:
            break
        target = wiki / path
        if not target.exists():
            deep_read_count += 1
            continue
        content = target.read_text(encoding="utf-8")
        prose = _strip_managed_sections(content)
        is_shallow = len(prose.strip()) < 200
        needs_source_read = (
            is_shallow
            or user_requested_source_read
        )
        if needs_source_read:
            auto_source_summaries.extend(
                _collect_related_source_summaries(target, wiki_dir=wiki)
            )
        deep_read_count += 1

    all_extra = extra_source_summaries + auto_source_summaries
    # Deduplicate by path
    seen_paths: set[str] = set()
    deduped_extra: list[tuple[str, str]] = []
    for path, content in all_extra:
        if path not in seen_paths:
            seen_paths.add(path)
            deduped_extra.append((path, content))

    # ── Build candidate groups respecting budget ──────────────────────
    header = f"=== Source summary ===\n{source_summary}"
    header_len = len(header)

    # Group candidates into batches that fit within budget
    batches: list[list[IngestCandidate]] = []
    current_batch: list[IngestCandidate] = []
    current_chars = header_len

    deep_count = 0
    for cand in candidates:
        page = wiki / cand.path
        page_chars = 0
        if cand.path in selected_paths and page.exists() and deep_count < max_deep:
            page_chars = len(page.read_text(encoding="utf-8"))
            deep_count += 1

        if current_batch and current_chars + page_chars > budget:
            batches.append(current_batch)
            current_batch = [cand]
            current_chars = header_len + page_chars
        else:
            current_batch.append(cand)
            current_chars += page_chars

    if current_batch:
        batches.append(current_batch)

    # ── Build messages for each batch ─────────────────────────────────
    result: list[list[Message]] = []
    deep_count = 0
    for batch in batches:
        parts = [header]
        total_chars = header_len

        parts.append("\n=== Candidate pages (deep read) ===")
        for cand in batch:
            if cand.path not in selected_paths:
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — NOT selected, "
                    f"action_hint={cand.action_hint}"
                )
                continue
            page = wiki / cand.path
            if page.exists() and deep_count < max_deep and total_chars < budget:
                page_content = page.read_text(encoding="utf-8")
                if total_chars + len(page_content) > budget:
                    page_content = (
                        page_content[:budget - total_chars] + "\n... (truncated)"
                    )
                total_chars += len(page_content)
                deep_count += 1
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — existing page:\n{page_content}"
                )
            elif page.exists():
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — exists but budget exceeded, "
                    f"action_hint={cand.action_hint}"
                )
            else:
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — NEW page, "
                    f"action_hint={cand.action_hint}"
                )
                deep_count += 1

        if deduped_extra:
            parts.append("\n=== Related source summaries ===")
            for spath, scontent in deduped_extra:
                if total_chars + len(scontent) > budget:
                    break
                parts.append(f"\n[{spath}]:\n{scontent}")
                total_chars += len(scontent)

        result.append([
            Message(role="system", content=INGEST_PLAN_SYSTEM),
            Message(role="user", content="\n".join(parts)),
        ])

    return result if result else [[
        Message(role="system", content=INGEST_PLAN_SYSTEM),
        Message(role="user", content=header + "\n\n(no candidates)"),
    ]]


_ACTION_LABELS = {
    "create": "新增",
    "update": "修改",
    "light_link": "轻关联",
    "skip": "跳过",
    "source_check": "需核查",
}


def _format_candidates_for_display(candidates: list[IngestCandidate]) -> str:
    lines = ["\n📋 候选页面：\n"]
    for i, c in enumerate(candidates, 1):
        sel = "✓" if c.default_selected else " "
        kind_label = "实体" if c.kind == "entity" else "概念"
        hint = _ACTION_LABELS.get(c.action_hint, c.action_hint)
        lines.append(
            f"  {i}. [{sel}] {c.title} ({kind_label}, {hint}) — {c.reason}"
        )
    lines.append("")
    lines.append("请回复选择（默认 / 全部 / 编号如 1,3,5 / 排除如 -2,-4）：")
    lines.append('（追加 +源 可要求读取关联源摘要，如"默认+源"）')
    return "\n".join(lines)


def _format_plan_for_display(actions: list[IngestWriteAction]) -> str:
    lines = ["\n📝 写入计划：\n"]
    for a in actions:
        label = _ACTION_LABELS.get(a.action, a.action)
        lines.append(f"  [{label}] {a.title} ({a.path})")
        if a.reason:
            lines.append(f"         原因: {a.reason}")
    lines.append("")
    return "\n".join(lines)


def _parse_user_selection(
    reply: str, candidates: list[IngestCandidate],
) -> tuple[set[int], bool]:
    """Parse user selection reply.

    Returns (selected_indices_0based, wants_source_read).
    User can append "+源" or "+source" to request source summary reads.
    """
    text = reply.strip()
    wants_sources = False
    for suffix in ("+源", "+source", "+src"):
        if suffix in text.lower():
            wants_sources = True
            text = text.replace(suffix, "").replace(suffix.upper(), "").strip()
            break

    text = text.lower()
    n = len(candidates)

    if text in ("全部", "all", "*"):
        return set(range(n)), wants_sources

    if text in ("默认", "default", "", "ok", "好"):
        return {i for i, c in enumerate(candidates) if c.default_selected}, wants_sources

    if text.startswith("-") and (
        "," in text or (len(text) > 1 and text[1:].isdigit())
    ):
        excludes = set()
        for part in text.split(","):
            part = part.strip()
            if part.startswith("-") and part[1:].isdigit():
                excludes.add(int(part[1:]) - 1)
        defaults = {i for i, c in enumerate(candidates) if c.default_selected}
        return defaults - excludes, wants_sources

    selected = set()
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < n:
                selected.add(idx)

    if not selected:
        selected = {i for i, c in enumerate(candidates) if c.default_selected}
    return selected, wants_sources


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


def _build_sources_section(
    existing_entries: list[str],
    new_source: str,
    *,
    from_filename: str | None = None,
) -> str:
    rel = _relative_wiki_link(new_source, from_filename)
    new_entry = f"- [[{rel}]]"
    if new_entry not in existing_entries:
        existing_entries = [*existing_entries, new_entry]
    return "## Sources\n\n" + "\n".join(existing_entries) + "\n"


def _collect_related_source_summaries(
    target: Path,
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
) -> list[tuple[str, str]]:
    """Read source summary content linked from a page's ## Sources section.

    Returns list of (path_str, content) for each resolvable source summary.
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    entries = _collect_sources_from_page(target)
    results: list[tuple[str, str]] = []
    page_dir = target.parent.relative_to(wiki) if target.is_relative_to(wiki) else target.parent
    for entry in entries:
        match = _re.search(r"\[\[([^\]]+)\]\]", entry)
        if not match:
            continue
        ref = match.group(1)
        # Resolve relative to page directory first, then fall back to wiki root
        resolved = posixpath.normpath(posixpath.join(str(page_dir), ref))
        source_path = wiki / resolved
        if not source_path.exists():
            # Try as absolute from wiki root (legacy format)
            source_path = wiki / ref
        if source_path.exists():
            try:
                rel_to_wiki = source_path.resolve().relative_to(wiki.resolve())
                results.append((str(rel_to_wiki).replace("\\", "/"), source_path.read_text(encoding="utf-8")))
            except ValueError:
                pass
    return results


def _relative_wiki_link(filename: str, from_filename: str | None) -> str:
    if not from_filename:
        return filename
    rel = posixpath.relpath(filename, posixpath.dirname(from_filename) or ".")
    return rel.replace("\\", "/")


def _canonical_wiki_target(target: str, from_filename: str) -> str | None:
    if (
        not target
        or "://" in target
        or target.startswith(("#", "/", "mailto:"))
    ):
        return None
    if target.startswith("entity_"):
        return f"entities/{target[len('entity_'):]}"
    if target.startswith("concept_"):
        return f"concepts/{target[len('concept_'):]}"
    if target.startswith("summary_"):
        return f"sources/{target}"
    if target.split("/", 1)[0] in {"sources", "entities", "concepts", "synthesis"}:
        return target
    normalized = posixpath.normpath(
        posixpath.join(posixpath.dirname(from_filename), target)
    )
    if normalized.split("/", 1)[0] in {"sources", "entities", "concepts", "synthesis"}:
        return normalized
    return None


def _rewrite_wiki_links_for_page(text: str, from_filename: str) -> str:
    def repl(match: _re.Match[str]) -> str:
        target = match.group(1)
        canonical = _canonical_wiki_target(target, from_filename)
        if canonical is None:
            return match.group(0)
        return f"]({_relative_wiki_link(canonical, from_filename)})"

    return _re.sub(r"\]\(([^)]+)\)", repl, text)


def _build_related_section(
    related: list[tuple[str, str]],
    *,
    from_filename: str | None = None,
) -> str:
    if not related:
        return ""
    lines = ["## Related\n"]
    for name, filename in related:
        lines.append(f"- [{name}]({_relative_wiki_link(filename, from_filename)})")
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
    target_filename = f"{target.parent.name}/{target.name}"
    sources_section = _build_sources_section(
        existing_sources, source_filename, from_filename=target_filename,
    )
    related_section = _build_related_section(
        related or [], from_filename=target_filename,
    )
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
    target_filename = f"{target.parent.name}/{target.name}"
    related_section = _build_related_section(
        related or [], from_filename=target_filename,
    )
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
        f"- [[{_relative_wiki_link(source_filename, target_filename)}]]\n"
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
    synthesis: list[IndexEntry] | None = None,
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
        + (_section("Synthesis", synthesis) if synthesis is not None else "")
    )
    (wiki_dir / "index.md").write_text(body, encoding="utf-8")


def _read_index_catalog(wiki_dir: Path) -> IndexCatalog:
    sources: list[IndexEntry] = []
    entities: list[IndexEntry] = []
    concepts: list[IndexEntry] = []
    synthesis: list[IndexEntry] = []
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return IndexCatalog(sources, entities, concepts, synthesis)
    current: list[IndexEntry] | None = None
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Sources"):
            current = sources
        elif line.startswith("## Entities"):
            current = entities
        elif line.startswith("## Concepts"):
            current = concepts
        elif line.startswith("## Synthesis"):
            current = synthesis
        elif current is not None and line.startswith("- ["):
            try:
                title = line[line.index("[") + 1:line.index("](")]
                filename = line[line.index("](") + 2:line.index(")")]
                summary = line.split("— ", 1)[1] if "— " in line else ""
                current.append(IndexEntry(title, filename, summary))
            except ValueError:
                continue
    return IndexCatalog(sources, entities, concepts, synthesis)


def _read_index_entries(
    wiki_dir: Path,
) -> tuple[list[IndexEntry], list[IndexEntry], list[IndexEntry]]:
    catalog = _read_index_catalog(wiki_dir)
    return catalog.sources, catalog.entities, catalog.concepts
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
    for name in ("sources", "entities", "concepts", "synthesis"):
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
        for prefix in ("sources/", "entities/", "concepts/", "synthesis/"):
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


def _pick_index_candidates(
    source_text: str,
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
    top_n: int | None = None,
    chat_context: str = "",
) -> list[IngestCandidate]:
    """Score existing wiki pages by title + summary only (no page file IO). Ranked candidates."""
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    effective_n = top_n if top_n is not None else app_config.WIKI_CANDIDATE_TOP_N

    sources_idx, entities_idx, concepts_idx = _read_index_entries(wiki)
    if not entities_idx and not concepts_idx:
        return []

    combined_text = source_text + "\n" + chat_context
    q_tokens = _tokenize(combined_text)
    if not q_tokens:
        return []

    scored: list[tuple[float, IndexEntry, str]] = []

    for entry, kind in (
        *((e, "entity") for e in entities_idx),
        *((e, "concept") for e in concepts_idx),
    ):
        hits = sum(
            1 for t in q_tokens
            if t in entry.title.lower() or t in entry.summary.lower()
        )
        if hits > 0:
            scored.append((float(hits), entry, kind))

    scored.sort(key=lambda t: t[0], reverse=True)
    max_score = scored[0][0] if scored else 1.0

    candidates: list[IngestCandidate] = []
    for score, entry, kind in scored[:effective_n]:
        confidence = round(min(score / max_score, 1.0), 2)
        candidates.append(IngestCandidate(
            kind=kind,
            path=entry.filename,
            title=entry.title,
            reason=f"Keyword overlap score {score:.0f}",
            confidence=confidence,
            default_selected=confidence >= 0.3,
            action_hint="update",
        ))

    return candidates


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
    related_section = _build_related_section(
        source_related, from_filename=source_filename,
    )
    if related_section:
        related_section = "\n" + related_section

    source_page.write_text(
        frontmatter + f"# {title}\n\n{extracted.summary}\n" + related_section,
        encoding="utf-8",
    )

    # After source page write, persist the source index entry before
    # _execute_write_plan reads and rewrites index.md.
    sources, entities_idx, concepts_idx = _read_index_entries(wiki)
    sources = [e for e in sources if e.filename != source_filename]
    sources.append(IndexEntry(
        title=title,
        filename=source_filename,
        summary=(
            extracted.summary.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]
            or "(no summary)"
        ),
    ))
    _write_index(wiki, sources=sources, entities=entities_idx, concepts=concepts_idx)

    # Build related_map and write actions from extracted entities/concepts
    related_map: dict[str, list[tuple[str, str]]] = {}
    actions: list[IngestWriteAction] = []
    for item, slug, filename in resolved:
        target = wiki / filename
        page_related: list[tuple[str, str]] = [(title, source_filename)]
        for peer_item, peer_slug, peer_fn in resolved:
            if peer_fn != filename:
                page_related.append((peer_item.get("name", peer_slug), peer_fn))
        related_map[filename] = page_related
        actions.append(IngestWriteAction(
            action="update" if target.exists() else "create",
            path=filename,
            title=item.get("name", slug),
            reason="extracted from source",
            contribution=item.get("contribution", ""),
        ))

    if actions:
        plan = IngestWritePlan(
            source_summary=extracted.summary,
            source_filename=source_filename,
            actions=actions,
            user_focus=[],
            referenced_source_summaries=[],
        )
        _execute_write_plan(plan, config, wiki_dir=wiki, related_map=related_map)

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
            updated = _rewrite_wiki_links_for_page(text, f"{sub}/{f.name}")
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


def _kind_for_path(path: str) -> str:
    prefix = path.split("/", 1)[0]
    return {
        "sources": "source",
        "entities": "entity",
        "concepts": "concept",
        "synthesis": "synthesis",
    }.get(prefix, "wiki")


def _query_kind_priority(kind: str) -> int:
    return {
        "entity": 0,
        "concept": 1,
        "synthesis": 2,
        "source": 3,
    }.get(kind, 4)


def _pick_query_index_candidates(
    question: str,
    *,
    wiki_dir: Path | None = None,
    top_n: int | None = None,
) -> list[QueryCandidate]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    effective_n = top_n if top_n is not None else app_config.WIKI_QUERY_TOP_N
    catalog = _read_index_catalog(wiki)
    q_tokens = _tokenize(question)
    if not q_tokens:
        return []

    scored: list[QueryCandidate] = []
    groups = (
        ("entity", catalog.entities),
        ("concept", catalog.concepts),
        ("synthesis", catalog.synthesis),
        ("source", catalog.sources),
    )
    for kind, entries in groups:
        for entry in entries:
            title = entry.title.lower()
            filename = entry.filename.lower()
            summary = entry.summary.lower()
            title_hits = sum(1 for t in q_tokens if t in title)
            path_hits = sum(1 for t in q_tokens if t in filename)
            summary_hits = sum(1 for t in q_tokens if t in summary)
            score = title_hits * 3 + path_hits * 2 + summary_hits
            if score <= 0:
                continue
            scored.append(QueryCandidate(
                path=entry.filename,
                title=entry.title,
                kind=kind,
                reason=f"index match score {score}",
                score=float(score),
                source="index",
            ))

    scored.sort(key=lambda c: (-c.score, _query_kind_priority(c.kind), c.title.lower()))
    return scored[:effective_n]


def _candidate_from_path(path: Path, wiki: Path, *, source: str) -> QueryCandidate:
    try:
        rel = path.resolve().relative_to(wiki.resolve())
        rel_path = str(rel).replace("\\", "/")
    except ValueError:
        rel_path = path.name
    title = path.stem.replace("summary_", "").replace("_", " ").replace("-", " ")
    return QueryCandidate(
        path=rel_path,
        title=title,
        kind=_kind_for_path(rel_path),
        reason=f"{source} match",
        score=1.0,
        source=source,
    )


def _extract_related_links(page_text: str, from_filename: str) -> list[str]:
    links: list[str] = []
    in_related = False
    for line in page_text.splitlines():
        stripped = line.strip()
        if stripped == "## Related":
            in_related = True
            continue
        if in_related and stripped.startswith("## "):
            break
        if not in_related:
            continue
        for target in _re.findall(r"\]\(([^)]+)\)", stripped):
            canonical = _canonical_wiki_target(target, from_filename)
            if canonical:
                links.append(canonical)
        for target in _re.findall(r"\[\[([^\]]+)\]\]", stripped):
            canonical = _canonical_wiki_target(target, from_filename)
            if canonical:
                links.append(canonical)
    return links


def _expand_query_related_pages(
    seed_pages: list[str],
    *,
    wiki_dir: Path | None = None,
    max_pages: int | None = None,
) -> list[QueryCandidate]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    limit = max_pages if max_pages is not None else app_config.WIKI_QUERY_RELATED_MAX
    if limit <= 0:
        return []

    seed_set = set(seed_pages)
    seen = set(seed_pages)
    found: list[QueryCandidate] = []
    for seed in seed_pages:
        page = wiki / seed
        if not page.exists():
            continue
        for rel in _extract_related_links(page.read_text(encoding="utf-8"), seed):
            if rel in seen or rel in seed_set:
                continue
            target = wiki / rel
            if not target.exists():
                continue
            seen.add(rel)
            found.append(QueryCandidate(
                path=rel,
                title=target.stem.replace("summary_", "").replace("_", " "),
                kind=_kind_for_path(rel),
                reason=f"related from {seed}",
                score=0.5,
                source="related",
            ))

    found.sort(key=lambda c: (0 if c.kind == "source" else 1, c.title.lower()))
    return found[:limit]


def _query_needs_raw_source(question: str) -> bool:
    text = question.lower()
    triggers = (
        "原文", "raw", "论文中", "第几页", "核对原文", "逐字",
        "具体段落", "根据原文", "raw source", "source check",
    )
    return any(t in text for t in triggers)


def _find_raw_sources_for_query(
    question: str,
    used_pages: list[str],
    *,
    wiki_dir: Path | None = None,
    notes_dir: Path | None = None,
) -> list[tuple[str, str]]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    notes = notes_dir if notes_dir is not None else app_config.NOTES_DIR
    if not notes.exists():
        return []

    q_tokens = _tokenize(question)
    candidates: list[Path] = []
    for used in used_pages:
        if not used.startswith("sources/summary_"):
            continue
        source_page = wiki / used
        note_name = ""
        if source_page.exists():
            for line in source_page.read_text(encoding="utf-8").splitlines()[:12]:
                if line.startswith("source:"):
                    note_name = line.split(":", 1)[1].strip()
                    break
        if note_name:
            candidates.append(notes / note_name)
        stem = Path(used).stem.replace("summary_", "")
        candidates.extend(notes.glob(stem + ".*"))

    if not candidates:
        candidates = [p for p in notes.iterdir() if p.is_file()]

    scored: list[tuple[int, Path]] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists() or not path.is_file():
            continue
        seen.add(path)
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lower = text.lower()
        hits = sum(1 for t in q_tokens if t in lower or t in path.name.lower())
        if hits > 0 or any(up.startswith("sources/") for up in used_pages):
            scored.append((hits, path))

    scored.sort(key=lambda item: item[0], reverse=True)
    max_items = app_config.WIKI_QUERY_RAW_SOURCE_MAX
    max_chars = app_config.WIKI_QUERY_RAW_SOURCE_MAX_CHARS
    results: list[tuple[str, str]] = []
    for _, path in scored[:max_items]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        results.append((str(path), text))
    return results


def _classify_query_answer_type(question: str) -> str:
    q = question.lower()
    checks = (
        ("comparison_table", ("比较", "对比", " vs ", "difference", "compare")),
        ("timeline", ("时间线", "timeline", "发展过程", "历程")),
        ("analysis_page", ("综述", "分析", "整理成文章", "analysis")),
        ("slide_outline", ("ppt", "slides", "presentation", "幻灯片")),
        ("chart_spec", ("图表", "chart", "趋势", "分布", "可视化")),
        ("source_audit", ("核对", "证据", "来源", "audit")),
        ("outline", ("提纲", "框架", "outline")),
        ("study_notes", ("学习笔记", "复习", "study notes")),
    )
    for answer_type, needles in checks:
        if any(n in q for n in needles):
            return answer_type
    return "direct_answer"


def _build_query_context(
    candidates: list[QueryCandidate],
    *,
    wiki_dir: Path | None = None,
) -> tuple[str, list[str]]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    parts: list[str] = []
    used_pages: list[str] = []
    total = 0
    max_total = app_config.WIKI_QUERY_CONTEXT_MAX_CHARS
    max_page = app_config.WIKI_QUERY_PAGE_MAX_CHARS

    seen: set[str] = set()
    for cand in candidates:
        if cand.path in seen:
            continue
        seen.add(cand.path)
        page = wiki / cand.path
        if not page.exists() or not page.is_file():
            continue
        text = page.read_text(encoding="utf-8")
        if len(text) > max_page:
            text = text[:max_page] + "\n... (truncated)"
        header = (
            f"=== Wiki page: {cand.path} ===\n"
            f"Title: {cand.title}\nKind: {cand.kind}\n"
            f"Why included: {cand.reason}\n\n"
        )
        block = header + text + "\n"
        if total + len(block) > max_total:
            break
        parts.append(block)
        used_pages.append(cand.path)
        total += len(block)
    return "\n".join(parts), used_pages


def _append_query_log(
    wiki_dir: Path,
    question: str,
    used_pages: list[str],
    raw_sources: list[str],
) -> None:
    title = question.strip().replace("\n", " ")[:80] or "(empty question)"
    details = "Used pages: " + (", ".join(used_pages) if used_pages else "No relevant pages found")
    if raw_sources:
        details += "\nRaw sources: " + ", ".join(raw_sources)
    _append_log(wiki_dir, "query", title, details)


def _dedupe_wiki_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def save_query_answer_as_wiki_page(
    question: str,
    answer: str,
    used_pages: list[str],
    wiki_dir: Path | None = None,
    answer_type: str = "direct_answer",
    raw_sources: list[str] | None = None,
) -> Path:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    _ensure_subdirs(wiki)
    raw_sources = raw_sources or []

    slug = _slugify(question)[:80]
    target = _dedupe_wiki_path(wiki / "synthesis" / f"query_{slug}.md")
    rel_path = str(target.relative_to(wiki)).replace("\\", "/")
    title = question.strip().replace("\n", " ")[:80] or "Query synthesis"
    now = datetime.now().strftime("%Y-%m-%d")

    source_lines = [f"- [[{_relative_wiki_link(p, rel_path)}]]" for p in used_pages]
    source_lines.extend(f"- Raw note: {p}" for p in raw_sources)
    related = [
        (Path(p).stem.replace("summary_", "").replace("_", " "), p)
        for p in used_pages
    ]
    related_section = _build_related_section(related, from_filename=rel_path)
    body = (
        "---\n"
        "type: synthesis\n"
        f"created: {now}\n"
        f"question: {question}\n"
        f"answer_type: {answer_type}\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Question\n\n"
        f"{question}\n\n"
        "## Answer\n\n"
        f"{answer.strip()}\n\n"
        "## Sources\n\n"
        + ("\n".join(source_lines) if source_lines else "- (none)")
        + "\n"
    )
    if related_section:
        body += "\n" + related_section
    target.write_text(body, encoding="utf-8")

    catalog = _read_index_catalog(wiki)
    synthesis = [e for e in catalog.synthesis if e.filename != rel_path]
    summary = answer.strip().splitlines()[0][:app_config.WIKI_INDEX_SUMMARY_LEN] if answer.strip() else question[:app_config.WIKI_INDEX_SUMMARY_LEN]
    synthesis.append(IndexEntry(title, rel_path, summary or "(saved query answer)"))
    _write_index(
        wiki,
        sources=catalog.sources,
        entities=catalog.entities,
        concepts=catalog.concepts,
        synthesis=synthesis,
    )
    _append_log(wiki, "query_save", title, f"Saved query answer to {rel_path}")
    return target


def query_wiki(
    question: str,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
    notes_dir: Path | None = None,
    on_meta: Callable[[QueryResultMeta], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
) -> Generator[str, None, None]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR

    candidates = _pick_query_index_candidates(question, wiki_dir=wiki)
    if not candidates:
        pages = _pick_relevant_pages(question, wiki_dir=wiki)
        candidates = [
            _candidate_from_path(path, wiki, source="fallback")
            for path in pages
        ]
    if not candidates:
        _append_query_log(wiki, question, [], [])
        yield "Wiki is empty — no pages to search."
        return

    seed_paths = [c.path for c in candidates]
    related = _expand_query_related_pages(seed_paths, wiki_dir=wiki)
    context, used_pages = _build_query_context([*candidates, *related], wiki_dir=wiki)
    if not used_pages:
        _append_query_log(wiki, question, [], [])
        yield "Wiki is empty — no pages to search."
        return

    raw_context = ""
    raw_sources: list[str] = []
    if _query_needs_raw_source(question):
        raw_items = _find_raw_sources_for_query(
            question, used_pages, wiki_dir=wiki, notes_dir=notes_dir,
        )
        raw_sources = [path for path, _ in raw_items]
        if raw_items:
            raw_parts = [
                f"=== Raw source excerpt: {path} ===\n{text}\n"
                for path, text in raw_items
            ]
            raw_context = "\n\nRaw source excerpts for verification only:\n\n" + "\n".join(raw_parts)

    answer_type = _classify_query_answer_type(question)
    if on_meta:
        on_meta(QueryResultMeta(
            question=question,
            answer_type=answer_type,
            used_pages=used_pages,
            raw_sources=raw_sources,
            suggested_save_title=_slugify(question)[:80],
        ))

    type_instruction = QUERY_TYPE_INSTRUCTIONS.get(
        answer_type, QUERY_TYPE_INSTRUCTIONS["direct_answer"],
    )
    system_prompt = QUERY_SYSTEM + "\n\nAnswer shape:\n" + type_instruction

    messages = [
        Message(role="system", content=system_prompt),
        Message(
            role="user",
            content=f"Wiki pages:\n\n{context}{raw_context}\n\n---\n\nQuestion: {question}",
        ),
    ]
    try:
        yield from chat_stream(config, messages, on_thinking=on_thinking)
    finally:
        _append_query_log(wiki, question, used_pages, raw_sources)


def background_ingest(note_path: Path) -> None:
    if not app_config.LLM_API_KEY:
        return
    config = LLMConfig(
        api_base=app_config.LLM_API_BASE,
        api_key=app_config.LLM_API_KEY,
        model=app_config.LLM_MODEL,
        thinking=app_config.LLM_THINKING,
    )

    def _worker():
        try:
            ingest_note(note_path, config)
        except Exception:
            _logging.exception("background ingest failed for %s", note_path)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _build_discuss_messages(
    source_text: str,
    history: list[dict[str, str]],
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
) -> list[Message]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    catalog = _index_catalog_for_prompt(wiki)
    entity_slugs, concept_slugs = _collect_existing_slugs(wiki)
    slug_list = _slug_list_for_prompt(entity_slugs, concept_slugs)

    source_section = f"=== Source document ===\n{source_text}"
    index_section = f"=== Current wiki index ===\n{catalog}"

    user_parts = [source_section, index_section]
    if slug_list:
        user_parts.append(slug_list)
    user_parts.append(
        "Please read this source and discuss your findings with me."
    )

    msgs = [Message(role="system", content=INGEST_DISCUSS_SYSTEM)]
    msgs.append(Message(role="user", content="\n\n".join(user_parts)))
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
    """Interactive ingest: 5-step workflow on a worker thread.

    1. Discussion loop — stream LLM discussion with user
    2. Candidate extraction — LLM identifies pages to create/update
    3. User focus selection — user picks candidates + optional source read
    4. Write plan generation — batched LLM calls after deep-reading pages
    5. Confirmed execution — user approves, plan is executed
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    _ensure_subdirs(wiki)
    source_text = _read_note_source(note_path)
    title = note_path.stem.replace("_", " ")
    history: list[dict[str, str]] = []

    # ── Step 1: Discussion loop ────────────────────────────────────────
    while True:
        messages = _build_discuss_messages(source_text, history, wiki_dir=wiki)
        full_reply: list[str] = []
        for chunk in chat_stream(config, messages):
            full_reply.append(chunk)
            chat_q.put(chunk)
        reply_text = "".join(full_reply)
        history.append({"role": "assistant", "content": reply_text})

        if "[READY_TO_INGEST]" in reply_text:
            break

        user_input = user_q.get()
        if user_input == "__CANCEL__":
            chat_q.put("__DONE__")
            return None
        history.append({"role": "user", "content": user_input})

    # ── Step 2: Candidate extraction ───────────────────────────────────
    chat_q.put("\n\n正在分析候选页面...\n")
    candidate_messages = _build_ingest_extract_messages(
        source_text, title, history, wiki_dir=wiki,
    )
    raw_candidates = chat(config, candidate_messages)
    summary, candidates = _parse_candidates(raw_candidates)

    if not summary:
        summary = title

    # Canonicalize slugs
    entity_slugs, concept_slugs = _collect_existing_slugs(wiki)
    canonicalized: list[IngestCandidate] = []
    for c in candidates:
        existing = entity_slugs if c.kind == "entity" else concept_slugs
        raw_slug = c.path.split("/")[-1].replace(".md", "")
        canon = _canonical_slug(raw_slug, existing)
        prefix = "entities" if c.kind == "entity" else "concepts"
        canon_path = f"{prefix}/{canon}.md"
        action_hint = "update" if (wiki / canon_path).exists() else "create"
        canonicalized.append(IngestCandidate(
            kind=c.kind, path=canon_path, title=c.title,
            reason=c.reason, confidence=c.confidence,
            default_selected=c.default_selected, action_hint=action_hint,
        ))
    candidates = canonicalized

    display_text = _format_candidates_for_display(candidates)
    chat_q.put(display_text)

    # ── Step 3: User focus selection ───────────────────────────────────
    user_selection = user_q.get()
    if user_selection == "__CANCEL__":
        chat_q.put("__DONE__")
        return None

    selected_indices, user_wants_sources = _parse_user_selection(
        user_selection, candidates,
    )
    selected_paths = [
        candidates[i].path
        for i in sorted(selected_indices)
        if i < len(candidates)
    ]

    # ── Step 4: Deep read + write plan (batched) ───────────────────────
    chat_q.put("\n正在深度阅读已选页面，生成写入计划...\n")

    plan_batches = _build_write_plan(
        source_summary=summary,
        candidates=candidates,
        selected_paths=selected_paths,
        wiki_dir=wiki,
        user_requested_source_read=user_wants_sources,
    )

    all_actions: list[IngestWriteAction] = []
    for batch_messages in plan_batches:
        raw_plan = chat(config, batch_messages)
        batch_actions = _parse_write_plan(raw_plan)
        all_actions.extend(batch_actions)

    if not all_actions:
        all_actions = [
            IngestWriteAction(
                action=c.action_hint,
                path=c.path,
                title=c.title,
                reason=c.reason,
                contribution=c.reason,
            )
            for c in candidates
            if c.path in selected_paths
        ]

    plan_display = _format_plan_for_display(all_actions)
    chat_q.put(plan_display)
    chat_q.put("__READY__")

    # ── Step 5: Confirmed execution ────────────────────────────────────
    confirm = user_q.get()
    if confirm == "__CANCEL__":
        chat_q.put("__DONE__")
        return None

    chat_q.put("\n正在执行写入计划...\n")

    source_filename = _wiki_filename(note_path.name)
    source_page = wiki / source_filename
    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
    )
    source_related = [
        (a.title, a.path) for a in all_actions
        if a.action in ("create", "update")
    ]
    related_section = _build_related_section(
        source_related, from_filename=source_filename,
    )
    if related_section:
        related_section = "\n" + related_section
    source_page.write_text(
        frontmatter + f"# {title}\n\n{summary}\n" + related_section,
        encoding="utf-8",
    )

    sources_idx, _, _ = _read_index_entries(wiki)
    sources_idx = [e for e in sources_idx if e.filename != source_filename]
    sources_idx.append(IndexEntry(
        title=title, filename=source_filename,
        summary=(
            summary.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]
            or "(no summary)"
        ),
    ))
    _, entities_idx, concepts_idx = _read_index_entries(wiki)
    _write_index(
        wiki, sources=sources_idx,
        entities=entities_idx, concepts=concepts_idx,
    )

    plan = IngestWritePlan(
        source_summary=summary,
        source_filename=source_filename,
        actions=all_actions,
        user_focus=selected_paths,
        referenced_source_summaries=[],
    )
    try:
        ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki)
        parts: list[str] = []
        if ok:
            parts.append(f"✅ {ok} 个页面已更新")
        if failed:
            parts.append(f"⚠ {failed} 个页面写入失败")
        if flagged:
            parts.append(f"🔍 {len(flagged)} 个页面需核查:\n" + "\n".join(f"  - {f}" for f in flagged))
        chat_q.put("\n" + "\n".join(parts) + "\n")
        chat_q.put("__DONE__")
        return source_page
    except Exception:
        _logging.exception("write plan execution failed for %s", note_path)
        chat_q.put("\n❌ 执行失败\n")
        chat_q.put("__ERROR__")
        return None
