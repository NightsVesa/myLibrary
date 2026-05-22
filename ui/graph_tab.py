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
