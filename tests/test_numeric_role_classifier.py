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


def test_latex_times_detected_as_fold_change_with_weak_units() -> None:
    assert classify_numeric_role(
        47.0, "score",
        "SwiftMem achieves 47$\\times$ faster search compared to baselines.",
    ) == "fold_change"


def test_unicode_times_detected_as_fold_change() -> None:
    assert classify_numeric_role(
        47.0, "", "SwiftMem achieves 47\u00d7 faster search compared to baselines.",
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


def test_weighted_mean_difference_with_measurement_unit_is_effect_size() -> None:
    """Explicit comparative-estimate syntax makes the value a finding,
    even when the outcome's unit also looks like a concentration unit."""
    assert classify_numeric_role(
        1.16, "mmol/L",
        "outcome changed (WMD = -1.16 mmol/L, 95% CI -1.36 to -0.96)",
    ) == "effect_size"


def test_standardized_mean_difference_is_effect_size() -> None:
    assert classify_numeric_role(
        1.06, "", "TC (SMD: 1.06; 95%CI: 0.64, 1.48; p = 0.00)",
    ) == "effect_size"


def test_p_value_near_effect_estimate_stays_p_value() -> None:
    assert classify_numeric_role(
        0.00, "", "TC (SMD: 1.06; 95%CI: 0.64, 1.48; p = 0.00)",
    ) == "p_value"


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


# ============= Sprint 71 — universal regimen / sample-size =============

def test_universal_carbon_restriction_is_regimen() -> None:
    """Climate-policy regimen: '40% carbon restriction' uses the
    universal 'restriction' marker — not biomedical."""
    assert classify_numeric_role(
        40.0, "%", "Sectoral 40% carbon restriction was imposed",
    ) == "regimen"


def test_universal_budget_protocol_is_regimen() -> None:
    """Public-finance regimen: 'budget protocol' fires the universal
    'protocol' marker."""
    assert classify_numeric_role(
        25.0, "%", "the 25% austerity protocol applied to ministries",
    ) == "regimen"


def test_universal_engineering_load_conditions_is_regimen() -> None:
    """Engineering regimen: '70% load conditions' — 'conditions' is
    universal across stress-test, climate, training domains."""
    assert classify_numeric_role(
        70.0, "%", "beam tested under 70% load conditions",
    ) == "regimen"


def test_universal_training_regimen_marker() -> None:
    """Sports / training: '60% VO2max regimen' — 'regimen' is
    universal."""
    assert classify_numeric_role(
        60.0, "%", "athletes followed a 60% VO2max regimen",
    ) == "regimen"


def test_universal_survey_sample_size_via_n_marker() -> None:
    """Social-science / survey: 'respondents (n=2400) reported' —
    'n=' is universal, even though 'respondents' isn't in the marker
    set. The structural 'n=' notation is sufficient."""
    assert classify_numeric_role(
        2400.0, "",
        "respondents (n=2400) reported a 12% drop in confidence",
    ) == "sample_size"


def test_universal_economics_subjects_sample_size() -> None:
    """Behavioural economics: 'subjects (n=500)' uses two universal
    markers."""
    assert classify_numeric_role(
        500.0, "", "subjects in the field experiment (n=500)",
    ) == "sample_size"


def test_biomedical_specific_markers_no_longer_in_set() -> None:
    """Sprint 71: 'patients' / 'volunteers' / 'feeding' / 'ad lib'
    were dropped from the marker sets. A phrase with ONLY those
    words (no n=, no participants, no restriction) must NOT
    classify as sample_size or regimen — the role classifier is now
    silo-agnostic. Universal-no-hardcoding contract enforced."""
    # 'patients' alone no longer triggers sample_size.
    assert classify_numeric_role(
        300.0, "", "treated patients showed improvement",
    ) != "sample_size"
    # 'feeding' alone no longer triggers regimen.
    assert classify_numeric_role(
        70.0, "%", "ad libitum feeding at 70% calories",
    ) != "regimen"


def test_loaded_role_markers_have_no_biomedical_literals() -> None:
    """Sprint 72 — structural lock on the universal-no-hardcoding
    contract. The role-marker vocabulary lives in
    topic_packs/role_markers.toml; this test asserts that no
    domain/clinical/animal-husbandry literal is in the loaded data.
    If a biomedical leak ever lands in the TOML, this test fails
    immediately. The auditor's strictest reading of 'no
    hardcoding' is now enforceable by CI."""
    from agent.numeric_role_classifier import _load_role_markers
    markers = _load_role_markers()
    blocklist = frozenset({
        # Clinical-trial vocabulary
        "patients", "volunteers", "patient", "clinic", "clinical",
        # Animal-husbandry / Latin
        "feeding", "feed", "ad lib", "ad libitum", "mice", "rats",
        # Drug/molecule literals
        "rapamycin", "metformin", "resveratrol", "sirt", "mtor",
        # Disease literals
        "cancer", "tumor", "alzheimer", "diabetes",
    })
    all_markers = markers["regimen"] | markers["sample_size"]
    leaks = {m for m in all_markers if m.lower() in blocklist}
    assert not leaks, (
        f"biomedical literals leaked into topic_packs/role_markers.toml: "
        f"{sorted(leaks)}. The universal-no-hardcoding contract requires "
        f"only language-level English research vocabulary.")


def test_role_markers_are_loaded_from_data_file() -> None:
    """Sprint 72 — the classifier should not embed marker lists in
    code. Loading from the TOML data file must yield non-empty
    universal vocabulary for both regimen and sample_size."""
    from agent.numeric_role_classifier import _load_role_markers
    markers = _load_role_markers()
    assert markers["regimen"], "regimen markers missing from TOML"
    assert markers["sample_size"], "sample_size markers missing from TOML"
    # Spot-check a known universal entry survives the round-trip.
    assert "restriction" in markers["regimen"]
    assert "n=" in markers["sample_size"]


# ============= Sprint 73 — regimen locality fix =============

def test_pct_with_diet_subject_far_from_value_is_effect_size() -> None:
    """Sprint 73 / auditor: 'Mediterranean diet reduced LDL by 30%'
    — 'diet' is the subject of a result clause, not adjacent to the
    value. The 30% IS the outcome, not the dose. The locality fix
    requires the regimen marker to sit within a tight window around
    the value, not just anywhere in the phrase."""
    assert classify_numeric_role(
        30.0, "%", "Mediterranean diet reduced LDL by 30%",
    ) == "effect_size"


def test_pct_with_protocol_subject_far_from_value_is_effect_size() -> None:
    """'policy protocol cut emissions by 8%' — 'protocol' is the
    subject of the clause, far from the value. The 8% is the
    outcome. Universal across climate / policy domains."""
    assert classify_numeric_role(
        8.0, "%", "policy protocol cut emissions by 8%",
    ) == "effect_size"


def test_pct_with_regimen_subject_far_from_value_is_effect_size() -> None:
    """'training regimen improved VO2max by 12%' — 'regimen' is
    the subject, the 12% is the outcome magnitude. Universal
    across sports / training domains."""
    assert classify_numeric_role(
        12.0, "%", "training regimen improved VO2max by 12%",
    ) == "effect_size"


def test_pct_with_conditions_far_from_value_is_effect_size() -> None:
    """'lab conditions did not change but the response rose 20%'
    — 'conditions' present but far before the value with an
    intervening result verb."""
    assert classify_numeric_role(
        20.0, "%",
        "lab conditions did not change but the response rose 20%",
    ) == "effect_size"
