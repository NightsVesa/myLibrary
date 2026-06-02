import pytest
from pathlib import Path
from unittest.mock import patch

from llm.client import LLMConfig
from llm.wiki_lint import (
    LintFinding, static_checks, llm_check, lint_wiki,
    save_lint_report, auto_fix, _finding, _PRIORITY_MAP, _parse_llm_lint,
)


@pytest.fixture
def wiki(tmp_path):
    w = tmp_path / "wiki"
    for d in ("sources", "entities", "concepts"):
        (w / d).mkdir(parents=True)
    return w


@pytest.fixture
def config():
    return LLMConfig(api_base="https://fake/v1", api_key="k", model="m")


# ── 1. LintFinding backwards compat ──────────────────────────────────────

def test_lint_finding_is_frozen():
    f = LintFinding(severity="warn", kind="orphan", location="entities/x.md",
                     message="No inbound links", suggestion="Add cross-ref")
    assert f.severity == "warn"
    with pytest.raises(AttributeError):
        f.severity = "error"


def test_lint_finding_old_5_arg_construction():
    f = LintFinding("warn", "orphan", "entities/x.md", "msg", "sug")
    assert f.priority == "P2"
    assert f.fixable is False
    assert f.source == "static"


def test_lint_finding_new_fields():
    f = LintFinding("error", "broken_link", "e/x.md", "m", "s",
                     priority="P0", fixable=True, source="llm")
    assert f.priority == "P0"
    assert f.fixable is True
    assert f.source == "llm"


# ── 2. Priority mapping ──────────────────────────────────────────────────

def test_priority_map_p0_kinds():
    for kind in ("missing_index", "missing_dir", "missing_file",
                 "broken_link", "empty_link", "missing_index_section"):
        assert _PRIORITY_MAP[kind] == "P0"


def test_priority_map_p1_kinds():
    for kind in ("duplicate_concept", "no_sources", "temporal_claim",
                 "duplicate_index", "heading_drift", "one_way_related",
                 "contradiction"):
        assert _PRIORITY_MAP[kind] == "P1"


def test_priority_map_unknown_defaults_p2():
    f = _finding("info", "some_unknown_kind", "x.md", "msg", "sug")
    assert f.priority == "P2"


def test_finding_helper_llm_never_p0():
    f = _finding("error", "missing_index", "index.md", "m", "s", source="llm")
    assert f.priority == "P1"


# ── 3. save_lint_report ──────────────────────────────────────────────────

def test_save_lint_report_creates_file(wiki):
    (wiki / "index.md").write_text("## Sources\n## Entities\n## Concepts\n",
                                    encoding="utf-8")
    findings = [
        _finding("error", "broken_link", "entities/x.md", "broken", "fix"),
        _finding("info", "orphan", "entities/y.md", "orphan", "link"),
    ]
    path = save_lint_report(wiki, findings)
    assert path.exists()
    assert path.name.startswith("wiki-lint-")
    text = path.read_text(encoding="utf-8")
    assert "## P0: 需要立刻处理" in text
    assert "broken_link" in text
    assert "## 建议修复顺序" in text


def test_save_lint_report_overwrites_same_day(wiki):
    (wiki / "index.md").write_text("## Sources\n## Entities\n## Concepts\n",
                                    encoding="utf-8")
    findings1 = [_finding("error", "broken_link", "x.md", "first", "fix")]
    findings2 = [_finding("warn", "orphan", "y.md", "second", "link")]
    path1 = save_lint_report(wiki, findings1)
    path2 = save_lint_report(wiki, findings2)
    assert path1 == path2
    text = path2.read_text(encoding="utf-8")
    assert "second" in text
    assert "first" not in text


def test_lint_report_not_flagged_by_index_disk_drift(wiki):
    (wiki / "index.md").write_text("## Sources\n## Entities\n## Concepts\n",
                                    encoding="utf-8")
    (wiki / "synthesis").mkdir(exist_ok=True)
    (wiki / "synthesis" / "wiki-lint-2026-01-01.md").write_text("# Report\n",
                                                                 encoding="utf-8")
    findings = static_checks(wiki)
    unindexed = [f for f in findings if f.kind == "unindexed_file"
                 and "wiki-lint" in f.location]
    assert len(unindexed) == 0


# ── 4. lint_wiki no longer writes log ────────────────────────────────────

def test_lint_wiki_does_not_write_log(wiki, config):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n## Concepts\n", encoding="utf-8")
    with patch("llm.wiki_lint.chat", return_value="NO_ISSUES"):
        list(lint_wiki(wiki, config))
    assert not (wiki / "log.md").exists()


# ── 5. duplicate_concept ─────────────────────────────────────────────────

def test_duplicate_concept_same_dir_slug_collision(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n"
        "- [强化学习](entities/强化学习.md) — rl\n"
        "- [强化-学习](entities/强化-学习.md) — rl2\n"
        "## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "强化学习.md").write_text("# 强化学习\n", encoding="utf-8")
    (wiki / "entities" / "强化-学习.md").write_text("# 强化-学习\n", encoding="utf-8")
    findings = static_checks(wiki)
    dupes = [f for f in findings if f.kind == "duplicate_concept" and f.severity == "warn"]
    assert len(dupes) >= 1


def test_duplicate_concept_cross_dir_info(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [AI](entities/ai.md) — ai\n"
        "## Concepts\n- [AI](concepts/ai.md) — ai concept\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "ai.md").write_text("# AI\n", encoding="utf-8")
    (wiki / "concepts" / "ai.md").write_text("# AI\n", encoding="utf-8")
    findings = static_checks(wiki)
    cross = [f for f in findings if f.kind == "duplicate_concept"
             and f.severity == "info" and "边界不清" in f.message]
    assert len(cross) >= 1


# ── 6. source_coverage ───────────────────────────────────────────────────

def test_source_coverage_warns_no_sources(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text("# E\n\nContent without sources.\n",
                                             encoding="utf-8")
    findings = static_checks(wiki)
    no_src = [f for f in findings if f.kind == "no_sources"]
    assert len(no_src) >= 1
    assert no_src[0].severity == "warn"
    assert no_src[0].priority == "P1"


def test_source_coverage_passes_with_sources(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text(
        "# E\n\nContent.\n\n## Sources\n\n- [[sources/summary_a.md]]\n",
        encoding="utf-8",
    )
    findings = static_checks(wiki)
    no_src = [f for f in findings if f.kind == "no_sources"
              and f.location == "entities/e.md"]
    assert len(no_src) == 0


# ── 7. frontmatter ───────────────────────────────────────────────────────

def test_frontmatter_missing(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text("# E\n\nNo frontmatter.\n",
                                             encoding="utf-8")
    findings = static_checks(wiki)
    missing = [f for f in findings if f.kind == "missing_frontmatter"]
    assert len(missing) >= 1
    assert missing[0].priority == "P2"


def test_frontmatter_type_mismatch(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n## Concepts\n- [C](concepts/c.md) — c\n",
        encoding="utf-8",
    )
    (wiki / "concepts" / "c.md").write_text(
        "---\ntype: entity\ncreated: 2026-01-01\n---\n\n# C\n",
        encoding="utf-8",
    )
    findings = static_checks(wiki)
    mismatch = [f for f in findings if f.kind == "frontmatter_type_mismatch"]
    assert len(mismatch) >= 1
    assert mismatch[0].severity == "warn"
    assert mismatch[0].priority == "P1"


# ── 8. uningested_notes ─────────────────────────────────────────────────

def test_uningested_notes_detected(wiki, tmp_path):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n## Concepts\n", encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "my_note.md").write_text("# My Note\n", encoding="utf-8")
    with patch("llm.wiki_lint.app_config") as mock_cfg:
        mock_cfg.NOTES_DIR = notes
        mock_cfg.WIKI_LINT_STALE_DAYS = 90
        mock_cfg.WIKI_LINT_MAX_CHARS = 16000
        findings = static_checks(wiki)
    uningested = [f for f in findings if f.kind == "uningested_note"]
    assert len(uningested) >= 1
    assert uningested[0].priority == "P2"


# ── 9. temporal_claims ───────────────────────────────────────────────────

def test_temporal_claims_with_old_frontmatter(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text(
        "---\ntype: entity\nupdated: 2020-01-01\n---\n\n# E\n\n目前这是最新的。\n",
        encoding="utf-8",
    )
    with patch("llm.wiki_lint.app_config") as mock_cfg:
        mock_cfg.NOTES_DIR = Path("/nonexistent")
        mock_cfg.WIKI_LINT_STALE_DAYS = 90
        mock_cfg.WIKI_LINT_MAX_CHARS = 16000
        findings = static_checks(wiki)
    temporal = [f for f in findings if f.kind == "temporal_claim"
                and f.severity == "warn"]
    assert len(temporal) >= 1
    assert temporal[0].priority == "P1"


def test_temporal_claims_no_date_is_info(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "e.md").write_text(
        "# E\n\n目前这是最新的。\n", encoding="utf-8",
    )
    with patch("llm.wiki_lint.app_config") as mock_cfg:
        mock_cfg.NOTES_DIR = Path("/nonexistent")
        mock_cfg.WIKI_LINT_STALE_DAYS = 90
        mock_cfg.WIKI_LINT_MAX_CHARS = 16000
        # Make mtime very old so it would be warn if date resolved
        import os, time
        old_time = time.time() - 200 * 86400
        os.utime(wiki / "entities" / "e.md", (old_time, old_time))
        findings = static_checks(wiki)
    temporal = [f for f in findings if f.kind == "temporal_claim"]
    assert len(temporal) >= 1
    # mtime is resolved, so this should be warn (mtime is old)
    assert temporal[0].severity == "warn"


# ── 10. missing_cross_refs ───────────────────────────────────────────────

def test_missing_cross_refs_detected(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n"
        "- [OpenAI](entities/openai.md) — ai company\n"
        "- [GPT](entities/gpt.md) — model\n"
        "## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "openai.md").write_text(
        "---\ntype: entity\n---\n\n# OpenAI\n\nOpenAI created GPT models.\n\n"
        "## Sources\n\n- [[sources/summary_a.md]]\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "gpt.md").write_text(
        "---\ntype: entity\n---\n\n# GPT\n\nA language model.\n\n"
        "## Sources\n\n- [[sources/summary_a.md]]\n",
        encoding="utf-8",
    )
    findings = static_checks(wiki)
    xrefs = [f for f in findings if f.kind == "missing_xref"
             and f.location == "entities/openai.md"]
    assert len(xrefs) >= 1
    assert "GPT" in xrefs[0].message


def test_missing_cross_refs_skips_linked(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n"
        "- [OpenAI](entities/openai.md) — ai\n"
        "- [GPT](entities/gpt.md) — model\n"
        "## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "openai.md").write_text(
        "# OpenAI\n\nOpenAI created [GPT](gpt.md) models.\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "gpt.md").write_text("# GPT\n\nA model.\n",
                                               encoding="utf-8")
    findings = static_checks(wiki)
    xrefs = [f for f in findings if f.kind == "missing_xref"
             and f.location == "entities/openai.md"
             and "GPT" in f.message]
    assert len(xrefs) == 0


def test_missing_cross_refs_skips_short_titles(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n"
        "- [AI](entities/ai.md) — ai\n"
        "- [OpenAI](entities/openai.md) — company\n"
        "## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "ai.md").write_text("# AI\n\nAI stuff.\n",
                                              encoding="utf-8")
    (wiki / "entities" / "openai.md").write_text(
        "# OpenAI\n\nAn AI company.\n", encoding="utf-8")
    findings = static_checks(wiki)
    xrefs = [f for f in findings if f.kind == "missing_xref"
             and "AI" == f.message.split("'")[1]]
    assert len(xrefs) == 0


# ── 11. LLM parser ──────────────────────────────────────────────────────

def test_llm_parser_two_section_format():
    raw = (
        "ISSUES:\n"
        "1. WARN duplicate entities/a.md | Semantic duplicate of b.md | Merge into one\n"
        "2. INFO gap index.md | Missing topic X | Add a page\n"
        "\n"
        "SUGGESTIONS:\n"
        "1. INFO next_source wiki | Search for topic Y | Try Google Scholar\n"
        "2. INFO investigation wiki | Explore Z | Ask the question\n"
    )
    findings = _parse_llm_lint(raw)
    assert len(findings) == 4
    issues = [f for f in findings if f.kind in ("duplicate", "gap")]
    suggestions = [f for f in findings if f.kind in ("next_source", "investigation")]
    assert len(issues) == 2
    assert len(suggestions) == 2
    for s in suggestions:
        assert s.priority == "P2"
    for f in findings:
        assert f.source == "llm"


def test_llm_parser_old_single_section_format():
    raw = "1. WARN gap entities/x.md | Missing info | Add source\n"
    findings = _parse_llm_lint(raw)
    assert len(findings) == 1
    assert findings[0].source == "llm"
    assert findings[0].kind == "gap"


def test_llm_parser_never_p0():
    raw = "1. ERROR missing_index index.md | Index is gone | Rebuild\n"
    findings = _parse_llm_lint(raw)
    assert len(findings) == 1
    assert findings[0].priority != "P0"


def test_llm_check_returns_findings(wiki, config):
    (wiki / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text("# A\n", encoding="utf-8")
    (wiki / "entities" / "e.md").write_text("# E\n", encoding="utf-8")
    llm_response = (
        "ISSUES:\n"
        "1. WARN gap entities/e.md | Page 'E' is very short | "
        "Add a description based on source A\n"
    )
    with patch("llm.wiki_lint.chat", return_value=llm_response):
        findings = list(llm_check(wiki, config))
    assert len(findings) >= 1
    assert findings[0].kind == "gap"


def test_llm_check_skipped_without_api_key(wiki):
    no_key = LLMConfig(api_base="https://fake/v1", api_key="", model="m")
    findings = list(llm_check(wiki, no_key))
    assert len(findings) == 0


# ── 12. auto_fix ─────────────────────────────────────────────────────────

def test_auto_fix_heading_drift(wiki):
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
    assert len(drift) >= 1
    assert drift[0].fixable is True

    fixed = auto_fix(wiki, findings)
    assert fixed >= 1
    text = (wiki / "entities" / "e.md").read_text(encoding="utf-8")
    assert "## Sources" in text
    assert "**Sources**" not in text


def test_auto_fix_standalone_empty_link(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n## Entities\n- [Empty]()\n## Concepts\n",
        encoding="utf-8",
    )
    findings = static_checks(wiki)
    empty = [f for f in findings if f.kind == "empty_link"]
    assert len(empty) >= 1
    fixable = [f for f in empty if f.fixable]
    assert len(fixable) >= 1

    fixed = auto_fix(wiki, findings)
    assert fixed >= 1


def test_auto_fix_does_not_touch_llm_findings(wiki):
    llm_finding = LintFinding(
        severity="warn", kind="heading_drift", location="entities/e.md",
        message="drift", suggestion="fix", fixable=True, source="llm",
    )
    fixed = auto_fix(wiki, [llm_finding])
    assert fixed == 0


# ── Preserved legacy tests ───────────────────────────────────────────────

def test_static_checks_finds_orphan(wiki):
    (wiki / "index.md").write_text(
        "# Wiki Index\n\n## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n"
        "## Concepts\n_(none yet)_\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text("# A\nContent.\n",
                                                    encoding="utf-8")
    (wiki / "entities" / "e.md").write_text("# E\nContent.\n", encoding="utf-8")
    findings = static_checks(wiki)
    orphans = [f for f in findings if f.kind == "orphan"]
    assert len(orphans) >= 1


def test_static_checks_finds_broken_related_link(wiki):
    (wiki / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n- [E](entities/e.md) — e\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text(
        "# A\n\n## Related\n\n- [E](../entities/e.md)\n- [Ghost](../entities/ghost.md)\n",
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


def test_static_checks_finds_missing_scaffold(tmp_path):
    w = tmp_path / "wiki"
    w.mkdir()
    findings = static_checks(w)
    kinds = {f.kind for f in findings}
    assert "missing_index" in kinds
    assert "missing_dir" in kinds


def test_lint_wiki_combines_static_and_llm(wiki, config):
    (wiki / "index.md").write_text(
        "## Sources\n- [A](sources/summary_a.md) — a\n"
        "## Entities\n## Concepts\n",
        encoding="utf-8",
    )
    (wiki / "sources" / "summary_a.md").write_text("# A\n", encoding="utf-8")
    with patch("llm.wiki_lint.chat",
               return_value="ISSUES:\n1. INFO gap index.md | Wiki is small | Add more sources"):
        findings = list(lint_wiki(wiki, config))
    kinds = {f.kind for f in findings}
    assert "gap" in kinds or "orphan" in kinds
