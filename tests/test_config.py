from pathlib import Path

import config


def test_wiki_dir_exists_and_is_directory():
    assert isinstance(config.WIKI_DIR, Path)
    assert config.WIKI_DIR.exists()
    assert config.WIKI_DIR.is_dir()


def test_llm_api_base_is_non_empty_string():
    assert isinstance(config.LLM_API_BASE, str)
    assert config.LLM_API_BASE != ""


def test_llm_api_key_is_string():
    # API key is optional — can be empty string, but must be a string
    assert isinstance(config.LLM_API_KEY, str)


def test_llm_model_is_non_empty_string():
    assert isinstance(config.LLM_MODEL, str)
    assert config.LLM_MODEL != ""
