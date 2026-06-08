# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows desktop-pet knowledge base. A floating triceratops sprite sits always-on-top on the desktop; hovering it reveals a 6-button sidebar (输入 / 上传 / 搜索 / 问答 / 图谱 / 体检) that opens themed glass panels for capturing notes, importing files, full-text-searching local Markdown files under `notes/`, LLM-powered Q&A over an auto-generated wiki, an interactive knowledge graph, and a wiki health-check tool.

## Commands

```bash
# Run the app (must run on Windows — uses wm_attributes("-transparentcolor"))
python app.py

# All tests
python -m pytest tests/

# Single test file / test
python -m pytest tests/test_note_store.py -v
python -m pytest tests/test_grep_search.py::test_case_insensitive -v

# Build exe (output: dist/知识库助手/)
pyinstaller build.spec --noconfirm
```

Required packages (no requirements.txt — install ad-hoc):
`ttkbootstrap`, `tkinterdnd2`, `python-docx`, `pdfplumber`, `Pillow`, `httpx`, `python-dotenv`, `pytest`. Optional: `reportlab` (only used by one PDF test — it skips if absent), `paddleocr` + `paddlepaddle` (OCR for images and scanned pages).

### LLM configuration

Create a `.env` file in the project root (gitignored). Any OpenAI-compatible endpoint works (DeepSeek, SenseNova, Ollama, Groq, LM Studio):
```
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
```
If `LLM_API_KEY` is empty or absent, LLM features (wiki ingest, chat Q&A) are silently disabled — the rest of the app works without it.

Advanced tuning (all via `.env`, sensible defaults in `config.py`): `LLM_TIMEOUT` (default 60s), `LLM_MAX_RETRIES` (2), `LLM_THINKING` (false — enable extended thinking for supported models), `WIKI_RETRIEVAL_TOP_N` (5), `WIKI_QUERY_TOP_N` (6), `WIKI_QUERY_CONTEXT_MAX_CHARS` (30000), `WIKI_MAX_EXTRACT_ITEMS` (15), `WIKI_LINT_STALE_DAYS` (90). See `config.py` for the full list.

## Architecture

### Entry and lifecycle

`app.py` → `ttk.Window(themename="cosmo")` → `TkinterDnD._require(root)` → `MainWindow(root)` → `root.mainloop()`. The root is the pet sprite itself: borderless (`overrideredirect`), always-on-top, and uses the `#ff00ff` transparent-color key to make the canvas around the sprite click-through. **Don't switch the root class** — `TkinterDnD._require(root)` patches the existing root in place to keep ttkbootstrap theming intact.

### The four Toplevel layers (pet → sidebar → panel → reader)

There are four kinds of windows, each a separate `Toplevel`, all using the `#ff00ff` transparent-color trick:

1. **Pet window** (the root) — `ui/main_window.MainWindow`. Owns sprite animation, drag, double-click-to-quit, sleep timer, global Ctrl+1/2/3/Esc shortcuts, and drop-target registration.
2. **Sidebar** — `ui/main_window._Sidebar`. One Toplevel containing all six action buttons drawn as Canvas vector items. Appears on pet hover, hides on hover-out.
3. **Panel** — themed glass card created by `MainWindow._toggle_panel`. The body is a PIL-generated rounded-rectangle PNG (`make_card_png` in `cartoon_widgets.py`) blitted onto a Canvas; title bar + close button are drawn as Canvas items on top of the PNG. Hosts an `InputTab` / `UploadTab` / `SearchTab` / `ChatTab` (frames embedded inside the panel). Panels opened via shortcut are *pinned* (mouse-out doesn't close them); panels opened via sidebar click are not. ChatTab is always pinned regardless.
4. **Reader** — `ui/search_tab._ReaderWindow`. Independent resizable Toplevel **parented on root, not on the panel** (so closing the panel doesn't destroy it). Uses Canvas items for chrome (no PIL PNG) so resize is cheap. Tracked on `root._active_reader` to enforce single-reader across `SearchTab` instances.

### Per-action theming

`ACTIONS` in `main_window.py` is a tuple of `(label, emoji, tab_class, hint, btn_body, btn_shadow, panel_pale_bg, panel_edge)`. Every visual element (sidebar button color, panel background, panel edge, tab content bg, widget borders) is driven by this single source. When adding a new tab, extend `ACTIONS` and pass `bg_color` + `edge_color` through to the tab constructor.

### Animation state machine

The sprite has 5 PNG frames (`assets/pet_{idle,attack,happy,sleep,eat}.png`) and 5 states. State transitions:
- press + drag > 4px → `attack` (with forward-lunge ease-out + shake)
- press without drag → `happy` for 1.2s (entrance pop + damped bounce) → back to `idle`
- file upload/ingest completes → `eat` (brief chomp animation) → back to `idle`
- no mouse activity for 30s → `sleep` (eased descent + slow breath)
- any mouse activity → wake to `idle`

A single `_tick` (`~33ms` / 30fps) reads `self._state` + `time.monotonic() - self._state_t0` and computes dx/dy via sin/decay math, then `canvas.coords()` the sprite. **Don't add per-state `after()` schedules** — keep all motion in `_tick`.

### Sprite generation (PIL chroma key)

Sprites are pre-rendered, **not generated at runtime**. The 4 frames live in `assets/pet_*.png` and are committed. They were sliced from `docs/ptes.png` (a 2×2 1536×1024 sprite sheet) by an inline PIL script that:
1. Crops each quadrant.
2. Uses the source's RGBA alpha channel (cutoff 40) to build a hard mask.
3. Keeps only the largest connected blob (kills stray dust/spark VFX from the original art).
4. Erodes 1px + multi-pass purple/dark-edge erosion to kill LANCZOS fringe colors against magenta.
5. Resizes everything to a uniform 235×180 canvas with magenta padding for the transparent-color key.

If sprites need regenerating, write a one-off script — see git history (commit before "完整阅读 md 文件" task) for the canonical version. Sprites must end with **pure `#ff00ff`** in the transparent regions; any near-magenta or dark fringe ruins the transparency effect.

### UI widget conventions

All cartoon UI primitives are in `ui/cartoon_widgets.py`:

- `cartoon_label(parent, ...)` — auto-inherits parent `bg`; use for any text label.
- `cartoon_entry(parent, ..., bg_color=None, border_color=SKY_LIGHT)` — bg defaults to parent's, border is themed.
- `cartoon_textarea(parent, ..., bg_color=None, border_color=SKY_LIGHT)` — same.
- `CartoonButton(parent, "💾 文字", command=..., kind="sky"|"mint"|"pink"|"orange")` — `kind` picks a body/shadow color pair. **Splits leading emoji from text** and renders them with separate fonts (`Segoe UI Emoji` for the emoji + `幼圆` for CJK) because `幼圆` has no emoji glyphs and would render `💾` as a missing-glyph box.

Fonts (defined in `cartoon_widgets.py`):
- `FONT_TITLE` / `FONT_HEADING` — `华文琥珀` (rounded display) for headings.
- `FONT_BODY` / `FONT_INPUT` — `幼圆` (soft rounded sans) for body / input text.
- `FONT_SHORTCUT` — `Comic Sans MS` for `Ctrl+N` pills.
- `FONT_MONO` — `Consolas` for file paths and code.

When drawing emoji + CJK text together in a single Canvas line, **always** split them and render with two separate `create_text` calls using two different fonts — never a single string with `Segoe UI Emoji` because that font lacks Chinese glyphs.

### Storage and search

- `storage/note_store.save_note(content, title=None, notes_dir=None)` — sanitizes title, auto-deduplicates filenames with `_1`, `_2` suffixes, writes UTF-8 `.md` to `config.NOTES_DIR`.
- `storage/note_meta.py` — stores lightweight local organization metadata in `notes/.note_meta.json`: tags, favorites, and recent opens. This metadata is not written into Markdown note bodies or wiki pages.
- `search/grep_search.search_notes(query, notes_dir=None)` — case-insensitive substring match across every `.md` file's contents. Returns `[{"file": Path, "snippet": str}]`. The return signature is the contract; UI layers depend on it. For LLM-powered semantic search, see the wiki layer below.

`SearchTab` also supports `#tag` queries: typing `#python` calls `list_by_tag()` instead of `search_notes()`. Quick-filter chips below the search bar let users switch between full-text results, recent notes (`list_recent`), and favorites (`list_favorites`).

### Markdown renderer

`ui/markdown_render.py` is a hand-rolled mini-parser (no `markdown` library dependency). `render_markdown_into(text_widget, source)` consumes a string and inserts pre-tagged spans into a `tk.Text`. Caller must pre-configure tags (`h1`–`h6`, `bold`, `italic`, `bold_italic`, `code`, `code_block`, `list_bullet`, `blockquote`, `blockquote_marker`, `hr`, `link`, `frontmatter`). Italic regex doesn't use `\w` lookbehind (Chinese chars are `\w` and would block matches); it uses `(?<!\*)\*(...)\*(?!\*)` instead.

`SearchTab` uses this for inline preview; `_ReaderWindow` re-uses the same renderer with larger fonts and adds `find_hit` / `find_current` tags driven by its own Ctrl+F bar. The reader also has a table-of-contents sidebar (parsed from ATX headings via `extract_markdown_headings`), a toolbar with back/forward navigation history, font-size +/−, TOC toggle, and favorite toggle. Tags and favorites are persisted via `storage/note_meta`.

### File upload (and drag-and-drop)

`ui/upload_tab.SUPPORTED` maps suffix → handler:
- `.docx` → `docx_to_markdown` (python-docx, heading-aware, with per-run image OCR)
- `.pdf` → `pdf_to_markdown` (pdfplumber, per-page `<!-- page N -->` markers; scanned pages trigger whole-page OCR)
- `.md` → `_md_passthrough` (reads Markdown and inserts OCR blocks for local image references when OCR is available)
- image suffixes (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp`) → `image_to_markdown`

`save_supported_upload(path)` is the unified save entry point for both upload and drag-and-drop. It decides per-format how to save: images and Markdown are converted to `.md` via `save_note()` so OCR text is searchable; DOCX/PDF are copied as raw files via `save_raw_file()` and converted during wiki ingest. Both `UploadTab._on_save()` and `MainWindow._on_files_dropped()` go through this function. OCR is optional: if `paddleocr`/`paddlepaddle` are absent, image-only uploads are rejected with a clear message, while DOCX/PDF/MD text import still works.

### LLM wiki layer

Three-layer architecture from `docs/llm-wiki.md`:
- **Raw sources** (`notes/`) — immutable user notes.
- **Wiki** (`wiki/`) — LLM-maintained pages organized in subdirectories:
  - `sources/summary_<stem>.md` — per-source summary
  - `entities/<slug>.md` — page about a person/tool/place/product
  - `concepts/<slug>.md` — page about an abstract idea or method
  - `index.md` — categorized catalog with `## Sources`, `## Entities`, `## Concepts` sections (links use relative paths like `sources/...`, `entities/...`, `concepts/...`)
  - `log.md` — chronological operation log
- **Schema** — prompt templates in `llm/prompts.py` (`INGEST_EXTRACT_SYSTEM`, `MERGE_PAGE_SYSTEM`, `QUERY_SYSTEM`).

`llm/client.py` is a thin `httpx` wrapper around any OpenAI-compatible chat completions endpoint. Configuration: `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` (env vars, defaults in `config.py`). Works with OpenAI, DeepSeek, Ollama, Groq, LM Studio.

**Ingest** (`llm/wiki_engine.ingest_note`) runs in two stages:

1. **Extract** — one LLM call receives the source note plus the current `index.md` catalog and an explicit list of existing entity/concept slugs, and returns a JSON document with `summary`, `entities`, `concepts`, and `update_targets`. LLM-proposed slugs are canonicalized against existing ones (`_canonical_slug` normalizes punctuation/case to prevent near-duplicate pages). If the JSON fails to parse, `_parse_extract` returns an empty `ExtractResult` and the source page is still written.
2. **Merge per page** — for every entity and concept in the extract result, one LLM call receives the page's existing markdown (if any) plus the new contribution from this source and returns the full updated page body. The orchestrator writes each page individually; a single page's failure is caught and isolated so the rest still proceed.

After all merges, `index.md` is rewritten from scratch by `_write_index` (no incremental edits — the on-disk state plus this run's new entries are the source of truth), and a log entry is appended. A typical source touches 5–15 pages and makes that many LLM calls. Ingest runs on a fire-and-forget daemon thread (`background_ingest`); silently skipped if `LLM_API_KEY` is empty.

**Query** (`llm/wiki_engine.query_wiki`) globs `sources/*.md`, `entities/*.md`, and `concepts/*.md` (plus legacy flat patterns), picks the top-N by keyword overlap with the question (`_tokenize` handles ASCII words + CJK bigrams), and streams the LLM's answer through `chat_stream`. Used by `ui/chat_tab.ChatTab` (the 4th sidebar panel, Ctrl+4, orange theme).

**Threading**: LLM calls never block the tkinter main loop. `ChatTab` uses `queue.Queue` + `root.after(50, poll)` to stream chunks into the text widget. `background_ingest` uses a fire-and-forget daemon thread.

**Lint** (`llm/wiki_lint.lint_wiki`) health-checks the wiki in two tiers:
- Static checks (zero LLM, <100ms): orphans, broken `## Related` links, duplicate index entries, index↔disk drift, heading format drift (`**Sources**` vs `## Sources`), empty links, stray files in wiki root.
- LLM check (1 call, ~2s): sends index + log + static findings to the LLM for gap analysis, stale content detection, and missing cross-reference suggestions.

Results include severity (`error`/`warn`/`info`), location, description, and fix suggestion. A log entry is appended to `log.md` after each run. Used by `ui/lint_tab.LintTab` (the 6th sidebar panel, Ctrl+6, red theme). Add new static checks to `wiki_lint.py:_check_*` ← `static_checks`; add LLM-specific checks to `llm_check`. `LintTab` follows the same `queue.Queue` + `root.after(50, poll)` streaming pattern as `ChatTab`.

### Knowledge graph

`llm/graph_data.py` parses `wiki/index.md` and the `## Related` sections inside wiki pages into a `Graph(nodes, edges)` dataclass. `Node` has `id`, `title`, `kind` (`source`/`entity`/`concept`), `summary`, `mtime`, and `exists` flag. `Edge` has `source`, `target`, `kind`, and `bidirectional` flag. The parser is pure logic with no tkinter dependency, so it's testable standalone.

`ui/graph_tab.py` renders the graph as a force-directed node-link diagram inside a standalone resizable Toplevel (`_GraphWindow`). Unlike other panels, the graph doesn't embed inside a panel — `GraphTab` is a sentinel class; `_toggle_panel` detects it and opens `_GraphWindow` directly. Key features:
- Force layout with `FORCE_ITERS` iterations + `DAMPING`, computed synchronously on reload.
- Node radius and color intensity scale by degree (connection count).
- Toolbar: search filter, kind toggles (source/entity/concept), min-degree slider, quality overlay, and path-finding mode.
- Detail panel: clicking a node shows its summary and neighbors.
- Relationship highlighting: selecting a node dims unrelated nodes/edges.
- Path mode: click two nodes to highlight the shortest path between them.
- Quality signals: orphan (no edges), missing (referenced but not on disk), and hub (high degree) overlays.
- Mtime caching: skips re-parsing `index.md` if mtime hasn't changed.

### Packaging (PyInstaller)

`build.spec` produces a one-folder bundle at `dist/知识库助手/` (~80 MB). Key decisions:
- `console=False` — no console window.
- `assets/` bundled inside `_MEIPASS`; `notes/`, `wiki/`, `.env` live next to the exe (user-writable).
- `config.py` switches paths via `sys.frozen` detection: `ASSETS_DIR` → `_MEIPASS/assets`, everything else → `Path(sys.executable).parent`.
- Aggressive `excludes` list (torch, numpy, scipy, matplotlib, pandas, sklearn, cv2, etc.) to keep the Anaconda-based bundle small. If a new dependency pulls in heavy transitive deps, add them to `excludes`.
- `tkinterdnd2/tkdnd` native DLLs are explicitly bundled via `datas`.
- Default PyInstaller builds do not bundle PaddleOCR/paddlepaddle; OCR is a source-run optional feature unless a separate OCR build profile is created.

## Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes.

### 1. Think Before Coding

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

- No features beyond what was asked.
- No abstractions for single-use code.
- No speculative "flexibility" or "configurability".
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Transform tasks into verifiable goals:
- "Add validation" -> write tests for invalid inputs, then make them pass
- "Fix the bug" -> write a test that reproduces it, then make it pass
- "Refactor X" -> ensure tests pass before and after

For multi-step tasks, state a brief plan:
```
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```
