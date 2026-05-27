# Knowledge Graph Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a light-weight interactive knowledge graph tab that visualizes wiki sources, entities, and concepts as a force-directed node-link diagram based on existing Related/Sources links.

**Architecture:** Parse the existing wiki files (`sources/`, `entities/`, `concepts/`) to build a graph (nodes + edges), then render it on a tkinter Canvas inside a new panel tab (Ctrl+5). A simple spring-electric force layout runs a few dozen iterations to position nodes. Click-drag to pan, scroll to zoom, click a node to open its wiki page in the reader.

**Tech Stack:** Python 3 stdlib (`pathlib`, `json`, `re`, `math`), `tkinter.Canvas`, no external graph libraries. Existing `ui/cartoon_widgets.py` for styling.

---

## File Structure

| File | Role |
|---|---|
| `llm/graph_data.py` | Parse `index.md` + source `## Related` links → `Graph(nodes, edges)`. Pure data, no UI. |
| `ui/graph_tab.py` | Canvas rendering + force layout + interaction. Owns a `tk.Frame`, accepts `main` reference. |
| `ui/main_window.py` | Add `图谱` action (Ctrl+5, plum theme). Wire GraphTab into panel system. |
| `tests/test_graph_data.py` | Test parser with a synthetic mini-wiki in `tmp_path`. |

Naming conventions follow existing patterns: data in `llm/`, UI in `ui/`, tests in `tests/`.

---

## Task 1: Graph data model + parser

**Files:**
- Create: `D:\myLibrary\llm\graph_data.py`
- Create: `D:\myLibrary\tests\test_graph_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_graph_data.py`:

```python
from pathlib import Path
from llm.graph_data import parse_wiki_graph, Graph, Node, Edge


def mini_wiki(tmp_path: Path) -> Path:
    """Set up a tiny synthetic wiki in a temp directory."""
    w = tmp_path / "wiki"
    w.mkdir()
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir()

    # index.md
    (w / "index.md").write_text(
        "# Wiki Index\n\n"
        "## Sources\n"
        "- [Note A](sources/summary_a.md) — a\n"
        "## Entities\n"
        "- [OpenAI](entities/openai.md) — AI lab\n"
        "- [DeepSeek](entities/deepseek.md) — AI lab\n"
        "## Concepts\n"
        "- [ML](concepts/ml.md) — machine learning\n",
        encoding="utf-8",
    )

    # Source page with Related links
    (w / "sources" / "summary_a.md").write_text(
        "# Note A\n\nContent.\n\n"
        "## Related\n\n"
        "- [OpenAI](entities/openai.md)\n"
        "- [ML](concepts/ml.md)\n",
        encoding="utf-8",
    )

    # Entity page (optional — some pages exist without sources)
    (w / "entities" / "openai.md").write_text("# OpenAI\n\nAI lab.\n", encoding="utf-8")
    (w / "entities" / "deepseek.md").write_text("# DeepSeek\n\nAI lab.\n", encoding="utf-8")
    (w / "concepts" / "ml.md").write_text("# ML\n\nField.\n", encoding="utf-8")
    return w


def test_parse_wiki_graph_nodes(mini_wiki):
    g = parse_wiki_graph(mini_wiki)
    nodes = {n.id for n in g.nodes}
    assert "sources/summary_a.md" in nodes
    assert "entities/openai.md" in nodes
    assert "entities/deepseek.md" in nodes
    assert "concepts/ml.md" in nodes
    # DeepSeek is in index but has no edges → still a node
    assert len(g.nodes) == 4


def test_parse_wiki_graph_node_types(mini_wiki):
    g = parse_wiki_graph(mini_wiki)
    by_type = {}
    for n in g.nodes:
        by_type.setdefault(n.kind, []).append(n.id)
    assert len(by_type["source"]) == 1
    assert len(by_type["entity"]) == 2
    assert len(by_type["concept"]) == 1


def test_parse_wiki_graph_edges(mini_wiki):
    g = parse_wiki_graph(mini_wiki)
    edge_keys = {(e.source, e.target) for e in g.edges}
    assert ("sources/summary_a.md", "entities/openai.md") in edge_keys
    assert ("sources/summary_a.md", "concepts/ml.md") in edge_keys
    assert len(g.edges) == 2  # DeepSeek has no incoming edges


def test_parse_wiki_graph_no_related_section(tmp_path):
    w = tmp_path / "wiki"
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir(parents=True)
    (w / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n"
        "## Concepts\n_(none yet)_\n",
        encoding="utf-8",
    )
    (w / "sources" / "summary_a.md").write_text("# A\n\nNo Related section.\n", encoding="utf-8")
    g = parse_wiki_graph(w)
    assert len(g.nodes) >= 1
    assert len(g.edges) == 0


def test_parse_wiki_graph_empty_wiki(tmp_path):
    w = tmp_path / "wiki"
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir(parents=True)
    (w / "index.md").write_text("## Sources\n_(none yet)_\n\n## Entities\n_(none yet)_\n\n## Concepts\n_(none yet)_\n", encoding="utf-8")
    g = parse_wiki_graph(w)
    assert len(g.nodes) == 0
    assert len(g.edges) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.graph_data'`

- [ ] **Step 3: Implement `llm/graph_data.py`**

```python
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

    # ── Extract edges from each source page's ## Related ───────────────
    edges: list[Edge] = []
    related_pat = re.compile(r"^- \[.+?\]\((.+?)\)$")

    for nid, (title, kind) in node_map.items():
        if kind != "source":
            continue
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph_data.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add llm/graph_data.py tests/test_graph_data.py
git commit -m "feat: wiki graph data model and parser from existing wiki links"
```

---

## Task 2: Graph tab with Canvas rendering + force layout

**Files:**
- Create: `D:\myLibrary\ui\graph_tab.py`

- [ ] **Step 1: Write a minimal render test**

Create `tests/test_graph_tab.py` (integration-lite — just that the module imports and the tab frame builds without error):

```python
import tkinter as tk
from pathlib import Path
from llm.graph_data import Graph, Node, Edge

# GraphTab requires a running tk root, so we test the layout logic directly.


def test_force_step_converges():
    """Force layout should move nodes at least initially."""
    from ui.graph_tab import _force_step
    nodes = [
        {"id": "a", "x": 10.0, "y": 10.0},
        {"id": "b", "x": 90.0, "y": 10.0},
        {"id": "c", "x": 50.0, "y": 90.0},
    ]
    edges = [("a", "b"), ("b", "c")]
    moved = _force_step(nodes, edges, width=200, height=200, temp=1.0)
    assert moved > 0.0


def test_graph_tab_creates_frame():
    root = tk.Tk()
    root.withdraw()
    try:
        from ui.graph_tab import GraphTab
        tab = GraphTab(root)
        assert isinstance(tab.frame, tk.Frame)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph_tab.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement `ui/graph_tab.py`**

```python
"""Knowledge graph tab: Canvas-rendered force-directed node-link diagram."""

import math
import tkinter as tk
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass

from llm.graph_data import parse_wiki_graph, Graph, Node as GNode, Edge as GEdge
from ui.cartoon_widgets import (
    FONT_BODY,
    cartoon_label, CartoonButton,
)

# ── constants ────────────────────────────────────────────────────────────

WIDTH, HEIGHT = 680, 440
BG = "#fafbff"

NODE_R = {
    "source":  12,
    "entity":  10,
    "concept":  9,
}

NODE_FILL = {
    "source":  "#a8d4f4",   # sky (matches 输入)
    "entity":  "#a8eedd",   # mint (matches 上传)
    "concept": "#ffe4a8",   # orange (matches 问答)
}

NODE_EDGE_COLOR = {
    "source":  "#5fa8d4",
    "entity":  "#3db88a",
    "concept": "#dba42a",
}

LINK_COLOR = "#d0d8e8"
FONT_NODE = ("Microsoft YaHei", 7)
FORCE_ITERS = 50
DAMPING = 0.85


# ── force layout (module-level, testable without tk) ─────────────────────

def _force_step(
    nodes: list[dict],
    edges: list[tuple[str, str]],
    *,
    width: float,
    height: float,
    temp: float,
) -> float:
    """One iteration of spring-electric force layout.

    Returns total displacement (for convergence check).
    """
    n = len(nodes)
    if n == 0:
        return 0.0

    idx = {nd["id"]: i for i, nd in enumerate(nodes)}
    fx = [0.0] * n
    fy = [0.0] * n

    # Repulsion: all-pairs Coulomb
    k_r = 5000.0
    for i in range(n):
        xi, yi = nodes[i]["x"], nodes[i]["y"]
        for j in range(i + 1, n):
            dx = xi - nodes[j]["x"]
            dy = yi - nodes[j]["y"]
            dist = math.hypot(dx, dy) or 0.01
            force = k_r / (dist * dist)
            fx[i] += (dx / dist) * force
            fy[i] += (dy / dist) * force
            fx[j] -= (dx / dist) * force
            fy[j] -= (dy / dist) * force

    # Attraction: edges are springs
    k_s = 0.06
    rest = 120.0
    for src, tgt in edges:
        i, j = idx.get(src), idx.get(tgt)
        if i is None or j is None:
            continue
        dx = nodes[j]["x"] - nodes[i]["x"]
        dy = nodes[j]["y"] - nodes[i]["y"]
        dist = math.hypot(dx, dy) or 0.01
        force = k_s * (dist - rest)
        fx[i] += (dx / dist) * force
        fy[i] += (dy / dist) * force
        fx[j] -= (dx / dist) * force
        fy[j] -= (dy / dist) * force

    # Center gravity
    cx, cy = width / 2, height / 2
    g_force = 0.008
    for i in range(n):
        fx[i] += (cx - nodes[i]["x"]) * g_force
        fy[i] += (cy - nodes[i]["y"]) * g_force

    # Apply with temperature + damping
    total_move = 0.0
    for i in range(n):
        dx = fx[i] * temp * DAMPING
        dy = fy[i] * temp * DAMPING
        # Clamp per-step movement
        max_step = 25.0
        dx = max(-max_step, min(max_step, dx))
        dy = max(-max_step, min(max_step, dy))
        nodes[i]["x"] = max(30.0, min(width - 30.0, nodes[i]["x"] + dx))
        nodes[i]["y"] = max(30.0, min(height - 30.0, nodes[i]["y"] + dy))
        total_move += abs(dx) + abs(dy)

    return total_move


def _layout(graph: Graph, width: float, height: float) -> list[dict]:
    """Run full force layout, return list of {id, x, y}."""
    nodes: list[dict] = []
    for nd in graph.nodes:
        # Seed around center with small random offset
        import random
        nodes.append({
            "id": nd.id,
            "x": width / 2 + random.uniform(-60, 60),
            "y": height / 2 + random.uniform(-60, 60),
        })

    edges = [(e.source, e.target) for e in graph.edges]

    temp = 3.0
    for _ in range(FORCE_ITERS):
        moved = _force_step(nodes, edges, width=width, height=height, temp=temp)
        temp *= 0.92
        if moved < 0.5:
            break

    return nodes


# ── tab ──────────────────────────────────────────────────────────────────

class GraphTab:
    def __init__(self, parent, bg_color: str = BG,
                 edge_color: str = "#c0cde0", *, main=None) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._main = main
        self._graph: Graph | None = None
        self._layout: list[dict] = []
        self._node_items: dict[str, int] = {}   # node id → canvas oval
        self._label_items: dict[str, int] = {}  # node id → canvas text
        self._edge_items: list[int] = []
        self._drag_idx: int | None = None
        self._pan = {"x": 0.0, "y": 0.0}
        self._pan_start = (0.0, 0.0)
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        # ── toolbar ──────────────────────────────────────────────────────
        bar = tk.Frame(self.frame, bg=self._bg)
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        bar.grid_columnconfigure(1, weight=1)

        cartoon_label(bar, "节点 — 拖拽平移 | 滚轮缩放 | 点击节点打开页面", kind="hint").grid(
            row=0, column=0, sticky="w",
        )

        CartoonButton(
            bar, "🔄 刷新", command=self._reload,
            kind="sky", height=32,
        ).grid(row=0, column=1, padx=(8, 0), sticky="e")

        # ── canvas ───────────────────────────────────────────────────────
        self._canvas = tk.Canvas(
            self.frame, width=WIDTH, height=HEIGHT,
            bg="#fdfdfe", highlightthickness=1,
            highlightbackground="#e0e5f0", borderwidth=0,
        )
        self._canvas.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))

        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<MouseWheel>", self._on_scroll)

        self.frame.after(100, self._reload)

    # ── data ─────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        import config
        self._graph = parse_wiki_graph(config.WIKI_DIR)
        self._layout = _layout(self._graph, WIDTH, HEIGHT)
        self._draw()

    def _draw(self) -> None:
        self._canvas.delete("all")
        self._node_items.clear()
        self._label_items.clear()
        self._edge_items.clear()

        if not self._graph:
            return

        ox, oy = self._pan["x"], self._pan["y"]

        # Edges
        idx = {nd["id"]: (nd["x"] + ox, nd["y"] + oy) for nd in self._layout}
        for e in self._graph.edges:
            if e.source in idx and e.target in idx:
                x1, y1 = idx[e.source]
                x2, y2 = idx[e.target]
                lid = self._canvas.create_line(
                    x1, y1, x2, y2, fill=LINK_COLOR, width=1.5,
                )
                self._canvas.tag_lower(lid)
                self._edge_items.append(lid)

        # Nodes (ovals) + labels
        for nd in self._layout:
            x, y = nd["x"] + ox, nd["y"] + oy
            gnode = self._find_node(nd["id"])
            kind = gnode.kind if gnode else "source"
            r = NODE_R.get(kind, 10)
            fill = NODE_FILL.get(kind, "#ccc")
            outline = NODE_EDGE_COLOR.get(kind, "#999")

            oval = self._canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill=fill, outline=outline, width=2,
                tags=("node", nd["id"]),
            )
            self._node_items[nd["id"]] = oval

            title = gnode.title if gnode else nd["id"]
            label = self._canvas.create_text(
                x + r + 4, y, text=title,
                anchor="w", fill="#2c3e50", font=FONT_NODE,
                tags=("label", nd["id"]),
            )
            self._label_items[nd["id"]] = label

    def _find_node(self, nid: str) -> GNode | None:
        if not self._graph:
            return None
        for n in self._graph.nodes:
            if n.id == nid:
                return n
        return None

    # ── interaction ──────────────────────────────────────────────────────

    def _on_press(self, e) -> None:
        # Check if we hit a node
        item = self._canvas.find_closest(e.x, e.y)
        tags = self._canvas.gettags(item) if item else ()
        for tag in tags:
            if tag.startswith("entities/") or tag.startswith("concepts/") or tag.startswith("sources/"):
                nid = tag
                self._drag_idx = nid
                return
        # Pan
        self._pan_start = (e.x - self._pan["x"], e.y - self._pan["y"])

    def _on_drag(self, e) -> None:
        if self._drag_idx is not None:
            # Drag node
            for nd in self._layout:
                if nd["id"] == self._drag_idx:
                    nd["x"] = e.x - self._pan["x"]
                    nd["y"] = e.y - self._pan["y"]
                    break
            self._draw()
        else:
            self._pan["x"] = e.x - self._pan_start[0]
            self._pan["y"] = e.y - self._pan_start[1]
            self._draw()

    def _on_release(self, e) -> None:
        if self._drag_idx is not None:
            # If didn't drag far, treat as click → open page
            self._drag_idx = None
        # Open reader on click (only if didn't drag)
        ox, oy = self._pan["x"], self._pan["y"]
        for nd in self._layout:
            x, y = nd["x"] + ox, nd["y"] + oy
            if abs(e.x - x) < 24 and abs(e.y - y) < 24:
                self._open_page(nd["id"])
                return
        self._drag_idx = None

    def _on_scroll(self, e) -> None:
        # Zoom via scaling node positions (simple: move toward/away from center)
        scale = 1.1 if e.delta > 0 else 0.9
        cx, cy = WIDTH / 2, HEIGHT / 2
        for nd in self._layout:
            nd["x"] = cx + (nd["x"] - cx) * scale
            nd["y"] = cy + (nd["y"] - cy) * scale
        self._draw()

    def _open_page(self, nid: str) -> None:
        import config
        path = config.WIKI_DIR / nid
        if not path.exists():
            return
        if self._main:
            self._main._open_reader(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph_tab.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add ui/graph_tab.py tests/test_graph_tab.py
git commit -m "feat: interactive force-directed knowledge graph tab"
```

---

## Task 3: Wire graph tab into main window (Ctrl+5)

**Files:**
- Modify: `D:\myLibrary\ui\main_window.py`

- [ ] **Step 1: Add GraphTab import and action tuple**

In `ui/main_window.py`, add the import and extend `ACTIONS`:

At the top (near line 22, after existing tab imports):

```python
from ui.graph_tab import GraphTab
```

In the `ACTIONS` list (near line 44-49), add a 5th entry:

```python
ACTIONS = [
    ("输入", "📖", InputTab,  "Ctrl+1", SKY_PRIMARY, SKY_DARK,  "#e8f4ff", "#a8d4f4"),
    ("上传", "📁", UploadTab, "Ctrl+2", MINT,        "#3db88a", "#ebfaf3", "#a8eedd"),
    ("搜索", "🔍", SearchTab, "Ctrl+3", LAVENDER,    "#7a5acc", "#f3eefc", "#d8cefa"),
    ("问答", "💬", ChatTab,   "Ctrl+4", ORANGE,      "#dba42a", "#fff8e0", "#ffe4a8"),
    ("图谱", "🕸️", GraphTab,  "Ctrl+5", "#9b59b6",   "#7d3c98", "#f5eeff", "#d4b8f0"),
]
```

The new purple/plum theme (`#9b59b6` / `#7d3c98`) sits between lavender and pink.

Add Ctrl+5 shortcut binding (near line 432, after the existing Ctrl+1-4 bindings):

```python
root.bind_all("<Control-Key-5>", lambda _e: self._shortcut_open(4))
```

- [ ] **Step 2: Add sidebar button shape**

The sidebar draws 4 buttons from the `ACTIONS` tuple. Since the tuple now has 5 entries, the `_draw_button` loop in `_Sidebar._build` auto-picks up the 5th button — no code change needed (it iterates `for i, ... in enumerate(ACTIONS)`).

But the sidebar height needs to accommodate 5 buttons. In the `__init__` or `_build` of `_Sidebar`, increase the height calculation. Look for how sidebar `H` is computed (near line 256-258):

Find:
```python
H = BTN_SIZE * len(ACTIONS) + BTN_GAP * (len(ACTIONS) - 1) + PAD * 2
```

This auto-computes for any number of actions, so no change needed.

- [ ] **Step 3: Verify imports and run tests**

Run: `python -m pytest tests/ -q`
Expected: all existing tests pass (80 passed, 1 skipped)

- [ ] **Step 4: Commit**

```bash
git add ui/main_window.py
git commit -m "feat: add knowledge graph tab (Ctrl+5, plum theme)"
```

---

## Task 4: Add _open_reader to MainWindow (needed by GraphTab)

**Files:**
- Modify: `D:\myLibrary\ui\main_window.py`

GraphTab calls `self._main._open_reader(path)`. MainWindow needs a public method to open a wiki page in the existing reader window.

- [ ] **Step 1: Add `_open_reader` method**

In `ui/main_window.py`, add to the MainWindow class (near the `_close_panel` method for locality):

```python
def _open_reader(self, path: Path) -> None:
    """Open a wiki page in the reader window (reuse SearchTab's reader)."""
    from ui.search_tab import _ReaderWindow
    # Reuse existing reader if available, otherwise create one
    if hasattr(self.root, "_active_reader") and self.root._active_reader is not None:
        reader = self.root._active_reader
        reader._load_path(path)
        reader.lift()
    else:
        reader = _ReaderWindow(self.root, path, query="", bg_color="#fafbff", edge_color="#d4b8f0")
        self.root._active_reader = reader
```

- [ ] **Step 2: Commit**

```bash
git add ui/main_window.py
git commit -m "feat: _open_reader method so GraphTab click opens wiki pages"
```

---

## Self-Review

1. **Spec coverage**: Parse wiki → graph ✅ (Task 1). Canvas force layout ✅ (Task 2). Sidebar tab + Ctrl+5 ✅ (Task 3). Click-to-open ✅ (Task 4).

2. **Placeholder scan**: No TBDs. All code shown in full. Synthesized wiki directory uses explicit file names and content. Reader path checks `path.exists()` before opening.

3. **Type consistency**: `Node` dataclass exposes `.id`, `.title`, `.kind` — these names match throughout graph_data.py and graph_tab.py. `_force_step` signature uses `list[dict]` nodes and `list[tuple[str, str]]` edges — consistent between exported function and its test.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-22-knowledge-graph.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
