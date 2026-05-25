from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Node:
    id: str       # e.g. "entities/openai.md"
    title: str    # e.g. "OpenAI"
    kind: str     # "source" | "entity" | "concept"


@dataclass(frozen=True)
class Edge:
    source: str   # node id
    target: str   # node id


@dataclass(frozen=True)
class Graph:
    nodes: list[Node]
    edges: list[Edge]


def parse_wiki_graph(wiki_dir: Path) -> Graph:
    """Build a graph from wiki index + source-page Related links."""
    idx_path = wiki_dir / "index.md"
    if not idx_path.exists():
        return Graph([], [])

    # ── Parse index.md into {id: (title, kind)} ────────────────────────
    node_map: dict[str, tuple[str, str]] = {}  # id → (title, kind)
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
                node_map[filename] = (title, current_kind)
            except ValueError:
                continue

    # ── Extract edges from each page's ## Related ──────────────────────
    edges: list[Edge] = []
    related_pat = re.compile(r"^- \[.+?\]\((.+?)\)$")

    for nid, (title, kind) in node_map.items():
        page = wiki_dir / nid
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
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
                    target = m.group(1)
                    # Only add edge if target is a known node
                    if target in node_map:
                        edges.append(Edge(nid, target))

    nodes = [Node(nid, title, kind) for nid, (title, kind) in node_map.items()]
    return Graph(nodes, edges)
