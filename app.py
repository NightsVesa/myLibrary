"""Application entry point."""

import argparse
import logging
import sys
from pathlib import Path

from web_panel.webview_entry import run_webview


def _configure_logging() -> None:
    logging.getLogger("pdfminer.pdffont").setLevel(logging.ERROR)
    base_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    log_dir = base_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_dir / "app.log",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            encoding="utf-8",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-panel", dest="web_panel_url")
    parser.add_argument("--title", default="myLibrary")
    parser.add_argument("--control-port", type=int, default=None)
    args = parser.parse_args(argv)

    if args.web_panel_url:
        return run_webview(args.web_panel_url, args.title, args.control_port)

    import ttkbootstrap as ttk
    import tkinter as tk
    from tkinterdnd2 import TkinterDnD

    from config import ASSETS_DIR
    from llm.wiki_engine import migrate_wiki_to_subdirs
    from ui.main_window import MainWindow

    migrate_wiki_to_subdirs()
    root = ttk.Window(themename="cosmo")
    icon_path = ASSETS_DIR / "app_icon.png"
    if icon_path.exists():
        try:
            root._app_icon = tk.PhotoImage(file=str(icon_path))
            root.iconphoto(True, root._app_icon)
        except Exception:
            logging.exception("Failed to load app icon")
    # Enable drag-and-drop on the existing ttk root — adds the tkdnd hooks
    # without forcing us to switch the Tk class.
    root.TkdndVersion = TkinterDnD._require(root)
    MainWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
