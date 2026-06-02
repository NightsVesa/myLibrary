import tkinter as tk
from pathlib import Path

from search.grep_search import search_notes
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SKY_DARK, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_BODY_BOLD, FONT_MONO,
    APP_BG, GLASS_EDGE, SOFT_SHADOW, AMBER_SOFT, PURPLE_SOFT,
    SPACING_SM, SPACING_MD, SPACING_LG, web_label, web_section,
    cartoon_entry, CartoonButton,
    _round_rect_points, PINK,
)
from ui.markdown_render import render_markdown_into, highlight_query

# Reader window dimensions
READER_W, READER_H = 1040, 780
READER_RADIUS = 28
READER_SHADOW = 8
READER_TITLE_H = 84
READER_PAD = 28
TRANSPARENT = "#ff00ff"


def _draw_reader_glow(canvas, w, h, *, tags="chrome"):
    canvas.create_oval(max(22, w - 300), 18, w - 34, 220, fill=AMBER_SOFT, outline="", tags=tags)
    canvas.create_oval(22, 18, min(300, w - 34), 220, fill=PURPLE_SOFT, outline="", tags=tags)


class SearchTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._results: list[dict] = []
        self._reader: tk.Toplevel | None = None
        self._reader_bg_photo = None     # keep PhotoImage ref alive
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(2, weight=1)

        search_section = web_section(
            self.frame, "搜索关键词", bg_color=self._bg,
            border_color=self._edge, accent="#8B5CF6",
        )
        search_section.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_LG))
        search_section.content.grid_columnconfigure(0, weight=1)

        search_row = tk.Frame(search_section.content, bg=search_section.content.cget("bg"))
        search_row.grid(row=0, column=0, sticky="ew")
        search_row.grid_columnconfigure(0, weight=1)
        search_row.grid_columnconfigure(1, weight=0, minsize=58)

        self.q_border = cartoon_entry(
            search_row, placeholder="输入要查找的内容...",
            border_color=self._edge,
        )
        self.q_border.grid(row=0, column=0, sticky="ew")
        self.q_border.entry.bind("<Return>", lambda _e: self._on_search())

        CartoonButton(
            search_row, "🔍", command=self._on_search,
            kind="sky", width=58, height=44,
        ).grid(row=0, column=1, padx=(SPACING_MD, 0), sticky="e")

        result_section = web_section(
            self.frame, None, bg_color=self._bg,
            border_color=self._edge, accent="#8B5CF6",
        )
        result_section.grid(row=1, column=0, sticky="ew", pady=(0, SPACING_LG))
        result_section.content.grid_columnconfigure(0, weight=1)
        self.result_header = web_label(
            result_section.content, "结果", kind="section", accent="#8B5CF6",
        )
        self.result_header.grid(row=0, column=0, sticky="w", pady=(0, SPACING_SM))

        list_border = tk.Frame(result_section.content, bg=self._edge)
        list_border.grid(row=1, column=0, sticky="ew")
        list_inner = tk.Frame(list_border, bg=WHITE)
        list_inner.pack(fill="both", expand=True, padx=1, pady=1)

        scrollbar = tk.Scrollbar(list_inner, orient="vertical")
        self.results_list = tk.Listbox(
            list_inner, yscrollcommand=scrollbar.set,
            font=FONT_MONO, selectmode=tk.SINGLE,
            height=4, activestyle="dotbox",
            bg=WHITE, fg=TEXT_MAIN,
            selectbackground=WHITE, selectforeground=SKY_DARK,
            relief="flat", borderwidth=0, highlightthickness=0,
        )
        scrollbar.config(command=self.results_list.yview)
        self.results_list.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        scrollbar.pack(side="right", fill="y", pady=2)
        self.results_list.bind("<<ListboxSelect>>", self._on_select)
        self.results_list.bind("<Double-Button-1>", lambda _e: self._open_reader())

        preview_section = web_section(
            self.frame, None, bg_color=self._bg,
            border_color=self._edge, accent="#8B5CF6",
        )
        preview_section.grid(row=2, column=0, sticky="nsew", pady=(0, SPACING_MD))
        preview_section.content.grid_columnconfigure(0, weight=1)
        preview_section.content.grid_rowconfigure(1, weight=1)

        prev_head = tk.Frame(preview_section.content, bg=preview_section.content.cget("bg"))
        prev_head.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SM))
        prev_head.grid_columnconfigure(0, weight=1)
        web_label(prev_head, "Markdown 预览", kind="section", accent="#8B5CF6").grid(
            row=0, column=0, sticky="w",
        )
        CartoonButton(
            prev_head, "📖", command=self._open_reader,
            kind="sky", width=48, height=34,
        ).grid(row=0, column=1, sticky="e")

        prev_border = tk.Frame(preview_section.content, bg=self._edge)
        prev_border.grid(row=1, column=0, sticky="nsew")
        prev_inner = tk.Frame(prev_border, bg=WHITE)
        prev_inner.pack(fill="both", expand=True, padx=1, pady=1)

        prev_scroll = tk.Scrollbar(prev_inner, orient="vertical")
        self.preview_text = tk.Text(
            prev_inner, wrap=tk.WORD,
            font=FONT_BODY,
            yscrollcommand=prev_scroll.set,
            state=tk.DISABLED,
            bg=WHITE, fg=TEXT_MAIN,
            relief="flat", borderwidth=0, highlightthickness=0,
            padx=12, pady=10,
        )
        prev_scroll.config(command=self.preview_text.yview)
        self.preview_text.pack(side="left", fill="both", expand=True)
        prev_scroll.pack(side="right", fill="y")

        # ── Markdown render tags ───────────────────────────────────────────
        t = self.preview_text
        t.tag_config("h1", font=("Microsoft YaHei", 15, "bold"), foreground=SKY_DARK,
                     spacing1=8, spacing3=4)
        t.tag_config("h2", font=("Microsoft YaHei", 13, "bold"), foreground=SKY_DARK,
                     spacing1=6, spacing3=3)
        t.tag_config("h3", font=("Microsoft YaHei", 12, "bold"), foreground=SKY_DARK,
                     spacing1=4, spacing3=2)
        t.tag_config("h4", font=("Microsoft YaHei", 11, "bold"), foreground=SKY_DARK)
        t.tag_config("h5", font=("Microsoft YaHei", 10, "bold"), foreground=SKY_DARK)
        t.tag_config("h6", font=("Microsoft YaHei", 10, "bold"), foreground=TEXT_LIGHT)

        t.tag_config("bold",        font=FONT_BODY_BOLD)
        t.tag_config("italic",      font=("Microsoft YaHei", 10, "italic"))
        t.tag_config("bold_italic", font=("Microsoft YaHei", 10, "bold", "italic"))

        t.tag_config("code", font=("Consolas", 10),
                     background="#F5F3FF", foreground="#5B21B6")
        t.tag_config("code_block", font=("Consolas", 9),
                     background="#F5F3FF", foreground="#4C1D95",
                     lmargin1=14, lmargin2=14, spacing1=2, spacing3=2)

        t.tag_config("list_bullet", foreground=SKY_DARK,
                     font=FONT_BODY_BOLD)

        t.tag_config("blockquote_marker", foreground=SKY_DARK,
                     font=FONT_BODY_BOLD)
        t.tag_config("blockquote", foreground=TEXT_LIGHT,
                     font=("Microsoft YaHei", 10, "italic"), lmargin1=4, lmargin2=14)

        t.tag_config("hr", foreground=SKY_LIGHT, font=("Consolas", 8),
                     spacing1=4, spacing3=4, justify="center")

        t.tag_config("link", foreground=SKY_DARK, underline=True)

        t.tag_config("frontmatter", foreground=TEXT_LIGHT, font=FONT_MONO,
                     lmargin1=4, lmargin2=4)
        t.tag_config("hit", background="#FDE68A")

        t.tag_config("filename", font=("Microsoft YaHei", 13, "bold"), foreground=SKY_DARK)
        t.tag_config("filepath", foreground=TEXT_LIGHT, font=FONT_MONO,
                     spacing3=8)

    # ── behaviour ──────────────────────────────────────────────────────────

    def _query(self) -> str:
        e = self.q_border.entry
        if getattr(e, "_is_placeholder", False):
            return ""
        return e.get().strip()

    def _on_search(self) -> None:
        query = self._query()
        if not query:
            return
        self._results = search_notes(query)
        self.results_list.delete(0, tk.END)
        for r in self._results:
            self.results_list.insert(tk.END, r["file"].name)
        if self._results:
            self.result_header.config(text=f"结果（{len(self._results)} 条）")
            self.results_list.selection_set(0)
            self._render_preview(0, highlight=query)
        else:
            self.result_header.config(text="结果（0 条）")
            self.results_list.insert(tk.END, "（无匹配结果）")
            self._set_preview("")

    def _on_select(self, _event) -> None:
        sel = self.results_list.curselection()
        if not sel or not self._results:
            return
        idx = sel[0]
        if idx >= len(self._results):
            return
        self._render_preview(idx, highlight=self._query())

    def _render_preview(self, idx: int, *, highlight: str = "") -> None:
        path = self._results[idx]["file"]
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._set_preview(f"[无法读取文件: {exc}]")
            return

        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        # File header
        self.preview_text.insert(tk.END, f"📄 {path.name}\n", "filename")
        self.preview_text.insert(tk.END, f"{path}\n", "filepath")
        # Render the markdown body
        render_markdown_into(self.preview_text, source)

        if highlight:
            highlight_query(self.preview_text, highlight)

        self.preview_text.config(state=tk.DISABLED)
        first = self.preview_text.tag_ranges("hit")
        if first:
            self.preview_text.see(first[0])

    def _set_preview(self, text: str) -> None:
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, text)
        self.preview_text.config(state=tk.DISABLED)

    # ── independent reader window ──────────────────────────────────────────

    def _open_reader(self) -> None:
        """Pop up a large centred glass window with the full markdown body."""
        sel = self.results_list.curselection()
        if not sel or not self._results:
            return
        idx = sel[0]
        if idx >= len(self._results):
            return
        path = self._results[idx]["file"]
        self._show_reader(path, query=self._query())

    def _show_reader(self, path, *, query: str = "") -> None:
        # Reader is independent of the search panel.
        root = self.frame.nametowidget(".")
        prev = getattr(root, "_active_reader", None)
        if prev is not None and prev.winfo_exists():
            prev.destroy()
        root._active_reader = None

        reader = _ReaderWindow(
            root, path, query=query,
            bg_color=self._bg, edge_color=self._edge,
        )
        root._active_reader = reader.win
        self._reader = reader.win

    def _close_reader(self) -> None:
        root = self.frame.nametowidget(".") if self.frame.winfo_exists() else None
        if self._reader is not None and self._reader.winfo_exists():
            self._reader.destroy()
        self._reader = None
        self._reader_bg_photo = None
        if root is not None and hasattr(root, "_active_reader"):
            root._active_reader = None


class _ReaderWindow:
    """Resizable, draggable, frameless markdown reader.

    Background, title bar, close button, and resize handle are all drawn
    directly on a single canvas so the window can be resized cheaply
    (no PIL redraw needed — just `coords()` updates).
    """

    MIN_W = 480
    MIN_H = 360
    HANDLE_SIZE = 22
    DEFAULT_FONT_BODY = ("Microsoft YaHei", 11)

    def __init__(self, root, path, *, query: str, bg_color: str, edge_color: str):
        self.root = root
        self.path = path
        self.query = query
        self.bg_color = APP_BG
        self.edge_color = GLASS_EDGE
        self.w = READER_W
        self.h = READER_H
        self._mode = None    # None / "drag" / "resize"
        self._drag_start = None
        # Local find state (Ctrl+F search bar)
        self._find_bar: tk.Frame | None = None
        self._find_entry: tk.Entry | None = None
        self._find_var: tk.StringVar | None = None
        self._find_count_label: tk.Label | None = None
        self._find_matches: list[int] = []  # character offsets of each hit
        self._find_current: int = 0

        self._build_window()
        self._build_canvas()
        self._build_body()
        self._render_markdown()
        self._draw_chrome()
        self._bind_events()

    # ── construction ───────────────────────────────────────────────────────

    def _build_window(self):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.config(bg=TRANSPARENT)
        try:
            win.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = (sw - self.w) // 2
        y = (sh - self.h) // 2
        win.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self.win = win

    def _build_canvas(self):
        c = tk.Canvas(
            self.win, width=self.w, height=self.h,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        c.place(x=0, y=0, width=self.w, height=self.h)
        self.canvas = c

    def _build_body(self):
        body = tk.Frame(self.win, bg=GLASS_EDGE)
        inner = tk.Frame(body, bg=WHITE)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        scroll = tk.Scrollbar(inner, orient="vertical")
        text = tk.Text(
            inner, wrap=tk.WORD,
            font=self.DEFAULT_FONT_BODY,
            yscrollcommand=scroll.set,
            bg=WHITE, fg=TEXT_MAIN,
            relief="flat", borderwidth=0, highlightthickness=0,
            padx=16, pady=14,
        )
        scroll.config(command=text.yview)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # markdown tags
        text.tag_config("h1", font=("Microsoft YaHei", 18, "bold"), foreground=SKY_DARK,
                        spacing1=12, spacing3=8)
        text.tag_config("h2", font=("Microsoft YaHei", 15, "bold"), foreground=SKY_DARK,
                        spacing1=10, spacing3=6)
        text.tag_config("h3", font=("Microsoft YaHei", 13, "bold"), foreground=SKY_DARK,
                        spacing1=6, spacing3=4)
        text.tag_config("h4", font=("Microsoft YaHei", 12, "bold"), foreground=SKY_DARK)
        text.tag_config("h5", font=("Microsoft YaHei", 11, "bold"), foreground=SKY_DARK)
        text.tag_config("h6", font=("Microsoft YaHei", 11, "bold"), foreground=TEXT_LIGHT)
        text.tag_config("bold",        font=("Microsoft YaHei", 11, "bold"))
        text.tag_config("italic",      font=("Microsoft YaHei", 11, "italic"))
        text.tag_config("bold_italic", font=("Microsoft YaHei", 11, "bold", "italic"))
        text.tag_config("code", font=("Consolas", 10),
                        background="#F5F3FF", foreground="#5B21B6")
        text.tag_config("code_block", font=("Consolas", 10),
                        background="#F5F3FF", foreground="#4C1D95",
                        lmargin1=18, lmargin2=18, spacing1=4, spacing3=4)
        text.tag_config("list_bullet", foreground=SKY_DARK,
                        font=("Microsoft YaHei", 11, "bold"))
        text.tag_config("blockquote_marker", foreground=SKY_DARK,
                        font=("Microsoft YaHei", 11, "bold"))
        text.tag_config("blockquote", foreground=TEXT_LIGHT,
                        font=("Microsoft YaHei", 11, "italic"), lmargin1=4, lmargin2=18)
        text.tag_config("hr", foreground=SKY_LIGHT, font=("Consolas", 8),
                        spacing1=6, spacing3=6, justify="center")
        text.tag_config("link", foreground=SKY_DARK, underline=True)
        text.tag_config("frontmatter", foreground=TEXT_LIGHT, font=FONT_MONO,
                        lmargin1=4, lmargin2=4)
        # Ctrl+F highlights (light amber for any hit, deeper amber for current).
        text.tag_config("find_hit", background="#FDE68A")
        text.tag_config("find_current", background="#F59E0B", foreground="#1E1B4B")

        self.body = body
        self.text = text
        self._place_body()

    def _place_body(self):
        body_top = READER_TITLE_H + 18
        body_h = self.h - body_top - READER_SHADOW - READER_PAD
        self.body.place(
            x=READER_PAD, y=body_top,
            width=self.w - READER_PAD * 2, height=max(50, body_h),
        )

    def _render_markdown(self):
        try:
            source = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            self.text.insert(tk.END, f"[无法读取文件: {exc}]")
        else:
            render_markdown_into(self.text, source)
        self.text.config(state=tk.DISABLED)
        self.text.tag_bind("link", "<Button-1>", self._on_link_click)
        self.text.tag_config("link", foreground=SKY_DARK, underline=True)

    def _on_link_click(self, event):
        idx = self.text.index(f"@{event.x},{event.y}")
        link_map = getattr(self.text, "_link_map", {})
        for (start, end), url in link_map.items():
            try:
                if self.text.compare(start, "<=", idx) and self.text.compare(idx, "<=", end):
                    self._load_path(url)
                    return
            except tk.TclError:
                continue

    def _load_path(self, path_str) -> None:
        """Navigate the reader to a different wiki page.
        Accepts a Path (from _open_reader) or a str (from a ## Related link).
        """
        import config as _cfg
        if isinstance(path_str, Path):
            target = path_str.resolve()
        else:
            target = (self.path.parent / path_str).resolve()
            if not target.exists():
                target = (_cfg.WIKI_DIR / path_str).resolve()
        if not target.is_relative_to(_cfg.WIKI_DIR.resolve()):
            return
        if not target.exists():
            return
        self.path = target
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self._render_markdown()

    # ── chrome (drawn on canvas, re-drawn on resize) ───────────────────────

    def _draw_chrome(self):
        c = self.canvas
        c.delete("chrome")
        w, h = self.w, self.h

        # Background fill (everything outside the rounded card is magenta)
        c.create_rectangle(
            0, 0, w, h, fill=TRANSPARENT, outline="", tags="chrome",
        )
        # Bottom drop-shadow plate
        c.create_polygon(
            _round_rect_points(0, READER_SHADOW, w, h, READER_RADIUS),
            smooth=True, fill=SOFT_SHADOW, outline="", tags="chrome",
        )
        # Card body
        c.create_polygon(
            _round_rect_points(0, 0, w, h - READER_SHADOW, READER_RADIUS),
            smooth=True, fill=self.bg_color,
            outline=self.edge_color, width=1, tags="chrome",
        )
        _draw_reader_glow(c, w, h)

        # Title bar — file name on row 1, path on row 2 (well-separated)
        from tkinter import font as tkfont
        title_x = READER_PAD
        name_y = 30
        path_y = 60
        f_emoji = tkfont.Font(font=("Segoe UI Emoji", 14))
        c.create_text(
            title_x, name_y, text="📄", anchor="w",
            font=("Segoe UI Emoji", 14), fill=TEXT_MAIN, tags="chrome",
        )
        emoji_w = f_emoji.measure("📄")
        c.create_text(
            title_x + emoji_w + 8, name_y, text=self.path.name, anchor="w",
            font=("Microsoft YaHei", 15, "bold"), fill=TEXT_MAIN, tags="chrome",
        )
        c.create_text(
            title_x, path_y, text=str(self.path), anchor="w",
            font=FONT_MONO, fill=TEXT_LIGHT, tags="chrome",
        )

        # Close button (rounded grey square) — vertically aligned with file name
        cx2 = w - READER_PAD
        cx1 = cx2 - 30
        ccy1 = 12
        ccy2 = ccy1 + 28
        self._close_box = (cx1, ccy1, cx2, ccy2)
        self._close_body_id = c.create_polygon(
            _round_rect_points(cx1, ccy1, cx2, ccy2, 10),
            smooth=True, fill=WHITE, outline=GLASS_EDGE, width=1,
            tags="chrome",
        )
        self._close_x_id = c.create_text(
            (cx1 + cx2) // 2, (ccy1 + ccy2) // 2,
            text="✕", fill=TEXT_LIGHT, font=FONT_BODY_BOLD, tags="chrome",
        )

        # Dashed separator
        c.create_line(
            READER_PAD, READER_TITLE_H + 10,
            w - READER_PAD, READER_TITLE_H + 10,
            fill=GLASS_EDGE, width=1, tags="chrome",
        )

        # Resize handle (bottom-right corner — three short diagonal hatches)
        hs = self.HANDLE_SIZE
        hx2 = w - 10
        hy2 = h - READER_SHADOW - 8
        hx1 = hx2 - hs
        hy1 = hy2 - hs
        self._handle_box = (hx1, hy1, hx2, hy2)
        for step in (3, 8, 13):
            c.create_line(
                hx2 - step, hy2,
                hx2,       hy2 - step,
                fill="#C4B5FD", width=2, capstyle="round", tags="chrome",
            )

    # ── event handling ─────────────────────────────────────────────────────

    def _bind_events(self):
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Esc closes the find bar if open, otherwise the whole window.
        self.win.bind("<Escape>", self._on_escape)
        # Ctrl+F opens / focuses the local find bar.
        self.win.bind("<Control-Key-f>", self._open_find)
        self.win.bind("<Control-Key-F>", self._open_find)
        self.text.bind("<Control-Key-f>", self._open_find)
        self.text.bind("<Control-Key-F>", self._open_find)
        self.win.focus_force()

    def _on_escape(self, _e):
        if self._find_bar is not None:
            self._close_find()
        else:
            self.close()

    def _hit_close(self, x, y):
        cx1, cy1, cx2, cy2 = self._close_box
        return cx1 <= x <= cx2 and cy1 <= y <= cy2

    def _hit_handle(self, x, y):
        hx1, hy1, hx2, hy2 = self._handle_box
        return hx1 <= x <= hx2 and hy1 <= y <= hy2

    def _on_hover(self, e):
        if self._hit_close(e.x, e.y):
            self.canvas.itemconfig(self._close_body_id, fill="#feecec", outline=PINK)
            self.canvas.itemconfig(self._close_x_id, fill=PINK)
            self.canvas.config(cursor="hand2")
        elif self._hit_handle(e.x, e.y):
            self.canvas.itemconfig(self._close_body_id, fill=WHITE, outline=GLASS_EDGE)
            self.canvas.itemconfig(self._close_x_id, fill=TEXT_LIGHT)
            self.canvas.config(cursor="bottom_right_corner")
        elif e.y < READER_TITLE_H:
            self.canvas.itemconfig(self._close_body_id, fill=WHITE, outline=GLASS_EDGE)
            self.canvas.itemconfig(self._close_x_id, fill=TEXT_LIGHT)
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.itemconfig(self._close_body_id, fill=WHITE, outline=GLASS_EDGE)
            self.canvas.itemconfig(self._close_x_id, fill=TEXT_LIGHT)
            self.canvas.config(cursor="arrow")

    def _on_press(self, e):
        if self._hit_close(e.x, e.y):
            self.close()
            return
        if self._hit_handle(e.x, e.y):
            self._mode = "resize"
            self._drag_start = (e.x_root, e.y_root, self.w, self.h)
            return
        if e.y < READER_TITLE_H:
            self._mode = "drag"
            self._drag_start = (
                e.x_root - self.win.winfo_x(),
                e.y_root - self.win.winfo_y(),
            )

    def _on_drag(self, e):
        if self._mode == "drag":
            off_x, off_y = self._drag_start
            self.win.geometry(f"+{e.x_root - off_x}+{e.y_root - off_y}")
        elif self._mode == "resize":
            sx, sy, sw, sh = self._drag_start
            new_w = max(self.MIN_W, sw + (e.x_root - sx))
            new_h = max(self.MIN_H, sh + (e.y_root - sy))
            if new_w == self.w and new_h == self.h:
                return
            self.w, self.h = new_w, new_h
            self.win.geometry(f"{new_w}x{new_h}")
            self.canvas.config(width=new_w, height=new_h)
            self.canvas.place_configure(width=new_w, height=new_h)
            self._draw_chrome()
            self._place_body()

    def _on_release(self, _e):
        self._mode = None
        self._drag_start = None

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()
        root = self.root
        if hasattr(root, "_active_reader"):
            root._active_reader = None

    # ── Ctrl+F local find ─────────────────────────────────────────────────

    def _open_find(self, _e=None):
        """Show the find bar (or just focus its entry if already open)."""
        if self._find_bar is not None and self._find_bar.winfo_exists():
            self._find_entry.focus_set()
            self._find_entry.select_range(0, "end")
            return "break"

        bar = tk.Frame(self.win, bg=WHITE, bd=0,
                       highlightbackground=GLASS_EDGE, highlightthickness=1)
        bar.place(relx=1.0, x=-READER_PAD - 4, y=READER_TITLE_H + 18,
                  anchor="ne", width=360, height=42)

        # Pack right-anchored controls FIRST so they always claim their space;
        # the entry then fills whatever remains in the middle.
        def mini(text, command, fg=TEXT_LIGHT):
            b = tk.Label(
                bar, text=text, font=("Microsoft YaHei", 12, "bold"),
                bg=WHITE, fg=fg, cursor="hand2", padx=4,
            )
            b.bind("<Button-1>", lambda _e: command())
            b.bind("<Enter>", lambda _e: b.config(fg=SKY_DARK))
            b.bind("<Leave>", lambda _e: b.config(fg=fg))
            return b

        mini("✕", self._close_find).pack(side="right", padx=(2, 8))
        mini("▼", lambda: self._find_next()).pack(side="right")
        mini("▲", lambda: self._find_prev()).pack(side="right")

        count = tk.Label(
            bar, text="0/0", font=("Consolas", 9),
            bg=WHITE, fg=TEXT_LIGHT, width=8, anchor="e",
        )
        count.pack(side="right", padx=(2, 4))

        # Use a StringVar with a trace so we only react to *text changes*,
        # not every keypress (Enter must not re-run _find_update).
        var = tk.StringVar()
        var.trace_add("write", lambda *_: self._find_update())
        entry = tk.Entry(
            bar, textvariable=var, font=("Microsoft YaHei", 11),
            bg=WHITE, fg=TEXT_MAIN, insertbackground=SKY_DARK,
            relief="flat", borderwidth=0, highlightthickness=0,
        )
        entry.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=6)
        entry.bind("<Return>", self._find_next)
        entry.bind("<Shift-Return>", self._find_prev)
        entry.bind("<Escape>", lambda _e: self._close_find())

        self._find_bar = bar
        self._find_entry = entry
        self._find_var = var
        self._find_count_label = count

        entry.focus_set()
        return "break"

    def _close_find(self):
        if self._find_bar is not None and self._find_bar.winfo_exists():
            self._find_bar.destroy()
        self._find_bar = None
        self._find_entry = None
        self._find_var = None
        self._find_count_label = None
        self.text.tag_remove("find_hit", "1.0", tk.END)
        self.text.tag_remove("find_current", "1.0", tk.END)
        self._find_matches = []
        self._find_current = 0

    def _find_update(self, _e=None):
        if self._find_entry is None:
            return
        needle = self._find_entry.get()
        self.text.tag_remove("find_hit", "1.0", tk.END)
        self.text.tag_remove("find_current", "1.0", tk.END)
        if not needle:
            self._find_matches = []
            self._find_count_label.config(text="0/0")
            return
        # Find all matches (case-insensitive, character offsets)
        full = self.text.get("1.0", tk.END)
        n_low = needle.lower()
        full_low = full.lower()
        matches: list[int] = []
        idx = 0
        while True:
            pos = full_low.find(n_low, idx)
            if pos == -1:
                break
            matches.append(pos)
            start = f"1.0 + {pos} chars"
            end = f"1.0 + {pos + len(needle)} chars"
            self.text.tag_add("find_hit", start, end)
            idx = pos + len(needle)
        self._find_matches = matches
        self._find_current = 0
        if matches:
            self._mark_current(needle)
        self._refresh_count_label()

    def _find_next(self, _e=None):
        if not self._find_matches:
            return "break"
        self._find_current = (self._find_current + 1) % len(self._find_matches)
        self._mark_current(self._find_entry.get())
        self._refresh_count_label()
        return "break"

    def _find_prev(self, _e=None):
        if not self._find_matches:
            return "break"
        self._find_current = (self._find_current - 1) % len(self._find_matches)
        self._mark_current(self._find_entry.get())
        self._refresh_count_label()
        return "break"

    def _mark_current(self, needle: str):
        self.text.tag_remove("find_current", "1.0", tk.END)
        pos = self._find_matches[self._find_current]
        start = f"1.0 + {pos} chars"
        end = f"1.0 + {pos + len(needle)} chars"
        self.text.tag_add("find_current", start, end)
        self.text.see(start)

    def _refresh_count_label(self):
        if self._find_count_label is None:
            return
        total = len(self._find_matches)
        cur = self._find_current + 1 if total else 0
        self._find_count_label.config(text=f"{cur}/{total}")
