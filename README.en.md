# Knowledge Base Assistant

English | [简体中文](README.md)

A Windows desktop-pet knowledge base app. A floating triceratops sprite stays on top of the desktop; hover over it to reveal a sidebar for note input, file upload, search, Q&A, graph view, and wiki health checks. It combines local Markdown notes, an LLM-maintained wiki, and LLM-powered Q&A for personal knowledge management.

## Pet Preview

The actual pet sprites used by the app live in `assets/`. At runtime, Windows transparent color `#ff00ff` is used to key out the background. The images below are white-background previews exported from the same sprites so the README does not show the magenta transparency key.

<p>
  <img src="assets/readme_pet_idle.png" width="150" alt="idle pet">
  <img src="assets/readme_pet_happy.png" width="150" alt="happy pet">
  <img src="assets/readme_pet_eat.png" width="150" alt="eat pet">
  <img src="assets/readme_pet_attack.png" width="150" alt="attack pet">
  <img src="assets/readme_pet_sleep.png" width="150" alt="sleep pet">
</p>

| State | White-background preview |
| --- | --- |
| Idle | <img src="assets/readme_pet_idle.png" width="120" alt="idle frame"> |
| Happy | <img src="assets/readme_pet_happy.png" width="120" alt="happy frame"> |
| Eating | <img src="assets/readme_pet_eat.png" width="120" alt="eat frame"> |
| Attack / Dragging | <img src="assets/readme_pet_attack.png" width="120" alt="attack frame"> |
| Sleeping | <img src="assets/readme_pet_sleep.png" width="120" alt="sleep frame"> |

## Features

- Desktop pet entry point: always on top, transparent background, draggable, with sleep and click animations.
- Quick note capture: save text as Markdown files under `notes/`.
- File import: supports `.md`, `.docx`, `.pdf`, and common image formats. Uploads and drag-and-drop use the same save pipeline.
- Optional OCR: with PaddleOCR installed, text from images, scanned pages, and document screenshots can be added to Markdown and wiki content.
- Local search: full-text search over Markdown files under `notes/`, with tags, favorites, recent items, and a reader preview.
- LLM wiki: compiles raw notes into `wiki/` pages for sources, entities, concepts, index, and log.
- Q&A panel: retrieves wiki context and streams answers from an OpenAI-compatible LLM endpoint.
- Knowledge graph: visualizes relationships between wiki pages, with filters, path finding, and quality signals.
- Wiki health check: finds orphan pages, broken links, index drift, duplicates, and maintenance issues.

## Installation

This project targets Windows desktop usage. Python 3.10+ is recommended.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The primary dependency file is `requirements.txt`. A same-content compatibility alias, `requirement.txt`, is also provided.

OCR support is large and is not included in the base source install:

```bash
pip install paddleocr paddlepaddle
```

`reportlab` is only used by one PDF test. If it is not installed, that test is skipped.

## LLM Configuration

Copy the template and fill in your local credentials:

```bash
copy .env.template .env
```

Example:

```env
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
```

Any OpenAI-compatible endpoint can be used, such as DeepSeek, SenseNova, Ollama, Groq, or LM Studio. If `LLM_API_KEY` is empty or missing, LLM features such as wiki ingest and Q&A are silently disabled; the rest of the local app still works.

## Common Commands

```bash
# Run the app
python app.py

# Run all tests
python -m pytest tests/

# Run one test file or one test
python -m pytest tests/test_wiki_engine.py -v
python -m pytest tests/test_grep_search.py::test_case_insensitive -v

# Build the lightweight Windows app, output to dist/myLibrary/
pyinstaller build.spec --noconfirm

# Build the OCR Windows app, output to dist/myLibrary-OCR/
pyinstaller build_ocr.spec --noconfirm
```

## Release 2.0

Release 2.0 provides two Windows one-folder zip packages:

| Package | OCR | Best for |
| --- | --- | --- |
| `myLibrary-release2.0-lite-windows.zip` | Not included | Notes, search, wiki, Q&A, graph, and health checks with a smaller download |
| `myLibrary-release2.0-ocr-windows.zip` | Includes PaddleOCR, PaddlePaddle, and Chinese OCR models | Image OCR, scanned PDF OCR, and OCR from images inside documents |

After extracting, run:

```text
myLibrary/myLibrary.exe
myLibrary-OCR/myLibrary-OCR.exe
```

Packaged app behavior:

- `assets/` is bundled into `_internal` and contains the actual pet frames used by the app.
- `notes/`, `wiki/`, and `.env` live next to the exe so users can write and migrate their data.
- The lightweight package does not bundle PaddleOCR / paddlepaddle. The OCR package includes Chinese detection, recognition, and angle-classification models, so users do not need to install OCR dependencies manually.
- On first OCR use, if the model path contains non-ASCII characters, the OCR package copies the bundled models to an ASCII cache path such as `C:\ProgramData\myLibrary\paddleocr\`. This avoids Paddle failing to open model files from Chinese paths.

## Directory Layout

```text
assets/       Pet sprites and UI assets
converter/    DOCX/PDF/Markdown/OCR conversion
llm/          LLM client, wiki engine, prompts, linting, graph data
notes/        Raw user notes, locally writable, not committed by default
search/       Local full-text search
storage/      Note saving and lightweight metadata
tests/        pytest tests
ui/           Tkinter panels, widgets, search reader, chat, and graph UI
wiki/         LLM-maintained wiki output, locally writable, not committed by default
```

## Wiki Workflow

The knowledge base has three layers:

- `notes/`: raw source material and the source of truth.
- `notes/.note_meta.json`: local organization metadata for tags, favorites, and recently opened notes. It is not written into Markdown note bodies.
- `wiki/`: the LLM-maintained compiled layer, including source summaries, entity pages, concept pages, `index.md`, and `log.md`.
- Schema and prompts: `AGENTS.md` and `llm/prompts.py` define how the LLM writes, queries, and maintains the wiki.

Queries first read `wiki/index.md` to find candidate pages, then read candidate wiki pages and one-hop `## Related` pages. By default, raw `notes/` content is not read. Raw notes are only sampled as supporting evidence when the user explicitly asks for source text, raw text, verification against the original, verbatim content, or page-specific checks.

## Development Notes

- The UI uses multiple transparent `Toplevel` layers: pet, sidebar, panel, and reader.
- Panel themes come from `ACTIONS` in `ui/main_window.py`.
- Animation is centralized in `MainWindow._tick()`. Do not add separate per-state `after()` loops.
- Supported upload formats are centralized in `SUPPORTED` in `ui/upload_tab.py`; actual persistence goes through `save_supported_upload()`.
- Tags, favorites, and recently opened notes are managed by `storage/note_meta.py`. Typing `#tag` in the search box filters by tag.
- The Markdown renderer is handwritten in `ui/markdown_render.py` to avoid adding another Markdown dependency.
