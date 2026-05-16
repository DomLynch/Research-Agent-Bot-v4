"""Sprint 59 — numeric role classifier tests.

Locks the unit + context rules. Universal fixtures only (no biomedical
hardcoding in the assertions themselves)."""
from __future__ import annotations

from agent.numeric_role_classifier import (
    classify_numeric_role,
    is_real_finding,
)


def test_percent_with_no_regimen_markers_is_effect_size() -> None:
    assert classify_numeric_role(
        60.0, "%", "3 months of rapamycin extended remaining lifespan by ~60%",
    ) == "effect_size"


def test_percent_with_restriction_marker_is_regimen() -> None:
    assert classify_numeric_role(
        40.0, "%", "Mice under 40% caloric restriction showed reversal",
    ) == "regimen"


def test_percent_with_conditions_marker_is_regimen() -> None:
    assert classify_numeric_role(
        70.0, "%", "CR conditions (70%)",
    ) == "regimen"


def test_weeks_units_classify_as_duration() -> None:
    assert classify_numeric_role(
        66.0, "weeks",
        "inguinal fat was significantly increased by CR at 66 weeks",
    ) == "duration"


def test_mg_per_kg_classifies_as_dose() -> None:
    assert classify_numeric_role(
        8.0, "mg/kg/day", "rapamycin 8 mg/kg/day i.p.",
    ) == "dose"


def test_mm_concentration_unit_classifies_as_concentration() -> None:
    assert classify_numeric_role(5.0, "mM", "5 mM glucose") == "concentration"


def test_fold_change_detected_from_context() -> None:
    assert classify_numeric_role(
        4.0, "", "a 4-fold increase in expression",
    ) == "fold_change"


def test_p_value_detected_from_context() -> None:
    assert classify_numeric_role(
        0.01, "", "macroadenoma rate: 1.71 vs 2.35; p=0.01",
    ) == "p_value"


def test_correlation_detected_from_context() -> None:
    assert classify_numeric_role(
        0.73, "", "creatine levels showed a correlation r=0.73 with age",
    ) == "correlation"


def test_sample_size_detected_from_n_marker() -> None:
    assert classify_numeric_role(
        218.0, "", "elderly humans (n=218) received the vaccine",
    ) == "sample_size"


def test_unknown_when_no_match() -> None:
    assert classify_numeric_role(42.0, "", "the answer was 42") == "unknown"


def test_is_real_finding_only_for_effect_fold_correlation() -> None:
    assert is_real_finding("effect_size")
    assert is_real_finding("fold_change")
    assert is_real_finding("correlation")
    assert not is_real_finding("dose")
    assert not is_real_finding("duration")
    assert not is_real_finding("regimen")
    assert not is_real_finding("sample_size")
    assert not is_real_finding("unknown")


def test_ratio_unit_or_classifies_as_effect_size() -> None:
    """Sprint 68: OR (odds ratio) is universal epi statistics —
    effect_size, not unknown. Auditor's telomere case."""
    assert classify_numeric_role(
        15.5, "OR",
        "age-adjusted OR=15.5 [95% CI 11.6-20.8] for breast cancer",
    ) == "effect_size"


def test_ratio_unit_hr_classifies_as_effect_size() -> None:
    """HR (hazard ratio) — same family as OR."""
    assert classify_numeric_role(
        0.90, "HR",
        "metformin HR 0.90 for colorectal cancer in cohort",
    ) == "effect_size"


def test_ratio_unit_rr_classifies_as_effect_size() -> None:
    """RR (relative risk) — same family."""
    assert classify_numeric_role(2.66, "RR",
                                  "longer TL RR=2.66 melanoma") == "effect_size"


def test_pvalue_prefix_position_aware_apc_case() -> None:
    """Sprint 68: 'macroadenoma count was 1.33 vs 2.50 (P<0.01)' —
    the value 1.33 is the effect, P<0.01 is a separate stat further
    along. Position-aware p-prefix detector should NOT classify 1.33
    as p_value; the paired-comparison fallback below catches the vs."""
    assert classify_numeric_role(
        1.33, "",
        "macroadenoma count was 1.33 vs 2.50 in CR males (P<0.01)",
    ) == "effect_size"


def test_pvalue_prefix_immediately_before_value_classifies_pvalue() -> None:
    """The 'p = 2.98 e-9' case: 2.98 immediately follows 'p = ' —
    must classify as p_value, not effect_size, even though phrase
    also contains 'vs'."""
    assert classify_numeric_role(
        2.98, "",
        "p = 2.98 e-9 for highest vs lowest quintile",
    ) == "p_value"


def test_paired_comparison_vs_marker_is_effect_size() -> None:
    """Sprint 67: '1.33 vs 2.50' (Apc(1638N/+) macroadenoma counts)
    should classify as effect_size, not unknown. Universal stats
    syntax."""
    assert classify_numeric_role(
        1.33, "",
        "macroadenoma count was 1.33 vs 2.50 in CR males (P<0.01)",
    ) == "effect_size"


def test_paired_comparison_plus_minus_marker_is_effect_size() -> None:
    """'1.71 ± 0.26 vs 2.35 ± 0.25' — mean±SD comparison."""
    assert classify_numeric_role(
        1.71, "",
        "macroadenomas in CR males (1.71 ± 0.26) vs control (2.35 ± 0.25)",
    ) == "effect_size"


def test_versus_word_marker_is_effect_size() -> None:
    assert classify_numeric_role(
        12.3, "",
        "primary outcome 12.3 versus 15.7 in treatment arm",
    ) == "effect_size"


def test_unitless_positive_without_comparison_stays_unknown() -> None:
    """A bare unitless number with no stats marker stays unknown
    (no false-positive promotion)."""
    assert classify_numeric_role(
        42, "", "the answer was 42",
    ) == "unknown"


def test_universal_non_biomedical_fixture() -> None:
    """Climate-policy fixture: 8% emissions reduction with no regimen
    markers should be classified as effect_size."""
    assert classify_numeric_role(
        8.0, "%", "Sweden's carbon tax cut emissions by 8% over 1991-2020",
    ) == "effect_size"


def test_minute_units_classify_as_duration() -> None:
    """Any time-unit -> duration (no biomedical assumption)."""
    assert classify_numeric_role(
        30.0, "min", "treatment for 30 min",
    ) == "duration"
