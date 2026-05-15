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


def test_value_not_in_phrase_not_artifact() -> None:
    """Value 99 doesn't appear in phrase -> nothing to flag."""
    assert is_numeric_artifact(99, "completely unrelated text") is False


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
