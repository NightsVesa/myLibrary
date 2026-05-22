# LLM Wiki Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-powered wiki knowledge base capabilities to the desktop-pet app — when notes are saved, the LLM incrementally builds a structured wiki; users can ask natural-language questions answered from the wiki.

**Architecture:** Three-layer design from `docs/llm-wiki.md`: raw sources (`notes/`) are immutable, the LLM maintains a generated wiki layer (`wiki/`) with summaries + index + log, and a schema prompt governs the LLM's behavior. The LLM client is a thin `httpx` wrapper targeting OpenAI-compatible APIs (works with OpenAI, DeepSeek, Ollama, Groq, LM Studio). A new "问答" (Chat) panel in the pet sidebar provides the Q&A interface.

**Tech Stack:** Python 3.12+, `httpx` (new dependency), OpenAI-compatible chat completions API, tkinter threading via `queue.Queue` + `root.after()` polling.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `llm/__init__.py` | Package marker |
| Create | `llm/client.py` | Thin OpenAI-compatible chat completions client (sync + streaming) |
| Create | `llm/prompts.py` | System prompt templates for ingest / query |
| Create | `llm/wiki_engine.py` | Ingest and query orchestration |
| Create | `ui/chat_tab.py` | 问答 panel — chat history + input + streaming display |
| Modify | `config.py` | Add `WIKI_DIR`, `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` |
| Modify | `ui/main_window.py:43-47` | Add 4th ACTIONS entry + Ctrl+4 binding + chat icon |
| Modify | `ui/input_tab.py:49-62` | After save, offer background wiki ingest |
| Modify | `ui/upload_tab.py:121-139` | After save, offer background wiki ingest |
| Create | `tests/test_llm_client.py` | Unit tests for LLM client (mocked HTTP) |
| Create | `tests/test_wiki_engine.py` | Unit tests for ingest/query logic (mocked LLM) |

---

### Task 1: Config — LLM and Wiki Settings

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path

def test_wiki_dir_exists():
    import config
    assert config.WIKI_DIR.exists()
    assert config.WIKI_DIR.is_dir()

def test_llm_config_has_defaults():
    import config
    assert isinstance(config.LLM_API_BASE, str)
    assert isinstance(config.LLM_API_KEY, str)
    assert isinstance(config.LLM_MODEL, str)
    assert len(config.LLM_API_BASE) > 0
    assert len(config.LLM_MODEL) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `config` has no `WIKI_DIR`, `LLM_API_BASE`, etc.

- [ ] **Step 3: Implement config additions**

Edit `config.py` to add after line 6:

```python
import os

WIKI_DIR = BASE_DIR / "wiki"
WIKI_DIR.mkdir(exist_ok=True)

LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests to check no regression**

Run: `python -m pytest tests/ -v`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add LLM and wiki config settings"
```

---

### Task 2: LLM Client — Thin OpenAI-Compatible Wrapper

**Files:**
- Create: `llm/__init__.py`
- Create: `llm/client.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_client.py
import json
import pytest
from unittest.mock import patch, MagicMock

from llm.client import LLMConfig, Message, chat, chat_stream


def _make_config():
    return LLMConfig(
        api_base="https://fake.api/v1",
        api_key="test-key",
        model="test-model",
    )


def test_llm_config_is_immutable():
    cfg = _make_config()
    with pytest.raises(AttributeError):
        cfg.api_key = "new"


def test_message_is_immutable():
    m = Message(role="user", content="hello")
    with pytest.raises(AttributeError):
        m.content = "bye"


def test_chat_returns_string():
    cfg = _make_config()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello back!"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.client.httpx.post", return_value=mock_response):
        result = chat(cfg, [Message(role="user", content="hi")])
    assert result == "Hello back!"


def test_chat_sends_correct_headers():
    cfg = _make_config()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.client.httpx.post", return_value=mock_response) as mock_post:
        chat(cfg, [Message(role="user", content="test")])
    call_kwargs = mock_post.call_args
    assert "Authorization" in call_kwargs.kwargs.get("headers", {}) or \
           "Authorization" in call_kwargs[1].get("headers", {})


def test_chat_stream_yields_chunks():
    cfg = _make_config()
    lines = [
        b'data: {"choices":[{"delta":{"content":"He"}}]}',
        b'data: {"choices":[{"delta":{"content":"llo"}}]}',
        b'data: [DONE]',
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_lines.return_value = iter(lines)
    mock_response.raise_for_status = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("llm.client.httpx.stream", return_value=mock_response):
        chunks = list(chat_stream(cfg, [Message(role="user", content="hi")]))
    assert chunks == ["He", "llo"]


def test_chat_raises_on_empty_key():
    cfg = LLMConfig(api_base="https://fake.api/v1", api_key="", model="m")
    with pytest.raises(ValueError, match="API key"):
        chat(cfg, [Message(role="user", content="hi")])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: FAIL — `llm` package does not exist.

- [ ] **Step 3: Create package and implement client**

```python
# llm/__init__.py
```

```python
# llm/client.py
from dataclasses import dataclass
from typing import Generator

import httpx


@dataclass(frozen=True)
class LLMConfig:
    api_base: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Message:
    role: str
    content: str


_TIMEOUT = 60.0


def _validate(config: LLMConfig) -> None:
    if not config.api_key:
        raise ValueError("API key is not configured")


def _headers(config: LLMConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


def _body(config: LLMConfig, messages: list[Message], *, stream: bool) -> dict:
    return {
        "model": config.model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": stream,
    }


def chat(config: LLMConfig, messages: list[Message]) -> str:
    _validate(config)
    resp = httpx.post(
        f"{config.api_base}/chat/completions",
        headers=_headers(config),
        json=_body(config, messages, stream=False),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chat_stream(
    config: LLMConfig, messages: list[Message],
) -> Generator[str, None, None]:
    _validate(config)
    with httpx.stream(
        "POST",
        f"{config.api_base}/chat/completions",
        headers=_headers(config),
        json=_body(config, messages, stream=True),
        timeout=_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            if not raw_line.startswith("data: "):
                continue
            payload = raw_line[6:]
            if payload.strip() == "[DONE]":
                break
            import json
            chunk = json.loads(payload)
            delta = chunk["choices"][0].get("delta", {})
            text = delta.get("content", "")
            if text:
                yield text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add llm/__init__.py llm/client.py tests/test_llm_client.py
git commit -m "feat: add lightweight LLM client (OpenAI-compatible API)"
```

---

### Task 3: Prompt Templates

**Files:**
- Create: `llm/prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py
from llm.prompts import INGEST_SYSTEM, QUERY_SYSTEM


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `llm.prompts` does not exist.

- [ ] **Step 3: Implement prompt templates**

```python
# llm/prompts.py

INGEST_SYSTEM = """\
You are a wiki maintainer for a personal knowledge base.

When given a source note, you must:
1. Write a concise summary page in Markdown (100-300 words).
2. Extract key entities (people, concepts, tools, places) mentioned.
3. Note any connections to topics that might already exist in the wiki.

Output format — respond with EXACTLY this structure:
```
## Summary
<your markdown summary here>

## Entities
- entity1
- entity2

## Connections
- <connection note>
```

Rules:
- Write in the same language as the source note.
- Be factual — do not add information not present in the source.
- Keep it concise. The summary should capture the essential knowledge.
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

INDEX_ENTRY_TEMPLATE = "- [{title}]({filename}) — {summary}\n"
LOG_ENTRY_TEMPLATE = "## [{date}] {operation} | {title}\n{details}\n\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add llm/prompts.py tests/test_prompts.py
git commit -m "feat: add LLM prompt templates for ingest and query"
```

---

### Task 4: Wiki Engine — Ingest

**Files:**
- Create: `llm/wiki_engine.py`
- Create: `tests/test_wiki_engine.py`

- [ ] **Step 1: Write the failing tests for ingest**

```python
# tests/test_wiki_engine.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from llm.client import LLMConfig
from llm.wiki_engine import ingest_note, _parse_ingest_response, _update_index, _append_log


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


def test_parse_ingest_response_extracts_summary():
    raw = """## Summary
This is about Python testing.

## Entities
- pytest
- unittest

## Connections
- Related to CI/CD
"""
    result = _parse_ingest_response(raw)
    assert "Python testing" in result.summary
    assert "pytest" in result.entities
    assert len(result.entities) == 2


def test_parse_ingest_response_handles_minimal():
    raw = "## Summary\nShort note.\n\n## Entities\n- one\n\n## Connections\n- none"
    result = _parse_ingest_response(raw)
    assert "Short note" in result.summary
    assert result.entities == ["one"]


def test_update_index_creates_file(wiki_dir):
    _update_index(wiki_dir, "test_page.md", "Test Page", "A brief description")
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "Test Page" in index
    assert "test_page.md" in index


def test_update_index_appends(wiki_dir):
    _update_index(wiki_dir, "a.md", "Page A", "First page")
    _update_index(wiki_dir, "b.md", "Page B", "Second page")
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "Page A" in index
    assert "Page B" in index


def test_update_index_replaces_existing(wiki_dir):
    _update_index(wiki_dir, "a.md", "Page A", "Old description")
    _update_index(wiki_dir, "a.md", "Page A", "New description")
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert index.count("Page A") == 1
    assert "New description" in index


def test_append_log_creates_file(wiki_dir):
    _append_log(wiki_dir, "ingest", "My Note", "Created summary_of_my_note.md")
    log = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "My Note" in log


def test_ingest_note_creates_wiki_page(wiki_dir, notes_dir, config):
    note = notes_dir / "test.md"
    note.write_text("# Test\nSome content about AI.", encoding="utf-8")

    llm_response = """## Summary
This note discusses AI concepts.

## Entities
- AI

## Connections
- none
"""
    with patch("llm.wiki_engine.chat", return_value=llm_response):
        result = ingest_note(note, config, wiki_dir=wiki_dir)

    assert result.exists()
    assert result.parent == wiki_dir
    content = result.read_text(encoding="utf-8")
    assert "AI concepts" in content
    assert (wiki_dir / "index.md").exists()
    assert (wiki_dir / "log.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py -v`
Expected: FAIL — `llm.wiki_engine` does not exist.

- [ ] **Step 3: Implement wiki engine ingest**

```python
# llm/wiki_engine.py
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import config as app_config
from llm.client import LLMConfig, Message, chat
from llm.prompts import INGEST_SYSTEM, INDEX_ENTRY_TEMPLATE, LOG_ENTRY_TEMPLATE


@dataclass(frozen=True)
class IngestResult:
    summary: str
    entities: list[str]
    connections: list[str]


def _parse_ingest_response(raw: str) -> IngestResult:
    summary = ""
    entities: list[str] = []
    connections: list[str] = []
    current_section = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Summary"):
            current_section = "summary"
            continue
        elif stripped.startswith("## Entities"):
            current_section = "entities"
            continue
        elif stripped.startswith("## Connections"):
            current_section = "connections"
            continue

        if current_section == "summary":
            summary += line + "\n"
        elif current_section == "entities" and stripped.startswith("- "):
            entities.append(stripped[2:].strip())
        elif current_section == "connections" and stripped.startswith("- "):
            connections.append(stripped[2:].strip())

    return IngestResult(
        summary=summary.strip(),
        entities=entities,
        connections=connections,
    )


def _update_index(wiki_dir: Path, filename: str, title: str, summary: str) -> None:
    index_path = wiki_dir / "index.md"
    header = "# Wiki Index\n\n"
    entries: list[str] = []

    if index_path.exists():
        text = index_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("- [") and f"]({filename})" not in line:
                entries.append(line + "\n")
    
    one_line = summary.split("\n")[0][:80]
    entries.append(INDEX_ENTRY_TEMPLATE.format(
        title=title, filename=filename, summary=one_line,
    ))
    index_path.write_text(header + "".join(sorted(entries)), encoding="utf-8")


def _append_log(wiki_dir: Path, operation: str, title: str, details: str) -> None:
    log_path = wiki_dir / "log.md"
    header = "# Wiki Log\n\n"
    existing = ""
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        if existing.startswith(header):
            existing = existing[len(header):]

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = LOG_ENTRY_TEMPLATE.format(
        date=date, operation=operation, title=title, details=details,
    )
    log_path.write_text(header + entry + existing, encoding="utf-8")


def _wiki_filename(note_name: str) -> str:
    stem = Path(note_name).stem
    return f"summary_{stem}.md"


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

    messages = [
        Message(role="system", content=INGEST_SYSTEM),
        Message(
            role="user",
            content=f"Source note title: {title}\n\n---\n\n{source_text}",
        ),
    ]
    raw = chat(config, messages)
    result = _parse_ingest_response(raw)

    filename = _wiki_filename(note_path.name)
    page_path = wiki / filename

    frontmatter = (
        f"---\nsource: {note_path.name}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"entities: {result.entities}\n---\n\n"
    )
    page_path.write_text(
        frontmatter + f"# {title}\n\n{result.summary}\n",
        encoding="utf-8",
    )

    one_line = result.summary.split("\n")[0][:80]
    _update_index(wiki, filename, title, one_line)
    _append_log(wiki, "ingest", title, f"Created {filename}")

    return page_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_engine.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: wiki engine ingest — LLM summarises notes into wiki pages"
```

---

### Task 5: Wiki Engine — Query

**Files:**
- Modify: `llm/wiki_engine.py`
- Modify: `tests/test_wiki_engine.py`

- [ ] **Step 1: Write the failing tests for query**

Append to `tests/test_wiki_engine.py`:

```python
from llm.wiki_engine import query_wiki, _pick_relevant_pages


def test_pick_relevant_pages_by_keyword(wiki_dir):
    (wiki_dir / "summary_ai.md").write_text("# AI\nArtificial intelligence overview.", encoding="utf-8")
    (wiki_dir / "summary_cooking.md").write_text("# Cooking\nHow to make pasta.", encoding="utf-8")
    _update_index(wiki_dir, "summary_ai.md", "AI", "Artificial intelligence overview")
    _update_index(wiki_dir, "summary_cooking.md", "Cooking", "How to make pasta")

    pages = _pick_relevant_pages("artificial intelligence", wiki_dir=wiki_dir, top_n=5)
    filenames = [p.name for p in pages]
    assert "summary_ai.md" in filenames


def test_pick_relevant_pages_returns_max_n(wiki_dir):
    for i in range(10):
        name = f"page_{i}.md"
        (wiki_dir / name).write_text(f"# Page {i}\nCommon keyword here.", encoding="utf-8")
        _update_index(wiki_dir, name, f"Page {i}", "Common keyword here")

    pages = _pick_relevant_pages("common keyword", wiki_dir=wiki_dir, top_n=3)
    assert len(pages) <= 3


def test_query_wiki_returns_generator(wiki_dir, config):
    (wiki_dir / "index.md").write_text("# Wiki Index\n\n- [AI](summary_ai.md) — AI overview\n", encoding="utf-8")
    (wiki_dir / "summary_ai.md").write_text("# AI\nArtificial intelligence is ...", encoding="utf-8")

    chunks = ["This ", "is ", "the answer."]
    with patch("llm.wiki_engine.chat_stream", return_value=iter(chunks)):
        result = list(query_wiki("What is AI?", config, wiki_dir=wiki_dir))
    assert result == chunks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_engine.py::test_pick_relevant_pages_by_keyword tests/test_wiki_engine.py::test_query_wiki_returns_generator -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement query functions**

Add to `llm/wiki_engine.py` (add `chat_stream` import at top, add these functions):

```python
from llm.client import LLMConfig, Message, chat, chat_stream
from llm.prompts import INGEST_SYSTEM, QUERY_SYSTEM, INDEX_ENTRY_TEMPLATE, LOG_ENTRY_TEMPLATE

# ... existing code ...

def _pick_relevant_pages(
    question: str,
    *,
    wiki_dir: Path | None = None,
    top_n: int = 5,
) -> list[Path]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR
    index_path = wiki / "index.md"
    if not index_path.exists():
        return []

    q_words = set(question.lower().split())
    scored: list[tuple[float, Path]] = []

    for md in wiki.glob("summary_*.md"):
        text = md.read_text(encoding="utf-8").lower()
        hits = sum(1 for w in q_words if w in text)
        if hits > 0:
            scored.append((hits, md))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [path for _, path in scored[:top_n]]


def query_wiki(
    question: str,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
) -> Generator[str, None, None]:
    wiki = wiki_dir if wiki_dir is not None else app_config.WIKI_DIR

    pages = _pick_relevant_pages(question, wiki_dir=wiki)
    if not pages:
        yield "Wiki is empty — no pages to search."
        return

    context_parts: list[str] = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        context_parts.append(f"=== {p.name} ===\n{text}\n")
    context = "\n".join(context_parts)

    messages = [
        Message(role="system", content=QUERY_SYSTEM),
        Message(
            role="user",
            content=f"Wiki pages:\n\n{context}\n\n---\n\nQuestion: {question}",
        ),
    ]
    yield from chat_stream(config, messages)
```

Also add import at the top of the file:
```python
from typing import Generator
```

- [ ] **Step 4: Run all wiki engine tests**

Run: `python -m pytest tests/test_wiki_engine.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add llm/wiki_engine.py tests/test_wiki_engine.py
git commit -m "feat: wiki engine query — keyword page selection + streaming LLM answer"
```

---

### Task 6: Chat Tab UI

**Files:**
- Create: `ui/chat_tab.py`

This task builds the 问答 panel. It displays a scrollable chat history with user and assistant messages, an input field, and a send button. LLM calls run in a background thread; streamed chunks are polled from a `queue.Queue` via `root.after()`.

- [ ] **Step 1: Create `ui/chat_tab.py`**

```python
# ui/chat_tab.py
import queue
import threading
import tkinter as tk

from llm.client import LLMConfig, Message
from llm.wiki_engine import query_wiki
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, SKY_DARK, SKY_PALE, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_HINT, FONT_INPUT,
    cartoon_label, cartoon_entry, CartoonButton,
)
import config as app_config


class ChatTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._streaming = False
        self._build()

    def _build(self) -> None:
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        cartoon_label(self.frame, "向知识库提问", kind="hint").grid(
            row=0, column=0, sticky="w", padx=2, pady=(4, 2),
        )

        # Chat history — scrollable text widget
        hist_border = tk.Frame(self.frame, bg=self._edge)
        hist_border.grid(row=1, column=0, sticky="nsew", padx=2)
        hist_inner = tk.Frame(hist_border, bg=self._bg)
        hist_inner.pack(fill="both", expand=True, padx=2, pady=(2, 3))

        hist_scroll = tk.Scrollbar(hist_inner, orient="vertical")
        self.history = tk.Text(
            hist_inner, wrap=tk.WORD, font=FONT_BODY,
            yscrollcommand=hist_scroll.set, state=tk.DISABLED,
            bg=self._bg, fg=TEXT_MAIN,
            relief="flat", borderwidth=0, highlightthickness=0,
            padx=8, pady=6,
        )
        hist_scroll.config(command=self.history.yview)
        self.history.pack(side="left", fill="both", expand=True)
        hist_scroll.pack(side="right", fill="y")

        self.history.tag_config("user_name", foreground=SKY_DARK,
                                font=("幼圆", 10, "bold"))
        self.history.tag_config("assistant_name", foreground="#e88a3a",
                                font=("幼圆", 10, "bold"))
        self.history.tag_config("error", foreground="#cc4444",
                                font=("幼圆", 10, "italic"))
        self.history.tag_config("meta", foreground=TEXT_LIGHT,
                                font=("幼圆", 9))

        # Input row
        input_row = tk.Frame(self.frame, bg=self._bg)
        input_row.grid(row=2, column=0, sticky="ew", padx=2, pady=(6, 4))
        input_row.grid_columnconfigure(0, weight=1)

        self.q_border = cartoon_entry(
            input_row, placeholder="输入你的问题...",
            border_color=self._edge,
        )
        self.q_border.grid(row=0, column=0, sticky="ew")
        self.q_border.entry.bind("<Return>", lambda _e: self._on_send())

        CartoonButton(
            input_row, "💬", command=self._on_send,
            kind="orange", width=52, height=40,
        ).grid(row=0, column=1, padx=(6, 0), sticky="e")

    def _append_text(self, text: str, tag: str = "") -> None:
        self.history.config(state=tk.NORMAL)
        if tag:
            self.history.insert(tk.END, text, tag)
        else:
            self.history.insert(tk.END, text)
        self.history.config(state=tk.DISABLED)
        self.history.see(tk.END)

    def _on_send(self) -> None:
        if self._streaming:
            return
        entry = self.q_border.entry
        if getattr(entry, "_is_placeholder", False):
            return
        question = entry.get().strip()
        if not question:
            return
        entry.delete(0, tk.END)

        self._append_text("You: ", "user_name")
        self._append_text(question + "\n\n")

        if not app_config.LLM_API_KEY:
            self._append_text(
                "Please set LLM_API_KEY environment variable first.\n\n",
                "error",
            )
            return

        self._append_text("Assistant: ", "assistant_name")
        self._streaming = True

        llm_config = LLMConfig(
            api_base=app_config.LLM_API_BASE,
            api_key=app_config.LLM_API_KEY,
            model=app_config.LLM_MODEL,
        )
        thread = threading.Thread(
            target=self._stream_worker,
            args=(question, llm_config),
            daemon=True,
        )
        thread.start()
        self._poll_queue()

    def _stream_worker(self, question: str, config: LLMConfig) -> None:
        try:
            for chunk in query_wiki(question, config):
                self._queue.put(chunk)
        except Exception as exc:
            self._queue.put(f"\n[Error: {exc}]")
        self._queue.put(None)

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if item is None:
                    self._append_text("\n\n")
                    self._streaming = False
                    return
                self._append_text(item)
        except queue.Empty:
            pass
        self.frame.after(50, self._poll_queue)
```

- [ ] **Step 2: Verify the module imports correctly**

Run: `python -c "from ui.chat_tab import ChatTab; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ui/chat_tab.py
git commit -m "feat: chat tab UI with streaming LLM responses"
```

---

### Task 7: Wire Chat Tab Into Main Window

**Files:**
- Modify: `ui/main_window.py`

- [ ] **Step 1: Add import for ChatTab**

At `ui/main_window.py:21` (after the SearchTab import), add:

```python
from ui.chat_tab import ChatTab
```

- [ ] **Step 2: Add 4th action to ACTIONS list**

Change the ACTIONS list (line 43-47) from:

```python
ACTIONS = [
    ("输入", "📖", InputTab,  "Ctrl+1", SKY_PRIMARY, SKY_DARK,  "#e8f4ff", "#a8d4f4"),
    ("上传", "📁", UploadTab, "Ctrl+2", MINT,        "#3db88a", "#ebfaf3", "#a8eedd"),
    ("搜索", "🔍", SearchTab, "Ctrl+3", LAVENDER,    "#7a5acc", "#f3eefc", "#d8cefa"),
]
```

to:

```python
ACTIONS = [
    ("输入", "📖", InputTab,  "Ctrl+1", SKY_PRIMARY, SKY_DARK,  "#e8f4ff", "#a8d4f4"),
    ("上传", "📁", UploadTab, "Ctrl+2", MINT,        "#3db88a", "#ebfaf3", "#a8eedd"),
    ("搜索", "🔍", SearchTab, "Ctrl+3", LAVENDER,    "#7a5acc", "#f3eefc", "#d8cefa"),
    ("问答", "💬", ChatTab,   "Ctrl+4", ORANGE,      "#dba42a", "#fff8e0", "#ffe4a8"),
]
```

- [ ] **Step 3: Add Ctrl+4 shortcut binding**

At line ~410 (after the `Control-Key-3` binding), add:

```python
root.bind_all("<Control-Key-4>", lambda _e: self._shortcut_open(3))
```

- [ ] **Step 4: Add chat bubble icon to `_draw_white_icon`**

In the `_draw_white_icon` function (around line 88), add a new `elif` branch before the `else`:

```python
    elif kind == "💬":
        # Chat bubble — rounded rectangle body + small triangle tail
        bx1, by1 = cx - 12, cy - 10
        bx2, by2 = cx + 12, cy + 6
        canvas.create_polygon(
            bx1 + 4, by1,  bx2 - 4, by1,  bx2, by1,
            bx2, by1 + 4,  bx2, by2 - 4,  bx2, by2,
            bx2 - 4, by2,  bx1 + 4, by2,  bx1, by2,
            bx1, by2 - 4,  bx1, by1 + 4,  bx1, by1,
            smooth=True, fill=color, outline="",
        )
        # Tail
        canvas.create_polygon(
            cx - 4, by2, cx + 2, by2, cx - 6, by2 + 7,
            fill=color, outline="",
        )
        # Three dots inside the bubble
        for dx in (-5, 0, 5):
            canvas.create_oval(
                cx + dx - 2, cy - 4, cx + dx + 2, cy,
                fill="#cfe7ff", outline="",
            )
```

- [ ] **Step 5: Verify the app launches**

Run: `python app.py`
Expected: Pet appears, sidebar now shows 4 buttons. Ctrl+4 opens the orange 问答 panel.

- [ ] **Step 6: Commit**

```bash
git add ui/main_window.py
git commit -m "feat: wire chat tab into main window — 4th sidebar action with Ctrl+4"
```

---

### Task 8: Hook Ingest Into Save Flow

**Files:**
- Modify: `ui/input_tab.py`
- Modify: `ui/upload_tab.py`

Both tabs should offer background wiki ingest after a successful save. The ingest runs in a daemon thread so the UI stays responsive. If the API key is not set, ingest is silently skipped (no error — the feature is optional).

- [ ] **Step 1: Create a shared ingest helper**

Create a small helper in `llm/wiki_engine.py` that can be called from any tab. Add to the end of `llm/wiki_engine.py`:

```python
def background_ingest(note_path: Path, root: "tk.Tk | None" = None) -> None:
    if not app_config.LLM_API_KEY:
        return
    config = LLMConfig(
        api_base=app_config.LLM_API_BASE,
        api_key=app_config.LLM_API_KEY,
        model=app_config.LLM_MODEL,
    )

    def _worker():
        try:
            ingest_note(note_path, config)
        except Exception:
            pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
```

Add `import threading` at the top of `llm/wiki_engine.py`.

- [ ] **Step 2: Hook into InputTab**

In `ui/input_tab.py`, add import at top:

```python
from llm.wiki_engine import background_ingest
```

In `_on_save`, after `path = save_note(md, title=title)` and before the Messagebox, add:

```python
        background_ingest(path)
```

- [ ] **Step 3: Hook into UploadTab**

In `ui/upload_tab.py`, add import at top:

```python
from llm.wiki_engine import background_ingest
```

In `_on_save`, after `path = save_note(md, title=title)` and before the Messagebox, add:

```python
            background_ingest(path)
```

- [ ] **Step 4: Hook into drag-and-drop**

In `ui/main_window.py`, add import at top (after existing imports):

```python
from llm.wiki_engine import background_ingest
```

In `_on_files_dropped`, inside the `try` block after `ok.append(saved)`, add:

```python
                background_ingest(saved)
```

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 6: Manual test — save a note and check wiki/**

1. Set `LLM_API_KEY` environment variable.
2. Run `python app.py`, open 输入 panel, type a note, save.
3. Check `wiki/` directory — should contain a summary page, `index.md`, `log.md`.

- [ ] **Step 7: Commit**

```bash
git add llm/wiki_engine.py ui/input_tab.py ui/upload_tab.py ui/main_window.py
git commit -m "feat: auto-ingest saved notes into wiki (background thread)"
```

---

### Task 9: CLAUDE.md Documentation Update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add LLM wiki section to CLAUDE.md**

Append the following section after the "### File upload (and drag-and-drop)" section:

```markdown
### LLM wiki layer

Three-layer architecture from `docs/llm-wiki.md`:
- **Raw sources** (`notes/`) — immutable user notes, same as before.
- **Wiki** (`wiki/`) — LLM-generated summary pages, `index.md` (catalog), `log.md` (chronological). The LLM owns this directory; users read it.
- **Schema** — prompt templates in `llm/prompts.py` govern the LLM's behavior.

`llm/client.py` is a thin wrapper around `httpx` targeting any OpenAI-compatible chat completions endpoint. Configuration: `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` (env vars, defaults in `config.py`). Works with OpenAI, DeepSeek, Ollama, Groq, LM Studio.

**Ingest**: `llm/wiki_engine.ingest_note(path)` reads a note, calls the LLM to generate a summary, writes `wiki/summary_<stem>.md`, updates `wiki/index.md` and `wiki/log.md`. Triggered automatically on save (input, upload, drag-and-drop) via `background_ingest()` in a daemon thread. Silently skipped if `LLM_API_KEY` is empty.

**Query**: `llm/wiki_engine.query_wiki(question)` picks relevant wiki pages by keyword overlap, sends them + the question to the LLM, and streams the response. Used by `ui/chat_tab.ChatTab` (the 4th sidebar panel, Ctrl+4, orange theme).

**Threading**: LLM calls never block the tkinter main loop. `ChatTab` uses `queue.Queue` + `root.after(50, poll)` to stream chunks into the text widget. `background_ingest` uses a fire-and-forget daemon thread.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add LLM wiki layer architecture to CLAUDE.md"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: All three operations from `docs/llm-wiki.md` (ingest, query, lint) are addressed — ingest and query are implemented, lint is deferred as a future enhancement (per the lightweight requirement).
- [x] **Placeholder scan**: No TBD/TODO/placeholder steps. All code is complete.
- [x] **Type consistency**: `LLMConfig`, `Message`, `IngestResult` types are used consistently across tasks. `chat` / `chat_stream` / `query_wiki` / `ingest_note` signatures match between test and implementation code.
- [x] **No breaking changes**: Existing grep search, note storage, and upload flows remain intact. LLM features are additive and gracefully degrade when API key is not set.
- [x] **Lightweight**: Single new dependency (`httpx`). No vector DB, no embedding model, no agent framework. Simple keyword-based page selection for queries. Background threads for async.
