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


def test_missing_both_pico_fields_is_d_bad_extraction() -> None:
    """D_bad now requires BOTH population AND intervention empty (essentially
    no PICO). A single empty slot is recoverable as B_context, not discarded."""
    v = classify_lane(_fact(intervention="", population=""), topic="rapamycin")
    assert v.lane == "D_bad_extraction"
    assert v.reason == "missing_population_and_intervention"


def test_missing_only_intervention_is_b_context_not_d_bad() -> None:
    """One empty PICO slot (intervention) no longer discards the fact: topic
    still matches via population/phrase, so it binds as usable B_context."""
    v = classify_lane(_fact(intervention=""), topic="rapamycin")
    assert v.lane == "B_context"


def test_missing_only_population_is_not_d_bad() -> None:
    """One empty PICO slot (population) no longer discards the fact as D_bad.
    Here intervention + numeric effect + topic-in-intervention remain, so it
    still earns A_core — the point is it is NOT thrown away for one empty slot."""
    v = classify_lane(_fact(population=""), topic="rapamycin")
    assert v.lane != "D_bad_extraction"
    assert v.lane == "A_core"


def test_duration_numeric_is_b_context_not_a_core() -> None:
    """The '66 weeks' timepoint must not rank as an effect size (so not the
    A_core lead), but the finding ('fat significantly increased by CR') is a
    real qualitative result with clean PICO + topic match — bind as context,
    don't discard it."""
    v = classify_lane(_fact(
        canonical_phrase="inguinal fat was significantly increased by CR at 66 weeks",
        intervention="caloric restriction",
        numeric_value=66.0, units="weeks",
    ), topic="caloric_restriction")
    assert v.lane == "B_context"
    assert v.numeric_role == "duration"
    assert v.reason == "topic_matched_no_clean_numeric_effect"


def test_regimen_numeric_is_b_context_not_a_core() -> None:
    """'70% CR conditions' is a regimen descriptor, not an effect size: not the
    A_core lead, but still PICO-complete + topic-matched context."""
    v = classify_lane(_fact(
        canonical_phrase="CR conditions (70%)",
        intervention="caloric restriction",
        numeric_value=70.0, units="%",
    ), topic="caloric_restriction")
    assert v.lane == "B_context"
    assert v.numeric_role == "regimen"


def test_numeric_less_finding_is_b_context_not_d_bad() -> None:
    """The dominant real-world case: a qualitative finding with complete PICO
    and topic-in-intervention but NO numeric value. Must bind as B_context
    (not discarded as D_bad just for lacking a number), while staying out of
    the A_core lead (which still requires a real numeric effect)."""
    v = classify_lane(_fact(
        canonical_phrase="ATO promoted autophagy and reduced atherosclerotic lesions",
        population="ApoE-/- mice",
        intervention="autophagy induction via ATO",
        numeric_value=None, units=None,
    ), topic="autophagy")
    assert v.lane == "B_context"
    assert v.reason == "topic_matched_no_clean_numeric_effect"


def test_topic_absent_is_c_noise() -> None:
    v = classify_lane(_fact(
        canonical_phrase="glucose levels dropped by 60%",
        population="diabetic patients",
        intervention="insulin therapy",
    ), topic="rapamycin")
    assert v.lane == "C_noise"


def test_senolytic_ignores_standalone_oncology_instance_use() -> None:
    """Class synonyms must not treat any standalone oncology use of an instance
    drug as senolytic evidence."""
    v = classify_lane(_fact(
        canonical_phrase="Objective response was observed in 21% of patients",
        population="relapsed refractory AML patients",
        intervention="venetoclax with low-intensity chemotherapy",
    ), topic="senolytic")

    assert v.lane == "C_noise"


def test_senolytic_context_phrase_still_binds() -> None:
    v = classify_lane(_fact(
        canonical_phrase="dasatinib + quercetin reduced senescent cell burden by 70%",
        population="aged mice",
        intervention="dasatinib + quercetin senolytic therapy",
    ), topic="senolytic")

    assert v.lane == "A_core"


def test_topic_in_phrase_only_is_b_context() -> None:
    """Topic appears in canonical_phrase but not intervention -> B_context."""
    v = classify_lane(_fact(
        canonical_phrase="rapamycin-treated cells showed 60% reduction in growth",
        intervention="vehicle control",  # topic NOT in intervention
    ), topic="rapamycin")
    assert v.lane == "B_context"


def test_background_add_on_therapy_is_context_not_a_core() -> None:
    """If the topic appears only as background therapy, the active intervention
    belongs to another treatment and must not lead as direct evidence."""
    v = classify_lane(_fact(
        canonical_phrase="HbA1c fell by 1.02% in the dorzagliatin group",
        population="patients with inadequate glycemic control",
        intervention="dorzagliatin added to metformin",
        comparator="placebo added to metformin",
        numeric_value=-1.02,
        units="%",
    ), topic="metformin_use")

    assert v.lane == "B_context"
    assert v.reason == "topic_in_background_context"


def test_population_background_therapy_is_context_not_a_core() -> None:
    v = classify_lane(_fact(
        canonical_phrase="HbA1c fell by 0.82% for canagliflozin vs glimepiride",
        population="patients with type 2 diabetes receiving metformin",
        intervention="canagliflozin",
        comparator="glimepiride",
        numeric_value=0.82,
        units="%",
    ), topic="metformin_use")

    assert v.lane == "B_context"
    assert v.reason == "topic_in_background_context"


def test_direct_topic_use_still_a_core() -> None:
    v = classify_lane(_fact(
        canonical_phrase="mortality was 13.0% for metformin users",
        population="sepsis patients with type 2 diabetes",
        intervention="preadmission metformin use",
        comparator="non-metformin use",
        numeric_value=13.0,
        units="%",
    ), topic="metformin_use")

    assert v.lane == "A_core"


def test_exercise_synonyms_bind_activity_receipts() -> None:
    """Exercise evidence often says physical activity or resistance training,
    not the literal topic word. The binding lives in topic-pack data."""
    v = classify_lane(_fact(
        canonical_phrase="VO2 peak increased by 10.6% after dynamic resistance training",
        population="older adults",
        intervention="dynamic resistance training",
        comparator="usual activity",
        numeric_value=10.6,
        units="%",
    ), topic="exercise")

    assert v.lane == "A_core"
    assert v.reason == "topic_in_intervention_pico_complete"


def test_exercise_synonyms_do_not_match_generic_training_word() -> None:
    v = classify_lane(_fact(
        canonical_phrase="safety training reduced errors by 10%",
        population="nursing teams",
        intervention="safety training",
        comparator="usual onboarding",
        numeric_value=10.0,
        units="%",
    ), topic="exercise")

    assert v.lane == "C_noise"


def test_topic_in_population_with_effect_is_a_core() -> None:
    """Condition/outcome topics can be direct when the topic is the studied
    population and the intervention has a real numeric effect."""
    v = classify_lane(_fact(
        canonical_phrase="exercise improved appendicular muscle mass by 8%",
        population="older adults with sarcopenia",
        intervention="resistance exercise",
        comparator="usual care",
        numeric_value=8.0,
        units="%",
    ), topic="sarcopenia_muscle_preservation")

    assert v.lane == "A_core"
    assert v.reason == "topic_in_population_pico_complete"


def test_disease_topic_population_match_is_context_not_a_core() -> None:
    v = classify_lane(_fact(
        canonical_phrase="exercise improved mobility by 8%",
        population="older adults with alzheimer disease",
        intervention="resistance exercise",
        comparator="usual care",
        numeric_value=8.0,
        units="%",
    ), topic="alzheimer_disease")

    assert v.lane == "B_context"
    assert v.reason == "topic_in_population_context_only"


def test_long_head_population_fallback_is_universal() -> None:
    """The compound-topic head fallback is structural, not biomedical:
    long, specific head words can define a studied population in any domain."""
    v = classify_lane({
        "fact_id": "mw/1",
        "canonical_phrase": "filtration policy reduced contamination by 12%",
        "population": "microplastic-contaminated rivers",
        "intervention": "filtration policy",
        "comparator": "usual monitoring",
        "numeric_value": 12.0,
        "units": "%",
    }, topic="microplastic_water_quality")

    assert v.lane == "A_core"
    assert v.reason == "topic_in_population_pico_complete"


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
