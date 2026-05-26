import tkinter as tk


def test_lint_tab_creates_frame():
    root = tk.Tk()
    root.withdraw()
    try:
        from ui.lint_tab import LintTab
        tab = LintTab(root, bg_color="#fff0f0", edge_color="#f0c0c0")
        assert isinstance(tab.frame, tk.Frame)
    finally:
        root.destroy()
