# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
NOTES_DIR = BASE_DIR / "notes"
NOTES_DIR.mkdir(exist_ok=True)

WIKI_DIR = BASE_DIR / "wiki"
WIKI_DIR.mkdir(exist_ok=True)

LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

APP_TITLE = "知识库助手"
