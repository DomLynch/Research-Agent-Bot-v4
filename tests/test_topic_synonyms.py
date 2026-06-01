"""Sprint 62 — class -> instance synonym resolver tests.

Locks the contract:
  - empty topic -> empty tuple
  - unregistered topic -> tuple containing just the topic word
  - registered class topic -> topic + all instances, dedup'd, topic-first
  - text_matches_topic case-insensitive, underscore-aware
  - text_matches_topic matches instance words for class queries
  - TOML missing / malformed -> falls back gracefully to {}
  - Universal non-biomedical (carbon_tax) still works without registry
"""
from __future__ import annotations

from pathlib import Path

from agent.topic_synonyms import (
    _norm,
    expand_topic_keywords,
    expand_topic_queries,
    load_synonyms,
    text_matches_topic,
)


def test_norm_collapses_punctuation_and_underscores() -> None:
    assert _norm("carbon_tax") == "carbon tax"
    assert _norm("ABT-263") == "abt 263"
    assert _norm("  Mixed-CASE/STUFF  ") == "mixed case stuff"


def test_empty_topic_returns_empty_tuple() -> None:
    assert expand_topic_keywords("") == ()
    assert expand_topic_keywords("   ") == ()


def test_unregistered_topic_returns_just_topic() -> None:
    """Topic not in synonyms TOML -> single-element tuple with the topic."""
    out = expand_topic_keywords("xyz_unknown_topic_2026")
    assert out == ("xyz_unknown_topic_2026",)


def test_registered_class_expands_to_instances() -> None:
    """senolytic should expand to tight senolytic-context instances."""
    out = expand_topic_keywords("senolytic")
    assert out[0] == "senolytic"  # topic always first
    assert "dasatinib" not in out
    assert "quercetin" not in out
    assert "venetoclax" not in out
    assert "dasatinib + quercetin" in out
    assert "ABT-263" in out
    # No duplicates
    assert len(out) == len(set(out))


def test_topic_first_then_instances_preserves_order() -> None:
    """Topic word leads, then instance order from TOML."""
    out = expand_topic_keywords("mtor_inhibitor")
    assert out[0] == "mtor_inhibitor"
    assert "rapamycin" in out


def test_expand_topic_queries_adds_normalized_prefixes() -> None:
    # Unregistered slug: prefix-trimming applies to the topic itself.
    out = expand_topic_queries("renewable_energy_subsidy")
    assert out[:3] == (
        "renewable_energy_subsidy", "renewable energy subsidy", "renewable energy",
    )


def test_unregistered_slug_queries_include_intervention_forms() -> None:
    out = expand_topic_queries("vitamin_D_healthspan", max_queries=8)

    assert "vitamin d" in out
    assert "vitamin d supplementation" in out


def test_expand_topic_queries_can_reach_registered_instances() -> None:
    out = expand_topic_queries("carnosine_anti_glycation", max_queries=16)

    assert "carnosine" in out


def test_registered_topic_does_not_trim_to_generic_modifier() -> None:
    out = expand_topic_queries("low_dose_lithium", max_queries=16)

    assert "low dose" not in out
    assert "lithium" in out


def test_unregistered_long_slug_does_not_trim_to_generic_short_prefix() -> None:
    out = expand_topic_queries("low_dose_naltrexone_inflammation", max_queries=16)

    assert "low dose naltrexone" in out
    assert "low dose" not in out
    assert "low dose therapy" not in out


def test_text_matches_topic_finds_instance() -> None:
    """senolytic query should match a fact about D+Q senescent-cell clearance."""
    text = "dasatinib + quercetin reduced senescent cell burden by 70%"
    assert text_matches_topic(text, "senolytic")


def test_senolytic_does_not_match_standalone_oncology_drug_use() -> None:
    assert not text_matches_topic(
        "venetoclax produced objective responses in AML patients", "senolytic",
    )
    assert not text_matches_topic(
        "dasatinib improved survival in Philadelphia-positive ALL", "senolytic",
    )


def test_text_matches_topic_finds_class_word_directly() -> None:
    assert text_matches_topic(
        "senolytic therapy reduced SMC", "senolytic")


def test_text_matches_topic_case_insensitive() -> None:
    assert text_matches_topic("DASATINIB + QUERCETIN cleared cells",
                              "senolytic")


def test_text_matches_topic_underscore_normalised() -> None:
    """carbon_tax topic should match 'carbon tax' in text."""
    assert text_matches_topic("Sweden's carbon tax cut emissions",
                              "carbon_tax")


def test_text_matches_returns_false_on_no_overlap() -> None:
    assert not text_matches_topic("glucose levels dropped", "senolytic")


def test_text_matches_empty_inputs() -> None:
    assert not text_matches_topic("", "senolytic")
    assert not text_matches_topic("dasatinib", "")


def test_short_synonym_matches_on_word_boundary_only() -> None:
    """`EPA` must NOT match inside `heparin`, but must match the real token."""
    assert not text_matches_topic("heparin reduced clotting risk", "omega_3_longevity")
    assert text_matches_topic("EPA reduced triglycerides", "omega_3_longevity")
    # also exercised through the fact-lane classifier's shared matcher
    from agent.topic_synonyms import phrase_in_text
    assert not phrase_in_text("epa", "heparin reduced clotting")
    assert phrase_in_text("epa", "epa lowered triglycerides")


def test_multiword_synonym_not_trimmed_to_generic_fragment() -> None:
    """Instances must NOT prefix-trim to generic fragments: 'low level laser
    therapy' must match its real phrase but not unrelated 'low-level ...' text."""
    t = "photobiomodulation_red_light"
    assert "low level" not in expand_topic_queries(t, max_queries=64)
    assert text_matches_topic("low-level laser therapy improved symptoms", t)
    assert not text_matches_topic("low-level weight loss intervention", t)


def test_brain_age_mri_requires_brain_age_not_generic_mri() -> None:
    assert text_matches_topic("BrainAGE predicted dementia conversion", "brain_age_MRI")
    assert text_matches_topic("brain age gap differed by diagnosis", "brain_age_MRI")
    assert not text_matches_topic("MRI classified brain tumors", "brain_age_MRI")
    assert not text_matches_topic("magnetic resonance imaging classified Parkinson disease", "brain_age_MRI")


def test_load_synonyms_missing_file_returns_empty() -> None:
    """Pointing at a nonexistent path returns {} (graceful)."""
    load_synonyms.cache_clear()
    out = load_synonyms(Path("/nonexistent/path/xyz.toml"))
    assert out == {}


def test_load_synonyms_malformed_toml_returns_empty(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("not valid toml = = = ===", encoding="utf-8")
    load_synonyms.cache_clear()
    assert load_synonyms(bad) == {}


def test_load_synonyms_returns_registered_classes() -> None:
    load_synonyms.cache_clear()
    syn = load_synonyms()
    assert "senolytic" in syn
    assert "mtor_inhibitor" in syn
    assert isinstance(syn["senolytic"], tuple)
    assert len(syn["senolytic"]) > 0


def test_universal_non_biomedical_unregistered_works() -> None:
    """xyz_topic without registry -> single-keyword behavior preserved."""
    text = "xyz_topic effects observed in cohort"
    assert text_matches_topic(text, "xyz_topic")
    assert not text_matches_topic(text, "different_thing")
