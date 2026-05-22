import pytest
from pathlib import Path
from unittest.mock import patch

from llm.client import LLMConfig
from llm.wiki_engine import (
    ingest_note,
    query_wiki,
    _pick_relevant_pages,
    _slugify,
    _parse_extract,
    ExtractResult,
    IndexEntry,
    _merge_page,
    _write_index,
    _append_log,
)


@pytest.fixture
def wiki_dir(tmp_path):
    d = tmp_path / "wiki"
    d.mkdir()
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


# --- _parse_extract --------------------------------------------------------

def test_parse_extract_minimal():
    raw = '{"summary": "s", "entities": [], "concepts": [], "update_targets": []}'
    out = _parse_extract(raw)
    assert isinstance(out, ExtractResult)
    assert out.summary == "s"
    assert out.entities == []
    assert out.update_targets == []


def test_parse_extract_full():
    raw = (
        '{"summary": "AI is broad.",'
        ' "entities": [{"name":"OpenAI","slug":"openai","contribution":"funded by ms"}],'
        ' "concepts": [{"name":"ML","slug":"ml","contribution":"core idea"}],'
        ' "update_targets": ["entity_openai.md","concept_ml.md"]}'
    )
    out = _parse_extract(raw)
    assert out.entities[0]["slug"] == "openai"
    assert out.concepts[0]["slug"] == "ml"
    assert "entity_openai.md" in out.update_targets


def test_parse_extract_strips_code_fences():
    raw = '```json\n{"summary":"s","entities":[],"concepts":[],"update_targets":[]}\n```'
    out = _parse_extract(raw)
    assert out.summary == "s"


def test_parse_extract_invalid_returns_empty():
    out = _parse_extract("not json at all")
    assert out.summary == ""
    assert out.entities == []


# --- _merge_page -----------------------------------------------------------

def test_merge_page_creates_new(wiki_dir, config):
    target = wiki_dir / "entity_openai.md"
    with patch(
        "llm.wiki_engine.chat",
        return_value="# OpenAI\n\nA US AI lab.\n\n## Sources\n- src.md\n",
    ):
        _merge_page(
            target,
            page_title="OpenAI",
            contribution="A US AI lab.",
            source_filename="summary_src.md",
            config=config,
        )
    body = target.read_text(encoding="utf-8")
    assert "OpenAI" in body
    assert "Sources" in body


def test_merge_page_passes_existing_content(wiki_dir, config):
    target = wiki_dir / "entity_openai.md"
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
            source_filename="summary_src.md",
            config=config,
        )

    assert "Old facts." in seen["user"]
    assert "New facts." in seen["user"]
    assert "summary_src.md" in seen["user"]
    assert "New facts" in target.read_text(encoding="utf-8")


# --- _write_index ----------------------------------------------------------

def test_write_index_three_sections(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[IndexEntry("My Note", "summary_my_note.md", "A test note")],
        entities=[IndexEntry("OpenAI", "entity_openai.md", "US AI lab")],
        concepts=[IndexEntry("ML", "concept_ml.md", "Machine learning")],
    )
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "## Sources" in text
    assert "## Entities" in text
    assert "## Concepts" in text
    sources_idx = text.index("## Sources")
    entities_idx = text.index("## Entities")
    concepts_idx = text.index("## Concepts")
    assert sources_idx < entities_idx < concepts_idx
    assert text.index("summary_my_note.md") < entities_idx
    assert entities_idx < text.index("entity_openai.md") < concepts_idx
    assert text.index("concept_ml.md") > concepts_idx


def test_write_index_replaces_atomically(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[IndexEntry("A", "summary_a.md", "first")],
        entities=[], concepts=[],
    )
    _write_index(
        wiki_dir,
        sources=[IndexEntry("A", "summary_a.md", "updated")],
        entities=[], concepts=[],
    )
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert text.count("summary_a.md") == 1
    assert "updated" in text
    assert "first" not in text


def test_write_index_sorts_entries(wiki_dir):
    _write_index(
        wiki_dir,
        sources=[
            IndexEntry("Zebra", "summary_z.md", "z"),
            IndexEntry("Apple", "summary_a.md", "a"),
        ],
        entities=[], concepts=[],
    )
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert text.index("Apple") < text.index("Zebra")


# --- _append_log -----------------------------------------------------------

def test_append_log_creates_file(wiki_dir):
    _append_log(wiki_dir, "ingest", "My Note", "Created summary_of_my_note.md")
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "My Note" in log


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
        ' "concepts": [{"name":"ML","slug":"ml","contribution":"Field of study."}],'
        ' "update_targets": ["entity_openai.md","concept_ml.md"]}'
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
    assert "OpenAI and ML" in result.read_text(encoding="utf-8")

    assert (wiki_dir / "entity_openai.md").exists()
    assert (wiki_dir / "concept_ml.md").exists()

    idx = _scan_index(wiki_dir)
    assert "summary_ai.md" in idx["Sources"]
    assert "entity_openai.md" in idx["Entities"]
    assert "concept_ml.md" in idx["Concepts"]

    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "ai" in log

    assert len(calls) == 3


def test_ingest_note_merge_failure_is_isolated(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")

    extract_json = (
        '{"summary": "S.",'
        ' "entities": [{"name":"E1","slug":"e1","contribution":"c1"},'
        '              {"name":"E2","slug":"e2","contribution":"c2"}],'
        ' "concepts": [], "update_targets": ["entity_e1.md","entity_e2.md"]}'
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
    assert not (wiki_dir / "entity_e1.md").exists()
    assert (wiki_dir / "entity_e2.md").exists()
    idx = _scan_index(wiki_dir)
    assert "entity_e2.md" in idx["Entities"]
    assert "entity_e1.md" not in idx["Entities"]


def test_ingest_note_skips_when_extract_unparseable(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")

    with patch("llm.wiki_engine.chat", return_value="garbage not json"):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    assert result.exists()
    idx = _scan_index(wiki_dir)
    assert idx["Entities"] == []
    assert idx["Concepts"] == []


# --- _pick_relevant_pages & query_wiki ------------------------------------

def test_pick_relevant_pages_by_keyword(wiki_dir):
    (wiki_dir / "summary_ai.md").write_text("# AI\nArtificial intelligence overview.", encoding="utf-8")
    (wiki_dir / "summary_cooking.md").write_text("# Cooking\nHow to make pasta.", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")

    pages = _pick_relevant_pages("artificial intelligence", wiki_dir=wiki_dir, top_n=5)
    filenames = [p.name for p in pages]
    assert "summary_ai.md" in filenames


def test_pick_relevant_pages_returns_max_n(wiki_dir):
    for i in range(10):
        name = f"summary_page_{i}.md"
        (wiki_dir / name).write_text(f"# Page {i}\nCommon keyword here.", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")

    pages = _pick_relevant_pages("common keyword", wiki_dir=wiki_dir, top_n=3)
    assert len(pages) <= 3


def test_pick_relevant_pages_empty_wiki(wiki_dir):
    pages = _pick_relevant_pages("anything", wiki_dir=wiki_dir, top_n=5)
    assert pages == []


def test_pick_relevant_pages_covers_all_prefixes(wiki_dir):
    (wiki_dir / "summary_a.md").write_text("artificial intelligence overview", encoding="utf-8")
    (wiki_dir / "entity_openai.md").write_text("openai builds artificial models", encoding="utf-8")
    (wiki_dir / "concept_ml.md").write_text("artificial reasoning concept", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Wiki Index\n", encoding="utf-8")

    pages = _pick_relevant_pages("artificial", wiki_dir=wiki_dir, top_n=10)
    names = {p.name for p in pages}
    assert "summary_a.md" in names
    assert "entity_openai.md" in names
    assert "concept_ml.md" in names


def test_query_wiki_returns_generator(wiki_dir, config):
    (wiki_dir / "index.md").write_text("# Wiki Index\n\n- [AI](summary_ai.md) — AI overview\n", encoding="utf-8")
    (wiki_dir / "summary_ai.md").write_text("# AI\nArtificial intelligence is ...", encoding="utf-8")

    chunks = ["This ", "is ", "the answer."]
    with patch("llm.wiki_engine.chat_stream", return_value=iter(chunks)):
        result = list(query_wiki("What is AI?", config, wiki_dir=wiki_dir))
    assert result == chunks


def test_query_wiki_empty_wiki(wiki_dir, config):
    result = list(query_wiki("anything?", config, wiki_dir=wiki_dir))
    assert len(result) == 1
    assert "empty" in result[0].lower() or "空" in result[0]
