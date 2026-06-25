from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import mimetypes
import queue
import shutil
import tempfile
import threading
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlencode

import httpx
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config as app_config
from converter.docx_converter import docx_to_markdown
from converter.ocr_converter import (
    IMAGE_SUFFIXES,
    OCRUnavailableError,
    _blockquote,
    _format_ocr_lines,
    enrich_markdown_images,
    image_to_markdown,
    is_image_file,
    ocr_image,
)
from converter.pdf_converter import pdf_to_markdown
from converter.text_converter import text_to_markdown
from llm.client import load_llm_config
from llm.wiki_engine import (
    _append_log as append_wiki_log,
    discuss_and_ingest,
    query_wiki,
    rebuild_index_from_disk,
    save_query_answer_as_wiki_page,
)
from llm.graph_data import Graph, parse_wiki_graph
from llm.wiki_lint import (
    LintFinding, LintFixFile, LintFixPreview,
    apply_llm_fix_preview, auto_fix, build_llm_fix_preview,
    lint_wiki, save_lint_report, static_checks,
)
from search.grep_search import search_notes_ranked
from storage.note_meta import (
    add_recent,
    get_tags,
    is_favorite,
    list_recent,
    normalize_tags,
    set_favorite,
    set_tags,
)
from storage.note_store import delete_note, save_note, save_raw_file

_log = logging.getLogger(__name__)

SearchMode = Literal["fulltext", "recent", "favorite", "tag"]
LibraryScope = Literal["notes", "wiki"]


class FavoritePayload(BaseModel):
    path: str
    favorite: bool
    scope: LibraryScope = "notes"


class TagsPayload(BaseModel):
    path: str
    tags: str | list[str]
    scope: LibraryScope = "notes"


class OpenReaderPayload(BaseModel):
    path: str
    query: str = ""


class NotePayload(BaseModel):
    title: str | None = None
    content: str


class QueryPayload(BaseModel):
    question: str


class QuerySavePayload(BaseModel):
    question: str
    answer: str
    used_pages: list[str] = []
    raw_sources: list[str] = []
    answer_type: str = "direct_answer"


class LintFixPayload(BaseModel):
    findings: list[dict[str, Any]]


class LintApplyPreviewPayload(BaseModel):
    preview: dict[str, Any]


class IngestPayload(BaseModel):
    paths: list[str]


class IngestSession:
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        self.chat_q: queue.Queue[Any] = queue.Queue()
        self.user_q: queue.Queue[str] = queue.Queue()
        self.started = False
        self.lock = threading.Lock()


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def error_response(code: str, message: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


def _event(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


def _plain_object(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return dict(value)


def _resolve_note_path(raw: str, notes_dir: Path) -> Path:
    base = notes_dir.resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path is outside notes directory") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Note not found")
    return candidate


def _resolve_wiki_path(raw: str, wiki_dir: Path) -> Path:
    base = wiki_dir.resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path is outside wiki directory") from exc
    if not candidate.exists() or not candidate.is_file() or candidate.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return candidate


def _relative_posix(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _snippet(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[:120].strip()
    except OSError:
        return ""


def _note_payload(path: Path, *, snippet: str = "", notes_dir: Path) -> dict[str, Any]:
    return {
        "scope": "notes",
        "path": str(path),
        "relative_path": _relative_posix(path, notes_dir),
        "name": path.name,
        "kind": "markdown",
        "snippet": snippet or _snippet(path),
        "favorite": is_favorite(path, notes_dir=notes_dir),
        "tags": get_tags(path, notes_dir=notes_dir),
    }


def _file_payload(path: Path) -> dict[str, str]:
    return {"path": str(path), "name": path.name}


def _source_preview_text(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return path.read_text(encoding="utf-8")
    return f"原始文件: {path.name}\n\n这是保存在 notes/ 下的源文件，可用于 wiki 收录。"


def _md_passthrough(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return enrich_markdown_images(text, Path(path).parent)


UPLOAD_CONVERTERS = {
    ".docx": docx_to_markdown,
    ".pdf": pdf_to_markdown,
    ".md": _md_passthrough,
}
UPLOAD_CONVERTERS.update({suffix: image_to_markdown for suffix in IMAGE_SUFFIXES})
SOURCE_VIEW_SUFFIXES = frozenset({".docx", ".pdf", *IMAGE_SUFFIXES})
WIKI_GROUPS = (
    ("source", "Sources", "sources"),
    ("concept", "Concepts", "concepts"),
    ("entity", "Entities", "entities"),
)


def _library_kind(path: Path, *, scope: LibraryScope, base: Path) -> str:
    if scope == "notes":
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return "image"
        return path.suffix.lower().lstrip(".") or "file"
    rel = Path(_relative_posix(path, base))
    if len(rel.parts) == 1:
        return path.stem
    return {
        "sources": "source",
        "entities": "entity",
        "concepts": "concept",
    }.get(rel.parts[0], rel.parts[0])


def _library_snippet(path: Path) -> str:
    if path.suffix.lower() != ".md":
        return f"原始文件: {path.name}"
    return _snippet(path)


def _library_file_payload(path: Path, *, scope: LibraryScope, base: Path) -> dict[str, Any]:
    relative_path = _relative_posix(path, base)
    return {
        "scope": scope,
        "path": str(path) if scope == "notes" else relative_path,
        "relative_path": relative_path,
        "name": path.name,
        "kind": _library_kind(path, scope=scope, base=base),
        "snippet": _library_snippet(path),
        "favorite": False,
        "tags": [],
    }


def _library_file_payload_with_meta(
    path: Path,
    *,
    scope: LibraryScope,
    base: Path,
    notes_dir: Path,
) -> dict[str, Any]:
    payload = _library_file_payload(path, scope=scope, base=base)
    payload["favorite"] = is_favorite(path, notes_dir=notes_dir)
    payload["tags"] = get_tags(path, notes_dir=notes_dir)
    return payload


def _meta_target(scope: LibraryScope, raw: str, *, notes_dir: Path, wiki_dir: Path) -> Path:
    if scope == "wiki":
        return _resolve_wiki_path(raw, wiki_dir)
    return _resolve_note_path(raw, notes_dir)


def _iter_meta_files(notes_dir: Path, wiki_dir: Path) -> list[tuple[Path, LibraryScope, Path]]:
    files: list[tuple[Path, LibraryScope, Path]] = []
    if notes_dir.exists():
        files.extend(
            (path, "notes", notes_dir)
            for path in sorted(notes_dir.iterdir(), key=lambda item: item.name.lower())
            if path.is_file() and not path.name.startswith(".")
        )
    files.extend((path, "wiki", wiki_dir) for path in _iter_wiki_files(wiki_dir))
    return files


def _meta_search_results(
    *,
    mode: SearchMode,
    query: str,
    notes_dir: Path,
    wiki_dir: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    wanted = {tag.casefold() for tag in normalize_tags(query)}
    for path, scope, base in _iter_meta_files(notes_dir, wiki_dir):
        tags = get_tags(path, notes_dir=notes_dir)
        if mode == "favorite" and not is_favorite(path, notes_dir=notes_dir):
            continue
        if mode == "tag":
            tag_set = {tag.casefold() for tag in tags}
            if wanted:
                if not wanted.intersection(tag_set):
                    continue
            elif not tag_set:
                continue
        results.append(_library_file_payload_with_meta(path, scope=scope, base=base, notes_dir=notes_dir))
    return results


def _iter_source_files(notes_dir: Path) -> list[Path]:
    if not notes_dir.exists():
        return []
    files: list[Path] = []
    for path in notes_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in SOURCE_VIEW_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: _relative_posix(item, notes_dir).lower())


def _iter_wiki_files(wiki_dir: Path) -> list[Path]:
    if not wiki_dir.exists():
        return []
    files: list[Path] = []
    for _kind, _label, dirname in WIKI_GROUPS:
        group_dir = wiki_dir / dirname
        if group_dir.exists():
            files.extend(sorted(group_dir.glob("*.md"), key=lambda item: item.name.lower()))
    return files


def _wiki_group_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for kind, label, _dirname in WIKI_GROUPS:
        group_items = [item for item in items if item["kind"] == kind]
        groups.append({"kind": kind, "label": label, "items": group_items})
    return groups


def _matches_library_query(path: Path, *, base: Path, query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    haystacks = [path.name.lower(), _relative_posix(path, base).lower()]
    if path.suffix.lower() == ".md":
        try:
            haystacks.append(path.read_text(encoding="utf-8").lower())
        except OSError:
            pass
    return any(needle in value for value in haystacks)


def _media_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _source_render_mode(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx_html"
    return "download"


def _raw_media_url(scope: LibraryScope, path: Path, base: Path) -> str:
    query = urlencode({"scope": scope, "path": _relative_posix(path, base)})
    return f"/api/library/files/raw?{query}"


def _docx_run_images(doc, run) -> list[str]:
    urls: list[str] = []
    for node in run._element.iter():
        if not node.tag.endswith("}blip"):
            continue
        rid = node.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if not rid:
            continue
        part = doc.part.related_parts.get(rid)
        if part is None or not getattr(part, "content_type", "").startswith("image/"):
            continue
        encoded = base64.b64encode(part.blob).decode("ascii")
        urls.append(f"data:{part.content_type};base64,{encoded}")
    return urls


def _docx_run_html(doc, run) -> str:
    text = html.escape(run.text or "")
    if text:
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.italic:
            text = f"<em>{text}</em>"
        if run.underline:
            text = f"<u>{text}</u>"
    images = "".join(
        f'<img src="{url}" alt="DOCX image" />'
        for url in _docx_run_images(doc, run)
    )
    return text + images


def _docx_paragraph_html(doc, para: Paragraph) -> str:
    inner = "".join(_docx_run_html(doc, run) for run in para.runs)
    if not inner:
        return ""
    style_name = getattr(para.style, "name", "")
    if style_name.startswith("Heading"):
        try:
            level = max(1, min(6, int(style_name.split()[-1])))
        except ValueError:
            level = 1
        return f"<h{level}>{inner}</h{level}>"
    return f"<p>{inner}</p>"


def _docx_table_html(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = "".join(
            f"<td>{html.escape(cell.text).replace(chr(10), '<br />')}</td>"
            for cell in row.cells
        )
        rows.append(f"<tr>{cells}</tr>")
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def _docx_to_html(path: Path) -> str:
    doc = Document(str(path))
    body: list[str] = []
    for child in doc.element.body:
        if child.tag.endswith("}p"):
            block = _docx_paragraph_html(doc, Paragraph(child, doc))
        elif child.tag.endswith("}tbl"):
            block = _docx_table_html(Table(child, doc))
        else:
            block = ""
        if block:
            body.append(block)
    return "\n".join(body)


def _copy_upload_to_temp(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(upload.file, tmp)
        return Path(tmp.name)


def _save_uploaded_file(path: Path, *, original_name: str, notes_dir: Path) -> Path:
    original = Path(original_name or path.name)
    suffix = original.suffix.lower()
    if suffix not in UPLOAD_CONVERTERS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")
    if is_image_file(original):
        asset_dir = notes_dir / ".assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_name = original.name
        asset_dest = asset_dir / asset_name
        if asset_dest.exists():
            asset_name = f"{original.stem}_{uuid.uuid4().hex[:6]}{original.suffix}"
            asset_dest = asset_dir / asset_name
        shutil.copy2(path, asset_dest)
        md = image_to_markdown(path)
        body = f"![](.assets/{asset_name})\n\n{md}"
        return save_note(body, title=original.stem, notes_dir=notes_dir)
    if suffix == ".md":
        return save_note(_md_passthrough(path), title=original.stem, notes_dir=notes_dir)
    renamed = path.with_name(original.name)
    shutil.copy2(path, renamed)
    return save_raw_file(renamed, notes_dir=notes_dir)


def _save_asset_upload(path: Path, *, original_name: str, notes_dir: Path) -> dict[str, str]:
    suffix = Path(original_name or path.name).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only image assets are supported")
    asset_dir = notes_dir / ".assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    original = Path(original_name or path.name)
    asset_name = original.name
    asset_dest = asset_dir / asset_name
    if asset_dest.exists():
        asset_name = f"{original.stem}_{uuid.uuid4().hex[:6]}{original.suffix}"
        asset_dest = asset_dir / asset_name
    shutil.copy2(path, asset_dest)

    markdown = f"![](.assets/{asset_name})"
    ocr_status = "unavailable"
    try:
        from PIL import Image

        with Image.open(path) as img:
            body = _format_ocr_lines(ocr_image(img))
        if body:
            markdown += f"\n\n<!-- ocr -->\n{_blockquote(body)}\n<!-- /ocr -->"
            ocr_status = "ok"
        else:
            ocr_status = "empty"
    except OCRUnavailableError:
        ocr_status = "unavailable"
    except Exception:
        ocr_status = "error"

    return {
        "path": str(asset_dest),
        "name": asset_name,
        "markdown": markdown,
        "ocr_status": ocr_status,
    }


def _find_uningested_notes(notes_dir: Path, wiki_dir: Path) -> list[Path]:
    if not notes_dir.exists():
        return []
    note_files = {
        f for f in notes_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".md", ".docx", ".pdf", *IMAGE_SUFFIXES}
    }
    sources_dir = wiki_dir / "sources"
    if sources_dir.exists():
        ingested_stems = {
            sf.stem[len("summary_"):]
            for sf in sources_dir.iterdir()
            if sf.name.startswith("summary_") and sf.suffix == ".md"
        }
        note_files = {f for f in note_files if f.stem not in ingested_stems}
    return sorted(note_files)


def _read_inbox_preview(note_path: Path) -> str:
    if note_path.suffix.lower() == ".md":
        return note_path.read_text(encoding="utf-8")
    return f"原始文件: {note_path.name}\n\n点击“收录”后会读取并更新 wiki。"


def _finding_payload(finding: LintFinding | dict[str, Any]) -> dict[str, Any]:
    if isinstance(finding, LintFinding):
        return asdict(finding)
    return dict(finding)


def _finding_from_payload(payload: dict[str, Any]) -> LintFinding:
    return LintFinding(
        severity=str(payload.get("severity", "info")),
        kind=str(payload.get("kind", "")),
        location=str(payload.get("location", "")),
        message=str(payload.get("message", "")),
        suggestion=str(payload.get("suggestion", "")),
        priority=str(payload.get("priority", "P2")),
        fixable=bool(payload.get("fixable", False)),
        source=str(payload.get("source", "static")),
    )


def _finding_key(finding: LintFinding) -> tuple[str, str, str]:
    return (finding.source, finding.kind, finding.location)


def _selected_findings_after_refresh(
    selected: list[LintFinding],
    refreshed: list[LintFinding],
) -> list[LintFinding]:
    selected_static = {
        _finding_key(finding)
        for finding in selected
        if finding.source != "llm"
    }
    remaining: list[LintFinding] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in refreshed:
        key = _finding_key(finding)
        if key in selected_static and key not in seen:
            remaining.append(finding)
            seen.add(key)
    for finding in selected:
        if finding.source == "llm":
            key = _finding_key(finding)
            if key not in seen:
                remaining.append(finding)
                seen.add(key)
    return remaining


def _fix_preview_from_payload(payload: dict[str, Any]) -> LintFixPreview:
    files = []
    for item in payload.get("files", []):
        files.append(LintFixFile(
            path=str(item.get("path", "")),
            original=str(item.get("original", "")),
            updated=str(item.get("updated", "")),
            issues=tuple(str(x) for x in item.get("issues", [])),
        ))
    return LintFixPreview(files=tuple(files), summary=str(payload.get("summary", "")))


def _graph_degrees(graph: Graph) -> dict[str, int]:
    degrees: dict[str, int] = {}
    for edge in graph.edges:
        degrees[edge.source] = degrees.get(edge.source, 0) + 1
        degrees[edge.target] = degrees.get(edge.target, 0) + 1
    for node in graph.nodes:
        degrees.setdefault(node.id, 0)
    return degrees


def _dedupe_graph_edges(graph: Graph) -> list[dict[str, Any]]:
    reverse_edges = {(edge.target, edge.source) for edge in graph.edges}
    seen_pairs: set[frozenset[str]] = set()
    payload: list[dict[str, Any]] = []
    for edge in graph.edges:
        pair = frozenset((edge.source, edge.target))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        payload.append({
            "source": edge.source,
            "target": edge.target,
            "kind": edge.kind,
            "bidirectional": edge.bidirectional or (edge.source, edge.target) in reverse_edges,
        })
    return payload


def _graph_payload(graph: Graph) -> dict[str, Any]:
    degrees = _graph_degrees(graph)
    max_degree = max(degrees.values()) if degrees else 0
    hub_threshold = max(1, int(max_degree * 0.8)) if max_degree else 1
    diagnostics = {
        "orphan": sorted(node.id for node in graph.nodes if degrees.get(node.id, 0) == 0),
        "missing": sorted(node.id for node in graph.nodes if not node.exists),
        "hub": sorted(
            node.id
            for node in graph.nodes
            if degrees.get(node.id, 0) >= hub_threshold and degrees.get(node.id, 0) > 1
        ),
    }
    return {
        "nodes": [
            {
                **asdict(node),
                "degree": degrees.get(node.id, 0),
            }
            for node in graph.nodes
        ],
        "edges": _dedupe_graph_edges(graph),
        "diagnostics": diagnostics,
    }


def create_app(
    *,
    notes_dir: Path,
    panel_token: str,
    frontend_dir: Path | None = None,
    open_reader: Callable[[Path, str], None] | None = None,
    wiki_dir: Path | None = None,
    ingest_runner: Callable[..., Path | None] | None = None,
    consume_panel_route: Callable[[], str | tuple[str, dict[str, str]] | None] | None = None,
) -> FastAPI:
    notes_dir = Path(notes_dir)
    default_wiki_dir = getattr(app_config, "WIKI_DIR", notes_dir.parent / "wiki")
    wiki_dir = Path(wiki_dir) if wiki_dir is not None else Path(default_wiki_dir)
    ingest_runner = ingest_runner or discuss_and_ingest
    ingest_sessions: dict[str, IngestSession] = {}

    app = FastAPI(title="myLibrary panel API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_token(x_panel_token: str | None = Header(default=None)) -> None:
        if not panel_token or x_panel_token != panel_token:
            raise HTTPException(status_code=401, detail="Invalid panel token")

    def require_media_token(
        token: str | None = Query(default=None),
        x_panel_token: str | None = Header(default=None),
    ) -> None:
        if not panel_token or (x_panel_token != panel_token and token != panel_token):
            raise HTTPException(status_code=401, detail="Invalid panel token")

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request, exc: HTTPException):
        code = "unauthorized" if exc.status_code == 401 else "request_error"
        return error_response(code, str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_request, exc: Exception):
        _log.exception("Unhandled panel API error")
        return error_response(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
            status_code=500,
        )

    @app.get("/api/health")
    def health(_auth: None = Depends(require_token)):
        return ok({"status": "ok"})

    @app.get("/api/panel-route")
    def panel_route(_auth: None = Depends(require_token)):
        command = consume_panel_route() if consume_panel_route is not None else None
        route: str | None = None
        params: dict[str, str] = {}
        if isinstance(command, tuple):
            route, params = command
        else:
            route = command
        return ok({"route": route, "params": params})

    @app.post("/api/notes")
    def create_note(payload: NotePayload, _auth: None = Depends(require_token)):
        if not payload.content.strip():
            raise HTTPException(status_code=400, detail="Note content is empty")
        title = payload.title.strip() if payload.title else None
        markdown = text_to_markdown(payload.content, title=title)
        path = save_note(markdown, title=title, notes_dir=notes_dir)
        return ok(_file_payload(path))

    @app.post("/api/assets")
    def upload_asset(file: UploadFile = File(...), _auth: None = Depends(require_token)):
        tmp = _copy_upload_to_temp(file)
        try:
            return ok(_save_asset_upload(tmp, original_name=file.filename or tmp.name, notes_dir=notes_dir))
        finally:
            tmp.unlink(missing_ok=True)

    @app.post("/api/uploads/preview")
    def upload_preview(file: UploadFile = File(...), _auth: None = Depends(require_token)):
        tmp = _copy_upload_to_temp(file)
        try:
            suffix = Path(file.filename or tmp.name).suffix.lower()
            converter = UPLOAD_CONVERTERS.get(suffix)
            if converter is None:
                raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")
            text = converter(tmp)
            return ok({"name": file.filename or tmp.name, "preview": text[:500]})
        except OCRUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            tmp.unlink(missing_ok=True)

    @app.post("/api/uploads")
    def upload_file(file: UploadFile = File(...), _auth: None = Depends(require_token)):
        tmp = _copy_upload_to_temp(file)
        try:
            path = _save_uploaded_file(tmp, original_name=file.filename or tmp.name, notes_dir=notes_dir)
            return ok(_file_payload(path))
        except OCRUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            tmp.unlink(missing_ok=True)

    @app.get("/api/inbox")
    def inbox(_auth: None = Depends(require_token)):
        items = [_file_payload(path) for path in _find_uningested_notes(notes_dir, wiki_dir)]
        return ok({"items": items})

    @app.get("/api/inbox/preview")
    def inbox_preview(path: str = Query(...), _auth: None = Depends(require_token)):
        note = _resolve_note_path(path, notes_dir)
        return ok({"path": str(note), "name": note.name, "content": _read_inbox_preview(note)})

    @app.delete("/api/inbox")
    def delete_inbox_item(path: str = Query(...), _auth: None = Depends(require_token)):
        note = _resolve_note_path(path, notes_dir)
        inbox_paths = {item.resolve() for item in _find_uningested_notes(notes_dir, wiki_dir)}
        if note.resolve() not in inbox_paths:
            raise HTTPException(status_code=404, detail="Inbox item not found")
        payload = _file_payload(note)
        delete_note(note)
        return ok(payload)

    @app.get("/api/search")
    def search(
        q: str = "",
        mode: SearchMode = "fulltext",
        _auth: None = Depends(require_token),
    ):
        if mode == "recent":
            paths = list_recent(notes_dir=notes_dir)
            results = [_note_payload(path, notes_dir=notes_dir) for path in paths]
        elif mode == "favorite":
            results = _meta_search_results(mode=mode, query=q, notes_dir=notes_dir, wiki_dir=wiki_dir)
        elif mode == "tag":
            results = _meta_search_results(mode=mode, query=q, notes_dir=notes_dir, wiki_dir=wiki_dir)
        else:
            hits = search_notes_ranked(q, notes_dir=notes_dir) if q.strip() else []
            results = [
                _note_payload(hit["file"], snippet=hit["snippet"], notes_dir=notes_dir)
                for hit in hits
            ]
        return ok({"mode": mode, "query": q, "results": results})

    @app.get("/api/notes/preview")
    def preview(
        path: str = Query(...),
        _auth: None = Depends(require_token),
    ):
        note = _resolve_note_path(path, notes_dir)
        add_recent(note, notes_dir=notes_dir)
        return ok({
            "scope": "notes",
            "path": str(note),
            "relative_path": _relative_posix(note, notes_dir),
            "name": note.name,
            "kind": "markdown",
            "content": note.read_text(encoding="utf-8"),
            "favorite": is_favorite(note, notes_dir=notes_dir),
            "tags": get_tags(note, notes_dir=notes_dir),
        })

    @app.get("/api/library/files")
    def library_files(
        scope: LibraryScope = "notes",
        q: str = "",
        _auth: None = Depends(require_token),
    ):
        if scope == "wiki":
            base = wiki_dir
            files = _iter_wiki_files(wiki_dir)
        else:
            base = notes_dir
            files = _iter_source_files(notes_dir)
        items = [
            _library_file_payload_with_meta(path, scope=scope, base=base, notes_dir=notes_dir)
            for path in files
            if _matches_library_query(path, base=base, query=q)
        ]
        payload: dict[str, Any] = {"scope": scope, "query": q, "items": items}
        if scope == "wiki":
            payload["groups"] = _wiki_group_payload(items)
        return ok(payload)

    @app.get("/api/library/files/preview")
    def library_preview(
        scope: LibraryScope = "notes",
        path: str = Query(...),
        _auth: None = Depends(require_token),
    ):
        if scope == "wiki":
            base = wiki_dir
            target = _resolve_wiki_path(path, wiki_dir)
            content = target.read_text(encoding="utf-8")
            render_mode = "markdown"
            media_url = ""
            html_content = ""
        else:
            base = notes_dir
            target = _resolve_note_path(path, notes_dir)
            if target.suffix.lower() not in SOURCE_VIEW_SUFFIXES:
                raise HTTPException(status_code=404, detail="Source file not found")
            render_mode = _source_render_mode(target)
            media_url = _raw_media_url(scope, target, base)
            html_content = _docx_to_html(target) if render_mode == "docx_html" else ""
            content = "" if render_mode != "download" else _source_preview_text(target)
        return ok({
            "scope": scope,
            "path": str(target) if scope == "notes" else _relative_posix(target, base),
            "relative_path": _relative_posix(target, base),
            "name": target.name,
            "kind": _library_kind(target, scope=scope, base=base),
            "render_mode": render_mode,
            "content_type": _media_type(target),
            "media_url": media_url,
            "html": html_content,
            "content": content,
            "favorite": is_favorite(target, notes_dir=notes_dir),
            "tags": get_tags(target, notes_dir=notes_dir),
        })

    @app.get("/api/library/files/raw")
    def library_raw(
        scope: LibraryScope = "notes",
        path: str = Query(...),
        _auth: None = Depends(require_media_token),
    ):
        if scope == "wiki":
            target = _resolve_wiki_path(path, wiki_dir)
        else:
            target = _resolve_note_path(path, notes_dir)
            if target.suffix.lower() not in SOURCE_VIEW_SUFFIXES:
                raise HTTPException(status_code=404, detail="Source file not found")
        return FileResponse(
            target,
            media_type=_media_type(target),
            filename=target.name,
            content_disposition_type="inline",
        )

    @app.post("/api/notes/open-reader")
    def open_reader_endpoint(
        payload: OpenReaderPayload,
        _auth: None = Depends(require_token),
    ):
        note = _resolve_note_path(payload.path, notes_dir)
        if open_reader is None:
            raise HTTPException(status_code=501, detail="Reader callback is not configured")
        open_reader(note, payload.query)
        return ok({"opened": True})

    @app.get("/api/meta")
    def meta(
        path: str = Query(...),
        scope: LibraryScope = "notes",
        _auth: None = Depends(require_token),
    ):
        note = _meta_target(scope, path, notes_dir=notes_dir, wiki_dir=wiki_dir)
        return ok({
            "favorite": is_favorite(note, notes_dir=notes_dir),
            "tags": get_tags(note, notes_dir=notes_dir),
        })

    @app.post("/api/meta/favorite")
    def update_favorite(
        payload: FavoritePayload,
        _auth: None = Depends(require_token),
    ):
        note = _meta_target(payload.scope, payload.path, notes_dir=notes_dir, wiki_dir=wiki_dir)
        return ok({"favorite": set_favorite(note, payload.favorite, notes_dir=notes_dir)})

    @app.post("/api/meta/tags")
    def update_tags(payload: TagsPayload, _auth: None = Depends(require_token)):
        note = _meta_target(payload.scope, payload.path, notes_dir=notes_dir, wiki_dir=wiki_dir)
        return ok({"tags": set_tags(note, payload.tags, notes_dir=notes_dir)})

    @app.post("/api/wiki/query")
    def wiki_query(payload: QueryPayload, _auth: None = Depends(require_token)):
        def generate():
            event_q: queue.Queue[dict[str, Any] | None] = queue.Queue()

            def worker() -> None:
                try:
                    config = load_llm_config()

                    def on_meta(meta: Any) -> None:
                        event_q.put({"type": "meta", "meta": _plain_object(meta)})

                    def on_thinking(text: str) -> None:
                        event_q.put({"type": "thinking", "text": text})

                    for chunk in query_wiki(
                        payload.question,
                        config,
                        wiki_dir=wiki_dir,
                        notes_dir=notes_dir,
                        on_meta=on_meta,
                        on_thinking=on_thinking,
                    ):
                        event_q.put({"type": "chunk", "text": chunk})
                    event_q.put({"type": "done"})
                except Exception as exc:
                    event_q.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
                finally:
                    event_q.put(None)

            threading.Thread(target=worker, daemon=True).start()
            while True:
                try:
                    event = event_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if event is None:
                    break
                yield _event(event)

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    @app.post("/api/wiki/query/save")
    def wiki_query_save(payload: QuerySavePayload, _auth: None = Depends(require_token)):
        path = save_query_answer_as_wiki_page(
            payload.question,
            payload.answer,
            payload.used_pages,
            answer_type=payload.answer_type,
            raw_sources=payload.raw_sources,
        )
        return ok(_file_payload(path))

    @app.get("/api/wiki/graph")
    def wiki_graph(_auth: None = Depends(require_token)):
        return ok(_graph_payload(parse_wiki_graph(wiki_dir)))

    @app.post("/api/wiki/lint")
    def wiki_lint(_auth: None = Depends(require_token)):
        def generate():
            try:
                config = load_llm_config()
                findings: list[LintFinding] = []
                for count, finding in enumerate(lint_wiki(wiki_dir, config), start=1):
                    findings.append(finding)
                    yield _event({"type": "progress", "count": count})
                    yield _event({"type": "finding", "finding": _finding_payload(finding)})
                report = save_lint_report(wiki_dir, findings)
                append_wiki_log(
                    wiki_dir,
                    "lint",
                    "Health check",
                    f"{len(findings)} issues; report: {report.name}",
                )
                yield _event({"type": "done", "report": str(report), "count": len(findings)})
            except Exception as exc:
                yield _event({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    @app.post("/api/wiki/lint/fix")
    def wiki_lint_fix(payload: LintFixPayload, _auth: None = Depends(require_token)):
        findings = [_finding_from_payload(item) for item in payload.findings]
        fixed = auto_fix(wiki_dir, findings)
        refreshed = [_finding_payload(finding) for finding in static_checks(wiki_dir)]
        return ok({"fixed": fixed, "findings": refreshed})

    @app.post("/api/wiki/lint/fix-preview")
    def wiki_lint_fix_preview(payload: LintFixPayload, _auth: None = Depends(require_token)):
        try:
            findings = [_finding_from_payload(item) for item in payload.findings]
            fixed = auto_fix(wiki_dir, findings)
            refreshed = list(static_checks(wiki_dir))
            preview_findings = _selected_findings_after_refresh(findings, refreshed)
            llm_findings = [finding for finding in findings if finding.source == "llm"]
            returned_findings = refreshed + llm_findings
            preview = None
            llm_error = None
            config = load_llm_config()
            if preview_findings and getattr(config, "api_key", ""):
                try:
                    preview = build_llm_fix_preview(wiki_dir, preview_findings, config)
                except httpx.TimeoutException as exc:
                    llm_error = f"大模型修复预览超时: {exc}"
            return ok({
                "fixed": fixed,
                "findings": [_finding_payload(finding) for finding in returned_findings],
                "preview": asdict(preview) if preview is not None else None,
                "llm_available": bool(getattr(config, "api_key", "")),
                "llm_error": llm_error,
            })
        except Exception as exc:
            return error_response(
                "llm_fix_preview_failed",
                f"{type(exc).__name__}: {exc}",
                status_code=502,
            )

    @app.post("/api/wiki/lint/apply-preview")
    def wiki_lint_apply_preview(payload: LintApplyPreviewPayload, _auth: None = Depends(require_token)):
        try:
            preview = _fix_preview_from_payload(payload.preview)
            written = apply_llm_fix_preview(wiki_dir, preview)
            rebuild_index_from_disk(wiki_dir)
            refreshed = [_finding_payload(finding) for finding in static_checks(wiki_dir)]
            return ok({"written": written, "findings": refreshed})
        except Exception as exc:
            return error_response(
                "llm_fix_apply_failed",
                f"{type(exc).__name__}: {exc}",
                status_code=409,
            )

    @app.post("/api/wiki/lint/rebuild-index")
    def wiki_lint_rebuild_index(_auth: None = Depends(require_token)):
        rebuild_index_from_disk(wiki_dir)
        refreshed = [_finding_payload(finding) for finding in static_checks(wiki_dir)]
        return ok({"findings": refreshed})

    @app.post("/api/wiki/ingest")
    def wiki_ingest(payload: IngestPayload, _auth: None = Depends(require_token)):
        if not getattr(app_config, "LLM_API_KEY", ""):
            return error_response(
                "llm_unavailable",
                "LLM_API_KEY is not configured",
                status_code=503,
            )
        if not payload.paths:
            raise HTTPException(status_code=400, detail="No ingest paths provided")
        paths = [_resolve_note_path(raw, notes_dir) for raw in payload.paths]
        session_id = uuid.uuid4().hex
        ingest_sessions[session_id] = IngestSession(paths)
        return ok({"session_id": session_id, "count": len(paths)})

    def _start_ingest_session(session: IngestSession) -> None:
        with session.lock:
            if session.started:
                return
            session.started = True

        def worker() -> None:
            ok_count = 0
            err_count = 0
            config = load_llm_config()
            total = len(session.paths)
            for idx, path in enumerate(session.paths, start=1):
                session.chat_q.put(("__NOTE__", path, idx, total))
                try:
                    result = ingest_runner(
                        path,
                        config,
                        wiki_dir=wiki_dir,
                        chat_q=session.chat_q,
                        user_q=session.user_q,
                    )
                    if result is not None:
                        ok_count += 1
                except Exception as exc:
                    err_count += 1
                    session.chat_q.put(("__FATAL__", f"{type(exc).__name__}: {exc}"))
                    break
            session.chat_q.put(("__SESSION_DONE__", ok_count, err_count))

        threading.Thread(target=worker, daemon=True).start()

    def _ingest_event(item: Any) -> dict[str, Any] | None:
        if isinstance(item, tuple) and item and item[0] == "__NOTE__":
            _, path, index, total = item
            return {
                "type": "note",
                "path": str(path),
                "name": Path(path).name,
                "index": index,
                "total": total,
            }
        if isinstance(item, tuple) and item and item[0] == "__STAGE__":
            _, stage, status = item
            return {"type": "stage", "stage": stage, "status": status}
        if isinstance(item, tuple) and item and item[0] == "__CANDIDATES__":
            return {"type": "candidates", "candidates": item[1]}
        if isinstance(item, tuple) and item and item[0] == "__PLAN__":
            return {"type": "plan", "actions": item[1]}
        if isinstance(item, tuple) and item and item[0] == "__AWAIT_INPUT__":
            _, mode, actions = item
            return {"type": "input_request", "mode": mode, "actions": actions}
        if isinstance(item, tuple) and item and item[0] == "__FATAL__":
            return {"type": "error", "message": item[1]}
        if isinstance(item, tuple) and item and item[0] == "__SESSION_DONE__":
            return {"type": "session_done", "ok": item[1], "error": item[2]}
        if item == "__SELECT_DEFAULT__":
            return {"type": "select"}
        if item == "__AWAIT_INPUT__":
            return {"type": "input_request"}
        if item == "__READY__":
            return {"type": "ready"}
        if item == "__DONE__":
            return {"type": "done"}
        if item == "__ERROR__":
            return {"type": "error", "message": "提取失败"}
        if isinstance(item, str):
            return {"type": "chunk", "text": item}
        return None

    @app.websocket("/api/wiki/ingest/{session_id}")
    async def wiki_ingest_ws(websocket: WebSocket, session_id: str):
        token = websocket.query_params.get("token") or websocket.headers.get("x-panel-token")
        if not panel_token or token != panel_token:
            await websocket.close(code=1008)
            return
        session = ingest_sessions.get(session_id)
        if session is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        _start_ingest_session(session)

        async def receive_inputs() -> None:
            while True:
                data = await websocket.receive_json()
                kind = data.get("type")
                if kind == "input":
                    session.user_q.put(str(data.get("text", "")))
                elif kind in ("command", "candidate_update", "plan_update"):
                    session.user_q.put(dict(data))
                elif kind == "confirm":
                    session.user_q.put("confirm")
                elif kind == "cancel":
                    session.user_q.put("__CANCEL__")

        receiver = asyncio.create_task(receive_inputs())
        try:
            while True:
                item = await asyncio.to_thread(session.chat_q.get)
                event = _ingest_event(item)
                if event is not None:
                    await websocket.send_json(event)
                if isinstance(item, tuple) and item and item[0] == "__SESSION_DONE__":
                    break
        finally:
            receiver.cancel()

    if frontend_dir is not None and Path(frontend_dir).exists():
        app.mount(
            "/",
            StaticFiles(directory=str(frontend_dir), html=True),
            name="frontend",
        )

    return app
