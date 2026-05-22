"""Cartoon Sky-Blue UI widgets — shared building blocks for all tabs.

Mirrors the look of `docs/cartoon-skyblue-ui-kit.html`:
- Inputs: white field, 2.5px sky-light border, 2px sky-light bottom shadow
- Buttons: solid colour body with 4px darker bottom shadow ("press-down" look)
- Labels: small bold uppercase-ish for hints
"""
import tkinter as tk

from PIL import Image, ImageDraw

# Palette (kept in sync with main_window.py)
SKY_PRIMARY = "#5CB8F0"
SKY_DARK = "#3a90cc"
SKY_LIGHT = "#a8d4f4"
SKY_PALE = "#e0f2ff"
WHITE = "#ffffff"
TEXT_MAIN = "#2c3e50"
TEXT_LIGHT = "#6b7c8f"
MINT = "#5DD5A8"
MINT_DARK = "#3db88a"
PINK = "#F07AA0"
ORANGE = "#FFC94A"
ORANGE_DARK = "#dba42a"

# ── Cartoon fonts ──────────────────────────────────────────────────────────
# YouYuan = soft, rounded sans (cartoon body text)
# Huawen Hupo = thick rounded display (titles)
# Comic Sans MS = playful English fallback
FONT_TITLE = ("华文琥珀", 13)
FONT_HEADING = ("华文琥珀", 11)
FONT_BODY = ("幼圆", 10)
FONT_BODY_BOLD = ("幼圆", 10, "bold")
FONT_HINT = ("幼圆", 9)
FONT_BUTTON = ("幼圆", 11, "bold")
FONT_INPUT = ("幼圆", 11)
FONT_MONO = ("Consolas", 9)
FONT_SHORTCUT = ("Comic Sans MS", 9, "bold")


def _round_rect_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def hex_to_rgb(s: str) -> tuple[int, int, int]:
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


def make_card_png(w: int, h: int, radius: int,
                  body_hex: str, edge_hex: str, shadow_hex: str,
                  shadow_px: int,
                  magenta=(255, 0, 255)) -> Image.Image:
    """Cartoon card: rounded body + edge outline + bottom drop-shadow strip.

    Pixels outside the visible card are filled with `magenta` so callers can
    use the OS transparent-color key for a true rounded-window effect.
    """
    img = Image.new("RGB", (w, h), magenta)
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle(
        [(0, shadow_px), (w - 1, h - 1)],
        radius=radius, fill=hex_to_rgb(shadow_hex),
    )
    dr.rounded_rectangle(
        [(0, 0), (w - 1, h - 1 - shadow_px)],
        radius=radius,
        fill=hex_to_rgb(body_hex),
        outline=hex_to_rgb(edge_hex), width=3,
    )
    return img


def _split_leading_emoji(s: str) -> tuple[str, str]:
    """Return (emoji_prefix, rest_text) where emoji_prefix holds any
    leading emoji codepoints (+ trailing space) and rest_text is the
    remainder.  Used so we can render emoji and CJK text with different
    fonts on the same button — `幼圆` etc. don't carry emoji glyphs.
    """
    if not s:
        return ("", "")
    # Common Unicode blocks that hold pictographic emoji
    def is_emoji(ch: str) -> bool:
        cp = ord(ch)
        return (
            0x1F300 <= cp <= 0x1FAFF or   # supplemental symbols & pictographs
            0x2600  <= cp <= 0x27BF  or   # misc symbols + dingbats
            0x2700  <= cp <= 0x27BF
        )

    i = 0
    while i < len(s) and (is_emoji(s[i]) or s[i] == " "):
        i += 1
    return (s[:i].rstrip(), s[i:].lstrip())


def cartoon_label(parent, text, *, kind="title"):
    """Small label.  `kind`: 'title' (bigger main), 'hint' (small grey).

    Background colour is inherited from `parent` so the label is invisible
    against any themed pane background (sky-pale / mint-pale / etc.).
    """
    if kind == "title":
        font = FONT_HEADING
        fg = TEXT_MAIN
    else:
        font = FONT_HINT
        fg = TEXT_LIGHT
    bg = parent.cget("bg") if hasattr(parent, "cget") else WHITE
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, anchor="w")


def cartoon_entry(parent, textvariable=None, *, placeholder=None,
                  height=36, bg_color=None, border_color=SKY_LIGHT):
    """Cartoon-style input.  Wraps `tk.Entry` in a coloured border Frame.

    `bg_color` controls the inner fill — defaults to the parent's bg so the
    input blends into the themed pane.  `border_color` is the 2px outline.
    """
    if bg_color is None:
        bg_color = parent.cget("bg") if hasattr(parent, "cget") else WHITE
    border = tk.Frame(parent, bg=border_color, bd=0)
    inner = tk.Frame(border, bg=bg_color)
    inner.pack(fill="both", expand=True, padx=2, pady=(2, 3))

    entry = tk.Entry(
        inner, textvariable=textvariable,
        font=FONT_INPUT,
        bg=bg_color, fg=TEXT_MAIN, insertbackground=SKY_DARK,
        relief="flat", borderwidth=0, highlightthickness=0,
    )
    entry.pack(fill="both", expand=True, padx=8, pady=4)

    def on_focus_in(_e):
        border.config(bg=SKY_PRIMARY)

    def on_focus_out(_e):
        border.config(bg=SKY_LIGHT)

    entry.bind("<FocusIn>", on_focus_in)
    entry.bind("<FocusOut>", on_focus_out)

    if placeholder:
        _attach_placeholder(entry, placeholder)

    border.entry = entry
    return border


def _attach_placeholder(entry, placeholder):
    PLACEHOLDER_FG = "#b0c8d8"
    REAL_FG = TEXT_MAIN

    def show():
        if not entry.get():
            entry.insert(0, placeholder)
            entry.config(fg=PLACEHOLDER_FG)
            entry._is_placeholder = True

    def hide(_e=None):
        if getattr(entry, "_is_placeholder", False):
            entry.delete(0, "end")
            entry.config(fg=REAL_FG)
            entry._is_placeholder = False

    def restore(_e=None):
        if not entry.get():
            show()

    entry._is_placeholder = False
    show()
    entry.bind("<FocusIn>", hide, add="+")
    entry.bind("<FocusOut>", restore, add="+")


def cartoon_textarea(parent, *, height=12, bg_color=None,
                     border_color=SKY_LIGHT):
    """Multi-line text area with the same cartoon border treatment."""
    if bg_color is None:
        bg_color = parent.cget("bg") if hasattr(parent, "cget") else WHITE
    border = tk.Frame(parent, bg=border_color, bd=0)
    inner = tk.Frame(border, bg=bg_color)
    inner.pack(fill="both", expand=True, padx=2, pady=(2, 3))

    text = tk.Text(
        inner, height=height, wrap=tk.WORD,
        font=FONT_BODY,
        bg=bg_color, fg=TEXT_MAIN, insertbackground=SKY_DARK,
        relief="flat", borderwidth=0, highlightthickness=0,
        padx=8, pady=6,
    )
    text.pack(fill="both", expand=True)

    border.text = text
    return border


class CartoonButton(tk.Canvas):
    """Solid cartoon button with a 4px coloured shadow underneath.

    Use `kind` to pick a color scheme: sky / mint / pink / orange / ghost.
    """

    KINDS = {
        "sky":     (SKY_PRIMARY, SKY_DARK, WHITE),
        "mint":    (MINT,       MINT_DARK,  WHITE),
        "pink":    (PINK,       "#cc5578",  WHITE),
        "orange":  (ORANGE,     ORANGE_DARK, "#7a5200"),
    }

    def __init__(self, parent, text, command=None, *, kind="sky", width=160, height=44):
        super().__init__(
            parent, width=width, height=height,
            bg=parent.cget("bg") if isinstance(parent.cget("bg"), str) else WHITE,
            highlightthickness=0, borderwidth=0,
        )
        self.command = command
        self.W, self.H = width, height
        self.body_color, self.shadow_color, self.fg = self.KINDS.get(
            kind, self.KINDS["sky"]
        )
        self.kind = kind
        self._pressed = False
        self._full_text = text
        self._build(text)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_configure)
        self.config(cursor="hand2")

    def _on_configure(self, e):
        # Repaint to match the actual size grid/pack gave us
        new_w, new_h = max(1, e.width), max(1, e.height)
        if new_w == self.W and new_h == self.H:
            return
        self.W, self.H = new_w, new_h
        self._build(self._full_text)

    def _build(self, text):
        self.delete("all")
        shadow_h = 4
        radius = 14
        self.shadow_id = self.create_polygon(
            _round_rect_points(1, shadow_h, self.W - 1, self.H - 1, radius),
            smooth=True, fill=self.shadow_color, outline="",
        )
        body_y2 = self.H - 1 - shadow_h if not self._pressed else self.H - 1 - shadow_h + 2
        body_y1 = 1 if not self._pressed else 3
        self.body_id = self.create_polygon(
            _round_rect_points(1, body_y1, self.W - 1, body_y2, radius),
            smooth=True, fill=self.body_color, outline="",
        )

        # Split emoji from text and render each with a font that supports it.
        # `幼圆` doesn't render emoji glyphs at all; rendering "💾 保存" with
        # 幼圆 swallows the emoji and shifts everything left.
        emoji, rest = _split_leading_emoji(text)
        cx = self.W // 2
        cy = (body_y1 + body_y2) // 2

        if emoji and rest:
            # Measure each piece, then centre the combined block
            from tkinter import font as tkfont
            f_emoji = tkfont.Font(font=("Segoe UI Emoji", FONT_BUTTON[1]))
            f_text = tkfont.Font(font=FONT_BUTTON)
            wE = f_emoji.measure(emoji)
            wT = f_text.measure(" " + rest)
            total = wE + wT
            start_x = cx - total // 2

            self.create_text(
                start_x, cy, text=emoji, anchor="w",
                fill=self.fg, font=("Segoe UI Emoji", FONT_BUTTON[1]),
            )
            self.text_id = self.create_text(
                start_x + wE, cy, text=" " + rest, anchor="w",
                fill=self.fg, font=FONT_BUTTON,
            )
        elif emoji:
            self.text_id = self.create_text(
                cx, cy, text=emoji, fill=self.fg,
                font=("Segoe UI Emoji", FONT_BUTTON[1]),
            )
        else:
            self.text_id = self.create_text(
                cx, cy, text=text, fill=self.fg, font=FONT_BUTTON,
            )

    def set_text(self, text):
        self._full_text = text
        self._build(text)

    def _on_enter(self, _e):
        self.itemconfig(self.body_id, fill=self.shadow_color)

    def _on_leave(self, _e):
        self.itemconfig(self.body_id, fill=self.body_color)
        if self._pressed:
            self._pressed = False
            self._build(self._full_text)

    def _on_press(self, _e):
        self._pressed = True
        self._build(self._full_text)

    def _on_release(self, _e):
        if not self._pressed:
            return
        self._pressed = False
        self._build(self._full_text)
        if self.command:
            self.command()
