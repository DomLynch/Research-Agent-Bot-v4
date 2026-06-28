"""CLI limit policy tests for the alpha topic-discovery runner."""
from __future__ import annotations

import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_topic_discovery
from run_topic_discovery import _resolve_limits

from agent.topic_discovery import TopicCandidate


@pytest.fixture(autouse=True)
def _disable_live_v5_client(monkeypatch: Any, tmp_path: Path) -> Any:
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK", "0")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_ENV_LOAD", "0")
    monkeypatch.setattr(
        run_topic_discovery,
        "_FULLRAW_COMPLETED_SWEEP_CACHE_PATH",
        tmp_path / "fullraw_completed_sweeps.json",
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "_FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH",
        tmp_path / "fullraw_in_progress_sweeps.json",
    )
    run_topic_discovery._FULLRAW_COMPLETED_SWEEP_CACHE.clear()
    yield
    for key in (
        "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL",
        "V5_MEMO_FULL_RAW_INDEX_TOKEN",
        "V5_MEMO_FULL_RAW_CORPUS_TOKEN",
        "V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED",
        "V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED",
        "V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH",
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS",
        "V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS",
        "V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS",
        "RESEARKA_FULLRAW_SEARCH_URL",
        "RESEARKA_FULLRAW_TOKEN",
        "RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED",
        "RESEARKA_FULLRAW_MIN_SOURCES_SEARCHED",
        "RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH",
        "RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS",
    ):
        os.environ.pop(key, None)


def _fullraw_rows(prefix: str, title_prefix: str, n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "doi": f"10.1/{prefix}{i}",
            "title": f"{title_prefix} paper {i}",
            "fwci": 2.0,
            "cited_by_count": 20 + i,
            "publication_year": 2025,
            "quality_score": 90.0,
        }
        for i in range(n)
    ]


def _fullraw_receipt() -> dict[str, Any]:
    return {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "sources_searched": {
            "openalex": 900,
            "pubmed": 120,
            "crossref": 90,
            "semantic_scholar": 60,
            "core": 40,
        },
    }


def test_fullraw_receipt_complete_accepts_list_sources() -> None:
    receipt = _fullraw_receipt()
    receipt["sources_searched"] = [
        "openalex", "pubmed", "crossref", "semantic_scholar", "core",
    ]

    assert run_topic_discovery._fullraw_receipt_complete(receipt)


def test_fullraw_receipt_complete_accepts_source_count() -> None:
    receipt = _fullraw_receipt()
    receipt.pop("sources_searched")
    receipt["source_count_searched"] = 5

    assert run_topic_discovery._fullraw_receipt_complete(receipt)


def test_seed_fullraw_records_incomplete_receipt_event(monkeypatch: Any) -> None:
    run_topic_discovery._FULLRAW_PROBE_EVENTS.clear()
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS", "0")
    receipt = {
        "shards_searched": 201,
        "shards_total": 1525,
        "partial_shard_search": True,
        "sweep_failed_shards": 0,
        "sources_searched": {"openalex": 10, "pubmed": 4},
    }

    def handler(req: Any) -> Any:
        assert json.loads(req.content.decode("utf-8"))["queue_if_missing"] is True
        return run_topic_discovery.httpx.Response(200, json={
            "meta": {
                "async_sweep": {"status": "queued", "shard_limit": 1525},
                "shard_receipt": receipt,
            },
            "results": [{"title": "Partial result must not publish"}],
        })

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "metformin longevity", client=client, limit=5,
        ) == []

    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1] == {
        "query": "metformin longevity",
        "status": "incomplete_receipt",
        "shards_searched": 201,
        "shards_total": 1525,
        "partial_shard_search": True,
        "sweep_failed_shards": 0,
        "source_count_searched": None,
        "sources_searched": {"openalex": 10, "pubmed": 4},
        "async_status": "queued",
        "shard_limit": 1525,
    }


def test_seed_fullraw_records_async_event_without_receipt(monkeypatch: Any) -> None:
    run_topic_discovery._FULLRAW_PROBE_EVENTS.clear()
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS", "0")

    def handler(_req: Any) -> Any:
        return run_topic_discovery.httpx.Response(200, json={
            "meta": {"async_sweep": {"status": "queued", "shard_limit": 1525}},
            "results": [],
        })

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "metformin longevity", client=client, limit=5,
        ) == []

    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1] == {
        "query": "metformin longevity",
        "status": "async_queued",
        "async_status": "queued",
        "shard_limit": 1525,
    }


def test_seed_fullraw_records_saturated_async_queue(monkeypatch: Any) -> None:
    run_topic_discovery._FULLRAW_PROBE_EVENTS.clear()
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS", "0")

    def handler(_req: Any) -> Any:
        return run_topic_discovery.httpx.Response(200, json={
            "meta": {
                "async_sweep": {
                    "cache_key": "abc123",
                    "inflight_count": 3,
                    "key_queued": False,
                    "key_running": False,
                    "max_inflight": 2,
                    "max_queue": 16,
                    "queued_count": 16,
                    "shard_limit": 1525,
                    "status": "queued",
                },
                "shard_receipt": {"authenticated": True},
            },
            "results": [],
        })

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "business supply chain", client=client, limit=5,
        ) == []

    event = run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]
    assert event["status"] == "queue_saturated"
    assert event["async_status"] == "queued"
    assert event["queued_count"] == 16
    assert event["max_queue"] == 16
    assert event["key_queued"] is False
    assert event["key_running"] is False


def test_seed_fullraw_backs_off_when_fullraw_inflight_is_saturated(
    monkeypatch: Any,
) -> None:
    run_topic_discovery._FULLRAW_PROBE_EVENTS.clear()
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")

    def handler(req: Any) -> Any:
        if req.url.path.endswith("/health"):
            return run_topic_discovery.httpx.Response(200, json={
                "async_sweep": {
                    "inflight_count": 3,
                    "max_inflight": 2,
                    "max_queue": 16,
                    "priority_queued_count": 0,
                    "queued_count": 0,
                },
            })
        raise AssertionError("search should not run while fullraw inflight is saturated")

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "business supply chain", client=client, limit=5,
        ) == []

    event = run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]
    assert event["status"] == "inflight_saturated"
    assert event["inflight_count"] == 3
    assert event["max_inflight"] == 2


def test_seed_fullraw_retries_after_endpoint_timeout(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", "2")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS", "0")
    calls = 0

    def handler(_req: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise run_topic_discovery.httpx.ReadTimeout("queued sweep still running")
        return run_topic_discovery.httpx.Response(200, json={
            "meta": {"shard_receipt": _fullraw_receipt()},
            "results": [{"title": "Complete fullraw result", "doi": "10.1/fullraw"}],
        })

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        papers = run_topic_discovery._seed_fullraw_papers(
            "metformin longevity", client=client, limit=5,
        )

    assert calls == 2
    assert papers[0]["title"] == "Complete fullraw result"


def test_seed_fullraw_default_polls_until_budget_not_derived_attempts(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "5")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS", "1")
    now = [0.0]
    monkeypatch.setattr(
        run_topic_discovery.topic_discovery_mod.time,
        "monotonic",
        lambda: now[0],
    )
    monkeypatch.setattr(
        run_topic_discovery.topic_discovery_mod.time,
        "sleep",
        lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    calls = 0

    def handler(req: Any) -> Any:
        nonlocal calls
        calls += 1
        body = json.loads(req.content.decode("utf-8"))
        assert body == {
            "query": "metformin longevity",
            "limit": 10,
            "rank_mode": "relevance",
            "cache_only": True,
            "queue_if_missing": True,
        }
        if calls < 3:
            return run_topic_discovery.httpx.Response(200, json={
                "meta": {"async_sweep": {"status": "queued", "shard_limit": 1525}},
                "results": [],
            })
        return run_topic_discovery.httpx.Response(200, json={
            "meta": {"shard_receipt": _fullraw_receipt()},
            "results": [{"title": "Complete budget-polled result", "doi": "10.1/fullraw"}],
        })

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        papers = run_topic_discovery._seed_fullraw_papers(
            "metformin_longevity", client=client, limit=5,
        )

    assert calls == 3
    assert papers[0]["title"] == "Complete budget-polled result"


def test_seed_fullraw_reuses_completed_sweep_for_equivalent_query(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    receipt = _fullraw_receipt()

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        return [{
            "doi": "10.1/urolithin",
            "title": "Urolithin mitochondrial aging replication",
            "fullraw_shard_receipt": receipt,
        }]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        first = run_topic_discovery._seed_fullraw_papers(
            "urolithin A mitochondrial aging", client=client, limit=5,
        )
        second = run_topic_discovery._seed_fullraw_papers(
            "urolithin mitochondrial aging", client=client, limit=5,
        )

    assert [row["title"] for row in first] == [row["title"] for row in second]
    assert calls == ["urolithin A mitochondrial aging"]
    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1] == {
        "query": "urolithin mitochondrial aging",
        "status": "cache_hit",
        "cache_key": "aging mitochondrial urolithin",
        "paper_count": 1,
    }


def test_seed_fullraw_reuses_completed_sweep_from_disk(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    receipt = _fullraw_receipt()

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        return [{
            "doi": "10.1/urolithin",
            "title": "Urolithin mitochondrial aging replication",
            "fullraw_shard_receipt": receipt,
        }]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        run_topic_discovery._seed_fullraw_papers(
            "urolithin A mitochondrial aging", client=client, limit=5,
        )
        run_topic_discovery._FULLRAW_COMPLETED_SWEEP_CACHE.clear()
        second = run_topic_discovery._seed_fullraw_papers(
            "urolithin mitochondrial aging", client=client, limit=5,
        )

    assert calls == ["urolithin A mitochondrial aging"]
    assert second[0]["title"] == "Urolithin mitochondrial aging replication"
    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]["status"] == "cache_hit"


def test_seed_fullraw_does_not_cache_incomplete_receipt(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    receipt = {
        **_fullraw_receipt(),
        "partial_shard_search": True,
        "shards_searched": 128,
    }

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        return [{
            "doi": "10.1/urolithin",
            "title": "Urolithin mitochondrial aging partial",
            "fullraw_shard_receipt": receipt,
        }]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        run_topic_discovery._seed_fullraw_papers(
            "urolithin mitochondrial aging", client=client, limit=5,
        )
        run_topic_discovery._seed_fullraw_papers(
            "urolithin mitochondrial aging", client=client, limit=5,
        )

    assert calls == ["urolithin mitochondrial aging", "urolithin mitochondrial aging"]


def test_seed_fullraw_backs_off_recent_incomplete_receipt(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            **_fullraw_receipt(),
            "partial_shard_search": True,
            "shards_searched": 192,
            "papers_searched": 313447963,
            "papers_total": 1456919317,
            "result_count_returned": 10,
            "result_count_unique": 17,
            "result_citation_diversity": 3,
        }
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {
            "status": "queued",
        }
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        first = run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )
        second = run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )

    assert first == second == []
    assert calls == ["platform strategy network"]
    event = run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]
    assert event["query"] == "platform strategy network"
    assert event["status"] == "in_progress_cache_hit"
    assert event["cached_status"] == "incomplete_receipt"
    assert event["cache_key"] == "network platform strategy"
    assert event["paper_count"] == 0
    assert event["shards_searched"] == 192
    assert event["partial_shard_search"] is True
    assert event["sweep_failed_shards"] == 0
    assert event["async_status"] == "queued"
    assert event["papers_searched"] == 313447963
    assert event["papers_total"] == 1456919317
    assert event["result_count_returned"] == 10
    assert event["result_count_unique"] == 17
    assert event["result_citation_diversity"] == 3


def test_seed_fullraw_polls_due_in_progress_receipt_before_ttl(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "900")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_POLL_INTERVAL_SECONDS", "60")

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if len(calls) == 1:
            run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
                **_fullraw_receipt(),
                "partial_shard_search": True,
                "shards_searched": 192,
            }
            run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {
                "status": "queued",
            }
            return []
        receipt = _fullraw_receipt()
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = receipt
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        return [{
            "doi": "10.1/platform",
            "title": "Platform strategy network replication",
            "fullraw_shard_receipt": receipt,
        }]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        ) == []
        cache = run_topic_discovery.publish_io.read_json(
            run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH, {},
        )
        cache["network platform strategy"]["ts"] -= 120
        run_topic_discovery.publish_io.write_json(
            run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH, cache,
        )
        rows = run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )

    assert calls == ["platform strategy network", "platform strategy network"]
    assert rows[0]["title"] == "Platform strategy network replication"
    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]["status"] == "in_progress_poll_due"


def test_seed_fullraw_polls_due_in_progress_despite_full_queue(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "900")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_POLL_INTERVAL_SECONDS", "60")

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if len(calls) == 1:
            run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
                **_fullraw_receipt(),
                "partial_shard_search": True,
                "shards_searched": 416,
                "source_count_searched": 4,
            }
            run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {
                "status": "queued",
                "queued_count": 16,
                "max_queue": 16,
            }
            return []
        receipt = _fullraw_receipt()
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = receipt
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        return [{
            "doi": "10.1/platform",
            "title": "Platform strategy network completed sweep",
            "fullraw_shard_receipt": receipt,
        }]

    def fail_if_saturation_checked(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        raise AssertionError("due in-progress fullraw keys must be polled")

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        ) == []
        cache = run_topic_discovery.publish_io.read_json(
            run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH, {},
        )
        cache["network platform strategy"]["ts"] -= 120
        run_topic_discovery.publish_io.write_json(
            run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH, cache,
        )
        monkeypatch.setattr(
            run_topic_discovery, "_fullraw_queue_saturated", fail_if_saturation_checked,
        )
        rows = run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )

    assert calls == ["platform strategy network", "platform strategy network"]
    assert rows[0]["title"] == "Platform strategy network completed sweep"
    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]["status"] == "in_progress_poll_due"


def test_fullraw_in_progress_backoff_default_covers_sweep_runtime(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", raising=False)

    assert run_topic_discovery._fullraw_in_progress_ttl_seconds() == 900.0


def test_fullraw_in_progress_backoff_uses_search_budget(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "1800")

    assert run_topic_discovery._fullraw_in_progress_ttl_seconds() == 1800.0


def test_fullraw_in_progress_backoff_uses_largest_configured_budget(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", "120")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "120")
    monkeypatch.setenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", "900")

    assert run_topic_discovery._fullraw_in_progress_ttl_seconds() == 900.0


def test_fullraw_in_progress_backoff_allows_explicit_override(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "1800")

    assert run_topic_discovery._fullraw_in_progress_ttl_seconds() == 120.0


def test_seed_fullraw_retries_expired_incomplete_receipt(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", "0")

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            **_fullraw_receipt(),
            "partial_shard_search": True,
            "shards_searched": 192,
        }
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {
            "status": "queued",
        }
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )
        run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )

    assert calls == ["platform strategy network", "platform strategy network"]


def test_seed_fullraw_reuses_budget_fresh_incomplete_receipt(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "900")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_IN_PROGRESS_POLL_INTERVAL_SECONDS", "700")

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            **_fullraw_receipt(),
            "partial_shard_search": True,
            "shards_searched": 192,
        }
        run_topic_discovery.topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {
            "status": "queued",
        }
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fetch)

    with run_topic_discovery.httpx.Client() as client:
        run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )
        cache = run_topic_discovery.publish_io.read_json(
            run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH, {},
        )
        cache["network platform strategy"]["ts"] -= 600
        run_topic_discovery.publish_io.write_json(
            run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH, cache,
        )
        run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )

    assert calls == ["platform strategy network"]
    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]["status"] == "in_progress_cache_hit"


def test_seed_fullraw_completed_sweep_overrides_in_progress_backoff(
    monkeypatch: Any,
) -> None:
    receipt = _fullraw_receipt()
    key = run_topic_discovery._fullraw_query_fingerprint("platform strategy network")
    run_topic_discovery.publish_io.write_json(
        run_topic_discovery._FULLRAW_IN_PROGRESS_SWEEP_CACHE_PATH,
        {
            key: {
                "ts": 1,
                "event": {
                    "status": "incomplete_receipt",
                    "async_status": "queued",
                    "partial_shard_search": True,
                },
            },
        },
    )
    run_topic_discovery.publish_io.write_json(
        run_topic_discovery._FULLRAW_COMPLETED_SWEEP_CACHE_PATH,
        {
            key: {
                "query": "platform strategy network",
                "ts": 2,
                "papers": [{
                    "doi": "10.1/platform",
                    "title": "Platform strategy network replication",
                    "fullraw_shard_receipt": receipt,
                }],
            },
        },
    )

    def fail_fetch(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("complete cache should avoid endpoint")

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fail_fetch)

    with run_topic_discovery.httpx.Client() as client:
        rows = run_topic_discovery._seed_fullraw_papers(
            "platform strategy network", client=client, limit=5,
        )

    assert rows[0]["title"] == "Platform strategy network replication"


def test_seed_fullraw_does_not_use_client_fallback_when_endpoint_incomplete(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "https://fullraw/search")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS", "0")
    monkeypatch.setattr(
        run_topic_discovery,
        "_v5_client_papers",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct endpoint receipt is authoritative"),
        ),
    )

    def handler(_req: Any) -> Any:
        return run_topic_discovery.httpx.Response(200, json={
            "meta": {"shard_receipt": {
                "shards_searched": 201,
                "partial_shard_search": True,
                "sweep_failed_shards": 0,
                "source_count_searched": 5,
            }},
            "results": [{"title": "Partial endpoint result"}],
        })

    transport = run_topic_discovery.httpx.MockTransport(handler)
    with run_topic_discovery.httpx.Client(transport=transport) as client:
        assert run_topic_discovery._seed_fullraw_papers(
            "metformin longevity", client=client, limit=5,
        ) == []


def test_default_discovery_keeps_publish_path_bounded() -> None:
    assert _resolve_limits(
        warm_backlog=False,
        derived_topic_limit=None,
        fact_probe_topics=None,
        configured_limit=5_000,
    ) == (250, None)


def test_cache_supported_covers_default_seed_space_only() -> None:
    """The source-rich cache is read only by domains that share the default
    seed file (longevity, longevity_research) — domains with their own seeds
    stay off to avoid the token-overlap filter pulling in cross-domain topics.
    Regression: longevity_research (the slug the live publisher runs) must be
    supported; ai_research must not be."""
    assert run_topic_discovery._cache_supported("longevity") is True
    assert run_topic_discovery._cache_supported("longevity_research") is True
    assert run_topic_discovery._cache_supported("ai_research") is False
    assert run_topic_discovery._cache_supported("business_research") is False


def test_warm_backlog_uses_full_pool_with_bounded_probe_window() -> None:
    assert _resolve_limits(
        warm_backlog=True,
        derived_topic_limit=None,
        fact_probe_topics=None,
        configured_limit=5_000,
    ) == (5_000, 250)


def test_warm_backlog_respects_explicit_probe_override() -> None:
    assert _resolve_limits(
        warm_backlog=True,
        derived_topic_limit=None,
        fact_probe_topics=80,
        configured_limit=5_000,
    ) == (5_000, 80)


def test_operator_overrides_discovery_limits() -> None:
    assert _resolve_limits(
        warm_backlog=False,
        derived_topic_limit=1_000,
        fact_probe_topics=40,
        configured_limit=5_000,
    ) == (1_000, 40)


def test_main_writes_limit_metadata_for_operator_overrides(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[tuple[int, int | None]] = []
    lock_calls: list[tuple[str, int]] = []

    def fake_discover(**kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append((kwargs["derived_topic_limit"], kwargs["fact_probe_topics"]))
        return (
            TopicCandidate(
                topic="topic", paper_count=1, fact_source_count=5,
                top_paper_doi="10.1/x", top_paper_title="Paper",
                velocity_score=1.0, mean_fwci=1.0, mean_cited_by=1.0,
            ),
        )

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).suffix, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("topic",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py",
        "--top", "1",
        "--derived-topic-limit", "1000",
        "--fact-probe-topics", "40",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == [(1_000, 40)]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["derived_topic_limit"] == 1_000
    assert payload["fact_probe_topics"] == 40
    assert (".lock", fcntl.LOCK_EX) in lock_calls


def test_cache_first_skips_slow_discovery_when_window_is_filled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="seed_rich_a", paper_count=5, fact_source_count=8,
            top_paper_doi="10.1/a", top_paper_title="Paper A",
            velocity_score=2.0, mean_fwci=1.0, mean_cited_by=10.0,
        ),
        TopicCandidate(
            topic="seed_rich_b", paper_count=5, fact_source_count=7,
            top_paper_doi="10.1/b", top_paper_title="Paper B",
            velocity_score=1.0, mean_fwci=1.0, mean_cited_by=8.0,
        ),
    )

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        raise AssertionError("cache-first should not fetch seed papers")

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--top", "2",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["cache_first"] is True
    assert payload["candidate_count"] == 2
    assert [row["topic"] for row in payload["top"]] == ["seed_rich_a", "seed_rich_b"]


def test_warm_backlog_probes_fullraw_before_source_rich_cache(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "seed longevity":
            return _fullraw_rows("raw", "Seed longevity source rich")
        return []

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: (_ for _ in ()).throw(
            AssertionError("warm backlog should not default to cache-first")
        ),
    )
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)
    monkeypatch.setattr(
        run_topic_discovery, "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("fullraw should satisfy the warm backlog window")
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--warm-backlog", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["cache_first"] is False
    assert payload["warm_backlog"] is True
    assert payload["candidate_count"] == 1
    assert calls[:1] == ["longevity anti aging"]
    assert payload["top"][0]["paper_count"] == 5


def test_cache_first_falls_back_when_cache_is_underfilled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="seed_cached_rich", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fallback = (
        TopicCandidate(
            topic="seed_fresh_rich", paper_count=3, fact_source_count=9,
            top_paper_doi="10.1/fresh", top_paper_title="Fresh",
            velocity_score=2.0, mean_fwci=1.0, mean_cited_by=4.0,
        ),
    )
    calls: list[str] = []

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return fallback

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--top", "2",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == [
        "seed_fresh_rich", "seed_cached_rich",
    ]


def test_cache_first_does_not_let_paperless_cache_suppress_fresh_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="seed_cached_rich", paper_count=0, fact_source_count=12,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fresh = (
        TopicCandidate(
            topic="seed_fullraw_fresh", paper_count=3, fact_source_count=6,
            top_paper_doi="10.1/fullraw", top_paper_title="Fullraw fresh paper",
            velocity_score=4.0, mean_fwci=2.0, mean_cited_by=20.0,
        ),
    )
    calls: list[str] = []

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return fresh

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["seed_fullraw_fresh"]


def test_hydration_queries_add_bounded_domain_context(monkeypatch: Any) -> None:
    monkeypatch.setenv("TOPIC_DISCOVERY_HYDRATE_QUERIES", "3")
    candidate = TopicCandidate(
        topic="metformin_use", paper_count=8, fact_source_count=10,
        top_paper_doi="", top_paper_title="",
        velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
    )

    assert run_topic_discovery._hydration_queries(
        candidate, context="Longevity / anti-aging research",
    ) == (
        "metformin_use",
        "metformin use",
        "metformin_use longevity anti aging",
    )


def test_discovery_hydrates_paper_fields_before_writing_queue(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fallback = (
        TopicCandidate(
            topic="seed_source_diverse", paper_count=8, fact_source_count=10,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "3")
    monkeypatch.setattr(run_topic_discovery, "discover_topics", lambda **_kw: fallback)
    monkeypatch.setattr(run_topic_discovery, "_fetch_topic_papers", lambda *_a, **_k: [{
        "doi": "10.1/fullraw", "title": "Full raw source-diverse paper",
        "fwci": 3.0, "cited_by_count": 20, "publication_year": 2026,
        "quality_score": 90.0,
    }])
    monkeypatch.setattr(sys, "argv", ["run_topic_discovery.py", "--top", "1"])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    row = payload["top"][0]
    assert row["top_paper_title"] == "Full raw source-diverse paper"
    assert row["top_paper_doi"] == "10.1/fullraw"
    assert row["velocity_score"] > 0


def test_seed_paper_candidate_skips_slow_discovery_when_enough(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("multi_agent_systems",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "3")
    monkeypatch.setattr(
        run_topic_discovery, "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "https://fullraw/search")

    def fake_fullraw(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        assert os.environ["TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"] == "6"
        return [{
            "doi": "10.1/seed", "title": "Seed paper-backed candidate",
            "fwci": 4.0, "cited_by_count": 40, "publication_year": 2026,
            "quality_score": 90.0,
            "fullraw_shard_receipt": _fullraw_receipt(),
        }]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["multi_agent_systems"]
    assert payload["top"][0]["top_paper_doi"] == "10.1/seed"
    assert payload["fullraw_seed_probe"]["configured"] is True
    assert payload["fullraw_seed_probe"]["receipt_count"] == 1
    receipt = payload["fullraw_seed_probe"]["receipts"][0]
    assert receipt["shards_searched"] == 1525
    assert receipt["partial_shard_search"] is False
    assert receipt["sweep_failed_shards"] == 0
    assert receipt["sources_searched"]["openalex"] == 900
    assert os.environ["TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"] == "20"


def test_seed_paper_probe_default_scales_with_requested_window(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    seeds = (*[f"blocked_{i}" for i in range(6)], "late_fresh_seed")
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: seeds,
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.delenv("TOPIC_DISCOVERY_SEED_PAPER_TOPICS", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "1")
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(
        run_topic_discovery,
        "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "late_fresh_seed":
            return [{
                "doi": "10.1/late",
                "title": "Late seed paper-backed candidate",
                "fwci": 4.0,
                "cited_by_count": 40,
                "publication_year": 2026,
                "quality_score": 90.0,
            }]
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "7",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == list(seeds)
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["late_fresh_seed"]


def test_seed_paper_probe_skips_excluded_seeds_before_fullraw(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    seeds = ("metformin", "spermidine", "late_fresh_seed")
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: seeds,
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery,
        "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_PAPER_TOPICS", "2")
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "1")
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: (),
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        return [{
            "doi": "10.1/late",
            "title": "Late seed paper-backed candidate",
            "fwci": 4.0,
            "cited_by_count": 40,
            "publication_year": 2026,
            "quality_score": 90.0,
        }]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--seed-paper-only", "--exclude-topic", "metformin",
        "--exclude-topic", "spermidine",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["late_fresh_seed"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["late_fresh_seed"]


def test_seed_paper_probe_requires_fullraw_endpoint_not_v5_client(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("metformin",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery,
        "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "1")
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: (),
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "_fetch_fullraw_topic_papers",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "_v5_client_papers",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("v4 fullraw must use the 9903 endpoint"),
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["top"] == []
    assert payload["fullraw_seed_probe"]["configured"] is False


def test_v5_client_bounds_restore_environment(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "99")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_QUERY_TIMEOUT", "98")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", "77")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MAX_VARIANTS", "8")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED", "1525")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED", "5")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", "6")

    old = run_topic_discovery._apply_v5_client_bounds()
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "6"
    assert os.environ["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "6"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS"] == "77"
    assert os.environ["V5_MEMO_FULL_RAW_MAX_VARIANTS"] == "2"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1525"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "5"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"

    run_topic_discovery._restore_env(old)
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "99"
    assert os.environ["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "98"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS"] == "77"
    assert os.environ["V5_MEMO_FULL_RAW_MAX_VARIANTS"] == "8"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1525"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "5"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"


def test_v5_client_bounds_inherit_fullraw_storage_waits(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "45")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_QUERY_TIMEOUT", "45")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MAX_VARIANTS", "16")

    old = run_topic_discovery._apply_v5_client_bounds()
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "30"
    assert os.environ["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "30"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_MAX_VARIANTS"] == "2"

    run_topic_discovery._restore_env(old)
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_MAX_VARIANTS"] == "16"


def test_v5_client_papers_relaxes_storage_audit_env(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    src = tmp_path / "src"
    package = src / "v5_memo"
    package.mkdir(parents=True)
    capture = tmp_path / "capture.json"
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    package.joinpath("client.py").write_text(
        """
import json
import os

class Hit:
    title = "Metformin longevity paper"
    doi = "10.1/met"
    hit_id = "W1"
    venue = "Journal"
    year = 2026
    url = "https://doi.org/10.1/met"
    metadata = {"shard_receipt": {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "sources_searched": {
            "openalex": 900,
            "pubmed": 120,
            "crossref": 90,
            "semantic_scholar": 60,
            "core": 40,
        },
    }}

class FullRawCorpusSearchClient:
    @classmethod
    def from_env(cls, *, strict=False):
        return cls(strict)

    def __init__(self, strict):
        self.strict = strict

    def search(self, query, *, limit):
        with open(CAPTURE, "w", encoding="utf-8") as handle:
            json.dump({
                "strict": self.strict,
                "query_timeout": os.environ.get("V5_MEMO_FULL_RAW_QUERY_TIMEOUT"),
                "max_variants": os.environ.get("V5_MEMO_FULL_RAW_MAX_VARIANTS"),
                "min_shards": os.environ.get("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"),
                "min_sources": os.environ.get("V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"),
                "require_complete": os.environ.get("V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"),
            }, handle)
        return [Hit()]
""".replace("CAPTURE", repr(str(capture))),
        encoding="utf-8",
    )
    monkeypatch.delitem(sys.modules, "v5_memo", raising=False)
    monkeypatch.delitem(sys.modules, "v5_memo.client", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SRC", str(src))
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED", "1525")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED", "5")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH", "1")

    rows = run_topic_discovery._v5_client_papers("metformin longevity", limit=1)

    assert rows[0]["title"] == "Metformin longevity paper"
    assert json.loads(capture.read_text(encoding="utf-8")) == {
        "strict": True,
        "query_timeout": "30",
        "max_variants": "2",
        "min_shards": "1525",
        "min_sources": "5",
        "require_complete": "1",
    }
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1525"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "5"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"


def test_fullraw_configured_rejects_v5_client_path_without_endpoint(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SRC", str(tmp_path))

    assert run_topic_discovery._fullraw_configured() is False


def test_fullraw_configured_accepts_index_token_default_endpoint(monkeypatch: Any) -> None:
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")

    assert run_topic_discovery._fullraw_configured() is True


def test_v5_env_loader_maps_researka_fullraw_aliases(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    env_file = tmp_path / "fullraw.env"
    env_file.write_text(
        "\n".join((
            "RESEARKA_FULLRAW_SEARCH_URL=http://127.0.0.1:9903/search",
            "RESEARKA_FULLRAW_TOKEN=tok-researka",
            "RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED=1525",
            "RESEARKA_FULLRAW_MIN_SOURCES_SEARCHED=5",
            "RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH=1",
            "RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS=900",
        )),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_ENV_FILE", str(env_file))
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_ENV_LOAD", "1")
    for key in (
        "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL",
        "V5_MEMO_FULL_RAW_INDEX_TOKEN",
        "V5_MEMO_FULL_RAW_CORPUS_TOKEN",
        "V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED",
        "V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED",
        "V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH",
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)

    run_topic_discovery._load_v5_env_defaults()

    assert run_topic_discovery._fullraw_configured() is True
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL"] == "http://127.0.0.1:9903/search"
    assert os.environ["V5_MEMO_FULL_RAW_INDEX_TOKEN"] == "tok-researka"
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TOKEN"] == "tok-researka"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1525"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "5"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "900"


def test_v5_client_bounds_allow_explicit_short_probe(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "45")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_QUERY_TIMEOUT", "45")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", "7200")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS", "6")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", "20")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS", "8")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_MAX_VARIANTS", "1")

    old = run_topic_discovery._apply_v5_client_bounds()
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "6"
    assert os.environ["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "6"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "20"
    assert os.environ["V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS"] == "8"
    assert os.environ["V5_MEMO_FULL_RAW_MAX_VARIANTS"] == "1"

    run_topic_discovery._restore_env(old)
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS"] == "7200"


def test_seed_paper_probe_expands_seed_queries_before_slow_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("llm_evaluation",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.delenv("TOPIC_DISCOVERY_SEED_QUERIES", raising=False)
    monkeypatch.setattr(
        run_topic_discovery, "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "llm evaluation":
            return [{
                "doi": "10.1/llm-eval", "title": "LLM evaluation benchmark paper",
                "fwci": 4.0, "cited_by_count": 40, "publication_year": 2026,
                "quality_score": 90.0,
            }]
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == [
        "llm_evaluation",
        "llm evaluation",
    ]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["llm_evaluation"]
    assert payload["top"][0]["top_paper_doi"] == "10.1/llm-eval"


def test_seed_paper_probe_stops_when_budget_spent(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("first_seed", "second_seed"),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS", "1")
    monkeypatch.setattr(
        run_topic_discovery,
        "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    now = {"value": 0.0}
    calls: list[str] = []
    monkeypatch.setattr(run_topic_discovery.time, "monotonic", lambda: now["value"])

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        now["value"] += 2.0
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["first_seed"]


def test_empty_seed_paper_probe_falls_back_to_domain_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fallback = (
        TopicCandidate(
            topic="multi_agent_systems", paper_count=3, fact_source_count=6,
            top_paper_doi="10.1/domain", top_paper_title="Domain backed paper",
            velocity_score=2.0, mean_fwci=1.0, mean_cited_by=10.0,
        ),
    )
    calls: list[str] = []

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return fallback

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://127.0.0.1/search")
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("multi_agent_systems",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "2")
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", lambda *_a, **_k: [])
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["multi_agent_systems"]


def test_empty_discovery_uses_fullraw_as_domain_supply_engine(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://127.0.0.1/search")
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "1")
    monkeypatch.setattr(
        run_topic_discovery,
        "load_seed_topics",
        lambda _path=None: ("metformin", "resveratrol"),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000,
    )
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: (),
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", lambda **_kw: ())
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query != "longevity anti aging":
            return []
        return [
            {
                "doi": f"10.1/vitd{i}",
                "title": f"Vitamin D deficiency and aging cohort {i}",
                "fwci": 2.0,
                "cited_by_count": 20 + i,
                "publication_year": 2025,
                "quality_score": 90.0,
                "fullraw_shard_receipt": _fullraw_receipt(),
            }
            for i in range(5)
        ]

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["top"][0]["topic"] == "deficiency_aging"
    assert payload["top"][0]["paper_count"] == 5
    assert payload["top"][0]["fact_source_count"] == 5
    assert payload["source_rich_count"] == 1
    assert payload["fullraw_seed_probe"]["receipts"][-1]["seed"] == "__domain_supply__"
    assert "longevity anti aging" in calls


def test_fullraw_supply_queries_seeds_when_domain_query_is_empty(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    limits: list[int] = []

    def fake_fullraw(
        query: str, *_args: Any, limit: int = 0, **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        calls.append(query)
        limits.append(limit)
        if query == "metformin":
            return _fullraw_rows("met", "Metformin longevity geroscience AMPK")
        if query == "resveratrol":
            return _fullraw_rows("res", "Resveratrol aging sirtuin senescence")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=2,
        seeds=("metformin", "resveratrol"),
    )

    topics = {row.topic for row in rows}
    assert "metformin" in calls
    assert "resveratrol" in calls
    assert set(limits) == {25}
    assert {"metformin", "resveratrol"} <= topics


def test_fullraw_supply_mines_beyond_probe_floor_for_coherent_topic(
    monkeypatch: Any,
) -> None:
    mixed = [
        "Rapamycin aging lifespan evidence",
        "Metformin aging cohort",
        "Vitamin D aging mortality",
        "Spermidine aging autophagy trial",
        "Quercetin aging inflammation",
    ]
    clustered = [f"Fisetin longevity senescence trial {i}" for i in range(5)]
    papers = [
        {
            "doi": f"10.1/paper{i}",
            "title": title,
            "fwci": 2.0,
            "cited_by_count": 20 + i,
            "publication_year": 2025,
            "quality_score": 90.0,
        }
        for i, title in enumerate([*mixed, *clustered])
    ]
    limits: list[int] = []

    def fake_fullraw(
        query: str, *_args: Any, limit: int = 0, **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        limits.append(limit)
        return papers[:limit] if query == "longevity anti aging" else []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
    )

    assert limits == [25]
    assert rows
    assert rows[0].fact_source_count == 5
    assert rows[0].top_paper_title.startswith("Fisetin longevity senescence")
    assert rows[0].topic in run_topic_discovery._FULLRAW_SUPPLY_SOURCE_PAPERS


def test_fullraw_supply_stops_after_concrete_source_rich_domain_query(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "longevity anti aging":
            return _fullraw_rows("domain", "Spermidine longevity source rich")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=2,
        seeds=("metformin", "resveratrol"),
    )

    assert calls[0] == "longevity anti aging"
    assert "spermidine_longevity" in {row.topic for row in rows}
    assert all(run_topic_discovery._concrete_topic(row.topic) for row in rows)
    assert all(row.fact_source_count == 5 for row in rows)


def test_fullraw_supply_prefers_seed_query_over_domain_placeholder(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "longevity anti aging":
            return _fullraw_rows("domain", "Longevity anti aging source rich")
        if query == "metformin longevity":
            return _fullraw_rows("met", "Metformin longevity geroscience AMPK")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
        seeds=("metformin",),
    )

    assert calls == ["longevity anti aging", "metformin longevity"]
    assert [row.topic for row in rows] == ["metformin_longevity"]


def test_fullraw_supply_keeps_seed_query_when_context_titles_are_sparse(
    monkeypatch: Any,
) -> None:
    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        if query == "metformin longevity":
            return _fullraw_rows("met", "Metformin AMPK intervention")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
        seeds=("metformin",),
    )

    assert [row.topic for row in rows] == ["metformin_longevity"]
    assert rows[0].paper_count == 5
    assert rows[0].fact_source_count == 5


def test_fullraw_supply_rejects_seed_query_supported_only_by_context(
    monkeypatch: Any,
) -> None:
    papers = _fullraw_rows("ctx", "Longevity pathway mitochondrial health", 5)

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return papers if query == "rapamycin longevity" else []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
        seeds=("rapamycin",),
    )

    assert rows == ()


def test_fullraw_supply_queries_domain_before_seed_breadth(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "metformin longevity":
            return _fullraw_rows("met", "Metformin longevity geroscience AMPK")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
        seeds=("rapamycin", "metformin", "resveratrol"),
    )

    assert [row.topic for row in rows] == ["metformin_longevity"]
    assert calls == [
        "longevity anti aging",
        "rapamycin longevity",
        "metformin longevity",
    ]


def test_fullraw_supply_searches_past_seed_probe_cap(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "late seed longevity":
            return _fullraw_rows("late", "Late seed longevity source rich")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
        seeds=(
            "seed_a", "seed_b", "seed_c", "seed_d", "seed_e", "seed_f",
            "late_seed",
        ),
    )

    assert [row.topic for row in rows] == ["late_seed_longevity"]
    assert "late seed longevity" in calls


def test_fullraw_supply_continues_seed_variants_until_window_filled(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "metformin longevity":
            return _fullraw_rows("lon", "Metformin longevity cohort")
        if query == "metformin anti aging":
            return _fullraw_rows("aging", "Metformin anti aging senescence")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=2,
        seeds=("metformin",),
    )

    assert {row.topic for row in rows} == {
        "metformin_anti_aging", "metformin_longevity",
    }
    assert "metformin anti aging" in calls


def test_fullraw_supply_uses_configured_window_for_seed_query(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    caps: list[tuple[str | None, str | None, str | None]] = []
    monkeypatch.delenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", raising=False)

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        caps.append((
            os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"),
        ))
        if query == "factor premia returns finance":
            return _fullraw_rows("factor", "Factor premia returns")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Finance research",
        current_year=2026,
        top=1,
        seeds=("factor_premia_returns",),
    )

    assert calls == ["factor premia returns finance"]
    assert caps == [("90.0", "75.0", "60.0")]
    assert [row.topic for row in rows] == ["factor_premia_returns_finance"]


def test_fullraw_supply_rejects_multi_token_seed_supported_by_one_token(
    monkeypatch: Any,
) -> None:
    papers = _fullraw_rows("green", "Green finance total factor productivity")

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return papers if query.startswith("factor") else []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Finance research",
        current_year=2026,
        top=1,
        seeds=("factor_premia_returns",),
    )

    assert rows == ()


def test_fullraw_supply_stops_when_total_pass_budget_is_spent(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    now = {"value": 0.0}

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        now["value"] = 2.0
        return []

    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS", "1")
    monkeypatch.setattr(run_topic_discovery.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)
    run_topic_discovery._FULLRAW_PROBE_EVENTS.clear()

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=2,
        seeds=("metformin", "resveratrol"),
    )

    assert rows == ()
    assert calls == ["longevity anti aging"]
    event = run_topic_discovery._FULLRAW_PROBE_EVENTS[-1]
    assert event["status"] == "budget_exhausted"
    assert event["attempted_queries"] == ["longevity anti aging"]
    assert event["skipped_query_count"] > 0


def test_fullraw_supply_caps_each_query_window(monkeypatch: Any) -> None:
    caps: list[tuple[str | None, str | None, str | None, str | None]] = []
    monkeypatch.delenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", raising=False)

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        assert query == "longevity anti aging"
        caps.append((
            os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_MAX_VARIANTS"),
        ))
        return []

    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS", "120")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", "240")
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
    )

    assert rows == ()
    assert len(caps) == 1
    assert caps[0][0] == "3.0"
    assert caps[0][1] == "75.0"
    assert 119.0 <= float(caps[0][2] or 0) <= 120.0
    assert caps[0][3] == "2"
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_MAX_VARIANTS") is None


def test_fullraw_supply_defaults_are_candidate_supply_sized(monkeypatch: Any) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", raising=False)

    assert run_topic_discovery._fullraw_supply_budget_seconds() == 240.0
    assert run_topic_discovery._fullraw_supply_query_timeout_seconds() == 90.0
    assert run_topic_discovery._fullraw_supply_query_budget_seconds() == 75.0
    assert run_topic_discovery._fullraw_supply_sweep_wait_seconds() == 60.0


def test_fullraw_supply_defaults_inherit_fullraw_search_contract(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", "900")

    assert run_topic_discovery._fullraw_supply_budget_seconds() == 7200.0
    assert run_topic_discovery._fullraw_supply_query_budget_seconds() == 7200.0
    assert run_topic_discovery._fullraw_supply_sweep_wait_seconds() == 900.0


def test_fullraw_supply_strict_contract_floors_short_researka_budget(
    monkeypatch: Any,
) -> None:
    for key in (
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS",
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS",
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS",
        "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
        "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS",
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS",
        "V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS",
        "V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS",
        "V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH",
        "V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", "900")
    monkeypatch.setenv("RESEARKA_FULLRAW_FOREGROUND_SWEEP_WAIT_SECONDS", "30")
    monkeypatch.setenv("RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH", "1")
    monkeypatch.setenv("RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED", "1525")

    assert run_topic_discovery._fullraw_supply_budget_seconds() == 2400.0
    assert run_topic_discovery._fullraw_supply_query_budget_seconds() == 2400.0
    assert run_topic_discovery._fullraw_supply_sweep_wait_seconds() == 2370.0


def test_fullraw_supply_explicit_overrides_are_not_strict_floored(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS", "90")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS", "80")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS", "70")
    monkeypatch.setenv("RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH", "1")
    monkeypatch.setenv("RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED", "1525")

    assert run_topic_discovery._fullraw_supply_budget_seconds() == 90.0
    assert run_topic_discovery._fullraw_supply_query_budget_seconds() == 80.0
    assert run_topic_discovery._fullraw_supply_sweep_wait_seconds() == 70.0


def test_fullraw_compacts_long_queries_to_high_signal_terms() -> None:
    query = (
        "randomized controlled clinical trial healthy older adults determine "
        "efficacy urolithin A mitochondrial aging"
    )

    assert run_topic_discovery._compact_fullraw_query(query) == (
        "clinical trial urolithin mitochondrial aging"
    )


def test_fullraw_supply_dedupes_near_duplicate_query_shapes(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        return []

    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_CAP_MULTIPLIER", "20")
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="",
        current_year=2026,
        top=1,
        seeds=("urolithin_a_mitochondrial_aging", "urolithin_mitochondrial_aging"),
    )

    assert rows == ()
    assert calls.count("urolithin mitochondrial aging") == 1
    assert not any(query == "urolithin a mitochondrial aging" for query in calls)


def test_fullraw_supply_query_cap_defaults_to_small_candidate_window(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_CAP_MULTIPLIER", raising=False)

    assert run_topic_discovery._fullraw_supply_query_cap(2) == 16


def test_fullraw_supply_prefers_alpha_shape_queries_before_bare_seed(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "urolithin mitochondrial aging replication":
            return _fullraw_rows("urolithin", "Urolithin mitochondrial aging replication")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="",
        current_year=2026,
        top=1,
        seeds=("urolithin_mitochondrial_aging",),
    )

    assert [row.topic for row in rows] == ["urolithin_mitochondrial_aging_replication"]
    assert calls[:3] == [
        "urolithin mitochondrial aging",
        "urolithin mitochondrial aging null",
        "urolithin mitochondrial aging replication",
    ]


def test_fullraw_supply_stops_after_repeated_busy_receipts(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        run_topic_discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "incomplete_receipt",
            "partial_shard_search": True,
            "shards_searched": 200,
        })
        return []

    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_BUSY_PROBE_LIMIT", "2")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_CAP_MULTIPLIER", "20")
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)
    run_topic_discovery._FULLRAW_PROBE_EVENTS.clear()

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="",
        current_year=2026,
        top=1,
        seeds=(
            "urolithin_mitochondrial_aging",
            "resveratrol_exercise_adaptation",
            "metformin_longevity",
        ),
    )

    assert rows == ()
    assert calls == [
        "urolithin mitochondrial aging",
        "resveratrol exercise adaptation",
    ]
    assert run_topic_discovery._FULLRAW_PROBE_EVENTS[-1] == {
        "status": "fullraw_busy_probe_limit_reached",
        "attempted_queries": calls,
        "skipped_query_count": 10,
    }


def test_fullraw_alpha_shape_terms_are_configurable_and_bounded(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS",
        "null,failed,blunted,subgroup",
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_QUERY_LIMIT", "2")

    assert run_topic_discovery._alpha_shape_query_terms() == ("null", "failed")


def test_fullraw_supply_prefers_context_seed_query_over_bare_seed(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "fisetin longevity":
            return _fullraw_rows("fis-lon", "Fisetin longevity senescence")
        if query == "fisetin":
            return _fullraw_rows("fis-off", "Fisetin glioblastoma cytotoxicity")
        return []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
        seeds=("fisetin",),
    )

    assert [row.topic for row in rows] == ["fisetin_longevity"]
    assert rows[0].top_paper_title.startswith("Fisetin longevity")
    assert calls[:2] == ["longevity anti aging", "fisetin longevity"]
    assert "fisetin" not in calls


def test_fullraw_supply_fallback_does_not_resurrect_excluded_topic(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "1")
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("metformin", "fisetin"),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_seed_paper_candidates", lambda *_a, **_kw: ())
    monkeypatch.setattr(run_topic_discovery, "discover_topics", lambda **_kw: ())

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        if query == "longevity anti aging":
            return _fullraw_rows("met", "Metformin longevity geroscience AMPK")
        if query == "fisetin":
            return _fullraw_rows("fis", "Fisetin aging senescence burden")
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--exclude-topic", "metformin",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["fisetin"]
    assert len(payload["top"][0]["source_papers"]) == 5
    assert payload["top"][0]["source_papers"][0]["doi"].startswith("10.1/fis")


def test_fullraw_supply_requires_per_topic_source_floor(monkeypatch: Any) -> None:
    papers = [
        {
            "doi": f"10.1/vitd{i}",
            "title": f"Vitamin D deficiency and aging cohort {i}",
            "fwci": 2.0,
            "cited_by_count": 20 + i,
            "publication_year": 2025,
            "quality_score": 90.0,
        }
        for i in range(4)
    ]
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", lambda *_a, **_k: papers)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
    )

    assert rows == ()


def test_fullraw_supply_does_not_promote_underfloor_domain_fallback(
    monkeypatch: Any,
) -> None:
    papers = [
        {
            "doi": f"10.1/lon{i}",
            "title": f"Spermidine longevity aging cohort {i}",
            "fwci": 2.0,
            "cited_by_count": 20 + i,
            "publication_year": 2025,
            "quality_score": 90.0,
        }
        for i in range(4)
    ] + [{
        "doi": "10.1/offscope",
        "title": "Glioblastoma chemotherapy response",
        "fwci": 2.0,
        "cited_by_count": 30,
        "publication_year": 2025,
        "quality_score": 90.0,
    }]
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", lambda *_a, **_k: papers)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
    )

    assert rows == ()


def test_fullraw_supply_title_slugs_stay_domain_or_seed_scoped(
    monkeypatch: Any,
) -> None:
    papers = _fullraw_rows(
        "mac", "Aging related macular degeneration retinal cohort",
    ) + _fullraw_rows("epi", "Epigenetic clocks longevity biomarker cohort")

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return papers if query == "longevity anti aging" else []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=3,
        seeds=("epigenetic_clocks",),
    )

    topics = {row.topic for row in rows}
    assert "epigenetic_clocks" in topics
    assert not any("macular" in topic or "degeneration" in topic for topic in topics)


def test_fullraw_supply_title_slugs_do_not_truncate_seed_topics(
    monkeypatch: Any,
) -> None:
    papers = _fullraw_rows(
        "stem", "Stem cell aging intervention cohort",
    ) + _fullraw_rows("epi", "Epigenetic clocks longevity biomarker cohort")

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return papers if query == "longevity anti aging" else []

    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=4,
        seeds=("stem_cell_exhaustion", "epigenetic_clocks"),
    )

    topics = {row.topic for row in rows}
    assert "stem_cell" not in topics
    assert "epigenetic_clocks" in topics


def test_fullraw_supply_uses_domain_query_when_titles_do_not_cluster(
    monkeypatch: Any,
) -> None:
    papers = [
        {
            "doi": f"10.1/mixed{i}",
            "title": title,
            "fwci": 2.0,
            "cited_by_count": 20 + i,
            "publication_year": 2025,
            "quality_score": 90.0,
        }
        for i, title in enumerate((
            "Rapamycin aging lifespan evidence",
            "Metformin aging cohort",
            "Vitamin D aging mortality",
            "Spermidine aging autophagy trial",
            "Fisetin aging senescence review",
        ))
    ]
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", lambda *_a, **_k: papers)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
    )

    assert rows == ()


def test_seed_paper_only_skips_slow_domain_discovery_when_empty(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return ()

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("multi_agent_systems",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", lambda *_a, **_k: [])
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == []
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["seed_paper_only"] is True
    assert payload["top"] == []
    assert payload["fullraw_seed_probe"]["events"][0]["status"] == "no_hits"


def test_fullraw_supply_only_skips_seed_and_db_expansion_when_empty(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("metformin",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", lambda *_a, **_k: [])
    monkeypatch.setattr(
        run_topic_discovery,
        "_seed_paper_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("seed probe")),
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "discover_topics",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "2",
        "--fullraw-supply-only",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["fullraw_supply_only"] is True
    assert payload["candidate_count"] == 0
    assert payload["top"] == []


def test_fullraw_supply_only_loads_v5_env_before_config_receipt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    env_file = tmp_path / "v5.env"
    env_file.write_text("V5_MEMO_FULL_RAW_INDEX_TOKEN=tok-from-file\n", encoding="utf-8")
    for key in (
        "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL",
        "V5_MEMO_FULL_RAW_INDEX_TOKEN",
        "V5_MEMO_FULL_RAW_CORPUS_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_ENV_FILE", str(env_file))
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_ENV_LOAD", "1")
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("metformin",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", lambda *_a, **_k: [])
    monkeypatch.setattr(
        run_topic_discovery,
        "_seed_paper_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("seed probe")),
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "discover_topics",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--fullraw-supply-only",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["fullraw_seed_probe"]["configured"] is True


def test_skip_seed_paper_probe_goes_directly_to_domain_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fallback = (
        TopicCandidate(
            topic="seed_fresh", paper_count=5, fact_source_count=5,
            top_paper_doi="10.1/fresh", top_paper_title="Fresh seed",
            velocity_score=2.0, mean_fwci=1.0, mean_cited_by=4.0,
        ),
    )
    calls: list[str] = []

    def fake_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return fallback

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(
        run_topic_discovery, "_fetch_fullraw_topic_papers",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("seed probe")),
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--skip-seed-paper-probe",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["seed_fresh"]


def test_seed_paper_probe_uses_domain_context_query(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics", lambda _path=None: ("metformin",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setenv("TOPIC_DISCOVERY_SEED_QUERIES", "2")
    monkeypatch.setattr(
        run_topic_discovery, "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("slow discovery")),
    )
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "metformin longevity":
            return [{
                "doi": "10.1/metformin-context",
                "title": "Metformin longevity evidence",
                "fwci": 4.0,
                "cited_by_count": 40,
                "publication_year": 2026,
                "quality_score": 90.0,
            }]
        return []

    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["metformin", "metformin longevity"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["metformin"]
    assert payload["top"][0]["top_paper_doi"] == "10.1/metformin-context"


def test_partial_seed_paper_probe_still_fills_window_from_domain_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fallback = (
        TopicCandidate(
            topic="tool_use_agents", paper_count=4, fact_source_count=7,
            top_paper_doi="10.1/tool", top_paper_title="Tool use agent paper",
            velocity_score=3.0, mean_fwci=2.0, mean_cited_by=12.0,
        ),
    )
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        if query == "multi_agent_systems":
            return [{
                "doi": "10.1/seed", "title": "Seed paper-backed candidate",
                "fwci": 4.0, "cited_by_count": 40, "publication_year": 2026,
                "quality_score": 90.0,
            }]
        return []

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return fallback

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("multi_agent_systems", "tool_use_agents"),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "2",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == [
        "tool_use_agents",
        "multi_agent_systems",
    ]


def test_domain_fullraw_supply_preempts_lower_floor_seed_top_up(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "metformin":
            return [{
                "doi": "10.1/metformin", "title": "Metformin longevity paper",
                "fwci": 4.0, "cited_by_count": 40, "publication_year": 2026,
                "quality_score": 90.0,
            }]
        if query == "longevity anti aging":
            return [
                {
                    "doi": f"10.1/vitd{i}",
                    "title": f"Vitamin D deficiency and aging cohort {i}",
                    "fwci": 2.0,
                    "cited_by_count": 20 + i,
                    "publication_year": 2025,
                    "quality_score": 90.0,
                }
                for i in range(5)
            ]
        return []

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("metformin",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", fake_fullraw)
    monkeypatch.setattr(run_topic_discovery, "discover_topics", lambda **_kwargs: ())
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "2",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert "longevity anti aging" in calls
    assert {row["topic"] for row in payload["top"]} == {
        "aging_cohort",
        "deficiency_aging",
    }


def test_discovery_hydration_tries_domain_context_after_bare_label(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    fallback = (
        TopicCandidate(
            topic="seed_source_diverse", paper_count=8, fact_source_count=10,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    calls: list[str] = []

    def fake_fetch(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "seed_source_diverse longevity anti aging":
            return [{
                "doi": "10.1/context", "title": "Context hydrated paper",
                "fwci": 3.0, "cited_by_count": 20, "publication_year": 2026,
                "quality_score": 90.0,
            }]
        return []

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "discover_topics", lambda **_kw: fallback)
    monkeypatch.setattr(run_topic_discovery, "_fetch_topic_papers", fake_fetch)
    monkeypatch.setattr(sys, "argv", ["run_topic_discovery.py", "--top", "1"])

    assert run_topic_discovery.main() == 0
    assert calls == [
        "seed_source_diverse",
        "seed source diverse",
        "seed_source_diverse longevity anti aging",
    ]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    row = payload["top"][0]
    assert row["top_paper_title"] == "Context hydrated paper"
    assert row["top_paper_doi"] == "10.1/context"


def test_paperless_topic_group_discovery_falls_back_to_paper_backed_topic(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[tuple[str, int, int | None]] = []

    def fake_discover(**kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append((
            os.environ.get("TOPIC_GROUPS_DISCOVERY", "1"),
            kwargs["derived_topic_limit"],
            kwargs["fact_probe_topics"],
        ))
        if calls[-1][0] == "0":
            return (
                TopicCandidate(
                    topic="multi_agent_systems", paper_count=3, fact_source_count=6,
                    top_paper_doi="10.1/mas", top_paper_title="MAS fresh paper",
                    velocity_score=3.0, mean_fwci=2.0, mean_cited_by=10.0,
                ),
            )
        return (
            TopicCandidate(
                topic="RAG", paper_count=29, fact_source_count=29,
                top_paper_doi="", top_paper_title="",
                velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
            ),
        )

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("RAG", "multi_agent_systems"),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(
        run_topic_discovery, "load_derived_topic_limit",
        lambda _path=None: 5_000,
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(
        run_topic_discovery, "_fetch_topic_papers",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("short paperless labels should not hydrate")
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == [("1", 250, None), ("0", 10, 3)]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["multi_agent_systems"]
    assert payload["top"][0]["top_paper_title"] == "MAS fresh paper"


def test_excluded_cached_topics_do_not_fill_cache_first_window(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="seed_old_winner", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fallback = (
        TopicCandidate(
            topic="seed_fresh_rich", paper_count=3, fact_source_count=9,
            top_paper_doi="10.1/fresh", top_paper_title="Fresh",
            velocity_score=2.0, mean_fwci=1.0, mean_cited_by=4.0,
        ),
    )
    calls: list[str] = []

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append("discover")
        return fallback

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--top", "1",
        "--exclude-topic", "seed_old_winner",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["seed_fresh_rich"]


def test_excluded_topic_family_does_not_fill_cache_first_window(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="metformin_use", paper_count=8, fact_source_count=11,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
        TopicCandidate(
            topic="resveratrol_supplementation", paper_count=8, fact_source_count=9,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("metformin", "resveratrol"))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(
        run_topic_discovery, "discover_topics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("cache-only")),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--cache-only", "--top", "2",
        "--exclude-topic", "metformin_treatment",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["resveratrol_supplementation"]


def test_topic_family_exclusion_keeps_unrelated_longevity_topics() -> None:
    candidates = (
        TopicCandidate(
            topic="omega_3_longevity", paper_count=8, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
        TopicCandidate(
            topic="semaglutide_once_weekly", paper_count=8, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )

    out = run_topic_discovery._filter_excluded(candidates, {"GLP_1_longevity"})

    assert [row.topic for row in out] == ["omega_3_longevity", "semaglutide_once_weekly"]


def test_cache_only_skips_slow_discovery_when_cache_is_underfilled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="seed_cached_rich", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        raise AssertionError("cache-only must not fetch seed papers")

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--cache-only", "--top", "2",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["cache_only"] is True
    assert payload["candidate_count"] == 1
    assert [row["topic"] for row in payload["top"]] == ["seed_cached_rich"]


def test_cache_only_filters_cached_topics_to_domain_seed_scope(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="retrieval_augmented_generation", paper_count=10,
            fact_source_count=10, top_paper_doi="10.1/rag",
            top_paper_title="Retrieval augmented generation",
            velocity_score=3.0, mean_fwci=2.0, mean_cited_by=10.0,
        ),
        TopicCandidate(
            topic="multi_agent_systems", paper_count=10,
            fact_source_count=10, top_paper_doi="10.1/mas",
            top_paper_title="Multi-agent systems",
            velocity_score=2.5, mean_fwci=2.0, mean_cited_by=10.0,
        ),
        TopicCandidate(
            topic="semaglutide_once_weekly", paper_count=4,
            fact_source_count=7, top_paper_doi="10.1/glp",
            top_paper_title="Once-weekly semaglutide",
            velocity_score=2.0, mean_fwci=1.5, mean_cited_by=8.0,
        ),
    )

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        raise AssertionError("cache-only must not fetch seed papers")

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics", lambda: ("semaglutide",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda: 5_000)
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--cache-only", "--top", "2",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["semaglutide_once_weekly"]


def test_business_family_discovery_filters_longevity_topics(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    def fake_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        return (
            TopicCandidate(
                topic="hormone_optimization_hrt_hormonal", paper_count=9,
                fact_source_count=9, top_paper_doi="10.1/hrt",
                top_paper_title="Hormone optimization",
                velocity_score=9.0, mean_fwci=2.0, mean_cited_by=20.0,
            ),
            TopicCandidate(
                topic="business_model_performance_margin", paper_count=8,
                fact_source_count=8, top_paper_doi="10.1/biz",
                top_paper_title="Business model performance",
                velocity_score=8.0, mean_fwci=2.0, mean_cited_by=18.0,
            ),
            TopicCandidate(
                topic="digital_ads_conversion_lift", paper_count=7,
                fact_source_count=7, top_paper_doi="10.1/ads",
                top_paper_title="Digital ads conversion lift",
                velocity_score=7.0, mean_fwci=2.0, mean_cited_by=17.0,
            ),
            TopicCandidate(
                topic="employee_engagement_turnover_risk", paper_count=6,
                fact_source_count=6, top_paper_doi="10.1/mgmt",
                top_paper_title="Employee engagement and turnover risk",
                velocity_score=6.0, mean_fwci=2.0, mean_cited_by=16.0,
            ),
        )

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    expected = {
        "business_research": "business_model_performance_margin",
        "marketing_research": "digital_ads_conversion_lift",
        "management_research": "employee_engagement_turnover_risk",
    }
    for domain, expected_topic in expected.items():
        monkeypatch.setattr(sys, "argv", [
            "run_topic_discovery.py", "--domain", domain, "--top", "2",
        ])

        assert run_topic_discovery.main() == 0
        out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
        payload = json.loads(out[-1].read_text(encoding="utf-8"))
        emitted = [row["topic"] for row in payload["top"]]
        assert "hormone_optimization_hrt_hormonal" not in emitted
        assert emitted == [expected_topic]


def test_exhausted_strict_seed_scope_uses_source_rich_domain_candidate(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    def fake_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        return (
            TopicCandidate(
                topic="SGLT2 inhibitors", paper_count=12, fact_source_count=18,
                top_paper_doi="10.1/sglt2",
                top_paper_title="SGLT2 inhibitors and aging outcomes",
                velocity_score=5.0, mean_fwci=2.0, mean_cited_by=20.0,
            ),
            TopicCandidate(
                topic="dapagliflozin", paper_count=8, fact_source_count=11,
                top_paper_doi="10.1/fresh",
                top_paper_title="Dapagliflozin outcomes in older adults",
                velocity_score=4.0, mean_fwci=1.8, mean_cited_by=18.0,
            ),
        )

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery, "load_seed_topics",
        lambda _path=None: ("SGLT2 inhibitors",),
    )
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
    monkeypatch.setattr(run_topic_discovery, "cached_source_rich_candidates", lambda *, limit: ())
    monkeypatch.setattr(run_topic_discovery, "_fetch_fullraw_topic_papers", lambda *_a, **_k: [])
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--exclude-topic", "SGLT2 inhibitors",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["dapagliflozin"]
    assert payload["source_rich_count"] == 1


def test_cache_first_preserves_cached_source_papers(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as discovery

    cache_path = tmp_path / "supply_cache.json"
    cache_path.write_text(json.dumps({
        "paper_backed": {
            "count": 6,
            "ts": 4_100_000_000,
            "version": discovery._SUPPLY_CACHE_VERSION,
            "source_papers": [{
                "doi": "10.1/cache",
                "title": "Cached paper",
                "fwci": 2.0,
                "cited_by_count": 100,
                "publication_year": 2025,
                "quality_score": 80,
            }],
        },
    }), encoding="utf-8")
    monkeypatch.setattr(discovery, "_SUPPLY_CACHE_PATH", cache_path)

    rows = discovery.cached_source_rich_candidates(limit=1)

    assert len(rows) == 1
    assert rows[0].topic == "paper_backed"
    assert rows[0].paper_count == 1
    assert rows[0].top_paper_doi == "10.1/cache"
