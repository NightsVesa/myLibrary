import pytest
from pathlib import Path
from unittest.mock import patch

from llm.client import LLMConfig
from llm.wiki_lint import LintFinding, static_checks


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
