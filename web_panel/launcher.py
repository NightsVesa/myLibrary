from __future__ import annotations

import os
import importlib
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


def react_panels_enabled() -> bool:
    value = os.environ.get("MYLIBRARY_REACT_PANELS")
    if value is None:
        return bool(getattr(sys, "frozen", False))
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_panel_url(base_url: str, panel: str, token: str) -> str:
    base = base_url.rstrip("/")
    query = urlencode({"token": token})
    return f"{base}/#/{panel}?{query}"


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def send_web_panel_control(
    port: int,
    action: str,
    *,
    route: str | None = None,
    timeout: float = 1,
) -> bool:
    opener = build_opener(ProxyHandler({}))
    query = urlencode({"route": route}) if route else ""
    suffix = f"?{query}" if query else ""
    request = Request(f"http://127.0.0.1:{port}/{action}{suffix}")
    with opener.open(request, timeout=timeout) as response:
        return getattr(response, "status", 0) == 200


def frontend_available(frontend_dir: Path) -> bool:
    return (Path(frontend_dir) / "index.html").exists()


def webview_available() -> bool:
    try:
        importlib.import_module("webview")
    except ModuleNotFoundError:
        return False
    return True


def default_frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled_frontend = bundle_dir / "frontend"
        if frontend_available(bundled_frontend):
            return bundled_frontend
        return Path(sys.executable).parent / "frontend"
    return Path(__file__).resolve().parents[1] / "frontend" / "dist"


def default_web_panel_log_path() -> Path:
    base_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return base_dir / "logs" / "web_panel.log"


def launch_web_panel_process(
    url: str,
    title: str,
    *,
    app_path: Path | None = None,
    control_port: int | None = None,
    log_path: Path | None = None,
):
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--web-panel", url, "--title", title]
    else:
        if app_path is None:
            app_path = Path(__file__).resolve().parents[1] / "app.py"
        cmd = [sys.executable, str(app_path), "--web-panel", url, "--title", title]
    if control_port is not None:
        cmd.extend(["--control-port", str(control_port)])

    log_file = Path(log_path) if log_path is not None else default_web_panel_log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab") as stream:
        return subprocess.Popen(
            cmd,
            stdout=stream,
            stderr=stream,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
