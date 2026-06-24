# Knowledge Base Assistant 2.0: Zelda-Style UI Update

English | [简体中文](README.md)

A small triceratops still lives on your Windows desktop. In 2.0, it now opens a full knowledge-base control panel.

Version 1.0 focused on the desktop pet and lightweight transparent glass panels: hover, drag, input, upload, and search from the desktop. Version 2.0 keeps the pet entry point, but upgrades the main workspace into a Zelda / Sheikah-inspired React / WebView panel: deep navy ancient-tech patterns, cyan glowing borders, Hylia-style title typography, fixed top navigation, unified cards, streaming Q&A, knowledge graph, and wiki health checks in one more stable interface.

## 2.0 UI Upgrade

| 1.0 | 2.0 |
| --- | --- |
| Tkinter transparent glass panels for lightweight actions | React + Vite frontend, opened through WebView in packaged builds |
| Each feature behaves like a separate small window | Input, Upload, Search, Q&A, Graph, and Health share one title bar and navigation |
| Search and preview are mostly native local widgets | Zelda-style deep navy patterned background, cyan borders, glowing dividers, and card-based results |
| Wiki features are mostly behind the scenes | Ingest, Q&A, Graph, and Health Check are organized as a visible workflow |
| Feels like a desktop utility | Feels more like a personal knowledge workbench around local files |

This is not just a skin refresh. The new UI makes the workflow clearer: capture material -> compile wiki -> search and verify -> ask questions -> inspect graph and health.

## Real UI Preview

These are screenshots from the current version, not concept art.

<p>
  <img src="promo/zelda-ui-chat-reference.png" width="430" alt="Zelda-style chat panel">
  <img src="promo/zelda-ui-upload-reference.png" width="430" alt="Zelda-style upload and inbox panel">
</p>

The visual language comes from `zelda-hyrule-ui`: top navigation, Sheikah symbol, deep blue rune background, cyan glowing borders, Hylia Serif title styling, and muted cream text. The goal is not a generic tech dashboard; it is to make the desktop-pet knowledge base feel like a knowledge slate.

## UI Library Attribution

The Zelda / Sheikah-style panel components come from `zelda-hyrule-ui`:

- GitHub: [github.com/chaos-xxl/zelda-hyrule-ui](https://github.com/chaos-xxl/zelda-hyrule-ui)
- npm: [zelda-hyrule-ui](https://www.npmjs.com/package/zelda-hyrule-ui)
- Online docs: [chaos-xxl.github.io/zelda-hyrule-ui](https://chaos-xxl.github.io/zelda-hyrule-ui/)
- Current dependency: `zelda-hyrule-ui@^0.4.0`, declared in `frontend/package.json`.
- License: MIT, see `frontend/node_modules/zelda-hyrule-ui/LICENSE` after installing dependencies.

The library README states that it is an unofficial fan project inspired by *The Legend of Zelda: Breath of the Wild*, and that it is not affiliated with, endorsed by, or sponsored by Nintendo. This project uses the React UI component library to build the interface and does not redistribute official Nintendo game assets.

## Entry Points

The desktop entry point is still a draggable triceratops that can idle, react, eat uploaded files, and sleep.

<p>
  <img src="assets/readme_pet_idle.png" width="145" alt="idle pet">
  <img src="assets/readme_pet_happy.png" width="145" alt="happy pet">
  <img src="assets/readme_pet_eat.png" width="145" alt="eat pet">
  <img src="assets/readme_pet_attack.png" width="145" alt="attack pet">
  <img src="assets/readme_pet_sleep.png" width="145" alt="sleep pet">
</p>

Hovering over the pet reveals six actions:

- Input: quickly save a Markdown note.
- Upload: import Markdown, DOCX, PDF, and images; Inbox supports preview, ingest, and deleting uningested files.
- Search: full-text search over `notes/`, with tags, favorites, recent items, and reader preview.
- Q&A: retrieve wiki context and stream answers from an OpenAI-compatible LLM.
- Graph: inspect relationships between sources, entities, and concepts.
- Health: check broken links, orphan pages, index drift, and duplicates.

## New Panel Experience

The 2.0 panel is a React app under `frontend/`. Production assets are built into `frontend/dist`, then served by a local FastAPI server and opened through WebView.

Key changes:

- Fixed top navigation: no more hunting through separate small windows.
- Zelda / Sheikah-style dark control panel: shared background, buttons, cards, scrollbars, and status feedback.
- Ancient-tech visual elements: eye symbol, rune patterns, cyan outlines, glowing dividers, and Hylia-style title text.
- More compact result cards: long paths and snippets wrap inside bounded cards.
- Richer search preview: tags, favorites, recent items, wiki pages, and raw notes live in one interface.
- Better Upload Inbox control: temporarily store, preview, ingest one, ingest all, or delete the corresponding `notes/` file.
- Graph and Health are first-class pages instead of hidden maintenance tools.

## Data Flow

```text
Desktop pet
  -> Input / Upload
  -> notes/ raw material
  -> wiki/ compiled layer
  -> Search / Q&A / Graph / Health
```

The data layers stay separate:

- `notes/`: raw user material, easy to back up and migrate.
- `notes/.note_meta.json`: local metadata for tags, favorites, and recently opened files.
- `wiki/`: LLM-maintained compiled layer, including source summaries, entity pages, concept pages, `index.md`, and `log.md`.

Without LLM configuration, note input, upload, search, reader preview, tags, and local file management still work. Wiki ingest, Q&A, and LLM health checks are skipped or degraded automatically.

## Supported Material

- Markdown: saved directly under `notes/`, searchable, previewable, and ingestible into wiki.
- DOCX: raw file is preserved; wiki ingest converts it to Markdown.
- PDF: text pages can be extracted; scanned pages are supported in OCR builds.
- Images: OCR builds can convert image text into Markdown.
- Drag-and-drop: dropping files onto the pet and selecting files in the Upload page use the same save pipeline.

## Installation

This project targets Windows desktop usage. Python 3.10+ is recommended.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Run from source:

```bash
python app.py
```

Build the React panel:

```bash
cd frontend
npm install
npm run build
```

In source runs, the React panel reads `frontend/dist`. Packaged builds enable the WebView panel automatically. To force React panels from source:

```bash
set MYLIBRARY_REACT_PANELS=1
python app.py
```

## LLM Configuration

For source runs, copy the template and fill in your local credentials:

```bash
copy .env.template .env
```

Example:

```env
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
```

Any OpenAI-compatible endpoint can be used, such as DeepSeek, SenseNova, Ollama, Groq, or LM Studio. If `.env` is missing or `LLM_API_KEY` is empty, local note input, uploads, and search still work; LLM features such as wiki ingest and Q&A are skipped automatically.

Packaged zip builds currently do not include a `.env` file. If you need LLM features, create `.env` manually next to the extracted `.exe` and add `LLM_API_BASE`, `LLM_API_KEY`, and `LLM_MODEL`.

## OCR Builds

The base source install does not include PaddleOCR. Install it only when you need image OCR, scanned PDF OCR, or OCR from document screenshots:

```bash
pip install paddleocr paddlepaddle
```

Release packages are typically split into two builds:

| Package | OCR | Best for |
| --- | --- | --- |
| Lite | Not included | Notes, uploads, search, wiki, Q&A, graph, and health checks |
| OCR | Includes PaddleOCR, PaddlePaddle, and Chinese OCR models | Images, scanned PDFs, and OCR from document screenshots |

Neither packaged build auto-generates `.env`; users must manually place the LLM configuration file next to the `.exe`.

## Common Commands

```bash
# All tests
python -m pytest tests/

# One test file / one test
python -m pytest tests/test_web_panel_api.py -q
python -m pytest tests/test_grep_search.py::test_case_insensitive -v

# Frontend static test and build
node frontend\src\pages\searchGrouping.test.cjs
cd frontend && npm run build

# Build lightweight Windows exe
pyinstaller build.spec --noconfirm

# Build OCR Windows exe
pyinstaller build_ocr.spec --noconfirm
```

## Directory Layout

```text
assets/        Pet sprites and app icons
converter/     DOCX / PDF / Markdown / OCR conversion
frontend/      2.0 React panel
llm/           LLM client, wiki engine, prompts, linting, graph data
notes/         Raw user material, locally writable, not committed by default
search/        Local full-text search
storage/       Note saving and lightweight metadata
tests/         pytest and lightweight frontend tests
ui/            Desktop pet, Tkinter entry point, reader, and legacy panel components
web_panel/     FastAPI + WebView panel service
wiki/          LLM-maintained wiki output, locally writable, not committed by default
```

## Development Notes

- Do not replace the root window class; `TkinterDnD._require(root)` patches the existing root for drag-and-drop.
- Pet animation is centralized in `MainWindow._tick()`. Do not add separate per-state `after()` loops.
- Upload entry points should go through the unified save pipeline so drag-and-drop and the Upload page behave consistently.
- `search/grep_search.search_notes()` return shape is a UI contract.
- Wiki queries read `wiki/` by default; raw `notes/` text is sampled only when the user explicitly asks for source verification.
- In packaged builds, `notes/`, `wiki/`, and user-created `.env` live next to the `.exe` for easier migration.

## Who This Is For

This project is for people who want local-first knowledge management with a lightweight AI-organized layer:

- You want learning notes to accumulate over time.
- You want PDFs, excerpts, image text, and Markdown searchable in one place.
- You do not want to move all material into a cloud knowledge base.
- You want to go from “I saved many things” to “I can search, ask, connect, and maintain them.”
