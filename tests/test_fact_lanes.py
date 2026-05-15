"""Sprint 59 — fact-lane classifier tests.

Locks the A/B/C/D rules. Universal fixtures: each test names a
specific failure mode (missing PICO, non-effect numeric, off-topic,
adjacent-mechanism) and verifies the lane decision.
"""
from __future__ import annotations

from typing import Any

from agent.fact_lanes import (
    LaneVerdict,
    classify_lane,
    classify_lanes,
    lane_counts,
)


def _fact(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fact_id": "f/x",
        "canonical_phrase": "rapamycin extended median lifespan by 60%",
        "population": "middle-aged C57BL/6 mice",
        "intervention": "rapamycin 8 mg/kg/day",
        "comparator": "vehicle",
        "numeric_value": 60.0,
        "units": "%",
    }
    base.update(overrides)
    return base


def test_complete_pico_with_effect_size_is_a_core() -> None:
    v = classify_lane(_fact(), topic="rapamycin")
    assert v.lane == "A_core"
    assert v.numeric_role == "effect_size"


def test_missing_intervention_is_d_bad_extraction() -> None:
    v = classify_lane(_fact(intervention=""), topic="rapamycin")
    assert v.lane == "D_bad_extraction"
    assert v.reason == "missing_population_or_intervention"


def test_missing_population_is_d_bad_extraction() -> None:
    v = classify_lane(_fact(population=""), topic="rapamycin")
    assert v.lane == "D_bad_extraction"


def test_duration_numeric_is_d_bad_extraction() -> None:
    """The '66 weeks' failure mode the auditor flagged on caloric_restriction."""
    v = classify_lane(_fact(
        canonical_phrase="inguinal fat was significantly increased by CR at 66 weeks",
        intervention="caloric restriction",
        numeric_value=66.0, units="weeks",
    ), topic="caloric_restriction")
    assert v.lane == "D_bad_extraction"
    assert v.numeric_role == "duration"


def test_regimen_numeric_is_d_bad_extraction() -> None:
    """'70% CR conditions' should not rank as an effect size."""
    v = classify_lane(_fact(
        canonical_phrase="CR conditions (70%)",
        intervention="caloric restriction",
        numeric_value=70.0, units="%",
    ), topic="caloric_restriction")
    assert v.lane == "D_bad_extraction"
    assert v.numeric_role == "regimen"


def test_topic_absent_is_c_noise() -> None:
    v = classify_lane(_fact(
        canonical_phrase="glucose levels dropped by 60%",
        population="diabetic patients",
        intervention="insulin therapy",
    ), topic="rapamycin")
    assert v.lane == "C_noise"


def test_topic_in_phrase_only_is_b_context() -> None:
    """Topic appears in canonical_phrase but not intervention -> B_context."""
    v = classify_lane(_fact(
        canonical_phrase="rapamycin-treated cells showed 60% reduction in growth",
        intervention="vehicle control",  # topic NOT in intervention
    ), topic="rapamycin")
    assert v.lane == "B_context"


def test_classify_lanes_batch_returns_one_per_fact() -> None:
    out = classify_lanes(
        [_fact(fact_id="f/1"), _fact(fact_id="f/2"), _fact(fact_id="f/3")],
        topic="rapamycin",
    )
    assert len(out) == 3
    assert {v.fact_id for v in out} == {"f/1", "f/2", "f/3"}


def test_classify_lanes_skips_non_dict_entries() -> None:
    out = classify_lanes([_fact(), "not-a-dict", _fact()],  # type: ignore[list-item]
                          topic="rapamycin")
    assert len(out) == 2


def test_lane_counts_buckets_all_four_lanes() -> None:
    verdicts = [
        LaneVerdict(fact_id="a", lane="A_core",
                    numeric_role="effect_size", reason="r"),
        LaneVerdict(fact_id="b", lane="A_core",
                    numeric_role="effect_size", reason="r"),
        LaneVerdict(fact_id="c", lane="D_bad_extraction",
                    numeric_role="duration", reason="r"),
        LaneVerdict(fact_id="d", lane="C_noise",
                    numeric_role="effect_size", reason="r"),
    ]
    counts = lane_counts(verdicts)
    assert counts["A_core"] == 2
    assert counts["D_bad_extraction"] == 1
    assert counts["C_noise"] == 1
    assert counts["B_context"] == 0


def test_universal_non_biomedical_carbon_tax() -> None:
    """Climate-policy fixture: 8% emissions reduction → A_core."""
    v = classify_lane({
        "fact_id": "ct/swe",
        "canonical_phrase": "Sweden cut emissions by 8% via carbon_tax 1991-2020",
        "population": "Sweden 1991-2020",
        "intervention": "carbon_tax",
        "numeric_value": 8.0, "units": "%",
    }, topic="carbon_tax")
    assert v.lane == "A_core"
