import time
from dataclasses import dataclass
from typing import Generator

import httpx

import config as _cfg


@dataclass(frozen=True)
class LLMConfig:
    api_base: str
    api_key: str
    model: str
    thinking: bool = False


def load_llm_config() -> LLMConfig:
    """Build an LLMConfig from the current env-derived module-level config."""
    return LLMConfig(
        api_base=_cfg.LLM_API_BASE,
        api_key=_cfg.LLM_API_KEY,
        model=_cfg.LLM_MODEL,
        thinking=_cfg.LLM_THINKING,
    )


@dataclass(frozen=True)
class Message:
    role: str
    content: str


_RETRYABLE = frozenset({429, 500, 502, 503, 504})


def _validate(config: LLMConfig) -> None:
    if not config.api_key:
        raise ValueError("API key is not configured")


def _headers(config: LLMConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


def _body(config: LLMConfig, messages: list[Message], *, stream: bool) -> dict:
    body: dict = {
        "model": config.model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": stream,
    }
    if config.thinking:
        body["enable_thinking"] = True
    return body


def _reasoning_text(delta: dict) -> str:
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = delta.get(key, "")
        if isinstance(value, str) and value:
            return value
    return ""


def chat(
    config: LLMConfig, messages: list[Message],
    *, on_thinking: "callable[[str], None] | None" = None,
) -> str:
    _validate(config)
    last_exc: Exception | None = None
    for attempt in range(_cfg.LLM_MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                f"{config.api_base}/chat/completions",
                headers=_headers(config),
                json=_body(config, messages, stream=False),
                timeout=_cfg.LLM_TIMEOUT,
            )
            if resp.status_code in _RETRYABLE and attempt < _cfg.LLM_MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            if on_thinking:
                reasoning = _reasoning_text(msg)
                if reasoning:
                    on_thinking(reasoning)
            return msg["content"]
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < _cfg.LLM_MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc  # type: ignore[misc]


def chat_stream(
    config: LLMConfig, messages: list[Message],
    *, on_thinking: "callable[[str], None] | None" = None,
) -> Generator[str, None, None]:
    _validate(config)
    import json
    last_exc: Exception | None = None
    for attempt in range(_cfg.LLM_MAX_RETRIES + 1):
        try:
            with httpx.stream(
                "POST",
                f"{config.api_base}/chat/completions",
                headers=_headers(config),
                json=_body(config, messages, stream=True),
                timeout=_cfg.LLM_TIMEOUT,
            ) as resp:
                if resp.status_code in _RETRYABLE and attempt < _cfg.LLM_MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if on_thinking:
                        reasoning = _reasoning_text(delta)
                        if reasoning:
                            on_thinking(reasoning)
                    text = delta.get("content", "")
                    if text:
                        yield text
                return
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < _cfg.LLM_MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc  # type: ignore[misc]
