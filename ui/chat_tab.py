import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path

from llm.client import LLMConfig
from llm.wiki_engine import QueryResultMeta, query_wiki, save_query_answer_as_wiki_page
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SKY_DARK, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_BODY_BOLD, FONT_HINT, SPACING_SM, SPACING_MD, SPACING_LG,
    web_label, web_section, cartoon_entry, CartoonButton,
)
import config as app_config


class ChatTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._queue: queue.Queue[str | None | tuple] = queue.Queue()
        self._streaming = False
        self._last_question = ""
        self._last_answer_chunks: list[str] = []
        self._last_meta: QueryResultMeta | None = None
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self.frame, bg=self._bg)
        header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_LG))
        header.grid_columnconfigure(0, weight=1)
        web_label(header, "向知识库提问", kind="section", accent="#F59E0B").grid(
            row=0, column=0, sticky="w",
        )
        CartoonButton(
            header, "📖", command=self._open_reader,
            kind="orange", width=48, height=34,
        ).grid(row=0, column=1, sticky="e")
        self.save_btn = CartoonButton(
            header, "💾", command=self._save_last_answer,
            kind="orange", width=48, height=34,
        )
        self.save_btn.grid(row=0, column=2, sticky="e", padx=(SPACING_SM, 0))

        hist_section = web_section(
            self.frame, None, bg_color=self._bg,
            border_color=self._edge, accent="#F59E0B",
        )
        hist_section.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_LG))
        hist_inner = hist_section.content
        hist_inner.grid_columnconfigure(0, weight=1)
        hist_inner.grid_rowconfigure(0, weight=1)

        hist_scroll = tk.Scrollbar(hist_inner, orient="vertical")
        self.history = tk.Text(
            hist_inner, wrap=tk.WORD, font=FONT_BODY,
            yscrollcommand=hist_scroll.set, state=tk.DISABLED,
            bg=self._bg, fg=TEXT_MAIN,
            relief="flat", borderwidth=0, highlightthickness=0,
            padx=12, pady=10,
        )
        hist_scroll.config(command=self.history.yview)
        self.history.grid(row=0, column=0, sticky="nsew")
        hist_scroll.grid(row=0, column=1, sticky="ns")

        self.history.tag_config("user_name", foreground=SKY_DARK,
                                font=FONT_BODY_BOLD)
        self.history.tag_config("assistant_name", foreground="#D97706",
                                font=FONT_BODY_BOLD)
        self.history.tag_config("error", foreground="#E11D48",
                                font=FONT_BODY_BOLD)
        self.history.tag_config("meta", foreground=TEXT_LIGHT,
                                font=FONT_HINT)
        self.history.tag_config("thinking", foreground="#8B5CF6",
                                font=FONT_HINT)

        # Input row
        input_row = tk.Frame(self.frame, bg=self._bg)
        input_row.grid(row=2, column=0, sticky="ew", pady=(0, SPACING_MD))
        input_row.grid_columnconfigure(0, weight=1)

        self.q_border = cartoon_entry(
            input_row, placeholder="输入你的问题...",
            border_color=self._edge,
        )
        self.q_border.grid(row=0, column=0, sticky="ew")
        self.q_border.entry.bind("<Return>", lambda _e: self._on_send())

        CartoonButton(
            input_row, "💬", command=self._on_send,
            kind="orange", width=58, height=44,
        ).grid(row=0, column=1, padx=(SPACING_MD, 0), sticky="e")

    def _append_text(self, text: str, tag: str = "") -> None:
        self.history.config(state=tk.NORMAL)
        if tag:
            self.history.insert(tk.END, text, tag)
        else:
            self.history.insert(tk.END, text)
        self.history.config(state=tk.DISABLED)
        self.history.see(tk.END)

    def _on_send(self) -> None:
        if self._streaming:
            return
        entry = self.q_border.entry
        if getattr(entry, "_is_placeholder", False):
            return
        question = entry.get().strip()
        if not question:
            return
        entry.delete(0, tk.END)

        self._append_text("You: ", "user_name")
        self._append_text(question + "\n\n")

        if not app_config.LLM_API_KEY:
            self._append_text(
                "请先设置 LLM_API_KEY 环境变量。\n\n",
                "error",
            )
            return

        self._append_text("Assistant: ", "assistant_name")
        self._streaming = True
        self._last_question = question
        self._last_answer_chunks = []
        self._last_meta = None

        llm_config = LLMConfig(
            api_base=app_config.LLM_API_BASE,
            api_key=app_config.LLM_API_KEY,
            model=app_config.LLM_MODEL,
            thinking=app_config.LLM_THINKING,
        )
        thread = threading.Thread(
            target=self._stream_worker,
            args=(question, llm_config),
            daemon=True,
        )
        thread.start()
        self._poll_queue()

    def _stream_worker(self, question: str, config: LLMConfig) -> None:
        try:
            def _on_meta(meta: QueryResultMeta) -> None:
                self._last_meta = meta

            def _on_thinking(text: str) -> None:
                self._queue.put(("think", text))

            for chunk in query_wiki(
                question, config, on_meta=_on_meta, on_thinking=_on_thinking,
            ):
                self._queue.put(chunk)
        except Exception as exc:
            self._queue.put(f"\n[Error: {exc}]")
        self._queue.put(None)

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    self._append_text("\n\n")
                    self._streaming = False
                    return
                if isinstance(item, tuple) and item[0] == "think":
                    self._append_text(item[1], "thinking")
                else:
                    self._last_answer_chunks.append(item)
                    self._append_text(item)
        except queue.Empty:
            pass
        self.frame.after(50, self._poll_queue)

    def _save_last_answer(self) -> None:
        if self._streaming or not self._last_question or not self._last_answer_chunks:
            return
        meta = self._last_meta
        used_pages = meta.used_pages if meta else []
        raw_sources = meta.raw_sources if meta else []
        answer_type = meta.answer_type if meta else "direct_answer"
        answer = "".join(self._last_answer_chunks).strip()
        try:
            path = save_query_answer_as_wiki_page(
                self._last_question,
                answer,
                used_pages,
                answer_type=answer_type,
                raw_sources=raw_sources,
            )
        except Exception as exc:
            self._append_text(f"[保存失败: {exc}]\n\n", "error")
            return
        self._append_text(f"[已保存到 {path}]\n\n", "meta")

    def _open_reader(self) -> None:
        text = self.history.get("1.0", tk.END).strip()
        if not text:
            return
        md = self._conversation_to_markdown(text)
        tmp = Path(app_config.WIKI_DIR) / "_chat_preview.md"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(md, encoding="utf-8")

        from ui.search_tab import _ReaderWindow
        root = self.frame.nametowidget(".")
        prev = getattr(root, "_active_reader", None)
        if prev is not None and prev.winfo_exists():
            prev.destroy()
        reader = _ReaderWindow(
            root, tmp, query="",
            bg_color=self._bg, edge_color=self._edge,
        )
        root._active_reader = reader.win

    @staticmethod
    def _conversation_to_markdown(raw: str) -> str:
        lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("You: "):
                lines.append(f"### You\n\n{line[5:]}\n")
            elif line.startswith("Assistant: "):
                lines.append(f"### Assistant\n\n{line[11:]}\n")
            else:
                lines.append(line)
        return "\n".join(lines)
