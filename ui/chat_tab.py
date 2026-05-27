import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path

from llm.client import LLMConfig
from llm.wiki_engine import QueryResultMeta, query_wiki, save_query_answer_as_wiki_page
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SKY_DARK, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_HINT,
    cartoon_label, cartoon_entry, CartoonButton,
)
import config as app_config


class ChatTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._streaming = False
        self._last_question = ""
        self._last_answer_chunks: list[str] = []
        self._last_meta: QueryResultMeta | None = None
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self.frame, bg=self._bg)
        header.grid(row=0, column=0, sticky="ew", padx=2, pady=(4, 2))
        header.grid_columnconfigure(0, weight=1)
        cartoon_label(header, "向知识库提问", kind="hint").grid(
            row=0, column=0, sticky="w",
        )
        CartoonButton(
            header, "📖", command=self._open_reader,
            kind="orange", width=44, height=30,
        ).grid(row=0, column=1, sticky="e")
        self.save_btn = CartoonButton(
            header, "💾", command=self._save_last_answer,
            kind="orange", width=44, height=30,
        )
        self.save_btn.grid(row=0, column=2, sticky="e", padx=(4, 0))

        # Chat history
        hist_border = tk.Frame(self.frame, bg=self._edge)
        hist_border.grid(row=1, column=0, sticky="nsew", padx=2)
        hist_inner = tk.Frame(hist_border, bg=self._bg)
        hist_inner.pack(fill="both", expand=True, padx=2, pady=(2, 3))

        hist_scroll = tk.Scrollbar(hist_inner, orient="vertical")
        self.history = tk.Text(
            hist_inner, wrap=tk.WORD, font=FONT_BODY,
            yscrollcommand=hist_scroll.set, state=tk.DISABLED,
            bg=self._bg, fg=TEXT_MAIN,
            relief="flat", borderwidth=0, highlightthickness=0,
            padx=8, pady=6,
        )
        hist_scroll.config(command=self.history.yview)
        self.history.pack(side="left", fill="both", expand=True)
        hist_scroll.pack(side="right", fill="y")

        self.history.tag_config("user_name", foreground=SKY_DARK,
                                font=("幼圆", 10, "bold"))
        self.history.tag_config("assistant_name", foreground="#e88a3a",
                                font=("幼圆", 10, "bold"))
        self.history.tag_config("error", foreground="#cc4444",
                                font=("幼圆", 10, "italic"))
        self.history.tag_config("meta", foreground=TEXT_LIGHT,
                                font=("幼圆", 9))

        # Input row
        input_row = tk.Frame(self.frame, bg=self._bg)
        input_row.grid(row=2, column=0, sticky="ew", padx=2, pady=(6, 4))
        input_row.grid_columnconfigure(0, weight=1)

        self.q_border = cartoon_entry(
            input_row, placeholder="输入你的问题...",
            border_color=self._edge,
        )
        self.q_border.grid(row=0, column=0, sticky="ew")
        self.q_border.entry.bind("<Return>", lambda _e: self._on_send())

        CartoonButton(
            input_row, "💬", command=self._on_send,
            kind="orange", width=52, height=40,
        ).grid(row=0, column=1, padx=(6, 0), sticky="e")

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

            for chunk in query_wiki(question, config, on_meta=_on_meta):
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
