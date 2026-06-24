from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_index_does_not_load_external_fonts():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_search_route_loads_recent_without_auto_preview():
    source = (ROOT / "frontend" / "src" / "pages" / "SearchPage.tsx").read_text(encoding="utf-8")

    assert "runSearch('recent', '', false)" in source


def test_main_window_schedules_react_panel_prewarm():
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "_schedule_react_panel_prewarm" in source
    assert "_prewarm_react_panel" in source
    assert "self.root.after(250, self._prewarm_react_panel)" in source


def test_main_window_can_reuse_live_web_panel_without_hiding_closed_windows():
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "WEB_PANEL_IDLE_MS" in source
    assert "_show_cached_web_panel" in source
    assert "_schedule_web_panel_process_watch" in source
    assert "_handle_web_panel_exit" in source
    assert "logs/web_panel.log" in source
    assert "_schedule_web_panel_idle_cleanup" in source
    assert "_close_cached_web_panel" in source
    assert "set_panel_route(route, params=params)" in source
    assert "send_web_panel_control" not in source
    assert "reserve_loopback_port" not in source


def test_drag_drop_routes_to_react_ingest_only_when_web_panel_is_live():
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    drop_body = source.split("def _on_files_dropped", 1)[1].split("    # ── ingest feedback", 1)[0]

    assert "_handle_dropped_saved_paths(saved_paths)" in drop_body
    assert "_ingest_with_animation(saved_paths)" not in drop_body
    assert "已保存到暂存箱" in source
    assert "_route_live_web_panel(" in source
    assert "\"ingest\"" in source
    assert "json.dumps([str(p) for p in saved_paths])" in source


def test_panel_shell_uses_static_scanlines_for_webview_performance():
    source = (ROOT / "frontend" / "src" / "components" / "PanelShell.tsx").read_text(encoding="utf-8")

    assert "SheikahScanlines animated" not in source
    assert "<SheikahScanlines opacity={0.06}" in source


def test_panel_shell_does_not_render_large_illustration_layer_by_default():
    source = (ROOT / "frontend" / "src" / "components" / "PanelShell.tsx").read_text(encoding="utf-8")

    assert "Illustration" not in source
    for page_path in (ROOT / "frontend" / "src" / "pages").glob("*Page.tsx"):
        page_source = page_path.read_text(encoding="utf-8")
        assert "illustration=" not in page_source


def test_main_window_routes_all_regular_tabs_to_react_panel():
    source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert "InputTab: \"input\"" in source
    assert "UploadTab: \"upload\"" in source
    assert "SearchTab: \"search\"" in source
    assert "ChatTab: \"chat\"" in source
    assert "GraphTab: \"graph\"" in source
    assert "LintTab: \"lint\"" in source


def test_frontend_declares_all_regular_panel_routes():
    expected_pages = {
        "InputPage.tsx": "SHEIKAH INPUT",
        "UploadPage.tsx": "SHEIKAH UPLOAD",
        "SearchPage.tsx": "SHEIKAH SEARCH",
        "ChatPage.tsx": "SHEIKAH CHAT",
        "GraphPage.tsx": "SHEIKAH GRAPH",
        "LintPage.tsx": "SHEIKAH LINT",
        "IngestPage.tsx": "SHEIKAH INGEST",
    }

    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    for route in ["/input", "/upload", "/search", "/chat", "/graph", "/lint", "/ingest"]:
        assert route in app_source
    for filename, marker in expected_pages.items():
        page_source = (ROOT / "frontend" / "src" / "pages" / filename).read_text(encoding="utf-8")
        assert marker in page_source


def test_lint_page_auto_fix_button_uses_actionable_findings_not_fixable_only():
    source = (ROOT / "frontend" / "src" / "pages" / "LintPage.tsx").read_text(encoding="utf-8")

    assert "const keyedFindings = useMemo" in source
    assert "const actionable = keyedFindings.filter" in source
    assert "const selectedFindings = actionable.filter" in source
    assert "disabled={selectedFindings.length === 0 || running}" in source
    assert "disabled={fixable.length === 0 || running}" not in source
    assert "previewLintFix(token, selectedFindings)" in source
    assert "applyLintFixPreview" in source


def test_lint_page_allows_selecting_fix_targets():
    source = (ROOT / "frontend" / "src" / "pages" / "LintPage.tsx").read_text(encoding="utf-8")

    assert "selectedFindingKeys" in source
    assert "toggleFindingSelection" in source
    assert "selectAllActionable" in source
    assert "clearSelection" in source
    assert 'type="checkbox"' in source


def test_lint_preview_shows_file_diff_and_original_findings():
    source = (ROOT / "frontend" / "src" / "pages" / "LintPage.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "buildSideBySideDiff" in source
    assert "previewIssuesByFile" in source
    assert "acceptedPreviewPaths" in source
    assert "togglePreviewAcceptance" in source
    assert "acceptedPreviewFiles" in source
    assert "openPreviewFiles" in source
    assert "查看 diff" in source
    assert "源文件" in source
    assert "新文件" in source
    assert "接受此文件" in source
    assert "applyLintFixPreview(token, acceptedPreview)" in source
    assert "原体检问题" in source
    assert 'className="side-by-side-diff"' in source
    assert 'className="diff-pane source"' in source
    assert 'className="diff-pane updated"' in source
    assert ".side-by-side-diff" in styles
    assert ".diff-pane.source" in styles
    assert ".diff-pane.updated" in styles
    assert ".diff-row.add" in styles
    assert ".diff-row.remove" in styles


def test_ingest_page_buffers_streaming_log_updates():
    source = (ROOT / "frontend" / "src" / "pages" / "IngestPage.tsx").read_text(encoding="utf-8")

    assert "logBufferRef" in source
    assert "flushLog" in source
    assert "window.setTimeout(flushLog, 50)" in source
    append_body = source.split("function append(text: string)", 1)[1].split("\n  }\n", 1)[0]
    assert "setLog(" not in append_body


def test_ingest_page_exposes_input_when_backend_requests_it():
    source = (ROOT / "frontend" / "src" / "pages" / "IngestPage.tsx").read_text(encoding="utf-8")

    assert "input_request" in source
    assert "'input'" in source
    assert "const [inputText, setInputText]" in source
    assert "stage === 'chat' || stage === 'input' || stage === 'select'" in source
    assert "sendInput(inputText" in source


def test_react_shell_draws_zelda_titlebar_without_js_window_controls():
    shell = (ROOT / "frontend" / "src" / "components" / "PanelShell.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'className="app-titlebar"' in shell
    assert "window-control" not in shell
    assert "minimizeWindow" not in shell
    assert "closeWindow" not in shell
    assert "pywebview" not in api
    assert ".app-titlebar::after" in styles
    assert "--titlebar-height: 52px" in styles


def test_frontend_polls_panel_route_commands_without_pywebview_bridge():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "pollPanelRouteCommand" in app
    assert "window.setInterval" in app
    assert "command.params" in app
    assert "/panel-route" in api
    assert "window.pywebview" not in api


def test_frontend_request_handles_non_json_error_responses():
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "await response.text()" in api
    assert "JSON.parse(raw)" in api
    assert "Response was not JSON" in api


def test_frontend_stream_handles_non_json_error_responses():
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "parseNdjsonLine" in api
    assert "Stream response was not JSON" in api
    assert "await response.text()" in api.split("async function streamNdjson", 1)[1]


def test_lint_page_shows_llm_preview_timeout_as_status():
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    lint = (ROOT / "frontend" / "src" / "pages" / "LintPage.tsx").read_text(encoding="utf-8")

    assert "llm_error: string | null" in api
    assert "payload.llm_error" in lint
    assert "大模型修复预览失败" in lint


def test_lint_page_uses_operation_specific_loading_states():
    lint = (ROOT / "frontend" / "src" / "pages" / "LintPage.tsx").read_text(encoding="utf-8")

    assert "operation === 'checking'" in lint
    assert "setOperation('fixing')" in lint
    assert "setOperation('applying')" in lint
    assert "setOperation('rebuilding')" in lint
    assert 'Loading tip="Checking..."' not in lint
    assert "Loading tip={loadingTip}" in lint


def test_pyinstaller_uses_generated_app_icon():
    spec = (ROOT / "build.spec").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert 'icon="assets/app_icon.ico"' in spec
    assert "app_icon.png" in app
    assert "root.iconphoto" in app
    assert (ROOT / "assets" / "app_icon.ico").exists()
    assert (ROOT / "assets" / "app_icon.png").exists()
