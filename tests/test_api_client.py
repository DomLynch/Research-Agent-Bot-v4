"""Shared API-client policy tests."""
from __future__ import annotations

import httpx
import pytest

from agent import api_client
from agent.api_client import ApiPolicy, async_api_request


@pytest.fixture(autouse=True)
def clear_limiters() -> None:
    api_client._LIMITERS.clear()


@pytest.mark.asyncio
async def test_async_api_request_retries_429_and_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("agent.api_client.asyncio.sleep", no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await async_api_request(
            client, "GET", "https://example.test",
            service="example", policy=ApiPolicy(
                max_attempts=3, backoff_base_seconds=0.0,
                rate_limit_per_second=0.0,
            ),
        )

    assert response is not None
    assert response.json() == {"ok": True}
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_async_api_request_returns_none_after_transient_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502)

    monkeypatch.setattr("agent.api_client.asyncio.sleep", no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await async_api_request(
            client, "GET", "https://example.test",
            service="example", policy=ApiPolicy(
                max_attempts=2, backoff_base_seconds=0.0,
                rate_limit_per_second=0.0,
            ),
        )

    assert response is None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_async_api_request_rate_limits_per_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("agent.api_client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("agent.api_client.time.monotonic", lambda: 100.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        policy = ApiPolicy(
            max_attempts=1, backoff_base_seconds=0.0,
            rate_limit_per_second=2.0,
        )
        first = await async_api_request(
            client, "GET", "https://example.test/1",
            service="quota", policy=policy,
        )
        second = await async_api_request(
            client, "GET", "https://example.test/2",
            service="quota", policy=policy,
        )

    assert first is not None
    assert second is not None
    assert sleeps == [0.5]
