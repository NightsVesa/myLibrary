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

CHROME_H = 32        # title-bar height
GRIP = 28  # resize-edge sensitivity (px)

NODE_R = {"source": 12, "entity": 10, "concept": 9}
NODE_FILL = {
    "source":  "#a8d4f4",
    "entity":  "#a8eedd",
    "concept": "#ffe4a8",
}
NODE_EDGE = {
    "source":  "#5fa8d4",
    "entity":  "#3db88a",
    "concept": "#dba42a",
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
    k_r = 6000.0
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
    k_s = 0.05
    rest = 130.0
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
            "x": width / 2 + random.uniform(-80, 80),
            "y": height / 2 + random.uniform(-80, 80),
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
        self._pan = {"x": 0.0, "y": 0.0}
        self._pan_start = (0.0, 0.0)
        self._drag_nid: str | None = None
        self._mode: str | None = None   # None | "drag" | "resize"
        self._resize_edge = ""          # "right", "bottom", or "rightbottom"
        self._drag_origin = (0, 0)
        self._scale = 1.0

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
        # Close-button hit test
        if self._hit_close(e.x, e.y):
            self._close()
            return
        # Refresh-button hit test
        if self._hit_refresh(e.x, e.y):
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
        # Title bar drag
        if e.y < CHROME_H:
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
        # Title bar cursor
        if e.y < CHROME_H and not on_right:
            self._canvas.config(cursor="fleur")
        elif on_right and on_bottom:
            self._canvas.config(cursor="sizing_se")
        elif on_right:
            self._canvas.config(cursor="sizing_e")
        elif on_bottom:
            self._canvas.config(cursor="sizing_s")
        # Hover on a node → hand cursor
        elif self._hit_node(e.x, e.y) is not None:
            self._canvas.config(cursor="hand2")
        else:
            self._canvas.config(cursor="arrow")

    def _hit_node(self, mx: float, my: float) -> str | None:
        ox, oy = self._pan["x"], self._pan["y"]
        for nd in reversed(self._layout_nodes):
            nx = nd["x"] * self._scale + ox
            ny = nd["y"] * self._scale + oy + CHROME_H
            r = NODE_R.get(self._node_kind(nd["id"]), 10) + 4
            if abs(mx - nx) < r and abs(my - ny) < r:
                return nd["id"]
        return None

    def _on_scroll(self, e) -> None:
        factor = 1.08 if e.delta > 0 else 0.92
        self._scale = max(0.25, min(3.0, self._scale * factor))
        self._draw()

    def _on_resize(self, e) -> None:
        if e.widget is not self.win:
            return
        self.w, self.h = e.width, e.height
        self._canvas.place(width=self.w, height=self.h)
        self._canvas.config(width=self.w, height=self.h)
        self._draw()

    # ── data ─────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        import config
        self._graph = parse_wiki_graph(config.WIKI_DIR)
        content_w, content_h = self.w, self.h - CHROME_H
        self._layout_nodes = _layout(self._graph, content_w, content_h)
        self._scale = 1.0
        self._pan = {"x": 0.0, "y": CHROME_H / 2.0}
        self._draw()

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
            r = NODE_R.get(kind, 10) * self._scale
            r = max(4, min(20, r))
            fill = NODE_FILL.get(kind, "#ccc")
            outline = NODE_EDGE.get(kind, "#999")

            c.create_oval(
                x - r, y - r, x + r, y + r,
                fill=fill, outline=outline, width=2,
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

        # Refresh button
        rfx1, rfy1, rfx2, rfy2 = self._refresh_rect()
        c.create_polygon(
            [rfx1, rfy1, rfx2, rfy1, rfx2, rfy2, rfx1, rfy2],
            fill="#e8dcf8", outline="#c0a8e0", width=1,
        )
        c.create_text(
            (rfx1 + rfx2) // 2, (rfy1 + rfy2) // 2,
            text="🔄", font=("Segoe UI Emoji", 11),
        )

        # Close button
        cx1, cy1, cx2, cy2 = self._close_rect()
        c.create_polygon(
            [cx1, cy1, cx2, cy1, cx2, cy2, cx1, cy2],
            fill="#fdf2f2", outline="#f0c0c0", width=1,
        )
        c.create_text(
            (cx1 + cx2) // 2, (cy1 + cy2) // 2,
            text="✕", fill=TEXT_LIGHT, font=("Microsoft YaHei", 8, "bold"),
        )

        # Resize grip — lines in bottom-right corner
        grip_x, grip_y = self.w - GRIP, self.h - GRIP
        for i in range(4):
            lx = grip_x + i * 8
            c.create_line(lx, self.h, self.w, grip_y + i * 8,
                          fill="#c8c0d8", width=1.5)
        # Also draw a subtle edge highlight on the right+bottom border
        c.create_rectangle(
            0, 0, self.w - 1, self.h - 1,
            outline="#d4b8f0", width=1,
        )

    # ── hit-test helpers ─────────────────────────────────────────────────

    def _refresh_rect(self) -> tuple[int, int, int, int]:
        """(x1, y1, x2, y2) for the refresh button."""
        return (self.w - 68, 4, self.w - 30, CHROME_H - 4)

    def _close_rect(self) -> tuple[int, int, int, int]:
        return (self.w - 26, 4, self.w - 6, CHROME_H - 4)

    def _hit_close(self, x: int, y: int) -> bool:
        cx1, cy1, cx2, cy2 = self._close_rect()
        return cx1 <= x <= cx2 and cy1 <= y <= cy2

    def _hit_refresh(self, x: int, y: int) -> bool:
        rfx1, rfy1, rfx2, rfy2 = self._refresh_rect()
        return rfx1 <= x <= rfx2 and rfy1 <= y <= rfy2

    # ── actions ──────────────────────────────────────────────────────────

    def _open_page(self, nid: str) -> None:
        import config
        path = config.WIKI_DIR / nid
        if not path.exists():
            return
        if self._main:
            self._main._open_reader(path)

    def _close(self) -> None:
        if self._main:
            self._main._close_graph()
        self.win.destroy()


# ── thin proxy for panel system (not used directly — _toggle_panel special-cases it) ──

class GraphTab:
    """Sentinel class so the ACTIONS tuple can reference a tab-like symbol."""
    pass
