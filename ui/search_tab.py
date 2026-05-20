import tkinter as tk

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, VERTICAL, X, Y, W

from search.grep_search import search_notes


class SearchTab:
    def __init__(self, parent) -> None:
        self.frame = ttk.Frame(parent)
        self._results: list[dict] = []
        self._build()

    def _build(self) -> None:
        search_row = ttk.Frame(self.frame)
        search_row.pack(fill=X, padx=10, pady=(12, 6))
        self.query_var = tk.StringVar()
        entry = ttk.Entry(search_row, textvariable=self.query_var, font=("Microsoft YaHei", 11))
        entry.pack(side=LEFT, fill=X, expand=True)
        entry.bind("<Return>", lambda _: self._on_search())
        ttk.Button(search_row, text="🔍", bootstyle="primary", command=self._on_search).pack(side=LEFT, padx=4)

        ttk.Label(self.frame, text="搜索结果:").pack(anchor=W, padx=10)
        list_frame = ttk.Frame(self.frame)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=4)
        scrollbar = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.results_list = tk.Listbox(
            list_frame, yscrollcommand=scrollbar.set,
            font=("Consolas", 9), selectmode=tk.SINGLE,
        )
        scrollbar.config(command=self.results_list.yview)
        self.results_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        ttk.Label(self.frame, text="片段预览:").pack(anchor=W, padx=10)
        self.snippet_text = tk.Text(
            self.frame, height=5, wrap=tk.WORD,
            state=tk.DISABLED, font=("Consolas", 9),
        )
        self.snippet_text.pack(fill=X, padx=10, pady=(2, 10))

        self.results_list.bind("<<ListboxSelect>>", self._on_select)

    def _on_search(self) -> None:
        query = self.query_var.get().strip()
        if not query:
            return
        self._results = search_notes(query)
        self.results_list.delete(0, tk.END)
        for r in self._results:
            self.results_list.insert(tk.END, r["file"].name)
        if not self._results:
            self.results_list.insert(tk.END, "（无匹配结果）")

    def _on_select(self, _event) -> None:
        sel = self.results_list.curselection()
        if not sel or not self._results:
            return
        idx = sel[0]
        if idx >= len(self._results):
            return
        snippet = self._results[idx]["snippet"]
        self.snippet_text.config(state=tk.NORMAL)
        self.snippet_text.delete("1.0", tk.END)
        self.snippet_text.insert(tk.END, snippet)
        self.snippet_text.config(state=tk.DISABLED)
