# 文件 Ingest 优化计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Commit steps in this plan are optional implementation checkpoints; do not create git commits unless the user explicitly asks for commits.

**Goal:** Upgrade the "discuss then auto-ingest" flow into a 5-step controllable wiki maintenance workflow: discussion → candidate_review → deep_review → write_plan → execute.

**Architecture:** The worker thread in `discuss_and_ingest` gains three new phases between discussion and execution. Two user-interactive checkpoints use plain text through the existing `chat_q`/`user_q` queues — candidate selection via text entry, final plan confirmation via the existing confirm button (`__READY__`). `ingest_note()` is refactored to delegate its write logic to a shared `_execute_write_plan()`, keeping its public API unchanged. All new internal functions accept `wiki_dir` + optional `wiki_scope` for future sub-wiki support.

**Boundary:** 子 wiki / 大规模拆分本次只预留 `wiki_scope` 等遗留接口，暂不实现多 wiki 路由、迁移、UI 切换或跨 wiki 检索。

**Tech Stack:** Python 3.11+, pytest, httpx (LLM client), tkinter (UI)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `llm/wiki_engine.py` | Core ingest orchestration | Modify: add data structures, new internal functions, refactor `discuss_and_ingest` |
| `llm/prompts.py` | LLM prompt templates | Modify: add `INGEST_CANDIDATE_SYSTEM`, `INGEST_PLAN_SYSTEM`; update `INGEST_DISCUSS_SYSTEM` |
| `config.py` | App configuration | Modify: add budget constants |
| `ui/main_window.py` | Ingest chat panel UI | Modify: verify `_poll` handles new text-based candidate flow |
| `tests/test_wiki_engine.py` | Engine tests | Modify: add tests for all new functions + flow + wiki_scope placeholders |

---

### Task 1: Add Budget Config Constants

**Files:**
- Modify: `config.py:30-32`
- Test: `tests/test_wiki_engine.py`

- [ ] **Step 1: Write failing test for new config values**

```python
# tests/test_wiki_engine.py — add at top-level
def test_config_budget_constants():
    import config as _cfg
    assert hasattr(_cfg, "WIKI_CANDIDATE_TOP_N")
    assert hasattr(_cfg, "WIKI_DEEP_READ_MAX")
    assert hasattr(_cfg, "WIKI_DEEP_READ_MAX_CHARS")
    assert isinstance(_cfg.WIKI_CANDIDATE_TOP_N, int)
    assert isinstance(_cfg.WIKI_DEEP_READ_MAX, int)
    assert isinstance(_cfg.WIKI_DEEP_READ_MAX_CHARS, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py::test_config_budget_constants -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'WIKI_CANDIDATE_TOP_N'`

- [ ] **Step 3: Add constants to config.py**

Add after line 32 (`WIKI_MAX_EXTRACT_ITEMS`):

```python
WIKI_CANDIDATE_TOP_N = int(os.environ.get("WIKI_CANDIDATE_TOP_N", "20"))
WIKI_DEEP_READ_MAX = int(os.environ.get("WIKI_DEEP_READ_MAX", "8"))
WIKI_DEEP_READ_MAX_CHARS = int(os.environ.get("WIKI_DEEP_READ_MAX_CHARS", "12000"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_engine.py::test_config_budget_constants -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_wiki_engine.py
git commit -m "feat: add wiki ingest budget config constants"
```

---

### Task 2: Add Data Structures

**Files:**
- Modify: `llm/wiki_engine.py:54-66` (after existing dataclasses)
- Test: `tests/test_wiki_engine.py`

- [ ] **Step 1: Write failing tests for new dataclasses**

```python
# tests/test_wiki_engine.py — add imports first:
from llm.wiki_engine import IngestCandidate, IngestWriteAction, IngestWritePlan

# Then add tests:
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py::test_ingest_candidate_is_frozen tests/test_wiki_engine.py::test_ingest_write_action_is_frozen tests/test_wiki_engine.py::test_ingest_write_action_source_check tests/test_wiki_engine.py::test_ingest_write_plan_is_frozen -v`
Expected: FAIL — `ImportError: cannot import name 'IngestCandidate'`

- [ ] **Step 3: Add dataclasses to wiki_engine.py**

Add after `IndexEntry` (line 66):

```python
@dataclass(frozen=True)
class IngestCandidate:
    kind: str          # "entity" | "concept"
    path: str          # e.g. "entities/openai.md"
    title: str
    reason: str
    confidence: float  # 0.0–1.0
    default_selected: bool
    action_hint: str   # "create" | "update" | "light_link"


@dataclass(frozen=True)
class IngestWriteAction:
    action: str        # "create" | "update" | "light_link" | "skip" | "source_check"
    path: str          # e.g. "entities/openai.md"
    title: str
    reason: str
    contribution: str  # text to merge into the page


@dataclass(frozen=True)
class IngestWritePlan:
    source_summary: str
    source_filename: str
    actions: list[IngestWriteAction]
    user_focus: list[str]                  # paths the user selected for deep review
    referenced_source_summaries: list[str] # paths of source summaries read during deep review
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "ingest_candidate or ingest_write_action or ingest_write_plan" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add IngestCandidate, IngestWriteAction, IngestWritePlan dataclasses"
```

---

### Task 3: Update INGEST_DISCUSS_SYSTEM to Include Index/Slug Context

**Files:**
- Modify: `llm/prompts.py:122-150` (update `INGEST_DISCUSS_SYSTEM`)
- Modify: `llm/wiki_engine.py` (update `_build_discuss_messages` to pass index/slug)
- Test: `tests/test_wiki_engine.py`

Original spec requires: "讨论阶段输入：当前 source、index/catalog、已有 slug 列表、聊天历史".

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_engine.py::test_build_discuss_messages_includes_index_and_slugs -v`
Expected: FAIL — `_build_discuss_messages() got an unexpected keyword argument 'wiki_dir'`

- [ ] **Step 3: Update _build_discuss_messages signature and body**

Replace the current `_build_discuss_messages` in `wiki_engine.py`:

```python
def _build_discuss_messages(
    source_text: str,
    history: list[dict[str, str]],
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
) -> list[Message]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    catalog = _index_catalog_for_prompt(wiki)
    entity_slugs, concept_slugs = _collect_existing_slugs(wiki)
    slug_list = _slug_list_for_prompt(entity_slugs, concept_slugs)

    source_section = f"=== Source document ===\n{source_text}"
    index_section = f"=== Current wiki index ===\n{catalog}"

    user_parts = [source_section, index_section]
    if slug_list:
        user_parts.append(slug_list)
    user_parts.append(
        "Please read this source and discuss your findings with me."
    )

    msgs = [Message(role="system", content=INGEST_DISCUSS_SYSTEM)]
    msgs.append(Message(role="user", content="\n\n".join(user_parts)))
    for entry in history:
        msgs.append(Message(role=entry["role"], content=entry["content"]))
    return msgs
```

- [ ] **Step 4: Update INGEST_DISCUSS_SYSTEM prompt in prompts.py**

Add a line about the index context the LLM will receive:

```python
INGEST_DISCUSS_SYSTEM = """\
You are a knowledge base assistant helping the user process a new source document.

You will receive the full text of a source file, the current wiki index catalog \
listing every existing page, and a list of existing entity/concept slugs. \
Your job is NOT to extract yet — it is to have a brief discussion with the user \
about what you found.

1. Read the source and identify: the main topic, key entities (people, tools, \
products, places), key concepts (ideas, methods, theories), and anything \
noteworthy (surprising claims, connections to existing knowledge, things the \
user might want to emphasize or ignore).

2. Check the wiki index: note which entities/concepts already have wiki pages \
and which would be new. Mention relevant existing pages so the user can decide \
whether to update or skip them.

3. Present your findings to the user in 2-4 sentences. Be specific — mention \
names, topics, and why they matter. End with a question inviting their input.

4. When the user replies, adjust your understanding. If they want to emphasize \
something, focus there. If they want to ignore something, drop it. If they ask \
a question, answer it. Keep the conversation moving — don't repeat yourself.

5. When the discussion has covered the important ground and the user seems \
satisfied, append the marker [READY_TO_INGEST] to the END of your message. \
This signals that you have enough guidance to proceed with formal extraction.

Rules:
- Write in the same language as the source.
- Keep each reply to 2-4 sentences. Be concise.
- Don't output JSON or extraction results during discussion — that comes later.
- The user may say things like "继续" or "可以了" or "go ahead" — treat these \
as confirmation to proceed. Append [READY_TO_INGEST] and thank them.
"""
```

- [ ] **Step 5: Fix existing test that doesn't pass wiki_dir**

Update `test_build_discuss_messages` and `test_build_discuss_messages_with_history` to still work (they don't pass `wiki_dir`, which defaults to `app_config.WIKI_DIR`). Patch `app_config.WIKI_DIR` or pass a `wiki_dir`:

```python
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
```

- [ ] **Step 6: Update `discuss_and_ingest` call site**

In `discuss_and_ingest`, update the `_build_discuss_messages` call to pass `wiki_dir`:

```python
messages = _build_discuss_messages(source_text, history, wiki_dir=wiki)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "build_discuss" -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add llm/wiki_engine.py llm/prompts.py tests/test_wiki_engine.py
git commit -m "feat: include index/catalog and slug list in discussion phase prompt"
```

---

### Task 4: Add _pick_index_candidates Helper

**Files:**
- Modify: `llm/wiki_engine.py` (new function after `_collect_existing_slugs`)
- Test: `tests/test_wiki_engine.py`

This function parses `index.md` and scores existing pages against source text + chat context to find candidates for update. **Only uses title + summary from IndexEntry — no page file IO.** Pure Python, no LLM.

- [ ] **Step 1: Write failing tests**

```python
from llm.wiki_engine import _pick_index_candidates

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "pick_index_candidates" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement _pick_index_candidates**

Add to `llm/wiki_engine.py` after `_slug_list_for_prompt`:

```python
def _pick_index_candidates(
    source_text: str,
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
    top_n: int | None = None,
    chat_context: str = "",
) -> list[IngestCandidate]:
    """Score existing wiki pages by title + summary only (no page file IO). Ranked candidates."""
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    effective_n = top_n if top_n is not None else app_config.WIKI_CANDIDATE_TOP_N

    sources_idx, entities_idx, concepts_idx = _read_index_entries(wiki)
    if not entities_idx and not concepts_idx:
        return []

    combined_text = source_text + "\n" + chat_context
    q_tokens = _tokenize(combined_text)
    if not q_tokens:
        return []

    scored: list[tuple[float, IndexEntry, str]] = []

    for entry, kind in (
        *((e, "entity") for e in entities_idx),
        *((e, "concept") for e in concepts_idx),
    ):
        hits = sum(
            1 for t in q_tokens
            if t in entry.title.lower() or t in entry.summary.lower()
        )
        if hits > 0:
            scored.append((float(hits), entry, kind))

    scored.sort(key=lambda t: t[0], reverse=True)
    max_score = scored[0][0] if scored else 1.0

    candidates: list[IngestCandidate] = []
    for score, entry, kind in scored[:effective_n]:
        confidence = round(min(score / max_score, 1.0), 2)
        candidates.append(IngestCandidate(
            kind=kind,
            path=entry.filename,
            title=entry.title,
            reason=f"Keyword overlap score {score:.0f}",
            confidence=confidence,
            default_selected=confidence >= 0.3,
            action_hint="update",
        ))

    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "pick_index_candidates" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add _pick_index_candidates with wiki_scope placeholder"
```

---

### Task 5: Add New Prompts

**Files:**
- Modify: `llm/prompts.py`
- Test: `tests/test_wiki_engine.py`

Two new prompts:
1. `INGEST_CANDIDATE_SYSTEM` — candidates from source + index + chat history.
2. `INGEST_PLAN_SYSTEM` — write plan with all 5 action types including `source_check`.

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "ingest_candidate_prompt or ingest_plan_prompt" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Add INGEST_CANDIDATE_SYSTEM to prompts.py**

Add after `INGEST_DISCUSS_SYSTEM`:

```python
INGEST_CANDIDATE_SYSTEM = """\
You are a wiki maintainer planning updates for a personal knowledge base.

You will receive:
(a) a source document,
(b) the current wiki index catalog,
(c) a list of existing entity/concept slugs,
(d) the discussion history between assistant and user about this source.

Your job: identify which wiki pages should be created or updated based on this source \
and the user's discussion guidance.

Respond with EXACTLY one JSON object (no markdown fences):

{
  "summary": "<100-300 word summary of the source>",
  "candidates": [
    {
      "kind": "entity|concept",
      "slug": "<kebab-case-slug>",
      "name": "<display name>",
      "reason": "<why this page should be created/updated>",
      "confidence": <0.0-1.0>,
      "action_hint": "create|update",
      "contribution": "<1-3 sentences: what THIS source adds>"
    }
  ]
}

Rules:
- Entities are concrete (people, tools, places, products). Concepts are abstract \
(ideas, methods, theories).
- Reuse exact existing slugs when your entity/concept matches one listed.
- Confidence: 1.0 = source has substantial, specific information; 0.5 = mentioned \
but not focal; 0.3 = tangential reference.
- action_hint: "create" for new pages, "update" for existing pages.
- Respect the user's discussion guidance: if they said to emphasize or ignore something, \
follow that.
- Write summary and contributions in the same language as the source.
- Be factual. Do not invent information.
- At most 15 candidates.
"""
```

- [ ] **Step 4: Add INGEST_PLAN_SYSTEM to prompts.py**

```python
INGEST_PLAN_SYSTEM = """\
You are a wiki maintainer generating a write plan for a personal knowledge base.

You will receive:
(a) a source document summary,
(b) candidate pages with their current content (deep-read),
(c) optionally, related source summaries for shallow or conflicting pages.

Your job: decide the exact action for each candidate and produce a structured write plan.

Respond with EXACTLY one JSON object (no markdown fences):

{
  "actions": [
    {
      "action": "create|update|light_link|skip|source_check",
      "path": "<e.g. entities/openai.md>",
      "title": "<display name>",
      "reason": "<why this action>",
      "contribution": "<full contribution text to merge — required for create/update>"
    }
  ]
}

Action semantics:
- create: new page — contribution becomes the initial page body.
- update: existing page — contribution is merged into existing content via a separate \
merge step.
- light_link: only add a cross-reference in ## Sources, no content merge. \
Use when the source merely mentions this entity/concept without adding substantive info.
- skip: do nothing for this candidate. Use when after deep reading you determine the \
source adds nothing new.
- source_check: flag this page for manual review. Use when you detect conflicting \
information between the new source and existing page content, or when the existing \
page's claims cannot be reconciled automatically. Set contribution to a description \
of the conflict.

Rules:
- For each candidate you MUST output exactly one action.
- Do NOT add pages not in the candidate list.
- Do NOT read raw notes/ files — only use the source summary and provided page content.
- When related source summaries are provided, use them to detect conflicts and decide \
between update vs source_check.
- Write contributions in the same language as the source.
- Be factual. Do not invent information.
"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "ingest_candidate_prompt or ingest_plan_prompt" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add llm/prompts.py tests/test_wiki_engine.py
git commit -m "feat: add INGEST_CANDIDATE_SYSTEM and INGEST_PLAN_SYSTEM with source_check action"
```

---

### Task 6: Add _collect_related_source_summaries Helper

**Files:**
- Modify: `llm/wiki_engine.py`
- Test: `tests/test_wiki_engine.py`

Reads `## Sources` from a target page, resolves to `wiki/sources/summary_*.md` paths, returns their content.

- [ ] **Step 1: Write failing tests**

```python
from llm.wiki_engine import _collect_related_source_summaries

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "collect_related_source_summaries" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement _collect_related_source_summaries**

Add to `llm/wiki_engine.py` after `_collect_sources_from_page`:

```python
def _collect_related_source_summaries(
    target: Path,
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
) -> list[tuple[str, str]]:
    """Read source summary content linked from a page's ## Sources section.

    Returns list of (path_str, content) for each resolvable source summary.
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    entries = _collect_sources_from_page(target)
    results: list[tuple[str, str]] = []
    for entry in entries:
        match = _re.search(r"\[\[([^\]]+)\]\]", entry)
        if not match:
            continue
        ref = match.group(1)
        if not ref.startswith("sources/"):
            ref = f"sources/{ref}"
        source_path = wiki / ref
        if source_path.exists():
            results.append((ref, source_path.read_text(encoding="utf-8")))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "collect_related_source_summaries" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add _collect_related_source_summaries with wiki_scope placeholder"
```

---

### Task 7: Add _parse_candidates and _parse_write_plan Parsers

**Files:**
- Modify: `llm/wiki_engine.py`
- Test: `tests/test_wiki_engine.py`

- [ ] **Step 1: Write failing tests**

```python
from llm.wiki_engine import _parse_candidates, _parse_write_plan

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "parse_candidates or parse_write_plan" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement parsers**

Add to `llm/wiki_engine.py` after `_parse_extract`:

```python
def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def _parse_candidates(raw: str) -> tuple[str, list[IngestCandidate]]:
    import json
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return "", []
    summary = str(data.get("summary", ""))
    candidates: list[IngestCandidate] = []
    for item in data.get("candidates", []):
        kind = str(item.get("kind", "entity"))
        slug = str(item.get("slug", ""))
        prefix = "entities" if kind == "entity" else "concepts"
        candidates.append(IngestCandidate(
            kind=kind,
            path=f"{prefix}/{slug}.md" if slug else "",
            title=str(item.get("name", slug)),
            reason=str(item.get("reason", "")),
            confidence=float(item.get("confidence", 0.5)),
            default_selected=float(item.get("confidence", 0.5)) >= 0.3,
            action_hint=str(item.get("action_hint", "create")),
        ))
    return summary, candidates


def _parse_write_plan(raw: str) -> list[IngestWriteAction]:
    import json
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    actions: list[IngestWriteAction] = []
    for item in data.get("actions", []):
        actions.append(IngestWriteAction(
            action=str(item.get("action", "skip")),
            path=str(item.get("path", "")),
            title=str(item.get("title", "")),
            reason=str(item.get("reason", "")),
            contribution=str(item.get("contribution", "")),
        ))
    return actions
```

Also refactor `_parse_extract` to use `_strip_code_fences` (define `_strip_code_fences` before `_parse_extract`, then simplify `_parse_extract`):

```python
def _parse_extract(raw: str) -> ExtractResult:
    import json
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return ExtractResult("", [], [])
    return ExtractResult(
        summary=str(data.get("summary", "")),
        entities=list(data.get("entities", [])),
        concepts=list(data.get("concepts", [])),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "parse_candidates or parse_write_plan" -v`
Expected: PASS

- [ ] **Step 5: Run existing _parse_extract tests to verify no regression**

Run: `python -m pytest tests/test_wiki_engine.py -k "parse_extract" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add _parse_candidates and _parse_write_plan JSON parsers"
```

---

### Task 8: Add _execute_write_plan Function

**Files:**
- Modify: `llm/wiki_engine.py`
- Test: `tests/test_wiki_engine.py`

Handles all 5 action types: `create`, `update`, `light_link`, `skip`, `source_check`. Accepts optional `related_map` for passing `## Related` links through to page writes.

- [ ] **Step 1: Write failing tests**

```python
from llm.wiki_engine import _execute_write_plan

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "execute_write_plan" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement _execute_write_plan**

Add to `llm/wiki_engine.py`:

```python
def _execute_write_plan(
    plan: IngestWritePlan,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
    related_map: dict[str, list[tuple[str, str]]] | None = None,
) -> tuple[int, int, list[str]]:
    """Execute all actions in a write plan.

    Returns (ok_count, fail_count, flagged_paths).
    flagged_paths contains paths of source_check actions.
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    _ensure_subdirs(wiki)

    sources_idx, entities_idx, concepts_idx = _read_index_entries(wiki)
    ok, failed = 0, 0
    flagged: list[str] = []

    for act in plan.actions:
        if act.action == "skip":
            continue

        target = wiki / act.path
        prefix = act.path.split("/")[0]
        page_type = prefix[:-1] if prefix.endswith("s") else prefix
        registry = entities_idx if prefix == "entities" else concepts_idx
        page_related = related_map.get(act.path) if related_map else None

        try:
            if act.action == "source_check":
                # Add source link but don't modify prose; flag for manual review
                if target.exists():
                    existing_sources = _collect_sources_from_page(target)
                    sources_section = _build_sources_section(
                        existing_sources, plan.source_filename,
                    )
                    text = target.read_text(encoding="utf-8")
                    lines = text.splitlines()
                    cut_idx = len(lines)
                    for i, line in enumerate(lines):
                        if line.strip() in _MANAGED_HEADINGS:
                            cut_idx = i
                            break
                    prose = "\n".join(lines[:cut_idx]).rstrip()
                    target.write_text(
                        prose + "\n\n" + sources_section, encoding="utf-8",
                    )
                flagged.append(f"{act.title} ({act.path}): {act.reason}")
                continue

            if act.action == "create":
                _new_page(
                    target,
                    page_title=act.title,
                    contribution=act.contribution,
                    source_filename=plan.source_filename,
                    page_type=page_type,
                    related=page_related,
                )
                ok += 1
            elif act.action == "update":
                if not target.exists():
                    _new_page(
                        target,
                        page_title=act.title,
                        contribution=act.contribution,
                        source_filename=plan.source_filename,
                        page_type=page_type,
                        related=page_related,
                    )
                else:
                    _merge_page(
                        target,
                        page_title=act.title,
                        contribution=act.contribution,
                        source_filename=plan.source_filename,
                        config=config,
                        related=page_related,
                    )
                ok += 1
            elif act.action == "light_link":
                if target.exists():
                    existing_sources = _collect_sources_from_page(target)
                    sources_section = _build_sources_section(
                        existing_sources, plan.source_filename,
                    )
                    text = target.read_text(encoding="utf-8")
                    lines = text.splitlines()
                    cut_idx = len(lines)
                    for i, line in enumerate(lines):
                        if line.strip() in _MANAGED_HEADINGS:
                            cut_idx = i
                            break
                    prose = "\n".join(lines[:cut_idx]).rstrip()
                    target.write_text(
                        prose + "\n\n" + sources_section, encoding="utf-8",
                    )
                ok += 1
            else:
                continue

            registry[:] = [e for e in registry if e.filename != act.path]
            registry.append(IndexEntry(
                title=act.title,
                filename=act.path,
                summary=(
                    act.contribution.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]
                    if act.contribution else "(linked)"
                ),
            ))
        except Exception:
            _logging.exception("write plan action failed for %s", act.path)
            failed += 1

    _write_index(wiki, sources=sources_idx, entities=entities_idx, concepts=concepts_idx)

    action_summary = ", ".join(
        f"{a.action} {a.path}" for a in plan.actions if a.action != "skip"
    )
    flag_summary = ""
    if flagged:
        flag_summary = f"; source_check: {', '.join(flagged)}"
    _append_log(
        wiki, "ingest", plan.source_filename,
        f"Executed write plan: {action_summary or '(no actions)'}; "
        f"ok={ok}, failed={failed}{flag_summary}",
    )
    return ok, failed, flagged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "execute_write_plan" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add _execute_write_plan with source_check, related_map, wiki_scope"
```

---

### Task 9: Add _build_ingest_extract_messages and _build_write_plan

**Files:**
- Modify: `llm/wiki_engine.py`
- Test: `tests/test_wiki_engine.py`

Function names match original spec: `_build_ingest_extract_messages` (candidate extraction), `_build_write_plan` (plan generation with deep reads, budget limits, and batching).

- [ ] **Step 1: Write failing tests**

```python
from llm.wiki_engine import _build_ingest_extract_messages, _build_write_plan

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "build_ingest_extract or build_write_plan" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement _build_ingest_extract_messages**

```python
def _build_ingest_extract_messages(
    source_text: str,
    source_title: str,
    history: list[dict[str, str]],
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
) -> list[Message]:
    from llm.prompts import INGEST_CANDIDATE_SYSTEM
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR

    catalog = _index_catalog_for_prompt(wiki)
    entity_slugs, concept_slugs = _collect_existing_slugs(wiki)
    slug_list = _slug_list_for_prompt(entity_slugs, concept_slugs)

    user_parts = [
        f"Source note title: {source_title}",
        "",
        f"=== Source ===\n{source_text}",
        f"=== Current wiki index ===\n{catalog}",
    ]
    if slug_list:
        user_parts.append(slug_list)
    if history:
        chat_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
            for h in history
        )
        user_parts.append(f"=== Discussion context ===\n{chat_text}")

    return [
        Message(role="system", content=INGEST_CANDIDATE_SYSTEM),
        Message(role="user", content="\n\n".join(user_parts)),
    ]
```

- [ ] **Step 4: Implement _build_write_plan with batching and deep-read limits**

```python
def _build_write_plan(
    source_summary: str,
    candidates: list[IngestCandidate],
    selected_paths: list[str],
    *,
    wiki_dir: Path | None = None,
    wiki_scope: str | None = None,  # reserved for future sub-wiki filtering
    extra_source_summaries: list[tuple[str, str]] | None = None,
    user_requested_source_read: bool = False,
) -> list[list[Message]]:
    """Build LLM messages for write plan generation.

    Returns a list of message batches. When all candidates fit within the
    character budget, a single batch is returned. When the budget is exceeded,
    candidates are split into multiple batches so each gets a separate Plan
    Review LLM call.
    """
    from llm.prompts import INGEST_PLAN_SYSTEM
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    budget = app_config.WIKI_DEEP_READ_MAX_CHARS
    max_deep = app_config.WIKI_DEEP_READ_MAX

    # ── Determine which pages need source summary reads ───────────────
    auto_source_summaries: list[tuple[str, str]] = []
    if not extra_source_summaries:
        extra_source_summaries = []

    deep_read_count = 0
    for path in selected_paths:
        if deep_read_count >= max_deep:
            break
        target = wiki / path
        if not target.exists():
            deep_read_count += 1
            continue
        content = target.read_text(encoding="utf-8")
        prose = _strip_managed_sections(content)
        is_shallow = len(prose.strip()) < 200
        needs_source_read = (
            is_shallow
            or user_requested_source_read
        )
        if needs_source_read:
            auto_source_summaries.extend(
                _collect_related_source_summaries(target, wiki_dir=wiki)
            )
        deep_read_count += 1

    all_extra = extra_source_summaries + auto_source_summaries
    # Deduplicate by path
    seen_paths: set[str] = set()
    deduped_extra: list[tuple[str, str]] = []
    for path, content in all_extra:
        if path not in seen_paths:
            seen_paths.add(path)
            deduped_extra.append((path, content))

    # ── Build candidate groups respecting budget ──────────────────────
    header = f"=== Source summary ===\n{source_summary}"
    header_len = len(header)

    # Group candidates into batches that fit within budget
    batches: list[list[IngestCandidate]] = []
    current_batch: list[IngestCandidate] = []
    current_chars = header_len

    deep_count = 0
    for cand in candidates:
        page = wiki / cand.path
        page_chars = 0
        if cand.path in selected_paths and page.exists() and deep_count < max_deep:
            page_chars = len(page.read_text(encoding="utf-8"))
            deep_count += 1

        if current_batch and current_chars + page_chars > budget:
            batches.append(current_batch)
            current_batch = [cand]
            current_chars = header_len + page_chars
        else:
            current_batch.append(cand)
            current_chars += page_chars

    if current_batch:
        batches.append(current_batch)

    # ── Build messages for each batch ─────────────────────────────────
    result: list[list[Message]] = []
    deep_count = 0
    for batch in batches:
        parts = [header]
        total_chars = header_len

        parts.append("\n=== Candidate pages (deep read) ===")
        for cand in batch:
            if cand.path not in selected_paths:
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — NOT selected, "
                    f"action_hint={cand.action_hint}"
                )
                continue
            page = wiki / cand.path
            if page.exists() and deep_count < max_deep and total_chars < budget:
                page_content = page.read_text(encoding="utf-8")
                if total_chars + len(page_content) > budget:
                    page_content = (
                        page_content[:budget - total_chars] + "\n... (truncated)"
                    )
                total_chars += len(page_content)
                deep_count += 1
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — existing page:\n{page_content}"
                )
            elif page.exists():
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — exists but budget exceeded, "
                    f"action_hint={cand.action_hint}"
                )
            else:
                parts.append(
                    f"\n[{cand.title}] ({cand.path}) — NEW page, "
                    f"action_hint={cand.action_hint}"
                )
                deep_count += 1

        if deduped_extra:
            parts.append("\n=== Related source summaries ===")
            for spath, scontent in deduped_extra:
                if total_chars + len(scontent) > budget:
                    break
                parts.append(f"\n[{spath}]:\n{scontent}")
                total_chars += len(scontent)

        result.append([
            Message(role="system", content=INGEST_PLAN_SYSTEM),
            Message(role="user", content="\n".join(parts)),
        ])

    return result if result else [[
        Message(role="system", content=INGEST_PLAN_SYSTEM),
        Message(role="user", content=header + "\n\n(no candidates)"),
    ]]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "build_ingest_extract or build_write_plan" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add _build_ingest_extract_messages and _build_write_plan with batching"
```

---

### Task 10: Add Display Formatters and User Selection Parser

**Files:**
- Modify: `llm/wiki_engine.py`
- Test: `tests/test_wiki_engine.py`

- [ ] **Step 1: Write failing tests**

```python
from llm.wiki_engine import (
    _format_candidates_for_display,
    _format_plan_for_display,
    _parse_user_selection,
)

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
    assert _parse_user_selection("默认", candidates) == {0, 1}


def test_parse_user_selection_all():
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "update"),
        IngestCandidate("entity", "e/b.md", "B", "r", 0.2, False, "update"),
    ]
    assert _parse_user_selection("全部", candidates) == {0, 1}


def test_parse_user_selection_numbers():
    candidates = [
        IngestCandidate("entity", f"e/{i}.md", f"E{i}", "r", 0.5, True, "u")
        for i in range(5)
    ]
    assert _parse_user_selection("1,3,5", candidates) == {0, 2, 4}


def test_parse_user_selection_exclude():
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "u"),
        IngestCandidate("entity", "e/b.md", "B", "r", 0.8, True, "u"),
        IngestCandidate("entity", "e/c.md", "C", "r", 0.7, True, "u"),
    ]
    assert _parse_user_selection("-2", candidates) == {0, 2}


def test_parse_user_selection_with_source_read_request():
    """User can append '+源' to request source summary reads."""
    candidates = [
        IngestCandidate("entity", "e/a.md", "A", "r", 0.9, True, "u"),
    ]
    selected, wants_sources = _parse_user_selection("默认+源", candidates)
    assert selected == {0}
    assert wants_sources is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "format_candidates or format_plan or parse_user_selection" -v`
Expected: FAIL

- [ ] **Step 3: Implement formatters and parser**

```python
_ACTION_LABELS = {
    "create": "新增",
    "update": "修改",
    "light_link": "轻关联",
    "skip": "跳过",
    "source_check": "需核查",
}


def _format_candidates_for_display(candidates: list[IngestCandidate]) -> str:
    lines = ["\n📋 候选页面：\n"]
    for i, c in enumerate(candidates, 1):
        sel = "✓" if c.default_selected else " "
        kind_label = "实体" if c.kind == "entity" else "概念"
        hint = _ACTION_LABELS.get(c.action_hint, c.action_hint)
        lines.append(
            f"  {i}. [{sel}] {c.title} ({kind_label}, {hint}) — {c.reason}"
        )
    lines.append("")
    lines.append("请回复选择（默认 / 全部 / 编号如 1,3,5 / 排除如 -2,-4）：")
    lines.append('（追加 +源 可要求读取关联源摘要，如"默认+源"）')
    return "\n".join(lines)


def _format_plan_for_display(actions: list[IngestWriteAction]) -> str:
    lines = ["\n📝 写入计划：\n"]
    for a in actions:
        label = _ACTION_LABELS.get(a.action, a.action)
        lines.append(f"  [{label}] {a.title} ({a.path})")
        if a.reason:
            lines.append(f"         原因: {a.reason}")
    lines.append("")
    return "\n".join(lines)


def _parse_user_selection(
    reply: str, candidates: list[IngestCandidate],
) -> tuple[set[int], bool]:
    """Parse user selection reply.

    Returns (selected_indices_0based, wants_source_read).
    User can append "+源" or "+source" to request source summary reads.
    """
    text = reply.strip()
    wants_sources = False
    for suffix in ("+源", "+source", "+src"):
        if suffix in text.lower():
            wants_sources = True
            text = text.replace(suffix, "").replace(suffix.upper(), "").strip()
            break

    text = text.lower()
    n = len(candidates)

    if text in ("全部", "all", "*"):
        return set(range(n)), wants_sources

    if text in ("默认", "default", "", "ok", "好"):
        return {i for i, c in enumerate(candidates) if c.default_selected}, wants_sources

    if text.startswith("-") and (
        "," in text or (len(text) > 1 and text[1:].isdigit())
    ):
        excludes = set()
        for part in text.split(","):
            part = part.strip()
            if part.startswith("-") and part[1:].isdigit():
                excludes.add(int(part[1:]) - 1)
        defaults = {i for i, c in enumerate(candidates) if c.default_selected}
        return defaults - excludes, wants_sources

    selected = set()
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < n:
                selected.add(idx)

    if not selected:
        selected = {i for i, c in enumerate(candidates) if c.default_selected}
    return selected, wants_sources
```

**Note:** `_parse_user_selection` now returns a tuple `(set[int], bool)`. Update earlier tests to match:

```python
def test_parse_user_selection_default():
    # ...
    selected, wants = _parse_user_selection("默认", candidates)
    assert selected == {0, 1}
    assert wants is False

# Similarly for test_parse_user_selection_all, _numbers, _exclude
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -k "format_candidates or format_plan or parse_user_selection" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: add display formatters and user selection parser with +源 support"
```

---

### Task 11: Refactor discuss_and_ingest for 5-Step Flow

**Files:**
- Modify: `llm/wiki_engine.py:714-770`
- Test: `tests/test_wiki_engine.py`

Core refactor. The new flow uses batched `_build_write_plan` and handles `source_check` flagged pages.

- [ ] **Step 1: Write failing tests for the new flow**

```python
def test_discuss_and_ingest_shows_candidates(notes_dir, config):
    note = notes_dir / "test.md"
    note.write_text("# AI\n\nOpenAI builds GPT.", encoding="utf-8")

    chat_q_out = queue.Queue()
    user_q_in = queue.Queue()

    def fake_stream(_cfg, messages):
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

    def fake_stream(_cfg, messages):
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

    def fake_stream(_cfg, messages):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -k "discuss_and_ingest_shows or discuss_and_ingest_cancel_at or discuss_and_ingest_chat_history" -v`
Expected: FAIL

- [ ] **Step 3: Rewrite discuss_and_ingest**

```python
def discuss_and_ingest(
    note_path: Path,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
    chat_q: queue.Queue[str],
    user_q: queue.Queue[str],
) -> Path | None:
    """Interactive ingest: 5-step workflow on a worker thread.

    1. Discussion loop — stream LLM discussion with user
    2. Candidate extraction — LLM identifies pages to create/update
    3. User focus selection — user picks candidates + optional source read
    4. Write plan generation — batched LLM calls after deep-reading pages
    5. Confirmed execution — user approves, plan is executed
    """
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    _ensure_subdirs(wiki)
    source_text = _read_note_source(note_path)
    title = note_path.stem.replace("_", " ")
    history: list[dict[str, str]] = []

    # ── Step 1: Discussion loop ────────────────────────────────────────
    while True:
        messages = _build_discuss_messages(source_text, history, wiki_dir=wiki)
        full_reply: list[str] = []
        for chunk in chat_stream(config, messages):
            full_reply.append(chunk)
            chat_q.put(chunk)
        reply_text = "".join(full_reply)
        history.append({"role": "assistant", "content": reply_text})

        if "[READY_TO_INGEST]" in reply_text:
            break

        user_input = user_q.get()
        if user_input == "__CANCEL__":
            chat_q.put("__DONE__")
            return None
        history.append({"role": "user", "content": user_input})

    # ── Step 2: Candidate extraction ───────────────────────────────────
    chat_q.put("\n\n正在分析候选页面...\n")
    candidate_messages = _build_ingest_extract_messages(
        source_text, title, history, wiki_dir=wiki,
    )
    raw_candidates = chat(config, candidate_messages)
    summary, candidates = _parse_candidates(raw_candidates)

    if not summary:
        summary = title

    # Canonicalize slugs
    entity_slugs, concept_slugs = _collect_existing_slugs(wiki)
    canonicalized: list[IngestCandidate] = []
    for c in candidates:
        existing = entity_slugs if c.kind == "entity" else concept_slugs
        raw_slug = c.path.split("/")[-1].replace(".md", "")
        canon = _canonical_slug(raw_slug, existing)
        prefix = "entities" if c.kind == "entity" else "concepts"
        canon_path = f"{prefix}/{canon}.md"
        action_hint = "update" if (wiki / canon_path).exists() else "create"
        canonicalized.append(IngestCandidate(
            kind=c.kind, path=canon_path, title=c.title,
            reason=c.reason, confidence=c.confidence,
            default_selected=c.default_selected, action_hint=action_hint,
        ))
    candidates = canonicalized

    display_text = _format_candidates_for_display(candidates)
    chat_q.put(display_text)

    # ── Step 3: User focus selection ───────────────────────────────────
    user_selection = user_q.get()
    if user_selection == "__CANCEL__":
        chat_q.put("__DONE__")
        return None

    selected_indices, user_wants_sources = _parse_user_selection(
        user_selection, candidates,
    )
    selected_paths = [
        candidates[i].path
        for i in sorted(selected_indices)
        if i < len(candidates)
    ]

    # ── Step 4: Deep read + write plan (batched) ───────────────────────
    chat_q.put("\n正在深度阅读已选页面，生成写入计划...\n")

    plan_batches = _build_write_plan(
        source_summary=summary,
        candidates=candidates,
        selected_paths=selected_paths,
        wiki_dir=wiki,
        user_requested_source_read=user_wants_sources,
    )

    all_actions: list[IngestWriteAction] = []
    for batch_messages in plan_batches:
        raw_plan = chat(config, batch_messages)
        batch_actions = _parse_write_plan(raw_plan)
        all_actions.extend(batch_actions)

    if not all_actions:
        all_actions = [
            IngestWriteAction(
                action=c.action_hint,
                path=c.path,
                title=c.title,
                reason=c.reason,
                contribution=c.reason,
            )
            for c in candidates
            if c.path in selected_paths
        ]

    plan_display = _format_plan_for_display(all_actions)
    chat_q.put(plan_display)
    chat_q.put("__READY__")

    # ── Step 5: Confirmed execution ────────────────────────────────────
    confirm = user_q.get()
    if confirm == "__CANCEL__":
        chat_q.put("__DONE__")
        return None

    chat_q.put("\n正在执行写入计划...\n")

    source_filename = _wiki_filename(note_path.name)
    source_page = wiki / source_filename
    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
    )
    source_related = [
        (a.title, a.path) for a in all_actions
        if a.action in ("create", "update")
    ]
    related_section = _build_related_section(
        source_related, from_filename=source_filename,
    )
    if related_section:
        related_section = "\n" + related_section
    source_page.write_text(
        frontmatter + f"# {title}\n\n{summary}\n" + related_section,
        encoding="utf-8",
    )

    sources_idx, _, _ = _read_index_entries(wiki)
    sources_idx = [e for e in sources_idx if e.filename != source_filename]
    sources_idx.append(IndexEntry(
        title=title, filename=source_filename,
        summary=(
            summary.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]
            or "(no summary)"
        ),
    ))
    _, entities_idx, concepts_idx = _read_index_entries(wiki)
    _write_index(
        wiki, sources=sources_idx,
        entities=entities_idx, concepts=concepts_idx,
    )

    plan = IngestWritePlan(
        source_summary=summary,
        source_filename=source_filename,
        actions=all_actions,
        user_focus=selected_paths,
        referenced_source_summaries=[],
    )
    try:
        ok, failed, flagged = _execute_write_plan(plan, config, wiki_dir=wiki)
        parts: list[str] = []
        if ok:
            parts.append(f"✅ {ok} 个页面已更新")
        if failed:
            parts.append(f"⚠ {failed} 个页面写入失败")
        if flagged:
            parts.append(f"🔍 {len(flagged)} 个页面需核查:\n" + "\n".join(f"  - {f}" for f in flagged))
        chat_q.put("\n" + "\n".join(parts) + "\n")
        chat_q.put("__DONE__")
        return source_page
    except Exception:
        _logging.exception("write plan execution failed for %s", note_path)
        chat_q.put("\n❌ 执行失败\n")
        chat_q.put("__ERROR__")
        return None
```

- [ ] **Step 4: Update the old test_discuss_and_ingest_ready_flow**

Replace with full 5-step flow test:

```python
def test_discuss_and_ingest_ready_flow(notes_dir, config):
    """Full 5-step flow: discussion → candidates → selection → plan → execute."""
    note = notes_dir / "test.md"
    note.write_text("# AI\n\nOpenAI builds GPT models.", encoding="utf-8")

    chat_q = queue.Queue()
    user_q = queue.Queue()

    def fake_stream(_cfg, messages):
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
```

- [ ] **Step 5: Run all discuss_and_ingest tests**

Run: `python -m pytest tests/test_wiki_engine.py -k "discuss_and_ingest" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: refactor discuss_and_ingest to 5-step workflow with batched plan review"
```

---

### Task 12: Refactor ingest_note to Use _execute_write_plan

**Files:**
- Modify: `llm/wiki_engine.py:387-511`
- Test: `tests/test_wiki_engine.py`

- [ ] **Step 1: Run existing ingest_note tests to establish baseline**

Run: `python -m pytest tests/test_wiki_engine.py -k "ingest_note" -v`
Expected: ALL PASS

- [ ] **Step 2: Refactor ingest_note**

Replace the entity/concept write loop (lines ~466–509) with `_execute_write_plan`. Build a `related_map` to preserve `## Related` behavior:

```python
    # After source page write, persist the source index entry before
    # _execute_write_plan reads and rewrites index.md.
    sources, entities_idx, concepts_idx = _read_index_entries(wiki)
    sources = [e for e in sources if e.filename != source_filename]
    sources.append(IndexEntry(
        title=title,
        filename=source_filename,
        summary=(
            extracted.summary.split("\n")[0][:app_config.WIKI_INDEX_SUMMARY_LEN]
            or "(no summary)"
        ),
    ))
    _write_index(wiki, sources=sources, entities=entities_idx, concepts=concepts_idx)

    # Build related_map and write actions from extracted entities/concepts
    related_map: dict[str, list[tuple[str, str]]] = {}
    actions: list[IngestWriteAction] = []
    for item, slug, filename in resolved:
        target = wiki / filename
        page_related: list[tuple[str, str]] = [(title, source_filename)]
        for peer_item, peer_slug, peer_fn in resolved:
            if peer_fn != filename:
                page_related.append((peer_item.get("name", peer_slug), peer_fn))
        related_map[filename] = page_related
        actions.append(IngestWriteAction(
            action="update" if target.exists() else "create",
            path=filename,
            title=item.get("name", slug),
            reason="extracted from source",
            contribution=item.get("contribution", ""),
        ))

    if actions:
        plan = IngestWritePlan(
            source_summary=extracted.summary,
            source_filename=source_filename,
            actions=actions,
            user_focus=[],
            referenced_source_summaries=[],
        )
        _execute_write_plan(plan, config, wiki_dir=wiki, related_map=related_map)

    return source_page
```

Remove the final entity/concept `_write_index` and final `_append_log` calls that were at the end of `ingest_note` because `_execute_write_plan` now handles action index updates and logging. Keep the source page write and the source index `_write_index` before `_execute_write_plan`; otherwise the source summary page can be written without appearing in `index.md`.

- [ ] **Step 3: Run existing ingest_note tests**

Run: `python -m pytest tests/test_wiki_engine.py -k "ingest_note" -v`
Expected: ALL PASS

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/test_wiki_engine.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "refactor: ingest_note delegates writes to _execute_write_plan with related_map"
```

---

### Task 13: Verify UI Compatibility

**Files:**
- Verify: `ui/main_window.py:929-1048`

No code changes expected — the existing UI already supports the new flow:
- Text entry is always visible for candidate selection typing
- Confirm/skip buttons appear on `__READY__` (now fires after plan display)
- All new content streams as plain text through `chat_q`

- [ ] **Step 1: Verify the existing UI code is compatible**

The text entry (line 982-986) and send button (line 991) handle candidate selection. The confirm/skip buttons start hidden and appear on `__READY__` (line 1037). The poll loop's `_append_text` handles all new text-based output. No new control codes.

- [ ] **Step 2: Manual test**

Run: `python app.py`
1. Drag a `.md` file to trigger ingest
2. Verify discussion phase works
3. Verify candidate list appears after `[READY_TO_INGEST]`
4. Type "默认" and hit Enter
5. Verify write plan appears and confirm/skip buttons show
6. Click "确认提取"
7. Verify execution completes with status summary

- [ ] **Step 3: Commit only if changes were needed**

```bash
git add ui/main_window.py
git commit -m "fix: adjust ingest chat UI for 5-step workflow"
```

---

### Task 14: Update Exports and Run Full Regression

**Files:**
- Modify: `tests/test_wiki_engine.py` (update imports)

- [ ] **Step 1: Update test imports**

```python
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
    _append_log,
    _ensure_subdirs,
    _collect_existing_slugs,
    _strip_managed_sections,
    _build_related_section,
    _build_sources_section,
    _collect_sources_from_page,
    _build_discuss_messages,
    discuss_and_ingest,
    migrate_wiki_to_subdirs,
)
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Run specific regression tests**

Run: `python -m pytest tests/test_wiki_engine.py tests/test_wiki_lint.py tests/test_graph_data.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_wiki_engine.py
git commit -m "test: update imports and run full regression for ingest workflow"
```

---

## Spec Compliance Matrix

| Original Spec Requirement | Task | Status |
|--------------------------|------|--------|
| 五步编排 discussion→candidate→deep_review→write_plan→execute | T11 | ✅ |
| 讨论阶段输入包含 index/catalog + slug 列表 | T3 | ✅ |
| IngestCandidate 数据结构 (kind/path/title/reason/confidence/default_selected/action_hint) | T2 | ✅ |
| IngestWriteAction 含 source_check action | T2, T5, T8 | ✅ |
| IngestWritePlan 含 user_focus + referenced_source_summaries | T2 | ✅ |
| 候选/抽取阶段输入含 source + index + slug + 聊天历史 | T9 | ✅ |
| 深读仅选中页；浅页/冲突/用户要求时读 source summary | T9 | ✅ |
| 超预算按批次 Plan Review | T9 | ✅ |
| WIKI_DEEP_READ_MAX 限制深读页数 | T9 | ✅ |
| Plan Review 输出 IngestWritePlan；确认后不重新抽取 | T11 | ✅ |
| Merge 保持逐页 LLM | T8 | ✅ |
| [READY_TO_INGEST]后展示候选,支持 默认/全部/编号/排除 | T10 | ✅ |
| 写入计划展示 新增/修改/轻关联/跳过/需要源检查 | T10 | ✅ |
| 确认后才写入;取消不落盘 | T11 | ✅ |
| _pick_index_candidates Python 词面打分 | T4 | ✅ |
| 不新增 UI 控制码,继续 __READY__/__DONE__/__ERROR__ | T11,T13 | ✅ |
| discuss_and_ingest 签名不变 | T11 | ✅ |
| ingest_note 保持兼容,内部复用 _execute_write_plan | T12 | ✅ |
| 函数名 _build_ingest_extract_messages / _build_write_plan | T9 | ✅ |
| wiki_scope 参数预留 + 测试占位 | T3,T4,T6,T8,T9 | ✅ |
| 默认不读 raw notes/ | T5 prompt | ✅ |
| 单页 merge 失败隔离 | T8 | ✅ |
| Source summary 总是创建/覆盖 | T11 | ✅ |
| 回归测试通过 | T14 | ✅ |

## Summary

| Task | What | LLM calls | Files |
|------|------|-----------|-------|
| 1 | Budget config constants | — | `config.py` |
| 2 | Data structures | — | `wiki_engine.py` |
| 3 | Update discuss prompt + messages with index/slug | — | `prompts.py`, `wiki_engine.py` |
| 4 | `_pick_index_candidates` | — | `wiki_engine.py` |
| 5 | New prompts (candidate + plan with source_check) | — | `prompts.py` |
| 6 | `_collect_related_source_summaries` | — | `wiki_engine.py` |
| 7 | JSON parsers | — | `wiki_engine.py` |
| 8 | `_execute_write_plan` (5 actions + related_map) | — | `wiki_engine.py` |
| 9 | `_build_ingest_extract_messages` + `_build_write_plan` (batched) | — | `wiki_engine.py` |
| 10 | Display formatters + user selection parser (+源) | — | `wiki_engine.py` |
| 11 | `discuss_and_ingest` 5-step refactor | +2+ (candidates + batched plans) | `wiki_engine.py` |
| 12 | `ingest_note` refactor | — | `wiki_engine.py` |
| 13 | UI verification | — | `main_window.py` |
| 14 | Regression suite | — | tests |

**Queue protocol:** No new control codes. `__READY__` fires once at plan confirmation. `__DONE__`/`__ERROR__` unchanged.
