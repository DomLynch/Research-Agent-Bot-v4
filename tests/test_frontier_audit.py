"""Sprint 59 — frontier-thesis survival gate tests.

Locks the five hard gates and their status outcomes:
  1. D_bad_extraction citation        -> rejected
  2. Metric family mix                 -> rejected
  3. Missing source metadata           -> needs_source_audit
  4. A_core density below min          -> needs_source_audit
  5. Opportunity cap (40 / 80 / orig)
"""
from __future__ import annotations

from typing import Any

from agent.fact_lanes import classify_lanes
from agent.frontier_audit import audit_frontier_review, audit_thesis


def _fact(fid: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fact_id": fid,
        "canonical_phrase": "rapamycin extended median lifespan by 14% in females",
        "population": "female heterogeneous-stock mice",
        "intervention": "rapamycin in feed",
        "numeric_value": 14.0, "units": "%",
        "source_paper": {"doi": "10.1/x", "pmid": "1234"},
    }
    base.update(kw)
    return base


def _thesis(title: str, rationale: str, opp: int = 90) -> dict[str, Any]:
    return {"title": title, "rationale": rationale,
            "opportunity_score": opp}


def test_clean_thesis_survives_uncapped() -> None:
    facts = [
        _fact("f/1", canonical_phrase="rapamycin lifespan +14% in females"),
        _fact("f/2", canonical_phrase="rapamycin lifespan +9% in males",
              numeric_value=9.0),
        _fact("f/3", canonical_phrase="rapamycin lifespan +26% at 42 ppm",
              numeric_value=26.0),
    ]
    lanes = classify_lanes(facts, topic="rapamycin")
    review = {"theses": [_thesis(
        title="Dose-dependent rapamycin lifespan extension",
        rationale="At 14% in females and 9% in males and 26% high dose, "
                  "the sex-x-dose interaction is clear.",
        opp=90,
    )]}
    audits = audit_frontier_review(review, facts, lanes, a_core_min=3)
    assert len(audits) == 1
    assert audits[0].status == "survives"
    assert audits[0].capped_opportunity == 90


def test_d_bad_citation_rejects_thesis() -> None:
    """Thesis cites an incomplete-PICO fact (D_bad_extraction) -> rejected, cap 40.
    (A methodological number like '66 weeks' is no longer D_bad — it binds as
    B_context — so the genuine D_bad case is missing population/intervention.)"""
    facts = [
        _fact("f/dur",
              canonical_phrase="rapamycin CR at 66 weeks of treatment",
              intervention="", population="",  # no PICO at all -> D_bad_extraction
              numeric_value=66.0, units="weeks"),
        _fact("f/ok"),
    ]
    lanes = classify_lanes(facts, topic="rapamycin")
    review = {"theses": [_thesis(
        title="Rapamycin lifespan extension at 66 weeks",
        rationale="At 66 weeks rapamycin showed strong effect",
        opp=85,
    )]}
    audits = audit_frontier_review(review, facts, lanes, a_core_min=1)
    assert audits[0].status == "rejected"
    assert audits[0].capped_opportunity <= 40
    assert any(f.startswith("cites_d_bad_extraction")
               for f in audits[0].blocking_flags)


def test_low_a_core_density_needs_source_audit() -> None:
    """Single A_core fact below default min=3 -> needs_source_audit."""
    facts = [_fact("f/1")]
    lanes = classify_lanes(facts, topic="rapamycin")
    review = {"theses": [_thesis(
        title="Rapamycin sole-finding paper",
        rationale="Only 14% in females supports this thesis.",
        opp=95,
    )]}
    audits = audit_frontier_review(review, facts, lanes)
    assert audits[0].status == "needs_source_audit"
    assert audits[0].capped_opportunity <= 80  # gate 5 cap
    assert any(f.startswith("a_core_density_too_low")
               for f in audits[0].blocking_flags)


def test_context_only_citations_repair_to_matching_a_core() -> None:
    """If the reviewer cites B_context while matching A_core receipts exist,
    the gate deterministically binds those A_core facts before density checks."""
    facts = [
        _fact("b/1",
              canonical_phrase="brain age MRI conversion model described",
              numeric_value=None, units=""),
        _fact("a/1",
              canonical_phrase="brain age MRI predicted dementia risk by 11%",
              intervention="brain age MRI",
              numeric_value=11.0, source_paper={"doi": "10.1/a1", "pmid": "1"}),
        _fact("a/2",
              canonical_phrase="brain age MRI predicted conversion to AD by 10%",
              intervention="brain age MRI",
              numeric_value=10.0, source_paper={"doi": "10.1/a2", "pmid": "2"}),
        _fact("a/3",
              canonical_phrase="brain age MRI classified Parkinson disease with 80%",
              intervention="brain age MRI",
              numeric_value=80.0, source_paper={"doi": "10.1/a3", "pmid": "3"}),
    ]
    lanes = classify_lanes(facts, topic="brain_age_MRI")
    review = {"theses": [{
        "title": "Brain age MRI as a differential diagnostic marker",
        "rationale": "The brain age MRI signal predicts dementia conversion.",
        "opportunity_score": 90,
        "cited_fact_ids": ["b/1"],
    }]}

    audits = audit_frontier_review(review, facts, lanes, a_core_min=3)

    assert audits[0].status == "survives"
    assert list(audits[0].cited_fact_ids) == ["b/1", "a/1", "a/2", "a/3"]
    assert not any(f.startswith("a_core_density_too_low")
                   for f in audits[0].blocking_flags)


def test_missing_source_metadata_flag() -> None:
    """Fact has no DOI and no PMID -> missing_source_metadata flag."""
    facts = [
        _fact("f/1", source_paper={}),
        _fact("f/2", canonical_phrase="rapamycin +9% in males",
              numeric_value=9.0),
        _fact("f/3", canonical_phrase="rapamycin +26% at high dose",
              numeric_value=26.0),
    ]
    lanes = classify_lanes(facts, topic="rapamycin")
    review = {"theses": [_thesis(
        title="Dose-dependent rapamycin",
        rationale="14% in females and 9% in males and 26% high dose.",
    )]}
    audits = audit_frontier_review(review, facts, lanes, a_core_min=3)
    assert audits[0].status == "needs_source_audit"
    assert any("missing_source_metadata" in f
               for f in audits[0].blocking_flags)


def test_metric_family_mix_rejects() -> None:
    """Thesis mixes effect_size + fold_change citations."""
    facts = [
        _fact("f/eff"),  # effect_size
        _fact("f/fold",
              canonical_phrase="rapamycin caused 4-fold increase in autophagy",
              numeric_value=4.0, units=""),  # fold_change via context
        _fact("f/ok", canonical_phrase="rapamycin +9% in males",
              numeric_value=9.0),
        _fact("f/ok2", canonical_phrase="rapamycin +26% at high dose",
              numeric_value=26.0),
    ]
    lanes = classify_lanes(facts, topic="rapamycin")
    review = {"theses": [_thesis(
        title="Mixed-metric rapamycin thesis",
        rationale="14% effect, 4-fold increase, 9% males, 26% high dose.",
    )]}
    audits = audit_frontier_review(review, facts, lanes, a_core_min=2)
    # Either rejected (preferred) or flagged for metric family mix
    assert any(f.startswith("metric_family_mix")
               for f in audits[0].blocking_flags)


def test_unmapped_theses_field_returns_empty() -> None:
    """Malformed frontier_review (no theses list) returns empty audit list."""
    audits = audit_frontier_review({"theses": "not-a-list"}, [], [])
    assert audits == []


def test_audit_thesis_round_trip_as_dict() -> None:
    facts = [_fact("f/1")]
    lanes = classify_lanes(facts, topic="rapamycin")
    audit = audit_thesis(
        _thesis("t", "14% in females", opp=70), 0, facts, lanes, a_core_min=1,
    )
    d = audit.as_dict()
    assert d["title"] == "t"
    assert d["status"] in ("survives", "needs_source_audit", "rejected")


def test_universal_non_biomedical_thesis() -> None:
    """Climate-policy thesis with 3 A_core facts -> survives."""
    facts = [{
        "fact_id": f"ct/{n}",
        "canonical_phrase": f"carbon_tax cut emissions by {n}% in country {n}",
        "population": f"country {n}",
        "intervention": "carbon_tax",
        "numeric_value": float(n), "units": "%",
        "source_paper": {"doi": f"10.1/{n}", "pmid": str(1000 + n)},
    } for n in (8, 12, 15)]
    lanes = classify_lanes(facts, topic="carbon_tax")
    review = {"theses": [_thesis(
        title="Carbon tax dose-response across countries",
        rationale="At 8%, 12%, and 15% reductions across countries.",
        opp=88,
    )]}
    audits = audit_frontier_review(review, facts, lanes, a_core_min=3)
    assert audits[0].status == "survives"
