"""Knowledge graph: standalone resizable window with force-directed node-link diagram."""

import math
import tkinter as tk
from pathlib import Path

from llm.graph_data import parse_wiki_graph, Graph, Node as GNode, Edge as GEdge

# ── constants ────────────────────────────────────────────────────────────

DEFAULT_W, DEFAULT_H = 860, 580
MIN_W, MIN_H = 480, 340
BG = "#fafbff"
TRANSPARENT = "#ff00ff"
TEXT_MAIN = "#2c3e50"
TEXT_LIGHT = "#6b7c8f"

CHROME_H = 38        # title-bar height
GRIP = 28  # resize-edge sensitivity (px)

NODE_R_BASE = {"source": 7, "entity": 6, "concept": 5}
NODE_R_MAX  = {"source": 20, "entity": 16, "concept": 13}
NODE_FILL_LOW = {
    "source":  "#d8effa",
    "entity":  "#d0f5e9",
    "concept": "#fff2d0",
}
NODE_FILL_HIGH = {
    "source":  "#4a9ed4",
    "entity":  "#1d9e6e",
    "concept": "#d49820",
}
NODE_EDGE_HIGH = {
    "source":  "#3a80b0",
    "entity":  "#157a54",
    "concept": "#b07818",
}
LINK_COLOR = "#d0d8e8"
FONT_NODE = ("Microsoft YaHei", 7)
FONT_TITLE = ("Microsoft YaHei", 10, "bold")
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
        self._mode: str | None = None   # None | "drag" | "resize"
        self._resize_edge = ""          # "right", "bottom", or "rightbottom"
        self._drag_origin = (0, 0)
        self._scale = 1.0
        self._maximized = False
        self._restore_geo = ""

        self._build_window()
        self._build_canvas()
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
            self._reload()
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
            self._mode = "node_drag"
            return
        # Background pan
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
            self._open_page(self._drag_nid)
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

    def _on_resize(self, e) -> None:
        if e.widget is not self.win:
            return
        self.w, self.h = e.width, e.height
        self._canvas.place(width=self.w, height=self.h)
        self._canvas.config(width=self.w, height=self.h)
        # Re-draw immediately for smooth resize visuals.
        self._draw()
        # Re-layout after the user stops resizing (debounce 400 ms).
        if hasattr(self, '_relayout_after'):
            self.win.after_cancel(self._relayout_after)
        self._relayout_after = self.win.after(400, self._relayout)

    def _relayout(self) -> None:
        """Re-run force layout for current window size."""
        if not self._graph:
            return
        content_w, content_h = self.w, self.h - CHROME_H
        self._layout_nodes = _layout(self._graph, content_w, content_h)
        self._scale = 1.0
        self._pan = {"x": 0.0, "y": CHROME_H / 2.0}
        self._draw()

    # ── data ─────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        import config
        self._graph = parse_wiki_graph(config.WIKI_DIR)
        self._degrees = self._compute_degrees(self._graph)
        self._max_degree = max(self._degrees.values()) if self._degrees else 1
        content_w, content_h = self.w, self.h - CHROME_H
        self._layout_nodes = _layout(self._graph, content_w, content_h)
        self._scale = 1.0
        self._pan = {"x": 0.0, "y": CHROME_H / 2.0}
        self._draw()

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
        if not self._graph:
            return

        ox, oy = self._pan["x"], self._pan["y"]

        # ── Edges ───────────────────────────────────────────────────────
        for e in self._graph.edges:
            snd = next((n for n in self._layout_nodes if n["id"] == e.source), None)
            tnd = next((n for n in self._layout_nodes if n["id"] == e.target), None)
            if snd and tnd:
                x1 = snd["x"] * self._scale + ox
                y1 = snd["y"] * self._scale + oy + CHROME_H
                x2 = tnd["x"] * self._scale + ox
                y2 = tnd["y"] * self._scale + oy + CHROME_H
                lid = c.create_line(x1, y1, x2, y2, fill=LINK_COLOR, width=1.2)
                c.tag_lower(lid)

        # ── Nodes ───────────────────────────────────────────────────────
        for nd in self._layout_nodes:
            x = nd["x"] * self._scale + ox
            y = nd["y"] * self._scale + oy + CHROME_H
            kind = self._node_kind(nd["id"])
            base_r = NODE_R_BASE.get(kind, 8)
            r = self._deg_r(nd["id"], base_r) * self._scale
            r = max(3, min(24, r))
            fill = self._deg_color(nd["id"])
            outline = NODE_EDGE_HIGH.get(kind, "#777")
            width = 2 if self._degrees.get(nd["id"], 0) >= self._max_degree * 0.5 else 1.5

            c.create_oval(
                x - r, y - r, x + r, y + r,
                fill=fill, outline=outline, width=width,
            )

            title = self._node_title(nd["id"])
            fs = max(6, int(FONT_NODE[1] * self._scale))
            c.create_text(
                x + r + 3, y, text=title,
                anchor="w", fill=TEXT_MAIN, font=(FONT_NODE[0], fs),
            )

        # ── Chrome ──────────────────────────────────────────────────────
        self._draw_chrome()

    def _draw_chrome(self) -> None:
        c = self._canvas
        # Title-bar background
        c.create_rectangle(0, 0, self.w, CHROME_H, fill="#f0ecff", outline="")
        # Bottom separator
        c.create_line(0, CHROME_H, self.w, CHROME_H, fill="#d4b8f0", width=1)

        # Title
        c.create_text(
            12, CHROME_H // 2, text="知识图谱",
            anchor="w", fill=TEXT_MAIN, font=FONT_TITLE,
        )

        node_count = len(self._layout_nodes) if self._layout_nodes else 0
        edge_count = len(self._graph.edges) if self._graph else 0
        c.create_text(
            110, CHROME_H // 2,
            text=f"{node_count} 节点  ·  {edge_count} 关系",
            anchor="w", fill=TEXT_LIGHT, font=("Microsoft YaHei", 8),
        )

        # ── Chrome buttons (right-aligned, right-to-left) ─────────────────
        close_btns = self._chrome_buttons()
        for bx1, by1, bx2, by2, text, bg_c, ol_c in close_btns:
            c.create_polygon(
                [bx1, by1, bx2, by1, bx2, by2, bx1, by2],
                fill=bg_c, outline=ol_c, width=1,
            )
            fs = ("Segoe UI Emoji", 13) if text in ("🔄", "🗖", "🗕") else ("Microsoft YaHei", 9, "bold")
            c.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                          text=text, fill=TEXT_LIGHT, font=fs)

        # Resize grip — lines in bottom-right corner
        grip_x, grip_y = self.w - GRIP, self.h - GRIP
        for i in range(4):
            lx = grip_x + i * 8
            c.create_line(lx, self.h, self.w, grip_y + i * 8,
                          fill="#c8c0d8", width=1.5)
        # Window border
        c.create_rectangle(
            0, 0, self.w - 1, self.h - 1,
            outline="#d4b8f0", width=1,
        )

        # ── Top-10 ranking overlay (right side) ──────────────────────────
        self._draw_ranking()

    def _chrome_buttons(self) -> list[tuple[int, int, int, int, str, str, str]]:
        """Return [(x1,y1,x2,y2, text, bg, outline), ...] right-to-left."""
        BTN_W = 28
        btns = []
        # close, maximize, minimize, refresh — right-to-left
        labels = [("✕", "#fdf2f2", "#f0c0c0"),   # close
                  ("🗖", "#f0ecff", "#c0a8e0"),   # maximize
                  ("🗕", "#f0ecff", "#c0a8e0"),   # minimize
                  ("🔄", "#e8dcf8", "#c0a8e0")]   # refresh
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
        """Return [(nid, title, degree, kind), ...] sorted by degree DESC."""
        if not self._graph:
            return []
        items = []
        for nd in self._graph.nodes:
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

        # Semi-transparent panel background (white with alpha-like opacity)
        c.create_rectangle(
            panel_x - 6, panel_y - 4,
            panel_x + panel_w, panel_y + panel_h,
            fill="#fefeff", outline="#e8e0f0", width=1,
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
        path = config.WIKI_DIR / nid
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
