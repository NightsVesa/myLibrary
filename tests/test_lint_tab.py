import tkinter as tk
from pathlib import Path


def test_static_checks_on_real_wiki():
    """Smoke-test lint on the actual wiki on disk (read-only)."""
    import config
    from llm.wiki_lint import static_checks
    findings = static_checks(config.WIKI_DIR)
    assert isinstance(findings, list)
    kinds = {f.kind for f in findings}
    assert len(kinds) > 0


def test_lint_tab_creates_frame():
    try:
        root = tk.Tk()
    except tk.TclError:
        return  # headless — skip
    root.withdraw()
    try:
        from ui.lint_tab import LintTab
        tab = LintTab(root, bg_color="#fff0f0", edge_color="#f0c0c0")
        assert isinstance(tab.frame, tk.Frame)
    finally:
        root.destroy()


def test_fixable_finding_explains_auto_fix_button():
    from llm.wiki_lint import LintFinding
    from ui.lint_tab import _auto_action_text

    finding = LintFinding(
        severity="warn",
        kind="heading_drift",
        location="entities/e.md",
        message="Non-standard heading",
        suggestion="Replace heading",
        fixable=True,
    )

    text = _auto_action_text(finding)

    assert "自动修复" in text
    assert "标准二级标题" in text


def test_non_fixable_finding_explains_manual_reason():
    from llm.wiki_lint import LintFinding
    from ui.lint_tab import _auto_action_text

    finding = LintFinding(
        severity="warn",
        kind="no_sources",
        location="entities/e.md",
        message="No sources",
        suggestion="Add source references",
    )

    text = _auto_action_text(finding)

    assert "大模型修复预览" in text
    assert "确认后再应用" in text


def test_llm_finding_also_offers_preview_apply_flow():
    from llm.wiki_lint import LintFinding
    from ui.lint_tab import _auto_action_text

    finding = LintFinding(
        severity="info",
        kind="gap",
        location="entities/e.md",
        message="Missing detail",
        suggestion="Expand the page",
        source="llm",
    )

    text = _auto_action_text(finding)

    assert "大模型修复预览" in text
    assert "确认后再应用" in text


def test_non_fixable_findings_count_as_auto_actionable():
    from llm.wiki_lint import LintFinding
    from ui.lint_tab import _auto_action_count

    findings = [
        LintFinding(
            severity="warn",
            kind="no_sources",
            location="entities/e.md",
            message="No sources",
            suggestion="Add source references",
        ),
    ]

    assert _auto_action_count(findings) == 1


def test_lint_tab_treats_preview_timeout_as_fix_done():
    source = Path("ui/lint_tab.py").read_text(encoding="utf-8")

    assert "httpx.TimeoutException" in source
    assert "大模型修复预览超时" in source
    assert "llm_error" in source
