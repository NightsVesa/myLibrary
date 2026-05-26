# Ingest Discussion — Design Spec

**Goal:** During file ingest, the LLM discusses key findings with the user in a chat interface before proceeding to formal extraction and merge. The user can guide what to emphasize, correct misinterpretations, and ask questions — before any wiki pages are written.

**Status:** Approved. Ready for implementation plan.

---

## Flow

```
User drops/upload file
  │
  ├─ 1. Save file to notes/          (existing, unchanged)
  ├─ 2. Pet eat animation starts     (existing, unchanged)
  ├─ 3. Read source file content     (existing _read_note_source)
  │
  ├─ 4. [NEW] Discussion phase
  │   ├─ Chat panel opens (ChatTab-style UI)
  │   ├─ LLM opens with summary of key findings, asks for feedback
  │   ├─ User responds in natural language
  │   ├─ LLM adjusts understanding, continues discussion
  │   ├─ Loop until LLM marks [READY_TO_INGEST]
  │   └─ User clicks "确认提取" button
  │
  ├─ 5. Formal extract + merge       (existing ingest_note, unchanged)
  │
  └─ 6. Toast "Wiki 更新完成"        (existing, unchanged)
```

---

## Components

### 1. `INGEST_DISCUSS_SYSTEM` prompt (`llm/prompts.py`)

New system prompt that instructs the LLM to:
- Read the source document and extract key themes, entities, concepts
- Present findings to the user in a conversational way
- Ask the user what to emphasize, what to ignore, what to correct
- When discussion is sufficient, append `[READY_TO_INGEST]` to the end of the message
- Keep replies concise (2-4 sentences each). Write in the source's language.

### 2. `discuss_and_ingest()` generator (`llm/wiki_engine.py`)

A new generator function that orchestrates the discussion → extract → merge pipeline:

```python
def discuss_and_ingest(
    note_path: Path,
    config: LLMConfig,
    *,
    wiki_dir: Path | None = None,
    chat_q: queue.Queue[str | None],      # → UI: LLM messages
    user_q: queue.Queue[str],              # ← UI: user replies
) -> Generator[LintFinding, None, None]:   # ...existing
```

States:
- **DISCUSSING**: read source, send to LLM via chat_stream, yield each user-visible message to chat_q. Wait for user reply from user_q.
- **WAITING_FOR_USER**: LLM emitted `[READY_TO_INGEST]`. Block on user_q for confirmation.
- **INGESTING**: Run existing `ingest_note()`. Send status messages to chat_q.
- **DONE**: Send None to chat_q.

### 3. Ingest chat panel (`ui/main_window.py`)

`_open_ingest_chat(paths)` method on MainWindow:
- Opens a new Toplevel panel (NOT a sidebar-tab — it's tied to a specific ingest session)
- Reuses ChatTab's UI layout: scrollable text widget + input entry + send button
- Two queues bridge the thread:
  - `chat_q`: worker thread sends LLM text chunks → main thread appends to text widget
  - `user_q`: main thread sends user input → worker thread reads
- Panel title shows source filename
- "确认提取" button appears when `[READY_TO_INGEST]` is detected
- Panel auto-closes when ingest completes, replaced by toast

### 4. Backward compatibility

- Ctrl+4 (ChatTab) is unaffected — it's a separate panel for Q&A
- `background_ingest()` is unchanged — when called directly (no UI context), it skips discussion
- Drop multiple files: discuss each one sequentially in the same panel

---

## Files

| File | Action | Changes |
|------|--------|---------|
| `llm/prompts.py` | Modify | Add `INGEST_DISCUSS_SYSTEM` |
| `llm/wiki_engine.py` | Modify | Add `discuss_and_ingest()` |
| `ui/main_window.py` | Modify | Add `_open_ingest_chat()`, modify `_ingest_with_animation` |
| `tests/test_wiki_engine.py` | Modify | Add discussion tests |

`llm/client.py`, `ui/chat_tab.py`, `storage/note_store.py` — unchanged.

---

## Edge cases

- **API key missing**: Skip discussion, fall back to silent background ingest
- **LLM fails during discussion**: Show error in chat panel, offer "重试" / "跳过讨论直接提取"
- **User closes panel mid-discussion**: Cancel ingest (source was already saved to notes/, but no wiki pages written yet)
- **Multi-file drop**: Process sequentially — discuss file 1 → ingest → discuss file 2 → ingest
- **Discussion times out**: If user doesn't respond for 5 minutes, auto-proceed with ingest (configurable)
