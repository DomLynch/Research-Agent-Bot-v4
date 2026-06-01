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

import json
import math
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx

from agent.topic_discovery import (
    TopicCandidate,
    _anchorage_counts,
    _derived_title_supported,
    _fact_probe_queries,
    _paper_score,
    _paper_title_facets,
    _score_topic,
    _title_topic_slugs,
    discover_topics,
    load_derived_topic_limit,
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


def test_fetch_papers_by_topic_uses_bounded_parallelism(monkeypatch: Any) -> None:
    from agent import topic_discovery as td

    seen_threads: set[int] = set()

    def fake_fetch(topic: str, **_kw: Any) -> list[dict[str, Any]]:
        seen_threads.add(threading.get_ident())
        time.sleep(0.01)
        return [_paper(doi=f"10.1/{topic}")]

    monkeypatch.setattr(td, "_fetch_topic_papers", fake_fetch)

    out = td._fetch_papers_by_topic(
        [f"topic_{i}" for i in range(12)], client=MagicMock(), settings=_settings())

    assert len(out) == 12
    assert len(seen_threads) > 1
    assert len(seen_threads) <= td._PAPER_FETCH_WORKERS


def test_fetch_papers_by_topic_can_require_title_support() -> None:
    from agent import topic_discovery as td

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if "low_dose_naltrexone_inflammation" in body:
            return httpx.Response(200, json=[
                _paper(title="Low dose CT screening in older adults"),
                _paper(title="Low dose radiation exposure and cancer risk"),
            ])
        return httpx.Response(200, json=[
            _paper(title="Grid storage tariffs improve adoption"),
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = td._fetch_papers_by_topic(
            ["low_dose_naltrexone_inflammation", "grid_storage"],
            client=c, settings=_settings(),
            require_title_support=True, current_year=2024,
        )

    assert out["low_dose_naltrexone_inflammation"] == []
    assert out["grid_storage"]


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


def test_load_derived_topic_limit_from_real_config() -> None:
    assert load_derived_topic_limit() >= 5_000


def test_title_topic_slugs_derive_candidates_from_paper_titles() -> None:
    out = _title_topic_slugs({
        "seed": [_paper(title="Carbon pricing and grid storage improve adoption")],
    }, current_year=2024, limit=8)

    assert "carbon_pricing" in out
    assert "grid_storage" in out
    assert all("study" not in slug for slug in out)


def test_title_topic_slugs_can_emit_5000_unique_candidates() -> None:
    papers = [
        _paper(
            title=(
                f"alpha{i} beta{i} gamma{i} delta{i} epsilon{i} "
                f"zeta{i} eta{i} theta{i}"
            ),
            doi=f"10.1/{i}",
        )
        for i in range(300)
    ]

    out = _title_topic_slugs({"seed": papers}, current_year=2024, limit=5_000)

    assert len(out) >= 5_000
    assert len(out) == len(set(out))


def test_title_topic_slugs_drop_cross_scope_connectors() -> None:
    out = _title_topic_slugs({
        "seed": [_paper(
            title="Risk factors across cohorts predict healthy aging outcomes",
            fwci=10.0,
            cited_by_count=1000,
        )],
    }, current_year=2024, limit=20)

    assert "risk_factors_across" not in out
    assert all("across" not in slug.split("_") for slug in out)


def test_derived_title_support_filters_generic_fragment_matches() -> None:
    assert _derived_title_supported("grid_storage", [
        _paper(title="Grid storage tariffs improve adoption"),
    ], 2024)
    assert not _derived_title_supported("low_dose_naltrexone_inflammation", [
        _paper(title="Low dose CT screening in older adults"),
        _paper(title="Low dose steroid therapy in chronic inflammation"),
        _paper(title="Low dose radiation exposure and cancer risk"),
    ], 2024)


def test_candidate_as_dict_round_trip() -> None:
    c = TopicCandidate(
        topic="rapamycin", paper_count=10, fact_source_count=6,
        top_paper_doi="10.1/x", top_paper_title="Paper", velocity_score=12.345,
        mean_fwci=2.5, mean_cited_by=120.7,
    )
    d = c.as_dict()
    assert d["topic"] == "rapamycin"
    assert d["fact_source_count"] == 6
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


# ============= Sprint 70 — cross-topic anchorage dampening =============

def test_anchorage_counts_per_paper_topic_membership() -> None:
    """Sprint 70: same DOI in 3 topics' top-K → count == 3.
    Universal across-topic structural signal."""
    shared = _paper(doi="10.1/shared", fwci=5.0, cited_by_count=500)
    unique = _paper(doi="10.1/unique_a", fwci=1.0, cited_by_count=10)
    counts = _anchorage_counts({
        "topic_a": [shared, unique],
        "topic_b": [shared],
        "topic_c": [shared],
    }, current_year=2024)
    assert counts.get("10.1/shared") == 3
    assert counts.get("10.1/unique_a") == 1


def test_score_topic_dampens_cross_topic_anchor() -> None:
    """Sprint 70 / auditor: an ACC/AHA-style paper that anchors three
    topics has its contribution dampened by 1/sqrt(3). Same paper in
    isolation (single-topic) keeps full score. Universal."""
    paper = _paper(doi="10.1/acc-aha", fwci=10.0, cited_by_count=1000)
    solo = _score_topic(
        "topic_x", [paper], 2024, anchorage={"10.1/acc-aha": 1},
    )
    crowded = _score_topic(
        "topic_x", [paper], 2024, anchorage={"10.1/acc-aha": 3},
    )
    assert crowded.velocity_score < solo.velocity_score
    expected = solo.velocity_score / math.sqrt(3)
    assert abs(crowded.velocity_score - expected) < 1e-6


def test_score_topic_no_dampening_for_solo_anchor() -> None:
    """M < 3 → no dampening. Single-topic specificity preserved."""
    paper = _paper(doi="10.1/specific", fwci=5.0, cited_by_count=200)
    no_anchor = _score_topic("t", [paper], 2024, anchorage=None)
    m1 = _score_topic("t", [paper], 2024, anchorage={"10.1/specific": 1})
    m2 = _score_topic("t", [paper], 2024, anchorage={"10.1/specific": 2})
    assert abs(no_anchor.velocity_score - m1.velocity_score) < 1e-6
    assert abs(no_anchor.velocity_score - m2.velocity_score) < 1e-6


def test_discover_topics_dampens_acc_aha_style_anchor() -> None:
    """Sprint 70 / auditor case: a single broad guideline appears as
    the top driver of three unrelated topics. After dampening, those
    topics' velocity scores drop; a topic with a unique strong paper
    overtakes them."""
    # Cross-domain anchor: same DOI returned for 3 topics.
    # Raw score ≈ 20 * ln(2001) * 0.7 ≈ 106.4; dampened by 1/sqrt(3)
    # ≈ 61.4.
    shared = _paper(doi="10.1/guideline",
                    title="Broad guideline anchoring 3 topics",
                    fwci=20.0, cited_by_count=2000)
    # Topic-specific paper for one topic only — strong enough to
    # overtake the dampened guideline. Raw ≈ 15 * ln(1001) * 0.7
    # ≈ 72.5 > 61.4.
    unique = _paper(doi="10.1/topic_d_only",
                    title="Topic-specific finding",
                    fwci=15.0, cited_by_count=1000)

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if "topic_d" in body:
            return httpx.Response(200, json=[unique])
        return httpx.Response(200, json=[shared])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("topic_a", "topic_b", "topic_c", "topic_d"),
            settings=_settings(), client=c, current_year=2024,
        )
    # Without dampening, the 3 shared-anchor topics would rank top.
    # With dampening, topic_d's unique paper rises.
    ranked_topics = [c.topic for c in out]
    assert ranked_topics.index("topic_d") < ranked_topics.index("topic_a")
    assert all(o.velocity_score > 0 for o in out)


def test_discover_topics_prefers_fact_source_breadth(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    """Paper velocity alone should not outrank a submit-floor-sized fact shelf."""
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    fast_thin = [_paper(doi="10.1/fast", fwci=20.0, cited_by_count=2000)]
    slower_rich = [_paper(doi="10.1/rich", fwci=2.0, cited_by_count=100)]

    def facts(n: int, topic: str) -> list[dict[str, Any]]:
        return [
            {
                "id": f"f{i}", "paper_id": f"10.2/{i}",
                "paper": {"doi": f"10.2/{i}"},
                "numeric_value": 10, "units": "%",
                "population": "adults",
                "intervention": topic.replace("_", " "),
                "canonical_phrase": f"{topic.replace('_', ' ')} reduced risk by 10%",
            }
            for i in range(n)
        ]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            topic = "rich_topic" if "rich" in body else "fast_topic"
            return httpx.Response(200, json=facts(5 if "rich" in body else 1, topic))
        if "rich" in body:
            return httpx.Response(200, json=slower_rich)
        return httpx.Response(200, json=fast_thin)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("fast_topic", "rich_topic"),
            settings=_settings(), client=c, current_year=2024,
        )

    assert out[0].topic == "rich_topic"
    assert out[0].fact_source_count == 5
    assert out[1].fact_source_count == 1


def test_discover_topics_warm_backlog_can_probe_all_seed_topics(
    monkeypatch: Any,
) -> None:
    """Submit path stays bounded; backlog mode can still cover the seed pool."""
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_FACT_PROBE_TOPICS", 1)
    fast_thin = [_paper(doi="10.1/fast", fwci=20.0, cited_by_count=2000)]
    slow_rich = [_paper(doi="10.1/rich", fwci=0.2, cited_by_count=10)]

    def facts(n: int, topic: str) -> list[dict[str, Any]]:
        return [
            {
                "id": f"f{i}", "paper_id": f"10.2/{topic}/{i}",
                "paper": {"doi": f"10.2/{topic}/{i}"},
                "numeric_value": 10, "units": "%",
                "population": "adults",
                "intervention": topic.replace("_", " "),
                "comparator": "usual care",
                "canonical_phrase": f"{topic.replace('_', ' ')} improved risk by 10%",
            }
            for i in range(n)
        ]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            topic = "slow_rich_topic" if "slow rich" in body else "fast_thin_topic"
            return httpx.Response(200, json=facts(5 if "slow rich" in body else 1, topic))
        if "slow_rich" in body:
            return httpx.Response(200, json=slow_rich)
        return httpx.Response(200, json=fast_thin)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = td.discover_topics(
            seeds=("fast_thin_topic", "slow_rich_topic"),
            settings=_settings(), client=c, current_year=2024,
            fact_probe_topics=2,
        )

    assert out[0].topic == "slow_rich_topic"
    assert out[0].fact_source_count == 5


def test_discover_topics_can_rank_derived_title_candidates(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    seed_papers = [_paper(
        doi="10.1/seed",
        title="Carbon pricing and grid storage improve adoption",
        fwci=2.0,
    )]
    derived_papers = [_paper(
        doi="10.1/derived",
        title="Grid storage tariffs improve adoption",
        fwci=12.0,
    )]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            return httpx.Response(200, json=[])
        if "grid_storage" in body:
            return httpx.Response(200, json=derived_papers)
        return httpx.Response(200, json=seed_papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = td.discover_topics(
            seeds=("seed_topic",), settings=_settings(), client=c,
            current_year=2024, derived_topic_limit=8,
        )

    topics = [c.topic for c in out]
    assert "grid_storage" in topics
    assert topics.index("seed_topic") < topics.index("grid_storage")


def test_discover_topics_lets_fact_rich_derived_candidate_outrank_seed(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    seed_papers = [_paper(
        doi="10.1/seed",
        title="Carbon pricing and grid storage improve adoption",
        fwci=10.0,
    )]
    derived_papers = [_paper(
        doi="10.1/derived",
        title="Grid storage tariffs improve adoption",
        fwci=2.0,
    )]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            if "grid" not in body:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[
                {
                    "id": f"f{i}", "paper_id": f"10.2/{i}",
                    "paper": {"doi": f"10.2/{i}"},
                    "numeric_value": 10, "units": "%",
                    "population": "adults",
                    "intervention": "grid storage tariffs",
                    "comparator": "usual care",
                    "canonical_phrase": "grid storage tariffs improved adoption by 10%",
                }
                for i in range(5)
            ])
        if "grid_storage" in body:
            return httpx.Response(200, json=derived_papers)
        return httpx.Response(200, json=seed_papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("seed_topic",), settings=_settings(), client=c,
            current_year=2024, derived_topic_limit=8,
        )

    assert out[0].topic == "grid_storage"
    assert out[0].fact_source_count == 5


def test_backlog_probe_window_can_cover_derived_topic_pool() -> None:
    """Backlog warming can probe every derived topic without slowing publish."""
    from agent import topic_discovery as td

    assert td.load_derived_topic_limit() > td._FACT_PROBE_TOPICS
    assert td.load_derived_topic_limit() <= td._DERIVED_TOPIC_LIMIT


def test_discover_topics_fact_probe_limit_keeps_submit_path_bounded(
    monkeypatch: Any,
) -> None:
    from agent import topic_discovery as td

    def fake_fetch(topics: list[str], **_: Any) -> dict[str, list[dict[str, Any]]]:
        return {
            topic: [_paper(
                doi=f"10.1/{topic}",
                title=topic.replace("_", " "),
                fwci=4.0 if topic.startswith("derived_") else 1.0,
            )]
            for topic in topics
        }

    seen: list[str] = []

    def capture_fact_source_counts(topics: list[str], **_: Any) -> dict[str, int]:
        seen.extend(topics)
        return {}

    monkeypatch.setattr(td, "_fetch_papers_by_topic", fake_fetch)
    monkeypatch.setattr(td, "_title_topic_slugs", lambda *_args, **_kw: [
        "derived_one", "derived_two", "derived_three",
    ])
    monkeypatch.setattr(td, "_fetch_fact_source_counts", capture_fact_source_counts)

    td.discover_topics(
        seeds=("seed_topic",), settings=_settings(), client=httpx.Client(),
        current_year=2024, derived_topic_limit=3, fact_probe_topics=1,
    )

    assert "seed_topic" in seen
    assert len([topic for topic in seen if topic.startswith("derived_")]) == 1


def test_discover_topics_advances_derived_probe_window_past_cached_head(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "derived_one": {
            "count": 0, "ts": time.time(), "version": td._SUPPLY_CACHE_VERSION,
        },
    }), encoding="utf-8")

    def fake_fetch(topics: list[str], **_: Any) -> dict[str, list[dict[str, Any]]]:
        return {
            topic: [_paper(
                doi=f"10.1/{topic}", title=topic.replace("_", " "), fwci=4.0)]
            for topic in topics
        }

    seen: list[str] = []

    def capture_fact_source_counts(topics: list[str], **_: Any) -> dict[str, int]:
        seen.extend(topics)
        return {}

    monkeypatch.setattr(td, "_fetch_papers_by_topic", fake_fetch)
    monkeypatch.setattr(td, "_title_topic_slugs", lambda *_args, **_kw: [
        "derived_one", "derived_two", "derived_three",
    ])
    monkeypatch.setattr(td, "_fetch_fact_source_counts", capture_fact_source_counts)

    td.discover_topics(
        seeds=("seed_topic",), settings=_settings(), client=httpx.Client(),
        current_year=2024, derived_topic_limit=3, fact_probe_topics=1,
    )

    assert "derived_one" not in seen
    assert "derived_two" in seen


def test_discover_topics_backfills_after_unsupported_derived_titles(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")

    def fake_fetch(
        topics: list[str], *, require_title_support: bool = False,
        current_year: int | None = None, **_: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for topic in topics:
            title = (
                "Generic low dose screening review"
                if topic == "low_dose_naltrexone_inflammation"
                else topic.replace("_", " ")
            )
            papers = [_paper(doi=f"10.1/{topic}", title=title, fwci=4.0)]
            if require_title_support and not td._derived_title_supported(
                topic, papers, current_year or 2024,
            ):
                papers = []
            out[topic] = papers
        return out

    seen: list[str] = []

    def capture_fact_source_counts(topics: list[str], **_: Any) -> dict[str, int]:
        seen.extend(topics)
        return {}

    monkeypatch.setattr(td, "_fetch_papers_by_topic", fake_fetch)
    monkeypatch.setattr(td, "_title_topic_slugs", lambda *_args, **_kw: [
        "low_dose_naltrexone_inflammation", "grid_storage", "carbon_pricing",
    ])
    monkeypatch.setattr(td, "_fetch_fact_source_counts", capture_fact_source_counts)

    td.discover_topics(
        seeds=("seed_topic",), settings=_settings(), client=httpx.Client(),
        current_year=2024, derived_topic_limit=3, fact_probe_topics=1,
    )

    assert "low_dose_naltrexone_inflammation" not in seen
    assert "grid_storage" in seen


def test_derived_cycle_keeps_rich_visible_and_warms_tail(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "rich_one": {
            "count": 6, "ts": time.time(), "version": td._SUPPLY_CACHE_VERSION,
        },
        "thin_one": {
            "count": 1, "ts": time.time(), "version": td._SUPPLY_CACHE_VERSION,
        },
    }), encoding="utf-8")

    out = td._derived_cycle_topics(
        ["rich_one", "thin_one", "new_one", "new_two"],
        limit=2, refresh_low_source_counts=False,
    )

    assert out == ["rich_one", "new_one"]


def test_inconclusive_probe_ignores_stale_cache_version(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "topic_a": {
            "count": 10, "ts": time.time(), "version": td._SUPPLY_CACHE_VERSION - 1,
        },
    }), encoding="utf-8")
    monkeypatch.setattr(
        td, "_fetch_topic_fact_source_count",
        lambda *_args, **_kwargs: td._PROBE_INCONCLUSIVE,
    )

    out = td._fetch_fact_source_counts(
        ["topic_a"], client=httpx.Client(), settings=_settings())

    assert out["topic_a"] == 0


def test_discover_topics_counts_slug_prefix_fact_sources(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    papers = [_paper(doi="10.1/omega", fwci=2.0, cited_by_count=100)]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            if "omega 3" not in body or "longevity" in body:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[
                {
                    "id": f"f{i}", "paper_id": f"10.2/{i}",
                    "paper": {"doi": f"10.2/{i}"},
                    "numeric_value": 10, "units": "%",
                    "population": "adults",
                    "intervention": "omega 3",
                    "canonical_phrase": "omega 3 changed risk by 10%",
                }
                for i in range(5)
            ])
        return httpx.Response(200, json=papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("omega_3_longevity",),
            settings=_settings(), client=c, current_year=2024,
        )

    assert out[0].fact_source_count == 5


def test_fact_source_count_respects_probe_budget(monkeypatch: Any) -> None:
    from agent import topic_discovery

    def handler(_req: httpx.Request) -> httpx.Response:
        raise AssertionError("fact probe should not call DB after budget expires")

    monkeypatch.setattr(topic_discovery, "_FACT_PROBE_BUDGET_SECONDS", 0.0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = topic_discovery._fetch_topic_fact_source_count(
            "omega_3_longevity", client=c, settings=_settings(),
        )

    # Budget expired before any probe ran, so the DB was never asked: the
    # count is *inconclusive*, not a genuine 0. The sentinel lets the caller
    # fall back to a cached count instead of mis-ranking the topic at 0.
    assert out == topic_discovery._PROBE_INCONCLUSIVE


def test_fact_source_probe_deepens_exact_query_then_bounds_facets() -> None:
    from agent import topic_discovery

    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        topic_discovery._fetch_topic_fact_source_count(
            "omega_3_longevity", client=c, settings=_settings(),
        )

    assert bodies[0]["top_k"] == 500
    assert bodies[1]["top_k"] == 50
    assert bodies[0]["min_confidence"] == "medium"
    assert bodies[0]["numeric_only"] is True


def test_paper_title_facets_are_data_derived() -> None:
    facets = _paper_title_facets("berberine", [
        _paper(title="Berberine improves glucose metabolism in randomized trials"),
        _paper(title="Berberine and lipid control in metabolic disease"),
    ], 2024)

    assert "glucose metabolism" in facets
    assert "randomized trials" in facets


def test_fact_probe_queries_include_data_derived_facets() -> None:
    queries = _fact_probe_queries(
        "berberine", facets=("glucose metabolism", "randomized trials"),
    )

    assert queries[0] == "berberine"
    assert "glucose metabolism" in queries
    assert "randomized trials" in queries


def test_fact_probe_queries_keep_compound_topic_root_early() -> None:
    queries = _fact_probe_queries("vitamin_K2_vascular_aging")

    assert queries[:2] == (
        "vitamin_K2_vascular_aging",
        "vitamin k2",
    )


def test_fact_probe_queries_skip_generic_low_dose_root() -> None:
    queries = _fact_probe_queries("low_dose_naltrexone_inflammation", max_queries=8)

    assert "low dose naltrexone" in queries
    assert "naltrexone" in queries
    assert "low dose" not in queries
    assert "low dose therapy" not in queries


def test_fact_probe_queries_include_distinctive_compound_atoms() -> None:
    queries = _fact_probe_queries("berberine_longevity", max_queries=8)

    assert "berberine" in queries
    assert "berberine longevity" in queries


def test_fact_source_probe_finds_sources_from_data_derived_facets() -> None:
    from agent import topic_discovery

    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        bodies.append(body)
        if body["query"] != "glucose metabolism":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[
            {
                "id": f"fact-{i}",
                "paper_id": f"paper-{i}",
                "paper": {"doi": f"10.1/berb-{i}", "title": f"Trial {i}"},
                "numeric_value": 10,
                "units": "%",
                "population": "adults",
                "intervention": "berberine",
                "comparator": "placebo",
                "canonical_phrase": "berberine reduced mortality risk by 10%",
            }
            for i in range(5)
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = topic_discovery._fetch_topic_fact_source_count(
            "berberine", client=c, settings=_settings(),
            facets=("glucose metabolism",),
        )

    assert out == 5
    assert "glucose metabolism" in [b["query"] for b in bodies]


def test_registered_synonyms_precede_title_facets() -> None:
    queries = _fact_probe_queries(
        "vitamin_K2_vascular_aging",
        facets=("oxidative stress", "aging mechanisms"),
    )

    assert queries[:8] == (
        "vitamin_K2_vascular_aging",
        "vitamin k2",
        "vitamin k2 vascular aging",
        "vitamin K2",
        "menaquinone",
        "menaquinone-7",
        "menaquinone 7",
        "MK-7",
    )
    assert "oxidative stress" in queries


def test_fact_source_count_uses_pmcid_and_paper_id_source_keys() -> None:
    """Source breadth uses the same DOI > PMID > PMCID > paper_id identity
    order as the publish gate, so no-DOI papers do not collapse by title."""
    from agent import topic_discovery

    rows = [
        {
            "id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "paper": {"pmcid": f"PMC{i}", "title": "Shared title"},
            "numeric_value": 10,
            "units": "%",
            "population": "adults",
            "intervention": "omega 3",
            "comparator": "usual care",
            "canonical_phrase": "omega 3 improved risk by 10%",
        }
        for i in range(5)
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = topic_discovery._fetch_topic_fact_source_count(
            "omega_3_longevity", client=c, settings=_settings(),
        )

    assert out == 5


def test_fact_source_probe_counts_canonical_topic_endpoint() -> None:
    from agent import topic_discovery

    rows = [
        {
            "fact_id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "source_paper": {"doi": f"10.1/brain-{i}", "title": f"Trial {i}"},
            "numeric_value": 10,
            "units": "%",
            "population": "brain age MRI cohort",
            "intervention": "exercise",
            "comparator": "usual care",
            "canonical_phrase": "exercise reduced brain age MRI gap by 10%",
        }
        for i in range(5)
    ]
    seen_paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_paths.append(req.url.path)
        if req.url.path.endswith("/api/v1/topics/brain_age_MRI/facts"):
            return httpx.Response(200, json=rows)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = topic_discovery._fetch_topic_fact_source_count(
            "brain_age_MRI", client=c, settings=_settings())

    assert out == 5
    assert "/api/v1/topics/brain_age_MRI/facts" in seen_paths


def test_fact_source_profile_emits_source_backed_child_topics() -> None:
    from agent import topic_discovery

    rows = [
        {
            "id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "paper": {"doi": f"10.1/rt-{i}", "title": f"Trial {i}"},
            "numeric_value": 10,
            "units": "%",
            "population": "older adults with sarcopenia",
            "intervention": "resistance training",
            "comparator": "usual care",
            "canonical_phrase": "resistance training improved muscle mass by 10%",
        }
        for i in range(5)
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        count, children = topic_discovery._fetch_topic_fact_source_profile(
            "sarcopenia_muscle_preservation", client=c, settings=_settings())

    assert count == 5
    assert ("resistance_training", 5) in children


def test_fact_source_profile_empty_rows_emit_no_sources_or_children() -> None:
    from agent import topic_discovery

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        count, children = topic_discovery._fetch_topic_fact_source_profile(
            "alzheimer_disease", client=c, settings=_settings())

    assert count == 0
    assert children == ()


def test_disease_population_context_facts_emit_children_not_parent_sources() -> None:
    from agent import topic_discovery

    rows = [
        {
            "id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "paper": {"doi": f"10.1/ex-{i}", "title": f"Trial {i}"},
            "numeric_value": 10,
            "units": "%",
            "population": "older adults with alzheimer disease",
            "intervention": "resistance training",
            "comparator": "usual care",
            "canonical_phrase": "resistance training improved mobility by 10%",
        }
        for i in range(5)
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        count, children = topic_discovery._fetch_topic_fact_source_profile(
            "alzheimer_disease", client=c, settings=_settings())

    assert count == 0
    assert ("resistance_training", 5) in children


def test_disease_population_context_count_does_not_clear_parent_floor() -> None:
    from agent import topic_discovery

    rows = [
        {
            "id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "paper": {"doi": f"10.1/pop-{i}", "title": f"Trial {i}"},
            "numeric_value": 10,
            "units": "%",
            "population": "patients with alzheimer disease",
            "intervention": "cognitive training",
            "comparator": "usual care",
            "canonical_phrase": "cognitive training improved memory by 10%",
        }
        for i in range(5)
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        count = topic_discovery._fetch_topic_fact_source_count(
            "alzheimer_disease", client=c, settings=_settings())

    assert count == 0


def test_fact_source_profile_emits_claim_phrase_child_topics() -> None:
    from agent import topic_discovery

    rows = [
        {
            "id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "paper": {"doi": f"10.1/bg-{i}", "title": f"Trial {i}"},
            "numeric_value": 10,
            "units": "%",
            "population": "adults",
            "intervention": "berberine",
            "comparator": "placebo",
            "canonical_phrase": (
                "berberine improved glucose metabolism by 10 percent"),
        }
        for i in range(5)
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        count, children = topic_discovery._fetch_topic_fact_source_profile(
            "berberine", client=c, settings=_settings())

    assert count == 5
    assert ("berberine_glucose_metabolism", 5) in children


def test_discover_topics_adds_fact_derived_source_rich_children(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    seed_papers = [_paper(
        doi="10.1/seed", title="Sarcopenia muscle preservation review", fwci=3.0)]
    child_papers = [_paper(
        doi="10.1/child", title="Resistance training improves muscle mass", fwci=2.0)]
    rows = [
        {
            "id": f"fact-{i}",
            "paper_id": f"paper-{i}",
            "paper": {"doi": f"10.1/rt-{i}", "title": f"Trial {i}"},
            "numeric_value": 10,
            "units": "%",
            "population": "older adults with sarcopenia",
            "intervention": "resistance training",
            "comparator": "usual care",
            "canonical_phrase": "resistance training improved muscle mass by 10%",
        }
        for i in range(5)
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            return httpx.Response(200, json=rows)
        if "resistance_training" in body:
            return httpx.Response(200, json=child_papers)
        return httpx.Response(200, json=seed_papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = discover_topics(
            seeds=("sarcopenia_muscle_preservation",),
            settings=_settings(), client=c, current_year=2024,
            fact_probe_topics=5,
        )

    by_topic = {candidate.topic: candidate for candidate in out}
    assert by_topic["resistance_training"].fact_source_count == 5
    assert by_topic["resistance_training"].paper_count == 1


def test_discover_topics_reuses_cached_source_rich_fact_children(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "cached_child_topic": {
            "count": 8,
            "ts": time.time(),
            "version": td._SUPPLY_CACHE_VERSION,
        },
    }), encoding="utf-8")
    seed_papers = [_paper(doi="10.1/seed", title="Seed topic trial", fwci=2.0)]
    child_papers = [_paper(
        doi="10.1/child", title="Cached child topic trial", fwci=1.5)]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            return httpx.Response(200, json=[])
        if "cached_child_topic" in body:
            return httpx.Response(200, json=child_papers)
        return httpx.Response(200, json=seed_papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = td.discover_topics(
            seeds=("seed_topic",), settings=_settings(), client=c,
            current_year=2024, derived_topic_limit=5, fact_probe_topics=5,
        )

    by_topic = {candidate.topic: candidate for candidate in out}
    assert by_topic["cached_child_topic"].fact_source_count == 8
    assert by_topic["cached_child_topic"].paper_count == 1


def test_discover_topics_ignores_cached_source_rich_hint_without_papers(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "cached_orphan_topic": {
            "count": 8,
            "ts": time.time(),
            "version": td._SUPPLY_CACHE_VERSION,
        },
    }), encoding="utf-8")
    seed_papers = [_paper(doi="10.1/seed", title="Seed topic trial", fwci=2.0)]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        if req.url.path.endswith("/tier2/facts/search"):
            return httpx.Response(200, json=[])
        if "cached_orphan_topic" in body:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=seed_papers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = td.discover_topics(
            seeds=("seed_topic",), settings=_settings(), client=c,
            current_year=2024, derived_topic_limit=5, fact_probe_topics=5,
        )

    assert "cached_orphan_topic" not in {candidate.topic for candidate in out}


def test_cached_source_rich_topics_can_use_previous_version_as_hint(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    now = time.time()
    (tmp_path / "supply.json").write_text(json.dumps({
        "legacy_rich": {
            "count": 7, "ts": now, "version": td._SUPPLY_CACHE_VERSION - 1,
        },
        "legacy_thin": {
            "count": 4, "ts": now, "version": td._SUPPLY_CACHE_VERSION - 1,
        },
        "legacy_stale": {
            "count": 9,
            "ts": now - td._SUPPLY_CACHE_TTL_SECONDS - 1,
            "version": td._SUPPLY_CACHE_VERSION - 1,
        },
    }), encoding="utf-8")

    out = td._cached_source_rich_topics(exclude=set(), limit=10)

    assert out == (("legacy_rich", 7),)


def test_supply_cache_hit_skips_reprobe(monkeypatch: Any, tmp_path: Path) -> None:
    """A fresh cached count is reused without re-probing the DB — the load
    reduction that also shrinks the window for transient false-zeros."""
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    calls = {"n": 0}

    def probe(*_a: Any, **_k: Any) -> tuple[int, tuple[tuple[str, int], ...]]:
        calls["n"] += 1
        return 9, ()

    monkeypatch.setattr(td, "_fetch_topic_fact_source_profile", probe)
    first = td._fetch_fact_source_counts(
        ["rapamycin"], client=MagicMock(), settings=_settings())
    second = td._fetch_fact_source_counts(
        ["rapamycin"], client=MagicMock(), settings=_settings())

    assert first == second == {"rapamycin": 9}
    assert calls["n"] == 1  # second call served from fresh cache


def test_low_supply_cache_expires_faster_than_publishable_cache(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    """Underfloor counts are refreshed on the publish cadence, while rich
    counts keep the longer DB-protection TTL."""
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    monkeypatch.setattr(td, "_LOW_SUPPLY_CACHE_TTL_SECONDS", 10.0)
    now = time.time()
    (tmp_path / "supply.json").write_text(json.dumps({
        "thin": {"count": 4, "ts": now - 11, "version": td._SUPPLY_CACHE_VERSION},
        "rich": {"count": 5, "ts": now - 11, "version": td._SUPPLY_CACHE_VERSION},
    }), encoding="utf-8")
    calls: list[str] = []

    def probe(topic: str, *_a: Any, **_k: Any) -> tuple[int, tuple[tuple[str, int], ...]]:
        calls.append(topic)
        return 6, ()

    monkeypatch.setattr(td, "_fetch_topic_fact_source_profile", probe)
    out = td._fetch_fact_source_counts(
        ["thin", "rich"], client=MagicMock(), settings=_settings())

    assert out == {"thin": 6, "rich": 5}
    assert calls == ["thin"]


def test_warm_backlog_refreshes_fresh_underfloor_cache(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "thin": {"count": 0, "ts": time.time(), "version": td._SUPPLY_CACHE_VERSION},
        "rich": {"count": 5, "ts": time.time(), "version": td._SUPPLY_CACHE_VERSION},
    }), encoding="utf-8")
    calls: list[str] = []

    def probe(topic: str, *_a: Any, **_k: Any) -> tuple[int, tuple[tuple[str, int], ...]]:
        calls.append(topic)
        return 6, ()

    monkeypatch.setattr(td, "_fetch_topic_fact_source_profile", probe)
    out = td._fetch_fact_source_counts(
        ["thin", "rich"], client=MagicMock(), settings=_settings(),
        refresh_low_source_counts=True,
    )

    assert out == {"thin": 6, "rich": 5}
    assert calls == ["thin"]


def test_supply_cache_version_mismatch_reprobes(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    (tmp_path / "supply.json").write_text(json.dumps({
        "topic": {"count": 1, "ts": time.time(), "version": 1},
    }), encoding="utf-8")
    monkeypatch.setattr(
        td, "_fetch_topic_fact_source_profile", lambda *_a, **_k: (7, ()))

    out = td._fetch_fact_source_counts(
        ["topic"], client=MagicMock(), settings=_settings())

    assert out == {"topic": 7}


def test_supply_cache_failure_keeps_prior_count(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    """A transient probe failure (-1) must NOT overwrite a known-good cached
    count — the exact false-zero that mis-ranked rich topics down to 0."""
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    monkeypatch.setattr(td, "_SUPPLY_CACHE_TTL_SECONDS", 0.0)  # force re-probe
    counts = iter([16, td._PROBE_INCONCLUSIVE])
    monkeypatch.setattr(
        td, "_fetch_topic_fact_source_profile",
        lambda *_a, **_k: (next(counts), ()))

    first = td._fetch_fact_source_counts(
        ["rapamycin"], client=MagicMock(), settings=_settings())
    second = td._fetch_fact_source_counts(
        ["rapamycin"], client=MagicMock(), settings=_settings())

    assert first == {"rapamycin": 16}
    assert second == {"rapamycin": 16}  # cached count survives the failure


def test_supply_cache_failure_without_prior_is_zero(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    """First-ever probe fails (-1) with no cached history → 0, so a dead DB
    cannot fabricate a phantom count."""
    from agent import topic_discovery as td

    monkeypatch.setattr(td, "_SUPPLY_CACHE_PATH", tmp_path / "supply.json")
    monkeypatch.setattr(
        td, "_fetch_topic_fact_source_profile",
        lambda *_a, **_k: (td._PROBE_INCONCLUSIVE, ()))

    out = td._fetch_fact_source_counts(
        ["rapamycin"], client=MagicMock(), settings=_settings())

    assert out == {"rapamycin": 0}
