"""Sprint 39-40 — Evidence Index + delta tests.

Locks the confidence-scoring formula and the delta classification
across snapshots. Universal: all fixtures synthesize paper folders
with generic study IDs; no biomedical literals.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.evidence_delta import compute_delta, deltas_as_dict
from agent.evidence_index import (
    ClaimAtom,
    EvidenceIndex,
    compute_evidence_index,
)


def _seed_paper(
    tmp_path: Path, topic: str, *,
    level: int, k_pool: int, paper_type: str,
    cite_clean: bool | None = True,
    pool_effects: list[dict[str, object]] | None = None,
    pool_skipped: list[str] | None = None,
    dual_agent_entries: list[dict[str, object]] | None = None,
) -> Path:
    pd = tmp_path / f"{topic}-paper-2026-05-14T00-00-00Z"
    pd.mkdir()
    pd.joinpath("readiness_report.json").write_text(
        json.dumps({"level": level, "label": "x"}), encoding="utf-8",
    )
    pd.joinpath("effect_pool.json").write_text(
        json.dumps({
            "k_effects": k_pool,
            "effects": pool_effects or [],
            "skipped_study_ids": pool_skipped or [],
        }), encoding="utf-8",
    )
    pd.joinpath("paper_type_decision.json").write_text(
        json.dumps({"name": paper_type}), encoding="utf-8",
    )
    if cite_clean is not None:
        pd.joinpath("cite_audit.json").write_text(
            json.dumps({"clean": cite_clean}), encoding="utf-8",
        )
    pd.joinpath("dual_agent_extraction_audit.json").write_text(
        json.dumps({"entries": dual_agent_entries or []}), encoding="utf-8",
    )
    return pd


# ----------------- compute_evidence_index ----------------------------


def test_index_scores_full_meta_analysis_high(tmp_path: Path) -> None:
    pd = _seed_paper(
        tmp_path, "rapamycin",
        level=6, k_pool=10, paper_type="meta-analysis-full",
        pool_effects=[{"study_id": f"s{i:02d}"} for i in range(10)],
        dual_agent_entries=[
            {"study_id": f"s{i:02d}", "confidence_score": 1.0} for i in range(10)
        ],
    )
    idx = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t1")
    c = idx.claims[0]
    # k=10 caps at full credit; readiness L6 full credit; cite clean +
    # dual-agent 1.0 → near max.
    assert c.confidence_0_100 >= 95
    assert c.readiness_level == 6
    assert c.k_pool == 10
    assert c.paper_type == "meta-analysis-full"
    assert len(c.supporting_study_ids) == 10


def test_index_scores_scoping_review_low(tmp_path: Path) -> None:
    pd = _seed_paper(
        tmp_path, "carbon_tax",
        level=3, k_pool=0, paper_type="scoping-review",
        cite_clean=True,
        pool_skipped=["s01", "s02"],
    )
    idx = compute_evidence_index(pd, topic="carbon_tax", snapshot_utc="t1")
    c = idx.claims[0]
    # No pool, mid readiness, clean cite, no agent confidence → low
    # but non-zero (cite + readiness contribute).
    assert c.confidence_0_100 < 50
    assert c.k_pool == 0
    assert c.contradicting_study_ids == ("s01", "s02")
    assert c.paper_type == "scoping-review"


def test_index_handles_missing_receipts_without_raising(tmp_path: Path) -> None:
    """An empty paper folder produces a defaulted ClaimAtom (score=0,
    cite_audit_clean=None for unknown)."""
    pd = tmp_path / "rapamycin-paper-X"
    pd.mkdir()
    idx = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t1")
    c = idx.claims[0]
    assert c.confidence_0_100 == 0
    assert c.readiness_level == 0
    assert c.cite_audit_clean is None  # absent file → unknown, not False


def test_index_universal_for_non_biomedical_topic(tmp_path: Path) -> None:
    """Climate-vocab topic produces a structurally identical index —
    no biomedical literals in the scoring or claim-text generation."""
    pd = _seed_paper(
        tmp_path, "carbon_tax",
        level=5, k_pool=3, paper_type="pilot-meta-analysis",
        pool_effects=[
            {"study_id": "city-stockholm-2022"},
            {"study_id": "country-norway-2019"},
            {"study_id": "subnational-uk-2021"},
        ],
        dual_agent_entries=[
            {"study_id": "city-stockholm-2022", "confidence_score": 1.0},
            {"study_id": "country-norway-2019", "confidence_score": 0.7},
            {"study_id": "subnational-uk-2021", "confidence_score": 0.5},
        ],
    )
    idx = compute_evidence_index(pd, topic="carbon_tax", snapshot_utc="t1")
    c = idx.claims[0]
    assert c.confidence_0_100 >= 70
    assert "city-stockholm-2022" in c.supporting_study_ids


def test_index_as_dict_round_trips_through_json(tmp_path: Path) -> None:
    pd = _seed_paper(tmp_path, "rapamycin", level=4, k_pool=0,
                      paper_type="scoping-review")
    idx = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t1")
    d = idx.as_dict()
    assert json.loads(json.dumps(d)) == d


# ----------------- compute_delta -------------------------------------


def _claim(text: str, *, conf: int = 50, supp: tuple[str, ...] = (),
            contra: tuple[str, ...] = ()) -> ClaimAtom:
    """Sprint 42/43: ClaimAtom now also carries score_breakdown +
    publication_opportunity. Tests default to a benign breakdown that
    sums to `conf` and a derived pub-opportunity flag."""
    return ClaimAtom(
        topic="t", claim_text=text, confidence_0_100=conf,
        score_breakdown=(("k_pool", 0), ("readiness_level", conf),
                          ("cite_audit_clean", 0), ("mean_agent_confidence", 0)),
        publication_opportunity=(conf >= 70 and len(supp) >= 2),
        paper_type="x", readiness_level=4, k_pool=0,
        supporting_study_ids=supp, contradicting_study_ids=contra,
        cite_audit_clean=True, mean_agent_confidence=0.0,
    )


def _idx(text: str, **kw: object) -> EvidenceIndex:
    return EvidenceIndex(
        topic="t", snapshot_utc="t", paper_dir_name="p",
        claims=(_claim(text, **kw),),  # type: ignore[arg-type]
    )


def test_delta_classifies_new_claim_when_no_prior() -> None:
    deltas = compute_delta(_idx("rapamycin → lifespan"), None)
    assert len(deltas) == 1
    assert deltas[0].direction == "new"
    assert deltas[0].previous_confidence is None


def test_delta_classifies_unchanged_when_same_score() -> None:
    cur = _idx("rapamycin → lifespan", conf=70)
    prev = _idx("rapamycin → lifespan", conf=70)
    d = compute_delta(cur, prev)[0]
    assert d.direction == "unchanged"
    assert d.delta_points == 0


def test_delta_classifies_strengthened_when_score_up() -> None:
    cur = _idx("rapamycin → lifespan", conf=80)
    prev = _idx("rapamycin → lifespan", conf=60)
    d = compute_delta(cur, prev)[0]
    assert d.direction == "strengthened"
    assert d.delta_points == 20


def test_delta_classifies_weakened_when_score_down() -> None:
    cur = _idx("rapamycin → lifespan", conf=38)
    prev = _idx("rapamycin → lifespan", conf=70)
    d = compute_delta(cur, prev)[0]
    assert d.direction == "weakened"
    assert d.delta_points == -32  # the live rapamycin May-12 → May-13 regression


def test_delta_classifies_lost_when_claim_vanishes() -> None:
    cur = _idx("only-this-claim", conf=50)
    prev_idx = EvidenceIndex(
        topic="t", snapshot_utc="t", paper_dir_name="p",
        claims=(_claim("only-this-claim", conf=50), _claim("phantom", conf=40)),
    )
    deltas = compute_delta(cur, prev_idx)
    directions = {d.direction for d in deltas}
    assert "lost" in directions
    lost = next(d for d in deltas if d.direction == "lost")
    assert lost.claim_text == "phantom"
    assert lost.current_confidence is None
    assert lost.previous_confidence == 40


def test_delta_surfaces_new_supporting_studies() -> None:
    cur = _idx("claim", conf=70, supp=("s01", "s02", "s03"))
    prev = _idx("claim", conf=50, supp=("s01",))
    d = compute_delta(cur, prev)[0]
    assert d.direction == "strengthened"
    assert set(d.new_supporting_studies) == {"s02", "s03"}


def test_deltas_as_dict_round_trips_through_json() -> None:
    cur = _idx("claim", conf=50)
    deltas = compute_delta(cur, None)
    payload = deltas_as_dict(cur, deltas)
    assert json.loads(json.dumps(payload)) == payload
    assert payload["topic"] == "t"
    assert len(payload["movers"]) == 1  # type: ignore[arg-type]


@pytest.mark.parametrize("level,k,expected_at_least", [
    (1, 0, 0),     # scaffold floor
    (3, 0, 10),    # scoping, no pool, but mid readiness contributes
    (5, 2, 50),    # pilot pool — solid floor
    (6, 10, 95),   # full meta — near max
])
def test_index_confidence_scales_with_level_and_k(
    tmp_path: Path, level: int, k: int, expected_at_least: int,
) -> None:
    """Lock the scoring monotonicity: stronger evidence ⇒ higher score."""
    pd = _seed_paper(
        tmp_path, "rapamycin",
        level=level, k_pool=k, paper_type="x",
        cite_clean=True,
        pool_effects=[{"study_id": f"s{i:02d}"} for i in range(k)],
        dual_agent_entries=[
            {"study_id": f"s{i:02d}", "confidence_score": 1.0} for i in range(k)
        ],
    )
    idx = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t")
    assert idx.claims[0].confidence_0_100 >= expected_at_least


# ----------------- Sprints 42-43: transparency + pub-opportunity -----


def test_score_breakdown_sums_to_total(tmp_path: Path) -> None:
    """GPT-auditor pushback: the 0..100 score must be reproducible from
    its components. Test asserts the 4 component points sum to the
    final confidence_0_100 — so any reviewer can audit the math."""
    pd = _seed_paper(
        tmp_path, "rapamycin",
        level=5, k_pool=2, paper_type="pilot-meta-analysis",
        cite_clean=True,
        pool_effects=[{"study_id": "s01"}, {"study_id": "s02"}],
        dual_agent_entries=[
            {"study_id": "s01", "confidence_score": 1.0},
            {"study_id": "s02", "confidence_score": 0.7},
        ],
    )
    c = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t").claims[0]
    breakdown = dict(c.score_breakdown)
    assert set(breakdown) == {
        "k_pool", "readiness_level", "cite_audit_clean", "mean_agent_confidence",
    }
    assert sum(breakdown.values()) == c.confidence_0_100


def test_score_breakdown_present_in_json_round_trip(tmp_path: Path) -> None:
    pd = _seed_paper(tmp_path, "rapamycin", level=4, k_pool=0,
                      paper_type="scoping-review")
    d = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t").as_dict()
    claim_dict = d["claims"][0]  # type: ignore[index]
    assert isinstance(claim_dict, dict)
    assert "score_breakdown" in claim_dict
    assert isinstance(claim_dict["score_breakdown"], dict)
    assert sum(claim_dict["score_breakdown"].values()) == claim_dict["confidence_0_100"]


def test_publication_opportunity_fires_when_confidence_and_k_qualify(
    tmp_path: Path,
) -> None:
    """confidence >= 70 AND k_pool >= 2 → publication_opportunity=True."""
    pd = _seed_paper(
        tmp_path, "rapamycin",
        level=6, k_pool=10, paper_type="meta-analysis-full",
        pool_effects=[{"study_id": f"s{i:02d}"} for i in range(10)],
        dual_agent_entries=[
            {"study_id": f"s{i:02d}", "confidence_score": 1.0} for i in range(10)
        ],
    )
    c = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t").claims[0]
    assert c.publication_opportunity is True
    assert c.confidence_0_100 >= 70 and c.k_pool >= 2


def test_publication_opportunity_does_not_fire_for_scoping(
    tmp_path: Path,
) -> None:
    """L4 scoping with k=0 — even with clean cite, the gate is below 70
    or k<2, so the flag stays False."""
    pd = _seed_paper(
        tmp_path, "rapamycin",
        level=4, k_pool=0, paper_type="scoping-review",
        cite_clean=True,
    )
    c = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t").claims[0]
    assert c.publication_opportunity is False


def test_publication_opportunity_blocked_when_k_below_two(tmp_path: Path) -> None:
    """Even at high confidence, k_pool < 2 keeps the flag False —
    journal-grade gate refuses to fire on single-study evidence."""
    pd = _seed_paper(
        tmp_path, "rapamycin",
        level=5, k_pool=1, paper_type="pilot-meta-analysis",
        pool_effects=[{"study_id": "s01"}],
        dual_agent_entries=[{"study_id": "s01", "confidence_score": 1.0}],
    )
    c = compute_evidence_index(pd, topic="rapamycin", snapshot_utc="t").claims[0]
    assert c.k_pool == 1
    assert c.publication_opportunity is False
