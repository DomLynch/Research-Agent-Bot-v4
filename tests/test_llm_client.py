"""Sprint 8.1d - hardened MiMo client tests.

Exercises the retry logic without touching the network. We monkeypatch
the module-level `httpx.Client` so `_post_chat` builds clients that
talk to an in-process MockTransport. The backoff schedule is overridden
with zeros so the test runs fast.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agent import llm_client


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


@pytest.fixture
def install_transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch the module's httpx.Client so any client built inside
    _post_chat routes through the supplied MockTransport."""

    def _install(handler: Any) -> None:
        transport = httpx.MockTransport(handler)
        real_client = httpx.Client

        def _factory(*args: Any, **kwargs: Any) -> httpx.Client:
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", _factory)

    return _install


def _post(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        base_url="http://mock/v1", api_key="k", model="m",
        messages=[{"role": "user", "content": "hi"}],
        read_timeout_sec=5.0, temperature=0.0,
        max_tokens=10, backoff_seconds=(0.0, 0.0, 0.0),
    )
    kwargs.update(overrides)
    return llm_client._post_chat(**kwargs)


def test_post_chat_returns_on_first_success(install_transport: Any) -> None:
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _ok_response()

    install_transport(handler)
    data = _post()
    assert data["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 1


def test_post_chat_retries_on_429_then_succeeds(install_transport: Any) -> None:
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": "rate"})
        return _ok_response()

    install_transport(handler)
    data = _post()
    assert data["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 3


def test_post_chat_retries_each_5xx(install_transport: Any) -> None:
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(502)
        if len(calls) == 2:
            return httpx.Response(503)
        return _ok_response()

    install_transport(handler)
    data = _post()
    assert data["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 3


def test_post_chat_raises_after_exhausting_retries(install_transport: Any) -> None:
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": "down"})

    install_transport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        _post()
    assert len(calls) == 4  # 1 initial + 3 retries


def test_post_chat_does_not_retry_on_400(install_transport: Any) -> None:
    """4xx that isn't 429 is the caller's fault — raise immediately."""
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": "bad request"})

    install_transport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        _post()
    assert len(calls) == 1


def test_post_chat_retries_on_read_timeout(install_transport: Any) -> None:
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ReadTimeout("simulated")
        return _ok_response()

    install_transport(handler)
    data = _post()
    assert data["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 2


def test_post_chat_payload_carries_max_tokens(install_transport: Any) -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return _ok_response()

    install_transport(handler)
    _post(max_tokens=12345)
    assert captured["max_tokens"] == 12345


def test_post_chat_omits_max_tokens_when_none(install_transport: Any) -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return _ok_response()

    install_transport(handler)
    _post(max_tokens=None)
    assert "max_tokens" not in captured


def test_call_writer_uses_minimax_anthropic_messages_api(
    install_transport: Any,
) -> None:
    from agent.llm_client import call_writer
    from agent.settings import Settings

    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["payload"] = json.loads(req.content)
        return httpx.Response(200, json={
            "model": "MiniMax-M3",
            "content": [{"type": "text", "text": "m3-ok"}],
            "usage": {"input_tokens": 3, "output_tokens": 5},
        })

    install_transport(handler)
    settings = Settings(
        mimo_api_key="k", mimo_base_url="http://mock/anthropic",
        mimo_model="MiniMax-M3", mimo_timeout_sec=5.0,
        openrouter_api_key="", openrouter_base_url="",
        judge_model="m", writer_max_retries=0,
        researka_database_url="", researka_database_token="",
        ncbi_api_key="", semantic_scholar_api_key="",
        core_api_key="", crossref_polite_email="", unpaywall_email="",
        bot_enabled=False, daily_cost_cap_usd=0.0, runs_dir="runs",
    )
    resp = call_writer(settings, [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ], max_tokens=10)

    assert resp.content == "m3-ok"
    assert resp.model == "MiniMax-M3"
    assert resp.prompt_tokens == 3
    assert resp.completion_tokens == 5
    assert captured["url"] == "http://mock/anthropic/v1/messages"
    assert captured["headers"]["x-api-key"] == "k"
    assert captured["payload"]["model"] == "MiniMax-M3"
    assert captured["payload"]["system"] == "sys"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    ]
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def _writer_test_settings() -> Any:
    from agent.settings import Settings
    return Settings(
        mimo_api_key="k", mimo_base_url="http://mock/v1",
        mimo_model="m", mimo_timeout_sec=5.0,
        openrouter_api_key="", openrouter_base_url="",
        judge_model="m", writer_max_retries=0,
        researka_database_url="", researka_database_token="",
        ncbi_api_key="", semantic_scholar_api_key="",
        core_api_key="", crossref_polite_email="", unpaywall_email="",
        bot_enabled=False, daily_cost_cap_usd=0.0, runs_dir="runs",
    )


def test_call_writer_retries_on_runaway_then_succeeds(
    install_transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MiMo pathology is intermittent: same prompt, sometimes runaway,
    sometimes real content. call_writer retries on empty content and
    returns the first non-empty response."""
    from agent.llm_client import call_writer
    monkeypatch.setattr("agent.llm_client.time.sleep", lambda _s: None)
    attempts: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": ""}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 4000},
            })
        return _ok_response()

    install_transport(handler)
    resp = call_writer(
        _writer_test_settings(),
        [{"role": "user", "content": "hi"}], max_tokens=10,
    )
    assert resp.content == "ok"
    assert len(attempts) == 3


def test_call_writer_raises_after_all_runaway_attempts(
    install_transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.llm_client import call_writer
    monkeypatch.setattr("agent.llm_client.time.sleep", lambda _s: None)
    attempts: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": ""}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 4000},
        })

    install_transport(handler)
    with pytest.raises(RuntimeError, match="runaway pathology"):
        call_writer(
            _writer_test_settings(),
            [{"role": "user", "content": "hi"}], max_tokens=10,
        )
    assert len(attempts) == 4  # 1 initial + 3 retries


def test_call_writer_allows_empty_content_with_zero_completion(
    install_transport: Any,
) -> None:
    """If MiMo returns empty content with 0 completion tokens (e.g. it
    chose to say nothing in a degenerate case), we let it through —
    the gate is specifically the runaway pattern."""
    from agent.llm_client import call_writer
    from agent.settings import Settings

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ""}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 0},
            },
        )

    install_transport(handler)
    settings = Settings(
        mimo_api_key="k", mimo_base_url="http://mock/v1",
        mimo_model="m", mimo_timeout_sec=5.0,
        openrouter_api_key="", openrouter_base_url="",
        judge_model="m", writer_max_retries=0,
        researka_database_url="", researka_database_token="",
        ncbi_api_key="", semantic_scholar_api_key="",
        core_api_key="", crossref_polite_email="", unpaywall_email="",
        bot_enabled=False, daily_cost_cap_usd=0.0, runs_dir="runs",
    )
    resp = call_writer(settings, [{"role": "user", "content": "hi"}], max_tokens=10)
    assert resp.content == ""


# -----------------------------------------------------------------------------
# Sprint 14 — MiMo → Gemma writer fallback for the runaway pathology.
# -----------------------------------------------------------------------------


def _fallback_settings() -> Any:
    """Settings wired for both the writer endpoint and the OpenRouter
    Gemma fallback endpoint. Both point at the in-process MockTransport;
    request URL distinguishes which handler answers."""
    from agent.settings import Settings
    return Settings(
        mimo_api_key="k", mimo_base_url="http://mock-mimo/v1",
        mimo_model="mimo-test", mimo_timeout_sec=5.0,
        openrouter_api_key="orkey", openrouter_base_url="http://mock-or/api/v1",
        judge_model="gemma-test", writer_max_retries=0,
        researka_database_url="", researka_database_token="",
        ncbi_api_key="", semantic_scholar_api_key="",
        core_api_key="", crossref_polite_email="", unpaywall_email="",
        bot_enabled=False, daily_cost_cap_usd=0.0, runs_dir="runs",
    )


def test_call_writer_with_fallback_returns_mimo_when_healthy(
    install_transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy writer: fallback is a no-op pass-through; response.model is
    the bare writer model id (no 'fallback' tag)."""
    from agent.llm_client import call_writer_with_fallback
    monkeypatch.setattr("agent.llm_client.time.sleep", lambda _s: None)

    def handler(req: httpx.Request) -> httpx.Response:
        return _ok_response()

    install_transport(handler)
    resp = call_writer_with_fallback(
        _fallback_settings(),
        [{"role": "user", "content": "hi"}], max_tokens=10,
    )
    assert resp.content == "ok"
    assert resp.model == "mimo-test"
    assert "fallback" not in resp.model


def test_call_writer_with_fallback_swaps_to_gemma_on_runaway(
    install_transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Writer runs away on all 4 attempts → call_judge is invoked → response
    is the Gemma reply, tagged as writer fallback."""
    from agent.llm_client import call_writer_with_fallback
    monkeypatch.setattr("agent.llm_client.time.sleep", lambda _s: None)
    mimo_calls: list[int] = []
    gemma_calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "mock-mimo" in url:
            mimo_calls.append(1)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": ""}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 4000},
            })
        gemma_calls.append(1)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "gemma-fallback-prose"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200},
        })

    install_transport(handler)
    resp = call_writer_with_fallback(
        _fallback_settings(),
        [{"role": "user", "content": "hi"}], max_tokens=10,
    )
    assert resp.content == "gemma-fallback-prose"
    assert resp.model == "writer-runaway-fallback:gemma-test"
    assert len(mimo_calls) == 4  # 1 + 3 retries
    assert len(gemma_calls) == 1


def test_call_writer_with_fallback_propagates_non_runaway_runtime_errors(
    install_transport: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RuntimeError that isn't the MiMo-runaway pathology (e.g. writer
    not configured) must propagate — never silently swap to Gemma for a
    real config / network failure."""
    from agent.llm_client import call_writer_with_fallback
    from agent.settings import Settings
    monkeypatch.setattr("agent.llm_client.time.sleep", lambda _s: None)
    settings = Settings(
        mimo_api_key="",  # writer not configured
        mimo_base_url="", mimo_model="m", mimo_timeout_sec=5.0,
        openrouter_api_key="orkey", openrouter_base_url="http://mock-or/api/v1",
        judge_model="g", writer_max_retries=0,
        researka_database_url="", researka_database_token="",
        ncbi_api_key="", semantic_scholar_api_key="",
        core_api_key="", crossref_polite_email="", unpaywall_email="",
        bot_enabled=False, daily_cost_cap_usd=0.0, runs_dir="runs",
    )
    with pytest.raises(RuntimeError, match="Writer not configured"):
        call_writer_with_fallback(
            settings, [{"role": "user", "content": "hi"}], max_tokens=10,
        )
