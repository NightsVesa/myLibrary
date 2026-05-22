from dataclasses import dataclass
from typing import Generator

import httpx


@dataclass(frozen=True)
class LLMConfig:
    api_base: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Message:
    role: str
    content: str


_TIMEOUT = 60.0


def _validate(config: LLMConfig) -> None:
    if not config.api_key:
        raise ValueError("API key is not configured")


def _headers(config: LLMConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


def _body(config: LLMConfig, messages: list[Message], *, stream: bool) -> dict:
    return {
        "model": config.model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": stream,
    }


def chat(config: LLMConfig, messages: list[Message]) -> str:
    _validate(config)
    resp = httpx.post(
        f"{config.api_base}/chat/completions",
        headers=_headers(config),
        json=_body(config, messages, stream=False),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chat_stream(
    config: LLMConfig, messages: list[Message],
) -> Generator[str, None, None]:
    _validate(config)
    import json
    with httpx.stream(
        "POST",
        f"{config.api_base}/chat/completions",
        headers=_headers(config),
        json=_body(config, messages, stream=True),
        timeout=_TIMEOUT,
    ) as resp:
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
            text = delta.get("content", "")
            if text:
                yield text
