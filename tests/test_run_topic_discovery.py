"""CLI limit policy tests for the alpha topic-discovery runner."""
from __future__ import annotations

import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_topic_discovery
from run_topic_discovery import _resolve_limits

from agent.topic_discovery import TopicCandidate


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
