"""Wiki health-check: static analysis + optional LLM audit."""

import json
import posixpath
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

import httpx
import config as app_config
from llm.client import LLMConfig, Message, chat
from llm.graph_data import parse_wiki_graph
from llm.prompts import LINT_SYSTEM


@dataclass(frozen=True)
class LintFinding:
    severity: str       # "error" | "warn" | "info"
    kind: str
    location: str
    message: str
    suggestion: str
    priority: str = "P2"
    fixable: bool = False
    source: str = "static"  # "static" | "llm"


@dataclass(frozen=True)
class LintFixFile:
    path: str
    original: str
    updated: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class LintFixPreview:
    files: tuple[LintFixFile, ...]
    summary: str = ""


_PRIORITY_MAP: dict[str, str] = {
    "missing_index": "P0", "missing_dir": "P0", "missing_file": "P0",
    "broken_link": "P0", "empty_link": "P0", "missing_index_section": "P0",
    "duplicate_concept": "P1", "no_sources": "P1", "temporal_claim": "P1",
    "duplicate_index": "P1", "heading_drift": "P1", "one_way_related": "P1",
    "frontmatter_type_mismatch": "P1", "contradiction": "P1",
    "stale": "P1", "stale_temporal": "P1", "stale_superseded": "P1",
}


def _finding(
    severity: str, kind: str, location: str, message: str, suggestion: str,
    *, fixable: bool = False, source: str = "static",
) -> LintFinding:
    priority = _PRIORITY_MAP.get(kind, "P2")
    if source == "llm" and priority == "P0":
        priority = "P1"
    return LintFinding(
        severity=severity, kind=kind, location=location,
        message=message, suggestion=suggestion,
        priority=priority, fixable=fixable, source=source,
    )


# ── Static checks ────────────────────────────────────────────────────────

def static_checks(wiki_dir: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    _check_wiki_scaffold(wiki_dir, findings)
    _check_index_structure(wiki_dir, findings)
    _check_orphans(wiki_dir, findings)
    _check_broken_links(wiki_dir, findings)
    _check_internal_markdown_links(wiki_dir, findings)
    _check_one_way_related_links(wiki_dir, findings)
    _check_duplicate_index(wiki_dir, findings)
    _check_index_disk_drift(wiki_dir, findings)
    _check_heading_drift(wiki_dir, findings)
    _check_empty_links(wiki_dir, findings)
    _check_stray_files(wiki_dir, findings)
    _check_shallow_pages(wiki_dir, findings)
    _check_log_health(wiki_dir, findings)
    _check_duplicate_concepts(wiki_dir, findings)
    _check_source_coverage(wiki_dir, findings)
    _check_frontmatter(wiki_dir, findings)
    _check_uningested_notes(wiki_dir, findings)
    _check_temporal_claims(wiki_dir, findings)
    _check_missing_cross_refs(wiki_dir, findings)
    return findings


_WIKI_SUBDIRS = ("sources", "entities", "concepts", "synthesis")


def _check_wiki_scaffold(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for sub in _WIKI_SUBDIRS:
        if not (wiki_dir / sub).exists():
            findings.append(_finding(
                "warn", "missing_dir", sub,
                f"Expected wiki subdirectory '{sub}' is missing",
                "Create the directory or run an ingest/query-save workflow",
            ))
    if not (wiki_dir / "index.md").exists():
        findings.append(_finding(
            "error", "missing_index", "index.md",
            "Wiki index is missing; the LLM has no catalog to navigate",
            "Rebuild index.md from disk or run a fresh ingest",
        ))


def _check_index_structure(wiki_dir: Path, findings: list[LintFinding]) -> None:
    idx = wiki_dir / "index.md"
    if not idx.exists():
        return
    text = idx.read_text(encoding="utf-8")
    headings = set(re.findall(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    for heading in ("Sources", "Entities", "Concepts"):
        if heading not in headings:
            findings.append(_finding(
                "error", "missing_index_section", "index.md",
                f"Missing required '## {heading}' section",
                "Restore the standard index sections: Sources, Entities, Concepts",
            ))
    if "Synthesis" not in headings and (wiki_dir / "synthesis").exists():
        has_synthesis = any(
            f for f in (wiki_dir / "synthesis").glob("*.md")
            if not f.name.startswith("wiki-lint-")
        )
        if has_synthesis:
            findings.append(_finding(
                "warn", "missing_index_section", "index.md",
                "synthesis/ pages exist but index.md has no '## Synthesis' section",
                "Add a Synthesis section so saved query answers remain discoverable",
            ))


def _check_orphans(wiki_dir: Path, findings: list[LintFinding]) -> None:
    g = parse_wiki_graph(wiki_dir)
    targets = {e.target for e in g.edges}
    for node in g.nodes:
        if not node.id:
            continue
        if node.id not in targets:
            findings.append(_finding(
                "warn", "orphan", node.id,
                f"'{node.title}' has no inbound links from other pages",
                "Add a cross-reference from a related page",
            ))


_RELATED_LINK = re.compile(r"^- \[.+?\]\((.+?)\)$")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _check_broken_links(wiki_dir: Path, findings: list[LintFinding]) -> None:
    def normalize_target(page_id: str, target: str) -> str:
        if target.split("/", 1)[0] in set(_WIKI_SUBDIRS):
            return target
        return posixpath.normpath(posixpath.join(posixpath.dirname(page_id), target))

    for sub in _WIKI_SUBDIRS:
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            page_id = f"{sub}/{f.name}"
            in_related = False
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip() == "## Related":
                    in_related = True
                    continue
                if in_related and line.startswith("## "):
                    break
                if in_related:
                    m = _RELATED_LINK.match(line.strip())
                    if m:
                        target = normalize_target(page_id, m.group(1))
                        if not (wiki_dir / target).exists():
                            findings.append(_finding(
                                "error", "broken_link", page_id,
                                f"Links to '{target}' which does not exist",
                                "Remove the link or create the missing page",
                            ))


def _iter_wiki_pages(wiki_dir: Path):
    for sub in _WIKI_SUBDIRS:
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if f.is_file() and f.suffix == ".md":
                yield sub, f


def _normalize_wiki_link(page_id: str, target: str) -> str | None:
    target = target.strip()
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = target.split("#", 1)[0].strip()
    if not target:
        return None
    if target.split("/", 1)[0] in set(_WIKI_SUBDIRS):
        return posixpath.normpath(target)
    return posixpath.normpath(posixpath.join(posixpath.dirname(page_id), target))


def _check_internal_markdown_links(wiki_dir: Path, findings: list[LintFinding]) -> None:
    seen: set[tuple[str, str]] = set()
    for sub, f in _iter_wiki_pages(wiki_dir):
        page_id = f"{sub}/{f.name}"
        for m in _MD_LINK.finditer(f.read_text(encoding="utf-8")):
            target = _normalize_wiki_link(page_id, m.group(1))
            if target is None or not target.endswith(".md"):
                continue
            key = (page_id, target)
            if key in seen:
                continue
            seen.add(key)
            if not (wiki_dir / target).exists():
                findings.append(_finding(
                    "error", "broken_link", page_id,
                    f"Markdown link points to missing page '{target}'",
                    "Fix the link, create the page, or remove stale cross-reference",
                ))


def _check_one_way_related_links(wiki_dir: Path, findings: list[LintFinding]) -> None:
    g = parse_wiki_graph(wiki_dir)
    edges = {(e.source, e.target) for e in g.edges}
    for source, target in sorted(edges):
        if (target, source) not in edges and not source.startswith("sources/"):
            findings.append(_finding(
                "info", "one_way_related", source,
                f"Related link to '{target}' has no backlink",
                "Add a reciprocal Related link if this is a durable association",
            ))


def _check_duplicate_index(wiki_dir: Path, findings: list[LintFinding]) -> None:
    catalog = _read_index_catalog_safe(wiki_dir)
    sections = (
        ("Sources", catalog[0]),
        ("Entities", catalog[1]),
        ("Concepts", catalog[2]),
        ("Synthesis", catalog[3]),
    )
    for label, entries in sections:
        seen: dict[str, int] = {}
        for entry in entries:
            seen[entry.filename] = seen.get(entry.filename, 0) + 1
        for fn, count in seen.items():
            if count > 1:
                findings.append(_finding(
                    "error", "duplicate_index", "index.md",
                    f"'{fn}' appears {count} times in ## {label}",
                    "Remove duplicate entries from index.md",
                ))


def _is_lint_report(rel: str) -> bool:
    return rel.startswith("synthesis/wiki-lint-")


def _check_index_disk_drift(wiki_dir: Path, findings: list[LintFinding]) -> None:
    sources, entities, concepts, synthesis = _read_index_catalog_safe(wiki_dir)
    indexed_files = {e.filename for e in sources + entities + concepts + synthesis}
    for fn in indexed_files:
        if not (wiki_dir / fn).exists():
            findings.append(_finding(
                "error", "missing_file", fn,
                "Listed in index.md but file does not exist",
                "Remove from index or re-ingest the source",
            ))
    for sub in _WIKI_SUBDIRS:
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if f.is_file() and f.suffix == ".md":
                rel = f"{sub}/{f.name}"
                if _is_lint_report(rel):
                    continue
                if rel not in indexed_files:
                    findings.append(_finding(
                        "warn", "unindexed_file", rel,
                        "File exists on disk but not listed in index.md",
                        "Re-run ingest or add to index manually",
                    ))


STUB_THRESHOLD = 500

_HEADING_DRIFT = re.compile(
    r"^(\*\*Sources?\*\*|\*\*来源\*\*|\*\*Related\*\*|## Source$|## Refs?$|## References?$)",
    re.MULTILINE,
)
_EMPTY_LINK = re.compile(r"\[.+?\]\(\s*\)")
_STANDALONE_EMPTY_LINK = re.compile(r"^-\s+\[.+?\]\(\s*\)\s*$", re.MULTILINE)
_KNOWN_ROOT_FILES = {"index.md", "log.md"}


def _read_index_catalog_safe(wiki_dir: Path):
    from llm.wiki_engine import _read_index_catalog
    catalog = _read_index_catalog(wiki_dir)
    return catalog.sources, catalog.entities, catalog.concepts, catalog.synthesis


def _check_heading_drift(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for sub, f in _iter_wiki_pages(wiki_dir):
        text = f.read_text(encoding="utf-8")
        for m in _HEADING_DRIFT.finditer(text):
            findings.append(_finding(
                "warn", "heading_drift", f"{sub}/{f.name}",
                f"Non-standard heading '{m.group(0).strip()}'",
                "Replace with '## Sources' or '## Related'",
                fixable=True,
            ))


def _check_empty_links(wiki_dir: Path, findings: list[LintFinding]) -> None:
    paths = [wiki_dir / "index.md"]
    paths.extend(f for _sub, f in _iter_wiki_pages(wiki_dir))
    for path in paths:
        if not path.exists():
            continue
        rel = path.name if path.parent == wiki_dir else f"{path.parent.name}/{path.name}"
        text = path.read_text(encoding="utf-8")
        for m in _EMPTY_LINK.finditer(text):
            is_standalone = bool(_STANDALONE_EMPTY_LINK.search(
                text[max(0, m.start() - 5):m.end() + 2],
            ))
            findings.append(_finding(
                "error", "empty_link", rel,
                f"Empty link: {m.group(0)}",
                "Fix the href or remove the entry",
                fixable=is_standalone,
            ))


def _check_stray_files(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for f in wiki_dir.iterdir():
        if f.is_file() and f.name not in _KNOWN_ROOT_FILES:
            findings.append(_finding(
                "info", "stray_file", f.name,
                f"Unexpected file in wiki root: {f.name}",
                "Move to a subdirectory or delete",
            ))


def _check_shallow_pages(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for sub in ("entities", "concepts"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            if len(text) < STUB_THRESHOLD:
                findings.append(_finding(
                    "info", "shallow", f"{sub}/{f.name}",
                    f"Page is a stub ({len(text)} chars) — only title + one line",
                    "Expand with information from related source pages",
                ))


def _check_log_health(wiki_dir: Path, findings: list[LintFinding]) -> None:
    log = wiki_dir / "log.md"
    if not log.exists():
        findings.append(_finding(
            "info", "missing_log", "log.md",
            "Wiki log is missing; operations will be harder to audit over time",
            "Run ingest/query/lint once to create log.md",
        ))
        return
    text = log.read_text(encoding="utf-8")
    if not text.strip():
        findings.append(_finding(
            "info", "empty_log", "log.md",
            "Wiki log exists but has no entries",
            "Keep chronological operation entries for ingest, query, and lint runs",
        ))
        return
    entries = re.findall(r"^##\s+\[\d{4}-\d{2}-\d{2}\]\s+.+$", text, flags=re.MULTILINE)
    if "## [" in text and not entries:
        findings.append(_finding(
            "warn", "log_format_drift", "log.md",
            "Log headings do not match the expected '## [YYYY-MM-DD] operation | title' shape",
            "Normalize log headings so recent operations remain parseable",
        ))


# ── New static checks (Phase 3) ──────────────────────────────────────────

def _normalize_slug(name: str) -> str:
    out: list[str] = []
    for ch in name.strip().lower():
        if ch.isalnum() or "一" <= ch <= "鿿":
            out.append(ch)
    return "".join(out)


def _check_duplicate_concepts(wiki_dir: Path, findings: list[LintFinding]) -> None:
    catalog = _read_index_catalog_safe(wiki_dir)
    groups = [
        ("entities", catalog[1]),
        ("concepts", catalog[2]),
    ]
    for sub, entries in groups:
        slug_map: dict[str, list[str]] = {}
        title_map: dict[str, list[str]] = {}
        for entry in entries:
            norm = _normalize_slug(entry.title)
            if norm:
                slug_map.setdefault(norm, []).append(entry.filename)
            title_map.setdefault(entry.title.strip().lower(), []).append(entry.filename)

        for norm, files in slug_map.items():
            unique = sorted(set(files))
            if len(unique) > 1:
                findings.append(_finding(
                    "warn", "duplicate_concept", unique[0],
                    f"Slug collision in {sub}/: {', '.join(unique)} normalize to the same slug",
                    "Merge duplicate pages or rename to distinguish",
                ))
        for title, files in title_map.items():
            unique = sorted(set(files))
            if len(unique) > 1 and _normalize_slug(title) not in slug_map:
                findings.append(_finding(
                    "warn", "duplicate_concept", unique[0],
                    f"Exact title match in {sub}/: {', '.join(unique)}",
                    "Merge duplicate pages or rename to distinguish",
                ))

    entity_titles = {e.title.strip().lower() for e in catalog[1]}
    concept_titles = {e.title.strip().lower() for e in catalog[2]}
    overlap = entity_titles & concept_titles
    for title in sorted(overlap):
        findings.append(_finding(
            "info", "duplicate_concept", "index.md",
            f"同名页面 '{title}' 分别存在于 entities/ 和 concepts/，可能边界不清",
            "检查分类是否正确",
        ))


def _check_source_coverage(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for sub in ("entities", "concepts"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            has_sources = False
            in_sources = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped in ("## Sources", "## 来源"):
                    in_sources = True
                    continue
                if in_sources and stripped.startswith("## "):
                    break
                if in_sources and stripped.startswith("- "):
                    has_sources = True
                    break
            if not has_sources:
                findings.append(_finding(
                    "warn", "no_sources", f"{sub}/{f.name}",
                    "Page has no source citations in ## Sources",
                    "Add source references to establish provenance",
                ))


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return None


def _check_frontmatter(wiki_dir: Path, findings: list[LintFinding]) -> None:
    subdir_type_map = {"entities": "entity", "concepts": "concept", "synthesis": "synthesis"}
    for sub in ("entities", "concepts", "synthesis"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            if f.name.startswith("wiki-lint-"):
                continue
            text = f.read_text(encoding="utf-8")
            fm = _parse_frontmatter(text)
            rel = f"{sub}/{f.name}"
            if fm is None:
                findings.append(_finding(
                    "info", "missing_frontmatter", rel,
                    "Page has no YAML frontmatter",
                    "Add frontmatter with type, created, and updated fields",
                ))
                continue
            expected = subdir_type_map.get(sub, "")
            actual = fm.get("type", "")
            if actual and expected and actual != expected:
                findings.append(_finding(
                    "warn", "frontmatter_type_mismatch", rel,
                    f"Frontmatter type '{actual}' does not match directory '{sub}'",
                    f"Change type to '{expected}' or move page to the correct directory",
                ))


def _check_uningested_notes(wiki_dir: Path, findings: list[LintFinding]) -> None:
    notes_dir = app_config.NOTES_DIR
    if not notes_dir.exists():
        return
    sources_dir = wiki_dir / "sources"
    for f in notes_dir.iterdir():
        if not f.is_file() or f.suffix != ".md":
            continue
        expected = sources_dir / f"summary_{f.stem}.md"
        if not expected.exists():
            findings.append(_finding(
                "info", "uningested_note", f"notes/{f.name}",
                f"Note '{f.name}' has no corresponding wiki source summary",
                "Run ingest to process this note into the wiki",
            ))


_TEMPORAL_KEYWORDS = re.compile(
    r"当前|目前|最新|最近|不再|已废弃|已过时"
    r"|currently|latest|recently|no longer|deprecated|obsolete",
    re.IGNORECASE,
)


def _parse_date_str(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _check_temporal_claims(wiki_dir: Path, findings: list[LintFinding]) -> None:
    threshold = timedelta(days=app_config.WIKI_LINT_STALE_DAYS)
    now = datetime.now()
    for sub in ("entities", "concepts"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            if not _TEMPORAL_KEYWORDS.search(text):
                continue
            fm = _parse_frontmatter(text)
            updated_str = fm.get("updated", "") if fm else ""
            updated_date = _parse_date_str(updated_str) if updated_str else None
            if updated_date is None:
                try:
                    mtime = f.stat().st_mtime
                    updated_date = datetime.fromtimestamp(mtime)
                except OSError:
                    pass
            rel = f"{sub}/{f.name}"
            if updated_date and (now - updated_date) > threshold:
                findings.append(_finding(
                    "warn", "temporal_claim", rel,
                    f"Contains time-sensitive language but last updated {updated_date.strftime('%Y-%m-%d')} (>{app_config.WIKI_LINT_STALE_DAYS} days ago)",
                    "Review temporal claims for accuracy",
                ))
            elif updated_date is None:
                findings.append(_finding(
                    "info", "temporal_claim", rel,
                    "Contains time-sensitive language but has no reliable update date",
                    "Add frontmatter 'updated:' field to track freshness",
                ))


def _strip_noise_sections(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    in_frontmatter = False
    past_frontmatter = False
    in_code_block = False
    in_skip_section = False

    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not past_frontmatter:
            if not in_frontmatter:
                in_frontmatter = True
                continue
            in_frontmatter = False
            past_frontmatter = True
            continue
        if in_frontmatter:
            continue
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped in ("## Sources", "## 来源", "## Related"):
            in_skip_section = True
            continue
        if in_skip_section and stripped.startswith("## "):
            in_skip_section = False
        if in_skip_section:
            continue
        result.append(line)
    return "\n".join(result)


def _check_missing_cross_refs(wiki_dir: Path, findings: list[LintFinding]) -> None:
    catalog = _read_index_catalog_safe(wiki_dir)
    all_entries = list(catalog[1]) + list(catalog[2])
    title_to_file: dict[str, str] = {}
    for entry in all_entries:
        title_to_file[entry.title.strip()] = entry.filename

    for sub in ("entities", "concepts"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            page_id = f"{sub}/{f.name}"
            text = f.read_text(encoding="utf-8")
            clean = _strip_noise_sections(text)
            existing_links: set[str] = set()
            for m in _MD_LINK.finditer(text):
                resolved = _normalize_wiki_link(page_id, m.group(1))
                if resolved:
                    existing_links.add(resolved)
            for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
                resolved = _normalize_wiki_link(page_id, m.group(1))
                if resolved:
                    existing_links.add(resolved)

            for title, target_file in title_to_file.items():
                if target_file == page_id:
                    continue
                is_ascii = all(c < "" for c in title)
                if is_ascii and len(title) < 3:
                    continue
                if not is_ascii and len(title) < 2:
                    continue
                if title not in clean:
                    continue
                if target_file in existing_links:
                    continue
                findings.append(_finding(
                    "info", "missing_xref", page_id,
                    f"Mentions '{title}' but has no link to {target_file}",
                    f"Consider adding a cross-reference to {target_file}",
                ))


# ── LLM-based check ──────────────────────────────────────────────────────

_SEV_MAP = {"ERROR": "error", "WARN": "warn", "INFO": "info"}


def _format_static_findings(findings: list[LintFinding]) -> str:
    if not findings:
        return "(no automated issues detected)"
    lines = []
    for f in findings:
        lines.append(f"- [{f.severity.upper()}] {f.kind}: {f.location} — {f.message}")
    return "\n".join(lines)


def _parse_llm_lint(raw: str) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if "NO_ISSUES" in raw.strip():
        return findings

    section = "issues"
    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ISSUES"):
            section = "issues"
            continue
        if stripped.upper().startswith("SUGGESTIONS"):
            section = "suggestions"
            continue
        if not stripped or not stripped[0].isdigit():
            continue
        rest = stripped.split(". ", 1)[-1] if ". " in stripped else stripped
        parts = rest.split(" | ")
        if len(parts) < 2:
            continue
        tokens = parts[0].strip().split(None, 2)
        if len(tokens) < 3:
            continue
        sev = _SEV_MAP.get(tokens[0], "info")
        kind = tokens[1]
        loc = tokens[2]
        msg = parts[1].strip() if len(parts) > 1 else ""
        sug = parts[2].strip() if len(parts) > 2 else ""

        if section == "suggestions":
            priority = "P2"
        else:
            priority = _PRIORITY_MAP.get(kind, "P2")
            if priority == "P0":
                priority = "P1"

        findings.append(LintFinding(
            severity=sev, kind=kind, location=loc,
            message=msg, suggestion=sug,
            priority=priority, source="llm",
        ))
    return findings


def _page_date_str(f: Path) -> str:
    text = f.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    if fm:
        for key in ("updated", "created"):
            if fm.get(key):
                return fm[key]
    try:
        return datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return "unknown"


def _collect_page_samples(wiki_dir: Path, static_findings: list[LintFinding] | None = None) -> str:
    budget = app_config.WIKI_LINT_MAX_CHARS
    deep_budget = int(budget * 0.5)
    parts: list[str] = []
    used = 0

    flagged_pages: set[str] = set()
    if static_findings:
        for f in static_findings:
            if f.kind in ("shallow", "temporal_claim", "no_sources", "heading_drift"):
                flagged_pages.add(f.location)

    sources_dir = wiki_dir / "sources"
    if sources_dir.exists():
        parts.append("=== Source Pages ===\n")
        for f in sorted(sources_dir.iterdir()):
            if f.suffix == ".md" and used < deep_budget:
                text = f.read_text(encoding="utf-8")
                preview = text[:1200]
                date = _page_date_str(f)
                block = f"## {f.stem} (updated: {date})\n{preview}\n"
                parts.append(block)
                used += len(block)

    for kind in ("entities", "concepts"):
        d = wiki_dir / kind
        if not d.exists():
            continue
        stubs: list[tuple[str, str, str]] = []
        flagged: list[tuple[str, str, str]] = []
        ok: list[tuple[str, str, str]] = []
        for f in d.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            date = _page_date_str(f)
            rel = f"{kind}/{f.name}"
            if len(text) < STUB_THRESHOLD:
                stubs.append((f.stem, text, date))
            elif rel in flagged_pages:
                flagged.append((f.stem, text[:1200], date))
            else:
                ok.append((f.stem, text[:300], date))

        if stubs:
            parts.append(f"\n=== {kind.title()} (stubs) ===\n")
            for stem, text, date in stubs[:20]:
                if used >= deep_budget:
                    break
                block = f"## {stem} (updated: {date})\n{text}\n"
                parts.append(block)
                used += len(block)
            parts.append(f"(total {len(stubs)} stubs of {len(stubs) + len(flagged) + len(ok)} {kind})\n")

        if flagged:
            parts.append(f"\n=== {kind.title()} (flagged) ===\n")
            for stem, preview, date in flagged:
                if used >= deep_budget:
                    break
                block = f"## {stem} (updated: {date})\n{preview}\n"
                parts.append(block)
                used += len(block)

        if ok:
            parts.append(f"\n=== {kind.title()} (sample) ===\n")
            for stem, preview, date in sorted(ok)[:5]:
                if used >= deep_budget:
                    break
                block = f"## {stem} (updated: {date}, excerpt)\n{preview}\n"
                parts.append(block)
                used += len(block)

    return "\n".join(parts)


def llm_check(
    wiki_dir: Path,
    config: LLMConfig,
    *,
    static_findings: list[LintFinding] | None = None,
) -> Generator[LintFinding, None, None]:
    if not config.api_key:
        return
    budget = app_config.WIKI_LINT_MAX_CHARS

    idx = wiki_dir / "index.md"
    index_text = idx.read_text(encoding="utf-8") if idx.exists() else "(empty)"
    index_budget = int(budget * 0.4)
    if len(index_text) > index_budget:
        index_text = index_text[:index_budget] + "\n... (truncated)"

    log = wiki_dir / "log.md"
    log_text = log.read_text(encoding="utf-8")[:2000] if log.exists() else "(no log)"

    auto_issues = _format_static_findings(static_findings or [])
    findings_budget = int(budget * 0.1)
    if len(auto_issues) > findings_budget:
        auto_issues = auto_issues[:findings_budget] + "\n... (truncated)"

    page_samples = _collect_page_samples(wiki_dir, static_findings)

    p0_count = sum(1 for f in (static_findings or []) if f.priority == "P0")
    p0_warning = ""
    if p0_count > 0:
        p0_warning = (
            f"\n⚠ Static checks found {p0_count} structural errors (P0). "
            "Wiki structure may be incomplete — factor this into your analysis.\n\n"
        )

    user_content = (
        f"{p0_warning}"
        f"=== Wiki Index ===\n{index_text}\n\n"
        f"=== Recent Log ===\n{log_text}\n\n"
        f"=== Automated Issues Already Detected ===\n{auto_issues}\n\n"
        f"=== Page Content Samples ===\n{page_samples}\n"
    )
    if len(user_content) > budget:
        user_content = user_content[:budget] + "\n\n[... content truncated ...]"

    messages = [
        Message(role="system", content=LINT_SYSTEM),
        Message(role="user", content=user_content),
    ]
    try:
        raw = chat(config, messages)
    except httpx.TimeoutException as exc:
        yield LintFinding(
            severity="warn",
            kind="llm_timeout",
            location="wiki",
            message=f"LLM 体检超时: {exc}",
            suggestion="静态检查结果已保留；请检查 LLM 服务状态，或调高 LLM_TIMEOUT 后重新体检。",
            priority="P2",
            source="llm",
        )
        return
    yield from _parse_llm_lint(raw)


def lint_wiki(
    wiki_dir: Path,
    config: LLMConfig,
) -> Generator[LintFinding, None, None]:
    static = static_checks(wiki_dir)
    yield from static
    llm_findings = list(llm_check(wiki_dir, config, static_findings=static))
    yield from llm_findings


# ── Report persistence ────────────────────────────────────────────────────

_SUGGESTION_KINDS = frozenset({"investigation", "next_source"})


def save_lint_report(wiki_dir: Path, findings: list[LintFinding]) -> Path:
    (wiki_dir / "synthesis").mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    target = wiki_dir / "synthesis" / f"wiki-lint-{today}.md"

    page_count = sum(
        1 for sub in _WIKI_SUBDIRS
        if (wiki_dir / sub).exists()
        for f in (wiki_dir / sub).iterdir()
        if f.is_file() and f.suffix == ".md" and not f.name.startswith("wiki-lint-")
    )

    by_priority: dict[str, list[LintFinding]] = {"P0": [], "P1": [], "P2": []}
    suggestions: list[LintFinding] = []
    for f in findings:
        if f.kind in _SUGGESTION_KINDS:
            suggestions.append(f)
        else:
            by_priority.setdefault(f.priority, []).append(f)

    fixable_count = sum(1 for f in findings if f.fixable)

    lines = [
        "---",
        "type: synthesis",
        f"created: {today}",
        "tags: [wiki-lint]",
        "---",
        "",
        f"# Wiki Lint Report {today}",
        "",
        "## Summary",
        f"- Pages scanned: {page_count}",
        f"- P0 issues: {len(by_priority['P0'])}",
        f"- P1 issues: {len(by_priority['P1'])}",
        f"- P2 issues: {len(by_priority['P2'])}",
        f"- Auto-fixable: {fixable_count}",
        "",
    ]

    section_labels = [
        ("P0", "P0: 需要立刻处理"),
        ("P1", "P1: 建议近期处理"),
        ("P2", "P2: 可逐步优化"),
    ]
    for key, label in section_labels:
        lines.append(f"## {label}")
        lines.append("")
        items = by_priority.get(key, [])
        if not items:
            lines.append("_(none)_")
            lines.append("")
            continue
        for i, f in enumerate(items, 1):
            lines.append(f"### {i}. [{f.kind}] {f.location}")
            lines.append(f"- Issue: {f.message}")
            if f.suggestion:
                lines.append(f"- Fix: {f.suggestion}")
            lines.append("")

    lines.append("## 探索建议")
    lines.append("")
    if suggestions:
        for i, f in enumerate(suggestions, 1):
            lines.append(f"{i}. **{f.kind}**: {f.message}")
            if f.suggestion:
                lines.append(f"   → {f.suggestion}")
        lines.append("")
    else:
        lines.append("_(none)_")
        lines.append("")

    lines.extend([
        "## 建议修复顺序",
        "",
        "1. 修复 index/log 结构",
        "2. 修复 broken/empty links",
        "3. 补充来源引用",
        "4. 合并重复概念",
        "5. 处理冲突和过时说法",
        "6. 新建缺失概念页",
        "7. 优化 cross-reference 和薄页面",
        "",
    ])

    target.write_text("\n".join(lines), encoding="utf-8")
    return target


# ── Auto-fix ──────────────────────────────────────────────────────────────

_HEADING_DRIFT_REPLACE = {
    "**Sources**": "## Sources",
    "**Source**": "## Sources",
    "**来源**": "## Sources",
    "**Related**": "## Related",
    "## Source": "## Sources",
    "## Ref": "## Sources",
    "## Refs": "## Sources",
    "## Reference": "## Sources",
    "## References": "## Sources",
}
_REBUILD_ACTION_KINDS = frozenset({
    "missing_index", "missing_index_section", "missing_file",
    "unindexed_file", "duplicate_index",
})


def auto_fix(wiki_dir: Path, findings: list[LintFinding]) -> int:
    fixed = 0
    heading_drift_files: set[str] = set()
    empty_link_files: set[str] = set()

    for f in findings:
        if not f.fixable or f.source == "llm":
            continue
        if f.kind == "heading_drift":
            heading_drift_files.add(f.location)
        elif f.kind == "empty_link":
            empty_link_files.add(f.location)

    for rel in heading_drift_files:
        path = wiki_dir / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in _HEADING_DRIFT_REPLACE.items():
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            fixed += 1

    for rel in empty_link_files:
        if rel in ("index.md",):
            path = wiki_dir / rel
        else:
            path = wiki_dir / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        text = _STANDALONE_EMPTY_LINK.sub("", text)
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        if cleaned != original:
            path.write_text(cleaned, encoding="utf-8")
            fixed += 1

    return fixed


_LLM_FIX_SYSTEM = """You repair a local Markdown wiki.
Return JSON only, with this shape:
{"summary":"short summary","files":[{"path":"entities/example.md","edits":[{"old":"exact existing text","new":"replacement text"}],"issues":["kind"]}]}
Rules:
- Only modify Markdown files inside index.md, log.md, or wiki subdirectories sources/, entities/, concepts/, synthesis/.
- Prefer edits. Each old value must be exact contiguous text copied from the current file.
- Preserve useful existing information and add concise citations or cross-links when possible.
- For every selected issue-target file shown under Current Files, return a file entry or explain in summary why it should not be changed.
- Do not return a short fragment as full file content. A legacy content field is accepted only when it is a safe full replacement.
- If an issue needs source material that is unavailable, add a brief note or placeholder section in the relevant wiki page rather than editing notes/.
"""


def _safe_preview_rel_path(wiki_dir: Path, raw_path: str) -> str:
    rel = raw_path.replace("\\", "/").strip()
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise ValueError(f"Unsafe wiki path from LLM: {raw_path}")
    parts = [part for part in rel.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ValueError(f"Unsafe wiki path from LLM: {raw_path}")
    rel = posixpath.normpath("/".join(parts))
    if rel in ("", ".") or not rel.endswith(".md"):
        raise ValueError(f"LLM fix path must be a Markdown file: {raw_path}")
    first = rel.split("/", 1)[0]
    if rel not in {"index.md", "log.md"} and first not in set(_WIKI_SUBDIRS):
        raise ValueError(f"LLM fix path is outside wiki structure: {raw_path}")

    root = wiki_dir.resolve()
    target = (wiki_dir / Path(*rel.split("/"))).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"Unsafe wiki path from LLM: {raw_path}")
    return rel


def _extract_json_document(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, count=1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM did not return a JSON object")
    return text[start:end + 1]


def _finding_target_files(wiki_dir: Path, findings: list[LintFinding]) -> list[str]:
    rels: list[str] = []
    for f in findings:
        candidates = [f.location]
        if f.kind in _REBUILD_ACTION_KINDS or f.location in {"wiki", "index"}:
            candidates.append("index.md")
        if f.location == "log":
            candidates.append("log.md")
        for candidate in candidates:
            try:
                rel = _safe_preview_rel_path(wiki_dir, candidate)
            except ValueError:
                continue
            if rel not in rels:
                rels.append(rel)
    return rels


def _truncate_for_context(text: str, limit: int) -> str:
    marker = "\n[... content truncated ...]"
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(marker):
        return text[:limit]
    return text[:limit - len(marker)].rstrip() + marker


def _format_fix_context(wiki_dir: Path, findings: list[LintFinding]) -> str:
    issue_lines = ["=== Issues ==="]
    for i, f in enumerate(findings, 1):
        issue_lines.append(
            f"{i}. {f.priority} {f.severity} {f.kind} {f.location} | "
            f"{f.message} | {f.suggestion}"
        )
    budget = app_config.WIKI_LINT_MAX_CHARS
    issue_budget = max(400, int(budget * 0.35))
    issue_text = _truncate_for_context("\n".join(issue_lines), issue_budget)

    rels = _finding_target_files(wiki_dir, findings)
    if not rels:
        return _truncate_for_context(
            f"{issue_text}\n\n=== Current Files ===\n(no directly editable wiki files found)",
            budget,
        )

    prefix = f"{issue_text}\n\n=== Current Files ==="
    header_len = sum(len(f"\n--- {rel} ---\n") for rel in rels)
    content_budget = max(0, budget - len(prefix) - header_len)
    per_file_budget = content_budget // max(1, len(rels))

    parts = [prefix]
    for rel in rels:
        path = wiki_dir / Path(*rel.split("/"))
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        parts.append(f"\n--- {rel} ---\n{_truncate_for_context(current, per_file_budget)}")
    return _truncate_for_context("".join(parts), budget)


_PAGE_LOCAL_FIX_KINDS = frozenset({
    "no_sources", "temporal_claim", "stale_temporal", "stale_superseded",
    "missing_xref", "shallow", "missing_frontmatter",
    "frontmatter_type_mismatch", "heading_drift", "empty_link",
    "broken_link", "one_way_related",
})


def _required_preview_files(wiki_dir: Path, findings: list[LintFinding]) -> list[str]:
    rels: list[str] = []
    for f in findings:
        candidates: list[str]
        if f.kind in _REBUILD_ACTION_KINDS or f.location in {"wiki", "index"}:
            candidates = ["index.md"]
        elif f.location == "log":
            candidates = ["log.md"]
        elif f.kind in _PAGE_LOCAL_FIX_KINDS or f.source == "llm":
            candidates = [f.location]
        else:
            candidates = []
        for candidate in candidates:
            try:
                rel = _safe_preview_rel_path(wiki_dir, candidate)
            except ValueError:
                continue
            if (wiki_dir / Path(*rel.split("/"))).exists() and rel not in rels:
                rels.append(rel)
    return rels


def _apply_llm_edits(original: str, edits: object, rel: str) -> str | None:
    if edits is None:
        return None
    if not isinstance(edits, list):
        raise ValueError(f"LLM edits must be a list for {rel}")
    updated = original
    used = False
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError(f"LLM edit must be an object for {rel}")
        old = edit.get("old")
        new = edit.get("new")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ValueError(f"LLM edit must include non-empty old and string new for {rel}")
        if old not in updated:
            raise ValueError(f"LLM edit target not found in current file: {rel}")
        updated = updated.replace(old, new, 1)
        used = True
    return updated if used else original


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _is_destructive_full_replacement(original: str, updated: str) -> bool:
    original_body = original.strip()
    if not original_body:
        return False
    original_lines = _nonempty_lines(original)
    if len(original_body) < 200 and len(original_lines) < 8:
        return False
    if len(updated.strip()) >= len(original_body) * 0.7:
        return False
    kept = sum(1 for line in original_lines if line in updated)
    return kept / max(1, len(original_lines)) < 0.5


def build_llm_fix_preview(
    wiki_dir: Path,
    findings: list[LintFinding],
    config: LLMConfig,
) -> LintFixPreview:
    if not config.api_key:
        raise ValueError("API key is not configured")
    if not findings:
        return LintFixPreview(files=())

    messages = [
        Message(role="system", content=_LLM_FIX_SYSTEM),
        Message(role="user", content=_format_fix_context(wiki_dir, findings)),
    ]
    raw = chat(config, messages)
    try:
        payload = json.loads(_extract_json_document(raw))
    except json.JSONDecodeError as exc:
        raise ValueError("LLM returned invalid fix JSON") from exc

    files: list[LintFixFile] = []
    for item in payload.get("files", []):
        if not isinstance(item, dict):
            continue
        rel = _safe_preview_rel_path(wiki_dir, str(item.get("path", "")))
        path = wiki_dir / Path(*rel.split("/"))
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = _apply_llm_edits(original, item.get("edits"), rel)
        if updated is None:
            updated = item.get("content")
        if not isinstance(updated, str):
            continue
        if updated == original:
            continue
        if _is_destructive_full_replacement(original, updated):
            raise ValueError(f"LLM fix for {rel} removed too much existing content")
        issues_raw = item.get("issues", [])
        issues = tuple(str(x) for x in issues_raw) if isinstance(issues_raw, list) else ()
        files.append(LintFixFile(path=rel, original=original, updated=updated, issues=issues))

    returned = {item.path for item in files}
    missing = [rel for rel in _required_preview_files(wiki_dir, findings) if rel not in returned]
    if missing:
        raise ValueError(f"LLM did not return fixes for selected file(s): {', '.join(missing)}")

    summary = payload.get("summary", "")
    return LintFixPreview(files=tuple(files), summary=str(summary) if summary else "")


def apply_llm_fix_preview(wiki_dir: Path, preview: LintFixPreview) -> int:
    written = 0
    for item in preview.files:
        rel = _safe_preview_rel_path(wiki_dir, item.path)
        path = wiki_dir / Path(*rel.split("/"))
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != item.original:
            raise ValueError(f"File changed since preview: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.updated, encoding="utf-8")
        written += 1
    return written
