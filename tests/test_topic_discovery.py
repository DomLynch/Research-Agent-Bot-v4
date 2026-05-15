"""Sprint 63 — autonomous topic-discovery tests.

Locks the velocity-scoring + ranking contract:
  - empty seeds -> empty result
  - per-paper score formula: fwci * log(1+cited) * recency * quality
  - missing fields -> zero contribution (graceful)
  - HTTP / JSON error -> empty paper list -> zero score
  - topics ranked by velocity descending
  - TOML missing / malformed -> empty seed list
  - Universal: non-biomedical seed list works identically
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx

from agent.topic_discovery import (
    TopicCandidate,
    _paper_score,
    _score_topic,
    discover_topics,
    load_seed_topics,
)


def _settings() -> Any:
    s = MagicMock()
    s.researka_database_url = "https://test"
    s.researka_database_token = "tok"
    return s


def _paper(**kw: Any) -> dict[str, Any]:
    base = {"doi": "10.1/x", "title": "Paper",
            "fwci": 1.0, "cited_by_count": 100,
            "publication_year": 2024, "quality_score": 70.0}
    base.update(kw)
    return base


def test_paper_score_baseline() -> None:
    """fwci=1, cited=100, year=current → ln(101) * 1 * 1 * 0.7"""
    expected = 1.0 * math.log1p(100) * 1.0 * 0.7
    assert abs(_paper_score(_paper(), 2024) - expected) < 1e-6


def test_paper_score_recency_decay() -> None:
    """5-year-old paper: recency_weight = 1 - 5/10 = 0.5"""
    score_now = _paper_score(_paper(publication_year=2024), 2024)
    score_old = _paper_score(_paper(publication_year=2019), 2024)
    assert score_old < score_now
    assert abs(score_old - score_now * 0.5) < 0.01


def test_paper_score_minimum_recency_floor() -> None:
    """Old papers: recency_weight floors at 0.2 (not below)."""
    score = _paper_score(_paper(publication_year=2000), 2024)
    expected_floor = 1.0 * math.log1p(100) * 0.2 * 0.7
    assert abs(score - expected_floor) < 1e-6


def test_paper_score_zero_on_missing_year() -> None:
    """No publication_year -> 0 (cannot compute recency)."""
    assert _paper_score(_paper(publication_year=None), 2024) == 0.0


def test_paper_score_handles_malformed_values() -> None:
    """Non-numeric fwci doesn't crash."""
    assert _paper_score(_paper(fwci="not-a-number"), 2024) == 0.0


def test_score_topic_picks_strongest_paper_as_anchor() -> None:
    """top_paper_doi is the highest-scoring paper."""
    papers = [
        _paper(doi="10.1/low", fwci=0.5, cited_by_count=10),
        _paper(doi="10.1/high", fwci=5.0, cited_by_count=500),
        _paper(doi="10.1/mid", fwci=2.0, cited_by_count=100),
    ]
    out = _score_topic("rapamycin", papers, 2024)
    assert out.top_paper_doi == "10.1/high"
    assert out.paper_count == 3


def test_score_topic_empty_papers_returns_zero() -> None:
    out = _score_topic("rapamycin", [], 2024)
    assert out.paper_count == 0
    assert out.velocity_score == 0.0
    assert out.top_paper_doi == ""


def test_discover_topics_ranks_by_velocity() -> None:
    """Two seed topics; richer one ranks first."""
    weak_papers = [_paper(fwci=0.1, cited_by_count=5)]
    strong_papers = [_paper(fwci=10.0, cited_by_count=1000)
                     for _ in range(3)]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if "weak" in body:
            return httpx.Response(200, json=weak_papers)
        return httpx.Response(200, json=strong_papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("weak_topic", "strong_topic"),
            settings=_settings(), client=c, current_year=2024,
        )
    assert len(out) == 2
    assert out[0].topic == "strong_topic"
    assert out[0].velocity_score > out[1].velocity_score


def test_discover_topics_handles_http_error_gracefully() -> None:
    """HTTP 500 → empty paper list → zero score, no raise."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream blew up")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("topic_a",), settings=_settings(), client=c,
        )
    assert len(out) == 1
    assert out[0].velocity_score == 0.0


def test_discover_topics_empty_seeds_returns_empty() -> None:
    out = discover_topics(
        seeds=(), settings=_settings(), client=None,
    )
    assert out == ()


def test_no_token_returns_zero_papers() -> None:
    s = MagicMock()
    s.researka_database_url = "https://x"
    s.researka_database_token = "   "  # whitespace
    with httpx.Client() as c:
        out = discover_topics(seeds=("topic_a",), settings=s, client=c)
    assert out[0].paper_count == 0


def test_load_seed_topics_missing_file() -> None:
    load_seed_topics.cache_clear()
    out = load_seed_topics(Path("/nonexistent.toml"))
    assert out == ()


def test_load_seed_topics_malformed_toml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("= = = totally invalid =", encoding="utf-8")
    load_seed_topics.cache_clear()
    assert load_seed_topics(bad) == ()


def test_load_seed_topics_real_seeds_loaded() -> None:
    """The shipped TOML returns a non-empty tuple of strings."""
    load_seed_topics.cache_clear()
    seeds = load_seed_topics()
    assert len(seeds) >= 5
    assert all(isinstance(s, str) and s.strip() for s in seeds)


def test_candidate_as_dict_round_trip() -> None:
    c = TopicCandidate(
        topic="rapamycin", paper_count=10, top_paper_doi="10.1/x",
        top_paper_title="Paper", velocity_score=12.345,
        mean_fwci=2.5, mean_cited_by=120.7,
    )
    d = c.as_dict()
    assert d["topic"] == "rapamycin"
    assert d["velocity_score"] == 12.345
    assert d["mean_cited_by"] == 120.7


def test_universal_non_biomedical_seed_list() -> None:
    """Climate-policy seed list ranks identically to biomedical."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            _paper(doi="ipcc/swe", title="Sweden CO2 tax 8% cut",
                   fwci=3.0, cited_by_count=200),
        ])
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("carbon_tax", "renewable_subsidy"),
            settings=_settings(), client=c,
        )
    assert len(out) == 2
    assert all(o.velocity_score > 0 for o in out)
