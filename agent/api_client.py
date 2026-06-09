"""Shared HTTP policy for external API calls."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
_TRANSIENT_EXCS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
    httpx.WriteTimeout,
)
_LIMITERS: dict[str, _AsyncRateLimiter] = {}
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_BASE_SECONDS = 0.25
_DEFAULT_RATE_LIMIT_PER_SECOND = 20.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)).strip())
    except (AttributeError, TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except (AttributeError, TypeError, ValueError):
        return default


def _key(service: str, suffix: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in service.upper())
    return f"API_CLIENT_{safe}_{suffix}"


@dataclass(frozen=True, slots=True)
class ApiPolicy:
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    backoff_base_seconds: float = _DEFAULT_BACKOFF_BASE_SECONDS
    rate_limit_per_second: float = _DEFAULT_RATE_LIMIT_PER_SECOND

    @classmethod
    def from_env(cls, service: str) -> ApiPolicy:
        return cls(
            max_attempts=max(1, _env_int(
                _key(service, "MAX_ATTEMPTS"),
                _env_int("API_CLIENT_MAX_ATTEMPTS", _DEFAULT_MAX_ATTEMPTS),
            )),
            backoff_base_seconds=max(0.0, _env_float(
                _key(service, "BACKOFF_BASE_SECONDS"),
                _env_float(
                    "API_CLIENT_BACKOFF_BASE_SECONDS",
                    _DEFAULT_BACKOFF_BASE_SECONDS,
                ),
            )),
            rate_limit_per_second=max(0.0, _env_float(
                _key(service, "RATE_LIMIT_PER_SECOND"),
                _env_float(
                    "API_CLIENT_RATE_LIMIT_PER_SECOND",
                    _DEFAULT_RATE_LIMIT_PER_SECOND,
                ),
            )),
        )


class _AsyncRateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self._interval = 0.0 if rate_per_second <= 0 else 1.0 / rate_per_second
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._interval
        if wait:
            await asyncio.sleep(wait)


def _limiter(service: str, policy: ApiPolicy) -> _AsyncRateLimiter:
    key = service or "default"
    existing = _LIMITERS.get(key)
    if existing is None:
        existing = _AsyncRateLimiter(policy.rate_limit_per_second)
        _LIMITERS[key] = existing
    return existing


def _retry_delay(response: httpx.Response | None, attempt: int, policy: ApiPolicy) -> float:
    if response is not None and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(max(0.0, float(retry_after)))
            except ValueError:
                pass
    return float(policy.backoff_base_seconds * (2.0 ** attempt))


async def async_api_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    service: str,
    policy: ApiPolicy | None = None,
    **kwargs: Any,
) -> httpx.Response | None:
    """Return a successful response, or None after handled API failure."""
    active = policy or ApiPolicy.from_env(service)
    last_response: httpx.Response | None = None
    for attempt in range(active.max_attempts):
        await _limiter(service, active).wait()
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in _TRANSIENT_STATUSES:
                last_response = response
                if attempt + 1 < active.max_attempts:
                    await asyncio.sleep(_retry_delay(response, attempt, active))
                    continue
                return None
            response.raise_for_status()
            return response
        except _TRANSIENT_EXCS:
            if attempt + 1 < active.max_attempts:
                await asyncio.sleep(_retry_delay(last_response, attempt, active))
                continue
            return None
        except httpx.HTTPError:
            return None
    return None
