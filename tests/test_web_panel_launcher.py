import importlib
import subprocess
import sys
from urllib.error import URLError

from web_panel.launcher import (
    build_panel_url,
    default_frontend_dir,
    frontend_available,
    launch_web_panel_process,
    react_panels_enabled,
    webview_available,
    send_web_panel_control,
)
from web_panel.webview_entry import WebviewController, run_webview, wait_until_page_ready


def test_react_panels_enabled_defaults_off_in_source_and_on_when_frozen(monkeypatch):
    monkeypatch.delenv("MYLIBRARY_REACT_PANELS", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert react_panels_enabled() is False

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert react_panels_enabled() is True

    monkeypatch.setenv("MYLIBRARY_REACT_PANELS", "1")
    assert react_panels_enabled() is True

    monkeypatch.setenv("MYLIBRARY_REACT_PANELS", "0")
    assert react_panels_enabled() is False


def test_build_panel_url_uses_hash_route_and_token():
    url = build_panel_url("http://127.0.0.1:54321", "search", "secret token")

    assert url == "http://127.0.0.1:54321/#/search?token=secret+token"


def test_send_web_panel_control_can_pass_route(monkeypatch):
    calls: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            assert timeout == 1
            return Response()

    monkeypatch.setattr("web_panel.launcher.build_opener", lambda *_args: Opener())

    assert send_web_panel_control(12345, "show", route="chat")
    assert calls == ["http://127.0.0.1:12345/show?route=chat"]


def test_frontend_available_requires_index_html(tmp_path):
    assert frontend_available(tmp_path) is False

    (tmp_path / "index.html").write_text("<div></div>", encoding="utf-8")

    assert frontend_available(tmp_path) is True


def test_default_frontend_dir_prefers_pyinstaller_bundle(monkeypatch, tmp_path):
    bundle_dir = tmp_path / "_internal"
    bundled_frontend = bundle_dir / "frontend"
    bundled_frontend.mkdir(parents=True)
    (bundled_frontend / "index.html").write_text("<div></div>", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "myLibrary.exe"))

    assert default_frontend_dir() == bundled_frontend


def test_webview_available_checks_import(monkeypatch):
    real_import = importlib.import_module

    def import_webview(name):
        if name == "webview":
            return object()
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", import_webview)
    assert webview_available() is True

    def missing_webview(name):
        if name == "webview":
            raise ModuleNotFoundError("No module named 'webview'")
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", missing_webview)
    assert webview_available() is False


def test_launch_web_panel_process_uses_app_entry(monkeypatch, tmp_path):
    app_path = tmp_path / "app.py"
    app_path.write_text("", encoding="utf-8")
    log_path = tmp_path / "web_panel.log"
    calls: list[list[str]] = []
    streams = {}

    class FakeProcess:
        pass

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        streams["stdout"] = kwargs["stdout"]
        streams["stderr"] = kwargs["stderr"]
        assert kwargs["stdout"] is not subprocess.DEVNULL
        assert kwargs["stderr"] is kwargs["stdout"]
        kwargs["stdout"].write(b"panel starting\n")
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = launch_web_panel_process(
        "http://127.0.0.1:1/#/search",
        "Search",
        app_path=app_path,
        log_path=log_path,
    )

    assert isinstance(result, FakeProcess)
    assert calls == [[
        sys.executable,
        str(app_path),
        "--web-panel",
        "http://127.0.0.1:1/#/search",
        "--title",
        "Search",
    ]]
    assert streams["stdout"].closed is True
    assert log_path.read_bytes() == b"panel starting\n"


def test_launch_web_panel_process_passes_control_port(monkeypatch, tmp_path):
    app_path = tmp_path / "app.py"
    app_path.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    class FakeProcess:
        pass

    def fake_popen(cmd, **_kwargs):
        calls.append(cmd)
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    launch_web_panel_process(
        "http://127.0.0.1:1/#/search",
        "Search",
        app_path=app_path,
        control_port=54321,
        log_path=tmp_path / "web_panel.log",
    )

    assert "--control-port" in calls[0]
    assert calls[0][-2:] == ["--control-port", "54321"]


def test_run_webview_returns_failure_when_pywebview_is_missing(monkeypatch):
    real_import = importlib.import_module

    def fake_import(name):
        if name == "webview":
            raise ModuleNotFoundError("No module named 'webview'")
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    assert run_webview("http://127.0.0.1:1", "Search") == 1


def test_run_webview_keeps_native_frame_and_avoids_js_window_api(monkeypatch):
    calls = {}

    class FakeWindow:
        class Events:
            def __init__(self):
                self.closing = self

            def __iadd__(self, _handler):
                return self

        events = Events()

    class FakeWebview:
        settings = {"DRAG_REGION_SELECTOR": ".pywebview-drag-region"}

        def create_window(self, *args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs
            calls["settings"] = dict(self.settings)
            return FakeWindow()

        def start(self):
            calls["started"] = True

    monkeypatch.setattr(importlib, "import_module", lambda name: FakeWebview())
    monkeypatch.setattr("web_panel.webview_entry.wait_until_page_ready", lambda url: None)

    assert run_webview("http://127.0.0.1:1/#/search", "Search", control_port=12345) == 0
    assert calls["kwargs"]["frameless"] is False
    assert calls["kwargs"]["easy_drag"] is False
    assert calls["kwargs"]["background_color"] == "#0A1428"
    assert "js_api" not in calls["kwargs"]
    assert calls["settings"]["DRAG_REGION_SELECTOR"] == ".pywebview-drag-region"


def test_run_webview_logs_runtime_exception(monkeypatch, caplog):
    class FakeWebview:
        def create_window(self, *_args, **_kwargs):
            raise RuntimeError("webview crashed")

        def start(self):
            raise AssertionError("should not start after create_window failure")

    monkeypatch.setattr(importlib, "import_module", lambda name: FakeWebview())
    monkeypatch.setattr("web_panel.webview_entry.wait_until_page_ready", lambda url: None)

    assert run_webview("http://127.0.0.1:1/#/lint", "Lint") == 3
    assert "Web panel crashed" in caplog.text
    assert "webview crashed" in caplog.text


def test_wait_until_page_ready_strips_hash_and_retries(monkeypatch):
    calls: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def opener(request, timeout):
        calls.append(request.full_url)
        assert timeout == 1
        if len(calls) == 1:
            raise URLError("not ready")
        return Response()

    ticks = iter([0.0, 0.1, 0.2])
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    wait_until_page_ready(
        "http://127.0.0.1:12345/#/search?token=secret",
        timeout_s=1,
        opener=opener,
    )

    assert calls == [
        "http://127.0.0.1:12345/",
        "http://127.0.0.1:12345/",
    ]


def test_webview_controller_queues_route_without_touching_webview_ui():
    calls: list[str] = []

    class FakeWindow:
        def destroy(self):
            calls.append("destroy")

    controller = WebviewController()
    controller.attach(FakeWindow())

    assert controller.on_closing() is None
    assert calls == []

    assert controller.show("chat") is True
    assert calls == []
    assert controller.consume_route() == "chat"
    assert controller.consume_route() is None

    assert controller.shutdown() is True
    assert calls[-1] == "destroy"
