import tkinter as tk

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, LEFT, X, W
from ttkbootstrap.dialogs import Messagebox

from converter.text_converter import text_to_markdown
from storage.note_store import save_note


class InputTab:
    def __init__(self, parent) -> None:
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self) -> None:
        title_row = ttk.Frame(self.frame)
        title_row.pack(fill=X, padx=10, pady=(10, 4))
        ttk.Label(title_row, text="标题（可选）:").pack(side=LEFT)
        self.title_var = tk.StringVar()
        ttk.Entry(title_row, textvariable=self.title_var, width=28).pack(side=LEFT, padx=6)

        ttk.Label(self.frame, text="粘贴内容:").pack(anchor=W, padx=10)
        self.text_area = tk.Text(self.frame, height=14, wrap=tk.WORD, font=("Consolas", 10))
        self.text_area.pack(fill=BOTH, expand=True, padx=10, pady=4)

        ttk.Button(
            self.frame,
            text="💾 保存到知识库",
            bootstyle="success",
            command=self._on_save,
        ).pack(pady=(4, 10))

    def _on_save(self) -> None:
        content = self.text_area.get("1.0", tk.END).strip()
        if not content:
            Messagebox.show_warning("内容不能为空", parent=self.frame)
            return
        title = self.title_var.get().strip() or None
        md = text_to_markdown(content, title=title)
        path = save_note(md, title=title)
        Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
        self.text_area.delete("1.0", tk.END)
        self.title_var.set("")
