"""Knowledge graph: standalone resizable window with force-directed node-link diagram."""

import math
import tkinter as tk
from pathlib import Path

from llm.graph_data import parse_wiki_graph, Graph, Node as GNode, Edge as GEdge
from ui.cartoon_widgets import (
    TEXT_MAIN, TEXT_LIGHT, APP_BG, WHITE, GLASS_EDGE, SOFT_SHADOW,
    AMBER_SOFT, PURPLE_SOFT, CARD_BG, SKY_PRIMARY, SKY_LIGHT,
    FONT_BODY, FONT_HINT, FONT_MONO,
    _round_rect_points,
)

# ── constants ────────────────────────────────────────────────────────────

DEFAULT_W, DEFAULT_H = 980, 680
MIN_W, MIN_H = 480, 340
BG = APP_BG
TRANSPARENT = "#ff00ff"

CHROME_H = 38        # title-bar height
GRIP = 28  # resize-edge sensitivity (px)

NODE_R_BASE = {"source": 7, "entity": 6, "concept": 5}
NODE_R_MAX  = {"source": 20, "entity": 16, "concept": 13}
NODE_FILL_LOW = {
    "source":  "#EDE9FE",  # purple-100
    "entity":  "#ECFDF5",  # emerald-50
    "concept": "#FFFBEB",  # amber-50
}
NODE_FILL_HIGH = {
    "source":  "#7C3AED",  # purple-600
    "entity":  "#10B981",  # emerald-500
    "concept": "#F59E0B",  # amber-500
}
NODE_EDGE_HIGH = {
    "source":  "#6D28D9",  # purple-700
    "entity":  "#059669",  # emerald-600
    "concept": "#D97706",  # amber-600
}
LINK_COLOR = "#DDD6FE"
FONT_NODE = ("Microsoft YaHei", 7)
FONT_TITLE = ("Microsoft YaHei", 10, "bold")
NODE_CLICK_THRESHOLD = 5  # px — distinguishes click from drag
FORCE_ITERS = 60
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
    """One iteration of spring-electric force layout. Returns total displacement."""
    n = len(nodes)
    if n == 0:
        return 0.0

    idx = {nd["id"]: i for i, nd in enumerate(nodes)}
    fx = [0.0] * n
    fy = [0.0] * n

    # Repulsion: all-pairs Coulomb
    k_r = 9000.0
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
    k_s = 0.04
    rest = 160.0
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
    g_force = 0.01
    for i in range(n):
        fx[i] += (cx - nodes[i]["x"]) * g_force
        fy[i] += (cy - nodes[i]["y"]) * g_force

    # Apply with temperature + damping
    total_move = 0.0
    for i in range(n):
        dx = fx[i] * temp * DAMPING
        dy = fy[i] * temp * DAMPING
        max_step = 30.0
        dx = max(-max_step, min(max_step, dx))
        dy = max(-max_step, min(max_step, dy))
        nodes[i]["x"] = max(30.0, min(width - 30.0, nodes[i]["x"] + dx))
        nodes[i]["y"] = max(30.0, min(height - 30.0, nodes[i]["y"] + dy))
        total_move += abs(dx) + abs(dy)

    return total_move


def _layout(graph: Graph, width: float, height: float) -> list[dict]:
    """Run full force layout, return list of {id, x, y}."""
    import random
    nodes: list[dict] = []
    for nd in graph.nodes:
        nodes.append({
            "id": nd.id,
            "x": random.uniform(60, width - 60),
            "y": random.uniform(60, height - 60),
        })

    edges = [(e.source, e.target) for e in graph.edges]
    temp = 4.0
    for _ in range(FORCE_ITERS):
        moved = _force_step(nodes, edges, width=width, height=height, temp=temp)
        temp *= 0.90
        if moved < 0.5:
            break

    return nodes


# ── filter helpers (pure, testable without tk) ──────────────────────────────

def filter_nodes(
    graph: Graph,
    *,
    kinds: set[str] | None = None,
    min_degree: int = 0,
    search: str = "",
    degrees: dict[str, int] | None = None,
) -> set[str]:
    """Return set of visible node ids after applying filters."""
    if degrees is None:
        degrees = {}
    search_lower = search.lower().strip()
    visible: set[str] = set()
    for n in graph.nodes:
        if kinds and n.kind not in kinds:
            continue
        if min_degree > 0 and degrees.get(n.id, 0) < min_degree:
            continue
        if search_lower:
            title_match = search_lower in n.title.lower()
            path_match = search_lower in n.id.lower()
            if not title_match and not path_match:
                continue
        visible.add(n.id)
    return visible


def filter_edges(
    graph: Graph,
    visible_ids: set[str],
) -> list[GEdge]:
    """Return edges where both endpoints are visible."""
    return [e for e in graph.edges if e.source in visible_ids and e.target in visible_ids]


def shortest_path(
    edges: list[GEdge],
    source: str,
    target: str,
) -> list[str] | None:
    """BFS shortest path between source and target. Returns node ids or None."""
    if source == target:
        return [source]
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e.source, []).append(e.target)
        adj.setdefault(e.target, []).append(e.source)
    from collections import deque
    visited = {source}
    queue: deque[list[str]] = deque([[source]])
    while queue:
        path = queue.popleft()
        current = path[-1]
        for neighbor in adj.get(current, []):
            if neighbor == target:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])
    return None


TOOLBAR_H = 44  # toolbar height below chrome
DEGREE_FILTERS = [0, 1, 2, 5]  # min degree options
DEGREE_LABELS = ["全部", "1+", "2+", "5+"]

# Quality signal thresholds
HUB_PERCENTILE = 0.8  # top 20% by degree = hub


def graph_diagnostics(
    graph: Graph,
    degrees: dict[str, int],
) -> dict[str, set[str]]:
    """Return sets of node ids with quality issues."""
    if not graph:
        return {"orphan": set(), "missing": set(), "hub": set()}

    max_deg = max(degrees.values()) if degrees else 1
    hub_threshold = max(1, int(max_deg * HUB_PERCENTILE))

    orphans: set[str] = set()
    missing: set[str] = set()
    hubs: set[str] = set()
    one_way_edges: list[tuple[str, str]] = []

    for n in graph.nodes:
        deg = degrees.get(n.id, 0)
        if deg == 0:
            orphans.add(n.id)
        if not n.exists:
            missing.add(n.id)
        if deg >= hub_threshold and deg > 1:
            hubs.add(n.id)

    return {"orphan": orphans, "missing": missing, "hub": hubs}


# ── standalone window ────────────────────────────────────────────────────

class _GraphWindow:
    """Resizable, draggable graph window (no OS chrome).

    Chrome items (title bar, close button, resize handle, refresh button)
    are drawn on the canvas so everything stays inside the transparent-color
    window.
    """

    def __init__(self, root, *, bg_color: str = BG,
                 edge_color: str = "#c0cde0", main=None) -> None:
        self.root = root
        self._bg = bg_color
        self._edge = edge_color
        self._main = main
        self.w = DEFAULT_W
        self.h = DEFAULT_H

        self._graph: Graph | None = None
        self._layout_nodes: list[dict] = []
        self._degrees: dict[str, int] = {}  # node id → connection count
        self._max_degree: int = 1
        self._pan = {"x": 0.0, "y": 0.0}
        self._pan_start = (0.0, 0.0)
        self._drag_nid: str | None = None
        self._node_press_pos: tuple[int, int] = (0, 0)
        self._mode: str | None = None   # None | "drag" | "resize"
        self._resize_edge = ""          # "right", "bottom", or "rightbottom"
        self._drag_origin = (0, 0)
        self._scale = 1.0
        self._maximized = False
        self._restore_geo = ""
        self._in_resize = False

        # Phase 2: filter state
        self._search_query = ""
        self._filter_kinds: set[str] = {"source", "entity", "concept"}
        self._min_degree = 0
        self._visible_ids: set[str] = set()
        self._toolbar_entry: tk.Entry | None = None

        # Phase 3: detail panel
        self._selected_nid: str | None = None
        self._detail_panel: tk.Frame | None = None
        self._detail_visible = False

        # Phase 4: relationship highlighting + path mode
        self._neighbor_ids: set[str] = set()
        self._path_mode = False
        self._path_source: str | None = None
        self._path_target: str | None = None
        self._path_nodes: list[str] = []
        self._path_edges: set[tuple[str, str]] = set()

        # Phase 5: quality signals
        self._show_quality = False
        self._quality_data: dict[str, set[str]] = {"orphan": set(), "missing": set(), "hub": set()}

        # Phase 6: performance
        self._graph_mtime: float = 0.0  # index.md mtime at last parse
        self._label_hide_threshold = 300  # hide labels when node count exceeds this

        self._build_window()
        self._build_canvas()
        self._build_toolbar()
        self._bind_events()
        self.win.after(100, self._reload)

    # ── window ───────────────────────────────────────────────────────────

    def _build_window(self) -> None:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.config(bg=TRANSPARENT)
        win.wm_attributes("-transparentcolor", TRANSPARENT)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = (sw - self.w) // 2
        y = (sh - self.h) // 2
        win.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self.win = win

    def _build_canvas(self) -> None:
        c = tk.Canvas(
            self.win, width=self.w, height=self.h,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        c.place(x=0, y=0, width=self.w, height=self.h)
        self._canvas = c

    def _build_toolbar(self) -> None:
        """Compact toolbar below chrome: search + type toggles + degree filter."""
        tb = tk.Frame(self.win, bg=CARD_BG)
        tb.place(x=0, y=CHROME_H, width=self.w, height=TOOLBAR_H)
        self._toolbar = tb

        # Search entry
        search_frame = tk.Frame(tb, bg=SKY_LIGHT, bd=0)
        search_frame.pack(side="left", padx=(12, 4), pady=6)
        inner = tk.Frame(search_frame, bg=WHITE)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._toolbar_entry = tk.Entry(
            inner, font=FONT_MONO, bg=WHITE, fg=TEXT_MAIN,
            insertbackground=SKY_PRIMARY, relief="flat", borderwidth=0,
            highlightthickness=0, width=16,
        )
        self._toolbar_entry.pack(fill="both", expand=True, padx=6, pady=2)
        self._toolbar_entry.insert(0, "")
        self._toolbar_entry.bind("<KeyRelease>", self._on_search_change)
        self._toolbar_entry.bind("<FocusIn>", lambda _e: self._toolbar_entry.select_range(0, "end"))

        # Placeholder
        self._toolbar_entry._placeholder = "搜索节点..."
        self._toolbar_entry._show_placeholder = True
        self._show_search_placeholder()
        self._toolbar_entry.bind("<FocusIn>", self._on_search_focus_in, add="+")
        self._toolbar_entry.bind("<FocusOut>", self._on_search_focus_out, add="+")

        # Type toggles
        self._kind_btns: dict[str, tk.Label] = {}
        kind_frame = tk.Frame(tb, bg=CARD_BG)
        kind_frame.pack(side="left", padx=4, pady=6)
        for kind, label in [("source", "来源"), ("entity", "实体"), ("concept", "概念")]:
            btn = tk.Label(
                kind_frame, text=label, font=FONT_HINT, fg=TEXT_MAIN,
                bg=SKY_LIGHT, padx=8, pady=2, cursor="hand2",
            )
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>", lambda _e, k=kind: self._toggle_kind(k))
            self._kind_btns[kind] = btn

        # Degree filter
        deg_frame = tk.Frame(tb, bg=CARD_BG)
        deg_frame.pack(side="left", padx=(8, 4), pady=6)
        self._deg_btns: list[tk.Label] = []
        for i, label in enumerate(DEGREE_LABELS):
            btn = tk.Label(
                deg_frame, text=label, font=FONT_HINT, fg=TEXT_MAIN,
                bg=SKY_LIGHT, padx=6, pady=2, cursor="hand2",
            )
            btn.pack(side="left", padx=1)
            btn.bind("<Button-1>", lambda _e, idx=i: self._set_degree(idx))
            self._deg_btns.append(btn)

        # Path mode button
        self._path_btn = tk.Label(
            tb, text="路径", font=FONT_HINT, fg=TEXT_LIGHT,
            bg=SKY_LIGHT, padx=6, pady=2, cursor="hand2",
        )
        self._path_btn.pack(side="right", padx=4, pady=6)
        self._path_btn.bind("<Button-1>", lambda _e: self._toggle_path_mode())

        # Quality overlay button
        self._quality_btn = tk.Label(
            tb, text="质量", font=FONT_HINT, fg=TEXT_LIGHT,
            bg=SKY_LIGHT, padx=6, pady=2, cursor="hand2",
        )
        self._quality_btn.pack(side="right", padx=2, pady=6)
        self._quality_btn.bind("<Button-1>", lambda _e: self._toggle_quality())

        # Reset button
        reset_btn = tk.Label(
            tb, text="重置", font=FONT_HINT, fg=TEXT_LIGHT,
            bg=CARD_BG, padx=6, pady=2, cursor="hand2",
        )
        reset_btn.pack(side="right", padx=(4, 4), pady=6)
        reset_btn.bind("<Button-1>", lambda _e: self._reset_filters())

        self._update_toolbar_styles()

    # ── events ───────────────────────────────────────────────────────────

    def _bind_events(self) -> None:
        c = self._canvas
        c.bind("<Button-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<MouseWheel>", self._on_scroll)
        c.bind("<Motion>", self._on_hover)
        self.win.bind("<Configure>", self._on_resize)

    def _on_press(self, e) -> None:
        # Chrome button bar hit test
        btn = self._btn_at(e.x, e.y)
        if btn == 0:  # close
            self._close()
            return
        if btn == 1:  # maximize
            self._toggle_maximize()
            return
        if btn == 2:  # minimize
            self._iconify()
            return
        if btn == 3:  # refresh
            self._reload(force=True)
            return
        # Resize: any edge within GRIP px
        on_right  = e.x >= self.w - GRIP
        on_bottom = e.y >= self.h - GRIP
        if on_right or on_bottom:
            self._resize_edge = ("right" if on_right else "") + ("bottom" if on_bottom else "")
            self._mode = "resize"
            self._drag_origin = (e.x_root, e.y_root)
            return
        # Title bar drag (left portion only, after buttons skipped above)
        if e.y < CHROME_H and e.x < self._title_drag_zone():
            self._mode = "drag"
            self._drag_origin = (e.x_root - self.win.winfo_x(),
                                 e.y_root - self.win.winfo_y())
            return
        # Node hit test (check after chrome)
        nid = self._hit_node(e.x, e.y)
        if nid is not None:
            self._drag_nid = nid
            self._node_press_pos = (e.x, e.y)
            self._mode = "node_drag"
            return
        # Background click deselects, then pan
        self._select_node(None)
        self._mode = "pan"
        self._pan_start = (e.x - self._pan["x"], e.y - self._pan["y"])

    def _on_motion(self, e) -> None:
        if self._mode == "drag":
            self.win.geometry(
                f"+{e.x_root - self._drag_origin[0]}"
                f"+{e.y_root - self._drag_origin[1]}"
            )
        elif self._mode == "resize":
            dx = e.x_root - self._drag_origin[0]
            dy = e.y_root - self._drag_origin[1]
            nw = self.w + (dx if "right" in self._resize_edge else 0)
            nh = self.h + (dy if "bottom" in self._resize_edge else 0)
            nw = max(MIN_W, nw)
            nh = max(MIN_H, nh)
            if nw != self.w or nh != self.h:
                self.w, self.h = nw, nh
                self.win.geometry(f"{nw}x{nh}")
                self._canvas.place(width=nw, height=nh)
                self._canvas.config(width=nw, height=nh)
                self._drag_origin = (e.x_root, e.y_root)
        elif self._mode == "pan":
            self._pan["x"] = e.x - self._pan_start[0]
            self._pan["y"] = e.y - self._pan_start[1]
            self._draw()
        elif self._mode == "node_drag" and self._drag_nid is not None:
            ox, oy = self._pan["x"], self._pan["y"]
            for nd in self._layout_nodes:
                if nd["id"] == self._drag_nid:
                    nd["x"] = (e.x - ox) / self._scale
                    nd["y"] = (e.y - oy) / self._scale
                    break
            self._draw()

    def _on_release(self, e) -> None:
        if self._mode == "node_drag" and self._drag_nid is not None:
            dx = e.x - self._node_press_pos[0]
            dy = e.y - self._node_press_pos[1]
            if dx * dx + dy * dy < NODE_CLICK_THRESHOLD * NODE_CLICK_THRESHOLD:
                self._select_node(self._drag_nid)
        elif self._mode == "pan":
            # Click on background deselects
            pass
        self._mode = None
        self._drag_nid = None
        self._resize_edge = ""

    def _on_hover(self, e) -> None:
        on_right  = e.x >= self.w - GRIP
        on_bottom = e.y >= self.h - GRIP
        # Chrome buttons override title-bar drag cursor
        if e.y < CHROME_H and self._btn_at(e.x, e.y) is not None:
            self._canvas.config(cursor="hand2")
        elif e.y < CHROME_H and e.x < self._title_drag_zone():
            self._canvas.config(cursor="fleur")
        elif on_right and on_bottom:
            self._canvas.config(cursor="bottom_right_corner")
        elif on_right:
            self._canvas.config(cursor="sb_h_double_arrow")
        elif on_bottom:
            self._canvas.config(cursor="sb_v_double_arrow")
        elif self._hit_node(e.x, e.y) is not None:
            self._canvas.config(cursor="hand2")
        else:
            self._canvas.config(cursor="arrow")

    def _hit_node(self, mx: float, my: float) -> str | None:
        ox, oy = self._pan["x"], self._pan["y"]
        for nd in reversed(self._layout_nodes):
            nx = nd["x"] * self._scale + ox
            ny = nd["y"] * self._scale + oy + CHROME_H
            base_r = NODE_R_BASE.get(self._node_kind(nd["id"]), 8)
            r = self._deg_r(nd["id"], base_r) + 4
            if abs(mx - nx) < r and abs(my - ny) < r:
                return nd["id"]
        return None

    def _on_scroll(self, e) -> None:
        factor = 1.08 if e.delta > 0 else 0.92
        new_scale = max(0.25, min(3.0, self._scale * factor))
        # Zoom toward mouse cursor, not center
        ratio = new_scale / self._scale
        self._pan["x"] = e.x - (e.x - self._pan["x"]) * ratio
        self._pan["y"] = e.y - (e.y - self._pan["y"]) * ratio
        self._scale = new_scale
        self._draw()

    # ── toolbar handlers ─────────────────────────────────────────────────

    def _show_search_placeholder(self) -> None:
        e = self._toolbar_entry
        if e and e._show_placeholder and not e.get():
            e.config(fg="#9CA3AF")
            e.delete(0, "end")
            e.insert(0, e._placeholder)

    def _on_search_focus_in(self, _e) -> None:
        e = self._toolbar_entry
        if e and e._show_placeholder:
            e._show_placeholder = False
            e.delete(0, "end")
            e.config(fg=TEXT_MAIN)

    def _on_search_focus_out(self, _e) -> None:
        e = self._toolbar_entry
        if e and not e.get().strip():
            e._show_placeholder = True
            self._show_search_placeholder()

    def _on_search_change(self, _e) -> None:
        e = self._toolbar_entry
        if e and not e._show_placeholder:
            self._search_query = e.get().strip()
        else:
            self._search_query = ""
        self._apply_filters()

    def _toggle_kind(self, kind: str) -> None:
        if kind in self._filter_kinds:
            if len(self._filter_kinds) > 1:
                self._filter_kinds.discard(kind)
        else:
            self._filter_kinds.add(kind)
        self._apply_filters()

    def _set_degree(self, idx: int) -> None:
        self._min_degree = DEGREE_FILTERS[idx]
        self._apply_filters()

    def _toggle_quality(self) -> None:
        self._show_quality = not self._show_quality
        if self._show_quality:
            self._quality_btn.config(bg="#F59E0B", fg=WHITE)
        else:
            self._quality_btn.config(bg=SKY_LIGHT, fg=TEXT_LIGHT)
        self._draw()

    def _reset_filters(self) -> None:
        self._search_query = ""
        self._filter_kinds = {"source", "entity", "concept"}
        self._min_degree = 0
        self._path_mode = False
        self._path_source = None
        self._path_target = None
        self._path_nodes = []
        self._path_edges = set()
        self._selected_nid = None
        self._neighbor_ids = set()
        self._hide_detail()
        if self._toolbar_entry:
            self._toolbar_entry.delete(0, "end")
            self._toolbar_entry._show_placeholder = True
            self._show_search_placeholder()
        self._update_path_btn_style()
        self._apply_filters()

    def _apply_filters(self) -> None:
        if not self._graph:
            return
        self._visible_ids = filter_nodes(
            self._graph,
            kinds=self._filter_kinds,
            min_degree=self._min_degree,
            search=self._search_query,
            degrees=self._degrees,
        )
        self._update_toolbar_styles()
        self._draw()

    def _update_toolbar_styles(self) -> None:
        for kind, btn in self._kind_btns.items():
            if kind in self._filter_kinds:
                btn.config(bg=SKY_PRIMARY, fg=WHITE)
            else:
                btn.config(bg=SKY_LIGHT, fg=TEXT_LIGHT)
        for i, btn in enumerate(self._deg_btns):
            if DEGREE_FILTERS[i] == self._min_degree:
                btn.config(bg=SKY_PRIMARY, fg=WHITE)
            else:
                btn.config(bg=SKY_LIGHT, fg=TEXT_LIGHT)

    # ── detail panel ─────────────────────────────────────────────────────

    def _select_node(self, nid: str | None) -> None:
        # Path mode: first click = source, second click = target
        if self._path_mode:
            if self._path_source is None:
                self._path_source = nid
                self._selected_nid = nid
                self._compute_neighbors(nid)
                self._draw()
                return
            elif nid and nid != self._path_source:
                self._path_target = nid
                self._find_path()
                self._draw()
                return

        self._selected_nid = nid
        self._path_source = None
        self._path_target = None
        self._path_nodes = []
        self._path_edges = set()
        if nid:
            self._compute_neighbors(nid)
            self._show_detail(nid)
        else:
            self._neighbor_ids = set()
            self._hide_detail()
        self._draw()

    def _compute_neighbors(self, nid: str | None) -> None:
        self._neighbor_ids = set()
        if not nid or not self._graph:
            return
        for e in self._graph.edges:
            if e.source == nid:
                self._neighbor_ids.add(e.target)
            elif e.target == nid:
                self._neighbor_ids.add(e.source)

    def _toggle_path_mode(self) -> None:
        self._path_mode = not self._path_mode
        self._path_source = None
        self._path_target = None
        self._path_nodes = []
        self._path_edges = set()
        if not self._path_mode:
            # Exiting path mode — recompute neighbors for current selection
            self._compute_neighbors(self._selected_nid)
        self._update_path_btn_style()
        self._draw()

    def _update_path_btn_style(self) -> None:
        if hasattr(self, '_path_btn'):
            if self._path_mode:
                self._path_btn.config(bg=SKY_PRIMARY, fg=WHITE)
            else:
                self._path_btn.config(bg=SKY_LIGHT, fg=TEXT_LIGHT)

    def _find_path(self) -> None:
        if not self._graph or not self._path_source or not self._path_target:
            return
        visible_edges = filter_edges(self._graph, self._visible_ids)
        path = shortest_path(visible_edges, self._path_source, self._path_target)
        if path:
            self._path_nodes = path
            self._path_edges = set()
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                self._path_edges.add((a, b))
                self._path_edges.add((b, a))
            # Expand neighbor set to include path nodes
            self._neighbor_ids = set(path)
        else:
            self._path_nodes = []
            self._path_edges = set()

    def _show_detail(self, nid: str) -> None:
        self._hide_detail()
        if not self._graph:
            return

        node = next((n for n in self._graph.nodes if n.id == nid), None)
        if not node:
            return

        panel_w = 220
        panel_h = 280
        px = self.w - panel_w - 12
        py = CHROME_H + TOOLBAR_H + 8

        pf = tk.Frame(self.win, bg=WHITE, highlightbackground=GLASS_EDGE,
                       highlightthickness=1)
        pf.place(x=px, y=py, width=panel_w, height=panel_h)
        self._detail_panel = pf

        # Title
        kind_colors = {"source": "#7C3AED", "entity": "#10B981", "concept": "#F59E0B"}
        kind_color = kind_colors.get(node.kind, "#888")
        kind_labels = {"source": "来源", "entity": "实体", "concept": "概念"}

        header = tk.Frame(pf, bg=WHITE)
        header.pack(fill="x", padx=12, pady=(12, 4))

        tk.Label(header, text=node.title, font=("Microsoft YaHei", 12, "bold"),
                 fg=TEXT_MAIN, bg=WHITE, anchor="w").pack(fill="x")

        tk.Label(header, text=kind_labels.get(node.kind, node.kind),
                 font=FONT_HINT, fg=WHITE, bg=kind_color,
                 padx=6, pady=1).pack(anchor="w", pady=(4, 0))

        # Stats
        deg = self._degrees.get(nid, 0)
        inbound = sum(1 for e in self._graph.edges if e.target == nid)
        outbound = sum(1 for e in self._graph.edges if e.source == nid)

        stats = tk.Frame(pf, bg=WHITE)
        stats.pack(fill="x", padx=12, pady=8)
        for label, value in [("连接度", str(deg)), ("入度", str(inbound)), ("出度", str(outbound))]:
            row = tk.Frame(stats, bg=WHITE)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=FONT_HINT, fg=TEXT_LIGHT,
                     bg=WHITE, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=FONT_BODY, fg=TEXT_MAIN,
                     bg=WHITE, anchor="e").pack(side="right")

        # Path
        path_frame = tk.Frame(pf, bg=WHITE)
        path_frame.pack(fill="x", padx=12, pady=4)
        tk.Label(path_frame, text="路径", font=FONT_HINT, fg=TEXT_LIGHT,
                 bg=WHITE, anchor="w").pack(fill="x")
        tk.Label(path_frame, text=node.path, font=FONT_MONO, fg=TEXT_MAIN,
                 bg=WHITE, anchor="w", wraplength=panel_w - 24).pack(fill="x")

        # Summary
        if node.summary:
            sum_frame = tk.Frame(pf, bg=WHITE)
            sum_frame.pack(fill="x", padx=12, pady=4)
            tk.Label(sum_frame, text="摘要", font=FONT_HINT, fg=TEXT_LIGHT,
                     bg=WHITE, anchor="w").pack(fill="x")
            tk.Label(sum_frame, text=node.summary, font=FONT_HINT, fg=TEXT_MAIN,
                     bg=WHITE, anchor="w", wraplength=panel_w - 24,
                     justify="left").pack(fill="x")

        # Missing page warning
        if not node.exists:
            tk.Label(pf, text="⚠ 页面文件不存在", font=FONT_HINT,
                     fg="#E11D48", bg=WHITE).pack(padx=12, pady=4)

        # Actions
        actions = tk.Frame(pf, bg=WHITE)
        actions.pack(fill="x", padx=12, pady=(8, 12))

        if node.exists:
            open_btn = tk.Label(actions, text="打开页面", font=FONT_HINT,
                                fg=SKY_PRIMARY, bg=WHITE, cursor="hand2")
            open_btn.pack(side="left", padx=(0, 8))
            open_btn.bind("<Button-1>", lambda _e: self._open_page(nid))

        center_btn = tk.Label(actions, text="居中", font=FONT_HINT,
                              fg=SKY_PRIMARY, bg=WHITE, cursor="hand2")
        center_btn.pack(side="left", padx=(0, 8))
        center_btn.bind("<Button-1>", lambda _e: self._center_node(nid))

        copy_btn = tk.Label(actions, text="复制路径", font=FONT_HINT,
                            fg=SKY_PRIMARY, bg=WHITE, cursor="hand2")
        copy_btn.pack(side="left")
        copy_btn.bind("<Button-1>", lambda _e: self._copy_path(nid))

    def _hide_detail(self) -> None:
        if self._detail_panel:
            self._detail_panel.destroy()
            self._detail_panel = None
        self._detail_visible = False

    def _center_node(self, nid: str) -> None:
        for nd in self._layout_nodes:
            if nd["id"] == nid:
                self._pan["x"] = self.w / 2 - nd["x"] * self._scale
                self._pan["y"] = (self.h - CHROME_H - TOOLBAR_H) / 2 - nd["y"] * self._scale
                self._draw()
                break

    def _copy_path(self, nid: str) -> None:
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(nid)
        except tk.TclError:
            pass

    def _on_resize(self, e) -> None:
        if e.widget is not self.win:
            return
        if self._in_resize:
            return
        self._in_resize = True
        try:
            self.w, self.h = e.width, e.height
            self._canvas.place(width=self.w, height=self.h)
            self._canvas.config(width=self.w, height=self.h)
            if hasattr(self, '_toolbar') and self._toolbar:
                self._toolbar.place(width=self.w)
            self._hide_detail()
            self._draw()
            if hasattr(self, '_relayout_after'):
                self.win.after_cancel(self._relayout_after)
            self._relayout_after = self.win.after(400, self._relayout)
        finally:
            self._in_resize = False

    def _relayout(self) -> None:
        """Re-run force layout for current window size."""
        if not self._graph:
            return
        content_w, content_h = self.w, self.h - CHROME_H - TOOLBAR_H
        self._layout_nodes = _layout(self._graph, content_w, content_h)
        self._scale = 1.0
        self._pan = {"x": 0.0, "y": (CHROME_H + TOOLBAR_H) / 2.0}
        self._draw()

    # ── data ─────────────────────────────────────────────────────────────

    def _reload(self, *, force: bool = False) -> None:
        import config
        idx_path = config.WIKI_DIR / "index.md"
        current_mtime = idx_path.stat().st_mtime if idx_path.exists() else 0.0

        # Cache: skip reparse if index.md hasn't changed
        if not force and self._graph and current_mtime == self._graph_mtime:
            self._apply_filters()
            return

        self._graph = parse_wiki_graph(config.WIKI_DIR)
        self._graph_mtime = current_mtime
        self._degrees = self._compute_degrees(self._graph)
        self._max_degree = max(self._degrees.values()) if self._degrees else 1
        self._quality_data = graph_diagnostics(self._graph, self._degrees)
        content_w, content_h = self.w, self.h - CHROME_H - TOOLBAR_H
        self._layout_nodes = _layout(self._graph, content_w, content_h)
        self._scale = 1.0
        self._pan = {"x": 0.0, "y": (CHROME_H + TOOLBAR_H) / 2.0}
        self._apply_filters()

    @staticmethod
    def _compute_degrees(g: Graph) -> dict[str, int]:
        deg: dict[str, int] = {}
        for e in g.edges:
            deg[e.source] = deg.get(e.source, 0) + 1
            deg[e.target] = deg.get(e.target, 0) + 1
        # ensure every node has at least 0
        for n in g.nodes:
            deg.setdefault(n.id, 0)
        return deg

    def _deg_r(self, nid: str, base: float) -> float:
        d = self._degrees.get(nid, 0)
        if self._max_degree <= 0:
            return base
        frac = d / self._max_degree
        return base + frac * (NODE_R_MAX.get(self._node_kind(nid), 14) - base)

    def _deg_color(self, nid: str) -> str:
        d = self._degrees.get(nid, 0)
        frac = (d / self._max_degree) if self._max_degree > 0 else 0.0
        lo = NODE_FILL_LOW.get(self._node_kind(nid), "#e0e0e0")
        hi = NODE_FILL_HIGH.get(self._node_kind(nid), "#888888")
        return self._lerp_color(lo, hi, frac)

    @staticmethod
    def _lerp_color(c_lo: str, c_hi: str, t: float) -> str:
        r1, g1, b1 = int(c_lo[1:3], 16), int(c_lo[3:5], 16), int(c_lo[5:7], 16)
        r2, g2, b2 = int(c_hi[1:3], 16), int(c_hi[3:5], 16), int(c_hi[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _node_kind(self, nid: str) -> str:
        if not self._graph:
            return "source"
        for n in self._graph.nodes:
            if n.id == nid:
                return n.kind
        return "source"

    def _node_title(self, nid: str) -> str:
        if not self._graph:
            return nid
        for n in self._graph.nodes:
            if n.id == nid:
                return n.title
        return nid

    def _draw(self) -> None:
        c = self._canvas
        c.delete("all")
        self._draw_shell()
        if not self._graph:
            self._draw_chrome()
            return

        ox, oy = self._pan["x"], self._pan["y"]
        visible = self._visible_ids
        has_selection = self._selected_nid is not None and self._neighbor_ids
        show_labels = len(self._layout_nodes) < self._label_hide_threshold or self._scale > 1.2
        has_path = bool(self._path_nodes)

        # ── Edges ───────────────────────────────────────────────────────
        for e in self._graph.edges:
            if e.source not in visible or e.target not in visible:
                continue
            snd = next((n for n in self._layout_nodes if n["id"] == e.source), None)
            tnd = next((n for n in self._layout_nodes if n["id"] == e.target), None)
            if snd and tnd:
                x1 = snd["x"] * self._scale + ox
                y1 = snd["y"] * self._scale + oy + CHROME_H + TOOLBAR_H
                x2 = tnd["x"] * self._scale + ox
                y2 = tnd["y"] * self._scale + oy + CHROME_H + TOOLBAR_H

                # Path edge highlighting
                edge_key = (e.source, e.target)
                if has_path and edge_key in self._path_edges:
                    c.create_line(x1, y1, x2, y2, fill="#F59E0B", width=3)
                elif has_selection:
                    connected = (e.source == self._selected_nid or e.target == self._selected_nid)
                    color = LINK_COLOR if connected else "#F0F0F0"
                    c.create_line(x1, y1, x2, y2, fill=color, width=1.2)
                else:
                    lid = c.create_line(x1, y1, x2, y2, fill=LINK_COLOR, width=1.2)
                    c.tag_lower(lid)

        # ── Nodes ───────────────────────────────────────────────────────
        for nd in self._layout_nodes:
            if nd["id"] not in visible:
                continue
            x = nd["x"] * self._scale + ox
            y = nd["y"] * self._scale + oy + CHROME_H + TOOLBAR_H
            kind = self._node_kind(nd["id"])
            base_r = NODE_R_BASE.get(kind, 8)
            r = self._deg_r(nd["id"], base_r) * self._scale
            r = max(3, min(24, r))
            fill = self._deg_color(nd["id"])
            outline = NODE_EDGE_HIGH.get(kind, "#777")
            w = 2 if self._degrees.get(nd["id"], 0) >= self._max_degree * 0.5 else 1.5

            # Dim non-neighbors when selection active
            if has_selection and nd["id"] != self._selected_nid and nd["id"] not in self._neighbor_ids:
                fill = "#E5E7EB"
                outline = "#D1D5DB"

            # Highlight matching nodes when search is active
            if self._search_query:
                title_lower = self._node_title(nd["id"]).lower()
                path_lower = nd["id"].lower()
                if self._search_query.lower() in title_lower or self._search_query.lower() in path_lower:
                    outline = "#F59E0B"  # amber highlight
                    w = 3

            # Path node highlighting
            if has_path and nd["id"] in self._path_nodes:
                outline = "#F59E0B"
                w = 3

            # Highlight selected node
            if nd["id"] == self._selected_nid:
                outline = "#F59E0B"
                w = 3
                c.create_oval(
                    x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                    fill="", outline="#FDE68A", width=2,
                )

            c.create_oval(
                x - r, y - r, x + r, y + r,
                fill=fill, outline=outline, width=w,
            )

            # Quality overlays
            if self._show_quality:
                if nd["id"] in self._quality_data.get("orphan", set()):
                    # Dashed outline for orphans
                    c.create_oval(
                        x - r - 2, y - r - 2, x + r + 2, y + r + 2,
                        fill="", outline="#9CA3AF", width=1, dash=(3, 3),
                    )
                if nd["id"] in self._quality_data.get("missing", set()):
                    # Red warning outline for missing pages
                    c.create_oval(
                        x - r - 2, y - r - 2, x + r + 2, y + r + 2,
                        fill="", outline="#E11D48", width=2,
                    )
                if nd["id"] in self._quality_data.get("hub", set()):
                    # Ring for dense hubs
                    c.create_oval(
                        x - r - 4, y - r - 4, x + r + 4, y + r + 4,
                        fill="", outline="#F59E0B", width=1,
                    )

            # Labels: hide for large graphs unless zoomed in
            if show_labels:
                title = self._node_title(nd["id"])
                fs = max(6, int(FONT_NODE[1] * self._scale))
                c.create_text(
                    x + r + 3, y, text=title,
                    anchor="w", fill=TEXT_MAIN, font=(FONT_NODE[0], fs),
                )

        # ── Chrome ──────────────────────────────────────────────────────
        self._draw_chrome()

    def _draw_shell(self) -> None:
        c = self._canvas
        c.create_rectangle(0, 0, self.w, self.h, fill=TRANSPARENT, outline="")
        c.create_polygon(
            _round_rect_points(0, 7, self.w, self.h, 24),
            smooth=True, fill=SOFT_SHADOW, outline="",
        )
        c.create_polygon(
            _round_rect_points(0, 0, self.w, self.h - 7, 24),
            smooth=True, fill=self._bg, outline=GLASS_EDGE, width=1,
        )
        c.create_oval(max(22, self.w - 300), 18, self.w - 34, 220, fill=AMBER_SOFT, outline="")
        c.create_oval(22, 18, min(300, self.w - 34), 220, fill=PURPLE_SOFT, outline="")

    def _draw_chrome(self) -> None:
        c = self._canvas
        # Title-bar background
        c.create_rectangle(1, 1, self.w - 2, CHROME_H, fill="", outline="")
        # Bottom separator
        c.create_line(24, CHROME_H, self.w - 24, CHROME_H, fill=GLASS_EDGE, width=1)

        # Title
        c.create_text(
            12, CHROME_H // 2, text="知识图谱",
            anchor="w", fill=TEXT_MAIN, font=FONT_TITLE,
        )

        node_count = len(self._visible_ids) if self._visible_ids else 0
        total_nodes = len(self._graph.nodes) if self._graph else 0
        edge_count = len(filter_edges(self._graph, self._visible_ids)) if self._graph else 0
        if node_count == total_nodes:
            count_text = f"{node_count} 节点  ·  {edge_count} 关系"
        else:
            count_text = f"{node_count}/{total_nodes} 节点  ·  {edge_count} 关系"
        c.create_text(
            110, CHROME_H // 2,
            text=count_text,
            anchor="w", fill=TEXT_LIGHT, font=("Microsoft YaHei", 8),
        )

        # ── Chrome buttons (right-aligned, right-to-left) ─────────────────
        close_btns = self._chrome_buttons()
        for bx1, by1, bx2, by2, text, bg_c, ol_c in close_btns:
            c.create_polygon(
                _round_rect_points(bx1, by1, bx2, by2, 8),
                smooth=True, fill=bg_c, outline=ol_c, width=1,
            )
            fs = ("Segoe UI Emoji", 13) if text in ("🔄", "🗖", "🗕") else ("Microsoft YaHei", 9, "bold")
            c.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                          text=text, fill=TEXT_LIGHT, font=fs)

        # Resize grip — lines in bottom-right corner
        grip_x, grip_y = self.w - GRIP, self.h - GRIP
        for i in range(4):
            lx = grip_x + i * 8
            c.create_line(lx, self.h, self.w, grip_y + i * 8,
                          fill="#C4B5FD", width=1.5)

        # ── Top-10 ranking overlay (right side) ──────────────────────────
        self._draw_ranking()

    def _chrome_buttons(self) -> list[tuple[int, int, int, int, str, str, str]]:
        """Return [(x1,y1,x2,y2, text, bg, outline), ...] right-to-left."""
        BTN_W = 28
        btns = []
        # close, maximize, minimize, refresh — right-to-left
        labels = [("✕", "#FFF1F2", "#FECDD3"),   # close (rose)
                  ("🗖", "#F5F3FF", "#C4B5FD"),   # maximize (purple)
                  ("🗕", "#F5F3FF", "#C4B5FD"),   # minimize (purple)
                  ("🔄", "#F5F3FF", "#C4B5FD")]   # refresh (purple)
        x2 = self.w - 8
        for text, bg_c, ol_c in labels:
            x1 = x2 - BTN_W
            btns.append((x1, 4, x2, CHROME_H - 4, text, bg_c, ol_c))
            x2 = x1 - 6
        return btns

    def _btn_at(self, x: int, y: int) -> int | None:
        """Return button index (0=close, 1=max, 2=min, 3=refresh) or None."""
        if not (0 <= y <= CHROME_H):
            return None
        for i, (bx1, by1, bx2, by2, *_unused) in enumerate(self._chrome_buttons()):
            if bx1 <= x <= bx2:
                return i
        return None

    def _title_drag_zone(self) -> int:
        """Return the x-coordinate where draggable title area ends (buttons begin)."""
        btns = self._chrome_buttons()
        if not btns:
            return self.w
        return min(b[0] for b in btns)  # left edge of the leftmost button

    def _top_ranked(self, n: int = 10) -> list[tuple[str, str, int, str]]:
        """Return [(nid, title, degree, kind), ...] sorted by degree DESC, visible only."""
        if not self._graph:
            return []
        items = []
        for nd in self._graph.nodes:
            if self._visible_ids and nd.id not in self._visible_ids:
                continue
            deg = self._degrees.get(nd.id, 0)
            if deg > 0:
                items.append((nd.id, nd.title, deg, nd.kind))
        items.sort(key=lambda t: t[2], reverse=True)
        return items[:n]

    def _draw_ranking(self) -> None:
        c = self._canvas
        items = self._top_ranked(10)
        if not items:
            return
        panel_w = 170
        panel_x = self.w - panel_w - 12
        panel_y = CHROME_H + 8
        row_h = 19
        panel_h = len(items) * row_h + 30

        c.create_polygon(
            _round_rect_points(
            panel_x - 6, panel_y - 4,
            panel_x + panel_w, panel_y + panel_h,
                10,
            ),
            smooth=True, fill=WHITE, outline=GLASS_EDGE, width=1,
        )
        c.create_text(
            panel_x + panel_w // 2, panel_y + 4,
            text="Top 10 连接度", fill=TEXT_MAIN,
            font=("Microsoft YaHei", 8, "bold"),
        )

        for rank, (nid, title, deg, kind) in enumerate(items):
            ry = panel_y + row_h + rank * row_h
            r = 4
            fill = NODE_FILL_HIGH.get(kind, "#ccc")
            c.create_oval(panel_x, ry - r, panel_x + r * 2, ry + r,
                          fill=fill, outline="", width=0)
            # Truncate title if too long
            short = title if len(title) <= 14 else title[:13] + "…"
            c.create_text(
                panel_x + 12, ry, text=f"{short}",
                anchor="w", fill=TEXT_MAIN, font=("Microsoft YaHei", 7),
            )
            c.create_text(
                panel_x + panel_w - 6, ry, text=str(deg),
                anchor="e", fill=TEXT_LIGHT, font=("Microsoft YaHei", 7, "bold"),
            )

    # ── hit-test helpers ─────────────────────────────────────────────────

    # ── actions ──────────────────────────────────────────────────────────

    def _open_page(self, nid: str) -> None:
        import config
        path = (config.WIKI_DIR / nid).resolve()
        if not path.is_relative_to(config.WIKI_DIR.resolve()):
            return
        if not path.exists():
            return
        if self._main:
            self._main._open_reader(path)

    def _toggle_maximize(self) -> None:
        if not self._maximized:
            self._restore_geo = self.win.geometry()
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
            self.win.geometry(f"{sw}x{sh}+0+0")
            self._maximized = True
        else:
            self.win.geometry(self._restore_geo)
            self._maximized = False

    def _iconify(self) -> None:
        self.win.iconify()

    def _close(self) -> None:
        if self._main:
            self._main._close_graph()
        self.win.destroy()


# ── thin proxy for panel system (not used directly — _toggle_panel special-cases it) ──

class GraphTab:
    """Sentinel class so the ACTIONS tuple can reference a tab-like symbol."""
    pass
