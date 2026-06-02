import logging as _err_log
import math
import queue
import re
import threading
import time
import traceback
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH
from ttkbootstrap.dialogs import Messagebox
from PIL import ImageTk
from tkinterdnd2 import DND_FILES

from config import APP_TITLE, ASSETS_DIR
from storage.note_store import save_raw_file

from ui.cartoon_widgets import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_BODY_BOLD, FONT_SHORTCUT, FONT_HINT, FONT_INPUT,
    CartoonButton,
    hex_to_rgb as _hex_to_rgb_shared, make_card_png as _shared_card_png,
    SKY_DARK,
    WHITE, TEXT_MAIN, TEXT_LIGHT, DASH_LINE, APP_BG, CARD_BG, GLASS_EDGE, SOFT_SHADOW,
    AMBER_SOFT, PURPLE_SOFT,
    PINK,
)
from ui.input_tab import InputTab
from ui.upload_tab import UploadTab, SUPPORTED as UPLOAD_HANDLERS
from ui.search_tab import SearchTab
from ui.chat_tab import ChatTab
from ui.graph_tab import GraphTab, _GraphWindow
from ui.lint_tab import LintTab

PET_DIR = ASSETS_DIR
PET_STATES = ("idle", "attack", "happy", "sleep", "eat")
TRANSPARENT = "#ff00ff"

# Per-action: label, emoji, tab_class, hint, btn body, btn shadow, panel pale-bg, panel edge
ACTIONS = [
    ("输入", "📖", InputTab,  "Ctrl+1", "#7C3AED", "#6D28D9", "#F5F3FF", "#DDD6FE"),
    ("上传", "📁", UploadTab, "Ctrl+2", "#10B981", "#059669", "#ECFDF5", "#A7F3D0"),
    ("搜索", "🔍", SearchTab, "Ctrl+3", "#8B5CF6", "#7C3AED", "#F5F3FF", "#C4B5FD"),
    ("问答", "💬", ChatTab,   "Ctrl+4", "#F59E0B", "#D97706", "#FFFBEB", "#FDE68A"),
    ("图谱", "🕸️", GraphTab,  "Ctrl+5", "#6366F1", "#4F46E5", "#EEF2FF", "#C7D2FE"),
    ("体检", "🩺", LintTab,  "Ctrl+6", "#F43F5E", "#E11D48", "#FFF1F2", "#FECDD3"),
]

# Pet behaviour
DRAG_THRESHOLD_PX = 4
HAPPY_HOLD_MS = 1200
SLEEP_IDLE_MS = 30_000
SPRITE_PAD_Y = 36
SPRITE_PAD_X = 16
TICK_MS = 33

# Sidebar geometry (matches HTML sidebar-toolbar)
BTN_SIZE = 50
BTN_GAP = 10
BTN_RADIUS = 12
BTN_SHADOW = 2
SIDEBAR_PAD = 12
SIDEBAR_RADIUS = 18
SIDEBAR_SHADOW = 3

# Panel geometry
PANEL_W, PANEL_H = 680, 760
PANEL_RADIUS = 24
PANEL_SHADOW = 8
PANEL_TITLE_H = 64
PANEL_BODY_PAD = 26
PANEL_GRIP = 24          # resize-edge sensitivity (px)
PANEL_MIN_W = 520
PANEL_MIN_H = 480
PANEL_RESIZE_DEBOUNCE_MS = 100


# ── Helpers ─────────────────────────────────────────────────────────────────

_hex_to_rgb = _hex_to_rgb_shared


def _lighten_local(hex_color: str, factor: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _round_rect_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def _draw_soft_glow(canvas, w, h, *, tags=None):
    """Canvas-only light accents kept inside the visible card."""
    canvas.create_oval(
        max(18, w - 260), 16, w - 28, 180,
        fill=AMBER_SOFT, outline="", tags=tags,
    )
    canvas.create_oval(
        18, 14, min(260, w - 32), 190,
        fill=PURPLE_SOFT, outline="", tags=tags,
    )


def _draw_white_icon(canvas, kind, *, cx, cy, color="white"):
    """Draw a small white vector icon centred at (cx, cy).

    `kind` is the emoji identifier from ACTIONS — we just dispatch on it.
    Used on sidebar buttons where emoji glyphs render too dimly.
    """
    if kind in ("📖", "📚", "✍"):
        # Open book — two pages joined at a center spine.  The spine dips
        # slightly so the silhouette reads as a book rather than two squares.
        w_half = 13
        top_y = cy - 9
        bot_y = cy + 11
        center_top_y = cy - 6      # spine dips down a few px
        center_bot_y = cy + 9
        # Left page
        canvas.create_polygon(
            cx - w_half, top_y,
            cx,          center_top_y,
            cx,          center_bot_y,
            cx - w_half, bot_y,
            fill=color, outline="",
        )
        # Right page
        canvas.create_polygon(
            cx,          center_top_y,
            cx + w_half, top_y,
            cx + w_half, bot_y,
            cx,          center_bot_y,
            fill=color, outline="",
        )
        # Suggested page-lines on each side
        for off in (-1, 2, 5):
            canvas.create_line(
                cx - w_half + 3, cy + off,
                cx - 3,          cy + off,
                fill="#cfe7ff", width=1,
            )
            canvas.create_line(
                cx + 3,          cy + off,
                cx + w_half - 3, cy + off,
                fill="#cfe7ff", width=1,
            )
    elif kind in ("📁", "📂"):
        # Folder — tab on top-left + main body
        canvas.create_polygon(
            cx - 12, cy - 8,  cx - 4, cy - 8,
            cx - 1, cy - 4,   cx + 12, cy - 4,
            cx + 12, cy + 9,  cx - 12, cy + 9,
            fill=color, outline="",
        )
        # Subtle inner notch (lighter shade hint via thin line — use body color)
        canvas.create_line(
            cx - 12, cy - 4, cx + 12, cy - 4,
            fill="#ffffff", width=1,
        )
    elif kind == "🔍":
        # Magnifier — circle + diagonal handle
        canvas.create_oval(
            cx - 12, cy - 12, cx + 4, cy + 4,
            outline=color, width=4,
        )
        canvas.create_line(
            cx + 3, cy + 3, cx + 13, cy + 13,
            fill=color, width=5, capstyle="round",
        )
    elif kind == "💬":
        bx1, by1 = cx - 12, cy - 10
        bx2, by2 = cx + 12, cy + 6
        canvas.create_polygon(
            bx1 + 4, by1,  bx2 - 4, by1,  bx2, by1,
            bx2, by1 + 4,  bx2, by2 - 4,  bx2, by2,
            bx2 - 4, by2,  bx1 + 4, by2,  bx1, by2,
            bx1, by2 - 4,  bx1, by1 + 4,  bx1, by1,
            smooth=True, fill=color, outline="",
        )
        canvas.create_polygon(
            cx - 4, by2, cx + 2, by2, cx - 6, by2 + 7,
            fill=color, outline="",
        )
        for dx in (-5, 0, 5):
            canvas.create_oval(
                cx + dx - 2, cy - 4, cx + dx + 2, cy,
                fill="#cfe7ff", outline="",
            )
    else:
        # Fallback: text glyph rendered with emoji font
        canvas.create_text(
            cx, cy, text=kind, fill=color,
            font=("Segoe UI Emoji", 18),
        )


_make_card_png = _shared_card_png


# ── Sidebar (single Toplevel containing N cartoon icon buttons) ─────────────

class _Sidebar:
    def __init__(self, root, actions, on_click_idx, on_leave):
        self.actions = actions
        self.on_click_idx = on_click_idx
        self.on_leave = on_leave
        n = len(actions)

        # Visible card area = pad*2 + buttons + gaps; shadow adds a few px below.
        body_w = SIDEBAR_PAD * 2 + BTN_SIZE
        body_h = SIDEBAR_PAD * 2 + BTN_SIZE * n + BTN_GAP * (n - 1)
        self.W = body_w
        self.H = body_h + SIDEBAR_SHADOW

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.config(bg=TRANSPARENT)
        try:
            self.win.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.win.geometry(f"{self.W}x{self.H}")

        # Pre-rendered glass toolbar background.
        bg_pil = _make_card_png(
            self.W, self.H, SIDEBAR_RADIUS,
            CARD_BG, GLASS_EDGE, SOFT_SHADOW, SIDEBAR_SHADOW,
        )
        self._bg_photo = ImageTk.PhotoImage(bg_pil)

        self.canvas = tk.Canvas(
            self.win, width=self.W, height=self.H,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        self.canvas.place(x=0, y=0, width=self.W, height=self.H)
        self.canvas.create_image(0, 0, anchor="nw", image=self._bg_photo)
        _draw_soft_glow(self.canvas, self.W, self.H)

        # Draw buttons on top of the card
        self.btn_regions = []
        for i, (label, emoji, _cls, hint, body_color, shadow_color, _pale, _edge) in enumerate(actions):
            x1 = SIDEBAR_PAD
            y1 = SIDEBAR_PAD + i * (BTN_SIZE + BTN_GAP)
            x2 = x1 + BTN_SIZE
            y2 = y1 + BTN_SIZE

            # Soft coloured plate gives each action a small identity cue.
            self.canvas.create_polygon(
                _round_rect_points(x1, y1 + BTN_SHADOW, x2, y2 + BTN_SHADOW, BTN_RADIUS),
                smooth=True, fill=_lighten_local(shadow_color, 0.55), outline="",
            )
            # Button face
            body_id = self.canvas.create_polygon(
                _round_rect_points(x1, y1, x2, y2, BTN_RADIUS),
                smooth=True, fill=body_color, outline="",
            )
            # Vector icon drawn in pure white — much crisper than the
            # default emoji font on coloured backgrounds.
            _draw_white_icon(
                self.canvas, emoji,
                cx=(x1 + x2) // 2, cy=(y1 + y2) // 2,
            )
            self.btn_regions.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "idx": i, "body_id": body_id,
                "base_color": body_color, "shadow_color": shadow_color,
                "label": label, "hint": hint,
            })

        self._hover_idx = None
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Leave>", self._on_leave_canvas)

        # Tooltip (lazy-created)
        self._tip_win: tk.Toplevel | None = None
        self._tip_after = None

    def _hit_test(self, x, y):
        for btn in self.btn_regions:
            if btn["x1"] <= x <= btn["x2"] and btn["y1"] <= y <= btn["y2"]:
                return btn
        return None

    def _on_motion(self, e):
        hit = self._hit_test(e.x, e.y)
        new_idx = hit["idx"] if hit else None
        if new_idx == self._hover_idx:
            return
        # Restore previous
        if self._hover_idx is not None:
            prev = self.btn_regions[self._hover_idx]
            self.canvas.itemconfig(prev["body_id"], fill=prev["base_color"])
        # Highlight new
        if hit is not None:
            self.canvas.itemconfig(hit["body_id"], fill=hit["shadow_color"])
            self.canvas.config(cursor="hand2")
            self._schedule_tooltip(hit, e.x_root, e.y_root)
        else:
            self.canvas.config(cursor="arrow")
            self._hide_tooltip()
        self._hover_idx = new_idx

    def _schedule_tooltip(self, btn, x_root, y_root):
        self._hide_tooltip()
        if self._tip_after is not None:
            self.win.after_cancel(self._tip_after)
        self._tip_after = self.win.after(
            350, lambda: self._show_tooltip(btn, x_root, y_root),
        )

    def _show_tooltip(self, btn, x_root, y_root):
        self._hide_tooltip()
        tip = tk.Toplevel(self.win)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.config(bg=TEXT_MAIN)
        tk.Label(
            tip, text=f"{btn['label']}  ·  {btn['hint']}",
            bg=TEXT_MAIN, fg="white",
            font=FONT_HINT,
            padx=10, pady=4,
        ).pack()
        tip.update_idletasks()
        # Position to the left of the sidebar button
        bw = tip.winfo_width()
        bh = tip.winfo_height()
        x = self.win.winfo_x() - bw - 8
        # Vertically aligned to the button centre
        y = self.win.winfo_y() + btn["y1"] + BTN_SIZE // 2 - bh // 2
        tip.geometry(f"+{x}+{y}")
        self._tip_win = tip

    def _hide_tooltip(self):
        if self._tip_after is not None:
            try:
                self.win.after_cancel(self._tip_after)
            except tk.TclError:
                pass
            self._tip_after = None
        if self._tip_win is not None and self._tip_win.winfo_exists():
            self._tip_win.destroy()
        self._tip_win = None

    def _on_click(self, e):
        hit = self._hit_test(e.x, e.y)
        if hit is not None:
            self.on_click_idx(hit["idx"])

    def _on_leave_canvas(self, e):
        # Reset hover state and forward to outside handler
        if self._hover_idx is not None:
            prev = self.btn_regions[self._hover_idx]
            self.canvas.itemconfig(prev["body_id"], fill=prev["base_color"])
            self._hover_idx = None
        self._hide_tooltip()
        if self.on_leave:
            self.on_leave(e)

    def position(self):
        return (self.win.winfo_x(), self.win.winfo_y(),
                self.win.winfo_width(), self.win.winfo_height())

    def move_to(self, x, y):
        self.win.geometry(f"+{x}+{y}")

    def destroy(self):
        self._hide_tooltip()
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ── Main window ─────────────────────────────────────────────────────────────

class MainWindow:
    def __init__(self, root: ttk.Window) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.config(bg=TRANSPARENT)
        root.wm_attributes("-transparentcolor", TRANSPARENT)

        # ── sprite frames ───────────────────────────────────────────────────
        self._sprites = {
            s: tk.PhotoImage(file=str(PET_DIR / f"pet_{s}.png"))
            for s in PET_STATES
        }
        pet_w = self._sprites["idle"].width()
        pet_h = self._sprites["idle"].height()
        self.pet_w, self.pet_h = pet_w, pet_h

        self.window_w = pet_w + SPRITE_PAD_X * 2
        self.window_h = pet_h + SPRITE_PAD_Y * 2

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self._px = sw - self.window_w - 40
        self._py = sh - self.window_h - 80
        root.geometry(f"{self.window_w}x{self.window_h}+{self._px}+{self._py}")

        # ── pet canvas ──────────────────────────────────────────────────────
        self.canvas = tk.Canvas(
            root, width=self.window_w, height=self.window_h,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        self.canvas.place(x=0, y=0, width=self.window_w, height=self.window_h)
        self.canvas.create_rectangle(
            0, 0, self.window_w, self.window_h,
            fill=TRANSPARENT, outline="", width=0,
        )
        self._image_id = self.canvas.create_image(
            SPRITE_PAD_X, SPRITE_PAD_Y,
            image=self._sprites["idle"], anchor="nw",
        )
        self._state = "idle"
        self._state_t0 = time.monotonic()
        self._happy_after_id = None
        self._happy_persist = False
        self._sleep_after_id = None
        self._tick_alive = True

        # ── drag / click bookkeeping ────────────────────────────────────────
        self._drag = (0, 0)
        self._press_pos = (0, 0)
        self._was_dragged = False
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # ── sidebar & panel state ───────────────────────────────────────────
        self._sidebar: _Sidebar | None = None
        self._panel: tk.Toplevel | None = None
        self._panel_bg: ImageTk.PhotoImage | None = None
        self._active_idx: int | None = None
        self._graph_win: _GraphWindow | None = None
        self._panel_pinned = False

        # ── panel resize state ─────────────────────────────────────────────
        self._panel_w = PANEL_W
        self._panel_h = PANEL_H
        self._panel_resize_edge = ""
        self._panel_drag_origin = (0, 0)
        self._panel_resize_after = None

        self.canvas.bind("<Enter>", self._on_activity_enter)
        self.canvas.bind("<Leave>", self._maybe_hide)
        self.canvas.bind("<Motion>", lambda _e: self._kick_activity())
        self.canvas.bind("<Double-Button-1>", lambda _: root.destroy())

        # ── global shortcuts ────────────────────────────────────────────────
        root.bind_all("<Control-Key-1>", lambda _e: self._shortcut_open(0))
        root.bind_all("<Control-Key-2>", lambda _e: self._shortcut_open(1))
        root.bind_all("<Control-Key-3>", lambda _e: self._shortcut_open(2))
        root.bind_all("<Control-Key-4>", lambda _e: self._shortcut_open(3))
        root.bind_all("<Control-Key-5>", lambda _e: self._shortcut_open(4))
        root.bind_all("<Control-Key-6>", lambda _e: self._shortcut_open(5))
        root.bind_all("<Escape>", lambda _e: self._close_panel())
        root.focus_force()

        # ── drag-and-drop files onto the pet ────────────────────────────────
        try:
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind("<<Drop>>", self._on_files_dropped)
        except (AttributeError, tk.TclError):
            # DnD initialisation failed — feature is optional.
            pass

        self._reset_sleep_timer()
        self._tick()

    # ── state machine ───────────────────────────────────────────────────────

    def _set_state(self, state: str, *, auto_end: bool = True) -> None:
        if state == self._state:
            return
        self._state = state
        self._state_t0 = time.monotonic()
        self.canvas.itemconfig(self._image_id, image=self._sprites[state])
        if state == "happy" and not auto_end:
            self._happy_persist = True
        # Cancel pending sleep when switching to a non-idle/non-sleep state.
        if state not in ("idle", "sleep") and self._sleep_after_id is not None:
            self.root.after_cancel(self._sleep_after_id)
            self._sleep_after_id = None

    def _tick(self) -> None:
        try:
            t = time.monotonic() - self._state_t0
            s = self._state
            if s == "idle":
                dy = math.sin(t * 1.8) * 5.0
                dx = math.sin(t * 0.9) * 1.5
            elif s == "happy":
                if t < 0.20:
                    p = t / 0.20
                    ease = 1 - (1 - p) ** 3
                    dy = (1 - ease) * 30
                    dx = 0.0
                else:
                    decay = max(0.0, 1 - (t - 0.20) / 1.0)
                    dy = -abs(math.sin((t - 0.20) * 9)) * 18 * decay
                    dx = math.sin((t - 0.20) * 5) * 4 * decay
            elif s == "attack":
                if t < 0.14:
                    p = t / 0.14
                    ease = 1 - (1 - p) ** 2
                    dx = -(1 - ease) * 18
                    dy = -(1 - ease) * 6
                else:
                    dx = math.sin((t - 0.14) * 28) * 4.0
                    dy = math.sin((t - 0.14) * 14) * 2.5
            elif s == "eat":
                # Gentle float + subtle nibble bob
                dy = math.sin(t * 1.8) * 5.0
                dx = math.sin(t * 0.9) * 1.5
                # small chomp: faster vertical hop every ~0.6 s
                chomp = math.sin(t * 10.5)
                if chomp > 0.7:
                    dy -= (chomp - 0.7) * 4.0
            elif s == "sleep":
                if t < 0.35:
                    p = t / 0.35
                    ease = 1 - (1 - p) ** 2
                    dy = (1 - ease) * 12
                    dx = 0.0
                else:
                    dy = math.sin((t - 0.35) * 0.9) * 4.0
                    dx = 0.0
            else:
                dx = dy = 0.0

            self.canvas.coords(
                self._image_id,
                int(round(SPRITE_PAD_X + dx)),
                int(round(SPRITE_PAD_Y + dy)),
            )
        except tk.TclError:
            self._tick_alive = False
            return

        if self._tick_alive:
            self.root.after(TICK_MS, self._tick)

    def _kick_activity(self) -> None:
        if self._state == "sleep":
            self._set_state("idle")
        self._reset_sleep_timer()

    def _on_activity_enter(self, _e) -> None:
        self._kick_activity()
        self._show_sidebar()

    def _reset_sleep_timer(self) -> None:
        if self._sleep_after_id is not None:
            self.root.after_cancel(self._sleep_after_id)
        # Only schedule auto-sleep when the pet is idling.
        if self._state != "idle":
            self._sleep_after_id = None
            return
        self._sleep_after_id = self.root.after(SLEEP_IDLE_MS, self._go_sleep)

    def _go_sleep(self) -> None:
        if self._state != "idle":
            return
        self._set_state("sleep")

    # ── press / drag / release ──────────────────────────────────────────────

    def _on_press(self, e) -> None:
        self._drag = (e.x, e.y)
        self._press_pos = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        self._was_dragged = False
        self._kick_activity()

    def _on_motion(self, _e) -> None:
        nx = self.root.winfo_pointerx() - self._drag[0]
        ny = self.root.winfo_pointery() - self._drag[1]
        if not self._was_dragged:
            dx = self.root.winfo_pointerx() - self._press_pos[0]
            dy = self.root.winfo_pointery() - self._press_pos[1]
            if dx * dx + dy * dy >= DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX:
                self._was_dragged = True
                self._set_state("attack")
        self._px, self._py = nx, ny
        self.root.geometry(f"+{nx}+{ny}")
        self._reposition_sidebar()
        self._reposition_panel()

    def _on_release(self, _e) -> None:
        if self._was_dragged:
            self._set_state("idle")
        else:
            self._set_state("happy")
            if self._happy_after_id is not None:
                self.root.after_cancel(self._happy_after_id)
            self._happy_after_id = self.root.after(HAPPY_HOLD_MS, self._end_happy)
        self._kick_activity()

    def _end_happy(self) -> None:
        self._happy_after_id = None
        if self._happy_persist:
            return
        if self._state == "happy":
            self._set_state("idle")

    # ── sidebar ─────────────────────────────────────────────────────────────

    def _show_sidebar(self) -> None:
        if self._sidebar is not None:
            return
        self._sidebar = _Sidebar(
            self.root, ACTIONS,
            on_click_idx=lambda idx: self._toggle_panel(idx, pinned=False),
            on_leave=self._maybe_hide,
        )
        self._reposition_sidebar()

    def _reposition_sidebar(self) -> None:
        if self._sidebar is None:
            return
        pet_center_y = self._py + SPRITE_PAD_Y + self.pet_h // 2
        sprite_left_x = self._px + SPRITE_PAD_X
        y = pet_center_y - self._sidebar.H // 2
        x = sprite_left_x - self._sidebar.W - 8
        self._sidebar.move_to(x, y)

    def _hide_sidebar(self) -> None:
        if self._sidebar is not None:
            self._sidebar.destroy()
            self._sidebar = None

    def _maybe_hide(self, _e=None) -> None:
        self.root.after(140, self._check_hide)

    def _check_hide(self) -> None:
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()

        if (self._px <= px <= self._px + self.window_w and
                self._py <= py <= self._py + self.window_h):
            return
        if self._sidebar is not None:
            wx, wy, ww, wh = self._sidebar.position()
            if wx <= px <= wx + ww and wy <= py <= wy + wh:
                return
        if self._panel and self._panel.winfo_exists():
            wx, wy = self._panel.winfo_x(), self._panel.winfo_y()
            ww, wh = self._panel.winfo_width(), self._panel.winfo_height()
            if wx <= px <= wx + ww and wy <= py <= wy + wh:
                return

        self._hide_sidebar()
        if not self._panel_pinned:
            self._close_panel()

    # ── side panel ──────────────────────────────────────────────────────────

    def _shortcut_open(self, idx: int) -> None:
        if self._active_idx == idx and self._panel and self._panel.winfo_exists():
            self._close_panel()
            return
        self._toggle_panel(idx, pinned=True)

    def _toggle_panel(self, idx: int, pinned: bool) -> None:
        # Special case: graph opens as a standalone resizable window.
        label, emoji, tab_cls, hint, accent, _shadow, pale_bg, edge_color = ACTIONS[idx]
        if tab_cls is GraphTab:
            if self._graph_win and self._graph_win.win.winfo_exists():
                self._close_graph()
                return
            self._close_panel()
            self._graph_win = _GraphWindow(
                self.root, bg_color=pale_bg, edge_color=edge_color, main=self,
            )
            return

        if self._active_idx == idx and self._panel and self._panel.winfo_exists():
            self._close_panel()
            return
        self._close_panel()
        self._active_idx = idx
        self._panel_pinned = pinned
        if tab_cls is ChatTab:
            pinned = True

        # Reset panel dimensions for each new panel
        self._panel_w = PANEL_W
        self._panel_h = PANEL_H

        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.config(bg=TRANSPARENT)
        panel.wm_attributes("-transparentcolor", TRANSPARENT)
        panel.geometry(f"{self._panel_w}x{self._panel_h}")

        # PIL background = pale themed body + matching edge + bottom shadow
        bg_pil = _make_card_png(
            self._panel_w, self._panel_h, PANEL_RADIUS,
            APP_BG, GLASS_EDGE, SOFT_SHADOW, PANEL_SHADOW,
        )
        self._panel_bg = ImageTk.PhotoImage(bg_pil)

        bg_canvas = tk.Canvas(
            panel, width=self._panel_w, height=self._panel_h,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        bg_canvas.place(x=0, y=0, width=self._panel_w, height=self._panel_h)
        bg_canvas.create_image(0, 0, anchor="nw", image=self._panel_bg)
        _draw_soft_glow(bg_canvas, self._panel_w, self._panel_h)

        # ── Title bar + close button + separator ─────────────────────────────
        chrome = self._draw_panel_chrome(bg_canvas, self._panel_w, label, emoji, hint)

        # Store references for resize handlers
        panel._bg_canvas = bg_canvas
        panel._close_body_id = chrome.close_body_id
        panel._close_x_id = chrome.close_x_id
        panel._close_cx1, panel._close_cx2 = chrome.cx1, chrome.cx2
        panel._close_cy1, panel._close_cy2 = chrome.cy1, chrome.cy2
        panel._pale_bg = APP_BG
        panel._edge_color = edge_color
        panel._label = label
        panel._emoji = emoji
        panel._hint = hint

        bg_canvas.bind("<Motion>", self._on_panel_motion)
        bg_canvas.bind("<Button-1>", self._on_panel_click)
        bg_canvas.bind("<B1-Motion>", self._on_panel_drag)
        bg_canvas.bind("<ButtonRelease-1>", self._on_panel_release)

        # ── Content area ────────────────────────────────────────────────────
        content_top = PANEL_TITLE_H + 14
        content = tk.Frame(panel, bg=APP_BG)
        content.place(
            x=PANEL_BODY_PAD, y=content_top,
            width=self._panel_w - PANEL_BODY_PAD * 2,
            height=self._panel_h - content_top - PANEL_SHADOW - PANEL_BODY_PAD,
        )
        panel._content = content
        panel._content_top = content_top

        if tab_cls in (InputTab, UploadTab):
            tab = tab_cls(content, bg_color=APP_BG, edge_color=edge_color, main=self)
        else:
            tab = tab_cls(content, bg_color=APP_BG, edge_color=edge_color)
        tab.frame.pack(fill=BOTH, expand=True)

        self._panel = panel
        self._reposition_panel()

        if not pinned:
            panel.bind("<Leave>", self._maybe_hide)

    def _reposition_panel(self) -> None:
        if not self._panel or not self._panel.winfo_exists():
            return
        sprite_left_x = self._px + SPRITE_PAD_X
        sidebar_w = self._sidebar.W if self._sidebar else (SIDEBAR_PAD * 2 + BTN_SIZE)
        x = sprite_left_x - sidebar_w - 8 - self._panel_w - 6
        sw = self.root.winfo_screenwidth()
        if x < 0:
            x = self._px + self.window_w + 8
        x = max(0, min(x, sw - self._panel_w))
        pet_center_y = self._py + SPRITE_PAD_Y + self.pet_h // 2
        y = pet_center_y - self._panel_h // 2
        sh = self.root.winfo_screenheight()
        y = max(0, min(y, sh - self._panel_h))
        self._panel.geometry(f"+{x}+{y}")

    def _close_panel(self) -> None:
        if self._panel_resize_after is not None:
            self.root.after_cancel(self._panel_resize_after)
            self._panel_resize_after = None
        if self._panel and self._panel.winfo_exists():
            self._panel.destroy()
        self._panel = None
        self._panel_bg = None
        self._active_idx = None
        self._panel_pinned = False
        self._panel_w = PANEL_W
        self._panel_h = PANEL_H
        self._panel_resize_edge = ""
        self._panel_drag_origin = (0, 0)

    def _close_graph(self) -> None:
        self._graph_win = None

    # ── panel chrome drawing ──────────────────────────────────────────────────

    class _PanelChrome:
        """Stores canvas item IDs for the panel title bar and close button."""
        __slots__ = ("close_body_id", "close_x_id", "cx1", "cx2", "cy1", "cy2")

        def __init__(self, close_body_id: int, close_x_id: int,
                     cx1: int, cx2: int, cy1: int, cy2: int) -> None:
            self.close_body_id = close_body_id
            self.close_x_id = close_x_id
            self.cx1, self.cx2 = cx1, cx2
            self.cy1, self.cy2 = cy1, cy2

    def _draw_panel_chrome(self, canvas: tk.Canvas, w: int,
                           label: str, emoji: str, hint: str) -> "MainWindow._PanelChrome":
        """Draw title bar, hint pill, close button, and separator."""
        # Title text (emoji + label with separate fonts)
        title_x = PANEL_BODY_PAD + 4
        cy = PANEL_TITLE_H // 2
        f_emoji = tkfont.Font(font=("Segoe UI Emoji", FONT_TITLE[1]))
        f_title = tkfont.Font(font=FONT_TITLE)
        canvas.create_text(
            title_x, cy, text=emoji, anchor="w",
            fill=TEXT_MAIN, font=("Segoe UI Emoji", FONT_TITLE[1]),
        )
        text_x = title_x + f_emoji.measure(emoji) + 8
        canvas.create_text(
            text_x, cy, text=label, anchor="w",
            fill=TEXT_MAIN, font=FONT_TITLE,
        )

        # Shortcut hint pill
        hint_pill_w = 72
        hint_x = text_x + f_title.measure(label) + 14
        canvas.create_polygon(
            _round_rect_points(hint_x, cy - 13, hint_x + hint_pill_w, cy + 13, 12),
            smooth=True, fill=WHITE, outline=GLASS_EDGE, width=1,
        )
        canvas.create_text(
            hint_x + hint_pill_w // 2, cy, text=hint,
            fill=SKY_DARK, font=FONT_SHORTCUT,
        )

        # Close button (glass square)
        cs = 30
        cx2 = w - PANEL_BODY_PAD - 4
        cx1 = cx2 - cs
        cy1 = (PANEL_TITLE_H - cs) // 2
        cy2 = cy1 + cs
        close_body_id = canvas.create_polygon(
            _round_rect_points(cx1, cy1, cx2, cy2, 10),
            smooth=True, fill=WHITE, outline=GLASS_EDGE, width=1,
        )
        close_x_id = canvas.create_text(
            (cx1 + cx2) // 2, (cy1 + cy2) // 2,
            text="✕", fill=TEXT_LIGHT, font=FONT_BODY_BOLD,
        )

        # Solid separator
        canvas.create_line(
            PANEL_BODY_PAD, PANEL_TITLE_H,
            w - PANEL_BODY_PAD, PANEL_TITLE_H,
            fill=GLASS_EDGE, width=1,
        )

        return self._PanelChrome(close_body_id, close_x_id, cx1, cx2, cy1, cy2)

    # ── panel resize handlers ────────────────────────────────────────────────

    def _panel_close_hit(self, x: int, y: int) -> bool:
        p = self._panel
        if not p:
            return False
        return (p._close_cx1 <= x <= p._close_cx2 and
                p._close_cy1 <= y <= p._close_cy2)

    def _on_panel_motion(self, e: tk.Event) -> None:
        p = self._panel
        if not p:
            return
        canvas = p._bg_canvas

        # Close button hover takes priority over resize grip
        if self._panel_close_hit(e.x, e.y):
            canvas.itemconfig(p._close_body_id, fill="#feecec", outline=PINK)
            canvas.itemconfig(p._close_x_id, fill=PINK)
            canvas.config(cursor="hand2")
            return

        # Reset close button appearance
        canvas.itemconfig(p._close_body_id, fill=WHITE, outline=GLASS_EDGE)
        canvas.itemconfig(p._close_x_id, fill=TEXT_LIGHT)

        # Resize grip cursor
        on_right = e.x >= self._panel_w - PANEL_GRIP
        on_bottom = e.y >= self._panel_h - PANEL_GRIP
        if on_right and on_bottom:
            canvas.config(cursor="bottom_right_corner")
        elif on_right:
            canvas.config(cursor="sb_h_double_arrow")
        elif on_bottom:
            canvas.config(cursor="sb_v_double_arrow")
        else:
            canvas.config(cursor="arrow")

    def _on_panel_click(self, e: tk.Event) -> None:
        p = self._panel
        if not p:
            return
        # Close button takes priority over resize grip
        if self._panel_close_hit(e.x, e.y):
            self._close_panel()
            return
        on_right = e.x >= self._panel_w - PANEL_GRIP
        on_bottom = e.y >= self._panel_h - PANEL_GRIP
        if on_right or on_bottom:
            self._panel_resize_edge = (
                ("right" if on_right else "") + ("bottom" if on_bottom else "")
            )
            self._panel_drag_origin = (e.x_root, e.y_root)

    def _on_panel_drag(self, e: tk.Event) -> None:
        if not self._panel_resize_edge:
            return
        dx = e.x_root - self._panel_drag_origin[0]
        dy = e.y_root - self._panel_drag_origin[1]
        nw = self._panel_w + (dx if "right" in self._panel_resize_edge else 0)
        nh = self._panel_h + (dy if "bottom" in self._panel_resize_edge else 0)
        nw = max(PANEL_MIN_W, nw)
        nh = max(PANEL_MIN_H, nh)
        # Clamp to screen bounds
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        nw = min(nw, sw - self._panel.winfo_x())
        nh = min(nh, sh - self._panel.winfo_y())
        if nw == self._panel_w and nh == self._panel_h:
            return
        self._panel_w, self._panel_h = nw, nh
        self._panel.geometry(f"{nw}x{nh}")
        p = self._panel
        p._bg_canvas.place(width=nw, height=nh)
        p._bg_canvas.config(width=nw, height=nh)
        self._update_panel_content()
        self._panel_drag_origin = (e.x_root, e.y_root)

    def _on_panel_release(self, _e: tk.Event) -> None:
        if not self._panel_resize_edge:
            return
        self._panel_resize_edge = ""
        # Debounce PIL background regeneration
        if self._panel_resize_after is not None:
            self.root.after_cancel(self._panel_resize_after)
        self._panel_resize_after = self.root.after(
            PANEL_RESIZE_DEBOUNCE_MS, self._refresh_panel_bg,
        )

    def _update_panel_content(self) -> None:
        p = self._panel
        if not p:
            return
        p._content.place(
            width=self._panel_w - PANEL_BODY_PAD * 2,
            height=self._panel_h - p._content_top - PANEL_SHADOW - PANEL_BODY_PAD,
        )

    def _refresh_panel_bg(self) -> None:
        self._panel_resize_after = None
        p = self._panel
        if not p or not p.winfo_exists():
            return
        canvas = p._bg_canvas
        w, h = self._panel_w, self._panel_h

        # Regenerate PIL background
        bg_pil = _make_card_png(
            w, h, PANEL_RADIUS,
            p._pale_bg, GLASS_EDGE, SOFT_SHADOW, PANEL_SHADOW,
        )
        self._panel_bg = ImageTk.PhotoImage(bg_pil)

        # Clear and redraw canvas
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self._panel_bg)
        _draw_soft_glow(canvas, w, h)

        # Redraw title bar, close button, separator
        chrome = self._draw_panel_chrome(canvas, w, p._label, p._emoji, p._hint)
        p._close_body_id = chrome.close_body_id
        p._close_x_id = chrome.close_x_id
        p._close_cx1, p._close_cx2 = chrome.cx1, chrome.cx2
        p._close_cy1, p._close_cy2 = chrome.cy1, chrome.cy2

    def _open_reader(self, path: Path) -> None:
        """Open a wiki page in a reader window (reuse if compatible)."""
        from ui.search_tab import _ReaderWindow
        prev = getattr(self.root, "_active_reader", None)
        if prev is not None:
            try:
                prev.destroy()
            except tk.TclError:
                pass
            self.root._active_reader = None
        reader = _ReaderWindow(self.root, path, query="", bg_color="#fafbff", edge_color="#d4b8f0")
        self.root._active_reader = reader

    # ── drag-and-drop file ingestion ────────────────────────────────────────

    def _on_files_dropped(self, event) -> None:
        """Handle one or more files dropped onto the pet sprite."""
        paths = _parse_dnd_files(event.data)
        if not paths:
            return
        ok, bad = [], []
        saved_paths = []
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                bad.append((p, "文件不存在"))
                continue
            if p.suffix.lower() not in UPLOAD_HANDLERS:
                bad.append((p, f"不支持的格式 {p.suffix}"))
                continue
            try:
                saved = save_raw_file(p)
                saved_paths.append(saved)
            except Exception as exc:
                bad.append((p, str(exc)))

        # Batch feedback — rejects upfront, then animates the saves.
        if bad and not saved_paths:
            details = "\n".join(f"  {p.name}: {msg}" for p, msg in bad)
            Messagebox.show_error(f"全部失败:\n{details}", parent=self.root)
        else:
            if bad:
                bad_names = "\n".join(f"  {p.name}: {msg}" for p, msg in bad)
                Messagebox.show_warning(
                    f"部分文件无法读取:\n{bad_names}", parent=self.root,
                )
            if saved_paths:
                self._ingest_with_animation(saved_paths)

    # ── ingest feedback ────────────────────────────────────────────────────

    MIN_EAT_MS = 2500  # keep eat animation for at least 2.5 s

    def _ingest_with_animation(self, paths: list[Path]) -> None:
        """Start eat animation, open discussion panel, then ingest."""
        if not paths:
            return
        self._set_state("eat")
        self._open_ingest_chat(paths)

    def _open_ingest_chat(self, paths: list[Path]) -> None:
        """Open a chat-style discussion panel for interactive ingest."""
        from llm.client import LLMConfig
        from llm.wiki_engine import discuss_and_ingest
        import config as _cfg

        llm_cfg = LLMConfig(
            api_base=_cfg.LLM_API_BASE,
            api_key=_cfg.LLM_API_KEY,
            model=_cfg.LLM_MODEL,
            thinking=_cfg.LLM_THINKING,
        )
        if not llm_cfg.api_key:
            # No LLM — fall back to silent background ingest.
            from llm.wiki_engine import background_ingest
            for p in paths:
                background_ingest(p)
            self._set_state("idle")
            Messagebox.show_info(f"已开始处理 {len(paths)} 个文件", parent=self.root)
            return

        chat_q: queue.Queue[str] = queue.Queue()
        user_q: queue.Queue[str] = queue.Queue()
        path_iter = iter(paths)
        self._current_note: Path | None = next(path_iter)
        self._pending_paths = list(path_iter)

        # ── Chat panel (Toplevel) ───────────────────────────────────────
        pw, ph = 560, 600
        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.config(bg=TRANSPARENT)
        panel.wm_attributes("-transparentcolor", TRANSPARENT)
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        px = max(0, rx + self.window_w // 2 - pw // 2)
        py = max(0, ry - ph - 16)
        panel.geometry(f"{pw}x{ph}+{px}+{py}")

        card = _shared_card_png(pw, ph, 22, APP_BG, GLASS_EDGE, SOFT_SHADOW, 8)
        self._chat_bg = ImageTk.PhotoImage(card)

        cv = tk.Canvas(panel, width=pw, height=ph,
                       bg=TRANSPARENT, highlightthickness=0, borderwidth=0)
        cv.pack()
        cv.create_image(0, 0, image=self._chat_bg, anchor="nw")
        _draw_soft_glow(cv, pw, ph)

        # Title bar
        cv.create_text(24, 30, text=f"讨论: {self._current_note.stem if self._current_note else '文件'}",
                       anchor="w", fill=TEXT_MAIN, font=FONT_HEADING)
        close_x = pw - 30
        cv.create_text(close_x, 30, text="✕", fill=TEXT_LIGHT,
                       font=FONT_BODY_BOLD)
        cv.create_line(24, 58, pw - 24, 58, fill=GLASS_EDGE, width=1)

        # Text widget for LLM streaming output
        text_frame = tk.Frame(panel, bg=GLASS_EDGE)
        text_frame.place(x=24, y=76, width=pw - 48, height=ph - 188)
        text_inner = tk.Frame(text_frame, bg=WHITE)
        text_inner.pack(fill="both", expand=True, padx=1, pady=1)
        text_widget = tk.Text(
            text_inner, wrap="word", font=FONT_INPUT,
            bg=WHITE, fg=TEXT_MAIN, relief="flat",
            state="disabled", padx=12, pady=10,
            spacing1=2, spacing3=2,
        )
        sb = tk.Scrollbar(text_inner, command=text_widget.yview)
        text_widget.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)

        ready = [False]
        ingest_phase = ["chat"]  # chat | select | confirm

        # ── closures (defined before widgets that reference them) ──────
        def _dismiss():
            try:
                panel.destroy()
            except tk.TclError:
                pass
            self._ingest_chat_dismiss = None

        self._ingest_chat_dismiss = _dismiss

        def _on_close():
            user_q.put("__CANCEL__")
            _dismiss()

        def _append_text(content: str) -> None:
            text_widget.config(state="normal")
            text_widget.insert("end", content)
            text_widget.config(state="disabled")
            text_widget.see("end")

        def _append_user(content: str) -> None:
            text_widget.config(state="normal")
            text_widget.insert("end", f"\n👤 {content}\n\n", "user")
            text_widget.config(state="disabled")
            text_widget.see("end")

        text_widget.tag_config("user", foreground="#7a5acc", font=FONT_BODY_BOLD)
        text_widget.tag_config("status", foreground="#6b7c8f", font=FONT_HINT)

        def _send():
            text = entry.get().strip()
            if not text:
                if ingest_phase[0] in ("select", "confirm"):
                    _confirm()
                return
            _append_user(text)
            entry.delete(0, "end")
            user_q.put(text)

        def _confirm():
            if ingest_phase[0] == "select":
                _append_user("默认")
                user_q.put("默认")
                ingest_phase[0] = "chat"
                confirm_btn.pack_forget()
                skip_btn.pack_forget()
            elif ingest_phase[0] == "confirm":
                user_q.put("__CONFIRM__")
                ingest_phase[0] = "chat"
                confirm_btn.pack_forget()
                skip_btn.pack_forget()

        def _skip():
            user_q.put("__CANCEL__")

        # ── widgets ───────────────────────────────────────────────────
        input_frame = tk.Frame(panel, bg=GLASS_EDGE)
        input_frame.place(x=24, y=ph - 96, width=pw - 48, height=42)
        input_inner = tk.Frame(input_frame, bg=WHITE)
        input_inner.pack(fill="both", expand=True, padx=1, pady=1)
        entry = tk.Entry(input_inner, font=FONT_INPUT, bg=WHITE,
                         fg=TEXT_MAIN, relief="flat", bd=0,
                         highlightthickness=0, insertbackground=SKY_DARK)
        entry.pack(fill="both", expand=True, padx=12, pady=8)
        entry.bind("<Return>", lambda _e: _send())

        btn_frame = tk.Frame(panel, bg=APP_BG)
        btn_frame.place(x=24, y=ph - 46, width=pw - 48, height=38)

        send_btn = CartoonButton(btn_frame, "💬 发送", command=_send, kind="sky", height=36)
        send_btn.pack(side="left", padx=(0, 6))
        confirm_btn = CartoonButton(btn_frame, "✅ 确认提取", command=_confirm, kind="mint")
        skip_btn = CartoonButton(btn_frame, "⏭ 跳过", command=_skip, kind="pink")
        skip_btn.pack(side="right")
        confirm_btn.pack(side="right", padx=6)
        for b in (confirm_btn, skip_btn):
            b.pack_forget()

        # Close button click
        cv.tag_bind(
            cv.create_rectangle(close_x - 14, 14, close_x + 14, 46,
                                fill="", outline=""),
            "<Button-1>", lambda _e: _on_close(),
        )

        # ── Worker thread ───────────────────────────────────────────────
        def _worker():
            ok, err = 0, 0
            p = self._current_note
            if p:
                try:
                    result = discuss_and_ingest(
                        p, llm_cfg,
                        chat_q=chat_q, user_q=user_q,
                    )
                    if result:
                        ok += 1
                    else:
                        err += 1
                except Exception as exc:
                    _err_log.exception("discuss+ingest failed for %s", p)
                    tb = traceback.format_exc()
                    log_path = _cfg.BASE_DIR / "ingest_error.log"
                    try:
                        with log_path.open("a", encoding="utf-8") as f:
                            f.write(
                                "\n\n=== ingest failure "
                                f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                                f"file: {p}\n"
                                f"error: {type(exc).__name__}: {exc}\n\n"
                                f"{tb}\n"
                            )
                    except Exception:
                        _err_log.exception("failed to write ingest error log")
                    detail = (
                        "\n\n❌ 处理失败\n"
                        f"文件: {p.name}\n"
                        f"错误: {type(exc).__name__}: {exc}\n"
                        f"日志: {log_path}\n"
                    )
                    chat_q.put(("__FATAL__", detail))
                    err += 1
                    self.root.after(0, lambda: self._end_eat_animated(ok, err))
                    return
            self.root.after(0, lambda: self._finish_ingest(ok, err))

        threading.Thread(target=_worker, daemon=True).start()

        # ── Poll loop ───────────────────────────────────────────────────
        def _poll():
            while True:
                try:
                    item = chat_q.get_nowait()
                except queue.Empty:
                    break
                if item == "__READY__":
                    ready[0] = True
                    ingest_phase[0] = "confirm"
                    confirm_btn.set_text("✅ 确认提取")
                    confirm_btn.pack(side="right", padx=6)
                    skip_btn.pack(side="right")
                elif item == "__SELECT_DEFAULT__":
                    ingest_phase[0] = "select"
                    confirm_btn.set_text("✅ 使用默认")
                    confirm_btn.pack(side="right", padx=6)
                    skip_btn.pack(side="right")
                elif item == "__DONE__":
                    return  # let worker thread call _finish_ingest
                elif item == "__ERROR__":
                    _append_text("\n❌ 提取失败，关闭窗口重试\n")
                    return
                elif isinstance(item, tuple) and item[0] == "__FATAL__":
                    _append_text(item[1], "status")
                    return
                else:
                    _append_text(item)
            panel.after(50, _poll)

        panel.after(50, _poll)

    def _finish_ingest(self, ok: int, err: int) -> None:
        self._set_state("idle")
        if self._ingest_chat_dismiss:
            self._ingest_chat_dismiss()
        self._show_ingest_toast(ok, err)

    def _end_eat_animated(self, ok: int, err: int) -> None:
        self._set_state("idle")
        self._show_ingest_toast(ok, err)

    def _show_ingest_toast(self, ok: int, err: int) -> None:
        """Cartoon card toast above the pet, auto-dismiss after 5 s."""
        bw, bh = 300, 108
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        bx = max(0, rx + self.window_w // 2 - bw // 2)
        by = max(0, ry - bh - 16)

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.config(bg=TRANSPARENT)
        toast.wm_attributes("-transparentcolor", TRANSPARENT)
        toast.geometry(f"{bw}x{bh}+{bx}+{by}")

        # ── PIL card with drop shadow (same style as panels) ────────────────
        card = _shared_card_png(bw, bh, 18, APP_BG, GLASS_EDGE, SOFT_SHADOW, 7)
        self._toast_bg_img = ImageTk.PhotoImage(card)

        cv = tk.Canvas(
            toast, width=bw, height=bh,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        cv.pack()
        cv.create_image(0, 0, image=self._toast_bg_img, anchor="nw")
        _draw_soft_glow(cv, bw, bh)

        cv.create_text(
            bw // 2, 34, text="Wiki 更新完成",
            fill=TEXT_MAIN, font=FONT_HEADING,
        )

        status = f"ok: {ok} 成功" + (f", {err} 失败" if err else "")
        cv.create_text(
            bw // 2, 66, text=status,
            fill=TEXT_LIGHT, font=FONT_HINT,
        )

        def _dismiss():
            try:
                toast.destroy()
            except tk.TclError:
                pass
        toast.bind("<Button-1>", lambda _e: _dismiss())
        self.root.after(5000, _dismiss)

    # ══ end ingest feedback ════════════════════════════════════════════════


def _parse_dnd_files(data: str) -> list[str]:
    """tkdnd hands us a space-separated string of paths.

    Paths with spaces are wrapped in `{ ... }`.  This parser handles both.
    """
    if not data:
        return []
    out = []
    # `{path with spaces} other/path "third/one"`  → handle each form
    i = 0
    while i < len(data):
        ch = data[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            end = data.find("}", i + 1)
            if end == -1:
                out.append(data[i + 1:])
                break
            out.append(data[i + 1:end])
            i = end + 1
        else:
            # Read until next whitespace
            m = re.match(r"\S+", data[i:])
            if not m:
                break
            out.append(m.group(0))
            i += m.end()
    return out


def _draw_dashed_line(canvas, x1, y1, x2, y2, color, dash=(6, 4), width=2):
    """Tk Canvas's `dash` option works on create_line — wrap it for readability."""
    canvas.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash)
