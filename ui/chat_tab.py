import queue
import threading
import tkinter as tk

from llm.client import LLMConfig
from llm.wiki_engine import query_wiki
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
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        cartoon_label(self.frame, "向知识库提问", kind="hint").grid(
            row=0, column=0, sticky="w", padx=2, pady=(4, 2),
        )

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
            for chunk in query_wiki(question, config):
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
                self._append_text(item)
        except queue.Empty:
            pass
        self.frame.after(50, self._poll_queue)
