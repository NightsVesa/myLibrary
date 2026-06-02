import tkinter as tk

from ttkbootstrap.dialogs import Messagebox

from converter.text_converter import text_to_markdown
from storage.note_store import save_note
from llm.wiki_engine import background_ingest
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SPACING_MD, SPACING_LG, web_section,
    cartoon_entry, cartoon_textarea, CartoonButton,
)


class InputTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT, *, main=None) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._main = main
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        title_section = web_section(
            self.frame, "标题", bg_color=self._bg,
            border_color=self._edge, accent="#7C3AED",
        )
        title_section.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, SPACING_LG))
        title_section.content.grid_columnconfigure(0, weight=1)

        self.title_border = cartoon_entry(
            title_section.content, placeholder="给笔记起个名字...",
            border_color=self._edge,
        )
        self.title_border.grid(row=0, column=0, sticky="ew")

        content_section = web_section(
            self.frame, "粘贴或键入内容", bg_color=self._bg,
            border_color=self._edge, accent="#7C3AED",
        )
        content_section.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, SPACING_LG))
        content_section.content.grid_columnconfigure(0, weight=1)
        content_section.content.grid_rowconfigure(0, weight=1)

        self.text_border = cartoon_textarea(
            content_section.content, height=10, border_color=self._edge,
        )
        self.text_border.grid(row=0, column=0, sticky="nsew")

        CartoonButton(
            self.frame, "💾 保存到知识库", command=self._on_save,
            kind="sky", height=48,
        ).grid(row=2, column=0, sticky="ew", padx=0, pady=(0, SPACING_MD))

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
        if self._main:
            self._main._ingest_with_animation([path])
        else:
            background_ingest(path)
        Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
        self.text_border.text.delete("1.0", tk.END)
        title_entry.delete(0, tk.END)
        title_entry.event_generate("<FocusOut>")
