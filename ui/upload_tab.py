import queue
import shutil
import threading
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog

import config as _cfg
from converter.ocr_converter import (
    IMAGE_SUFFIXES,
    OCRUnavailableError,
    enrich_markdown_images,
    image_to_markdown,
    is_image_file,
)
from converter.docx_converter import docx_to_markdown
from converter.pdf_converter import pdf_to_markdown
from storage.note_store import save_note, save_raw_file
from llm.wiki_engine import background_ingest
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, TEXT_LIGHT, TEXT_MAIN,
    FONT_BODY, FONT_BODY_BOLD, SPACING_MD, SPACING_LG, SPACING_SM,
    web_label, web_section, cartoon_textarea, cartoon_entry, CartoonButton,
)


_INBOX_SUFFIXES = {".md", ".docx", ".pdf", *IMAGE_SUFFIXES}


def _find_uningested_notes() -> list[Path]:
    """Return note paths that have no wiki source summary."""
    notes_dir = Path(_cfg.NOTES_DIR)
    wiki_dir = Path(_cfg.WIKI_DIR)
    if not notes_dir.exists():
        return []
    note_files = {
        f for f in notes_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _INBOX_SUFFIXES
    }
    sources_dir = wiki_dir / "sources"
    if sources_dir.exists():
        ingested_stems = {
            sf.stem[len("summary_"):]
            for sf in sources_dir.iterdir()
            if sf.name.startswith("summary_") and sf.suffix == ".md"
        }
        note_files = {f for f in note_files if f.stem not in ingested_stems}
    return sorted(note_files)


def _read_inbox_preview(note_path: Path) -> str:
    if note_path.suffix.lower() == ".md":
        return note_path.read_text(encoding="utf-8")
    return f"原始文件: {note_path.name}\n\n点击“收录”后会读取并更新 wiki。"


def _md_passthrough(path: Path) -> str:
    """Read Markdown and add OCR text for local image references."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return enrich_markdown_images(text, path.parent)


SUPPORTED = {
    ".docx": docx_to_markdown,
    ".pdf":  pdf_to_markdown,
    ".md":   _md_passthrough,
}
SUPPORTED.update({suffix: image_to_markdown for suffix in IMAGE_SUFFIXES})


def save_supported_upload(path: Path) -> Path:
    """Save a supported upload to notes, converting images/Markdown to .md.

    Image files are copied to ``notes/.assets/`` and saved as a Markdown
    file containing the image link plus OCR text.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"不支持的文件格式: {suffix}")
    if is_image_file(path):
        asset_dir = Path(_cfg.NOTES_DIR) / ".assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_name = path.name
        asset_dest = asset_dir / asset_name
        if asset_dest.exists():
            stem, ext = path.stem, path.suffix
            asset_name = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
            asset_dest = asset_dir / asset_name
        shutil.copy2(path, asset_dest)
        md = image_to_markdown(path)
        body = f"![](.assets/{asset_name})\n\n{md}"
        return save_note(body, title=path.stem)
    if suffix == ".md":
        md = _md_passthrough(path)
        return save_note(md, title=path.stem)
    return save_raw_file(path)


_VIEW_UPLOAD = "upload"
_VIEW_INBOX = "inbox"


class UploadTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT, *, main=None) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._main = main
        self._selected: Path | None = None
        self._preview_q: queue.Queue[tuple[Path, str, str]] = queue.Queue()
        self._save_q: queue.Queue[tuple[Path, str, Path | None, str]] = queue.Queue()
        self._preview_polling = False
        self._save_polling = False
        self._saving = False
        self._view = _VIEW_UPLOAD
        self._build()

    # ── build ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        # ── upload view widgets ───────────────────────────────────
        self._upload_frame = tk.Frame(self.frame, bg=self._bg)
        self._upload_frame.grid_columnconfigure(0, weight=1)
        self._upload_frame.grid_rowconfigure(1, weight=1)

        picker_section = web_section(
            self._upload_frame, "选择 DOCX / PDF / Markdown / 图片文件",
            bg_color=self._bg, border_color=self._edge, accent="#10B981",
        )
        picker_section.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_LG))
        picker_section.content.grid_columnconfigure(0, weight=1)

        pick_row = tk.Frame(picker_section.content, bg=picker_section.content.cget("bg"))
        pick_row.grid(row=0, column=0, sticky="ew")
        pick_row.grid_columnconfigure(0, weight=1)
        pick_row.grid_columnconfigure(1, weight=0, minsize=58)

        self._file_holder = tk.Frame(pick_row, bg=self._edge)
        self._file_holder.grid(row=0, column=0, sticky="ew")
        self._file_inner = tk.Frame(self._file_holder, bg=WHITE)
        self._file_inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.file_label = tk.Label(
            self._file_inner, text="未选择文件",
            font=FONT_BODY, fg=TEXT_LIGHT, bg=WHITE, anchor="w",
        )
        self.file_label.pack(fill="both", expand=True, padx=12, pady=10)

        CartoonButton(
            pick_row, "📂", command=self._pick_file,
            kind="mint", width=56, height=44,
        ).grid(row=0, column=1, padx=(SPACING_MD, 0), sticky="e")

        preview_section = web_section(
            self._upload_frame, "预览（前 500 字符）",
            bg_color=self._bg, border_color=self._edge, accent="#10B981",
        )
        preview_section.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_LG))
        preview_section.content.grid_columnconfigure(0, weight=1)
        preview_section.content.grid_rowconfigure(0, weight=1)

        self.preview_border = cartoon_textarea(
            preview_section.content, height=8, border_color=self._edge,
        )
        self.preview_border.text.config(state=tk.DISABLED)
        self.preview_border.grid(row=0, column=0, sticky="nsew")

        self.save_btn = CartoonButton(
            self._upload_frame, "💾 转换并保存", command=self._on_save,
            kind="mint", height=48,
        )
        self.save_btn.grid(row=2, column=0, sticky="ew", pady=(0, SPACING_SM))

        # ── inbox view widgets ────────────────────────────────────
        self._inbox_frame = tk.Frame(self.frame, bg=self._bg)
        self._inbox_frame.grid_columnconfigure(0, weight=1)
        self._inbox_frame.grid_rowconfigure(1, weight=3)
        self._inbox_frame.grid_rowconfigure(2, weight=2)

        inbox_header = tk.Frame(self._inbox_frame, bg=self._bg)
        inbox_header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SM))
        inbox_header.grid_columnconfigure(1, weight=1)

        self._inbox_title = web_label(
            inbox_header, "📥 暂存箱", kind="section", accent="#10B981",
        )
        self._inbox_title.grid(row=0, column=0, sticky="w")

        self._inbox_search = cartoon_entry(
            inbox_header, placeholder="搜索...",
            border_color=self._edge,
        )
        self._inbox_search.grid(row=0, column=1, sticky="ew", padx=SPACING_MD)
        self._inbox_search.entry.bind("<KeyRelease>", self._on_inbox_search)

        CartoonButton(
            inbox_header, "全部收录", command=self._on_ingest_all,
            kind="mint", height=36,
        ).grid(row=0, column=2, sticky="e")

        # scrollable list
        list_frame = tk.Frame(self._inbox_frame, bg=self._edge)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_SM))
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        list_inner = tk.Frame(list_frame, bg=self._bg)
        list_inner.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        list_inner.grid_rowconfigure(0, weight=1)
        list_inner.grid_columnconfigure(0, weight=1)

        self._inbox_canvas = tk.Canvas(
            list_inner, bg=self._bg, highlightthickness=0,
        )
        self._inbox_sb = tk.Scrollbar(
            list_inner, orient="vertical", command=self._inbox_canvas.yview,
        )
        self._inbox_scroll_frame = tk.Frame(self._inbox_canvas, bg=self._bg)

        self._inbox_scroll_frame.bind(
            "<Configure>",
            lambda e: self._inbox_canvas.configure(
                scrollregion=self._inbox_canvas.bbox("all")
            ),
        )
        self._inbox_canvas_window = self._inbox_canvas.create_window(
            (0, 0), window=self._inbox_scroll_frame, anchor="nw",
        )
        self._inbox_canvas.configure(yscrollcommand=self._inbox_sb.set)
        self._inbox_canvas.bind(
            "<Configure>",
            lambda e: self._inbox_canvas.itemconfig(
                self._inbox_canvas_window, width=e.width,
            ),
        )
        self._inbox_canvas.bind("<MouseWheel>", self._on_inbox_mousewheel)
        self._inbox_scroll_frame.bind("<MouseWheel>", self._on_inbox_mousewheel)

        self._inbox_canvas.grid(row=0, column=0, sticky="nsew")
        self._inbox_sb.grid(row=0, column=1, sticky="ns")

        # preview area
        preview_sec = web_section(
            self._inbox_frame, "预览",
            bg_color=self._bg, border_color=self._edge, accent="#10B981",
        )
        preview_sec.grid(row=2, column=0, sticky="nsew")
        preview_sec.content.grid_columnconfigure(0, weight=1)
        preview_sec.content.grid_rowconfigure(0, weight=1)

        self._inbox_preview = cartoon_textarea(
            preview_sec.content, height=6, border_color=self._edge,
        )
        self._inbox_preview.text.config(state=tk.DISABLED)
        self._inbox_preview.grid(row=0, column=0, sticky="nsew")

        self._inbox_all_notes: list[Path] = []
        self._inbox_selected: Path | None = None

        # ── tab bar (toggle between upload / inbox) ───────────────
        tab_row = tk.Frame(self.frame, bg=self._bg)
        tab_row.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SM))
        tab_row.grid_columnconfigure(0, weight=1)
        tab_row.grid_columnconfigure(1, weight=1)

        self._tab_upload_btn = CartoonButton(
            tab_row, "📂 上传文件", command=self._show_upload,
            kind="mint", height=40,
        )
        self._tab_upload_btn.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self._tab_inbox_btn = CartoonButton(
            tab_row, "📥 暂存箱", command=self._show_inbox,
            kind="sky", height=40,
        )
        self._tab_inbox_btn.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # ── status bar ────────────────────────────────────────────
        self.status_label = web_label(self.frame, "选择文件后会自动生成预览", kind="hint")
        self.status_label.config(fg=TEXT_LIGHT)
        self.status_label.grid(row=2, column=0, sticky="w", pady=(SPACING_SM, 0))

        # show default view
        self._show_upload()
        self.frame.after(120, self._refresh_inbox_count)

    # ── view switching ─────────────────────────────────────────────────

    def _show_upload(self) -> None:
        self._view = _VIEW_UPLOAD
        self._inbox_frame.grid_forget()
        self._upload_frame.grid(row=1, column=0, sticky="nsew")

    def _show_inbox(self) -> None:
        self._view = _VIEW_INBOX
        self._upload_frame.grid_forget()
        self._inbox_frame.grid(row=1, column=0, sticky="nsew")
        self._refresh_inbox()

    # ── status ─────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    # ── upload: pick / preview / save ──────────────────────────────────

    def _pick_file(self) -> None:
        path_str = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[
                ("支持的文件", "*.docx *.pdf *.md *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("Markdown",  "*.md"),
                ("Word",      "*.docx"),
                ("PDF",       "*.pdf"),
                ("图片",      "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("所有文件",  "*.*"),
            ],
        )
        if not path_str:
            return
        self._selected = Path(path_str)
        self.file_label.config(text=self._selected.name, fg=TEXT_MAIN)
        self._set_status(f"已选择 {self._selected.name}")
        self._update_preview()

    def _update_preview(self) -> None:
        if not self._selected:
            return
        suffix = self._selected.suffix.lower()
        converter = SUPPORTED.get(suffix)
        if converter is None:
            self._set_upload_preview("不支持的文件类型")
            self._set_status("不支持的文件类型")
            return
        selected = self._selected
        self._set_upload_preview("正在转换预览...")
        self._set_status("正在后台生成预览")

        def worker() -> None:
            try:
                md = converter(selected)
                self._preview_q.put((selected, "ok", md[:500]))
            except OCRUnavailableError as exc:
                self._preview_q.put((selected, "error", str(exc)))
            except Exception as exc:
                self._preview_q.put((selected, "error", f"预览失败: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_preview()

    def _poll_preview(self) -> None:
        if self._preview_polling:
            return
        self._preview_polling = True

        def poll() -> None:
            while True:
                try:
                    selected, status, text = self._preview_q.get_nowait()
                except queue.Empty:
                    self.frame.after(50, poll)
                    return
                if selected == self._selected:
                    self._preview_polling = False
                    self._set_upload_preview(text)
                    if status == "ok":
                        self._set_status("预览已更新" if text else "预览为空")
                    else:
                        self._set_status(text)
                    return

        self.frame.after(50, poll)

    def _set_upload_preview(self, text: str) -> None:
        t = self.preview_border.text
        t.config(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        t.insert(tk.END, text)
        t.config(state=tk.DISABLED)

    def _on_save(self) -> None:
        if self._saving:
            return
        if not self._selected:
            self._set_status("请先选择文件")
            return
        suffix = self._selected.suffix.lower()
        if suffix not in SUPPORTED:
            self._set_status("不支持的文件格式")
            return
        selected = self._selected
        self._saving = True
        self.save_btn.set_text("处理中...")
        self._set_upload_preview("正在转换并保存...")
        self._set_status("正在后台保存")

        def worker() -> None:
            try:
                path = save_supported_upload(selected)
                self._save_q.put((selected, "ok", path, ""))
            except OCRUnavailableError as exc:
                self._save_q.put((selected, "error", None, str(exc)))
            except Exception as exc:
                self._save_q.put((selected, "error", None, f"保存失败: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_save()

    def _poll_save(self) -> None:
        if self._save_polling:
            return
        self._save_polling = True

        def poll() -> None:
            try:
                selected, status, path, msg = self._save_q.get_nowait()
            except queue.Empty:
                self.frame.after(50, poll)
                return
            self._save_polling = False
            self._saving = False
            self.save_btn.set_text("💾 转换并保存")
            if status != "ok" or path is None:
                self._set_status(msg)
                return
            if self._main:
                started = self._main._ingest_with_animation([path])
                if started:
                    self._set_status(f"已保存 {path.name}，正在更新 wiki")
                else:
                    self._set_status(f"已保存 {path.name}，未配置 LLM，wiki 未更新")
            else:
                if _cfg.LLM_API_KEY:
                    background_ingest(path)
                    self._set_status(f"已保存 {path.name}，正在更新 wiki")
                else:
                    self._set_status(f"已保存 {path.name}，未配置 LLM，wiki 未更新")
            if selected == self._selected:
                self._selected = None
                self.file_label.config(text="未选择文件", fg=TEXT_LIGHT)
                self._set_upload_preview("")
            self._refresh_inbox_count()

        self.frame.after(50, poll)

    # ── inbox ──────────────────────────────────────────────────────────

    def _refresh_inbox_count(self) -> None:
        count = len(_find_uningested_notes())
        text = f"📥 暂存箱 ({count})" if count else "📥 暂存箱"
        self._tab_inbox_btn.set_text(text)

    def _refresh_inbox(self) -> None:
        self._inbox_all_notes = _find_uningested_notes()
        self._inbox_selected = None
        self._inbox_title.config(
            text=f"📥 暂存箱 ({len(self._inbox_all_notes)} 条)"
        )
        self._refresh_inbox_count()
        self._set_inbox_preview("")
        self._render_inbox_list()

    def _on_inbox_mousewheel(self, event) -> None:
        self._inbox_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_inbox_search(self, _event=None) -> None:
        self._render_inbox_list()

    def _render_inbox_list(self) -> None:
        for w in self._inbox_scroll_frame.winfo_children():
            w.destroy()

        entry = self._inbox_search.entry
        query = ("" if getattr(entry, "_is_placeholder", False)
                 else entry.get().strip().lower())
        filtered = [
            p for p in self._inbox_all_notes
            if not query or query in p.name.lower()
        ]
        if not filtered:
            msg = "没有匹配的笔记" if query else "暂存箱为空"
            tk.Label(
                self._inbox_scroll_frame, text=msg,
                font=FONT_BODY, bg=self._bg, fg=TEXT_LIGHT,
            ).pack(pady=SPACING_MD)
            return

        for note_path in filtered:
            self._inbox_add_row(note_path)

    def _inbox_add_row(self, note_path: Path) -> None:
        is_sel = (note_path == self._inbox_selected)
        row_bg = "#A7F3D0" if is_sel else WHITE
        row_fg = "#065F46" if is_sel else TEXT_MAIN
        row_font = FONT_BODY_BOLD if is_sel else FONT_BODY

        row = tk.Frame(self._inbox_scroll_frame, bg=row_bg, cursor="hand2")
        row.pack(fill="x", pady=(0, 1))
        row.grid_columnconfigure(1, weight=1)

        if is_sel:
            tk.Frame(row, bg="#10B981", width=3).grid(row=0, column=0, sticky="ns")

        lbl = tk.Label(
            row, text=note_path.name, font=row_font,
            bg=row_bg, fg=row_fg, anchor="w", cursor="hand2",
        )
        lbl.grid(row=0, column=1, sticky="ew", padx=(SPACING_SM, SPACING_SM))

        for w in (row, lbl):
            w.bind("<Button-1>", lambda e, p=note_path: self._on_inbox_select(p))
            w.bind("<MouseWheel>", self._on_inbox_mousewheel)

        CartoonButton(
            row, "收录",
            command=lambda p=note_path: self._on_ingest_one(p),
            kind="mint", height=28,
        ).grid(row=0, column=2, sticky="e", padx=(0, SPACING_SM))

    def _on_inbox_select(self, note_path: Path) -> None:
        self._inbox_selected = note_path
        self._render_inbox_list()
        try:
            content = _read_inbox_preview(note_path)
        except Exception:
            content = "(无法读取文件)"
        self._set_inbox_preview(content)

    def _set_inbox_preview(self, text: str) -> None:
        t = self._inbox_preview.text
        t.config(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        t.insert(tk.END, text)
        t.config(state=tk.DISABLED)

    def _on_ingest_one(self, note_path: Path) -> None:
        if self._main:
            started = self._main._ingest_with_animation([note_path])
            if not started:
                self._set_status(f"已保存 {note_path.name}，未配置 LLM，wiki 未更新")
                return
        else:
            if not _cfg.LLM_API_KEY:
                self._set_status(f"已保存 {note_path.name}，未配置 LLM，wiki 未更新")
                return
            background_ingest(note_path)
        self._set_status(f"正在收录: {note_path.name}")
        self.frame.after(500, self._refresh_inbox)

    def _on_ingest_all(self) -> None:
        notes = list(self._inbox_all_notes)
        if not notes:
            return
        if self._main:
            started = self._main._ingest_with_animation(notes)
            if not started:
                self._set_status(f"已保存 {len(notes)} 条笔记，未配置 LLM，wiki 未更新")
                return
        else:
            if not _cfg.LLM_API_KEY:
                self._set_status(f"已保存 {len(notes)} 条笔记，未配置 LLM，wiki 未更新")
                return
            for p in notes:
                background_ingest(p)
        self._set_status(f"正在收录全部 {len(notes)} 条笔记")
        self.frame.after(500, self._refresh_inbox)
