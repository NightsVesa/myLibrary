"""Lint panel: one-click wiki health check with streamed results."""

import queue
import threading
import tkinter as tk

from llm.client import LLMConfig
from llm.wiki_lint import LintFinding, lint_wiki
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_BODY_BOLD, FONT_INPUT,
    cartoon_label, CartoonButton,
)

_SEV_EMOJI = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}


class LintTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._q: queue.Queue[LintFinding | None] = queue.Queue()
        self._running = False
        self._build()

    def _build(self) -> None:
        bg = self._bg
        top = tk.Frame(self.frame, bg=bg)
        top.pack(fill="x", padx=8, pady=(8, 4))

        cartoon_label(top, "Wiki 健康检查", kind="title").pack(side="left")

        self._run_btn = CartoonButton(
            top, "🩺 开始检查", command=self._on_run, kind="pink",
        )
        self._run_btn.pack(side="right")

        text_frame = tk.Frame(self.frame, bg=self._edge, bd=0)
        text_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._text = tk.Text(
            text_frame, wrap="word", font=FONT_INPUT,
            bg=bg, fg=TEXT_MAIN, relief="flat",
            state="disabled", padx=10, pady=8,
            spacing1=2, spacing3=2,
        )
        sb = tk.Scrollbar(text_frame, command=self._text.yview)
        self._text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        self._text.tag_config("error", foreground="#d9534f", font=FONT_BODY_BOLD)
        self._text.tag_config("warn", foreground="#f0ad4e", font=FONT_BODY_BOLD)
        self._text.tag_config("info", foreground="#5bc0de", font=FONT_BODY_BOLD)
        self._text.tag_config("loc", foreground="#8e44ad")
        self._text.tag_config("msg", foreground=TEXT_MAIN, font=FONT_BODY)
        self._text.tag_config("sug", foreground=TEXT_LIGHT)
        self._text.tag_config("header", foreground=TEXT_MAIN, font=FONT_BODY_BOLD)

    def _on_run(self) -> None:
        if self._running:
            return
        self._running = True
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", "正在检查...\n\n", "header")
        self._text.config(state="disabled")

        def _worker():
            import config as _cfg
            cfg = LLMConfig(
                api_base=_cfg.LLM_API_BASE,
                api_key=_cfg.LLM_API_KEY,
                model=_cfg.LLM_MODEL,
            )
            try:
                for finding in lint_wiki(_cfg.WIKI_DIR, cfg):
                    self._q.put(finding)
            except Exception:
                pass
            self._q.put(None)

        threading.Thread(target=_worker, daemon=True).start()
        self.frame.after(50, self._poll)

    def _poll(self) -> None:
        batch = 0
        while batch < 20:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                self._finish()
                return
            self._append_finding(item)
            batch += 1
        self.frame.after(50, self._poll)

    def _append_finding(self, f: LintFinding) -> None:
        self._text.config(state="normal")
        emoji = _SEV_EMOJI.get(f.severity, "•")
        self._text.insert("end", f"{emoji} ", f.severity)
        self._text.insert("end", f"[{f.kind}] ", f.severity)
        self._text.insert("end", f"{f.location}", "loc")
        self._text.insert("end", f"\n  {f.message}\n", "msg")
        if f.suggestion:
            self._text.insert("end", f"  → {f.suggestion}\n", "sug")
        self._text.insert("end", "\n")
        self._text.config(state="disabled")
        self._text.see("end")

    def _finish(self) -> None:
        self._text.config(state="normal")
        self._text.insert("end", "✅ 检查完成\n", "header")
        self._text.config(state="disabled")
        self._text.see("end")
        self._running = False
