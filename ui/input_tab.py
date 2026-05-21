import tkinter as tk

from ttkbootstrap.dialogs import Messagebox

from converter.text_converter import text_to_markdown
from storage.note_store import save_note
from llm.wiki_engine import background_ingest
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, cartoon_label, cartoon_entry, cartoon_textarea, CartoonButton,
)


class InputTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        # Rows: 0 hint, 1 title input, 2 hint, 3 textarea (elastic), 4 save btn
        self.frame.grid_rowconfigure(3, weight=1)

        cartoon_label(self.frame, "标题（可选）", kind="hint").grid(
            row=0, column=0, sticky="w", padx=2, pady=(4, 2),
        )

        self.title_border = cartoon_entry(
            self.frame, placeholder="给笔记起个名字...",
            border_color=self._edge,
        )
        self.title_border.grid(row=1, column=0, sticky="ew", padx=2)

        cartoon_label(self.frame, "粘贴或键入内容", kind="hint").grid(
            row=2, column=0, sticky="w", padx=2, pady=(10, 2),
        )

        self.text_border = cartoon_textarea(
            self.frame, height=8, border_color=self._edge,
        )
        self.text_border.grid(row=3, column=0, sticky="nsew", padx=2)

        CartoonButton(
            self.frame, "💾 保存到知识库", command=self._on_save,
            kind="sky", height=44,
        ).grid(row=4, column=0, sticky="ew", padx=2, pady=(10, 4))

    def _on_save(self) -> None:
        content = self.text_border.text.get("1.0", tk.END).strip()
        if not content:
            Messagebox.show_warning("内容不能为空", parent=self.frame)
            return
        title_entry = self.title_border.entry
        title_raw = "" if getattr(title_entry, "_is_placeholder", False) else title_entry.get().strip()
        title = title_raw or None
        md = text_to_markdown(content, title=title)
        path = save_note(md, title=title)
        background_ingest(path)
        Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
        self.text_border.text.delete("1.0", tk.END)
        title_entry.delete(0, tk.END)
        title_entry.event_generate("<FocusOut>")
