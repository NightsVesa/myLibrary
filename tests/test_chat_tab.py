import tkinter as tk

import pytest

from llm.wiki_engine import QueryResultMeta
from ui.chat_tab import ChatTab


def _make_tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    return root


def test_source_chip_tags_are_unique_per_answer():
    root = _make_tk_root()
    if root is None:
        pytest.skip("headless — no tkinter display")
    try:
        tab = ChatTab(root)
        tab._last_meta = QueryResultMeta(
            question="q1",
            answer_type="direct_answer",
            used_pages=[],
            raw_sources=["first.md"],
            suggested_save_title="q1",
        )
        tab._render_source_chips()

        tab._last_meta = QueryResultMeta(
            question="q2",
            answer_type="direct_answer",
            used_pages=[],
            raw_sources=["second.md"],
            suggested_save_title="q2",
        )
        tab._render_source_chips()

        tags = set(tab.history.tag_names())
        assert "src_1_0" in tags
        assert "src_2_0" in tags
    finally:
        root.destroy()
