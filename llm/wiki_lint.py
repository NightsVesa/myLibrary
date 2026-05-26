"""Wiki health-check: static analysis + optional LLM audit."""

import re
from dataclasses import dataclass
from pathlib import Path

from llm.graph_data import parse_wiki_graph


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
    return findings


def _check_orphans(wiki_dir: Path, findings: list[LintFinding]) -> None:
    g = parse_wiki_graph(wiki_dir)
    targets = {e.target for e in g.edges}
    for node in g.nodes:
        if node.id not in targets:
            findings.append(LintFinding(
                severity="warn", kind="orphan", location=node.id,
                message=f"'{node.title}' has no inbound links from other pages",
                suggestion="Add a cross-reference from a related page",
            ))
