"""Wiki health-check: static analysis + optional LLM audit."""

import re
from dataclasses import dataclass
from pathlib import Path

from llm.graph_data import parse_wiki_graph
from llm.wiki_engine import _read_index_entries


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
