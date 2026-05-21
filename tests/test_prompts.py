from llm.prompts import INGEST_SYSTEM, QUERY_SYSTEM, INDEX_ENTRY_TEMPLATE, LOG_ENTRY_TEMPLATE


def test_ingest_system_is_nonempty_string():
    assert isinstance(INGEST_SYSTEM, str)
    assert len(INGEST_SYSTEM) > 50


def test_query_system_is_nonempty_string():
    assert isinstance(QUERY_SYSTEM, str)
    assert len(QUERY_SYSTEM) > 50


def test_ingest_system_mentions_wiki():
    assert "wiki" in INGEST_SYSTEM.lower() or "维基" in INGEST_SYSTEM


def test_query_system_mentions_answer():
    lower = QUERY_SYSTEM.lower()
    assert "answer" in lower or "回答" in QUERY_SYSTEM or "question" in lower


def test_index_entry_template_has_placeholders():
    assert "{title}" in INDEX_ENTRY_TEMPLATE
    assert "{filename}" in INDEX_ENTRY_TEMPLATE
    assert "{summary}" in INDEX_ENTRY_TEMPLATE


def test_log_entry_template_has_placeholders():
    assert "{date}" in LOG_ENTRY_TEMPLATE
    assert "{operation}" in LOG_ENTRY_TEMPLATE
    assert "{title}" in LOG_ENTRY_TEMPLATE
