# config.py
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    _BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path(sys.executable).parent
else:
    _BUNDLE_DIR = Path(__file__).parent
    BASE_DIR = Path(__file__).parent

load_dotenv(BASE_DIR / ".env")

ASSETS_DIR = _BUNDLE_DIR / "assets"
NOTES_DIR = BASE_DIR / "notes"
NOTES_DIR.mkdir(exist_ok=True)

WIKI_DIR = BASE_DIR / "wiki"
WIKI_DIR.mkdir(exist_ok=True)

LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))

WIKI_RETRIEVAL_TOP_N = int(os.environ.get("WIKI_RETRIEVAL_TOP_N", "5"))
WIKI_INDEX_SUMMARY_LEN = int(os.environ.get("WIKI_INDEX_SUMMARY_LEN", "80"))
WIKI_MAX_EXTRACT_ITEMS = int(os.environ.get("WIKI_MAX_EXTRACT_ITEMS", "15"))

APP_TITLE = "知识库助手"
