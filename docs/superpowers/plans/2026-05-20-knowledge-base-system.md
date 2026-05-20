# Knowledge Base System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a desktop-pet-style knowledge base app where users can paste text, upload DOCX/PDF files, and search stored notes — all saved as Markdown files in a local folder.

**Architecture:** A ttkbootstrap GUI floats always-on-top like a desktop widget. File I/O converts pastes and uploads to `.md` files stored under `D:/myLibrary/notes/`. A lightweight LLM layer (stub for now) will later index and search those files; today's search is plain-text grep. The app is a single Python process with clearly separated modules: `ui/`, `storage/`, `converter/`, and `search/`.

**Tech Stack:** Python 3.11, ttkbootstrap, python-docx, pdfplumber, Markdown, pathlib

---

## File Structure

```
D:/myLibrary/
├── app.py                        # Entry point
├── config.py                     # Constants (NOTES_DIR, etc.)
├── ui/
│   ├── __init__.py
│   ├── main_window.py            # Root ttkbootstrap window, always-on-top widget
│   ├── input_tab.py              # Tab: paste text → save as MD
│   ├── upload_tab.py             # Tab: file picker → convert → save as MD
│   └── search_tab.py             # Tab: keyword search over notes
├── converter/
│   ├── __init__.py
│   ├── text_converter.py         # Plain text → Markdown
│   ├── docx_converter.py         # DOCX → Markdown via python-docx
│   └── pdf_converter.py          # PDF → Markdown via pdfplumber
├── storage/
│   ├── __init__.py
│   └── note_store.py             # Save / list / delete .md files
├── search/
│   ├── __init__.py
│   └── grep_search.py            # Plain-text search (LLM stub hook)
├── tests/
│   ├── test_text_converter.py
│   ├── test_docx_converter.py
│   ├── test_pdf_converter.py
│   ├── test_note_store.py
│   └── test_grep_search.py
└── notes/                        # Auto-created; all .md knowledge files live here
```

---

## Task 1: Project Scaffold & Config

**Files:**
- Create: `D:/myLibrary/config.py`
- Create: `D:/myLibrary/app.py`
- Create: `D:/myLibrary/ui/__init__.py`
- Create: `D:/myLibrary/converter/__init__.py`
- Create: `D:/myLibrary/storage/__init__.py`
- Create: `D:/myLibrary/search/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p D:/myLibrary/ui D:/myLibrary/converter D:/myLibrary/storage D:/myLibrary/search D:/myLibrary/tests D:/myLibrary/notes
```

- [ ] **Step 2: Write config.py**

```python
# config.py
from pathlib import Path

BASE_DIR = Path(__file__).parent
NOTES_DIR = BASE_DIR / "notes"
NOTES_DIR.mkdir(exist_ok=True)

APP_TITLE = "知识库助手"
WINDOW_GEOMETRY = "420x560"
```

- [ ] **Step 3: Write stub app.py**

```python
# app.py
import ttkbootstrap as ttk
from ui.main_window import MainWindow

def main():
    root = ttk.Window(themename="cosmo")
    app = MainWindow(root)
    root.mainloop()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write empty __init__.py files**

Create each file with just a blank line:
- `ui/__init__.py`
- `converter/__init__.py`
- `storage/__init__.py`
- `search/__init__.py`

- [ ] **Step 5: Commit**

```bash
cd D:/myLibrary && git init && git add . && git commit -m "feat: project scaffold and config"
```

---

## Task 2: Note Storage Module

**Files:**
- Create: `D:/myLibrary/storage/note_store.py`
- Create: `D:/myLibrary/tests/test_note_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_note_store.py
import pytest
from pathlib import Path
import tempfile, shutil
from storage.note_store import save_note, list_notes, delete_note

@pytest.fixture
def tmp_notes(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "NOTES_DIR", tmp_path)
    return tmp_path

def test_save_note_creates_file(tmp_notes):
    path = save_note("hello world", "test-note", notes_dir=tmp_notes)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello world"

def test_save_note_sanitizes_title(tmp_notes):
    path = save_note("content", "title with spaces & symbols!", notes_dir=tmp_notes)
    assert " " not in path.name
    assert "&" not in path.name

def test_save_note_auto_title(tmp_notes):
    path = save_note("content", notes_dir=tmp_notes)
    assert path.suffix == ".md"

def test_list_notes_returns_md_files(tmp_notes):
    (tmp_notes / "a.md").write_text("a")
    (tmp_notes / "b.md").write_text("b")
    (tmp_notes / "c.txt").write_text("c")
    notes = list_notes(notes_dir=tmp_notes)
    assert len(notes) == 2
    assert all(n.suffix == ".md" for n in notes)

def test_delete_note(tmp_notes):
    p = tmp_notes / "del.md"
    p.write_text("bye")
    delete_note(p)
    assert not p.exists()

def test_delete_note_missing_is_noop(tmp_notes):
    delete_note(tmp_notes / "ghost.md")  # should not raise
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd D:/myLibrary && python -m pytest tests/test_note_store.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError` or similar — module doesn't exist yet.

- [ ] **Step 3: Implement note_store.py**

```python
# storage/note_store.py
import re
from datetime import datetime
from pathlib import Path
import config

def _sanitize(title: str) -> str:
    """Replace non-alphanumeric chars (except - and _) with _."""
    return re.sub(r"[^\w\-]", "_", title).strip("_") or "note"

def save_note(content: str, title: str | None = None, *, notes_dir: Path | None = None) -> Path:
    """Save content as a .md file. Returns the saved Path."""
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stem = _sanitize(title) if title else datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"{stem}.md"
    # Avoid overwrite: append counter if file exists
    counter = 1
    while path.exists():
        path = directory / f"{stem}_{counter}.md"
        counter += 1
    path.write_text(content, encoding="utf-8")
    return path

def list_notes(*, notes_dir: Path | None = None) -> list[Path]:
    """Return all .md files in notes_dir, sorted by name."""
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    return sorted(directory.glob("*.md"))

def delete_note(path: Path) -> None:
    """Delete a note file; silently ignore if not found."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd D:/myLibrary && python -m pytest tests/test_note_store.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add storage/note_store.py tests/test_note_store.py && git commit -m "feat: note storage module"
```

---

## Task 3: Text → Markdown Converter

**Files:**
- Create: `D:/myLibrary/converter/text_converter.py`
- Create: `D:/myLibrary/tests/test_text_converter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_text_converter.py
from converter.text_converter import text_to_markdown

def test_plain_text_unchanged():
    result = text_to_markdown("hello world")
    assert "hello world" in result

def test_adds_yaml_frontmatter():
    result = text_to_markdown("content", title="My Note")
    assert result.startswith("---")
    assert "title: My Note" in result

def test_empty_string():
    result = text_to_markdown("")
    assert isinstance(result, str)

def test_preserves_existing_newlines():
    result = text_to_markdown("line1\nline2\nline3")
    assert "line1" in result
    assert "line3" in result
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd D:/myLibrary && python -m pytest tests/test_text_converter.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement text_converter.py**

```python
# converter/text_converter.py
from datetime import datetime

def text_to_markdown(text: str, title: str | None = None) -> str:
    """Wrap plain text in Markdown with optional YAML front-matter."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_title = title or "Untitled"
    frontmatter = f"---\ntitle: {safe_title}\ncreated: {timestamp}\n---\n\n"
    return frontmatter + text
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd D:/myLibrary && python -m pytest tests/test_text_converter.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add converter/text_converter.py tests/test_text_converter.py && git commit -m "feat: text to markdown converter"
```

---

## Task 4: DOCX → Markdown Converter

**Files:**
- Create: `D:/myLibrary/converter/docx_converter.py`
- Create: `D:/myLibrary/tests/test_docx_converter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docx_converter.py
import pytest
from pathlib import Path
from docx import Document
import tempfile
from converter.docx_converter import docx_to_markdown

@pytest.fixture
def sample_docx(tmp_path):
    doc = Document()
    doc.add_heading("Test Heading", level=1)
    doc.add_paragraph("First paragraph.")
    doc.add_paragraph("Second paragraph.")
    path = tmp_path / "sample.docx"
    doc.save(str(path))
    return path

def test_extracts_heading(sample_docx):
    result = docx_to_markdown(sample_docx)
    assert "# Test Heading" in result

def test_extracts_paragraphs(sample_docx):
    result = docx_to_markdown(sample_docx)
    assert "First paragraph." in result
    assert "Second paragraph." in result

def test_returns_string(sample_docx):
    assert isinstance(docx_to_markdown(sample_docx), str)

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        docx_to_markdown(Path("/nonexistent/file.docx"))
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd D:/myLibrary && python -m pytest tests/test_docx_converter.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement docx_converter.py**

```python
# converter/docx_converter.py
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn

def docx_to_markdown(path: Path) -> str:
    """Convert a DOCX file to Markdown string."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    doc = Document(str(path))
    lines: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        style = para.style.name
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 1
            lines.append(f"{'#' * level} {text}")
        else:
            lines.append(text)

    return "\n".join(lines)
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd D:/myLibrary && python -m pytest tests/test_docx_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converter/docx_converter.py tests/test_docx_converter.py && git commit -m "feat: docx to markdown converter"
```

---

## Task 5: PDF → Markdown Converter

**Files:**
- Create: `D:/myLibrary/converter/pdf_converter.py`
- Create: `D:/myLibrary/tests/test_pdf_converter.py`

- [ ] **Step 1: Install pdfplumber if not present**

```bash
pip install pdfplumber
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_pdf_converter.py
import pytest
from pathlib import Path
from converter.pdf_converter import pdf_to_markdown

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        pdf_to_markdown(Path("/nonexistent/file.pdf"))

def test_returns_string(tmp_path):
    # Create a minimal valid PDF with reportlab (skip if not installed)
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    p = tmp_path / "test.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(100, 750, "Hello PDF World")
    c.save()
    result = pdf_to_markdown(p)
    assert isinstance(result, str)
    assert "Hello PDF World" in result
```

- [ ] **Step 3: Run — expect FAIL (module missing)**

```bash
cd D:/myLibrary && python -m pytest tests/test_pdf_converter.py -v 2>&1 | head -20
```

- [ ] **Step 4: Implement pdf_converter.py**

```python
# converter/pdf_converter.py
from pathlib import Path
import pdfplumber

def pdf_to_markdown(path: Path) -> str:
    """Convert a PDF file to Markdown string using pdfplumber."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"<!-- page {i} -->\n{text.strip()}")

    return "\n\n".join(pages)
```

- [ ] **Step 5: Run — expect PASS (test_missing_file_raises always passes; PDF test skipped if reportlab absent)**

```bash
cd D:/myLibrary && python -m pytest tests/test_pdf_converter.py -v
```

- [ ] **Step 6: Commit**

```bash
git add converter/pdf_converter.py tests/test_pdf_converter.py && git commit -m "feat: pdf to markdown converter"
```

---

## Task 6: Plain-Text Search Module

**Files:**
- Create: `D:/myLibrary/search/grep_search.py`
- Create: `D:/myLibrary/tests/test_grep_search.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_grep_search.py
import pytest
from pathlib import Path
from search.grep_search import search_notes

@pytest.fixture
def note_dir(tmp_path):
    (tmp_path / "alpha.md").write_text("# Alpha\nThis is about apples.", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta\nThis is about bananas.", encoding="utf-8")
    (tmp_path / "gamma.md").write_text("# Gamma\nNothing relevant here.", encoding="utf-8")
    return tmp_path

def test_finds_matching_notes(note_dir):
    results = search_notes("apples", notes_dir=note_dir)
    assert len(results) == 1
    assert results[0]["file"].name == "alpha.md"

def test_returns_snippet(note_dir):
    results = search_notes("bananas", notes_dir=note_dir)
    assert "bananas" in results[0]["snippet"]

def test_no_match_returns_empty(note_dir):
    assert search_notes("zzznomatch", notes_dir=note_dir) == []

def test_case_insensitive(note_dir):
    results = search_notes("APPLES", notes_dir=note_dir)
    assert len(results) == 1

def test_returns_list_of_dicts(note_dir):
    results = search_notes("alpha", notes_dir=note_dir)
    assert isinstance(results, list)
    assert all("file" in r and "snippet" in r for r in results)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd D:/myLibrary && python -m pytest tests/test_grep_search.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement grep_search.py**

```python
# search/grep_search.py
from pathlib import Path
from typing import TypedDict
import config

class SearchResult(TypedDict):
    file: Path
    snippet: str

def search_notes(query: str, *, notes_dir: Path | None = None) -> list[SearchResult]:
    """
    Case-insensitive plain-text search over all .md files.
    Returns list of {file, snippet} dicts.
    LLM-powered search can replace this function later.
    """
    directory = notes_dir if notes_dir is not None else config.NOTES_DIR
    results: list[SearchResult] = []
    lower_query = query.lower()

    for md_file in sorted(directory.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        if lower_query in text.lower():
            # Find first matching line as snippet
            for line in text.splitlines():
                if lower_query in line.lower():
                    snippet = line.strip()[:120]
                    break
            else:
                snippet = text[:120].strip()
            results.append({"file": md_file, "snippet": snippet})

    return results
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd D:/myLibrary && python -m pytest tests/test_grep_search.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add search/grep_search.py tests/test_grep_search.py && git commit -m "feat: plain-text search module"
```

---

## Task 7: Main Window UI Shell

**Files:**
- Create: `D:/myLibrary/ui/main_window.py`

- [ ] **Step 1: Write main_window.py**

```python
# ui/main_window.py
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from config import APP_TITLE, WINDOW_GEOMETRY
from ui.input_tab import InputTab
from ui.upload_tab import UploadTab
from ui.search_tab import SearchTab

class MainWindow:
    def __init__(self, root: ttk.Window):
        self.root = root
        root.title(APP_TITLE)
        root.geometry(WINDOW_GEOMETRY)
        root.resizable(False, False)
        root.attributes("-topmost", True)   # Always on top — desktop pet behaviour

        # Drag to move (no title bar needed)
        root.overrideredirect(False)        # Keep OS chrome for now; can strip later

        notebook = ttk.Notebook(root, bootstyle="primary")
        notebook.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self.input_tab = InputTab(notebook)
        self.upload_tab = UploadTab(notebook)
        self.search_tab = SearchTab(notebook)

        notebook.add(self.input_tab.frame, text="  ✍ 输入  ")
        notebook.add(self.upload_tab.frame, text="  📁 上传  ")
        notebook.add(self.search_tab.frame, text="  🔍 查询  ")
```

- [ ] **Step 2: Smoke-test import (no GUI shown)**

```bash
cd D:/myLibrary && python -c "import ui.main_window; print('import ok')" 2>&1
```
This will fail until the tab files exist — that's expected. Proceed to Task 8.

- [ ] **Step 3: Commit stub**

```bash
git add ui/main_window.py && git commit -m "feat: main window shell"
```

---

## Task 8: Input Tab (Paste Text → Save MD)

**Files:**
- Create: `D:/myLibrary/ui/input_tab.py`

- [ ] **Step 1: Write input_tab.py**

```python
# ui/input_tab.py
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from converter.text_converter import text_to_markdown
from storage.note_store import save_note

class InputTab:
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self):
        # Title entry
        title_row = ttk.Frame(self.frame)
        title_row.pack(fill=X, padx=10, pady=(10, 4))
        ttk.Label(title_row, text="标题（可选）:").pack(side=LEFT)
        self.title_var = tk.StringVar()
        ttk.Entry(title_row, textvariable=self.title_var, width=28).pack(side=LEFT, padx=6)

        # Text area
        ttk.Label(self.frame, text="粘贴内容:").pack(anchor=W, padx=10)
        self.text_area = tk.Text(self.frame, height=14, wrap=tk.WORD, font=("Consolas", 10))
        self.text_area.pack(fill=BOTH, expand=True, padx=10, pady=4)

        # Save button
        ttk.Button(
            self.frame,
            text="💾 保存到知识库",
            bootstyle="success",
            command=self._on_save,
        ).pack(pady=(4, 10))

    def _on_save(self):
        content = self.text_area.get("1.0", tk.END).strip()
        if not content:
            Messagebox.show_warning("内容不能为空", parent=self.frame)
            return
        title = self.title_var.get().strip() or None
        md = text_to_markdown(content, title=title)
        path = save_note(md, title=title)
        Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
        self.text_area.delete("1.0", tk.END)
        self.title_var.set("")
```

- [ ] **Step 2: Commit**

```bash
git add ui/input_tab.py && git commit -m "feat: input tab UI"
```

---

## Task 9: Upload Tab (DOCX/PDF → Save MD)

**Files:**
- Create: `D:/myLibrary/ui/upload_tab.py`

- [ ] **Step 1: Write upload_tab.py**

```python
# ui/upload_tab.py
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from converter.docx_converter import docx_to_markdown
from converter.pdf_converter import pdf_to_markdown
from storage.note_store import save_note

SUPPORTED = {".docx": docx_to_markdown, ".pdf": pdf_to_markdown}

class UploadTab:
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self._selected: Path | None = None
        self._build()

    def _build(self):
        ttk.Label(self.frame, text="选择 DOCX 或 PDF 文件:").pack(anchor=W, padx=10, pady=(12, 4))

        pick_row = ttk.Frame(self.frame)
        pick_row.pack(fill=X, padx=10)
        self.file_label = ttk.Label(pick_row, text="未选择文件", bootstyle="secondary", width=32)
        self.file_label.pack(side=LEFT)
        ttk.Button(pick_row, text="浏览…", bootstyle="outline", command=self._pick_file).pack(side=LEFT, padx=6)

        # Preview area
        ttk.Label(self.frame, text="预览（前500字符）:").pack(anchor=W, padx=10, pady=(10, 2))
        self.preview = tk.Text(self.frame, height=10, wrap=tk.WORD, state=tk.DISABLED,
                               font=("Consolas", 9), bg="#f0f0f0")
        self.preview.pack(fill=BOTH, expand=True, padx=10)

        ttk.Button(
            self.frame,
            text="💾 转换并保存",
            bootstyle="success",
            command=self._on_save,
        ).pack(pady=(8, 10))

    def _pick_file(self):
        path_str = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[("文档文件", "*.docx *.pdf"), ("所有文件", "*.*")],
        )
        if not path_str:
            return
        self._selected = Path(path_str)
        self.file_label.config(text=self._selected.name)
        self._update_preview()

    def _update_preview(self):
        if not self._selected:
            return
        suffix = self._selected.suffix.lower()
        converter = SUPPORTED.get(suffix)
        if converter is None:
            self._set_preview("不支持的文件类型")
            return
        try:
            md = converter(self._selected)
            self._set_preview(md[:500])
        except Exception as exc:
            self._set_preview(f"预览失败: {exc}")

    def _set_preview(self, text: str):
        self.preview.config(state=tk.NORMAL)
        self.preview.delete("1.0", tk.END)
        self.preview.insert(tk.END, text)
        self.preview.config(state=tk.DISABLED)

    def _on_save(self):
        if not self._selected:
            Messagebox.show_warning("请先选择文件", parent=self.frame)
            return
        suffix = self._selected.suffix.lower()
        converter = SUPPORTED.get(suffix)
        if converter is None:
            Messagebox.show_error("不支持的文件格式", parent=self.frame)
            return
        try:
            md = converter(self._selected)
            title = self._selected.stem
            path = save_note(md, title=title)
            Messagebox.show_info(f"已保存:\n{path.name}", parent=self.frame)
            self._selected = None
            self.file_label.config(text="未选择文件")
            self._set_preview("")
        except Exception as exc:
            Messagebox.show_error(f"转换失败:\n{exc}", parent=self.frame)
```

- [ ] **Step 2: Commit**

```bash
git add ui/upload_tab.py && git commit -m "feat: upload tab UI"
```

---

## Task 10: Search Tab (Keyword Search)

**Files:**
- Create: `D:/myLibrary/ui/search_tab.py`

- [ ] **Step 1: Write search_tab.py**

```python
# ui/search_tab.py
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from search.grep_search import search_notes

class SearchTab:
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self):
        # Search bar
        search_row = ttk.Frame(self.frame)
        search_row.pack(fill=X, padx=10, pady=(12, 6))
        self.query_var = tk.StringVar()
        entry = ttk.Entry(search_row, textvariable=self.query_var, font=("Microsoft YaHei", 11))
        entry.pack(side=LEFT, fill=X, expand=True)
        entry.bind("<Return>", lambda _: self._on_search())
        ttk.Button(search_row, text="🔍", bootstyle="primary", command=self._on_search).pack(side=LEFT, padx=4)

        # Results listbox
        ttk.Label(self.frame, text="搜索结果:").pack(anchor=W, padx=10)
        list_frame = ttk.Frame(self.frame)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=4)
        scrollbar = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.results_list = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                       font=("Consolas", 9), selectmode=tk.SINGLE)
        scrollbar.config(command=self.results_list.yview)
        self.results_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # Snippet area
        ttk.Label(self.frame, text="片段预览:").pack(anchor=W, padx=10)
        self.snippet_text = tk.Text(self.frame, height=5, wrap=tk.WORD,
                                    state=tk.DISABLED, font=("Consolas", 9))
        self.snippet_text.pack(fill=X, padx=10, pady=(2, 10))

        self.results_list.bind("<<ListboxSelect>>", self._on_select)
        self._results: list[dict] = []

    def _on_search(self):
        query = self.query_var.get().strip()
        if not query:
            return
        self._results = search_notes(query)
        self.results_list.delete(0, tk.END)
        for r in self._results:
            self.results_list.insert(tk.END, r["file"].name)
        if not self._results:
            self.results_list.insert(tk.END, "（无匹配结果）")

    def _on_select(self, _event):
        sel = self.results_list.curselection()
        if not sel or not self._results:
            return
        idx = sel[0]
        if idx >= len(self._results):
            return
        snippet = self._results[idx]["snippet"]
        self.snippet_text.config(state=tk.NORMAL)
        self.snippet_text.delete("1.0", tk.END)
        self.snippet_text.insert(tk.END, snippet)
        self.snippet_text.config(state=tk.DISABLED)
```

- [ ] **Step 2: Commit**

```bash
git add ui/search_tab.py && git commit -m "feat: search tab UI"
```

---

## Task 11: Integration & Smoke Test

**Files:**
- No new files; run everything together.

- [ ] **Step 1: Install missing dependencies**

```bash
pip install ttkbootstrap pdfplumber python-docx
```

- [ ] **Step 2: Run all unit tests**

```bash
cd D:/myLibrary && python -m pytest tests/ -v
```
Expected: All pass (PDF test skipped if reportlab absent).

- [ ] **Step 3: Launch the app**

```bash
cd D:/myLibrary && python app.py
```
Expected: A ttkbootstrap window opens with three tabs: 输入 / 上传 / 查询.

- [ ] **Step 4: Manual smoke test checklist**
  - [ ] Paste text in 输入 tab, enter a title, click 保存 → file appears in `notes/`
  - [ ] Open 上传 tab, pick a DOCX → preview appears → 转换并保存 → file in `notes/`
  - [ ] Open 查询 tab, search for a word from the saved note → result appears in list → click to see snippet

- [ ] **Step 5: Final commit**

```bash
git add -A && git commit -m "feat: knowledge base system — file storage complete"
```

---

## LLM Stub Hook (for future implementation)

When you're ready to add LLM-powered search, replace the body of `search/grep_search.py::search_notes` with an LLM call. The function signature stays the same so all callers work unchanged:

```python
# search/grep_search.py  (future LLM version — same signature)
def search_notes(query: str, *, notes_dir: Path | None = None) -> list[SearchResult]:
    # TODO: embed query, cosine-search indexed vectors
    ...
```

The UI, storage, and converter layers require zero changes.
