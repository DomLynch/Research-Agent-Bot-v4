"""Sprint 8 - effect-pooling tests."""
from __future__ import annotations

import math
from types import MappingProxyType

from agent.effect_extraction import ExtractionReceipt
from agent.effect_pooling import compile_pool, compute_effect
from agent.topic_pack import TopicPack


def _pack() -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=("mouse",), discouraged_terms=(),
        endpoint="lifespan", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("rapamycin",),
        translational_only_interventions=(), retrieval_sources=(),
        eligibility_endpoint_terms=("median_lifespan", "survival"),
        eligibility_control_terms=("control", "vehicle"),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(), secondary_design_quote_markers=(),
    )


def _r(**kw: object) -> ExtractionReceipt:
    defaults: dict[str, object] = dict(
        study_id="s1", status="extracted", metric="median_lifespan",
        treated_value=None, control_value=None,
        treated_n=None, control_n=None,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=None,
        moderators=MappingProxyType({}),
        evidence_quotes=("median lifespan extended by rapamycin in mice",),
        failure_reason="", reviewer="test", text_hash="", timestamp_utc="",
    )
    defaults.update(kw)
    return ExtractionReceipt(**defaults)  # type: ignore[arg-type]


def test_compute_effect_returns_none_when_contract_fails() -> None:
    r = _r(status="no_numerics")
    assert compute_effect(r, _pack()) is None


def test_compute_effect_uses_hazard_ratio_when_ci_present() -> None:
    r = _r(
        metric="survival", treated_value=1.0, control_value=1.0,
        hazard_ratio=0.78,
        hazard_ratio_ci_low=0.65, hazard_ratio_ci_high=0.93,
    )
    pair = compute_effect(r, _pack())
    assert pair is not None
    outcome, effect = pair
    assert effect.metric == "log_hazard_ratio"
    assert math.isclose(effect.estimate, math.log(0.78), rel_tol=1e-9)
    expected_se = (math.log(0.93) - math.log(0.65)) / (2 * 1.959963984540054)
    assert math.isclose(effect.se or 0.0, expected_se, rel_tol=1e-9)
    assert outcome.metric_name == "log_hazard_ratio"


def test_compute_effect_falls_back_to_log_median_ratio() -> None:
    r = _r(
        metric="median_lifespan",
        treated_value=1100.0, control_value=900.0,
        treated_n=120, control_n=118,
    )
    pair = compute_effect(r, _pack())
    assert pair is not None
    outcome, effect = pair
    assert effect.metric == "log_median_ratio"
    assert outcome.metric_name == "log_median_ratio"
    assert math.isclose(effect.estimate, math.log(1100.0 / 900.0), rel_tol=1e-9)
    assert math.isclose(
        effect.se or 0.0, math.sqrt(1 / 120 + 1 / 118), rel_tol=1e-9,
    )


def test_compute_effect_returns_none_without_pooling_numerics() -> None:
    r = _r(
        metric="median_lifespan",
        treated_value=1100.0, control_value=900.0,
        # missing sample sizes -> SE not estimable
    )
    assert compute_effect(r, _pack()) is None


def test_compute_effect_returns_none_for_hr_without_ci() -> None:
    r = _r(metric="survival", hazard_ratio=0.78)  # no CI bounds
    # Should fall through to median path which is also missing
    assert compute_effect(r, _pack()) is None


def test_compile_pool_keeps_modal_metric_only() -> None:
    pack = _pack()
    receipts = (
        _r(
            study_id="hr1", metric="survival", treated_value=1.0,
            control_value=1.0, hazard_ratio=0.78,
            hazard_ratio_ci_low=0.65, hazard_ratio_ci_high=0.93,
        ),
        _r(
            study_id="hr2", metric="survival", treated_value=1.0,
            control_value=1.0, hazard_ratio=0.82,
            hazard_ratio_ci_low=0.70, hazard_ratio_ci_high=0.97,
        ),
        _r(
            study_id="med1", metric="median_lifespan",
            treated_value=1100.0, control_value=900.0,
            treated_n=120, control_n=118,
        ),
    )
    outcomes, effects, skipped = compile_pool(receipts, pack)
    metrics = {e.metric for e in effects}
    assert metrics == {"log_hazard_ratio"}  # modal kept
    assert "med1" in skipped
    assert len(outcomes) == 2


def test_compile_pool_records_failures() -> None:
    receipts = (
        _r(study_id="ok", metric="median_lifespan",
           treated_value=1100, control_value=900, treated_n=10, control_n=10),
        _r(study_id="bad", status="no_numerics"),
    )
    outcomes, effects, skipped = compile_pool(receipts, _pack())
    assert {o.study_id for o in outcomes} == {"ok"}
    assert {e.study_id for e in effects} == {"ok"}
    assert "bad" in skipped
