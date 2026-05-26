import tkinter as tk
from pathlib import Path


# LintTab requires a running tk root, so we test the lint engine directly;
# the UI test is conditional on having a display.


def test_static_checks_on_real_wiki():
    """Smoke-test lint on the actual wiki on disk (read-only)."""
    import config
    from llm.wiki_lint import static_checks
    findings = static_checks(config.WIKI_DIR)
    assert isinstance(findings, list)
    # The real wiki has content — there should be at least one finding.
    kinds = {f.kind for f in findings}
    assert len(kinds) > 0


def test_lint_tab_creates_frame():
    root = tk.Tk()
    root.withdraw()
    try:
        from ui.lint_tab import LintTab
        tab = LintTab(root, bg_color="#fff0f0", edge_color="#f0c0c0")
        assert isinstance(tab.frame, tk.Frame)
    finally:
        root.destroy()
