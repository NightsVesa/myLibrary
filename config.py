# config.py
from pathlib import Path

BASE_DIR = Path(__file__).parent
NOTES_DIR = BASE_DIR / "notes"
NOTES_DIR.mkdir(exist_ok=True)

APP_TITLE = "知识库助手"
WINDOW_GEOMETRY = "420x560"
