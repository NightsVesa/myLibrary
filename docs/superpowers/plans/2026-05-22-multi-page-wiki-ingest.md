# Multi-Page Wiki Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-summary ingest with a two-stage LLM flow that produces a source summary plus cross-page updates to entity and concept pages, and a categorized `index.md`.

**Architecture:**
Stage 1 (`extract`) sends the raw source plus the current `index.md` catalog to the LLM, which returns one JSON document describing the source summary, the entities/concepts it mentions, and which existing pages to update. Stage 2 (`merge`) loops over each affected entity/concept page: one LLM call per page receives the page's current text (empty if new) plus the new contribution and returns the updated page body. The orchestrator writes the source summary, every updated entity/concept page, a categorized index, and a log entry. The flow remains fire-and-forget on the background thread; if any merge call fails, that page is skipped but the source summary is still written.

**Tech Stack:** Python 3, `httpx` (existing `llm/client.py`), `pytest` with `unittest.mock.patch`, OpenAI-compatible chat endpoint (DeepSeek default).

---

## File Structure

| File | Role |
|---|---|
| `llm/prompts.py` | Add `INGEST_EXTRACT_SYSTEM`, `MERGE_PAGE_SYSTEM`, JSON schema description. Keep existing `QUERY_SYSTEM`. Remove old `INGEST_SYSTEM` and `INDEX_ENTRY_TEMPLATE`. |
| `llm/wiki_engine.py` | Rewrite ingest pipeline. Add `_extract`, `_merge_page`, `_write_index`, helpers `_slugify`, `_load_page`. Keep `query_wiki` / `_pick_relevant_pages` but make them glob `summary_*.md`, `entity_*.md`, `concept_*.md`. |
| `tests/test_prompts.py` | Drop assertions about removed templates; add assertions about new ones. |
| `tests/test_wiki_engine.py` | Replace tests tied to old `_parse_ingest_response` / flat index with tests for the new JSON-based extract, per-page merge, categorized index, and orchestrated `ingest_note`. |
| `CLAUDE.md` | Update "LLM wiki layer" section to describe the new file layout, two-stage flow, and categorized index. |

Naming convention (flat directory, prefix-based — no migration required, old `summary_*.md` files continue to work as source pages):
- `summary_<note-stem>.md` — per-source summary page (unchanged name)
- `entity_<slug>.md` — per-entity page (NEW)
- `concept_<slug>.md` — per-concept page (NEW)
- `index.md` — three sections: Sources, Entities, Concepts (CHANGED)
- `log.md` — append-only chronological log (unchanged)

---

## Task 1: Slug helper

**Files:**
- Modify: `D:\myLibrary\llm\wiki_engine.py`
- Test: `D:\myLibrary\tests\test_wiki_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wiki_engine.py`:

```python
from llm.wiki_engine import _slugify


def test_slugify_ascii():
    assert _slugify("Hello World") == "hello-world"


def test_slugify_cjk_kept():
    # CJK characters are preserved (lowercased ASCII only)
    assert _slugify("机器 学习") == "机器-学习"


def test_slugify_strips_punctuation():
    assert _slugify("AI/ML & DL!") == "ai-ml-dl"


def test_slugify_collapses_dashes():
    assert _slugify("  a   b  ") == "a-b"


def test_slugify_empty_falls_back():
    assert _slugify("!!!") == "untitled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py::test_slugify_ascii -v`
Expected: FAIL — `ImportError: cannot import name '_slugify'`

- [ ] **Step 3: Implement `_slugify` in `llm/wiki_engine.py`**

Add near the top of the module (after the imports):

```python
import re as _re


def _slugify(name: str) -> str:
    text = name.strip().lower()
    # Replace runs of non-alphanumeric (keeping CJK) with a single dash.
    out_chars: list[str] = []
    for ch in text:
        if ch.isalnum() or "一" <= ch <= "鿿":
            out_chars.append(ch)
        else:
            out_chars.append("-")
    slug = "".join(out_chars)
    slug = _re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k slugify -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add slug helper for entity and concept page filenames"
```

---

## Task 2: New prompt templates

**Files:**
- Modify: `D:\myLibrary\llm\prompts.py`
- Test: `D:\myLibrary\tests\test_prompts.py`

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_prompts.py` with:

```python
from llm.prompts import (
    INGEST_EXTRACT_SYSTEM,
    MERGE_PAGE_SYSTEM,
    QUERY_SYSTEM,
    LOG_ENTRY_TEMPLATE,
)


def test_extract_prompt_mentions_json():
    assert "JSON" in INGEST_EXTRACT_SYSTEM


def test_extract_prompt_lists_required_keys():
    for key in ("summary", "entities", "concepts", "update_targets"):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ImportError` on `INGEST_EXTRACT_SYSTEM` / `MERGE_PAGE_SYSTEM`.

- [ ] **Step 3: Rewrite `llm/prompts.py`**

Full replacement contents:

```python
INGEST_EXTRACT_SYSTEM = """\
You are a wiki maintainer for a personal knowledge base.

You will receive (a) a source note and (b) the current wiki index catalog \
listing every existing page. Your job is to plan the wiki updates for this \
source.

Respond with EXACTLY one JSON object and nothing else. Do not wrap it in \
markdown fences. The object must have these keys:

{
  "summary": "<100-300 word markdown summary of the source>",
  "entities": [
    {"name": "<display name>", "slug": "<kebab-case-slug>",
     "contribution": "<1-3 sentences explaining what THIS source adds about this entity>"}
  ],
  "concepts": [
    {"name": "<display name>", "slug": "<kebab-case-slug>",
     "contribution": "<1-3 sentences explaining what THIS source adds about this concept>"}
  ],
  "update_targets": ["entity_<slug>.md", "concept_<slug>.md", ...]
}

Rules:
- Entities are concrete (people, tools, places, products). Concepts are abstract \
(ideas, methods, theories).
- Slugs: lowercase ASCII with dashes, OR CJK characters joined with dashes. \
Match an existing page's slug if one already covers the same thing (look at the index).
- `update_targets` MUST list every page (existing or new) whose `<slug>` appears \
in entities/concepts above. The orchestrator uses this to drive per-page merge calls.
- Write summary and contributions in the same language as the source.
- Be factual. Do not invent information.
- Keep entities + concepts to AT MOST 15 combined.
"""

MERGE_PAGE_SYSTEM = """\
You are a wiki maintainer updating a single wiki page.

You will receive:
- The page's existing markdown content (may be empty if this is a new page).
- The new contribution from a freshly ingested source, including the source's title.

Your job: return the FULL updated markdown body for the page. Integrate the new \
contribution into the existing content. Add a "Sources" section at the bottom \
listing every source that has contributed, including the new one (avoid duplicates).

Rules:
- Preserve facts already on the page. Only add or refine — never delete unless \
contradicted.
- Keep the page focused on its subject. No meta-commentary.
- Write in the same language as the existing page (or the new contribution if \
the page is empty).
- Output ONLY the markdown body. No code fences, no JSON, no explanations.
"""

QUERY_SYSTEM = """\
You are a knowledge base assistant. You answer questions based on the wiki \
pages provided in the context.

Rules:
- Answer in the same language the user asks in.
- Base your answer ONLY on the provided wiki pages. If the wiki does not \
contain enough information, say so honestly.
- Cite which wiki page(s) your answer draws from.
- Be concise but thorough.
- If the question is ambiguous, ask for clarification.
"""

LOG_ENTRY_TEMPLATE = "## [{date}] {operation} | {title}\n{details}\n\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add llm/prompts.py tests/test_prompts.py
git commit -m "feat: split ingest prompt into extract + per-page merge"
```

---

## Task 3: Parse extract JSON

**Files:**
- Modify: `D:\myLibrary\llm\wiki_engine.py`
- Test: `D:\myLibrary\tests\test_wiki_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wiki_engine.py`:

```python
from llm.wiki_engine import ExtractResult, _parse_extract


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py -k parse_extract -v`
Expected: FAIL — `ExtractResult` and `_parse_extract` do not exist.

- [ ] **Step 3: Implement parser in `llm/wiki_engine.py`**

Replace the existing `IngestResult` dataclass and `_parse_ingest_response` function with:

```python
@dataclass(frozen=True)
class ExtractResult:
    summary: str
    entities: list[dict]
    concepts: list[dict]
    update_targets: list[str]


def _parse_extract(raw: str) -> ExtractResult:
    import json
    text = raw.strip()
    if text.startswith("```"):
        # Strip leading ```json or ``` and trailing ```
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return ExtractResult("", [], [], [])
    return ExtractResult(
        summary=str(data.get("summary", "")),
        entities=list(data.get("entities", [])),
        concepts=list(data.get("concepts", [])),
        update_targets=list(data.get("update_targets", [])),
    )
```

Also remove the now-stale `from llm.prompts import INGEST_SYSTEM, ...INDEX_ENTRY_TEMPLATE` import — replace it with:

```python
from llm.prompts import (
    INGEST_EXTRACT_SYSTEM,
    MERGE_PAGE_SYSTEM,
    QUERY_SYSTEM,
    LOG_ENTRY_TEMPLATE,
)
```

(Other code that referenced `IngestResult` / `_parse_ingest_response` / `INDEX_ENTRY_TEMPLATE` will be rewritten in Tasks 4–6. If you run the suite now, expect tests in `test_wiki_engine.py` that touch the old names to fail — that is fine; they will be replaced in Task 6.)

- [ ] **Step 4: Run parser tests**

Run: `python -m pytest tests/test_wiki_engine.py -k parse_extract -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: parse extract-stage JSON response"
```

---

## Task 4: Per-page merge call

**Files:**
- Modify: `D:\myLibrary\llm\wiki_engine.py`
- Test: `D:\myLibrary\tests\test_wiki_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wiki_engine.py`:

```python
from llm.wiki_engine import _merge_page


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py -k merge_page -v`
Expected: FAIL — `_merge_page` not defined.

- [ ] **Step 3: Implement `_merge_page`**

Add to `llm/wiki_engine.py`:

```python
def _merge_page(
    target: Path,
    *,
    page_title: str,
    contribution: str,
    source_filename: str,
    config: LLMConfig,
) -> None:
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    user_content = (
        f"Page title: {page_title}\n"
        f"New source: {source_filename}\n\n"
        f"=== Existing page content ===\n{existing or '(empty — this is a new page)'}\n\n"
        f"=== New contribution from this source ===\n{contribution}\n"
    )
    messages = [
        Message(role="system", content=MERGE_PAGE_SYSTEM),
        Message(role="user", content=user_content),
    ]
    updated = chat(config, messages)
    target.write_text(updated.rstrip() + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_wiki_engine.py -k merge_page -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: per-page LLM merge for entity and concept updates"
```

---

## Task 5: Categorized index writer

**Files:**
- Modify: `D:\myLibrary\llm\wiki_engine.py`
- Test: `D:\myLibrary\tests\test_wiki_engine.py`

- [ ] **Step 1: Write the failing test**

Replace the existing `test_update_index_*` block in `tests/test_wiki_engine.py` with:

```python
from llm.wiki_engine import _write_index, IndexEntry


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
    # Each entry must appear under its section.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py -k write_index -v`
Expected: FAIL — `_write_index` / `IndexEntry` not defined.

- [ ] **Step 3: Implement in `llm/wiki_engine.py`**

Remove the old `_update_index` function. Add:

```python
@dataclass(frozen=True)
class IndexEntry:
    title: str
    filename: str
    summary: str


def _write_index(
    wiki_dir: Path,
    *,
    sources: list[IndexEntry],
    entities: list[IndexEntry],
    concepts: list[IndexEntry],
) -> None:
    def _section(name: str, entries: list[IndexEntry]) -> str:
        if not entries:
            return f"## {name}\n\n_(none yet)_\n\n"
        lines = [f"## {name}\n"]
        for e in sorted(entries, key=lambda x: x.title.lower()):
            lines.append(f"- [{e.title}]({e.filename}) — {e.summary}\n")
        lines.append("\n")
        return "".join(lines)

    body = (
        "# Wiki Index\n\n"
        + _section("Sources", sources)
        + _section("Entities", entities)
        + _section("Concepts", concepts)
    )
    (wiki_dir / "index.md").write_text(body, encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_wiki_engine.py -k write_index -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: categorized index with sources/entities/concepts sections"
```

---

## Task 6: Orchestrate ingest end-to-end

**Files:**
- Modify: `D:\myLibrary\llm\wiki_engine.py`
- Test: `D:\myLibrary\tests\test_wiki_engine.py`

- [ ] **Step 1: Write the failing test**

Replace the existing `test_ingest_note_creates_wiki_page` test with the following block, and delete `test_parse_ingest_response_*` tests entirely (they target the removed parser):

```python
def _scan_index(wiki_dir):
    """Helper: parse current index.md into {section: [filename, ...]}."""
    text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {"Sources": [], "Entities": [], "Concepts": []}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
        elif current in sections and line.startswith("- ["):
            # extract filename between '](' and ')'
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
        calls.append(messages[0].content[:30])  # crude tag of which prompt
        if "wiki maintainer" in messages[0].content and "JSON" in messages[0].content:
            return extract_json
        # merge call — echo a minimal page body
        return "# Page\n\nMerged content.\n"

    with patch("llm.wiki_engine.chat", side_effect=fake_chat):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    # Source page
    assert result.name == "summary_ai.md"
    assert result.exists()
    assert "OpenAI and ML" in result.read_text(encoding="utf-8")

    # Entity + concept pages
    assert (wiki_dir / "entity_openai.md").exists()
    assert (wiki_dir / "concept_ml.md").exists()

    # Index has all three sections populated
    idx = _scan_index(wiki_dir)
    assert "summary_ai.md" in idx["Sources"]
    assert "entity_openai.md" in idx["Entities"]
    assert "concept_ml.md" in idx["Concepts"]

    # Log appended
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "ai" in log

    # One extract call + two merge calls = 3 total
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

    # Source page still written despite merge failure
    assert result.exists()
    # Failed entity page absent; second one written
    assert not (wiki_dir / "entity_e1.md").exists()
    assert (wiki_dir / "entity_e2.md").exists()
    # Index reflects only the successfully-written pages
    idx = _scan_index(wiki_dir)
    assert "entity_e2.md" in idx["Entities"]
    assert "entity_e1.md" not in idx["Entities"]


def test_ingest_note_skips_when_extract_unparseable(wiki_dir, notes_dir, config):
    note = notes_dir / "ai.md"
    note.write_text("content", encoding="utf-8")

    with patch("llm.wiki_engine.chat", return_value="garbage not json"):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    # Source page is still written (with empty summary) so the user sees
    # something happened; entities/concepts are empty.
    assert result.exists()
    idx = _scan_index(wiki_dir)
    assert idx["Entities"] == []
    assert idx["Concepts"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py -k ingest_note -v`
Expected: FAIL — `ingest_note` still references removed helpers.

- [ ] **Step 3: Rewrite `ingest_note` and helpers**

Remove the old `_update_index`, `_append_log` (we will keep `_append_log` as-is; just rewrite `ingest_note`). Replace the body of `ingest_note` with:

```python
def _read_index_entries(wiki_dir: Path) -> tuple[list[IndexEntry], list[IndexEntry], list[IndexEntry]]:
    """Parse the existing index.md back into three lists."""
    sources: list[IndexEntry] = []
    entities: list[IndexEntry] = []
    concepts: list[IndexEntry] = []
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return sources, entities, concepts
    current: list[IndexEntry] | None = None
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Sources"):
            current = sources
        elif line.startswith("## Entities"):
            current = entities
        elif line.startswith("## Concepts"):
            current = concepts
        elif current is not None and line.startswith("- ["):
            # "- [Title](file.md) — summary"
            try:
                title = line[line.index("[") + 1:line.index("](")]
                filename = line[line.index("](") + 2:line.index(")")]
                summary = line.split("— ", 1)[1] if "— " in line else ""
                current.append(IndexEntry(title, filename, summary))
            except ValueError:
                continue
    return sources, entities, concepts


def _index_catalog_for_prompt(wiki_dir: Path) -> str:
    """Render index.md (or a placeholder) for the extract prompt."""
    idx = wiki_dir / "index.md"
    if not idx.exists():
        return "(wiki is empty)"
    return idx.read_text(encoding="utf-8")


def ingest_note(
    note_path: Path,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
) -> Path:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    wiki.mkdir(parents=True, exist_ok=True)

    source_text = note_path.read_text(encoding="utf-8")
    title = note_path.stem.replace("_", " ")
    catalog = _index_catalog_for_prompt(wiki)

    # Stage 1: extract
    extract_messages = [
        Message(role="system", content=INGEST_EXTRACT_SYSTEM),
        Message(
            role="user",
            content=(
                f"Source note title: {title}\n\n"
                f"=== Source ===\n{source_text}\n\n"
                f"=== Current wiki index ===\n{catalog}\n"
            ),
        ),
    ]
    extracted = _parse_extract(chat(config, extract_messages))

    # Write the source summary page first.
    source_filename = _wiki_filename(note_path.name)
    source_page = wiki / source_filename
    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
    )
    source_page.write_text(
        frontmatter + f"# {title}\n\n{extracted.summary}\n",
        encoding="utf-8",
    )

    # Stage 2: per-page merges. Track which pages succeeded for the index.
    sources, entities, concepts = _read_index_entries(wiki)
    # Ensure this source is in the Sources list.
    sources = [e for e in sources if e.filename != source_filename]
    sources.append(IndexEntry(
        title=title,
        filename=source_filename,
        summary=(extracted.summary.split("\n")[0][:80] or "(no summary)"),
    ))

    def _merge_and_register(items: list[dict], prefix: str, registry: list[IndexEntry]) -> None:
        for item in items:
            slug = _slugify(item.get("slug") or item.get("name", ""))
            if not slug:
                continue
            filename = f"{prefix}_{slug}.md"
            target = wiki / filename
            try:
                _merge_page(
                    target,
                    page_title=item.get("name", slug),
                    contribution=item.get("contribution", ""),
                    source_filename=source_filename,
                    config=config,
                )
            except Exception:
                continue  # skip this page, keep going
            # Deduplicate registry entry by filename.
            registry[:] = [e for e in registry if e.filename != filename]
            registry.append(IndexEntry(
                title=item.get("name", slug),
                filename=filename,
                summary=(item.get("contribution", "").split("\n")[0][:80]),
            ))

    _merge_and_register(extracted.entities, "entity", entities)
    _merge_and_register(extracted.concepts, "concept", concepts)

    _write_index(wiki, sources=sources, entities=entities, concepts=concepts)
    _append_log(
        wiki, "ingest", title,
        f"Created {source_filename}; touched {len(extracted.entities)} entities, "
        f"{len(extracted.concepts)} concepts",
    )

    return source_page
```

- [ ] **Step 4: Run full wiki test suite**

Run: `python -m pytest tests/test_wiki_engine.py -v`
Expected: all tests pass. If `test_pick_relevant_pages_*` fails because it still writes `summary_*.md` files (which now coexist with `entity_*.md` / `concept_*.md`), proceed — Task 7 fixes the picker.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: orchestrate two-stage ingest with cross-page updates"
```

---

## Task 7: Extend query to all page categories

**Files:**
- Modify: `D:\myLibrary\llm\wiki_engine.py`
- Test: `D:\myLibrary\tests\test_wiki_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wiki_engine.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py -k covers_all_prefixes -v`
Expected: FAIL — entity_/concept_ files are not globbed.

- [ ] **Step 3: Update `_pick_relevant_pages`**

In `llm/wiki_engine.py`, replace the `for md in wiki.glob("summary_*.md"):` loop with:

```python
    candidates: list[Path] = []
    for pattern in ("summary_*.md", "entity_*.md", "concept_*.md"):
        candidates.extend(wiki.glob(pattern))

    for md in candidates:
        text = md.read_text(encoding="utf-8").lower()
        hits = sum(1 for t in q_tokens if t in text)
        if hits > 0:
            scored.append((hits, md))
```

- [ ] **Step 4: Run query tests**

Run: `python -m pytest tests/test_wiki_engine.py -k "pick_relevant or query_wiki" -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: query reads source, entity, and concept pages"
```

---

## Task 8: Update CLAUDE.md docs

**Files:**
- Modify: `D:\myLibrary\CLAUDE.md`

- [ ] **Step 1: Replace the "LLM wiki layer" subsection**

In `CLAUDE.md`, find the section starting with `### LLM wiki layer` and replace its body with:

````markdown
### LLM wiki layer

Three-layer architecture from `docs/llm-wiki.md`:
- **Raw sources** (`notes/`) — immutable user notes.
- **Wiki** (`wiki/`) — LLM-maintained pages. Flat directory using filename prefixes:
  - `summary_<note-stem>.md` — per-source summary
  - `entity_<slug>.md` — page about a person/tool/place/product
  - `concept_<slug>.md` — page about an abstract idea or method
  - `index.md` — categorized catalog with `## Sources`, `## Entities`, `## Concepts` sections
  - `log.md` — chronological operation log
- **Schema** — prompts in `llm/prompts.py`.

`llm/client.py` is a thin `httpx` wrapper around any OpenAI-compatible chat
completions endpoint. Configuration: `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL`.

**Ingest** (`llm/wiki_engine.ingest_note`) runs in two stages:

1. **Extract** — one LLM call receives the source note plus the current
   `index.md` catalog and returns a JSON document with `summary`, `entities`,
   `concepts`, and `update_targets`. The orchestrator writes the
   `summary_<stem>.md` source page from this.
2. **Merge per page** — for every entity and concept in the extract result,
   one LLM call receives the page's existing markdown (if any) plus the new
   contribution from this source and returns the full updated page body. The
   orchestrator writes each page individually; a single page's failure is
   isolated and does not abort the rest.

After all merges, the categorized `index.md` is rewritten from scratch from
the on-disk state, and a log entry is appended. A typical source touches
5-15 pages and makes that many LLM calls. Ingest runs on a fire-and-forget
daemon thread (`background_ingest`); LLM calls never block the tkinter loop.

**Query** (`llm/wiki_engine.query_wiki`) globs `summary_*.md`, `entity_*.md`,
and `concept_*.md`, picks the top-N by keyword overlap with the question,
and streams the LLM's answer through `chat_stream`. Used by
`ui/chat_tab.ChatTab`.
````

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe two-stage ingest and categorized wiki layout"
```

---

## Task 9: Manual smoke test

- [ ] **Step 1: Back up the current wiki**

```bash
cp -r wiki wiki.bak.2026-05-22
```

- [ ] **Step 2: Run a real ingest end-to-end**

Confirm `.env` has a valid `LLM_API_KEY`, then in a Python REPL:

```python
from pathlib import Path
from llm.client import LLMConfig
from llm.wiki_engine import ingest_note
import config
cfg = LLMConfig(api_base=config.LLM_API_BASE, api_key=config.LLM_API_KEY, model=config.LLM_MODEL)
# pick any existing note
ingest_note(Path("notes") / "<some-existing-note>.md", cfg)
```

Inspect:
- `wiki/summary_<stem>.md` — should contain a fresh summary.
- `wiki/entity_*.md` and `wiki/concept_*.md` — at least one new file each, with a `Sources` section listing the source.
- `wiki/index.md` — three sections, the new files appearing in the right one.
- `wiki/log.md` — newest entry on top.

- [ ] **Step 3: Restore if needed**

If output is wrong, `rm -rf wiki && mv wiki.bak.2026-05-22 wiki` and iterate on the prompts in `llm/prompts.py`.

---

## Self-Review Notes

- **Spec coverage:** source summary ✅ (Task 6), entity/concept page updates ✅ (Tasks 4, 6), categorized index ✅ (Task 5), log append ✅ (Task 6 reuses existing `_append_log`), index-driven query ✅ (Task 7 + existing `_pick_relevant_pages`).
- **Backward compatibility:** existing `summary_*.md` files remain valid; `_read_index_entries` tolerates a missing index; old flat `index.md` is overwritten on the first new ingest.
- **Failure isolation:** verified by `test_ingest_note_merge_failure_is_isolated`. Extract failure falls back to an empty `ExtractResult`, so the source summary is still written.
- **Out of scope:** an interactive review UI, batch ingest, RAG/embedding fallback, prompt-tuning for different LLM providers. Add later if needed.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-multi-page-wiki-ingest.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
