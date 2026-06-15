"""Unit tests for the deterministic novelty gate (P9, pure functions)."""
from __future__ import annotations

from agent.novelty_gate import (
    CITATION_HALLUCINATED,
    INSUFFICIENT_NOVELTY,
    NoveltyConfig,
    NoveltyReport,
    compute_novelty,
    novelty_blockers,
)

CFG = NoveltyConfig()


def _compute(**kw: object) -> NoveltyReport:
    base: dict[str, object] = dict(
        corpus_prior_art_count=0,
        lead_shape=frozenset({"rapamycin", "lifespan", "increase"}),
        other_shapes=(),
        newest_source_year=2026,
        now_year=2026,
        citation_hallucinated=False,
        cfg=CFG,
    )
    base.update(kw)
    return compute_novelty(**base)  # type: ignore[arg-type]


# ---------- scarcity (corpus prior-art frequency) ----------

def test_zero_prior_art_is_maximally_novel() -> None:
    r = _compute(corpus_prior_art_count=0)
    assert r.scarcity == 1.0


def test_saturated_prior_art_is_not_novel() -> None:
    r = _compute(corpus_prior_art_count=CFG.saturation_count)
    assert r.scarcity == 0.0


def test_unavailable_count_is_neutral_not_blocking() -> None:
    # corpus outage -> None -> neutral 0.5, never a false novelty failure.
    r = _compute(corpus_prior_art_count=None)
    assert r.scarcity == 0.5
    assert INSUFFICIENT_NOVELTY not in r.blockers  # fresh+distinct keep it above floor


# ---------- distinctiveness (vs the run's other facts) ----------

def test_lead_with_no_peers_is_fully_distinct() -> None:
    assert _compute(other_shapes=()).distinctiveness == 1.0


def test_lead_identical_to_crowd_is_not_distinct() -> None:
    shape = frozenset({"metformin", "glucose", "reduce"})
    r = _compute(lead_shape=shape, other_shapes=(shape, shape, shape))
    assert r.distinctiveness == 0.0


def test_partial_overlap_is_mid_distinct() -> None:
    lead = frozenset({"a", "b", "c", "d"})
    other = frozenset({"a", "b"})  # jaccard = 2/4 = 0.5 -> distinct = 0.5
    assert _compute(lead_shape=lead, other_shapes=(other,)).distinctiveness == 0.5


# ---------- recency ----------

def test_recent_source_is_fresh() -> None:
    assert _compute(newest_source_year=2025, now_year=2026).recency == 1.0


def test_old_source_has_zero_recency() -> None:
    assert _compute(newest_source_year=2010, now_year=2026).recency == 0.0


def test_missing_year_is_neutral() -> None:
    assert _compute(newest_source_year=None, now_year=2026).recency == 0.5


# ---------- composite score + blockers ----------

def test_fully_novel_claim_scores_high_and_clears() -> None:
    r = _compute(corpus_prior_art_count=0, other_shapes=(), newest_source_year=2026)
    assert r.score == 100
    assert r.blockers == ()


def test_saturated_crowded_stale_claim_is_blocked() -> None:
    shape = frozenset({"x", "y", "z"})
    r = _compute(
        corpus_prior_art_count=CFG.saturation_count,
        lead_shape=shape,
        other_shapes=(shape, shape),
        newest_source_year=2005,
        now_year=2026,
    )
    assert r.score == 0
    assert INSUFFICIENT_NOVELTY in r.blockers


def test_hallucinated_citation_always_blocks_even_if_novel() -> None:
    r = _compute(corpus_prior_art_count=0, citation_hallucinated=True)
    assert r.score == 100  # novel...
    assert CITATION_HALLUCINATED in r.blockers  # ...but cited source does not exist


def test_score_is_weighted_blend() -> None:
    # scarcity=1, distinct=1, recency=0 -> (0.5+0.3+0)/1.0 = 0.8 -> 80
    r = _compute(corpus_prior_art_count=0, other_shapes=(), newest_source_year=2005)
    assert r.score == 80


# ---------- novelty_blockers (offline re-derivation from sidecar) ----------

def test_novelty_blockers_from_report_dict() -> None:
    report = {"score": 10, "citation_hallucinated": False}
    assert novelty_blockers(report, CFG) == [INSUFFICIENT_NOVELTY]


def test_novelty_blockers_re_applies_current_threshold() -> None:
    report = {"score": 50, "citation_hallucinated": False}
    strict = NoveltyConfig(min_score=60)
    assert novelty_blockers(report, strict) == [INSUFFICIENT_NOVELTY]
    assert novelty_blockers(report, NoveltyConfig(min_score=40)) == []


def test_novelty_blockers_garbled_report_is_safe() -> None:
    assert novelty_blockers("not a dict", CFG) == []  # type: ignore[arg-type]
    assert novelty_blockers({}, CFG) == []  # missing score -> defaults to min, no block


def test_novelty_blockers_hallucination_from_report() -> None:
    report = {"score": 95, "citation_hallucinated": True}
    assert novelty_blockers(report, CFG) == [CITATION_HALLUCINATED]
