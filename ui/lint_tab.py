"""Lint panel: one-click wiki health check with streamed results."""

import queue
import threading
import tkinter as tk

import httpx
from llm.client import LLMConfig, load_llm_config
from llm.wiki_lint import (
    LintFinding, LintFixPreview, lint_wiki, auto_fix,
    build_llm_fix_preview, apply_llm_fix_preview,
    save_lint_report, static_checks,
)
from llm.wiki_engine import _append_log
from ui.cartoon_widgets import (
    WHITE, SKY_LIGHT, TEXT_MAIN, TEXT_LIGHT,
    FONT_BODY, FONT_BODY_BOLD, FONT_INPUT, SPACING_MD, SPACING_LG,
    web_label, web_section, CartoonButton,
)

_SEV_EMOJI = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}
_SUGGESTION_KINDS = frozenset({"investigation", "next_source"})
_AUTO_FIX_ACTIONS = {
    "heading_drift": "会把 Sources/Related 等非标准标题改成标准二级标题。",
    "empty_link": "会删除整行空链接条目。",
}
_REBUILD_ACTION_KINDS = frozenset({
    "missing_index", "missing_index_section", "missing_file",
    "unindexed_file", "duplicate_index",
})


def _auto_action_text(f: LintFinding) -> str:
    if f.source == "llm":
        return "自动处理：可点击「自动修复」生成大模型修复预览，确认后再应用。"
    if f.fixable:
        detail = _AUTO_FIX_ACTIONS.get(f.kind, "会按内置规则处理此项。")
        return f"自动处理：可点击「自动修复」按钮，{detail}"
    if f.kind in _REBUILD_ACTION_KINDS:
        return "自动处理：可先点击「重建索引」按钮刷新目录；也可由「自动修复」生成大模型修复预览。"
    return "自动处理：可点击「自动修复」生成大模型修复预览，确认后再应用。"


def _auto_action_count(findings: list[LintFinding]) -> int:
    return sum(1 for f in findings if f.kind not in _SUGGESTION_KINDS)


class LintTab:
    def __init__(self, parent, bg_color: str = WHITE,
                 edge_color: str = SKY_LIGHT) -> None:
        self.frame = tk.Frame(parent, bg=bg_color)
        self._bg = bg_color
        self._edge = edge_color
        self._q: queue.Queue[tuple] = queue.Queue()
        self._running = False
        self._findings: list[LintFinding] = []
        self._pending_preview: LintFixPreview | None = None
        self._report_path: str = ""
        self._build()

    def _build(self) -> None:
        bg = self._bg
        top = tk.Frame(self.frame, bg=bg)
        top.pack(fill="x", pady=(0, SPACING_LG))

        web_label(top, "Wiki 健康检查", kind="section", accent="#F43F5E").pack(side="left")

        self._fix_btn = CartoonButton(
            top, "🔧 自动修复", command=self._on_fix, kind="pink", height=44,
        )
        self._fix_btn.pack_forget()

        self._rebuild_btn = CartoonButton(
            top, "📋 重建索引", command=self._on_rebuild_index, kind="pink", height=44,
        )
        self._rebuild_btn.pack_forget()

        self._apply_btn = CartoonButton(
            top, "✅ 应用预览", command=self._on_apply_preview, kind="pink", height=44,
        )
        self._apply_btn.pack_forget()

        self._run_btn = CartoonButton(
            top, "🩺 开始检查", command=self._on_run, kind="pink", height=44,
        )
        self._run_btn.pack(side="right")

        text_section = web_section(
            self.frame, None, bg_color=self._bg,
            border_color=self._edge, accent="#F43F5E",
        )
        text_section.pack(fill="both", expand=True, pady=(0, SPACING_MD))
        text_frame = text_section.content

        self._text = tk.Text(
            text_frame, wrap="word", font=FONT_INPUT,
            bg=WHITE, fg=TEXT_MAIN, relief="flat",
            state="disabled", padx=12, pady=10,
            spacing1=3, spacing3=3,
        )
        sb = tk.Scrollbar(text_frame, command=self._text.yview)
        self._text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        self._text.tag_config("error", foreground="#d9534f", font=FONT_BODY_BOLD)
        self._text.tag_config("warn", foreground="#f0ad4e", font=FONT_BODY_BOLD)
        self._text.tag_config("info", foreground="#5bc0de", font=FONT_BODY_BOLD)
        self._text.tag_config("loc", foreground="#8e44ad")
        self._text.tag_config("msg", foreground=TEXT_MAIN, font=FONT_BODY)
        self._text.tag_config("sug", foreground=TEXT_LIGHT)
        self._text.tag_config("header", foreground=TEXT_MAIN, font=FONT_BODY_BOLD)
        self._text.tag_config("p0_header", foreground="#d9534f", font=FONT_BODY_BOLD)
        self._text.tag_config("p1_header", foreground="#f0ad4e", font=FONT_BODY_BOLD)
        self._text.tag_config("p2_header", foreground="#5bc0de", font=FONT_BODY_BOLD)
        self._text.tag_config("suggest_header", foreground="#27ae60", font=FONT_BODY_BOLD)
        self._text.tag_config("suggest", foreground="#27ae60")

    def _on_run(self) -> None:
        if self._running:
            return
        self._running = True
        self._findings.clear()
        self._pending_preview = None
        self._report_path = ""
        self._fix_btn.pack_forget()
        self._rebuild_btn.pack_forget()
        self._apply_btn.pack_forget()
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", "正在检查...\n", "header")
        self._text.config(state="disabled")

        def _worker():
            import config as _cfg
            cfg = load_llm_config()
            count = 0
            all_findings: list[LintFinding] = []
            try:
                for finding in lint_wiki(_cfg.WIKI_DIR, cfg):
                    all_findings.append(finding)
                    count += 1
                    self._q.put(("progress", count))
                    self._q.put(("finding", finding))
                report = save_lint_report(_cfg.WIKI_DIR, all_findings)
                _append_log(
                    _cfg.WIKI_DIR, "lint", "Health check",
                    f"{count} issues; report: {report.name}",
                )
                self._q.put(("done", str(report)))
            except Exception as exc:
                self._q.put(("error", f"检查过程失败: {type(exc).__name__}: {exc}"))

        threading.Thread(target=_worker, daemon=True).start()
        self.frame.after(50, self._poll)

    def _poll(self) -> None:
        batch = 0
        while batch < 20:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "progress":
                self._update_progress(item[1])
            elif kind == "finding":
                self._findings.append(item[1])
            elif kind == "done":
                self._report_path = item[1]
                self._render_grouped()
                return
            elif kind == "error":
                self._show_error(item[1])
                return
            batch += 1
        self.frame.after(50, self._poll)

    def _update_progress(self, count: int) -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", f"正在检查... 已发现 {count} 个问题\n", "header")
        self._text.config(state="disabled")

    def _render_grouped(self, notice: str = "") -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        if notice:
            self._text.insert("end", f"{notice}\n\n", "header")

        by_priority: dict[str, list[LintFinding]] = {"P0": [], "P1": [], "P2": []}
        suggestions: list[LintFinding] = []
        for f in self._findings:
            if f.kind in _SUGGESTION_KINDS:
                suggestions.append(f)
            else:
                by_priority.setdefault(f.priority, []).append(f)

        sections = [
            ("P0", "P0: 需要立刻处理", "p0_header", by_priority.get("P0", [])),
            ("P1", "P1: 建议近期处理", "p1_header", by_priority.get("P1", [])),
            ("P2", "P2: 可逐步优化", "p2_header", by_priority.get("P2", [])),
        ]
        for _key, label, tag, items in sections:
            if not items:
                continue
            self._text.insert("end", f"━━━ {label} ({len(items)}) ━━━\n\n", tag)
            for f in items:
                self._append_finding(f)

        if suggestions:
            self._text.insert("end", "━━━ 🌱 探索建议 ━━━\n\n", "suggest_header")
            for f in suggestions:
                self._text.insert("end", f"💡 [{f.kind}] ", "suggest")
                self._text.insert("end", f"{f.message}\n", "suggest")
                if f.suggestion:
                    self._text.insert("end", f"  → {f.suggestion}\n", "sug")
                self._text.insert("end", "\n")

        p0 = len(by_priority.get("P0", []))
        p1 = len(by_priority.get("P1", []))
        p2 = len(by_priority.get("P2", []))
        fixable = _auto_action_count(self._findings)
        summary = f"✅ 检查完成: P0×{p0} P1×{p1} P2×{p2}"
        if fixable:
            summary += f" | {fixable} 可自动处理"
        if self._report_path:
            from pathlib import Path
            summary += f" | 报告已保存: {Path(self._report_path).name}"
        self._text.insert("end", f"\n{summary}\n", "header")

        self._text.config(state="disabled")
        self._text.see("end")
        self._running = False
        self._apply_btn.pack_forget()

        if fixable > 0:
            self._fix_btn.pack(side="right", padx=(8, 0))
        self._rebuild_btn.pack(side="right", padx=(8, 0))

    def _append_finding(self, f: LintFinding) -> None:
        emoji = _SEV_EMOJI.get(f.severity, "•")
        self._text.insert("end", f"{emoji} ", f.severity)
        self._text.insert("end", f"[{f.kind}] ", f.severity)
        self._text.insert("end", f"{f.location}", "loc")
        self._text.insert("end", f"\n  {f.message}\n", "msg")
        if f.suggestion:
            self._text.insert("end", f"  → {f.suggestion}\n", "sug")
        self._text.insert("end", f"  ⚙ {_auto_action_text(f)}\n", "sug")
        self._text.insert("end", "\n")

    def _show_error(self, message: str) -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", f"❌ {message}\n", "error")
        self._text.config(state="disabled")
        self._running = False

    def _on_fix(self) -> None:
        if self._running:
            return
        self._running = True
        self._pending_preview = None
        self._fix_btn.pack_forget()
        self._apply_btn.pack_forget()

        def _fix_worker():
            import config as _cfg
            try:
                cfg = load_llm_config()
                fixed = auto_fix(_cfg.WIKI_DIR, self._findings)
                new_findings = static_checks(_cfg.WIKI_DIR)
                llm_findings = [f for f in self._findings if f.source == "llm"]
                remaining = new_findings + llm_findings
                if remaining and cfg.api_key:
                    try:
                        preview = build_llm_fix_preview(_cfg.WIKI_DIR, remaining, cfg)
                    except httpx.TimeoutException as exc:
                        llm_error = f"大模型修复预览超时: {exc}"
                        self._q.put(("fix_done", fixed, remaining, bool(cfg.api_key), llm_error))
                    else:
                        self._q.put(("fix_preview", fixed, preview, remaining))
                else:
                    self._q.put(("fix_done", fixed, remaining, bool(cfg.api_key), None))
            except Exception as exc:
                self._q.put(("error", f"修复失败: {type(exc).__name__}: {exc}"))

        threading.Thread(target=_fix_worker, daemon=True).start()
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", "正在自动修复...\n", "header")
        self._text.config(state="disabled")
        self.frame.after(50, self._poll_fix)

    def _poll_fix(self) -> None:
        try:
            item = self._q.get_nowait()
        except queue.Empty:
            self.frame.after(50, self._poll_fix)
            return

        if item[0] == "fix_done":
            fixed_count = item[1]
            self._findings = item[2]
            has_llm = item[3] if len(item) > 3 else False
            llm_error = item[4] if len(item) > 4 else None
            if llm_error:
                notice = f"自动修复 {fixed_count} 项；{llm_error}"
            elif has_llm:
                notice = f"自动修复 {fixed_count} 项；大模型没有生成可应用的文件预览"
            else:
                notice = f"自动修复 {fixed_count} 项；未配置 LLM_API_KEY，剩余问题无法生成大模型预览"
            self._render_grouped(notice)
        elif item[0] == "fix_preview":
            fixed_count = item[1]
            preview = item[2]
            self._findings = item[3]
            self._pending_preview = preview
            self._render_fix_preview(fixed_count, preview)
        elif item[0] == "error":
            self._show_error(item[1])

    def _render_fix_preview(self, fixed_count: int, preview: LintFixPreview) -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", f"确定性自动修复 {fixed_count} 项。\n", "header")
        if preview.summary:
            self._text.insert("end", f"{preview.summary}\n", "msg")
        if not preview.files:
            self._text.insert("end", "大模型没有生成可应用的文件预览。\n", "header")
            self._text.config(state="disabled")
            self._running = False
            return

        self._text.insert("end", "\n大模型修复预览（尚未写入文件）\n\n", "header")
        for item in preview.files:
            self._text.insert("end", f"📄 {item.path}\n", "loc")
            if item.issues:
                self._text.insert("end", f"  处理问题: {', '.join(item.issues)}\n", "sug")
            old_preview = item.original[:260].replace("\n", " / ")
            new_preview = item.updated[:260].replace("\n", " / ")
            self._text.insert("end", f"  原内容: {old_preview}\n", "sug")
            self._text.insert("end", f"  新内容: {new_preview}\n\n", "msg")

        self._text.insert("end", "确认无误后点击「应用预览」写入文件。\n", "header")
        self._text.config(state="disabled")
        self._text.see("end")
        self._running = False
        self._apply_btn.pack(side="right", padx=(8, 0))

    def _on_apply_preview(self) -> None:
        if self._running or self._pending_preview is None:
            return
        self._running = True
        self._apply_btn.pack_forget()

        def _apply_worker():
            import config as _cfg
            from llm.wiki_engine import rebuild_index_from_disk
            try:
                written = apply_llm_fix_preview(_cfg.WIKI_DIR, self._pending_preview)
                rebuild_index_from_disk(_cfg.WIKI_DIR)
                new_findings = static_checks(_cfg.WIKI_DIR)
                self._q.put(("apply_done", written, new_findings))
            except Exception as exc:
                self._q.put(("error", f"应用预览失败: {type(exc).__name__}: {exc}"))

        threading.Thread(target=_apply_worker, daemon=True).start()
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", "正在应用大模型修复预览...\n", "header")
        self._text.config(state="disabled")
        self.frame.after(50, self._poll_apply)

    def _poll_apply(self) -> None:
        try:
            item = self._q.get_nowait()
        except queue.Empty:
            self.frame.after(50, self._poll_apply)
            return

        if item[0] == "apply_done":
            written = item[1]
            self._pending_preview = None
            self._findings = item[2]
            self._render_grouped(f"已应用大模型修复预览，写入 {written} 个文件。")
        elif item[0] == "error":
            self._show_error(item[1])

    def _on_rebuild_index(self) -> None:
        if self._running:
            return
        self._running = True
        self._rebuild_btn.pack_forget()
        self._apply_btn.pack_forget()

        def _rebuild_worker():
            import config as _cfg
            from llm.wiki_engine import rebuild_index_from_disk
            try:
                rebuild_index_from_disk(_cfg.WIKI_DIR)
                new_findings = static_checks(_cfg.WIKI_DIR)
                self._q.put(("rebuild_done", new_findings))
            except Exception as exc:
                self._q.put(("error", f"重建索引失败: {type(exc).__name__}: {exc}"))

        threading.Thread(target=_rebuild_worker, daemon=True).start()
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", "正在重建索引...\n", "header")
        self._text.config(state="disabled")
        self.frame.after(50, self._poll_rebuild)

    def _poll_rebuild(self) -> None:
        try:
            item = self._q.get_nowait()
        except queue.Empty:
            self.frame.after(50, self._poll_rebuild)
            return

        if item[0] == "rebuild_done":
            new_static = item[1]
            llm_findings = [f for f in self._findings if f.source == "llm"]
            self._findings = new_static + llm_findings
            self._text.config(state="normal")
            self._text.delete("1.0", "end")
            self._text.insert("end", "索引已重建，静态检查已刷新\n\n", "header")
            self._text.config(state="disabled")
            self._running = False
            self._render_grouped()
        elif item[0] == "error":
            self._show_error(item[1])
