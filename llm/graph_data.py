from dataclasses import dataclass, field
from pathlib import Path
import posixpath
import re


@dataclass(frozen=True)
class Node:
    id: str       # e.g. "entities/openai.md"
    title: str    # e.g. "OpenAI"
    kind: str     # "source" | "entity" | "concept"
    path: str = ""          # same as id (relative wiki path)
    summary: str = ""       # first useful paragraph or index description
    mtime: float = 0.0      # file modified timestamp, 0.0 if missing
    exists: bool = True     # whether the linked wiki page exists on disk


@dataclass(frozen=True)
class Edge:
    source: str   # node id
    target: str   # node id
    kind: str = "related"       # "related" for ## Related links
    bidirectional: bool = False # true when target also links back


@dataclass(frozen=True)
class Graph:
    nodes: list[Node]
    edges: list[Edge]


def _extract_summary(text: str) -> str:
    """Extract the first useful paragraph from a wiki page."""
    lines = text.splitlines()
    in_frontmatter = False
    past_frontmatter = False
    for line in lines:
        stripped = line.strip()
        # Skip frontmatter
        if stripped == "---":
            if not in_frontmatter and not past_frontmatter:
                in_frontmatter = True
                continue
            elif in_frontmatter:
                in_frontmatter = False
                past_frontmatter = True
                continue
        if in_frontmatter:
            continue
        # Skip headings, empty lines, Related section markers
        if not stripped or stripped.startswith("#") or stripped.startswith("- ["):
            continue
        # This is a content line
        # Truncate to ~120 chars
        if len(stripped) > 120:
            return stripped[:117] + "..."
        return stripped
    return ""


def parse_wiki_graph(wiki_dir: Path) -> Graph:
    """Build a graph from wiki index + source-page Related links."""
    idx_path = wiki_dir / "index.md"
    if not idx_path.exists():
        return Graph([], [])

    # ── Parse index.md into {id: (title, kind, summary)} ────────────────
    node_map: dict[str, tuple[str, str, str]] = {}  # id → (title, kind, summary)
    current_kind: str | None = None

    SECTION_MAP = {
        "Sources": "source",
        "Entities": "entity",
        "Concepts": "concept",
    }

    for line in idx_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current_kind = SECTION_MAP.get(line[3:].strip())
        elif current_kind and line.startswith("- ["):
            try:
                title = line[line.index("[") + 1:line.index("](")]
                filename = line[line.index("](") + 2:line.index(")")]
                if filename:
                    # Extract inline description from index if present
                    desc_part = ""
                    rest = line[line.index(")") + 1:]
                    if rest.startswith(" — ") or rest.startswith(" - "):
                        desc_part = rest.lstrip(" —- ").strip()
                    node_map[filename] = (title, current_kind, desc_part)
            except ValueError:
                continue

    # ── Extract edges from each page's ## Related ──────────────────────
    edges: list[Edge] = []
    related_pat = re.compile(r"^- \[.+?\]\((.+?)\)$")
    # Track reverse links for bidirectional detection
    link_map: dict[str, set[str]] = {}  # source_id → set of target_ids

    def normalize_target(source_id: str, target: str) -> str:
        if target.split("/", 1)[0] in {"sources", "entities", "concepts"}:
            return target
        return posixpath.normpath(posixpath.join(posixpath.dirname(source_id), target))

    for nid in node_map:
        page = wiki_dir / nid
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        link_map[nid] = set()
        # Find the ## Related section
        in_related = False
        for line in text.splitlines():
            if line.startswith("## Related"):
                in_related = True
                continue
            if in_related and line.startswith("## "):
                break  # next section
            if in_related:
                m = related_pat.match(line.strip())
                if m:
                    target = normalize_target(nid, m.group(1))
                    if target in node_map:
                        link_map[nid].add(target)

    # Build edges from link_map, dedup by (source, target)
    seen_edges: set[tuple[str, str]] = set()
    for source_id, targets in link_map.items():
        for target_id in targets:
            edge_key = (source_id, target_id)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            bidirectional = target_id in link_map and source_id in link_map[target_id]
            edges.append(Edge(source_id, target_id, "related", bidirectional))

    # ── Build nodes with metadata ──────────────────────────────────────
    nodes: list[Node] = []
    for nid, (title, kind, index_summary) in node_map.items():
        page = wiki_dir / nid
        file_exists = page.exists()
        mtime = page.stat().st_mtime if file_exists else 0.0
        summary = index_summary
        if not summary and file_exists:
            summary = _extract_summary(page.read_text(encoding="utf-8"))
        nodes.append(Node(
            id=nid, title=title, kind=kind,
            path=nid, summary=summary, mtime=mtime, exists=file_exists,
        ))

    return Graph(nodes, edges)
