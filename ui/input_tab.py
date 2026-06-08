from __future__ import annotations

import queue
import threading
import tkinter as tk
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageGrab, ImageTk

import config
from converter.ocr_converter import (
    IMAGE_SUFFIXES,
    OCRUnavailableError,
    _blockquote,
    _format_ocr_lines,
    ocr_image,
)
from converter.text_converter import text_to_markdown
from llm.wiki_engine import background_ingest
from storage.note_store import save_note
from ui.cartoon_widgets import (
    WHITE,
    SKY_LIGHT,
    TEXT_LIGHT,
    SPACING_MD,
    SPACING_LG,
    SPACING_SM,
    web_label,
    web_section,
    cartoon_entry,
    cartoon_textarea,
    CartoonButton,
)

MAX_DISPLAY_WIDTH = 400


def _dump_to_markdown_body(
    dump: list[tuple[str, str, str]], image_map: dict[str, Path]
) -> str:
    """Convert tk.Text.dump() output to a Markdown body string.

    Text segments are appended verbatim. Image segments are replaced with
    ``![](.assets/<filename>.png)`` using the saved asset path.
    Unknown images (not in *image_map*) are silently skipped.
    """
    parts: list[str] = []
    for item in dump:
        kind = item[0]
        if kind == "text":
            parts.append(item[1])
        elif kind == "image":
            name = item[1]
            path = image_map.get(name)
            if path is not None:
                parts.append(f"![](.assets/{path.name})")
    body = "".join(parts)
    if body.endswith("\n"):
        body = body[:-1]
    return body


class InputTab:
    def __init__(
        self,
        parent,
        bg_color: str = WHITE,
        edge_color: str = SKY_LIGHT,
        *,
        main=None,
    ) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._main = main

        self._image_map: dict[str, Path] = {}
        self._image_marks: dict[str, str] = {}
        self._photo_refs: list[ImageTk.PhotoImage] = []
        self._ocr_q: queue.Queue[tuple[int, str, str, list[str]]] = queue.Queue()
        self._ocr_polling: str | None = None
        self._ocr_pending: int = 0
        self._editor_generation: int = 0

        self._build()

    # ── build ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        title_section = web_section(
            self.frame,
            "标题",
            bg_color=self._bg,
            border_color=self._edge,
            accent="#7C3AED",
        )
        title_section.grid(
            row=0, column=0, sticky="ew", padx=0, pady=(0, SPACING_LG)
        )
        title_section.content.grid_columnconfigure(0, weight=1)

        self.title_border = cartoon_entry(
            title_section.content,
            placeholder="给笔记起个名字...",
            border_color=self._edge,
        )
        self.title_border.grid(row=0, column=0, sticky="ew")

        content_section = web_section(
            self.frame,
            "粘贴或键入内容",
            bg_color=self._bg,
            border_color=self._edge,
            accent="#7C3AED",
        )
        content_section.grid(
            row=1, column=0, sticky="nsew", padx=0, pady=(0, SPACING_LG)
        )
        content_section.content.grid_columnconfigure(0, weight=1)
        content_section.content.grid_rowconfigure(0, weight=1)

        self.text_border = cartoon_textarea(
            content_section.content,
            height=10,
            border_color=self._edge,
        )
        self.text_border.grid(row=0, column=0, sticky="nsew")
        self.text_border.text.bind("<Control-Return>", self._save_ingest_shortcut)
        self.text_border.text.bind("<Control-KP_Enter>", self._save_ingest_shortcut)
        self.text_border.text.bind("<Control-Shift-Return>", self._save_inbox_shortcut)
        self.text_border.text.bind("<Control-Shift-KP_Enter>", self._save_inbox_shortcut)
        self.text_border.text.bind("<<Paste>>", self._on_paste)
        self.title_border.entry.bind("<Control-Return>", self._save_ingest_shortcut)
        self.title_border.entry.bind("<Control-KP_Enter>", self._save_ingest_shortcut)
        self.title_border.entry.bind("<Control-Shift-Return>", self._save_inbox_shortcut)
        self.title_border.entry.bind("<Control-Shift-KP_Enter>", self._save_inbox_shortcut)

        btn_frame = tk.Frame(self.frame, bg=self._bg)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=(0, SPACING_MD))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        CartoonButton(
            btn_frame,
            "📥 暂存",
            command=self._on_save_inbox,
            kind="mint",
            height=48,
        ).grid(row=0, column=0, sticky="ew", padx=(0, SPACING_SM))

        CartoonButton(
            btn_frame,
            "💾 保存并收录",
            command=self._on_save_with_ingest,
            kind="sky",
            height=48,
        ).grid(row=0, column=1, sticky="ew", padx=(SPACING_SM, 0))

        self.status_label = web_label(
            self.frame,
            "Ctrl+Enter 收录  |  Ctrl+Shift+Enter 暂存",
            kind="hint",
        )
        self.status_label.config(fg=TEXT_LIGHT)
        self.status_label.grid(
            row=3, column=0, sticky="w", pady=(0, SPACING_SM)
        )
        self.frame.after(120, self.text_border.text.focus_set)

    # ── status ─────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    # ── save shortcuts ────────────────────────────────────────────────

    def _save_ingest_shortcut(self, _event) -> str:
        self._on_save(ingest=True)
        return "break"

    def _save_inbox_shortcut(self, _event) -> str:
        self._on_save(ingest=False)
        return "break"

    # ── paste ─────────────────────────────────────────────────────────

    def _on_paste(self, event) -> str | None:
        try:
            clipboard = ImageGrab.grabclipboard()
        except Exception:
            return None

        if isinstance(clipboard, Image.Image):
            self._handle_clipboard_image(clipboard)
            return "break"

        if isinstance(clipboard, (list, tuple)):
            handled = self._handle_clipboard_file_list(clipboard)
            if handled:
                return "break"

        return None

    def _handle_clipboard_file_list(self, file_list: list[str]) -> bool:
        handled = False
        for path_str in file_list:
            if not isinstance(path_str, str):
                continue
            path = Path(path_str)
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                with Image.open(path) as img:
                    img.load()
                    self._handle_clipboard_image(img.copy())
            except Exception:
                continue
            handled = True
        return handled

    def _handle_clipboard_image(self, image: Image.Image) -> None:
        asset_path = self._save_clipboard_image(image)
        try:
            image_name = self._embed_image(image, asset_path)
        except Exception:
            asset_path.unlink(missing_ok=True)
            raise
        self._start_ocr(image_name, image)

    # ── image save ────────────────────────────────────────────────────

    def _save_clipboard_image(self, image: Image.Image) -> Path:
        asset_dir = config.NOTES_DIR / ".assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{uuid.uuid4().hex[:6]}.png"
        path = asset_dir / filename
        image.save(path, "PNG")
        return path

    # ── embed ─────────────────────────────────────────────────────────

    def _embed_image(self, image: Image.Image, asset_path: Path) -> str:
        w, h = image.size
        if w > MAX_DISPLAY_WIDTH:
            ratio = MAX_DISPLAY_WIDTH / w
            display_img = image.resize((MAX_DISPLAY_WIDTH, int(h * ratio)), Image.LANCZOS)
        else:
            display_img = image.copy()

        photo = ImageTk.PhotoImage(display_img)
        self._photo_refs.append(photo)

        text = self.text_border.text
        if text.index("insert") != "1.0":
            text.insert("insert", "\n")

        image_name = text.image_create("insert", image=photo)
        text.insert("insert", "\n")

        mark_name = f"img_mark_{image_name}"
        text.mark_set(mark_name, f"{image_name}+1c")
        text.mark_gravity(mark_name, "right")

        self._image_map[image_name] = asset_path
        self._image_marks[image_name] = mark_name

        return image_name

    # ── OCR ───────────────────────────────────────────────────────────

    def _start_ocr(self, image_name: str, image: Image.Image) -> None:
        gen = self._editor_generation
        self._ocr_pending += 1

        def _worker() -> None:
            try:
                lines = ocr_image(image.copy())
            except OCRUnavailableError:
                self._ocr_q.put((gen, image_name, "unavailable", []))
                return
            except Exception:
                self._ocr_q.put((gen, image_name, "error", []))
                return
            self._ocr_q.put((gen, image_name, "ok", lines))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        if self._ocr_polling is None:
            self._ocr_polling = self.frame.after(50, self._poll_ocr)

    def _poll_ocr(self) -> None:
        try:
            while True:
                gen, image_name, status, lines = self._ocr_q.get_nowait()
                self._ocr_pending -= 1
                if gen != self._editor_generation:
                    continue
                if image_name not in self._image_map:
                    continue
                if status == "ok":
                    self._insert_ocr_result(image_name, lines)
                elif status == "error":
                    self._set_status("OCR 失败，图片仍可保存")
        except queue.Empty:
            pass

        if self._ocr_pending > 0:
            self._ocr_polling = self.frame.after(50, self._poll_ocr)
        else:
            self._ocr_polling = None

    def _insert_ocr_result(self, image_name: str, lines: list[str]) -> None:
        text = self.text_border.text
        mark = self._image_marks.get(image_name)
        if mark is None:
            return
        try:
            pos = text.index(mark)
        except tk.TclError:
            return

        body = _format_ocr_lines(lines)
        if not body:
            return

        ocr_block = f"\n<!-- ocr -->\n{_blockquote(body)}\n<!-- /ocr -->"
        text.insert(pos, ocr_block)
        end_pos = text.index(f"{pos}+{len(ocr_block)}c")
        text.tag_add("generated_ocr", pos, end_pos)

    # ── save ──────────────────────────────────────────────────────────

    def _editor_body_to_markdown(self) -> str:
        text = self.text_border.text
        dump = text.dump("1.0", tk.END, image=True, text=True)
        return _dump_to_markdown_body(dump, self._image_map)

    def _on_save_with_ingest(self) -> None:
        self._on_save(ingest=True)

    def _on_save_inbox(self) -> None:
        self._on_save(ingest=False)

    def _on_save(self, *, ingest: bool) -> None:
        body = self._editor_body_to_markdown()
        has_text = bool(body.strip())
        has_images = bool(self._image_map)
        if not has_text and not has_images:
            self._set_status("先写一点内容，再保存")
            self.text_border.text.focus_set()
            return

        title_entry = self.title_border.entry
        title_raw = (
            ""
            if getattr(title_entry, "_is_placeholder", False)
            else title_entry.get().strip()
        )
        title = title_raw or None
        md = text_to_markdown(body, title=title)
        path = save_note(md, title=title)

        if ingest:
            if self._main:
                started = self._main._ingest_with_animation([path])
                if started:
                    self._set_status(f"已保存 {path.name}，正在更新 wiki")
                else:
                    self._set_status(f"已保存 {path.name}，未配置 LLM，wiki 未更新")
            else:
                if config.LLM_API_KEY:
                    background_ingest(path)
                    self._set_status(f"已保存 {path.name}，正在更新 wiki")
                else:
                    self._set_status(f"已保存 {path.name}，未配置 LLM，wiki 未更新")
        else:
            self._set_status(f"已暂存至 inbox: {path.name}")

        self.text_border.text.delete("1.0", tk.END)
        title_entry.delete(0, tk.END)
        title_entry.event_generate("<FocusOut>")
        self._image_map.clear()
        self._image_marks.clear()
        self._photo_refs.clear()
        self._ocr_pending = 0
        self._editor_generation += 1
        self.text_border.text.focus_set()
