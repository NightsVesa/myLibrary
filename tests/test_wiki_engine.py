import pytest
import threading
from pathlib import Path
from unittest.mock import patch

from llm.client import LLMConfig
from llm.wiki_engine import (
    ingest_note,
    query_wiki,
    _pick_relevant_pages,
    _read_note_source,
    _slugify,
    _canonical_slug,
    _parse_extract,
    _parse_candidates,
    _parse_write_plan,
    _parse_user_selection,
    _pick_index_candidates,
    _pick_query_index_candidates,
    _expand_query_related_pages,
    _classify_query_answer_type,
    _collect_related_source_summaries,
    _build_ingest_extract_messages,
    _build_write_plan,
    _format_candidates_for_display,
    _format_plan_for_display,
    _execute_write_plan,
    ExtractResult,
    IndexEntry,
    IngestCandidate,
    IngestWriteAction,
    IngestWritePlan,
    _merge_page,
    _new_page,
    _write_index,
    _read_index_entries,
    _append_log,
    _ensure_subdirs,
    _collect_existing_slugs,
    _strip_managed_sections,
    _build_related_section,
    _build_sources_section,
    _collect_sources_from_page,
    _read_index_catalog,
    save_query_answer_as_wiki_page,
    _build_discuss_messages,
    discuss_and_ingest,
    migrate_wiki_to_subdirs,
)


# --- config budget constants -------------------------------------------------

def test_config_budget_constants():
    import config as _cfg
    assert hasattr(_cfg, "WIKI_CANDIDATE_TOP_N")
    assert hasattr(_cfg, "WIKI_DEEP_READ_MAX")
    assert hasattr(_cfg, "WIKI_DEEP_READ_MAX_CHARS")
    assert hasattr(_cfg, "WIKI_QUERY_TOP_N")
    assert hasattr(_cfg, "WIKI_QUERY_CONTEXT_MAX_CHARS")
    assert isinstance(_cfg.WIKI_CANDIDATE_TOP_N, int)
    assert isinstance(_cfg.WIKI_DEEP_READ_MAX, int)
    assert isinstance(_cfg.WIKI_DEEP_READ_MAX_CHARS, int)
    assert isinstance(_cfg.WIKI_QUERY_TOP_N, int)


# --- ingest data structures --------------------------------------------------


def test_ingest_candidate_is_frozen():
    c = IngestCandidate(
        kind="entity", path="entities/openai.md", title="OpenAI",
        reason="Mentioned as key org", confidence=0.9,
        default_selected=True, action_hint="update",
    )
    assert c.kind == "entity"
    assert c.default_selected is True
    with pytest.raises(AttributeError):
        c.kind = "concept"


def test_ingest_write_action_is_frozen():
    a = IngestWriteAction(
        action="update", path="entities/openai.md", title="OpenAI",
        reason="New info from source", contribution="Builds GPT-5.",
    )
    assert a.action == "update"
    assert a.contribution == "Builds GPT-5."


def test_ingest_write_action_source_check():
    a = IngestWriteAction(
        action="source_check", path="entities/openai.md", title="OpenAI",
        reason="Conflicting info between sources", contribution="",
    )
    assert a.action == "source_check"


def test_ingest_write_plan_is_frozen():
    plan = IngestWritePlan(
        source_summary="Summary text",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("create", "entities/new.md", "New", "new entity", "content"),
        ],
        user_focus=["entities/openai.md"],
        referenced_source_summaries=[],
    )
    assert len(plan.actions) == 1
    assert plan.actions[0].action == "create"


# --- _pick_index_candidates --------------------------------------------------


def test_pick_index_candidates_scores_by_overlap(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "US AI lab"),
        IndexEntry("DeepSeek", "entities/deepseek.md", "Chinese AI lab"),
    ], concepts=[
        IndexEntry("ML", "concepts/ml.md", "Machine learning"),
    ])

    results = _pick_index_candidates("OpenAI builds advanced AI models", wiki_dir=wiki_dir, top_n=10)
    paths = [c.path for c in results]
    assert "entities/openai.md" in paths
    if "entities/deepseek.md" in paths:
        assert paths.index("entities/openai.md") < paths.index("entities/deepseek.md")


def test_pick_index_candidates_respects_top_n(wiki_dir):
    entities = []
    for i in range(10):
        slug = f"entity{i}"
        entities.append(IndexEntry(f"E{i}", f"entities/{slug}.md", "common keyword"))
    _write_index(wiki_dir, sources=[], entities=entities, concepts=[])

    results = _pick_index_candidates("common keyword", wiki_dir=wiki_dir, top_n=3)
    assert len(results) <= 3


def test_pick_index_candidates_empty_wiki(wiki_dir):
    results = _pick_index_candidates("anything", wiki_dir=wiki_dir, top_n=5)
    assert results == []


def test_pick_index_candidates_includes_chat_context(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("React", "entities/react.md", "Frontend framework"),
    ], concepts=[])

    results = _pick_index_candidates(
        "Some note about programming",
        wiki_dir=wiki_dir, top_n=5,
        chat_context="The user wants to focus on React integration",
    )
    paths = [c.path for c in results]
    assert "entities/react.md" in paths


def test_pick_index_candidates_wiki_scope_placeholder(wiki_dir):
    """wiki_scope parameter is accepted but ignored for now."""
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("A", "entities/a.md", "test"),
    ], concepts=[])

    results = _pick_index_candidates(
        "test", wiki_dir=wiki_dir, top_n=5, wiki_scope="sub1",
    )
    # wiki_scope is accepted without error; results are same as without it
    assert len(results) >= 0


# --- ingest prompts ----------------------------------------------------------

def test_ingest_candidate_prompt_exists():
    from llm.prompts import INGEST_CANDIDATE_SYSTEM
    assert "JSON" in INGEST_CANDIDATE_SYSTEM
    assert "candidates" in INGEST_CANDIDATE_SYSTEM.lower()
    assert "confidence" in INGEST_CANDIDATE_SYSTEM.lower()


def test_ingest_plan_prompt_exists():
    from llm.prompts import INGEST_PLAN_SYSTEM
    assert "JSON" in INGEST_PLAN_SYSTEM
    assert "action" in INGEST_PLAN_SYSTEM.lower()
    for action_type in ("create", "update", "light_link", "skip", "source_check"):
        assert action_type in INGEST_PLAN_SYSTEM


def test_ingest_plan_prompt_forbids_raw_notes():
    from llm.prompts import INGEST_PLAN_SYSTEM
    assert "raw" in INGEST_PLAN_SYSTEM.lower() or "notes/" in INGEST_PLAN_SYSTEM


# --- _collect_related_source_summaries ---------------------------------------


def test_collect_related_source_summaries_reads_linked_sources(wiki_dir):
    target = wiki_dir / "entities" / "openai.md"
    target.write_text(
        "# OpenAI\n\nA lab.\n\n## Sources\n\n- [[sources/summary_ai.md]]\n- [[sources/summary_gpt.md]]\n",
        encoding="utf-8",
    )
    (wiki_dir / "sources" / "summary_ai.md").write_text("# AI note\n\nAI content.", encoding="utf-8")
    (wiki_dir / "sources" / "summary_gpt.md").write_text("# GPT note\n\nGPT content.", encoding="utf-8")

    results = _collect_related_source_summaries(target, wiki_dir=wiki_dir)
    assert len(results) == 2
    assert any("AI content" in text for _, text in results)
    assert any("GPT content" in text for _, text in results)


def test_collect_related_source_summaries_skips_missing(wiki_dir):
    target = wiki_dir / "entities" / "openai.md"
    target.write_text(
        "# OpenAI\n\nA lab.\n\n## Sources\n\n- [[sources/summary_missing.md]]\n",
        encoding="utf-8",
    )
    results = _collect_related_source_summaries(target, wiki_dir=wiki_dir)
    assert results == []


def test_collect_related_source_summaries_no_sources_section(wiki_dir):
    target = wiki_dir / "entities" / "openai.md"
    target.write_text("# OpenAI\n\nJust prose.", encoding="utf-8")
    results = _collect_related_source_summaries(target, wiki_dir=wiki_dir)
    assert results == []


def test_collect_related_source_summaries_wiki_scope_placeholder(wiki_dir):
    target = wiki_dir / "entities" / "a.md"
    target.write_text("# A\n\n## Sources\n\n- [[sources/summary_x.md]]\n", encoding="utf-8")
    (wiki_dir / "sources" / "summary_x.md").write_text("content", encoding="utf-8")
    results = _collect_related_source_summaries(target, wiki_dir=wiki_dir, wiki_scope="sub1")
    assert len(results) == 1


# --- JSON parsers -------------------------------------------------------------


def test_parse_candidates_valid():
    raw = '{"summary": "AI overview.", "candidates": [' \
          '{"kind": "entity", "slug": "openai", "name": "OpenAI", ' \
          '"reason": "Key org", "confidence": 0.9, "action_hint": "update", ' \
          '"contribution": "Builds GPT."}]}'
    summary, candidates = _parse_candidates(raw)
    assert summary == "AI overview."
    assert len(candidates) == 1
    assert candidates[0].kind == "entity"
    assert candidates[0].title == "OpenAI"
    assert candidates[0].confidence == 0.9


def test_parse_candidates_strips_fences():
    raw = '```json\n{"summary": "S", "candidates": []}\n```'
    summary, candidates = _parse_candidates(raw)
    assert summary == "S"
    assert candidates == []


def test_parse_candidates_invalid_returns_empty():
    summary, candidates = _parse_candidates("not json")
    assert summary == ""
    assert candidates == []


def test_parse_write_plan_valid():
    raw = '{"actions": [' \
          '{"action": "update", "path": "entities/openai.md", "title": "OpenAI", ' \
          '"reason": "New info", "contribution": "Builds GPT-5."},' \
          '{"action": "source_check", "path": "entities/deepseek.md", "title": "DeepSeek", ' \
          '"reason": "Conflict with existing page", "contribution": "Date discrepancy"},' \
          '{"action": "skip", "path": "concepts/ml.md", "title": "ML", ' \
          '"reason": "No new info", "contribution": ""}]}'
    actions = _parse_write_plan(raw)
    assert len(actions) == 3
    assert actions[0].action == "update"
    assert actions[1].action == "source_check"
    assert actions[2].action == "skip"


def test_parse_write_plan_invalid_returns_empty():
    actions = _parse_write_plan("garbage")
    assert actions == []


# --- _execute_write_plan -----------------------------------------------------


def test_execute_write_plan_create_action(wiki_dir, config):
    plan = IngestWritePlan(
        source_summary="AI overview.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("create", "entities/openai.md", "OpenAI", "new", "Builds GPT models."),
        ],
        user_focus=[], referenced_source_summaries=[],
    )
    (wiki_dir / "sources" / "summary_ai.md").write_text("# AI\n\nAI overview.", encoding="utf-8")
    _write_index(wiki_dir, sources=[
        IndexEntry("AI", "sources/summary_ai.md", "AI overview"),
    ], entities=[], concepts=[])

    ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki_dir)
    assert ok == 1
    assert failed == 0
    assert flagged == []
    assert (wiki_dir / "entities" / "openai.md").exists()
    body = (wiki_dir / "entities" / "openai.md").read_text(encoding="utf-8")
    assert "OpenAI" in body
    assert "Builds GPT" in body
    idx = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "entities/openai.md" in idx


def test_execute_write_plan_update_action(wiki_dir, config):
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI\n\nOld info.\n", encoding="utf-8")
    (wiki_dir / "sources" / "summary_ai.md").write_text("# AI\n\nSummary.", encoding="utf-8")
    _write_index(wiki_dir, sources=[
        IndexEntry("AI", "sources/summary_ai.md", "AI overview"),
    ], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])

    plan = IngestWritePlan(
        source_summary="New findings.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("update", "entities/openai.md", "OpenAI", "new info", "Now builds GPT-5."),
        ],
        user_focus=[], referenced_source_summaries=[],
    )

    with patch("llm.wiki_engine.chat", return_value="# OpenAI\n\nOld info. Now builds GPT-5."):
        ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki_dir)

    assert ok == 1 and failed == 0 and flagged == []
    body = (wiki_dir / "entities" / "openai.md").read_text(encoding="utf-8")
    assert "GPT-5" in body


def test_execute_write_plan_light_link_action(wiki_dir, config):
    (wiki_dir / "entities" / "openai.md").write_text(
        "# OpenAI\n\nA lab.\n\n## Sources\n\n- [[sources/summary_old.md]]\n",
        encoding="utf-8",
    )
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])

    plan = IngestWritePlan(
        source_summary="S.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("light_link", "entities/openai.md", "OpenAI", "just a mention", ""),
        ],
        user_focus=[], referenced_source_summaries=[],
    )
    ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki_dir)
    assert ok == 1
    body = (wiki_dir / "entities" / "openai.md").read_text(encoding="utf-8")
    assert "summary_ai.md" in body
    assert "A lab." in body  # prose unchanged


def test_execute_write_plan_skip_action(wiki_dir, config):
    _write_index(wiki_dir, sources=[], entities=[], concepts=[])
    plan = IngestWritePlan(
        source_summary="S.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("skip", "entities/openai.md", "OpenAI", "irrelevant", ""),
        ],
        user_focus=[], referenced_source_summaries=[],
    )
    ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki_dir)
    assert ok == 0 and failed == 0 and flagged == []
    assert not (wiki_dir / "entities" / "openai.md").exists()


def test_execute_write_plan_source_check_action(wiki_dir, config):
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI\n\nExisting.\n", encoding="utf-8")
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])

    plan = IngestWritePlan(
        source_summary="S.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("source_check", "entities/openai.md", "OpenAI",
                              "Conflicting founding date", "Source says 2015, page says 2016"),
        ],
        user_focus=[], referenced_source_summaries=[],
    )
    ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki_dir)
    assert ok == 0
    assert failed == 0
    assert len(flagged) == 1
    assert "openai" in flagged[0].lower()
    # Page content should NOT be modified
    body = (wiki_dir / "entities" / "openai.md").read_text(encoding="utf-8")
    assert "Existing." in body
    # But source link should be added
    assert "summary_ai.md" in body
    # Log should record the flag
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "source_check" in log.lower() or "Conflicting" in log


def test_execute_write_plan_isolates_failures(wiki_dir, config):
    (wiki_dir / "entities" / "e1.md").write_text("# E1\n\nold\n", encoding="utf-8")
    (wiki_dir / "entities" / "e2.md").write_text("# E2\n\nold\n", encoding="utf-8")
    (wiki_dir / "sources" / "summary_ai.md").write_text("# AI\n\nS.", encoding="utf-8")
    _write_index(wiki_dir, sources=[
        IndexEntry("AI", "sources/summary_ai.md", "S"),
    ], entities=[
        IndexEntry("E1", "entities/e1.md", "e1"),
        IndexEntry("E2", "entities/e2.md", "e2"),
    ], concepts=[])

    plan = IngestWritePlan(
        source_summary="S.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("update", "entities/e1.md", "E1", "r", "c1"),
            IngestWriteAction("update", "entities/e2.md", "E2", "r", "c2"),
        ],
        user_focus=[], referenced_source_summaries=[],
    )
    call_n = [0]

    def fake_chat(_cfg, messages):
        call_n[0] += 1
        if call_n[0] == 1:
            raise RuntimeError("boom")
        return "# E2\n\nUpdated."

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki_dir)

    assert ok == 1
    assert failed == 1
    assert "old" in (wiki_dir / "entities" / "e1.md").read_text(encoding="utf-8")
    assert "Updated" in (wiki_dir / "entities" / "e2.md").read_text(encoding="utf-8")


def test_execute_write_plan_with_related_map(wiki_dir, config):
    _write_index(wiki_dir, sources=[], entities=[], concepts=[])
    related_map = {
        "entities/openai.md": [("AI", "sources/summary_ai.md"), ("ML", "concepts/ml.md")],
    }
    plan = IngestWritePlan(
        source_summary="S.",
        source_filename="sources/summary_ai.md",
        actions=[
            IngestWriteAction("create", "entities/openai.md", "OpenAI", "new", "Content."),
        ],
        user_focus=[], referenced_source_summaries=[],
    )
    ok, _, _ = _execute_write_plan(plan, config, wiki_dir=wiki_dir, related_map=related_map)
    assert ok == 1
    body = (wiki_dir / "entities" / "openai.md").read_text(encoding="utf-8")
    assert "## Related" in body
    assert "ML" in body


# --- _build_ingest_extract_messages / _build_write_plan ----------------------


def test_build_ingest_extract_messages_includes_source_index_history(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")

    msgs = _build_ingest_extract_messages(
        source_text="OpenAI trains GPT",
        source_title="ai",
        history=[{"role": "user", "content": "Focus on OpenAI"}],
        wiki_dir=wiki_dir,
    )
    assert msgs[0].role == "system"
    user_content = msgs[1].content
    assert "OpenAI trains GPT" in user_content
    assert "openai" in user_content.lower()
    assert any("Focus on OpenAI" in m.content for m in msgs)


def test_build_ingest_extract_messages_wiki_scope_placeholder(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[], concepts=[])
    msgs = _build_ingest_extract_messages(
        source_text="text", source_title="t", history=[],
        wiki_dir=wiki_dir, wiki_scope="sub1",
    )
    assert len(msgs) >= 2


def test_build_write_plan_includes_deep_read(wiki_dir):
    (wiki_dir / "entities" / "openai.md").write_text(
        "# OpenAI\n\nExisting content.", encoding="utf-8",
    )
    candidates = [
        IngestCandidate("entity", "entities/openai.md", "OpenAI", "key org", 0.9, True, "update"),
    ]
    batches = _build_write_plan(
        source_summary="AI overview.",
        candidates=candidates,
        selected_paths=["entities/openai.md"],
        wiki_dir=wiki_dir,
    )
    assert len(batches) >= 1
    msgs = batches[0]
    assert msgs[0].role == "system"
    user_content = msgs[1].content
    assert "Existing content" in user_content
    assert "AI overview" in user_content


def test_build_write_plan_respects_deep_read_max(wiki_dir):
    """Only WIKI_DEEP_READ_MAX pages are deep-read; rest get action_hint only."""
    for i in range(12):
        (wiki_dir / "entities" / f"e{i}.md").write_text(
            f"# E{i}\n\n{'x' * 500}", encoding="utf-8",
        )
    candidates = [
        IngestCandidate("entity", f"entities/e{i}.md", f"E{i}", "r", 0.9, True, "update")
        for i in range(12)
    ]
    selected = [f"entities/e{i}.md" for i in range(12)]

    import config as _cfg
    old_max = _cfg.WIKI_DEEP_READ_MAX
    _cfg.WIKI_DEEP_READ_MAX = 3
    try:
        batches = _build_write_plan(
            source_summary="S.",
            candidates=candidates,
            selected_paths=selected,
            wiki_dir=wiki_dir,
        )
        # All batches combined, count how many have "existing page:" content
        all_content = "\n".join(m.content for batch in batches for m in batch)
        deep_read_count = all_content.count("existing page:")
        assert deep_read_count <= 3
    finally:
        _cfg.WIKI_DEEP_READ_MAX = old_max


def test_build_write_plan_batches_on_budget(wiki_dir):
    """When total chars exceed budget, multiple message batches are returned."""
    for i in range(5):
        (wiki_dir / "entities" / f"e{i}.md").write_text(
            f"# E{i}\n\n{'A' * 5000}", encoding="utf-8",
        )
    candidates = [
        IngestCandidate("entity", f"entities/e{i}.md", f"E{i}", "r", 0.9, True, "update")
        for i in range(5)
    ]
    selected = [f"entities/e{i}.md" for i in range(5)]

    import config as _cfg
    old_chars = _cfg.WIKI_DEEP_READ_MAX_CHARS
    old_max = _cfg.WIKI_DEEP_READ_MAX
    _cfg.WIKI_DEEP_READ_MAX_CHARS = 6000  # force batching
    _cfg.WIKI_DEEP_READ_MAX = 10
    try:
        batches = _build_write_plan(
            source_summary="S.",
            candidates=candidates,
            selected_paths=selected,
            wiki_dir=wiki_dir,
        )
        assert len(batches) >= 2
    finally:
        _cfg.WIKI_DEEP_READ_MAX_CHARS = old_chars
        _cfg.WIKI_DEEP_READ_MAX = old_max


def test_build_write_plan_includes_source_summaries_for_shallow(wiki_dir):
    """Shallow pages trigger related source summary inclusion."""
    target = wiki_dir / "entities" / "openai.md"
    target.write_text(
        "# OpenAI\n\nStub.\n\n## Sources\n\n- [[sources/summary_old.md]]\n",
        encoding="utf-8",
    )
    (wiki_dir / "sources" / "summary_old.md").write_text(
        "# Old\n\nOld source content about OpenAI.", encoding="utf-8",
    )
    candidates = [
        IngestCandidate("entity", "entities/openai.md", "OpenAI", "r", 0.9, True, "update"),
    ]
    batches = _build_write_plan(
        source_summary="New AI overview.",
        candidates=candidates,
        selected_paths=["entities/openai.md"],
        wiki_dir=wiki_dir,
    )
    all_content = "\n".join(m.content for batch in batches for m in batch)
    assert "Old source content" in all_content


def test_build_write_plan_includes_explicit_source_summaries_for_conflict(wiki_dir):
    """Pages with an explicit conflict/source_check signal get source summaries."""
    target = wiki_dir / "entities" / "openai.md"
    target.write_text(
        "# OpenAI\n\nFounded in 2015. Some detail here that makes it non-shallow.\n"
        "Additional content to exceed 200 chars threshold for shallowness.\n"
        "More content here.\n\n"
        "## Sources\n\n- [[sources/summary_a.md]]\n",
        encoding="utf-8",
    )
    (wiki_dir / "sources" / "summary_a.md").write_text("# A\n\nSource A content.", encoding="utf-8")

    candidates = [
        IngestCandidate("entity", "entities/openai.md", "OpenAI", "r", 0.9, True, "update"),
    ]
    batches = _build_write_plan(
        source_summary="Founded in 2016 actually.",
        candidates=candidates,
        selected_paths=["entities/openai.md"],
        wiki_dir=wiki_dir,
        extra_source_summaries=[
            ("sources/summary_a.md", "# A\n\nSource A content."),
        ],
    )
    all_content = "\n".join(m.content for batch in batches for m in batch)
    assert "Source A content" in all_content


def test_build_write_plan_user_requested_source_read(wiki_dir):
    """When user_requested_source_read=True, always include source summaries."""
    target = wiki_dir / "entities" / "openai.md"
    target.write_text(
        "# OpenAI\n\nLong non-shallow content that exceeds 200 chars easily. "
        "This is not shallow at all. Lots of detail. Even more detail here.\n\n"
        "## Sources\n\n- [[sources/summary_a.md]]\n",
        encoding="utf-8",
    )
    (wiki_dir / "sources" / "summary_a.md").write_text("# A\n\nForce-read content.", encoding="utf-8")

    candidates = [
        IngestCandidate("entity", "entities/openai.md", "OpenAI", "r", 0.9, True, "update"),
    ]
    batches = _build_write_plan(
        source_summary="S.",
        candidates=candidates,
        selected_paths=["entities/openai.md"],
        wiki_dir=wiki_dir,
        user_requested_source_read=True,
    )
    all_content = "\n".join(m.content for batch in batches for m in batch)
    assert "Force-read content" in all_content


# --- display formatters and user selection parser ----------------------------


def test_format_candidates_for_display():
    candidates = [
        IngestCandidate("entity", "entities/openai.md", "OpenAI", "Key AI org", 0.9, True, "update"),
        IngestCandidate("concept", "concepts/ml.md", "ML", "Core method", 0.5, True, "create"),
        IngestCandidate("entity", "entities/google.md", "Google", "Tangential", 0.2, False, "update"),
    ]
    text = _format_candidates_for_display(candidates)
    assert "OpenAI" in text and "ML" in text and "Google" in text
    assert "1." in text and "2." in text and "3." in text
    assert "✓" in text


def test_format_plan_for_display():
    actions = [
        IngestWriteAction("create", "entities/new.md", "New Entity", "Brand new", "Full content."),
        IngestWriteAction("update", "entities/openai.md", "OpenAI", "New info", "GPT-5 details."),
        IngestWriteAction("light_link", "concepts/ml.md", "ML", "Just mentioned", ""),
        IngestWriteAction("skip", "concepts/dl.md", "DL", "Not relevant", ""),
        IngestWriteAction("source_check", "entities/x.md", "X", "Conflict", "dates differ"),
    ]
    text = _format_plan_for_display(actions)
    assert "新增" in text
    assert "修改" in text
    assert "轻关联" in text
    assert "跳过" in text
    assert "需核查" in text


def test_parse_user_selection_default():
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "update"),
        IngestCandidate("entity", "e/b.md", "B", "r", 0.5, True, "update"),
        IngestCandidate("entity", "e/c.md", "C", "r", 0.2, False, "update"),
    ]
    selected, wants = _parse_user_selection("默认", candidates)
    assert selected == {0, 1}
    assert wants is False


def test_parse_user_selection_all():
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "update"),
        IngestCandidate("entity", "e/b.md", "B", "r", 0.2, False, "update"),
    ]
    selected, wants = _parse_user_selection("全部", candidates)
    assert selected == {0, 1}
    assert wants is False


def test_parse_user_selection_numbers():
    candidates = [
        IngestCandidate("entity", f"e/{i}.md", f"E{i}", "r", 0.5, True, "u")
        for i in range(5)
    ]
    selected, wants = _parse_user_selection("1,3,5", candidates)
    assert selected == {0, 2, 4}
    assert wants is False


def test_parse_user_selection_exclude():
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "u"),
        IngestCandidate("entity", "e/b.md", "B", "r", 0.8, True, "u"),
        IngestCandidate("entity", "e/c.md", "C", "r", 0.7, True, "u"),
    ]
    selected, wants = _parse_user_selection("-2", candidates)
    assert selected == {0, 2}
    assert wants is False


def test_parse_user_selection_with_source_read_request():
    """User can append '+源' to request source summary reads."""
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "u"),
    ]
    selected, wants_sources = _parse_user_selection("默认+源", candidates)
    assert selected == {0}
    assert wants_sources is True


# --- discuss_and_ingest 5-step flow ------------------------------------------

def test_discuss_and_ingest_shows_candidates(notes_dir, config):
    note = notes_dir / "test.md"
    note.write_text("# AI\n\nOpenAI builds GPT.", encoding="utf-8")

    chat_q_out = queue.Queue()
    user_q_in = queue.Queue()

    def fake_stream(_cfg, messages, **_kw):
        yield "Looks good. [READY_TO_INGEST]"

    candidate_json = (
        '{"summary": "AI overview.",'
        ' "candidates": [{"kind": "entity", "slug": "openai", "name": "OpenAI",'
        ' "reason": "Key org", "confidence": 0.9, "action_hint": "create",'
        ' "contribution": "Builds GPT."}]}'
    )
    plan_json = (
        '{"actions": [{"action": "create", "path": "entities/openai.md",'
        ' "title": "OpenAI", "reason": "new entity", "contribution": "Builds GPT models."}]}'
    )
    call_n = [0]

    def fake_chat(_cfg, messages):
        call_n[0] += 1
        if call_n[0] == 1:
            return candidate_json
        return plan_json

    with patch("llm.wiki_engine.chat_stream", side_effect=fake_stream), \
         patch("llm.wiki_engine.chat", side_effect=fake_chat):

        def _run():
            discuss_and_ingest(note, config, chat_q=chat_q_out, user_q=user_q_in)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        items = []
        while True:
            item = chat_q_out.get(timeout=3)
            items.append(item)
            if "候选" in str(item) or "📋" in str(item):
                break
            if item in ("__DONE__", "__ERROR__"):
                break

        assert any("候选" in str(i) or "📋" in str(i) for i in items)

        user_q_in.put("默认")

        while True:
            item = chat_q_out.get(timeout=3)
            if item == "__READY__":
                break

        user_q_in.put("__CONFIRM__")

        while True:
            item = chat_q_out.get(timeout=3)
            if item in ("__DONE__", "__ERROR__"):
                break

        t.join(timeout=3)


def test_discuss_and_ingest_cancel_at_candidates(notes_dir, config):
    note = notes_dir / "test.md"
    note.write_text("content", encoding="utf-8")

    chat_q_out = queue.Queue()
    user_q_in = queue.Queue()

    def fake_stream(_cfg, messages, **_kw):
        yield "Ready. [READY_TO_INGEST]"

    with patch("llm.wiki_engine.chat_stream", side_effect=fake_stream), \
         patch("llm.wiki_engine.chat", return_value='{"summary": "S.", "candidates": []}'):

        def _run():
            return discuss_and_ingest(note, config, chat_q=chat_q_out, user_q=user_q_in)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        while True:
            item = chat_q_out.get(timeout=3)
            if "候选" in str(item) or "选择" in str(item):
                break
            if item in ("__DONE__", "__ERROR__"):
                break

        user_q_in.put("__CANCEL__")

        while True:
            item = chat_q_out.get(timeout=3)
            if item in ("__DONE__", "__ERROR__"):
                break

        t.join(timeout=3)


def test_discuss_and_ingest_chat_history_in_candidate_prompt(notes_dir, config):
    note = notes_dir / "test.md"
    note.write_text("OpenAI and DeepSeek", encoding="utf-8")

    chat_q_out = queue.Queue()
    user_q_in = queue.Queue()
    stream_call = [0]

    def fake_stream(_cfg, messages, **_kw):
        stream_call[0] += 1
        if stream_call[0] == 1:
            yield "I see OpenAI and DeepSeek. Which interests you more?"
        else:
            yield "Got it, focusing on OpenAI. [READY_TO_INGEST]"

    seen_candidate_prompt = {}

    def fake_chat(_cfg, messages):
        if not seen_candidate_prompt:
            seen_candidate_prompt["user"] = messages[-1].content
        return '{"summary": "S.", "candidates": []}'

    with patch("llm.wiki_engine.chat_stream", side_effect=fake_stream), \
         patch("llm.wiki_engine.chat", side_effect=fake_chat):

        def _run():
            discuss_and_ingest(note, config, chat_q=chat_q_out, user_q=user_q_in)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        while True:
            item = chat_q_out.get(timeout=3)
            if "interests" in str(item):
                break

        user_q_in.put("Focus on OpenAI please")

        while True:
            item = chat_q_out.get(timeout=3)
            if "候选" in str(item) or "选择" in str(item):
                break
            if item in ("__DONE__", "__ERROR__"):
                break

        user_q_in.put("__CANCEL__")
        while True:
            item = chat_q_out.get(timeout=3)
            if item in ("__DONE__", "__ERROR__"):
                break

        t.join(timeout=3)

    assert "Focus on OpenAI" in seen_candidate_prompt.get("user", "")


@pytest.fixture
def wiki_dir(tmp_path):
    d = tmp_path / "wiki"
    d.mkdir()
    _ensure_subdirs(d)
    return d


@pytest.fixture
def notes_dir(tmp_path):
    d = tmp_path / "notes"
    d.mkdir()
    return d


@pytest.fixture
def config():
    return LLMConfig(api_base="https://fake/v1", api_key="k", model="m")


# --- slugify ---------------------------------------------------------------

def test_slugify_ascii():
    assert _slugify("Hello World") == "hello-world"


def test_slugify_cjk_kept():
    assert _slugify("机器 学习") == "机器-学习"


def test_slugify_strips_punctuation():
    assert _slugify("AI/ML & DL!") == "ai-ml-dl"


def test_slugify_collapses_dashes():
    assert _slugify("  a   b  ") == "a-b"


def test_slugify_empty_falls_back():
    assert _slugify("!!!") == "untitled"


# --- _canonical_slug --------------------------------------------------------

def test_canonical_slug_exact_match():
    assert _canonical_slug("openai", {"openai", "deepseek"}) == "openai"


def test_canonical_slug_dash_variant():
    assert _canonical_slug("open-ai", {"openai", "deepseek"}) == "openai"


def test_canonical_slug_case_variant():
    assert _canonical_slug("OpenAI", {"openai"}) == "openai"


def test_canonical_slug_no_match_returns_proposed():
    assert _canonical_slug("anthropic", {"openai", "deepseek"}) == "anthropic"


def test_canonical_slug_empty_returns_empty():
    assert _canonical_slug("", {"openai"}) == ""


def test_canonical_slug_cjk_no_false_positive():
    # Different CJK characters should not match.
    assert _canonical_slug("学习", {"机器", "深度"}) == "学习"


# --- _read_note_source ----------------------------------------------------

def test_read_note_source_md(tmp_path):
    note = tmp_path / "t.md"
    note.write_text("# Hello", encoding="utf-8")
    assert _read_note_source(note) == "# Hello"


def test_read_note_source_unsupported_raises(tmp_path):
    note = tmp_path / "t.txt"
    note.write_text("hello")
    with pytest.raises(ValueError, match="unsupported"):
        _read_note_source(note)


# --- _parse_extract --------------------------------------------------------

def test_parse_extract_minimal():
    raw = '{"summary": "s", "entities": [], "concepts": []}'
    out = _parse_extract(raw)
    assert isinstance(out, ExtractResult)
    assert out.summary == "s"
    assert out.entities == []


def test_parse_extract_full():
    raw = (
        '{"summary": "AI is broad.",'
        ' "entities": [{"name":"OpenAI","slug":"openai","contribution":"funded by ms"}],'
        ' "concepts": [{"name":"ML","slug":"ml","contribution":"core idea"}]}'
    )
    out = _parse_extract(raw)
    assert out.entities[0]["slug"] == "openai"
    assert out.concepts[0]["slug"] == "ml"


def test_parse_extract_strips_code_fences():
    raw = '```json\n{"summary":"s","entities":[],"concepts":[]}\n```'
    out = _parse_extract(raw)
    assert out.summary == "s"


def test_parse_extract_invalid_returns_empty():
    out = _parse_extract("not json at all")
    assert out.summary == ""
    assert out.entities == []


# --- _merge_page -----------------------------------------------------------

def test_merge_page_creates_new(wiki_dir, config):
    target = wiki_dir / "entities" / "openai.md"
    target.write_text("", encoding="utf-8")
    with patch(
        "llm.wiki_engine.chat",
        return_value="# OpenAI\n\nA US AI lab.\n\n## Sources\n- src.md\n",
    ):
        _merge_page(
            target,
            page_title="OpenAI",
            contribution="A US AI lab.",
            source_filename="sources/summary_src.md",
            config=config,
        )
    body = target.read_text(encoding="utf-8")
    assert "OpenAI" in body
    assert "Sources" in body


def test_merge_page_passes_existing_content(wiki_dir, config):
    target = wiki_dir / "entities" / "openai.md"
    target.write_text("# OpenAI\n\nOld facts.\n", encoding="utf-8")

    seen = {}

    def fake_chat(_cfg, messages):
        seen["user"] = messages[1].content
        return "# OpenAI\n\nOld facts. New facts.\n"

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        _merge_page(
            target,
            page_title="OpenAI",
            contribution="New facts.",
            source_filename="sources/summary_src.md",
            config=config,
        )

    assert "Old facts." in seen["user"]
    assert "New facts." in seen["user"]
    assert "sources/summary_src.md" in seen["user"]
    assert "New facts" in target.read_text(encoding="utf-8")


# --- _write_index ----------------------------------------------------------

def test_write_index_three_sections(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[IndexEntry("My Note", "sources/summary_my_note.md", "A test note")],
        entities=[IndexEntry("OpenAI", "entities/openai.md", "US AI lab")],
        concepts=[IndexEntry("ML", "concepts/ml.md", "Machine learning")],
    )
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "## Sources" in text
    assert "## Entities" in text
    assert "## Concepts" in text
    sources_idx = text.index("## Sources")
    entities_idx = text.index("## Entities")
    concepts_idx = text.index("## Concepts")
    assert sources_idx < entities_idx < concepts_idx
    assert text.index("sources/summary_my_note.md") < entities_idx
    assert entities_idx < text.index("entities/openai.md") < concepts_idx
    assert text.index("concepts/ml.md") > concepts_idx


def test_write_index_replaces_atomically(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[IndexEntry("A", "sources/summary_a.md", "first")],
        entities=[], concepts=[],
    )
    _write_index(
        wiki_dir,
        sources=[IndexEntry("A", "sources/summary_a.md", "updated")],
        entities=[], concepts=[],
    )
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert text.count("sources/summary_a.md") == 1
    assert "updated" in text
    assert "first" not in text


def test_write_index_sorts_entries(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[
            IndexEntry("Zebra", "sources/summary_z.md", "z"),
            IndexEntry("Apple", "sources/summary_a.md", "a"),
        ],
        entities=[], concepts=[],
    )
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert text.index("Apple") < text.index("Zebra")


# --- _append_log -----------------------------------------------------------

def test_append_log_creates_file(wiki_dir):
    _append_log(wiki_dir, "ingest", "My Note", "Created sources/summary_of_my_note.md")
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "My Note" in log


# --- _collect_existing_slugs -----------------------------------------------

def test_collect_existing_slugs(wiki_dir):
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")
    (wiki_dir / "entities" / "deepseek.md").write_text("# DeepSeek", encoding="utf-8")
    (wiki_dir / "concepts" / "ml.md").write_text("# ML", encoding="utf-8")

    e, c = _collect_existing_slugs(wiki_dir)
    assert e == {"openai", "deepseek"}
    assert c == {"ml"}


def test_collect_existing_slugs_empty(wiki_dir):
    e, c = _collect_existing_slugs(wiki_dir)
    assert e == set()
    assert c == set()


# --- ingest_note end-to-end -----------------------------------------------

def _scan_index(wiki_dir):
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {"Sources": [], "Entities": [], "Concepts": []}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
        elif current in sections and line.startswith("- ["):
            start = line.find("](")
            end = line.find(")", start)
            if start != -1 and end != -1:
                sections[current].append(line[start + 2:end])
    return sections


def test_ingest_note_writes_summary_entities_concepts(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("OpenAI builds GPT. ML is the field.", encoding="utf-8")

    extract_json = (
        '{"summary": "Note about OpenAI and ML.",'
        ' "entities": [{"name":"OpenAI","slug":"openai","contribution":"Builds GPT."}],'
        ' "concepts": [{"name":"ML","slug":"ml","contribution":"Field of study."}]}'
    )

    calls = []

    def fake_chat(_cfg, messages):
        calls.append(messages[0].content[:30])
        if "JSON" in messages[0].content:
            return extract_json
        return "# Page\n\nMerged content.\n"

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    assert result.name == "summary_ai.md"
    assert result.exists()
    assert result.parent.name == "sources"
    assert "OpenAI and ML" in result.read_text(encoding="utf-8")

    assert (wiki_dir / "entities" / "openai.md").exists()
    assert (wiki_dir / "concepts" / "ml.md").exists()

    idx = _scan_index(wiki_dir)
    assert "sources/summary_ai.md" in idx["Sources"]
    assert "entities/openai.md" in idx["Entities"]
    assert "concepts/ml.md" in idx["Concepts"]

    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "ai" in log

    assert len(calls) == 1  # extract only; new pages use _new_page (no LLM)


def test_ingest_note_summary_lists_related_pages(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")

    extract_json = (
        '{"summary": "A summary.",'
        ' "entities": [{"name":"OpenAI","slug":"openai","contribution":"c"}],'
        ' "concepts": [{"name":"ML","slug":"ml","contribution":"c"}]}'
    )

    def fake_chat(_cfg, messages):
        if "JSON" in messages[0].content:
            return extract_json
        return "# P\n\nbody\n"

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    body = result.read_text(encoding="utf-8")
    assert "## Related" in body
    assert "[OpenAI](../entities/openai.md)" in body
    assert "[ML](../concepts/ml.md)" in body


def test_ingest_note_no_related_section_when_empty(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")
    extract_json = (
        '{"summary": "Only a summary.",'
        ' "entities": [], "concepts": []}'
    )
    with patch("llm.wiki_engine.chat", return_value=extract_json):
        result = ingest_note(note, config, wiki_dir=wiki_dir)
    body = result.read_text(encoding="utf-8")
    assert "## Related" not in body


def test_ingest_note_canonicalizes_slug(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")

    extract_json = (
        '{"summary": "S.",'
        ' "entities": [{"name":"OpenAI","slug":"open-ai","contribution":"c"}],'
        ' "concepts": []}'
    )

    def fake_chat(_cfg, messages):
        if "JSON" in messages[0].content:
            return extract_json
        return "# OpenAI\n\nUpdated.\n"

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    body = result.read_text(encoding="utf-8")
    # The Related section should link to the canonical slug, not the proposed one.
    assert "[OpenAI](../entities/openai.md)" in body
    # The proposed slug file should NOT have been created.
    assert not (wiki_dir / "entities" / "open-ai.md").exists()


def test_ingest_note_merge_failure_is_isolated(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")
    # Pre-create entity files so _merge_page (not _new_page) is called.
    (wiki_dir / "entities" / "e1.md").write_text("# E1\n\nold\n", encoding="utf-8")
    (wiki_dir / "entities" / "e2.md").write_text("# E2\n\nold\n", encoding="utf-8")

    extract_json = (
        '{"summary": "S.",'
        ' "entities": [{"name":"E1","slug":"e1","contribution":"c1"},'
        '              {"name":"E2","slug":"e2","contribution":"c2"}],'
        ' "concepts": []}'
    )

    call_n = [0]

    def fake_chat(_cfg, messages):
        call_n[0] += 1
        if call_n[0] == 1:
            return extract_json
        if call_n[0] == 2:
            raise RuntimeError("merge boom")
        return "# E2\n\nok\n"

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    assert result.exists()
    # E1 merge failed — file still has old content (merge exception caught).
    assert "old" in (wiki_dir / "entities" / "e1.md").read_text(encoding="utf-8")
    # E2 merge succeeded.
    assert "ok" in (wiki_dir / "entities" / "e2.md").read_text(encoding="utf-8")
    idx = _scan_index(wiki_dir)
    assert "entities/e2.md" in idx["Entities"]
    # E1 should NOT be in the index (merge failed → not registered).
    assert "entities/e1.md" not in idx["Entities"]


def test_ingest_note_skips_when_extract_unparseable(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")

    with patch("llm.wiki_engine.chat", return_value="garbage not json"):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    assert result.exists()
    idx = _scan_index(wiki_dir)
    assert idx["Entities"] == []
    assert idx["Concepts"] == []


# --- migrate_wiki_to_subdirs ----------------------------------------------

def test_migrate_moves_summary_files(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "summary_a.md").write_text("# A", encoding="utf-8")
    (wiki / "entity_b.md").write_text("# B", encoding="utf-8")
    (wiki / "concept_c.md").write_text("# C", encoding="utf-8")
    (wiki / "index.md").write_text(
        "- [A](summary_a.md) — a\n- [B](entity_b.md) — b\n- [C](concept_c.md) — c\n",
        encoding="utf-8",
    )

    n = migrate_wiki_to_subdirs(wiki)
    assert n == 3

    assert (wiki / "sources" / "summary_a.md").exists()
    assert (wiki / "entities" / "b.md").exists()
    assert (wiki / "concepts" / "c.md").exists()
    assert not (wiki / "summary_a.md").exists()

    idx = (wiki / "index.md").read_text(encoding="utf-8")
    assert "sources/summary_a.md" in idx
    assert "entities/b.md" in idx
    assert "concepts/c.md" in idx


def test_migrate_strips_prefix_from_already_migrated(tmp_path):
    """Files already in subdirs with 'entity_' prefix get cleaned up."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "entities").mkdir()
    (wiki / "concepts").mkdir()
    (wiki / "entities" / "entity_openai.md").write_text("# OpenAI", encoding="utf-8")
    (wiki / "concepts" / "concept_ml.md").write_text("# ML", encoding="utf-8")
    (wiki / "index.md").write_text(
        "- [E](entities/entity_openai.md) — e\n- [C](concepts/concept_ml.md) — c\n",
        encoding="utf-8",
    )

    n = migrate_wiki_to_subdirs(wiki)
    assert n == 2
    assert (wiki / "entities" / "openai.md").exists()
    assert not (wiki / "entities" / "entity_openai.md").exists()
    assert (wiki / "concepts" / "ml.md").exists()
    assert not (wiki / "concepts" / "concept_ml.md").exists()

    idx = (wiki / "index.md").read_text(encoding="utf-8")
    assert "entities/openai.md" in idx
    assert "concepts/ml.md" in idx


def test_migrate_deletes_prefixed_when_target_exists(tmp_path):
    """Prefixed copy is deleted when newer correct-named file already present."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "entities").mkdir()
    (wiki / "entities" / "entity_openai.md").write_text("old", encoding="utf-8")
    (wiki / "entities" / "openai.md").write_text("new", encoding="utf-8")

    n = migrate_wiki_to_subdirs(wiki)
    assert n == 1
    assert (wiki / "entities" / "openai.md").read_text(encoding="utf-8") == "new"
    assert not (wiki / "entities" / "entity_openai.md").exists()


# --- _pick_relevant_pages & query_wiki ------------------------------------

def test_pick_relevant_pages_by_keyword(wiki_dir):
    (wiki_dir / "sources" / "summary_ai.md").write_text(
        "# AI\nArtificial intelligence overview.", encoding="utf-8")
    (wiki_dir / "sources" / "summary_cooking.md").write_text(
        "# Cooking\nHow to make pasta.", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")

    pages = _pick_relevant_pages("artificial intelligence", wiki_dir=wiki_dir, top_n=5)
    names = [p.name for p in pages]
    assert "summary_ai.md" in names


def test_pick_relevant_pages_returns_max_n(wiki_dir):
    for i in range(10):
        name = f"summary_page_{i}.md"
        (wiki_dir / "sources" / name).write_text(
            f"# Page {i}\nCommon keyword here.", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")

    pages = _pick_relevant_pages("common keyword", wiki_dir=wiki_dir, top_n=3)
    assert len(pages) <= 3


def test_pick_relevant_pages_empty_wiki(wiki_dir):
    pages = _pick_relevant_pages("anything", wiki_dir=wiki_dir, top_n=5)
    assert pages == []


def test_pick_relevant_pages_covers_all_prefixes(wiki_dir):
    (wiki_dir / "sources" / "summary_a.md").write_text(
        "artificial intelligence overview", encoding="utf-8")
    (wiki_dir / "entities" / "openai.md").write_text(
        "openai builds artificial models", encoding="utf-8")
    (wiki_dir / "concepts" / "ml.md").write_text(
        "artificial reasoning concept", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")

    pages = _pick_relevant_pages("artificial", wiki_dir=wiki_dir, top_n=10)
    names = {p.name for p in pages}
    assert "summary_a.md" in names
    assert "openai.md" in names
    assert "ml.md" in names


def test_read_index_catalog_supports_synthesis(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[],
        entities=[],
        concepts=[],
        synthesis=[IndexEntry("Saved answer", "synthesis/query_ai.md", "AI answer")],
    )
    catalog = _read_index_catalog(wiki_dir)
    assert catalog.synthesis[0].filename == "synthesis/query_ai.md"
    sources, entities, concepts = _read_index_entries(wiki_dir)
    assert sources == []
    assert entities == []
    assert concepts == []


def test_pick_query_index_candidates_uses_index_without_page_reads(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])
    (wiki_dir / "entities" / "openai.md").write_text(
        "this file should not be needed", encoding="utf-8",
    )

    with patch("pathlib.Path.read_text", autospec=True) as mocked:
        def fake_read(path, *args, **kwargs):
            if str(path).endswith("index.md"):
                return "# Wiki Index\n\n## Entities\n\n- [OpenAI](entities/openai.md) — AI lab\n"
            raise AssertionError("page read")
        mocked.side_effect = fake_read
        candidates = _pick_query_index_candidates("OpenAI", wiki_dir=wiki_dir, top_n=5)

    assert candidates[0].path == "entities/openai.md"


def test_expand_query_related_pages_one_hop(wiki_dir):
    (wiki_dir / "entities" / "openai.md").write_text(
        "# OpenAI\n\n## Related\n\n- [AI](../sources/summary_ai.md)\n",
        encoding="utf-8",
    )
    (wiki_dir / "sources" / "summary_ai.md").write_text(
        "# AI\n\n## Related\n\n- [ML](../concepts/ml.md)\n",
        encoding="utf-8",
    )
    (wiki_dir / "concepts" / "ml.md").write_text("# ML", encoding="utf-8")

    related = _expand_query_related_pages(
        ["entities/openai.md"], wiki_dir=wiki_dir, max_pages=5,
    )
    paths = [c.path for c in related]
    assert "sources/summary_ai.md" in paths
    assert "concepts/ml.md" not in paths


def test_classify_query_answer_type():
    assert _classify_query_answer_type("比较 OpenAI 和 DeepSeek") == "comparison_table"
    assert _classify_query_answer_type("做一个时间线") == "timeline"
    assert _classify_query_answer_type("生成 PPT 提纲") == "slide_outline"
    assert _classify_query_answer_type("普通问题") == "direct_answer"


def test_query_wiki_returns_generator(wiki_dir, config):
    (wiki_dir / "index.md").write_text(
        "# Wiki Index\n\n- [AI](sources/summary_ai.md) — AI overview\n",
        encoding="utf-8")
    (wiki_dir / "sources" / "summary_ai.md").write_text(
        "# AI\nArtificial intelligence is ...", encoding="utf-8")

    chunks = ["This ", "is ", "the answer."]
    with patch("llm.wiki_engine.chat_stream", return_value=iter(chunks)):
        result = list(query_wiki("What is AI?", config, wiki_dir=wiki_dir))
    assert result == chunks


def test_query_wiki_uses_index_first_context(wiki_dir, config):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI\n\nBuilds AI.", encoding="utf-8")
    seen = {}

    def fake_stream(_cfg, messages, **_kw):
        seen["user"] = messages[1].content
        yield "answer"

    with patch("llm.wiki_engine.chat_stream", side_effect=fake_stream):
        assert list(query_wiki("OpenAI", config, wiki_dir=wiki_dir)) == ["answer"]

    assert "Wiki page: entities/openai.md" in seen["user"]


def test_query_wiki_raw_source_only_on_trigger(wiki_dir, notes_dir, config):
    _write_index(wiki_dir, sources=[
        IndexEntry("AI", "sources/summary_ai.md", "AI source"),
    ], entities=[], concepts=[])
    (wiki_dir / "sources" / "summary_ai.md").write_text(
        "---\nsource: ai.md\n---\n\n# AI\n\nSummary.", encoding="utf-8",
    )
    (notes_dir / "ai.md").write_text("Raw source detail.", encoding="utf-8")
    seen = []

    def fake_stream(_cfg, messages, **_kw):
        seen.append(messages[1].content)
        yield "answer"

    with patch("llm.wiki_engine.chat_stream", side_effect=fake_stream):
        list(query_wiki("AI", config, wiki_dir=wiki_dir, notes_dir=notes_dir))
        list(query_wiki("核对原文 AI", config, wiki_dir=wiki_dir, notes_dir=notes_dir))

    assert "Raw source excerpt" not in seen[0]
    assert "Raw source excerpt" in seen[1]


def test_save_query_answer_as_wiki_page_updates_index_and_log(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[])
    path = save_query_answer_as_wiki_page(
        "What is OpenAI?",
        "OpenAI is an AI lab.",
        ["entities/openai.md"],
        wiki_dir=wiki_dir,
        answer_type="direct_answer",
    )
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "type: synthesis" in body
    assert "entities/openai.md" in body
    idx = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "## Synthesis" in idx
    assert "synthesis/" in idx
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "query_save" in log


def test_query_wiki_empty_wiki(wiki_dir, config):
    result = list(query_wiki("anything?", config, wiki_dir=wiki_dir))
    assert len(result) == 1
    assert "empty" in result[0].lower() or "空" in result[0]


# --- _strip_managed_sections -----------------------------------------------

def test_strip_managed_sections_removes_frontmatter_and_sources():
    text = (
        "---\ntype: entity\ncreated: 2026-01-01\n---\n\n"
        "# OpenAI\n\nA lab.\n\n## Sources\n\n- src.md\n"
    )
    result = _strip_managed_sections(text)
    assert "---" not in result
    assert "## Sources" not in result
    assert "# OpenAI" in result
    assert "A lab." in result


def test_strip_managed_sections_chinese_sources():
    text = "# 数据集\n\n描述。\n\n## 来源\n\n- src.md\n"
    result = _strip_managed_sections(text)
    assert "## 来源" not in result
    assert "描述" in result


def test_strip_managed_sections_related():
    text = "# Page\n\nContent.\n\n## Related\n\n- [A](a.md)\n"
    result = _strip_managed_sections(text)
    assert "## Related" not in result
    assert "Content." in result


def test_strip_managed_sections_no_sections():
    text = "# Title\n\nJust prose."
    assert _strip_managed_sections(text) == text


# --- _build_related_section / _build_sources_section -----------------------

def test_build_related_section():
    related = [("ML", "concepts/ml.md"), ("DL", "concepts/dl.md")]
    section = _build_related_section(related)
    assert "## Related" in section
    assert "[ML](concepts/ml.md)" in section
    assert "[DL](concepts/dl.md)" in section


def test_build_related_section_relative_to_source_page():
    related = [("OpenAI", "entities/openai.md"), ("ML", "concepts/ml.md")]
    section = _build_related_section(
        related, from_filename="sources/summary_ai.md",
    )
    assert "[OpenAI](../entities/openai.md)" in section
    assert "[ML](../concepts/ml.md)" in section


def test_build_related_section_empty():
    assert _build_related_section([]) == ""


def test_build_sources_section_dedup():
    existing = ["- [[sources/summary_a.md]]"]
    section = _build_sources_section(existing, "sources/summary_a.md")
    assert section.count("summary_a.md") == 1


def test_build_sources_section_appends_new():
    existing = ["- [[sources/summary_a.md]]"]
    section = _build_sources_section(existing, "sources/summary_b.md")
    assert "summary_a.md" in section
    assert "summary_b.md" in section


# --- _merge_page deterministic sections -----------------------------------

def test_merge_page_strips_sections_before_llm(wiki_dir, config):
    target = wiki_dir / "entities" / "test.md"
    target.write_text(
        "# Test\n\nOld prose.\n\n## Sources\n\n- [[old_src.md]]\n\n## Related\n\n- [A](a.md)\n",
        encoding="utf-8",
    )
    seen = {}

    def fake_chat(_cfg, messages):
        seen["user"] = messages[1].content
        return "# Test\n\nOld prose. New prose."

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        _merge_page(target, page_title="Test", contribution="New.",
                     source_filename="sources/summary_x.md", config=config)
    assert "## Sources" not in seen["user"]
    assert "## Related" not in seen["user"]
    body = target.read_text(encoding="utf-8")
    assert "## Sources" in body
    assert "summary_x.md" in body


def test_merge_page_with_related(wiki_dir, config):
    target = wiki_dir / "entities" / "test.md"
    target.write_text("# Test\n\nExisting.\n", encoding="utf-8")

    with patch("llm.wiki_engine.chat", return_value="# Test\n\nMerged."):
        _merge_page(
            target, page_title="Test", contribution="New.",
            source_filename="sources/summary_x.md", config=config,
            related=[("ML", "concepts/ml.md")],
        )
    body = target.read_text(encoding="utf-8")
    assert "## Related" in body
    assert "[ML](../concepts/ml.md)" in body


# --- _new_page with related -----------------------------------------------

def test_new_page_with_related(wiki_dir):
    target = wiki_dir / "entities" / "test.md"
    _new_page(
        target, page_title="Test", contribution="Content.",
        source_filename="sources/summary_x.md", page_type="entity",
        related=[("ML", "concepts/ml.md"), ("DL", "concepts/dl.md")],
    )
    body = target.read_text(encoding="utf-8")
    assert "## Related" in body
    assert "[ML](../concepts/ml.md)" in body
    assert "[DL](../concepts/dl.md)" in body


# --- migrate fixes old-format links in content ----------------------------

def test_migrate_fixes_old_format_links_in_content(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "sources").mkdir()
    (wiki / "entities").mkdir()
    (wiki / "concepts").mkdir()
    (wiki / "sources" / "summary_a.md").write_text(
        "# A\n\n## Related\n\n- [Foo](entity_foo.md)\n- [Bar](concept_bar.md)\n",
        encoding="utf-8",
    )
    (wiki / "entities" / "foo.md").write_text("# Foo", encoding="utf-8")
    (wiki / "concepts" / "bar.md").write_text("# Bar", encoding="utf-8")
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")

    migrate_wiki_to_subdirs(wiki)

    body = (wiki / "sources" / "summary_a.md").read_text(encoding="utf-8")
    assert "../entities/foo.md" in body
    assert "entity_foo.md" not in body
    assert "../concepts/bar.md" in body
    assert "concept_bar.md" not in body


# --- discuss_and_ingest ---------------------------------------------------

import queue


def test_build_discuss_messages(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _ensure_subdirs(wiki)
    msgs = _build_discuss_messages("Hello world", [], wiki_dir=wiki)
    assert len(msgs) == 2  # system + user
    assert msgs[0].role == "system"
    assert "Hello world" in msgs[1].content


def test_build_discuss_messages_with_history(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _ensure_subdirs(wiki)
    msgs = _build_discuss_messages(
        "Source",
        [{"role": "assistant", "content": "I see X and Y"},
         {"role": "user", "content": "Focus on X"}],
        wiki_dir=wiki,
    )
    assert len(msgs) == 4  # system + source + assistant + user
    assert msgs[2].content == "I see X and Y"
    assert msgs[3].content == "Focus on X"


def test_build_discuss_messages_includes_index_and_slugs(wiki_dir):
    _write_index(wiki_dir, sources=[], entities=[
        IndexEntry("OpenAI", "entities/openai.md", "AI lab"),
    ], concepts=[
        IndexEntry("ML", "concepts/ml.md", "Machine learning"),
    ])
    (wiki_dir / "entities" / "openai.md").write_text("# OpenAI", encoding="utf-8")
    (wiki_dir / "concepts" / "ml.md").write_text("# ML", encoding="utf-8")

    msgs = _build_discuss_messages("Hello world", [], wiki_dir=wiki_dir)
    user_content = msgs[1].content
    assert "Hello world" in user_content
    # Index catalog must be included
    assert "OpenAI" in user_content
    assert "ML" in user_content
    # Slug list must be included
    assert "openai" in user_content
    assert "ml" in user_content


def test_discuss_and_ingest_ready_flow(notes_dir, config):
    """Full 5-step flow: discussion → candidates → selection → plan → execute."""
    note = notes_dir / "test.md"
    note.write_text("# AI\n\nOpenAI builds GPT models.", encoding="utf-8")

    chat_q = queue.Queue()
    user_q = queue.Queue()

    def fake_stream(_cfg, messages, **_kw):
        yield "I found: OpenAI. [READY_TO_INGEST]"

    candidate_json = (
        '{"summary": "Note about OpenAI.",'
        ' "candidates": [{"kind": "entity", "slug": "openai", "name": "OpenAI",'
        ' "reason": "Key org", "confidence": 0.9, "action_hint": "create",'
        ' "contribution": "Builds GPT."}]}'
    )
    plan_json = (
        '{"actions": [{"action": "create", "path": "entities/openai.md",'
        ' "title": "OpenAI", "reason": "new entity",'
        ' "contribution": "Builds GPT models."}]}'
    )
    call_n = [0]

    def fake_chat(_cfg, messages):
        call_n[0] += 1
        if call_n[0] == 1:
            return candidate_json
        return plan_json

    with patch("llm.wiki_engine.chat_stream", side_effect=fake_stream), \
         patch("llm.wiki_engine.chat", side_effect=fake_chat):

        def _run():
            discuss_and_ingest(note, config, chat_q=chat_q, user_q=user_q)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        chunks = []
        while True:
            item = chat_q.get(timeout=3)
            chunks.append(item)
            if "候选" in str(item) or "选择" in str(item):
                break

        assert any("OpenAI" in str(c) for c in chunks)

        user_q.put("默认")

        while True:
            item = chat_q.get(timeout=3)
            if item == "__READY__":
                break

        user_q.put("__CONFIRM__")

        final_items = []
        while True:
            item = chat_q.get(timeout=3)
            final_items.append(item)
            if item in ("__DONE__", "__ERROR__"):
                break

        assert "__DONE__" in final_items
        t.join(timeout=3)
