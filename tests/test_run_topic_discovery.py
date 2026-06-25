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
def _disable_live_v5_client(monkeypatch: Any) -> None:
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK", "0")


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
        if query == "longevity anti aging":
            return _fullraw_rows("raw", "Longevity anti aging source rich")
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
    assert calls[0] == "longevity anti aging"
    assert payload["top"][0]["topic"].startswith("longevity")


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
            "fullraw_shard_receipt": {
                "shards_searched": 1305,
                "partial_shard_search": False,
                "sources_searched": {"openalex": 988, "pubmed": 374},
            },
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
    assert payload["fullraw_seed_probe"]["receipts"][0]["shards_searched"] == 1305
    assert payload["fullraw_seed_probe"]["receipts"][0]["partial_shard_search"] is False
    assert payload["fullraw_seed_probe"]["receipts"][0]["sources_searched"]["openalex"] == 988
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


def test_seed_paper_probe_uses_v5_client_before_direct_http(
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
        lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("direct HTTP fallback"))
        ),
    )
    monkeypatch.setattr(
        run_topic_discovery,
        "_v5_client_papers",
        lambda *_args, **_kwargs: [{
            "doi": "10.1/v5",
            "title": "V5 client fullraw candidate",
            "fwci": 4.0,
            "cited_by_count": 40,
            "publication_year": 2026,
            "quality_score": 90.0,
            "fullraw_shard_receipt": {
                "shards_searched": 1514,
                "partial_shard_search": False,
                "sources_searched": {"openalex": 988},
            },
        }],
    )
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "longevity_research", "--top", "1",
        "--seed-paper-only",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["top"][0]["topic"] == "metformin"
    assert payload["top"][0]["top_paper_doi"] == "10.1/v5"
    assert payload["fullraw_seed_probe"]["receipts"][0]["shards_searched"] == 1514


def test_v5_client_bounds_restore_environment(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "99")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS", "77")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED", "1514")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED", "4")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", "6")

    old = run_topic_discovery._apply_v5_client_bounds()
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "6"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS"] == "20"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "1"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "0"

    run_topic_discovery._restore_env(old)
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "99"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS"] == "77"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1514"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "4"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"


def test_v5_client_bounds_do_not_inherit_long_storage_waits(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "45")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS", "7200")

    old = run_topic_discovery._apply_v5_client_bounds()
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "20"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS"] == "20"

    run_topic_discovery._restore_env(old)
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS"] == "7200"


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
    metadata = {"shard_receipt": {"shards_searched": 50, "sources_searched": {"openalex": 50}}}

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
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED", "1514")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED", "4")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH", "1")

    rows = run_topic_discovery._v5_client_papers("metformin longevity", limit=1)

    assert rows[0]["title"] == "Metformin longevity paper"
    assert json.loads(capture.read_text(encoding="utf-8")) == {
        "strict": False,
        "min_shards": "1",
        "min_sources": "1",
        "require_complete": "0",
    }
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1514"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "4"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"


def test_v5_client_bounds_allow_explicit_short_probe(monkeypatch: Any) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "45")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS", "7200")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS", "6")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", "20")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS", "8")

    old = run_topic_discovery._apply_v5_client_bounds()
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "6"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "20"
    assert os.environ["V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS"] == "8"

    run_topic_discovery._restore_env(old)
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TIMEOUT"] == "45"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "7200"
    assert os.environ["V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS"] == "7200"


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
                "fullraw_shard_receipt": {
                    "shards_searched": 1514,
                    "partial_shard_search": False,
                    "sources_searched": {"openalex": 900},
                },
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
    assert payload["top"][0]["topic"] == "vitamin_deficiency"
    assert payload["top"][0]["paper_count"] == 5
    assert payload["top"][0]["fact_source_count"] == 5
    assert payload["source_rich_count"] == 1
    assert payload["fullraw_seed_probe"]["receipts"][-1]["seed"] == "__domain_supply__"
    assert "longevity anti aging" in calls


def test_fullraw_supply_queries_seeds_when_domain_query_is_empty(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
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
    assert "longevity anti aging" in calls
    assert "metformin" in calls
    assert "resveratrol" in calls
    assert {"metformin", "resveratrol"} <= topics


def test_fullraw_supply_samples_seed_breadth_before_seed_variants(
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
    assert calls == ["longevity anti aging", "rapamycin longevity", "metformin longevity"]


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

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=2,
        seeds=("metformin", "resveratrol"),
    )

    assert rows == ()
    assert calls == ["longevity anti aging"]


def test_fullraw_supply_caps_each_query_timeout(monkeypatch: Any) -> None:
    caps: list[tuple[str | None, str | None, str | None]] = []

    def fake_fullraw(query: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        assert query == "longevity anti aging"
        caps.append((
            os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
            os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"),
        ))
        return []

    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS", "12")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_fullraw)

    rows = run_topic_discovery._fullraw_supply_candidates(
        query_context="Longevity / anti-aging research",
        current_year=2026,
        top=1,
    )

    assert rows == ()
    assert caps == [("3.0", "3.0", "3.0")]
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS") is None


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
    assert "fisetin longevity" in calls
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

    assert [(row.topic, row.paper_count, row.fact_source_count) for row in rows] == [
        ("longevity_anti_aging", 5, 5),
    ]


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
        "deficiency_aging",
        "vitamin_deficiency",
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
