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
