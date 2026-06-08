"""Light-tech SaaS UI widgets - shared building blocks for all tabs.

- Inputs: white field, 1px subtle border, purple focus glow
- Buttons: flat solid colour, hover darkens
- Labels: clean sans-serif, generous whitespace
"""
import tkinter as tk

from PIL import Image, ImageDraw

# ── Palette (purple-amber SaaS) ─────────────────────────────────────────
SKY_PRIMARY = "#7C3AED"    # primary purple
SKY_DARK = "#6D28D9"       # dark purple
SKY_LIGHT = "#E5E7EB"      # subtle border
SKY_PALE = "#F5F3FF"       # pale purple tint
WHITE = "#ffffff"
TEXT_MAIN = "#1E1B4B"      # deep purple-black
TEXT_LIGHT = "#6B7280"     # warm grey
DASH_LINE = "#F3F4F6"      # near-invisible divider
LAVENDER = "#8B5CF6"       # violet accent
MINT = "#10B981"           # emerald
MINT_DARK = "#059669"      # dark emerald
PINK = "#F43F5E"           # rose
ORANGE = "#F59E0B"         # amber
ORANGE_DARK = "#D97706"    # dark amber

APP_BG = "#FBFAFF"
CARD_BG = "#FFFFFF"
CARD_TINT = "#F8F6FF"
GLASS_BG = "#FFFFFF"
GLASS_SOFT = "#FBFAFF"
GLASS_EDGE = "#E9DDFE"
SOFT_SHADOW = "#D9C8FB"
AMBER_SOFT = "#FFF7ED"
PURPLE_SOFT = "#F5F3FF"
PLACEHOLDER = "#9CA3AF"


# ── Fonts ──────────────────────────────────────────────────────────────────
FONT_TITLE = ("Microsoft YaHei", 16, "bold")
FONT_HEADING = ("Microsoft YaHei", 12, "bold")
FONT_BODY = ("Microsoft YaHei", 10)
FONT_BODY_BOLD = ("Microsoft YaHei", 10, "bold")
FONT_HINT = ("Microsoft YaHei", 9)
FONT_BUTTON = ("Microsoft YaHei", 11, "bold")
FONT_INPUT = ("Microsoft YaHei", 11)
FONT_MONO = ("Consolas", 9)
FONT_SHORTCUT = ("Consolas", 9)

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 20
SPACING_2XL = 24
CARD_RADIUS = 8


def _round_rect_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def hex_to_rgb(s: str) -> tuple[int, int, int]:
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


def _lighten(hex_color: str, factor: float = 0.15) -> str:
    """Return a lighter version of hex_color."""
    r, g, b = hex_to_rgb(hex_color)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, factor: float = 0.12) -> str:
    """Return a darker version of hex_color."""
    r, g, b = hex_to_rgb(hex_color)
    r = max(0, int(r * (1 - factor)))
    g = max(0, int(g * (1 - factor)))
    b = max(0, int(b * (1 - factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def make_card_png(w: int, h: int, radius: int,
                  body_hex: str, edge_hex: str, shadow_hex: str,
                  shadow_px: int,
                  magenta=(255, 0, 255)) -> Image.Image:
    """Glass-style card: rounded body + subtle border + soft shadow.

    Pixels outside the visible card are filled with `magenta` so callers can
    use the OS transparent-color key for a true rounded-window effect.
    """
    img = Image.new("RGB", (w, h), magenta)
    dr = ImageDraw.Draw(img)
    if shadow_px > 0:
        for i in range(shadow_px, 0, -1):
            factor = i / max(1, shadow_px)
            shadow = _lighten(shadow_hex, 0.45 + (1 - factor) * 0.25)
            dr.rounded_rectangle(
                [(i // 2, i), (w - 1 - i // 2, h - 1)],
                radius=radius, fill=hex_to_rgb(shadow),
            )
    dr.rounded_rectangle(
        [(0, 0), (w - 1, h - 1 - shadow_px)],
        radius=radius,
        fill=hex_to_rgb(body_hex), outline=hex_to_rgb(edge_hex), width=1,
    )
    dr.rounded_rectangle(
        [(0, 0), (w - 1, h - 1 - shadow_px)],
        radius=radius,
        outline=hex_to_rgb(edge_hex), width=1,
    )
    return img


def _split_leading_emoji(s: str) -> tuple[str, str]:
    """Return (emoji_prefix, rest_text) where emoji_prefix holds any
    leading emoji codepoints (+ trailing space) and rest_text is the
    remainder.  Used so we can render emoji and CJK text with different
    fonts on the same button.
    """
    if not s:
        return ("", "")
    def is_emoji(ch: str) -> bool:
        cp = ord(ch)
        return (
            0x1F300 <= cp <= 0x1FAFF or
            0x2600  <= cp <= 0x27BF  or
            0x2700  <= cp <= 0x27BF
        )

    i = 0
    while i < len(s) and (is_emoji(s[i]) or s[i] == " "):
        i += 1
    return (s[:i].rstrip(), s[i:].lstrip())


def _parent_bg(parent, fallback=WHITE):
    return parent.cget("bg") if hasattr(parent, "cget") else fallback


def web_label(parent, text, *, kind="body", accent=None):
    """SaaS-style label. `kind`: title / section / body / hint."""
    if kind == "title":
        font = FONT_TITLE
        fg = TEXT_MAIN
    elif kind == "section":
        font = FONT_HEADING
        fg = accent or TEXT_MAIN
    elif kind == "hint":
        font = FONT_HINT
        fg = TEXT_LIGHT
    else:
        font = FONT_BODY
        fg = TEXT_MAIN
    return tk.Label(parent, text=text, font=font, fg=fg, bg=_parent_bg(parent), anchor="w")


def web_section(parent, title: str | None = None, *, bg_color=None,
                border_color=GLASS_EDGE, accent=None, pad=SPACING_LG):
    """Return the content frame inside a lightly bordered SaaS card."""
    bg = bg_color or _parent_bg(parent, APP_BG)
    outer = tk.Frame(parent, bg=border_color, bd=0)
    inner = tk.Frame(outer, bg=GLASS_BG, bd=0)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if title:
        web_label(inner, title, kind="section", accent=accent).pack(
            fill="x", padx=pad, pady=(pad, SPACING_SM),
        )
    content = tk.Frame(inner, bg=GLASS_BG, bd=0)
    content.pack(fill="both", expand=True, padx=pad, pady=(0 if title else pad, pad))
    outer.content = content
    outer.inner = inner
    outer.bg_color = bg
    return outer


def cartoon_label(parent, text, *, kind="title"):
    """Label widget.  `kind`: 'title' (bold heading), 'hint' (small grey).

    Background colour is inherited from `parent`.
    """
    return web_label(parent, text, kind="title" if kind == "title" else "hint")


def cartoon_entry(parent, textvariable=None, *, placeholder=None,
                  height=40, bg_color=None, border_color=SKY_LIGHT):
    """Input field with subtle 1px border and purple focus glow.

    `bg_color` controls the inner fill — defaults to the parent's bg.
    `border_color` is the unfocused border (1px).
    """
    if bg_color is None:
        bg_color = WHITE
    border = tk.Frame(parent, bg=border_color, bd=0)
    inner = tk.Frame(border, bg=bg_color)
    inner.pack(fill="both", expand=True, padx=1, pady=1)

    entry = tk.Entry(
        inner, textvariable=textvariable,
        font=FONT_INPUT,
        bg=bg_color, fg=TEXT_MAIN, insertbackground=SKY_PRIMARY,
        relief="flat", borderwidth=0, highlightthickness=0,
    )
    entry.pack(fill="both", expand=True, padx=12, pady=7)

    def on_focus_in(_e):
        border.config(bg=SKY_PRIMARY)

    def on_focus_out(_e):
        border.config(bg=border_color)

    entry.bind("<FocusIn>", on_focus_in)
    entry.bind("<FocusOut>", on_focus_out)

    if placeholder:
        _attach_placeholder(entry, placeholder)

    border.entry = entry
    return border


def _attach_placeholder(entry, placeholder):
    REAL_FG = TEXT_MAIN

    def show():
        if not entry.get():
            entry.insert(0, placeholder)
            entry.config(fg=PLACEHOLDER)
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
    """Multi-line text area with the same 1px border treatment."""
    if bg_color is None:
        bg_color = WHITE
    border = tk.Frame(parent, bg=border_color, bd=0)
    inner = tk.Frame(border, bg=bg_color)
    inner.pack(fill="both", expand=True, padx=1, pady=1)

    text = tk.Text(
        inner, height=height, wrap=tk.WORD,
        font=FONT_BODY,
        bg=bg_color, fg=TEXT_MAIN, insertbackground=SKY_PRIMARY,
        relief="flat", borderwidth=0, highlightthickness=0,
        padx=12, pady=10,
    )
    text.pack(fill="both", expand=True)

    def on_focus_in(_e):
        border.config(bg=SKY_PRIMARY)

    def on_focus_out(_e):
        border.config(bg=border_color)

    text.bind("<FocusIn>", on_focus_in)
    text.bind("<FocusOut>", on_focus_out)

    border.text = text
    return border


class CartoonButton(tk.Canvas):
    """Flat solid-colour button with hover darkening.

    Use `kind` to pick a color scheme: sky / mint / pink / orange.
    """

    KINDS = {
        "sky":     (SKY_PRIMARY, SKY_DARK, WHITE),
        "mint":    (MINT,       MINT_DARK,  WHITE),
        "pink":    (PINK,       "#BE123C",  WHITE),
        "orange":  (ORANGE,     ORANGE_DARK, WHITE),
    }

    def __init__(self, parent, text, command=None, *, kind="sky", width=160, height=46):
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
        self._full_text = text
        self._build(text)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_configure)
        self.config(cursor="hand2")

    def _on_configure(self, e):
        new_w, new_h = max(1, e.width), max(1, e.height)
        if new_w == self.W and new_h == self.H:
            return
        self.W, self.H = new_w, new_h
        self._build(self._full_text)

    def _build(self, text):
        self.delete("all")
        radius = 10
        self.body_id = self.create_polygon(
            _round_rect_points(1, 1, self.W - 1, self.H - 1, radius),
            smooth=True, fill=self.body_color, outline="",
        )
        self.create_line(
            10, 2, self.W - 10, 2,
            fill=_lighten(self.body_color, 0.42), width=1,
        )

        emoji, rest = _split_leading_emoji(text)
        cx = self.W // 2
        cy = self.H // 2

        if emoji and rest:
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

    def _on_press(self, _e):
        pass

    def _on_release(self, _e):
        if self.command:
            self.command()
