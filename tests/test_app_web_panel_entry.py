import app


def test_main_routes_web_panel_mode_to_webview(monkeypatch):
    calls: list[tuple[str, str, int | None]] = []

    def fake_run_webview(url: str, title: str, control_port: int | None = None) -> int:
        calls.append((url, title, control_port))
        return 7

    monkeypatch.setattr(app, "run_webview", fake_run_webview)

    result = app.main([
        "--web-panel",
        "http://127.0.0.1:1/#/search",
        "--title",
        "Search",
        "--control-port",
        "54321",
    ])

    assert result == 7
    assert calls == [("http://127.0.0.1:1/#/search", "Search", 54321)]
