from urllib.error import URLError

import httpx
import pytest

from web_panel.server import PanelApiServer, _wait_until_http_ready


def test_panel_api_server_starts_on_loopback_random_port(tmp_path):
    server = PanelApiServer(notes_dir=tmp_path, panel_token="secret")
    server.start()
    try:
        assert server.base_url.startswith("http://127.0.0.1:")
        with httpx.Client(trust_env=False, timeout=5) as client:
            response = client.get(
                f"{server.base_url}/api/health",
                headers={"X-Panel-Token": "secret"},
            )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ok"
    finally:
        server.stop()


def test_panel_api_server_exposes_single_use_route_command(tmp_path):
    server = PanelApiServer(notes_dir=tmp_path, panel_token="secret")
    server.start()
    try:
        server.set_panel_route("ingest", params={"paths": "[\"note.md\"]"})
        with httpx.Client(trust_env=False, timeout=5) as client:
            first = client.get(
                f"{server.base_url}/api/panel-route",
                headers={"X-Panel-Token": "secret"},
            )
            second = client.get(
                f"{server.base_url}/api/panel-route",
                headers={"X-Panel-Token": "secret"},
            )
        assert first.status_code == 200
        assert first.json()["data"]["route"] == "ingest"
        assert first.json()["data"]["params"] == {"paths": "[\"note.md\"]"}
        assert second.json()["data"]["route"] is None
        assert second.json()["data"]["params"] == {}
    finally:
        server.stop()


def test_wait_until_http_ready_retries_until_health_endpoint_accepts(monkeypatch):
    calls: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def opener(request, timeout):
        calls.append(request.full_url)
        assert request.headers["X-panel-token"] == "secret"
        assert timeout == 1
        if len(calls) == 1:
            raise URLError("not ready")
        return Response()

    ticks = iter([0.0, 0.1, 0.2])
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _wait_until_http_ready(
        "http://127.0.0.1:12345",
        "secret",
        timeout_s=1,
        opener=opener,
    )

    assert calls == [
        "http://127.0.0.1:12345/api/health",
        "http://127.0.0.1:12345/api/health",
    ]


def test_panel_api_server_clears_port_when_start_health_check_fails(monkeypatch, tmp_path):
    def fail_health_check(*_args, **_kwargs):
        raise TimeoutError("not reachable")

    monkeypatch.setattr("web_panel.server._wait_until_http_ready", fail_health_check)

    server = PanelApiServer(notes_dir=tmp_path, panel_token="secret")

    with pytest.raises(TimeoutError):
        server.start()

    with pytest.raises(RuntimeError):
        _ = server.base_url


def test_panel_api_server_passes_activity_callback_to_app(monkeypatch, tmp_path):
    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("web_panel.server.create_app", fake_create_app)

    def on_activity():
        pass

    server = PanelApiServer(
        notes_dir=tmp_path,
        panel_token="secret",
        on_panel_activity=on_activity,
    )

    app = server._create_app()

    assert app is not None
    assert captured["on_panel_activity"] is on_activity
