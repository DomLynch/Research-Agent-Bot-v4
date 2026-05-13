"""HTTP clients for the two-model stack.

Writer: MiMo v2.5 Pro (Xiaomi OpenAI-compatible endpoint)
Judge / editor: Gemma 4 31B via OpenRouter

Both speak OpenAI chat-completions JSON.

Hardening (Sprint 8.1c + 8.1d):
  - Split timeouts: connect fails fast (15s) so dead endpoints surface
    quickly; read is generous (the read_timeout argument) so a slow
    server token stream does not abort a real generation.
  - 3 automatic retries on a wide transient set: ReadTimeout,
    ConnectTimeout, ConnectError, RemoteProtocolError, PoolTimeout,
    AND HTTP 429 / 500 / 502 / 503 / 504 from the provider.
  - Exponential backoff with jitter: 3s, 8s, 20s (cumulative ~31s).
    Polite to the API; not a hammering loop.
  - max_tokens is plumbed through with a high default for the writer
    (16384) so generations do not hit an artificial low ceiling. Set
    to None for unbounded; the writer's Max Monthly plan has plenty
    of token budget.
"""
from __future__ import annotations

import time
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


_TRANSIENT_EXCS: tuple[type[Exception], ...] = (
    httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError,
    httpx.RemoteProtocolError, httpx.PoolTimeout, httpx.WriteTimeout,
)
_TRANSIENT_HTTP_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (3.0, 8.0, 20.0)


def _post_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    read_timeout_sec: float,
    temperature: float,
    max_tokens: int | None = None,
    extra_headers: dict[str, str] | None = None,
    max_retries: int = 3,
    backoff_seconds: tuple[float, ...] = _DEFAULT_BACKOFF_SECONDS,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    payload: dict[str, Any] = {
        "model": model, "messages": messages, "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    timeout = httpx.Timeout(
        connect=15.0, read=read_timeout_sec, write=60.0, pool=10.0,
    )

    def _sleep(attempt_idx: int) -> None:
        delay = (
            backoff_seconds[attempt_idx]
            if attempt_idx < len(backoff_seconds)
            else backoff_seconds[-1]
        )
        time.sleep(delay)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    json=payload, headers=headers,
                )
                if r.status_code in _TRANSIENT_HTTP_STATUSES:
                    last_exc = httpx.HTTPStatusError(
                        f"{r.status_code} {r.reason_phrase} from "
                        f"{base_url.rstrip('/')}/chat/completions",
                        request=r.request, response=r,
                    )
                    if attempt >= max_retries:
                        break
                    _sleep(attempt)
                    continue
                r.raise_for_status()
                return cast(dict[str, Any], r.json())
        except _TRANSIENT_EXCS as e:
            last_exc = e
            if attempt >= max_retries:
                break
            _sleep(attempt)
    assert last_exc is not None
    raise last_exc


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
    max_tokens: int | None = 4000,
) -> LLMResponse:
    """Single MiMo chat call. Raises if writer not configured.

    max_tokens defaults to 4000. EMPIRICAL CALIBRATION: MiMo v2.5 Pro
    has a server-side pathology where setting max_tokens >= ~6000
    triggers "runaway" generation — completion_tokens reaches the cap
    and content comes back empty. Probed live on 2026-05-12:

        4000 -> OK, 1561 completion, 6144-char content (45s)
        6000 -> FAIL, 6000 completion, empty content (109s)
        8192 -> FAIL, 8192 completion, empty content
        16384 -> FAIL, 16384 completion, empty content

    Natural single-section output is ~1500-2000 tokens, so 4000 gives
    2-3x headroom while staying under the pathology trigger. Callers
    can pass None for unbounded (MiMo's own stop logic), or a higher
    value if they have characterised a specific prompt.

    The hardened client retries up to 3 times on transient network
    failures or HTTP 429 / 5xx. RuntimeError is raised if MiMo returns
    empty content with non-zero completion_tokens — the pathological
    case caught above — so callers do not silently write zero-byte
    drafts.
    """
    if not settings.writer_configured:
        raise RuntimeError("Writer not configured: set MIMO_API_KEY and MIMO_BASE_URL")
    # MiMo v2.5 Pro has an intermittent server-side bug: sometimes it
    # generates up to max_tokens and returns empty content. Same prompt,
    # same params, different attempts -> sometimes content, sometimes
    # empty. Retry that case as a transient failure; raise only when
    # all attempts in a row are runaway.
    last_response: LLMResponse | None = None
    for attempt in range(4):  # 1 initial + 3 retries
        data = _post_chat(
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=settings.mimo_model,
            messages=messages,
            read_timeout_sec=settings.mimo_timeout_sec,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        last_response = _extract(data, settings.mimo_model)
        if last_response.content.strip():
            return last_response
        if last_response.completion_tokens == 0:
            return last_response  # degenerate but not pathological
        if attempt < 3:
            time.sleep(5.0 * (attempt + 1))  # 5s, 10s, 15s
    assert last_response is not None
    raise RuntimeError(
        f"writer returned empty content on all 4 attempts; "
        f"last completion_tokens={last_response.completion_tokens}. "
        f"This is the MiMo runaway pathology — try a smaller "
        f"max_tokens or shorten the prompt."
    )


def call_writer_with_fallback(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = 4000,
) -> LLMResponse:
    """Sprint 14: MiMo-then-Gemma writer fallback for the runaway pathology.

    MiMo first (canonical writer). On runaway-exhaustion only, falls back
    to Gemma 4 31B. Response.model is tagged `mimo-runaway-fallback:<id>`
    so the audit trail records the swap. Non-runaway errors propagate.
    """
    try:
        return call_writer(settings, messages, temperature=temperature, max_tokens=max_tokens)
    except RuntimeError as e:
        if "MiMo runaway" not in str(e):
            raise
    resp = call_judge(settings, messages, temperature=temperature)
    return LLMResponse(
        content=resp.content,
        model=f"mimo-runaway-fallback:{resp.model}",
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
    )


def call_judge(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
) -> LLMResponse:
    """Single Gemma 4 31B chat call via OpenRouter. Used for judge + editor.

    Model is fixed to settings.judge_model. The 2-model stack
    (MiMo writer + Gemma judge) is non-negotiable per AGENTS.md;
    do not add a model override here without explicit prior approval.
    """
    if not settings.judge_configured:
        raise RuntimeError("Judge not configured: set OPENROUTER_API_KEY")
    # Judge calls are short. Cap at 60s to fail fast on dead connections;
    # the writer can still use the longer mimo_timeout_sec for prose runs.
    data = _post_chat(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=settings.judge_model,
        messages=messages,
        read_timeout_sec=min(60.0, settings.mimo_timeout_sec),
        temperature=temperature,
        extra_headers={"HTTP-Referer": "https://research-agent-bot-v4.local"},
    )
    return _extract(data, settings.judge_model)
