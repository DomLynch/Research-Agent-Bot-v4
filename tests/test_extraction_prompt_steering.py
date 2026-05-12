"""Sprint 11.3 — extraction prompt steering tests.

Covers two prompt nudges:
  1. metric-family preference clause appears in the system prompt when
     pack.preferred_metric_families is non-empty;
  2. sample-size recovery instruction appears regardless (its absence
     was the reviewer's specific blocker for s086 / s230 / s235).
"""
from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from agent.effect_extraction import build_extraction_prompt
from agent.topic_pack import TopicPack


def _pack(preferred: tuple[str, ...]) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="mouse",
        preferred_terms=("mouse",),
        discouraged_terms=(), endpoint="lifespan",
        cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}),
        length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("rapamycin",),
        translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=("lifespan", "survival"),
        eligibility_control_terms=("vehicle",),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
        genotype_modified_strain_markers=(),
        preferred_metric_families=preferred,
        references_bibliography=MappingProxyType({}),
        placeholders=MappingProxyType({}),
        methods_honesty_rewrites=MappingProxyType({}),
    )


def test_sample_size_nudge_always_present() -> None:
    msgs = build_extraction_prompt(_pack(()), "s086", "Title", "Body" * 100)
    system = msgs[0]["content"]
    assert "Sample-size recovery is critical" in system
    assert "treated_n and control_n" in system
    assert "Methods, Table 1" in system


def test_metric_family_preference_clause_when_pack_declares_preference() -> None:
    msgs = build_extraction_prompt(
        _pack(("median_lifespan", "median_survival")),
        "s246", "BMAL1 KO median lifespan", "Body" * 100,
    )
    system = msgs[0]["content"]
    assert "When multiple metric families are reported" in system
    assert "median_lifespan" in system
    assert "median_survival" in system
    assert "inverse-variance-pooled" in system


def test_no_preference_clause_when_pack_empty() -> None:
    msgs = build_extraction_prompt(_pack(()), "s086", "Title", "Body" * 100)
    system = msgs[0]["content"]
    assert "When multiple metric families are reported" not in system


def test_preference_clause_handles_single_family() -> None:
    msgs = build_extraction_prompt(
        _pack(("median_lifespan",)), "s086", "Title", "Body" * 100,
    )
    system = msgs[0]["content"]
    assert "[median_lifespan]" in system


def test_unicode_minus_marker_does_not_break_prompt() -> None:
    """Defence in depth: the BMAL1 paper uses U+2212; the prompt should
    handle a pack whose strings contain it without UnicodeError."""
    minus_pack = replace(
        _pack(("median_lifespan",)),
        genotype_modified_strain_markers=(f"bmal1{chr(0x2212)}/{chr(0x2212)}",),
    )
    msgs = build_extraction_prompt(minus_pack, "s246", "T", "Body" * 100)
    assert isinstance(msgs[0]["content"], str)
    assert isinstance(msgs[1]["content"], str)
