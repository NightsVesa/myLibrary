from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.request import ProxyHandler, Request, build_opener

import uvicorn

from web_panel.api import create_app


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_http_ready(
    base_url: str,
    panel_token: str,
    *,
    timeout_s: float = 5,
    opener: Callable | None = None,
) -> None:
    deadline = time.monotonic() + timeout_s
    health_url = f"{base_url.rstrip('/')}/api/health"
    last_error: Exception | None = None
    open_url = opener or build_opener(ProxyHandler({})).open

    while time.monotonic() <= deadline:
        request = Request(health_url, headers={"X-Panel-Token": panel_token})
        try:
            with open_url(request, timeout=1) as response:
                if getattr(response, "status", None) == 200:
                    return
                last_error = RuntimeError(f"Health check returned {response.status}")
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)

    raise TimeoutError(f"Panel API health check failed: {last_error}")


class PanelApiServer:
    def __init__(
        self,
        *,
        notes_dir: Path,
        panel_token: str,
        frontend_dir: Path | None = None,
        open_reader: Callable[[Path, str], None] | None = None,
        wiki_dir: Path | None = None,
    ) -> None:
        self.notes_dir = Path(notes_dir)
        self.wiki_dir = Path(wiki_dir) if wiki_dir is not None else None
        self.panel_token = panel_token
        self.frontend_dir = Path(frontend_dir) if frontend_dir is not None else None
        self.open_reader = open_reader
        self.host = "127.0.0.1"
        self.port: int | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._route_lock = threading.Lock()
        self._pending_route: tuple[str, dict[str, str]] | None = None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise RuntimeError("Panel API server has not started")
        return f"http://{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return (
            self.port is not None
            and self._server is not None
            and self._thread is not None
            and self._thread.is_alive()
        )

    def set_panel_route(self, route: str, *, params: dict[str, str] | None = None) -> None:
        if not route.replace("-", "").replace("_", "").isalnum():
            return
        with self._route_lock:
            self._pending_route = (route, dict(params or {}))

    def consume_panel_route(self) -> tuple[str, dict[str, str]] | None:
        with self._route_lock:
            command = self._pending_route
            self._pending_route = None
        return command

    def start(self) -> None:
        if self.is_running:
            return
        if self._server is not None:
            self.stop()

        self.port = _free_loopback_port()
        app = create_app(
            notes_dir=self.notes_dir,
            wiki_dir=self.wiki_dir,
            panel_token=self.panel_token,
            frontend_dir=self.frontend_dir,
            open_reader=self.open_reader,
            consume_panel_route=self.consume_panel_route,
        )
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        self._server = server
        self._thread = thread
        thread.start()

        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError("Panel API server exited during startup")
            if time.monotonic() > deadline:
                raise TimeoutError("Panel API server did not start")
            time.sleep(0.02)
        try:
            _wait_until_http_ready(self.base_url, self.panel_token)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        self.port = None
