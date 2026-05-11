"""HTTP clients for the two-model stack.

Writer: MiMo v2.5 Pro (Xiaomi OpenAI-compatible endpoint)
Judge / editor: Gemma 4 31B via OpenRouter

Both speak OpenAI chat-completions JSON. Minimal here — one request, one
response, no streaming. Retry/correction policy lives upstream in the
orchestrator; here we only translate HTTP to a typed LLMResponse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import httpx

from agent.settings import Settings


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int


def _post_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_sec: float,
    temperature: float,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    payload = {"model": model, "messages": messages, "temperature": temperature}
    with httpx.Client(timeout=timeout_sec) as client:
        r = client.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return cast(dict[str, Any], r.json())


def _extract(data: dict[str, Any], model: str) -> LLMResponse:
    choice = data["choices"][0]
    content = choice["message"]["content"]
    usage = data.get("usage") or {}
    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


def call_writer(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
) -> LLMResponse:
    """Single MiMo chat call. Raises if writer not configured."""
    if not settings.writer_configured:
        raise RuntimeError("Writer not configured: set MIMO_API_KEY and MIMO_BASE_URL")
    data = _post_chat(
        base_url=settings.mimo_base_url,
        api_key=settings.mimo_api_key,
        model=settings.mimo_model,
        messages=messages,
        timeout_sec=settings.mimo_timeout_sec,
        temperature=temperature,
    )
    return _extract(data, settings.mimo_model)


def call_judge(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    model_override: str = "",
) -> LLMResponse:
    """Single OpenRouter chat call.

    Defaults to `settings.judge_model` (Gemma 4 31B). Pass `model_override`
    to route to a different OpenRouter-hosted model — used by the Sprint 7
    eligibility judge to escalate to a frontier reviewer (Claude Opus-class
    or GPT-class) without disturbing the prose-judge pipeline.
    """
    if not settings.judge_configured:
        raise RuntimeError("Judge not configured: set OPENROUTER_API_KEY")
    model = model_override or settings.judge_model
    data = _post_chat(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=model,
        messages=messages,
        timeout_sec=settings.mimo_timeout_sec,
        temperature=temperature,
        extra_headers={"HTTP-Referer": "https://research-agent-bot-v4.local"},
    )
    return _extract(data, model)
