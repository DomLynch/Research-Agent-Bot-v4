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
    """senolytic should expand to a list of compound names + class words."""
    out = expand_topic_keywords("senolytic")
    assert out[0] == "senolytic"  # topic always first
    assert "dasatinib" in out
    assert "quercetin" in out
    assert "ABT-263" in out
    # No duplicates
    assert len(out) == len(set(out))


def test_topic_first_then_instances_preserves_order() -> None:
    """Topic word leads, then instance order from TOML."""
    out = expand_topic_keywords("mtor_inhibitor")
    assert out[0] == "mtor_inhibitor"
    assert "rapamycin" in out


def test_expand_topic_queries_adds_normalized_prefixes() -> None:
    out = expand_topic_queries("omega_3_longevity")
    assert out[:3] == ("omega_3_longevity", "omega 3 longevity", "omega 3")


def test_text_matches_topic_finds_instance() -> None:
    """senolytic query should match a fact about dasatinib."""
    text = "dasatinib + quercetin reduced senescent cell burden by 70%"
    assert text_matches_topic(text, "senolytic")


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
