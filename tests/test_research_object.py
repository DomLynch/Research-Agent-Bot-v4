"""Sprint 24 — Researka publishing object model tests.

Locks the StudyCard / ClaimCard / EvidenceReceipt schemas and the
bundler's contract against the canonical receipt files. Universal: no
domain literals; the dataclasses are field-typed only.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.research_object import (
    ClaimCard,
    EvidenceReceipt,
    StudyCard,
    bundle_research_object,
)


def _write(p: Path, payload: object) -> None:
    p.write_text(json.dumps(payload), encoding="utf-8")


def _seed_full_paper(tmp_path: Path, *, topic: str = "rapamycin") -> Path:
    pd = tmp_path / f"{topic}-paper-2026-05-13T00-00-00Z"
    pd.mkdir()
    _write(pd / "readiness_report.json", {"level": 6, "label": "meta-analytic-pool"})
    _write(pd / "cite_audit.json", {"clean": True, "unresolved_anchors": []})
    _write(pd / "paper_type_decision.json", {"name": "meta-analysis-standard"})
    _write(pd / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "s01", "action": "approve"},
        {"kind": "sentinel", "sentinel_id": "10.1/x", "action": "uploaded"},
    ]})
    _write(pd / "effect_extractions.json", {
        "topic": topic,
        "receipts": [
            {"study_id": "s01", "status": "extracted", "metric": "lifespan_days",
             "treated_value": 1100, "control_value": 1000,
             "treated_n": 50, "control_n": 50, "percent_change": 10.0,
             "hazard_ratio": None,
             "evidence_quotes": ["Treated mice lived 1100 days vs 1000 days."],
             "reviewer": "mimo-dual-pass-agreed:m"},
            {"study_id": "s02", "status": "no_numerics", "metric": "",
             "treated_value": None, "control_value": None,
             "treated_n": None, "control_n": None, "percent_change": None,
             "hazard_ratio": None, "evidence_quotes": [],
             "reviewer": "mimo-only-primary"},
        ],
    })
    # Canonical pool shape — pooled claim lives in pooled_a_core_summary
    # (matches compile_pool / regen_section3 writer), NOT in `outcomes`
    # which carries per-study records.
    _write(pd / "effect_pool.json", {
        "pooled_a_core_summary": {
            "k": 3, "metric": "lifespan_days",
            "estimate": 8.5, "se": 1.8,
            "ci_low": 4.1, "ci_high": 12.9, "i_squared": 22.0,
        },
        "effects": [{"study_id": f"s{i:02d}"} for i in range(3)],
    })
    return pd


def test_bundle_returns_typed_evidence_receipt(tmp_path: Path) -> None:
    pd = _seed_full_paper(tmp_path)
    er = bundle_research_object(pd)
    assert isinstance(er, EvidenceReceipt)
    assert er.topic == "rapamycin"
    assert er.paper_dir_name == pd.name
    assert er.readiness_level == 6
    assert er.readiness_label == "meta-analytic-pool"
    assert er.cite_audit_clean is True
    assert er.paper_type == "meta-analysis-standard"
    assert er.manual_audits_count == 2


def test_study_cards_carry_extraction_fields(tmp_path: Path) -> None:
    pd = _seed_full_paper(tmp_path)
    er = bundle_research_object(pd)
    assert len(er.studies) == 2
    s = next(s for s in er.studies if s.study_id == "s01")
    assert isinstance(s, StudyCard)
    assert s.metric == "lifespan_days"
    assert s.treated_value == 1100.0
    assert s.percent_change == 10.0
    assert s.treated_n == 50
    assert s.evidence_quotes == (
        "Treated mice lived 1100 days vs 1000 days.",
    )
    assert s.extraction_status == "extracted"


def test_claim_cards_carry_pooled_fields(tmp_path: Path) -> None:
    pd = _seed_full_paper(tmp_path)
    er = bundle_research_object(pd)
    assert len(er.claims) == 1
    c = er.claims[0]
    assert isinstance(c, ClaimCard)
    assert c.metric == "lifespan_days"
    assert c.k_effects == 3
    assert c.pooled_effect == 8.5
    assert c.pooled_ci_low == 4.1
    assert c.pooled_ci_high == 12.9
    assert c.i_squared == 22.0


def test_claim_cards_read_pooled_summary_not_outcomes_list(tmp_path: Path) -> None:
    """GPT-auditor bug 2026-05-13: the bundler used to read
    pool['outcomes'] expecting pooled-effect objects, but `outcomes`
    holds per-study records. The pooled claim canonically lives in
    `pooled_a_core_summary`. This test locks the fix.
    """
    pd = tmp_path / "lock-shape"
    pd.mkdir()
    _write(pd / "effect_pool.json", {
        # Per-study records — should NOT be misread as claims.
        "outcomes": [
            {"study_id": "s01", "metric_name": "log_ratio",
             "treated_value": 900.0, "control_value": 820.0},
        ],
        # The actual pooled claim.
        "pooled_a_core_summary": {
            "k": 2, "metric": "log_median_ratio",
            "estimate": 0.104, "se": 0.077,
            "ci_low": -0.047, "ci_high": 0.255,
        },
    })
    er = bundle_research_object(pd)
    # Exactly one claim — the pooled summary, not 1-per-outcome.
    assert len(er.claims) == 1
    c = er.claims[0]
    assert c.k_effects == 2
    assert c.metric == "log_median_ratio"
    assert c.pooled_effect == 0.104
    assert c.pooled_ci_low == -0.047
    assert c.pooled_ci_high == 0.255


def test_claim_cards_emit_two_when_sensitivity_summary_present(tmp_path: Path) -> None:
    """When the pool carries both a primary and a sensitivity summary,
    both surface as separate ClaimCards in first-defined order."""
    pd = tmp_path / "two-summaries"
    pd.mkdir()
    _write(pd / "effect_pool.json", {
        "pooled_a_core_summary": {"k": 2, "metric": "m", "estimate": 0.1,
                                   "ci_low": 0.0, "ci_high": 0.2},
        "pooled_sensitivity_summary": {"k": 3, "metric": "m", "estimate": 0.08,
                                        "ci_low": -0.01, "ci_high": 0.17},
    })
    cards = bundle_research_object(pd).claims
    assert len(cards) == 2
    assert cards[0].k_effects == 2 and cards[0].pooled_effect == 0.1
    assert cards[1].k_effects == 3 and cards[1].pooled_effect == 0.08


def test_bundle_tolerates_missing_receipts(tmp_path: Path) -> None:
    """Empty paper folder → bundler returns a defaulted EvidenceReceipt
    without raising. cite_audit_clean uses None (unknown) when the file
    is absent — honest tri-state, never False (which would falsely
    signal citation defects on a paper that simply hasn't been audited
    yet)."""
    pd = tmp_path / "empty-paper"
    pd.mkdir()
    er = bundle_research_object(pd, topic="x")
    assert er.topic == "x"
    assert er.readiness_level == 0
    assert er.readiness_label == ""
    assert er.cite_audit_clean is None  # absent file -> unknown, not False
    assert er.paper_type == ""
    assert er.manual_audits_count == 0
    assert er.studies == ()
    assert er.claims == ()


def test_bundle_cite_audit_tri_state_present_clean_dirty_absent(tmp_path: Path) -> None:
    """Locks the tri-state contract:
      - cite_audit.json absent          -> cite_audit_clean is None
      - cite_audit.json clean=True      -> cite_audit_clean is True
      - cite_audit.json clean=False     -> cite_audit_clean is False
    """
    pd_absent = tmp_path / "absent"
    pd_absent.mkdir()
    assert bundle_research_object(pd_absent).cite_audit_clean is None

    pd_clean = tmp_path / "clean"
    pd_clean.mkdir()
    _write(pd_clean / "cite_audit.json", {"clean": True})
    assert bundle_research_object(pd_clean).cite_audit_clean is True

    pd_dirty = tmp_path / "dirty"
    pd_dirty.mkdir()
    _write(pd_dirty / "cite_audit.json", {"clean": False,
                                          "unresolved_anchors": ["x"]})
    assert bundle_research_object(pd_dirty).cite_audit_clean is False


def test_bundle_tolerates_malformed_json(tmp_path: Path) -> None:
    pd = tmp_path / "bad-paper"
    pd.mkdir()
    (pd / "readiness_report.json").write_text("oops", encoding="utf-8")
    (pd / "effect_pool.json").write_text("also oops", encoding="utf-8")
    er = bundle_research_object(pd)
    assert er.readiness_level == 0
    assert er.claims == ()


def test_as_dict_round_trips_through_json(tmp_path: Path) -> None:
    pd = _seed_full_paper(tmp_path)
    d = bundle_research_object(pd).as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["readiness_level"] == 6
    studies = d["studies"]
    claims = d["claims"]
    assert isinstance(studies, list) and len(studies) == 2
    assert isinstance(claims, list) and len(claims) == 1


def test_evidence_receipt_is_immutable(tmp_path: Path) -> None:
    pd = _seed_full_paper(tmp_path)
    er = bundle_research_object(pd)
    try:
        er.topic = "x"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("EvidenceReceipt should be immutable")


def test_topic_arg_overrides_extractions_topic_field(tmp_path: Path) -> None:
    """Explicit topic argument takes precedence over whatever the
    extractions receipt declares (operator override semantics)."""
    pd = _seed_full_paper(tmp_path)
    er = bundle_research_object(pd, topic="carbon_tax")
    assert er.topic == "carbon_tax"


def test_bundle_universal_for_non_biomedical_paper(tmp_path: Path) -> None:
    """Bundler reads field shapes, not topic-specific values — climate
    data round-trips identically."""
    pd = _seed_full_paper(tmp_path, topic="carbon_tax")
    er = bundle_research_object(pd)
    assert er.topic == "carbon_tax"
    assert isinstance(er, EvidenceReceipt)


def test_safe_numeric_parsers_handle_garbage_values(tmp_path: Path) -> None:
    """When upstream receipts contain non-numeric junk in numeric
    fields (within the JSON-serialisable subset that real receipts can
    actually contain), bundle_research_object emits None rather than
    raising."""
    pd = tmp_path / "junky"
    pd.mkdir()
    _write(pd / "effect_extractions.json", {"receipts": [{
        "study_id": "s01", "status": "extracted", "metric": "x",
        "treated_value": "oops",         # non-numeric string
        "control_value": [1, 2],          # list where number expected
        "treated_n": {"a": 1},            # dict where int expected
        "control_n": "five",              # non-numeric string
        "percent_change": "lots",         # non-numeric string
        "hazard_ratio": True,             # boolean -> int() = 1 by accident-tolerant
        "evidence_quotes": [], "reviewer": "x",
    }]})
    er = bundle_research_object(pd)
    s = er.studies[0]
    assert s.treated_value is None
    assert s.control_value is None
    assert s.treated_n is None
    assert s.control_n is None
    assert s.percent_change is None
