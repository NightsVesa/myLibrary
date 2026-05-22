import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from ttkbootstrap.dialogs import Messagebox

from converter.docx_converter import docx_to_markdown
from converter.pdf_converter import pdf_to_markdown
from storage.note_store import save_raw_file
from llm.wiki_engine import background_ingest
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SKY_PALE, TEXT_LIGHT, TEXT_MAIN,
    FONT_BODY,
    cartoon_label, cartoon_textarea, CartoonButton,
)


def _md_passthrough(path: Path) -> str:
    """`.md` files are already Markdown — read and store as-is."""
    return Path(path).read_text(encoding="utf-8")


SUPPORTED = {
    ".docx": docx_to_markdown,
    ".pdf":  pdf_to_markdown,
    ".md":   _md_passthrough,
}


class UploadTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT, *, main=None) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._main = main
        self._selected: Path | None = None
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        # 0 hint, 1 picker row, 2 hint, 3 preview (elastic), 4 save btn
        self.frame.grid_rowconfigure(3, weight=1)

        cartoon_label(self.frame, "选择 DOCX 或 PDF 文件", kind="hint").grid(
            row=0, column=0, sticky="w", padx=2, pady=(4, 2),
        )

        pick_row = tk.Frame(self.frame, bg=self._bg)
        pick_row.grid(row=1, column=0, sticky="ew", padx=2)
        pick_row.grid_columnconfigure(0, weight=1)
        pick_row.grid_columnconfigure(1, weight=0, minsize=58)

        # Filename display (same border style as cartoon_entry but disabled)
        self._file_holder = tk.Frame(pick_row, bg=self._edge)
        self._file_holder.grid(row=0, column=0, sticky="ew")
        self._file_inner = tk.Frame(self._file_holder, bg=self._bg)
        self._file_inner.pack(fill="both", expand=True, padx=2, pady=(2, 3))
        self.file_label = tk.Label(
            self._file_inner, text="未选择文件",
            font=FONT_BODY, fg=TEXT_LIGHT, bg=self._bg, anchor="w",
        )
        self.file_label.pack(fill="both", expand=True, padx=8, pady=6)

        CartoonButton(
            pick_row, "📂", command=self._pick_file,
            kind="mint", width=52, height=40,
        ).grid(row=0, column=1, padx=(6, 0), sticky="e")

        cartoon_label(self.frame, "预览（前 500 字符）", kind="hint").grid(
            row=2, column=0, sticky="w", padx=2, pady=(10, 2),
        )

        self.preview_border = cartoon_textarea(
            self.frame, height=6, border_color=self._edge,
        )
        self.preview_border.text.config(state=tk.DISABLED)
        self.preview_border.grid(row=3, column=0, sticky="nsew", padx=2)

        CartoonButton(
            self.frame, "💾 转换并保存", command=self._on_save,
            kind="sky", height=44,
        ).grid(row=4, column=0, sticky="ew", padx=2, pady=(10, 4))

    def _pick_file(self) -> None:
        path_str = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[
                ("支持的文档", "*.docx *.pdf *.md"),
                ("Markdown",  "*.md"),
                ("Word",      "*.docx"),
                ("PDF",       "*.pdf"),
                ("所有文件",  "*.*"),
            ],
        )
        if not path_str:
            return
        self._selected = Path(path_str)
        self.file_label.config(text=self._selected.name, fg=TEXT_MAIN)
        self._update_preview()

    def _update_preview(self) -> None:
        if not self._selected:
            return
        suffix = self._selected.suffix.lower()
        converter = SUPPORTED.get(suffix)
        if converter is None:
            self._set_preview("不支持的文件类型")
            return
        try:
            md = converter(self._selected)
            self._set_preview(md[:500])
        except Exception as exc:
            self._set_preview(f"预览失败: {exc}")

    def _set_preview(self, text: str) -> None:
        t = self.preview_border.text
        t.config(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        t.insert(tk.END, text)
        t.config(state=tk.DISABLED)

    def _on_save(self) -> None:
        if not self._selected:
            Messagebox.show_warning("请先选择文件", parent=self.frame)
            return
        suffix = self._selected.suffix.lower()
        if suffix not in SUPPORTED:
            Messagebox.show_error("不支持的文件格式", parent=self.frame)
            return
        try:
            path = save_raw_file(self._selected)
            if self._main:
                self._main._ingest_with_animation([path])
            else:
                background_ingest(path)
            Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
            self._selected = None
            self.file_label.config(text="未选择文件", fg=TEXT_LIGHT)
            self._set_preview("")
        except Exception as exc:
            Messagebox.show_error(f"保存失败:\n{exc}", parent=self.frame)
