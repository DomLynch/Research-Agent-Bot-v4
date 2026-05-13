"""Sprint 16 — readiness classifier tests (L1..L6).

Each level is locked by a minimal receipt fixture so the contract is
explicit:

  L1 — no receipts at all
  L2 — summary present, k_eligible = 0
  L3 — k_eligible > 0, A-core empty
  L4 — A-core > 0, pool.effects empty
  L5 — pool.effects 1..2 (pilot)
  L6 — pool.effects >= 3 (meta-analytic)

Universal: every fixture uses generic field counts, no domain literals.
"""
from __future__ import annotations

from agent.readiness import ReadinessReport, classify_readiness


def test_l1_returns_scaffold_when_no_receipts_present() -> None:
    r = classify_readiness(summary=None, strict=None, extractions=None, pool=None)
    assert r.level == 1
    assert r.label == "scaffold"
    assert any("pipeline has not run" in s for s in r.reasons)
    assert r.counts["k_eligible"] == 0


def test_l2_returns_no_eligible_studies_when_keligible_zero() -> None:
    r = classify_readiness(
        summary={"k_eligible": 0}, strict={}, extractions={}, pool={},
    )
    assert r.level == 2
    assert r.label == "no-eligible-studies"
    assert r.counts["k_eligible"] == 0


def test_l3_returns_no_primary_set_when_a_core_empty() -> None:
    r = classify_readiness(
        summary={"k_eligible": 5},
        strict={"A_core_direct_lifespan": [], "B_disease_model_survival": []},
        extractions={}, pool={},
    )
    assert r.level == 3
    assert r.label == "no-primary-set"
    assert r.counts["k_eligible"] == 5
    assert r.counts["k_a_core"] == 0


def test_l4_returns_no_pooled_effects_when_pool_empty() -> None:
    r = classify_readiness(
        summary={"k_eligible": 5},
        strict={"A_core_direct_lifespan": [{"study_id": "s01"},
                                            {"study_id": "s02"}]},
        extractions={"extractions": [{"study_id": "s01"}]},
        pool={"effects": []},
    )
    assert r.level == 4
    assert r.label == "no-pooled-effects"
    assert r.counts["k_a_core"] == 2
    assert r.counts["k_pool"] == 0


def test_l5_returns_pilot_pool_when_pool_has_one_or_two_effects() -> None:
    for k in (1, 2):
        r = classify_readiness(
            summary={"k_eligible": 5},
            strict={"A_core_direct_lifespan": [{"study_id": f"s{i:02d}"}
                                                for i in range(k)]},
            extractions={"extractions": []},
            pool={"effects": [{"study_id": f"s{i:02d}"} for i in range(k)]},
        )
        assert r.level == 5, f"k={k} should be pilot-pool"
        assert r.label == "pilot-pool"
        assert r.counts["k_pool"] == k


def test_l6_returns_meta_analytic_pool_when_pool_has_three_plus() -> None:
    r = classify_readiness(
        summary={"k_eligible": 8},
        strict={"A_core_direct_lifespan": [{"study_id": f"s{i:02d}"}
                                            for i in range(5)]},
        extractions={"extractions": [{"study_id": f"s{i:02d}"}
                                      for i in range(5)]},
        pool={"effects": [{"study_id": f"s{i:02d}"} for i in range(5)]},
    )
    assert r.level == 6
    assert r.label == "meta-analytic-pool"
    assert r.counts["k_pool"] == 5
    assert "ship" in r.next_steps[0].lower()


def test_as_dict_round_trips_for_json_serialization() -> None:
    """as_dict() must contain only JSON-serialisable primitives so the
    receipt writes cleanly to disk."""
    import json
    r = classify_readiness(
        summary={"k_eligible": 1},
        strict={"A_core_direct_lifespan": [{"id": "s01"}]},
        extractions=None,
        pool={"effects": [{"id": "s01"}, {"id": "s02"}, {"id": "s03"}]},
    )
    d = r.as_dict()
    s = json.dumps(d)  # must not raise
    assert json.loads(s) == d
    assert d["level"] == 6
    assert isinstance(d["reasons"], list)
    assert isinstance(d["next_steps"], list)
    assert isinstance(d["counts"], dict)


def test_classifier_is_universal_no_domain_literals() -> None:
    """Same classifier; non-biomedical receipt shapes (climate-like)
    produce identical level results — proves no hardcoded domain
    vocabulary in the classifier."""
    r = classify_readiness(
        summary={"k_eligible": 2,
                 "topic": "carbon_tax", "judge_model": "any"},
        strict={
            "A_core_direct_lifespan": [
                {"study_id": "city-stockholm-2022"},
                {"study_id": "country-norway-2019"},
            ],
            "topic": "carbon_tax",
        },
        extractions={"extractions": [{"study_id": "city-stockholm-2022"}]},
        pool={"effects": [{"study_id": "city-stockholm-2022"},
                          {"study_id": "country-norway-2019"}]},
    )
    assert isinstance(r, ReadinessReport)
    assert r.level == 5
    assert r.label == "pilot-pool"


def test_classifier_tolerates_garbage_field_types() -> None:
    """A malformed receipt (e.g. list where dict expected) must not raise."""
    r = classify_readiness(
        summary={"k_eligible": "oops"},  # string, not int
        strict={"A_core_direct_lifespan": "not-a-list"},
        extractions=None, pool=None,
    )
    # "oops" can't be int-parsed -> k_eligible = 0 -> level 2
    assert r.level == 2
