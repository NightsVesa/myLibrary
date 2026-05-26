"""Wiki health-check: static analysis + optional LLM audit."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from llm.client import LLMConfig, Message, chat
from llm.graph_data import parse_wiki_graph
from llm.prompts import LINT_SYSTEM
from llm.wiki_engine import _read_index_entries, _append_log


@dataclass(frozen=True)
class LintFinding:
    severity: str   # "error" | "warn" | "info"
    kind: str       # "orphan" | "broken_link" | "duplicate_index" | ...
    location: str   # file path or "index.md"
    message: str
    suggestion: str


def static_checks(wiki_dir: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    _check_orphans(wiki_dir, findings)
    _check_broken_links(wiki_dir, findings)
    _check_duplicate_index(wiki_dir, findings)
    _check_index_disk_drift(wiki_dir, findings)
    _check_heading_drift(wiki_dir, findings)
    _check_empty_links(wiki_dir, findings)
    _check_stray_files(wiki_dir, findings)
    return findings


def _check_orphans(wiki_dir: Path, findings: list[LintFinding]) -> None:
    g = parse_wiki_graph(wiki_dir)
    targets = {e.target for e in g.edges}
    for node in g.nodes:
        if not node.id:
            continue
        if node.id not in targets:
            findings.append(LintFinding(
                severity="warn", kind="orphan", location=node.id,
                message=f"'{node.title}' has no inbound links from other pages",
                suggestion="Add a cross-reference from a related page",
            ))


_RELATED_LINK = re.compile(r"^- \[.+?\]\((.+?)\)$")


def _check_broken_links(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for sub in ("sources", "entities", "concepts"):
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
                        target = m.group(1)
                        if not (wiki_dir / target).exists():
                            findings.append(LintFinding(
                                severity="error", kind="broken_link",
                                location=page_id,
                                message=f"Links to '{target}' which does not exist",
                                suggestion="Remove the link or create the missing page",
                            ))


def _check_duplicate_index(wiki_dir: Path, findings: list[LintFinding]) -> None:
    sources, entities, concepts = _read_index_entries(wiki_dir)
    for label, entries in (("Sources", sources), ("Entities", entities), ("Concepts", concepts)):
        seen: dict[str, int] = {}
        for entry in entries:
            seen[entry.filename] = seen.get(entry.filename, 0) + 1
        for fn, count in seen.items():
            if count > 1:
                findings.append(LintFinding(
                    severity="error", kind="duplicate_index",
                    location="index.md",
                    message=f"'{fn}' appears {count} times in ## {label}",
                    suggestion="Remove duplicate entries from index.md",
                ))


def _check_index_disk_drift(wiki_dir: Path, findings: list[LintFinding]) -> None:
    sources, entities, concepts = _read_index_entries(wiki_dir)
    indexed_files = {e.filename for e in sources + entities + concepts}
    for fn in indexed_files:
        if not (wiki_dir / fn).exists():
            findings.append(LintFinding(
                severity="error", kind="missing_file",
                location=fn,
                message="Listed in index.md but file does not exist",
                suggestion="Remove from index or re-ingest the source",
            ))
    for sub in ("sources", "entities", "concepts"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if f.is_file() and f.suffix == ".md":
                rel = f"{sub}/{f.name}"
                if rel not in indexed_files:
                    findings.append(LintFinding(
                        severity="warn", kind="unindexed_file",
                        location=rel,
                        message="File exists on disk but not listed in index.md",
                        suggestion="Re-run ingest or add to index manually",
                    ))


_HEADING_DRIFT = re.compile(
    r"^(\*\*Sources?\*\*|\*\*来源\*\*|\*\*Related\*\*|## Source$|## Refs?$|## References?$)",
    re.MULTILINE,
)
_EMPTY_LINK = re.compile(r"\[.+?\]\(\s*\)")
_KNOWN_ROOT_FILES = {"index.md", "log.md"}


def _check_heading_drift(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for sub in ("sources", "entities", "concepts"):
        sd = wiki_dir / sub
        if not sd.exists():
            continue
        for f in sd.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            for m in _HEADING_DRIFT.finditer(text):
                findings.append(LintFinding(
                    severity="warn", kind="heading_drift",
                    location=f"{sub}/{f.name}",
                    message=f"Non-standard heading '{m.group(0).strip()}'",
                    suggestion="Replace with '## Sources' or '## Related'",
                ))


def _check_empty_links(wiki_dir: Path, findings: list[LintFinding]) -> None:
    idx = wiki_dir / "index.md"
    if not idx.exists():
        return
    text = idx.read_text(encoding="utf-8")
    for m in _EMPTY_LINK.finditer(text):
        findings.append(LintFinding(
            severity="error", kind="empty_link",
            location="index.md",
            message=f"Empty link: {m.group(0)}",
            suggestion="Fix the href or remove the entry",
        ))


def _check_stray_files(wiki_dir: Path, findings: list[LintFinding]) -> None:
    for f in wiki_dir.iterdir():
        if f.is_file() and f.name not in _KNOWN_ROOT_FILES:
            findings.append(LintFinding(
                severity="info", kind="stray_file",
                location=f.name,
                message=f"Unexpected file in wiki root: {f.name}",
                suggestion="Move to a subdirectory or delete",
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
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        rest = line.split(". ", 1)[-1] if ". " in line else line
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
        findings.append(LintFinding(severity=sev, kind=kind, location=loc,
                                     message=msg, suggestion=sug))
    return findings


def _collect_page_samples(wiki_dir: Path) -> str:
    """Build a page-content sample for the LLM: all sources (short) + stubs."""
    parts: list[str] = []
    # All source pages (they're short: ~200–400 words each, 18 pages ≈ 6k words).
    sources_dir = wiki_dir / "sources"
    if sources_dir.exists():
        parts.append("=== Source Pages ===\n")
        for f in sorted(sources_dir.iterdir()):
            if f.suffix == ".md":
                text = f.read_text(encoding="utf-8")
                preview = text[:800]  # cap long summaries
                parts.append(f"## {f.stem}\n{preview}\n")
    # Stub entity/concept pages — the LLM needs to see what's thin.
    for kind in ("entities", "concepts"):
        d = wiki_dir / kind
        if not d.exists():
            continue
        stubs = []
        ok = []
        for f in d.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            text = f.read_text(encoding="utf-8")
            if len(text) < 500:
                stubs.append((f.stem, text))
            else:
                ok.append((f.stem, text[:300]))
        parts.append(f"\n=== {kind.title()} (stubs) ===\n")
        for stem, text in stubs[:20]:
            parts.append(f"## {stem}\n{text}\n")
        if stubs:
            parts.append(f"\n(total {len(stubs)} stubs of {len(stubs) + len(ok)} {kind})\n")
        # Sample a few non-stubs for context
        if ok:
            parts.append(f"\n=== {kind.title()} (sample) ===\n")
            for stem, preview in sorted(ok)[:5]:
                parts.append(f"## {stem} (excerpt)\n{preview}\n")
    return "\n".join(parts)


def llm_check(
    wiki_dir: Path,
    config: LLMConfig,
    *,
    static_findings: list[LintFinding] | None = None,
) -> Generator[LintFinding, None, None]:
    if not config.api_key:
        return
    idx = wiki_dir / "index.md"
    index_text = idx.read_text(encoding="utf-8") if idx.exists() else "(empty)"
    log = wiki_dir / "log.md"
    log_text = log.read_text(encoding="utf-8")[:2000] if log.exists() else "(no log)"
    auto_issues = _format_static_findings(static_findings or [])
    page_samples = _collect_page_samples(wiki_dir)
    user_content = (
        f"=== Wiki Index ===\n{index_text}\n\n"
        f"=== Recent Log ===\n{log_text}\n\n"
        f"=== Automated Issues Already Detected ===\n{auto_issues}\n\n"
        f"=== Page Content Samples ===\n{page_samples}\n"
    )
    # Trim to ~12k chars to stay within token budgets.
    if len(user_content) > 12000:
        user_content = user_content[:12000] + "\n\n[... content truncated ...]"
    messages = [
        Message(role="system", content=LINT_SYSTEM),
        Message(role="user", content=user_content),
    ]
    raw = chat(config, messages)
    yield from _parse_llm_lint(raw)


def lint_wiki(
    wiki_dir: Path,
    config: LLMConfig,
) -> Generator[LintFinding, None, None]:
    static = static_checks(wiki_dir)
    yield from static
    llm_findings = list(llm_check(wiki_dir, config, static_findings=static))
    yield from llm_findings
    total = len(static) + len(llm_findings)
    errors = sum(1 for f in static + llm_findings if f.severity == "error")
    warns = sum(1 for f in static + llm_findings if f.severity == "warn")
    _append_log(
        wiki_dir, "lint", "Health check",
        f"{total} issues ({errors} errors, {warns} warnings)",
    )
