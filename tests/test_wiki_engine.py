import pytest
from pathlib import Path
from unittest.mock import patch

from llm.client import LLMConfig
from llm.wiki_engine import (
    ingest_note,
    query_wiki,
    _pick_relevant_pages,
    _slugify,
    _canonical_slug,
    _parse_extract,
    ExtractResult,
    IndexEntry,
    _merge_page,
    _write_index,
    _append_log,
    _ensure_subdirs,
    _collect_existing_slugs,
    migrate_wiki_to_subdirs,
)


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

    assert len(calls) == 3


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
    assert "[OpenAI](entities/openai.md)" in body
    assert "[ML](concepts/ml.md)" in body


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
    assert "[OpenAI](entities/openai.md)" in body
    # The proposed slug file should NOT have been created.
    assert not (wiki_dir / "entities" / "open-ai.md").exists()


def test_ingest_note_merge_failure_is_isolated(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")

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
    assert not (wiki_dir / "entities" / "e1.md").exists()
    assert (wiki_dir / "entities" / "e2.md").exists()
    idx = _scan_index(wiki_dir)
    assert "entities/e2.md" in idx["Entities"]
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


def test_query_wiki_empty_wiki(wiki_dir, config):
    result = list(query_wiki("anything?", config, wiki_dir=wiki_dir))
    assert len(result) == 1
    assert "empty" in result[0].lower() or "空" in result[0]
