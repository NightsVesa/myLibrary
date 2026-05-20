import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, LEFT, X, W
from ttkbootstrap.dialogs import Messagebox

from converter.docx_converter import docx_to_markdown
from converter.pdf_converter import pdf_to_markdown
from storage.note_store import save_note

SUPPORTED = {".docx": docx_to_markdown, ".pdf": pdf_to_markdown}


class UploadTab:
    def __init__(self, parent) -> None:
        self.frame = ttk.Frame(parent)
        self._selected: Path | None = None
        self._build()

    def _build(self) -> None:
        ttk.Label(self.frame, text="选择 DOCX 或 PDF 文件:").pack(anchor=W, padx=10, pady=(12, 4))

        pick_row = ttk.Frame(self.frame)
        pick_row.pack(fill=X, padx=10)
        self.file_label = ttk.Label(pick_row, text="未选择文件", bootstyle="secondary", width=32)
        self.file_label.pack(side=LEFT)
        ttk.Button(pick_row, text="浏览…", bootstyle="outline", command=self._pick_file).pack(side=LEFT, padx=6)

        ttk.Label(self.frame, text="预览（前500字符）:").pack(anchor=W, padx=10, pady=(10, 2))
        self.preview = tk.Text(
            self.frame, height=10, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 9), bg="#f0f0f0",
        )
        self.preview.pack(fill=BOTH, expand=True, padx=10)

        ttk.Button(
            self.frame,
            text="💾 转换并保存",
            bootstyle="success",
            command=self._on_save,
        ).pack(pady=(8, 10))

    def _pick_file(self) -> None:
        path_str = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[("文档文件", "*.docx *.pdf"), ("所有文件", "*.*")],
        )
        if not path_str:
            return
        self._selected = Path(path_str)
        self.file_label.config(text=self._selected.name)
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
        self.preview.config(state=tk.NORMAL)
        self.preview.delete("1.0", tk.END)
        self.preview.insert(tk.END, text)
        self.preview.config(state=tk.DISABLED)

    def _on_save(self) -> None:
        if not self._selected:
            Messagebox.show_warning("请先选择文件", parent=self.frame)
            return
        suffix = self._selected.suffix.lower()
        converter = SUPPORTED.get(suffix)
        if converter is None:
            Messagebox.show_error("不支持的文件格式", parent=self.frame)
            return
        try:
            md = converter(self._selected)
            title = self._selected.stem
            path = save_note(md, title=title)
            Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
            self._selected = None
            self.file_label.config(text="未选择文件")
            self._set_preview("")
        except Exception as exc:
            Messagebox.show_error(f"转换失败:\n{exc}", parent=self.frame)
