import math
import re
import time
import tkinter as tk
from pathlib import Path

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, LEFT, RIGHT
from ttkbootstrap.dialogs import Messagebox
from PIL import Image, ImageDraw, ImageTk
from tkinterdnd2 import DND_FILES

from config import APP_TITLE, BASE_DIR
from storage.note_store import save_note
from ui.cartoon_widgets import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_BODY_BOLD, FONT_SHORTCUT, FONT_HINT,
    hex_to_rgb as _hex_to_rgb_shared, make_card_png as _shared_card_png,
)
from ui.input_tab import InputTab
from ui.upload_tab import UploadTab, SUPPORTED as UPLOAD_HANDLERS
from ui.search_tab import SearchTab
from ui.chat_tab import ChatTab

PET_DIR = BASE_DIR / "assets"
PET_STATES = ("idle", "attack", "happy", "sleep")
TRANSPARENT = "#ff00ff"

# ── Cartoon Sky-Blue palette (lifted from the HTML UI kit) ──────────────────
SKY_PRIMARY = "#5CB8F0"
SKY_DARK = "#3a90cc"
SKY_LIGHT = "#a8d4f4"
SKY_PALE = "#e0f2ff"
WHITE = "#ffffff"
TEXT_MAIN = "#2c3e50"
TEXT_LIGHT = "#6b7c8f"
DASH_LINE = "#e0eeff"

MINT = "#5DD5A8"
PINK = "#F07AA0"
ORANGE = "#FFC94A"
LAVENDER = "#A080F0"

# Per-action: label, emoji, tab_class, hint, btn body, btn shadow, panel pale-bg, panel edge
ACTIONS = [
    ("输入", "📖", InputTab,  "Ctrl+1", SKY_PRIMARY, SKY_DARK,  "#e8f4ff", "#a8d4f4"),
    ("上传", "📁", UploadTab, "Ctrl+2", MINT,        "#3db88a", "#ebfaf3", "#a8eedd"),
    ("搜索", "🔍", SearchTab, "Ctrl+3", LAVENDER,    "#7a5acc", "#f3eefc", "#d8cefa"),
    ("问答", "💬", ChatTab,   "Ctrl+4", ORANGE,      "#dba42a", "#fff8e0", "#ffe4a8"),
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
BTN_RADIUS = 16
BTN_SHADOW = 4
SIDEBAR_PAD = 12
SIDEBAR_RADIUS = 22
SIDEBAR_SHADOW = 5

# Panel geometry
PANEL_W, PANEL_H = 520, 680
PANEL_RADIUS = 26
PANEL_SHADOW = 6
PANEL_TITLE_H = 52
PANEL_BODY_PAD = 16


# ── Helpers ─────────────────────────────────────────────────────────────────

_hex_to_rgb = _hex_to_rgb_shared


def _round_rect_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]


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

        # Pre-rendered card background (white + sky-light edge + bottom shadow)
        bg_pil = _make_card_png(
            self.W, self.H, SIDEBAR_RADIUS,
            WHITE, SKY_LIGHT, SKY_LIGHT, SIDEBAR_SHADOW,
        )
        self._bg_photo = ImageTk.PhotoImage(bg_pil)

        self.canvas = tk.Canvas(
            self.win, width=self.W, height=self.H,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        self.canvas.place(x=0, y=0, width=self.W, height=self.H)
        self.canvas.create_image(0, 0, anchor="nw", image=self._bg_photo)

        # Draw buttons on top of the card
        self.btn_regions = []
        for i, (label, emoji, _cls, hint, body_color, shadow_color, _pale, _edge) in enumerate(actions):
            x1 = SIDEBAR_PAD
            y1 = SIDEBAR_PAD + i * (BTN_SIZE + BTN_GAP)
            x2 = x1 + BTN_SIZE
            y2 = y1 + BTN_SIZE

            # Bottom drop-shadow plate (creates "press-down" feel)
            self.canvas.create_polygon(
                _round_rect_points(x1, y1 + BTN_SHADOW, x2, y2 + BTN_SHADOW, BTN_RADIUS),
                smooth=True, fill=shadow_color, outline="",
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
        self._panel_pinned = False

        self.canvas.bind("<Enter>", self._on_activity_enter)
        self.canvas.bind("<Leave>", self._maybe_hide)
        self.canvas.bind("<Motion>", lambda _e: self._kick_activity())
        self.canvas.bind("<Double-Button-1>", lambda _: root.destroy())

        # ── global shortcuts ────────────────────────────────────────────────
        root.bind_all("<Control-Key-1>", lambda _e: self._shortcut_open(0))
        root.bind_all("<Control-Key-2>", lambda _e: self._shortcut_open(1))
        root.bind_all("<Control-Key-3>", lambda _e: self._shortcut_open(2))
        root.bind_all("<Control-Key-4>", lambda _e: self._shortcut_open(3))
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

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._state_t0 = time.monotonic()
        self.canvas.itemconfig(self._image_id, image=self._sprites[state])

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
        self._sleep_after_id = self.root.after(SLEEP_IDLE_MS, self._go_sleep)

    def _go_sleep(self) -> None:
        if self._state in ("attack", "happy"):
            self._reset_sleep_timer()
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
        if self._active_idx == idx and self._panel and self._panel.winfo_exists():
            self._close_panel()
            return
        self._close_panel()
        self._active_idx = idx
        self._panel_pinned = pinned
        label, emoji, tab_cls, hint, accent, _shadow, pale_bg, edge_color = ACTIONS[idx]

        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.config(bg=TRANSPARENT)
        panel.wm_attributes("-transparentcolor", TRANSPARENT)
        panel.geometry(f"{PANEL_W}x{PANEL_H}")

        # PIL background = pale themed body + matching edge + bottom shadow
        bg_pil = _make_card_png(
            PANEL_W, PANEL_H, PANEL_RADIUS,
            pale_bg, edge_color, edge_color, PANEL_SHADOW,
        )
        self._panel_bg = ImageTk.PhotoImage(bg_pil)

        bg_canvas = tk.Canvas(
            panel, width=PANEL_W, height=PANEL_H,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        bg_canvas.place(x=0, y=0, width=PANEL_W, height=PANEL_H)
        bg_canvas.create_image(0, 0, anchor="nw", image=self._panel_bg)

        # ── Title bar ───────────────────────────────────────────────────────
        from tkinter import font as tkfont
        # Render emoji + title separately (the cartoon Chinese font 华文琥珀
        # doesn't carry emoji glyphs).
        title_x = PANEL_BODY_PAD + 4
        cy = PANEL_TITLE_H // 2
        f_emoji = tkfont.Font(font=("Segoe UI Emoji", FONT_TITLE[1]))
        f_title = tkfont.Font(font=FONT_TITLE)
        bg_canvas.create_text(
            title_x, cy, text=emoji, anchor="w",
            fill=TEXT_MAIN, font=("Segoe UI Emoji", FONT_TITLE[1]),
        )
        text_x = title_x + f_emoji.measure(emoji) + 8
        bg_canvas.create_text(
            text_x, cy, text=label, anchor="w",
            fill=TEXT_MAIN, font=FONT_TITLE,
        )

        # Shortcut hint pill — placed RIGHT after the actual title width
        hint_pill_w = 64
        hint_x = text_x + f_title.measure(label) + 14
        bg_canvas.create_polygon(
            _round_rect_points(hint_x, cy - 11, hint_x + hint_pill_w, cy + 11, 10),
            smooth=True, fill=SKY_PALE, outline=SKY_LIGHT, width=2,
        )
        bg_canvas.create_text(
            hint_x + hint_pill_w // 2, cy, text=hint,
            fill=SKY_DARK, font=FONT_SHORTCUT,
        )

        # Close button (cartoon style: light grey rounded square, hover red)
        cx2 = PANEL_W - PANEL_BODY_PAD - 4
        cx1 = cx2 - 26
        cy1 = (PANEL_TITLE_H - 26) // 2
        cy2 = cy1 + 26
        close_body_id = bg_canvas.create_polygon(
            _round_rect_points(cx1, cy1, cx2, cy2, 10),
            smooth=True, fill="#f7fbff", outline="#dddddd", width=2,
        )
        close_x_id = bg_canvas.create_text(
            (cx1 + cx2) // 2, (cy1 + cy2) // 2,
            text="✕", fill=TEXT_LIGHT, font=FONT_BODY_BOLD,
        )

        def _close_hit(x, y):
            return cx1 <= x <= cx2 and cy1 <= y <= cy2

        def _on_canvas_motion(e):
            if _close_hit(e.x, e.y):
                bg_canvas.itemconfig(close_body_id, fill="#feecec", outline=PINK)
                bg_canvas.itemconfig(close_x_id, fill=PINK)
                bg_canvas.config(cursor="hand2")
            else:
                bg_canvas.itemconfig(close_body_id, fill="#f7fbff", outline="#dddddd")
                bg_canvas.itemconfig(close_x_id, fill=TEXT_LIGHT)
                bg_canvas.config(cursor="arrow")

        def _on_canvas_click(e):
            if _close_hit(e.x, e.y):
                self._close_panel()

        bg_canvas.bind("<Motion>", _on_canvas_motion)
        bg_canvas.bind("<Button-1>", _on_canvas_click)

        # ── Dashed separator under title ────────────────────────────────────
        _draw_dashed_line(
            bg_canvas, PANEL_BODY_PAD, PANEL_TITLE_H,
            PANEL_W - PANEL_BODY_PAD, PANEL_TITLE_H, DASH_LINE,
        )

        # ── Content area ────────────────────────────────────────────────────
        content_top = PANEL_TITLE_H + 8
        content = tk.Frame(panel, bg=pale_bg)
        content.place(
            x=PANEL_BODY_PAD, y=content_top,
            width=PANEL_W - PANEL_BODY_PAD * 2,
            height=PANEL_H - content_top - PANEL_SHADOW - PANEL_BODY_PAD,
        )

        tab = tab_cls(content, bg_color=pale_bg, edge_color=edge_color)
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
        x = sprite_left_x - sidebar_w - 8 - PANEL_W - 6
        pet_center_y = self._py + SPRITE_PAD_Y + self.pet_h // 2
        y = pet_center_y - PANEL_H // 2
        sh = self.root.winfo_screenheight()
        y = max(0, min(y, sh - PANEL_H))
        self._panel.geometry(f"+{x}+{y}")

    def _close_panel(self) -> None:
        if self._panel and self._panel.winfo_exists():
            self._panel.destroy()
        self._panel = None
        self._panel_bg = None
        self._active_idx = None
        self._panel_pinned = False

    # ── drag-and-drop file ingestion ────────────────────────────────────────

    def _on_files_dropped(self, event) -> None:
        """Handle one or more files dropped onto the pet sprite."""
        paths = _parse_dnd_files(event.data)
        if not paths:
            return
        ok, bad = [], []
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                bad.append((p, "文件不存在"))
                continue
            handler = UPLOAD_HANDLERS.get(p.suffix.lower())
            if handler is None:
                bad.append((p, f"不支持的格式 {p.suffix}"))
                continue
            try:
                content = handler(p)
                saved = save_note(content, title=p.stem)
                ok.append(saved)
            except Exception as exc:
                bad.append((p, str(exc)))

        # Celebrate with the happy animation when at least one file worked
        if ok:
            self._set_state("happy")
            if self._happy_after_id is not None:
                self.root.after_cancel(self._happy_after_id)
            self._happy_after_id = self.root.after(HAPPY_HOLD_MS, self._end_happy)

        # Feedback
        if ok and not bad:
            names = "\n".join(f"  {n.name}" for n in ok)
            Messagebox.show_info(f"已保存 {len(ok)} 个文件:\n{names}", parent=self.root)
        elif bad and not ok:
            details = "\n".join(f"  {p.name}: {msg}" for p, msg in bad)
            Messagebox.show_error(f"全部失败:\n{details}", parent=self.root)
        elif ok and bad:
            ok_names = "\n".join(f"  ✓ {n.name}" for n in ok)
            bad_names = "\n".join(f"  ✗ {p.name}: {msg}" for p, msg in bad)
            Messagebox.show_warning(
                f"部分成功:\n{ok_names}\n\n{bad_names}", parent=self.root,
            )


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
