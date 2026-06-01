"""CLI limit policy tests for the alpha topic-discovery runner."""
from __future__ import annotations

import json
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
    monkeypatch.setattr(run_topic_discovery, "load_seed_topics", lambda: ("seed",))
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


def test_cache_first_skips_slow_discovery_when_window_is_filled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    cached = (
        TopicCandidate(
            topic="rich_a", paper_count=0, fact_source_count=8,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
        ),
        TopicCandidate(
            topic="rich_b", paper_count=0, fact_source_count=7,
            top_paper_doi="", top_paper_title="",
            velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
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
    assert [row["topic"] for row in payload["top"]] == ["rich_a", "rich_b"]


def test_cache_first_falls_back_when_cache_is_underfilled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
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
        lambda *, limit: (),
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", slow_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--cache-first", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert calls == ["discover"]
