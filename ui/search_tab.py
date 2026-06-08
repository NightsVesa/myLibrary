from __future__ import annotations

import tkinter as tk
import os
from pathlib import Path

from search.grep_search import search_notes
from storage.note_meta import (
    add_recent,
    get_tags,
    list_by_tag,
    is_favorite,
    list_favorites,
    list_recent,
    set_tags,
    toggle_favorite,
)
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SKY_DARK, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_BODY_BOLD, FONT_MONO,
    APP_BG, GLASS_EDGE, SOFT_SHADOW, AMBER_SOFT, PURPLE_SOFT,
    SPACING_SM, SPACING_MD, SPACING_LG, web_label, web_section,
    cartoon_entry, CartoonButton,
    _round_rect_points, PINK,
)
from ui.markdown_render import render_markdown_into, highlight_query, configure_markdown_tags

# Reader window dimensions
READER_W, READER_H = 1040, 780
READER_RADIUS = 28
READER_SHADOW = 8
READER_TITLE_H = 84
READER_PAD = 28
TRANSPARENT = "#ff00ff"
TOC_W = 220
TOC_GAP = 12
STATUS_H = 24

_READER_HEADING_RE = r"^(#{1,6})\s+(.+?)\s*$"


def extract_markdown_headings(source: str) -> list[tuple[int, str]]:
    """Return ATX headings outside frontmatter and fenced code blocks."""
    import re

    headings: list[tuple[int, str]] = []
    in_codeblock = False
    in_frontmatter = False
    for i, line in enumerate(source.splitlines()):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if stripped.startswith("```"):
            in_codeblock = not in_codeblock
            continue
        if in_codeblock:
            continue
        m = re.match(_READER_HEADING_RE, line)
        if m:
            title = m.group(2).strip()
            if title:
                headings.append((len(m.group(1)), title))
    return headings


def open_reader(
    root, path: Path, *, query: str = "",
    bg_color: str = "#fafbff", edge_color: str = "#d4b8f0",
) -> "_ReaderWindow":
    """Create a _ReaderWindow, destroying any previous active reader.

    Handles both cases defensively:
      - Normal: root._active_reader is a tk.Toplevel (.win)
      - Bug recovery: root._active_reader is a _ReaderWindow instance
    """
    prev = getattr(root, "_active_reader", None)
    saved_geo = None
    if prev is not None:
        try:
            if isinstance(prev, tk.Toplevel):
                saved_geo = prev.geometry()
                prev.destroy()
            else:
                saved_geo = prev.win.geometry()
                prev.close()
        except tk.TclError:
            pass
        root._active_reader = None

    if saved_geo:
        root._reader_geo = saved_geo

    reader = _ReaderWindow(
        root, path, query=query,
        bg_color=bg_color, edge_color=edge_color,
    )
    root._active_reader = reader.win

    restored = getattr(root, "_reader_geo", None)
    if restored:
        try:
            reader.win.geometry(restored)
            reader.win.update_idletasks()
            reader.w, reader.h = reader.win.winfo_width(), reader.win.winfo_height()
            if reader.w < reader.MIN_W:
                reader.w = READER_W
            reader._draw_chrome()
            reader._place_body()
            reader._place_toolbar()
        except tk.TclError:
            pass

    reader.show()
    return reader


def _middle_ellipsis(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 12:
        return text[-max_chars:]
    left = max(4, max_chars // 3)
    right = max_chars - left - 3
    return f"{text[:left]}...{text[-right:]}"


def extract_source_label(path: Path) -> str:
    """Read the first # heading from a file as the display label.

    Falls back to the cleaned stem (underscores/hyphens replaced with spaces).
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem.replace("_", " ").replace("-", " ")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ")


def resolve_source_path(
    rel_path: str, wiki_dir: Path, notes_dir: Path,
) -> Path | None:
    """Resolve a wiki relative path or raw note path to an absolute Path.

    `rel_path` may be a wiki page like "entities/openai.md" or an
    absolute / notes-relative raw note path.
    """
    wiki_dir = Path(wiki_dir)
    notes_dir = Path(notes_dir)
    wiki_candidate = (wiki_dir / rel_path).resolve()
    if wiki_candidate.exists():
        return wiki_candidate
    raw = Path(rel_path)
    if raw.is_absolute() and raw.exists():
        return raw
    notes_candidate = (notes_dir / rel_path).resolve()
    if notes_candidate.exists():
        return notes_candidate
    return None


def is_raw_note_path(path: Path, notes_dir: Path) -> bool:
    """Return True if *path* is inside *notes_dir* (a raw note, not a wiki page)."""
    try:
        Path(path).resolve().relative_to(Path(notes_dir).resolve())
        return True
    except ValueError:
        return False


def resolve_wiki_node_path(wiki_dir: Path, node_id: str) -> Path | None:
    """Resolve a wiki graph node id to an absolute file path.

    Returns None if the path is outside the wiki directory or doesn't exist.
    """
    wiki = Path(wiki_dir).resolve()
    path = (wiki / node_id).resolve()
    if not path.is_relative_to(wiki):
        return None
    if not path.exists():
        return None
    return path


def find_original_note_for_source(
    source_node_id: str, notes_dir: Path,
) -> Path | None:
    """For a wiki source node like 'sources/summary_foo.md', find the original note."""
    notes = Path(notes_dir)
    filename = source_node_id.split("/")[-1]
    if filename.startswith("summary_"):
        note_stem = filename[len("summary_"):]
    else:
        note_stem = filename
    candidate = notes / note_stem
    if candidate.exists():
        return candidate
    stem = Path(note_stem).stem
    for f in notes.glob(f"{stem}.*"):
        return f
    return None


def parse_wikilinks(text: str) -> list[str]:
    """Extract wikilink targets from [[target]] and [[target|label]] patterns."""
    import re
    matches = re.findall(r'\[\[([^\]]+)\]\]', text)
    return [m.split("|")[0].strip() for m in matches]


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
        self._search_after: str | None = None
        self._last_query = ""
        self._result_mode = "search"
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
        self.q_border.entry.bind("<KeyRelease>", self._on_query_key)
        self.q_border.entry.bind("<Return>", self._on_enter)

        CartoonButton(
            search_row, "🔍", command=self._on_search,
            kind="sky", width=58, height=44,
        ).grid(row=0, column=1, padx=(SPACING_MD, 0), sticky="e")

        self.search_hint = web_label(
            search_section.content, "输入文字或 #标签，Enter 打开首条结果",
            kind="hint",
        )
        self.search_hint.grid(row=1, column=0, sticky="w", pady=(SPACING_SM, 0))

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
        self.results_list.bind("<Return>", lambda _e: self._open_reader())

        meta_row = tk.Frame(result_section.content, bg=result_section.content.cget("bg"))
        meta_row.grid(row=2, column=0, sticky="ew", pady=(SPACING_SM, 0))
        meta_row.grid_columnconfigure(4, weight=1)

        self.favorite_btn = CartoonButton(
            meta_row, "★", command=self._toggle_selected_favorite,
            kind="orange", width=42, height=34,
        )
        self.favorite_btn.grid(row=0, column=0, sticky="w", padx=(0, SPACING_SM))

        CartoonButton(
            meta_row, "收藏", command=self._show_favorites,
            kind="orange", width=64, height=34,
        ).grid(row=0, column=1, sticky="w", padx=(0, SPACING_SM))

        CartoonButton(
            meta_row, "最近", command=self._show_recent,
            kind="sky", width=64, height=34,
        ).grid(row=0, column=2, sticky="w", padx=(0, SPACING_SM))

        CartoonButton(
            meta_row, "Inbox", command=lambda: self._show_by_tag("inbox"),
            kind="mint", width=64, height=34,
        ).grid(row=0, column=3, sticky="w", padx=(0, SPACING_SM))

        self.tags_border = cartoon_entry(
            meta_row, placeholder="标签",
            border_color=self._edge,
        )
        self.tags_border.grid(row=0, column=4, sticky="ew", padx=(0, SPACING_SM))
        self.tags_border.entry.bind("<Return>", self._save_tags_shortcut)

        CartoonButton(
            meta_row, "保存", command=self._save_selected_tags,
            kind="sky", width=64, height=34,
        ).grid(row=0, column=5, sticky="e")

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
        configure_markdown_tags(t, base_size=10)
        t.tag_config("hit", background="#FDE68A")
        t.tag_config("filename", font=("Microsoft YaHei", 13, "bold"), foreground=SKY_DARK)
        t.tag_config("filepath", foreground=TEXT_LIGHT, font=FONT_MONO,
                     spacing3=8)
        self.frame.after(120, self.q_border.entry.focus_set)

    # ── behaviour ──────────────────────────────────────────────────────────

    def _query(self) -> str:
        e = self.q_border.entry
        if getattr(e, "_is_placeholder", False):
            return ""
        return e.get().strip()

    def _on_search(self) -> None:
        query = self._query()
        if not query:
            self._clear_results()
            return
        self._run_search(query)

    def _on_query_key(self, event) -> None:
        if event.keysym in {"Return", "Up", "Down", "Left", "Right", "Escape"}:
            return
        if self._search_after:
            self.frame.after_cancel(self._search_after)
        self._search_after = self.frame.after(220, self._search_from_entry)

    def _search_from_entry(self) -> None:
        self._search_after = None
        query = self._query()
        if not query:
            self._clear_results()
            return
        if query == self._last_query:
            return
        self._run_search(query)

    def _on_enter(self, _event) -> str:
        query = self._query()
        if self._results and query == self._last_query:
            self._open_reader()
        else:
            self._on_search()
        return "break"

    def _clear_results(self) -> None:
        self._last_query = ""
        self._result_mode = "search"
        self._results = []
        self.results_list.delete(0, tk.END)
        self.result_header.config(text="结果")
        self._set_preview("输入关键词后自动搜索")
        self._sync_selected_meta()

    def _run_search(self, query: str) -> None:
        self._last_query = query
        self._result_mode = "search"
        if query.startswith("#") and len(query.strip()) > 1:
            tag = query.strip()[1:].strip()
            self._results = [{"file": path, "snippet": ""} for path in list_by_tag(tag)]
            result_title = f"标签 #{tag}"
        else:
            from search.grep_search import search_notes_ranked
            self._results = search_notes_ranked(query)
            result_title = "结果"
        self._refresh_results_list()
        if self._results:
            self.result_header.config(text=f"{result_title}（{len(self._results)} 条）")
            self.results_list.selection_set(0)
            self.results_list.activate(0)
            self._render_preview(0, highlight="" if query.startswith("#") else query)
        else:
            if query.startswith("#"):
                self.result_header.config(text=f"{result_title}（0 条）")
                self.results_list.insert(tk.END, "（没有找到带有此标签的笔记）")
            else:
                self.result_header.config(text=f"{result_title}（0 条）")
                self.results_list.insert(tk.END, "（无匹配结果）")
            self._set_preview("")
        self._sync_selected_meta()

    def _refresh_results_list(self) -> None:
        self.results_list.delete(0, tk.END)
        for r in self._results:
            self.results_list.insert(tk.END, self._result_label(r["file"]))

    def _result_label(self, path: Path) -> str:
        star = "★" if is_favorite(path) else " "
        tags = get_tags(path)
        tag_text = " ".join(f"#{tag}" for tag in tags[:3])
        return f"{star} {path.name}" + (f"  {tag_text}" if tag_text else "")

    def _selected_index(self) -> int | None:
        sel = self.results_list.curselection()
        if not sel or not self._results:
            return None
        idx = sel[0]
        if idx >= len(self._results):
            return None
        return idx

    def _selected_path(self) -> Path | None:
        idx = self._selected_index()
        if idx is None:
            return None
        return self._results[idx]["file"]

    def _on_select(self, _event) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        self._render_preview(idx, highlight=self._query())
        self._sync_selected_meta()

    def _sync_selected_meta(self) -> None:
        path = self._selected_path()
        entry = self.tags_border.entry
        entry.delete(0, tk.END)
        if path is None:
            self.favorite_btn.set_text("★")
            return
        tags = get_tags(path)
        if tags:
            entry.insert(0, " ".join(tags))
            entry.config(fg=TEXT_MAIN)
            entry._is_placeholder = False
        else:
            entry.event_generate("<FocusOut>")
        self.favorite_btn.set_text("★" if is_favorite(path) else "☆")

    def _save_tags_shortcut(self, _event) -> str:
        self._save_selected_tags()
        return "break"

    def _save_selected_tags(self) -> None:
        path = self._selected_path()
        if path is None:
            self.search_hint.config(text="先选中一篇笔记")
            return
        entry = self.tags_border.entry
        raw = "" if getattr(entry, "_is_placeholder", False) else entry.get()
        tags = set_tags(path, raw)
        self.search_hint.config(text=f"已保存标签: {' '.join(tags) if tags else '无'}")
        self._refresh_current_row()
        self._sync_selected_meta()

    def _toggle_selected_favorite(self) -> None:
        path = self._selected_path()
        if path is None:
            self.search_hint.config(text="先选中一篇笔记")
            return
        value = toggle_favorite(path)
        self.search_hint.config(text="已收藏" if value else "已取消收藏")
        self._refresh_current_row()
        self._sync_selected_meta()

    def _refresh_current_row(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        self.results_list.delete(idx)
        self.results_list.insert(idx, self._result_label(self._results[idx]["file"]))
        self.results_list.selection_set(idx)
        self.results_list.activate(idx)

    def _show_recent(self) -> None:
        paths = list_recent()
        self._show_path_list(paths, "最近打开")

    def _show_favorites(self) -> None:
        paths = list_favorites()
        self._show_path_list(paths, "收藏", empty_msg="还没有收藏任何笔记\n在结果列表点击 ★ 即可收藏")

    def _show_by_tag(self, tag: str) -> None:
        """Quick-filter results by a specific tag."""
        paths = list_by_tag(tag)
        self._show_path_list(paths, f"#{tag}", empty_msg=f"还没有 #{tag} 标签的笔记")

    def _show_path_list(self, paths: list[Path], title: str, *, empty_msg: str = "（暂无）") -> None:
        self._last_query = ""
        self._result_mode = title
        self._results = [{"file": path, "snippet": ""} for path in paths]
        self._refresh_results_list()
        if self._results:
            self.result_header.config(text=f"{title}（{len(self._results)} 条）")
            self.results_list.selection_set(0)
            self.results_list.activate(0)
            self._render_preview(0, highlight="")
        else:
            self.result_header.config(text=f"{title}（0 条）")
            self.results_list.insert(tk.END, empty_msg)
            self._set_preview("")
        self._sync_selected_meta()

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
        root = self.frame.nametowidget(".")
        reader = open_reader(root, path, query=query,
                             bg_color=self._bg, edge_color=self._edge)
        self._reader = reader.win


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
        self.path = Path(path).resolve()
        self.query = query
        self.bg_color = APP_BG
        self.edge_color = GLASS_EDGE
        self.w = READER_W
        self.h = READER_H
        self._mode = None    # None / "drag" / "resize"
        self._drag_start = None
        self._source = ""
        self._toc_entries: list[tuple[int, str, str]] = []
        self._toc_visible = True
        self._font_size = 11
        self._history: list[Path] = [self.path]
        self._history_pos = 0
        self._toolbar_buttons: dict[str, tk.Label] = {}
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
        self._build_toolbar()
        self._draw_chrome()
        self._show_loading()
        self._bind_events()
        self._render_markdown()

    # ── construction ───────────────────────────────────────────────────────

    def _build_window(self):
        win = tk.Toplevel(self.root)
        win.withdraw()
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

    def show(self) -> None:
        self.win.update_idletasks()
        self.win.deiconify()
        self.win.lift()

    def _build_canvas(self):
        c = tk.Canvas(
            self.win, width=self.w, height=self.h,
            bg=TRANSPARENT, highlightthickness=0, borderwidth=0,
        )
        c.place(x=0, y=0, width=self.w, height=self.h)
        self.canvas = c

    def _build_body(self):
        toc = tk.Frame(self.win, bg=GLASS_EDGE)
        toc_inner = tk.Frame(toc, bg=WHITE)
        toc_inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(
            toc_inner, text="目录", font=("Microsoft YaHei", 11, "bold"),
            fg=SKY_DARK, bg=WHITE, anchor="w",
        ).pack(fill="x", padx=10, pady=(10, 4))
        toc_list = tk.Listbox(
            toc_inner,
            font=("Microsoft YaHei", 9),
            activestyle="none",
            bg=WHITE, fg=TEXT_MAIN,
            selectbackground="#F5F3FF", selectforeground=SKY_DARK,
            relief="flat", borderwidth=0, highlightthickness=0,
        )
        toc_scroll = tk.Scrollbar(toc_inner, orient="vertical", command=toc_list.yview)
        toc_list.config(yscrollcommand=toc_scroll.set)
        toc_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 10))
        toc_scroll.pack(side="right", fill="y", pady=(0, 10))
        toc_list.bind("<<ListboxSelect>>", self._on_toc_select)
        self.toc = toc
        self.toc_list = toc_list

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
        configure_markdown_tags(text, base_size=11)
        # Ctrl+F highlights (light amber for any hit, deeper amber for current).
        text.tag_config("find_hit", background="#FDE68A")
        text.tag_config("find_current", background="#F59E0B", foreground="#1E1B4B")
        text.tag_config("reader_hit", background="#FEF3C7")

        self.body = body
        self.text = text
        self.status_label = tk.Label(
            self.win, text="", font=FONT_MONO, fg=TEXT_LIGHT, bg=APP_BG,
            anchor="w",
        )
        self._apply_reader_fonts()
        self._place_body()

    def _place_body(self):
        body_top = READER_TITLE_H + 18
        body_h = self.h - body_top - READER_SHADOW - READER_PAD - STATUS_H
        toc_visible = self._toc_visible and bool(self._toc_entries) and self.w >= 780
        toc_w = TOC_W if toc_visible else 0
        gap = TOC_GAP if toc_visible else 0
        if toc_visible:
            self.toc.place(
                x=READER_PAD, y=body_top,
                width=toc_w, height=max(50, body_h),
            )
        else:
            self.toc.place_forget()
        self.body.place(
            x=READER_PAD + toc_w + gap, y=body_top,
            width=self.w - READER_PAD * 2 - toc_w - gap, height=max(50, body_h),
        )
        self.status_label.place(
            x=READER_PAD, y=self.h - READER_SHADOW - STATUS_H,
            width=self.w - READER_PAD * 2, height=STATUS_H,
        )

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.win, bg=APP_BG, bd=0)

        def btn(key: str, text: str, command) -> None:
            label = tk.Label(
                bar, text=text, font=("Microsoft YaHei", 10, "bold"),
                bg=WHITE, fg=TEXT_MAIN, cursor="hand2",
                width=3, padx=2, pady=2,
                relief="flat", borderwidth=0,
                highlightbackground=GLASS_EDGE, highlightthickness=1,
            )
            label.pack(side="left", padx=(0, 5))
            label.bind("<Button-1>", lambda _e: command())
            label.bind("<Enter>", lambda _e: label.config(fg=SKY_DARK))
            label.bind("<Leave>", lambda _e: label.config(fg=TEXT_MAIN))
            self._toolbar_buttons[key] = label

        btn("back", "‹", lambda: self._navigate_history(-1))
        btn("forward", "›", lambda: self._navigate_history(1))
        btn("toc", "☰", self._toggle_toc)
        btn("smaller", "A-", lambda: self._set_font_delta(-1))
        btn("larger", "A+", lambda: self._set_font_delta(1))
        btn("copy", "⧉", self._copy_path)
        btn("folder", "⌂", self._open_folder)

        # Raw note metadata (favorite + tags) or wiki badge
        import config as _R_cfg
        from storage.note_meta import (
            is_favorite as _R_isfav,
            toggle_favorite as _R_togfav,
            get_tags as _R_gettags,
            set_tags as _R_settags,
        )
        if is_raw_note_path(self.path, _R_cfg.NOTES_DIR):
            def _fav_cmd():
                val = _R_togfav(self.path, notes_dir=_R_cfg.NOTES_DIR)
                self._toolbar_buttons["fav"].config(text="★" if val else "☆")

            fav_text = "★" if _R_isfav(self.path, notes_dir=_R_cfg.NOTES_DIR) else "☆"
            btn("fav", fav_text, _fav_cmd)

            tags = _R_gettags(self.path, notes_dir=_R_cfg.NOTES_DIR)
            if tags:
                tag_text = " ".join(f"#{t}" for t in tags[:3])
                tk.Label(
                    bar, text=tag_text, font=("Microsoft YaHei", 9),
                    bg=WHITE, fg=TEXT_LIGHT, padx=4,
                ).pack(side="left", padx=(0, 5))

            tag_var = tk.StringVar(value=" ".join(tags))
            self._tag_var = tag_var
            tag_entry = tk.Entry(
                bar, textvariable=tag_var, font=("Microsoft YaHei", 9),
                bg=WHITE, fg=TEXT_MAIN, relief="flat",
                borderwidth=0, highlightthickness=0, width=14,
            )
            tag_entry.pack(side="left", padx=(0, 4))

            def _save_tags():
                _R_settags(self.path, tag_var.get(), notes_dir=_R_cfg.NOTES_DIR)
                self._set_status("标签已保存")

            save_btn = tk.Label(
                bar, text="保存", font=("Microsoft YaHei", 9, "bold"),
                bg=WHITE, fg=SKY_DARK, cursor="hand2", padx=4,
            )
            save_btn.pack(side="left")
            save_btn.bind("<Button-1>", lambda _e: _save_tags())
            tag_entry.bind("<Return>", lambda _e: _save_tags())
            self._tag_entry = tag_entry
        else:
            tk.Label(
                bar, text="wiki", font=("Microsoft YaHei", 8, "bold"),
                bg="#EDE9FE", fg="#7C3AED", padx=6, pady=1,
            ).pack(side="left", padx=(6, 0))

        self.toolbar = bar
        self._place_toolbar()

    def _place_toolbar(self) -> None:
        if not hasattr(self, "toolbar"):
            return
        children = [c for c in self.toolbar.winfo_children() if c.winfo_ismapped()]
        width = max(292, len(children) * 48 + 16)
        self.toolbar.place(
            x=max(READER_PAD + 240, self.w - READER_PAD - width - 42),
            y=50, width=width, height=32,
        )

    def _set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def _show_loading(self) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, "正在渲染...")
        self.text.config(state=tk.DISABLED)
        self._set_status(str(self.path))

    def _apply_reader_fonts(self) -> None:
        s = self._font_size
        self.text.config(font=("Microsoft YaHei", s))
        self.text.tag_config("h1", font=("Microsoft YaHei", s + 7, "bold"))
        self.text.tag_config("h2", font=("Microsoft YaHei", s + 4, "bold"))
        self.text.tag_config("h3", font=("Microsoft YaHei", s + 2, "bold"))
        self.text.tag_config("h4", font=("Microsoft YaHei", s + 1, "bold"))
        self.text.tag_config("h5", font=("Microsoft YaHei", s, "bold"))
        self.text.tag_config("h6", font=("Microsoft YaHei", s, "bold"))
        self.text.tag_config("bold", font=("Microsoft YaHei", s, "bold"))
        self.text.tag_config("italic", font=("Microsoft YaHei", s, "italic"))
        self.text.tag_config("bold_italic", font=("Microsoft YaHei", s, "bold", "italic"))
        self.text.tag_config("code", font=("Consolas", max(9, s - 1)))
        self.text.tag_config("code_block", font=("Consolas", max(9, s - 1)))
        self.text.tag_config("list_bullet", font=("Microsoft YaHei", s, "bold"))
        self.text.tag_config("blockquote_marker", font=("Microsoft YaHei", s, "bold"))
        self.text.tag_config("blockquote", font=("Microsoft YaHei", s, "italic"))

    def _set_font_delta(self, delta: int) -> None:
        new_size = max(9, min(16, self._font_size + delta))
        if new_size == self._font_size:
            return
        self._font_size = new_size
        self._apply_reader_fonts()
        self._set_status(f"字号 {self._font_size}")

    def _toggle_toc(self) -> None:
        self._toc_visible = not self._toc_visible
        self._place_body()
        self._set_status("目录已显示" if self._toc_visible else "目录已隐藏")

    def _render_markdown(self):
        add_recent(self.path)
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text._link_map = {}
        try:
            self._source = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            self.text.insert(tk.END, f"[无法读取文件: {exc}]")
        else:
            render_markdown_into(self.text, self._source)
            if self.query:
                highlight_query(self.text, self.query, tag="reader_hit")
        self.text.config(state=tk.DISABLED)
        self.text.tag_bind("link", "<Button-1>", self._on_link_click)
        self.text.tag_config("link", foreground=SKY_DARK, underline=True)
        self._populate_toc()
        self._draw_chrome()
        self._place_body()
        self._refresh_toolbar_state()
        self._set_status(str(self.path))
        first = self.text.tag_ranges("reader_hit")
        if first:
            self.text.see(first[0])

    def _populate_toc(self) -> None:
        headings = extract_markdown_headings(self._source)
        self.toc_list.delete(0, tk.END)
        self._toc_entries = []
        start = "1.0"
        for level, title in headings:
            idx = self.text.search(title, start, stopindex=tk.END)
            if not idx:
                continue
            label = f"{'  ' * (level - 1)}{title}"
            self.toc_list.insert(tk.END, label)
            self._toc_entries.append((level, title, idx))
            start = f"{idx} lineend"
        self._show_backlinks()

    def _show_backlinks(self) -> None:
        """Populate the TOC sidebar with incoming wiki links (backlinks)."""
        import config as _cfg
        from llm.graph_data import parse_wiki_graph, get_incoming_edges

        wiki_dir = _cfg.WIKI_DIR.resolve()
        try:
            node_id = str(self.path.resolve().relative_to(wiki_dir)).replace("\\", "/")
        except ValueError:
            note_stem = self.path.stem
            node_id = f"sources/summary_{note_stem}.md"

        graph = parse_wiki_graph(_cfg.WIKI_DIR)
        incoming = get_incoming_edges(graph, node_id)

        if not incoming:
            return

        self.toc_list.insert(tk.END, "──── 反向链接 ────")
        sep_idx = self.toc_list.size() - 1
        self.toc_list.itemconfig(sep_idx, fg=TEXT_LIGHT)

        for edge in incoming:
            src_node = next((n for n in graph.nodes if n.id == edge.source), None)
            label = src_node.title if src_node else edge.source
            display = f"  {label}"
            self.toc_list.insert(tk.END, display)
            self._toc_entries.append((-1, edge.source, edge.source))

    def _on_toc_select(self, _event) -> None:
        sel = self.toc_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._toc_entries):
            return
        level, title, text_index = self._toc_entries[idx]
        if level == -1:
            import config as _cfg
            target = resolve_wiki_node_path(_cfg.WIKI_DIR, title)
            if target:
                self._load_path(target, add_history=True)
                self._set_status(f"跳转到: {title}")
            return
        self.text.see(text_index)
        self._set_status(title)

    def _on_link_click(self, event):
        idx = self.text.index(f"@{event.x},{event.y}")
        link_map = getattr(self.text, "_link_map", {})
        for (start, end), url in link_map.items():
            try:
                if self.text.compare(start, "<=", idx) and self.text.compare(idx, "<=", end):
                    self._load_path(url, add_history=True)
                    return
            except tk.TclError:
                continue

    def _load_path(self, path_str, *, add_history: bool = False) -> None:
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
        if not self._allowed_reader_path(target):
            return
        if not target.exists():
            return
        self.path = target
        add_recent(target)
        if add_history:
            del self._history[self._history_pos + 1:]
            self._history.append(target)
            self._history_pos = len(self._history) - 1
        self._render_markdown()

    def _allowed_reader_path(self, target: Path) -> bool:
        import config as _cfg
        roots = (_cfg.WIKI_DIR.resolve(), _cfg.NOTES_DIR.resolve())
        return any(target.is_relative_to(root) for root in roots)

    def _navigate_history(self, delta: int) -> None:
        next_pos = self._history_pos + delta
        if not (0 <= next_pos < len(self._history)):
            return
        self._history_pos = next_pos
        self.path = self._history[self._history_pos]
        self._render_markdown()

    def _refresh_toolbar_state(self) -> None:
        back = self._history_pos > 0
        forward = self._history_pos < len(self._history) - 1
        self._toolbar_buttons["back"].config(fg=TEXT_MAIN if back else TEXT_LIGHT)
        self._toolbar_buttons["forward"].config(fg=TEXT_MAIN if forward else TEXT_LIGHT)
        self._toolbar_buttons["toc"].config(fg=SKY_DARK if self._toc_visible else TEXT_MAIN)

    def _copy_path(self) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(str(self.path))
        self._set_status("已复制路径")

    def _open_folder(self) -> None:
        try:
            os.startfile(str(self.path.parent))
            self._set_status("已打开所在文件夹")
        except OSError as exc:
            self._set_status(f"无法打开文件夹: {exc}")

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
        name_chars = max(18, int((w - READER_PAD * 2 - 380 - emoji_w) / 9))
        c.create_text(
            title_x + emoji_w + 8, name_y,
            text=_middle_ellipsis(self.path.name, name_chars), anchor="w",
            font=("Microsoft YaHei", 15, "bold"), fill=TEXT_MAIN, tags="chrome",
        )
        path_chars = max(24, int((w - READER_PAD * 2 - 360) / 7))
        c.create_text(
            title_x, path_y, text=_middle_ellipsis(str(self.path), path_chars), anchor="w",
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
            self._place_toolbar()

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
