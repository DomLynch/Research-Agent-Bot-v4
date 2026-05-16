"""Sprint 64 — numeric-artifact detector tests.

Locks the universal syntactic rules + the auditor's exact failure
cases (14,15-EET, UOK 257-1, Ser555). Universal — same detector
catches the climate-policy artifact pattern (Article 5(b)).
"""
from __future__ import annotations

from agent.numeric_sanitizer import (
    filter_artifacts,
    is_numeric_artifact,
)

# ============= Auditor's named failure cases =============

def test_chemical_comma_list_14_15_eet() -> None:
    """The autophagy headliner: '14,15-EET inhibited CSC-induced
    autophagy' was parsed as numeric_value=1415. Detector must catch
    this — value 14 or 15 should be flagged as a comma-list embed."""
    phrase = "14,15-EET inhibited CSC-induced autophagy in Beas-2B cells"
    assert is_numeric_artifact(14, phrase) is True
    assert is_numeric_artifact(15, phrase) is True


def test_cell_line_uok_257_1() -> None:
    """The mTOR run had 'UOK 257-1' parsed as effect 257."""
    phrase = "UOK 257-1 cells showed up to 100-fold lower sensitivity"
    assert is_numeric_artifact(257, phrase) is True


def test_amino_acid_position_ser555() -> None:
    """The exercise run had 'Ser555' phosphorylation parsed as 555."""
    phrase = "Physical exercise increased ULK1 phosphorylation at Ser555"
    assert is_numeric_artifact(555, phrase) is True


def test_amino_acid_position_ser_paren_555() -> None:
    """The Sprint 65 audit found Ser(555) parsed as 555. Walk-adjacent
    detector must catch this — letter before paren before value."""
    phrase = "Leucine alone stimulated S6K1 phosphorylation at Ser(555)"
    assert is_numeric_artifact(555, phrase) is True


def test_amino_acid_position_with_dash() -> None:
    """Ser-555 (alternate notation) also flagged."""
    phrase = "phosphorylation at Ser-555 was increased"
    assert is_numeric_artifact(555, phrase) is True


def test_p_value_in_parens_not_artifact() -> None:
    """(P < 0.001) — value preceded by whitespace inside parens; the
    P is separated by whitespace, so walk-back stops at the space
    before seeing the letter. Not an identifier embed."""
    phrase = "the difference was significant (P < 0.001) in the trial"
    assert is_numeric_artifact(0.001, phrase) is False


def test_value_in_parens_with_space_not_artifact() -> None:
    """(60%) — paren is not a letter, whitespace before paren. Real
    effect size in parens should pass."""
    phrase = "lifespan extension (60%) was observed in middle-aged mice"
    assert is_numeric_artifact(60, phrase) is False


def test_chemical_abt_263() -> None:
    """'ABT-263 reduced SMC by 90%' — value 263 is the compound id."""
    phrase = "ABT-263 reduced SMC by 90% in advanced atherosclerosis"
    assert is_numeric_artifact(263, phrase) is True


# ============= True positives — real effect sizes =============

def test_real_percent_effect_not_artifact() -> None:
    """'reduced SMC by 90%' — value 90 is a clean effect."""
    phrase = "ABT-263 reduced SMC by 90% in advanced atherosclerosis"
    assert is_numeric_artifact(90, phrase) is False


def test_real_lifespan_extension_not_artifact() -> None:
    phrase = ("3 months of rapamycin extended remaining lifespan by ~60% "
              "in middle-aged mice")
    assert is_numeric_artifact(60, phrase) is False


def test_real_dose_not_artifact() -> None:
    phrase = "Mice received NMN in drinking water (400 mg/kg)"
    assert is_numeric_artifact(400, phrase) is False


def test_real_year_not_artifact() -> None:
    """Year mentions like '2014' should pass — they're surrounded by
    spaces, not identifier characters."""
    phrase = "Miller et al. 2014 reported median lifespan extension"
    assert is_numeric_artifact(2014, phrase) is False


# ============= Edge cases / robustness =============

def test_empty_phrase_not_artifact() -> None:
    assert is_numeric_artifact(60, "") is False


def test_value_not_in_phrase_is_artifact() -> None:
    """If the value doesn't appear in the canonical_phrase, it's
    either a concat artifact (14,15 -> 1415) or an unauditable
    extraction. Either way: do not surface in Top 5."""
    assert is_numeric_artifact(99, "completely unrelated text") is True


def test_value_1415_from_comma_concat_is_artifact() -> None:
    """The auditor's exact case: '14,15-EET' phrase, value=1415
    (extractor concatenated). value 1415 doesn't appear in phrase
    -> artifact via the 'value-absent' rule."""
    assert is_numeric_artifact(
        1415, "14,15-EET inhibited CSC-induced autophagy") is True


def test_none_value_not_artifact() -> None:
    assert is_numeric_artifact(None, "any phrase") is False


def test_bool_value_skipped() -> None:
    """Bool isn't a numeric value we'd extract."""
    assert is_numeric_artifact(True, "True statements") is False
    assert is_numeric_artifact(False, "False positives") is False


def test_float_value_supported() -> None:
    phrase = "the protein decreased 27.5% from baseline"
    assert is_numeric_artifact(27.5, phrase) is False


# ============= filter_artifacts batch helper =============

def test_filter_splits_kept_and_filtered() -> None:
    """Realistic case: extractor produces (90, 14, 263) — the artifact
    filter keeps 90 (clean effect) and 60, drops 14 (comma-list embed)
    and 263 (identifier embed)."""
    facts = [
        {"numeric_value": 90.0, "canonical_phrase":
         "ABT-263 reduced SMC by 90% in plaque"},
        {"numeric_value": 263.0, "canonical_phrase":
         "ABT-263 reduced SMC by 90% in plaque"},
        {"numeric_value": 14.0, "canonical_phrase":
         "14,15-EET inhibited autophagy"},
        {"numeric_value": 60.0, "canonical_phrase":
         "rapamycin extended lifespan by 60%"},
    ]
    kept, filtered = filter_artifacts(facts)
    assert len(kept) == 2
    kept_values = {f["numeric_value"] for f in kept}
    assert kept_values == {90.0, 60.0}
    filtered_values = {f["numeric_value"] for f in filtered}
    assert filtered_values == {263.0, 14.0}


def test_filter_handles_non_dict_entries() -> None:
    facts: list[object] = [
        {"numeric_value": 60.0, "canonical_phrase": "x by 60%"},
        "not-a-dict",
        {"numeric_value": 90.0, "canonical_phrase": "y by 90%"},
    ]
    kept, filtered = filter_artifacts(facts)  # type: ignore[arg-type]
    assert len(kept) == 2
    assert filtered == []


# ============= Universal non-biomedical fixture =============

def test_universal_policy_identifier_article_5() -> None:
    """Climate policy: 'Article 5(b)' would be parsed as value 5.
    Detector must catch it under rule 1 (alphanumeric before)."""
    phrase = "Article5(b) of the IPCC framework requires reporting"
    assert is_numeric_artifact(5, phrase) is True


def test_universal_real_climate_effect_not_artifact() -> None:
    phrase = "Sweden's carbon tax cut emissions by 8% over 1991-2020"
    assert is_numeric_artifact(8, phrase) is False


# ============= Sprint 69 — auditor cases (Cal 27 / 72 h) =============

def test_cell_line_with_space_cal_27_is_artifact() -> None:
    """Sprint 69 / auditor: 'Cal 27' is a cell-line designator parsed
    as numeric_value=27 in the sirtuin betaine item. Walk-stop in
    rule 1 misses it because the letters and digits are space-
    separated. Sprint 69 catches the one-space identifier pattern."""
    phrase = ("betaines showed the highest effect in reducing Cal 27 "
              "cell proliferation up to 72 h (p < 0.01)")
    assert is_numeric_artifact(27, phrase) is True


def test_cell_line_with_space_hct_116_is_artifact() -> None:
    """HCT 116 — 3-letter prefix + space + 3-digit code."""
    phrase = "HCT 116 cells showed reduced proliferation after treatment"
    assert is_numeric_artifact(116, phrase) is True


def test_inline_time_suffix_72h_is_artifact() -> None:
    """Sprint 69 / auditor: 'treatment with whey for 72 h' in the
    sirtuin SIRT3 item was parsed as numeric_value=72.0 with empty
    units field, so the lane classifier saw 'unknown' instead of
    'duration'. The sanitizer must also catch this so top_5.md
    doesn't surface a duration as an effect."""
    phrase = ("treatment with whey for 72 h inhibited cell proliferation "
              "(p < 0.001)")
    assert is_numeric_artifact(72, phrase) is True


def test_inline_time_suffix_24_hours_is_artifact() -> None:
    """Full-word time unit: '24 hours of fasting'."""
    phrase = "24 hours of fasting reduced glucose by 15%"
    assert is_numeric_artifact(24, phrase) is True


def test_inline_time_suffix_30_min_is_artifact() -> None:
    """Min suffix: '30 min of exercise'."""
    phrase = "subjects performed 30 min of moderate-intensity exercise"
    assert is_numeric_artifact(30, phrase) is True


def test_real_effect_with_year_following_not_artifact() -> None:
    """'8% over 1991-2020' — the 8 is followed by '%' (no time
    suffix). Sprint 69 must not regress the climate-policy effect
    test."""
    phrase = "Sweden's carbon tax cut emissions by 8% over 1991-2020"
    assert is_numeric_artifact(8, phrase) is False


def test_dose_with_unit_not_flagged_as_time_suffix() -> None:
    """'8 mg/kg/day i.p.' — value 8 followed by 'mg' (not a time
    unit). Must not trigger the time-suffix rule."""
    phrase = "rapamycin was administered at 8 mg/kg/day i.p. for 3 weeks"
    assert is_numeric_artifact(8, phrase) is False


def test_ic50_concentration_after_gene_name_not_artifact() -> None:
    """Sprint 69 regression: 'IC50 SIRT2 0.25 µM' — the value 0.25
    is a real concentration effect (compound's IC50). The 'IRT2 '
    prefix is part of a gene name, not a cell-line designator, and
    µM follows the value. Identifier rule must not false-positive
    when a measurement unit follows."""
    phrase = ("compound 55 (IC50 SIRT2 0.25 µM and <25% inhibition "
              "at 50 µM against SIRT1 and SIRT3)")
    assert is_numeric_artifact(0.25, phrase) is False


def test_real_percent_after_capitalized_word_not_artifact() -> None:
    """'The 60% reduction was observed' — value 60 follows 'The '
    (uppercase prefix) but '%' immediately follows the value, so
    it's a real effect, not an identifier embed."""
    phrase = "The 60% reduction was observed in treated cohorts"
    assert is_numeric_artifact(60, phrase) is False


def test_real_dose_after_capitalized_word_not_artifact() -> None:
    """'Mice 8 mg/kg/day' — 'Mice ' prefix could falsely look like
    an identifier; the 'mg' unit follows so the value is a dose."""
    phrase = "Mice 8 mg/kg/day intraperitoneally for 3 weeks"
    assert is_numeric_artifact(8, phrase) is False


def test_lowercase_word_before_value_not_identifier() -> None:
    """'over 1991-2020' — 'over' is lowercase English, not a
    capitalized identifier code. Sprint 69 capitalized-prefix rule
    must not regress this. (1991 already flagged by rule 2 as part
    of '1991-2020' pure-numeric range, but the prefix check itself
    should be inert here.)"""
    # Year-range fixtures are caught by rule 2; testing the prefix
    # rule in isolation: a lowercase prefix must not match.
    phrase = "between 2020 results emerged"
    # value 2020 isolated, preceded by 'en ' (lowercase) — not an
    # identifier. Year recognition stays as-is.
    assert is_numeric_artifact(2020, phrase) is False
