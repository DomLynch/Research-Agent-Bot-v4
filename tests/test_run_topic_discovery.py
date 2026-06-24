"""CLI limit policy tests for the alpha topic-discovery runner."""
from __future__ import annotations

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


def test_longevity_research_lane_can_use_longevity_cache() -> None:
    assert run_topic_discovery._cache_supported_domain("longevity_research") is True
    assert run_topic_discovery._cache_supported_domain("ai_research") is False


def test_main_writes_limit_metadata_for_operator_overrides(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[tuple[int, int | None]] = []

    def fake_discover(**kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append((kwargs["derived_topic_limit"], kwargs["fact_probe_topics"]))
        return (
            TopicCandidate(
                topic="topic", paper_count=1, fact_source_count=5,
                top_paper_doi="10.1/x", top_paper_title="Paper",
                velocity_score=1.0, mean_fwci=1.0, mean_cited_by=1.0,
            ),
        )

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
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


def test_cache_first_skips_slow_discovery_when_window_is_filled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="rich_a", paper_count=5, fact_source_count=8,
            top_paper_doi="10.1/a", top_paper_title="Paper A",
            velocity_score=2.0, mean_fwci=1.0, mean_cited_by=10.0,
        ),
        TopicCandidate(
            topic="rich_b", paper_count=5, fact_source_count=7,
            top_paper_doi="10.1/b", top_paper_title="Paper B",
            velocity_score=1.0, mean_fwci=1.0, mean_cited_by=8.0,
        ),
    )

    def slow_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        raise AssertionError("cache-first should not fetch seed papers")

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
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
    assert [row["topic"] for row in payload["top"]] == ["rich_a", "rich_b"]


def test_cache_first_falls_back_when_cache_is_underfilled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="cached_rich", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fallback = (
        TopicCandidate(
            topic="fresh_rich", paper_count=3, fact_source_count=9,
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
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("seed",))
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
    assert calls == ["discover", "discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["fresh_rich", "cached_rich"]


def test_cache_first_does_not_let_paperless_cache_suppress_fresh_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="cached_rich", paper_count=0, fact_source_count=12,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fresh = (
        TopicCandidate(
            topic="fresh_fullraw", paper_count=3, fact_source_count=6,
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
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("seed",))
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
    assert [row["topic"] for row in payload["top"]] == ["fresh_fullraw"]


def test_paperless_topic_group_discovery_falls_back_to_paper_backed_topics(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_discover(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        calls.append(os.environ.get("TOPIC_GROUPS_DISCOVERY", "1"))
        if calls[-1] == "0":
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
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("seed",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(run_topic_discovery, "_fetch_topic_papers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["1", "0"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["multi_agent_systems"]


def test_excluded_cached_topics_do_not_fill_cache_first_window(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="old_winner", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fallback = (
        TopicCandidate(
            topic="fresh_rich", paper_count=3, fact_source_count=9,
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
        "--exclude-topic", "old_winner",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert [row["topic"] for row in payload["top"]] == ["fresh_rich"]


def test_cache_only_skips_slow_discovery_when_cache_is_underfilled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="cached_rich", paper_count=0, fact_source_count=8,
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
    assert [row["topic"] for row in payload["top"]] == ["cached_rich"]


def test_empty_discovery_uses_fullraw_as_source_rich_supply(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    class Hit:
        def __init__(self, n: int) -> None:
            self.title = f"Metformin longevity paper {n}"
            self.doi = f"10.1/fullraw.{n}"
            self.year = 2025
            self.metadata = {"cited_by_count": n}

    class FakeFullraw:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def search(self, query: str, *, limit: int = 25) -> list[Hit]:
            self.calls.append((query, limit))
            return [Hit(i) for i in range(6)]

    fullraw = FakeFullraw()
    cached = (
        TopicCandidate(
            topic="cached_rich", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
    )
    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda _path=None: ("metformin",))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "load_derived_topic_limit", lambda _path=None: 5_000)
    monkeypatch.setattr(run_topic_discovery, "discover_topics", lambda **_kwargs: ())
    monkeypatch.setattr(
        run_topic_discovery, "cached_source_rich_candidates",
        lambda *, limit: cached[:limit],
    )
    monkeypatch.setattr(run_topic_discovery, "_fullraw_search_client", lambda: fullraw)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert fullraw.calls == [("metformin Longevity anti-aging", 25)]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 2
    assert payload["top"][0]["topic"] == "metformin"
    assert payload["top"][0]["paper_count"] == 6
    assert payload["top"][0]["fact_source_count"] == 6


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
