import pytest
from pathlib import Path
from unittest.mock import patch

from llm.client import LLMConfig
from llm.wiki_lint import LintFinding, static_checks, llm_check, lint_wiki


@pytest.fixture
def wiki(tmp_path):
    w = tmp_path / "wiki"
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir(parents=True)
    return w


def test_lint_finding_is_frozen():
    f = LintFinding(severity="warn", kind="orphan", location="entities/x.md",
                     message="No inbound links", suggestion="Add cross-ref")
    assert f.severity == "warn"
    with pytest.raises(AttributeError):
        f.severity = "error"


def test_static_checks_finds_orphan(wiki):
    (wiki / "index.md").write_text(
        "# Wiki Index\n\n## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n"
        "## Concepts\n_(none yet)_\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text(
        "# A\n\nContent.\n", encoding="utf-8")
    (wiki / "entities" / "e.md").write_text(
        "# E\n\nContent.\n", encoding="utf-8")

    findings = static_checks(wiki)
    orphans = [f for f in findings if f.kind == "orphan"]
    assert len(orphans) >= 1
    assert any("entities/e.md" in f.location for f in orphans)


def test_static_checks_finds_broken_related_link(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text(
        "# A\n\n## Related\n\n- [E](entities/e.md)\n- [Ghost](entities/ghost.md)\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text("# E\n", encoding="utf-8")

    findings = static_checks(wiki)
    broken = [f for f in findings if f.kind == "broken_link"]
    assert any("ghost.md" in f.message for f in broken)


def test_static_checks_finds_duplicate_index_entry(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n"
        "- [E](entities/e.md) — first\n"
        "- [E](entities/e.md) — second\n"
        "## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text("# E\n", encoding="utf-8")

    findings = static_checks(wiki)
    dupes = [f for f in findings if f.kind == "duplicate_index"]
    assert len(dupes) >= 1


def test_static_checks_finds_index_disk_drift(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )

    findings = static_checks(wiki)
    drift = [f for f in findings if f.kind == "missing_file"]
    assert any("entities/e.md" in f.location for f in drift)


def test_static_checks_finds_unindexed_file(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n## Concepts\n", encoding="utf-8")
    (wiki / "entities" / "secret.md").write_text("# Secret\n", encoding="utf-8")

    findings = static_checks(wiki)
    unindexed = [f for f in findings if f.kind == "unindexed_file"]
    assert any("secret.md" in f.location for f in unindexed)


def test_static_checks_finds_heading_drift(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text(
        "# E\n\nContent.\n\n**Sources**\n\n- src.md\n",
        encoding="utf-8",
    )
    findings = static_checks(wiki)
    drift = [f for f in findings if f.kind == "heading_drift"]
    assert any("**Sources**" in f.message for f in drift)


def test_static_checks_finds_empty_link(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [Empty]()\n## Concepts\n",
        encoding="utf-8",
    )
    findings = static_checks(wiki)
    empty = [f for f in findings if f.kind == "empty_link"]
    assert len(empty) >= 1


def test_static_checks_finds_stray_file(wiki):
    (wiki / "index.md").write_text("## Sources\n## Entities\n## Concepts\n",
                                    encoding="utf-8")
    (wiki / "_chat_preview.md").write_text("temp", encoding="utf-8")

    findings = static_checks(wiki)
    stray = [f for f in findings if f.kind == "stray_file"]
    assert any("_chat_preview" in f.location for f in stray)


# --- LLM check -----------------------------------------------------------

@pytest.fixture
def config():
    return LLMConfig(api_base="https://fake/v1", api_key="k", model="m")


def test_llm_check_returns_findings(wiki, config):
    (wiki / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text("# A\n", encoding="utf-8")
    (wiki / "entities" / "e.md").write_text("# E\n", encoding="utf-8")

    llm_response = (
        "1. WARN gap entities/e.md | Page 'E' is very short | "
        "Add a description based on source A"
    )
    with patch("llm.wiki_lint.chat", return_value=llm_response):
        findings = list(llm_check(wiki, config))

    assert len(findings) >= 1
    assert findings[0].kind == "gap"


def test_llm_check_skipped_without_api_key(wiki):
    no_key = LLMConfig(api_base="https://fake/v1", api_key="", model="m")
    findings = list(llm_check(wiki, no_key))
    assert len(findings) == 0


def test_lint_wiki_combines_static_and_llm(wiki, config):
    (wiki / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text("# A\n", encoding="utf-8")

    with patch("llm.wiki_lint.chat", return_value="1. INFO gap index.md | Wiki is small | Add more sources"):
        findings = list(lint_wiki(wiki, config))

    kinds = {f.kind for f in findings}
    assert "gap" in kinds or "orphan" in kinds


def test_lint_wiki_appends_log(wiki, config):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n## Concepts\n", encoding="utf-8")
    with patch("llm.wiki_lint.chat", return_value="NO_ISSUES"):
        list(lint_wiki(wiki, config))
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert "lint" in log
    assert "Health check" in log
