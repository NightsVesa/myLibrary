import logging

import app


def test_configure_logging_suppresses_noisy_pdfminer_font_warnings(tmp_path, monkeypatch):
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)
    monkeypatch.setattr(app, "__file__", str(tmp_path / "app.py"))
    logger = logging.getLogger("pdfminer.pdffont")
    previous_level = logger.level
    logger.setLevel(logging.NOTSET)

    try:
        app._configure_logging()

        assert logger.level == logging.ERROR
    finally:
        logger.setLevel(previous_level)
