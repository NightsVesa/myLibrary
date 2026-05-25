from llm.prompts import (
    INGEST_EXTRACT_SYSTEM,
    ingest_extract_system,
    MERGE_PAGE_SYSTEM,
    QUERY_SYSTEM,
    LOG_ENTRY_TEMPLATE,
)


def test_extract_prompt_mentions_json():
    assert "JSON" in INGEST_EXTRACT_SYSTEM


def test_extract_prompt_lists_required_keys():
    for key in ("summary", "entities", "concepts"):
        assert key in INGEST_EXTRACT_SYSTEM


def test_merge_prompt_mentions_existing_and_new():
    assert "existing" in MERGE_PAGE_SYSTEM.lower()
    assert "new contribution" in MERGE_PAGE_SYSTEM.lower()


def test_query_prompt_unchanged_contract():
    assert "wiki" in QUERY_SYSTEM.lower()


def test_log_entry_template_has_placeholders():
    sample = LOG_ENTRY_TEMPLATE.format(
        date="2026-05-22 10:00", operation="ingest", title="t", details="d"
    )
    assert "2026-05-22" in sample
    assert "ingest" in sample


def test_extract_prompt_function_respects_max_items():
    prompt_10 = ingest_extract_system(max_items=10)
    assert "AT MOST 10" in prompt_10
    prompt_20 = ingest_extract_system(max_items=20)
    assert "AT MOST 20" in prompt_20


def test_merge_prompt_says_no_sources_related():
    lower = MERGE_PAGE_SYSTEM.lower()
    assert "do not emit" in lower
    assert "## sources" in lower
    assert "## related" in lower
