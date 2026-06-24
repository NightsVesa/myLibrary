from __future__ import annotations

import importlib
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urldefrag, urlparse
from urllib.request import ProxyHandler, Request, build_opener


def wait_until_page_ready(
    url: str,
    *,
    timeout_s: float = 12,
    opener: Callable | None = None,
) -> None:
    page_url = urldefrag(url)[0]
    deadline = time.monotonic() + timeout_s
    open_url = opener or build_opener(ProxyHandler({})).open
    last_error: Exception | None = None

    while time.monotonic() <= deadline:
        request = Request(page_url)
        try:
            with open_url(request, timeout=1) as response:
                status = getattr(response, "status", 0)
                if 200 <= status < 400:
                    return
                last_error = RuntimeError(f"Page returned {status}")
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)

    raise TimeoutError(f"Panel page is not reachable: {last_error}")


class WebviewController:
    def __init__(self) -> None:
        self.window = None
        self.server: ThreadingHTTPServer | None = None
        self._route_lock = threading.Lock()
        self._pending_route: str | None = None

    def attach(self, window) -> None:
        self.window = window

    def on_closing(self):
        # Let closing release WebView2; hidden windows kept rendering and caused lag.
        return None

    def show(self, route: str | None = None) -> bool:
        if self.window is None:
            return False
        if route and route.replace("-", "").replace("_", "").isalnum():
            with self._route_lock:
                self._pending_route = route
        return True

    def consume_route(self) -> str | None:
        with self._route_lock:
            route = self._pending_route
            self._pending_route = None
        return route

    def shutdown(self) -> bool:
        if self.window is not None:
            self.window.destroy()
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        return True


def _make_control_handler(controller: WebviewController):
    class ControlHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/show":
                route = parse_qs(parsed.query).get("route", [None])[0]
                ok = controller.show(route)
                self._send(200 if ok else 503)
                return
            if parsed.path == "/shutdown":
                controller.shutdown()
                self._send(200)
                return
            self._send(404)

        def log_message(self, _format, *_args):
            return

        def _send(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return ControlHandler


def start_control_server(port: int, controller: WebviewController) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_control_handler(controller))
    controller.server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_webview(url: str, title: str, control_port: int | None = None) -> int:
    try:
        webview = importlib.import_module("webview")
    except ModuleNotFoundError:
        return 1

    try:
        wait_until_page_ready(url)
    except TimeoutError:
        return 2

    controller = WebviewController()
    try:
        window = webview.create_window(
            title,
            url,
            width=980,
            height=720,
            resizable=True,
            frameless=False,
            easy_drag=False,
            shadow=True,
            background_color="#0A1428",
        )
        controller.attach(window)
        window.events.closing += controller.on_closing
        if control_port is not None:
            start_control_server(control_port, controller)
        webview.start()
        return 0
    except Exception:
        logging.exception("Web panel crashed")
        return 3
    finally:
        if controller.server is not None:
            controller.server.shutdown()
