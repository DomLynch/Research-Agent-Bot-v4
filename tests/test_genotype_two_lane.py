"""Sprint 11.3 - two-lane primary effect tests.

Covers `has_genotype_modified_strain`: studies whose evidence quotes
name a genotype-modified strain marker (BMAL1 knockout, transgenic,
etc.) are flagged for routing into the B_disease_model_survival
sensitivity lane instead of carrying the A-core headline estimate.

Note on Unicode: the real BMAL1 paper renders homozygous deletion as
"Bmal1<U+2212>/<U+2212>" (MINUS SIGN, U+2212), not "Bmal1-/-"
(HYPHEN-MINUS). Tests use `\\u2212` escape sequences so the source
file stays ASCII-clean while still exercising the production marker.
"""
from __future__ import annotations

from types import MappingProxyType

from agent.include_contract import has_genotype_modified_strain
from agent.topic_pack import TopicPack

# Match the production marker (Unicode MINUS SIGN, U+2212) without
# putting the raw glyph in source bytes (ruff RUF001 flags ambiguity).
_MINUS = chr(0x2212)


def _pack(markers: tuple[str, ...]) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="mouse",
        preferred_terms=("mouse", "mice"),
        discouraged_terms=(), endpoint="lifespan",
        cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}),
        length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=(), translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=(), eligibility_control_terms=(),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
        genotype_modified_strain_markers=markers,
        references_bibliography=MappingProxyType({}),
        placeholders=MappingProxyType({}),
        methods_honesty_rewrites=MappingProxyType({}),
    )


def test_bmal1_knockout_quote_flags_genotype_modified() -> None:
    quotes = (
        f"Kaplan-Meyer survival curves of Bmal1{_MINUS}/{_MINUS} mice",
        "The median lifespan of untreated mice is 7.8 months",
    )
    assert has_genotype_modified_strain(
        quotes, _pack((f"bmal1{_MINUS}/{_MINUS}",)),
    ) is True


def test_wild_type_heterogeneous_stock_does_not_flag() -> None:
    quotes = (
        "Genetically heterogeneous male and female mice from the UM-HET3 stock",
        "Rapamycin extended median lifespan compared with controls",
    )
    assert has_genotype_modified_strain(
        quotes, _pack(("knockout", "transgenic", f"{_MINUS}/{_MINUS}")),
    ) is False


def test_transgenic_marker_caught_case_insensitive() -> None:
    quotes = ("APP/PS1 Transgenic mice treated with rapamycin",)
    assert has_genotype_modified_strain(quotes, _pack(("transgenic",))) is True


def test_no_markers_in_pack_returns_false() -> None:
    quotes = ("Bmal1-/- mice were treated with rapamycin",)
    assert has_genotype_modified_strain(quotes, _pack(())) is False


def test_empty_quotes_returns_false() -> None:
    assert has_genotype_modified_strain((), _pack(("knockout",))) is False


def test_multiple_markers_only_one_needed() -> None:
    quotes = (
        "Wild-type C57BL/6 mice were the primary cohort",
        "A separate cohort of IGF1R-deficient mice received rapamycin",
    )
    assert has_genotype_modified_strain(
        quotes, _pack(("knockout", "-deficient", "transgenic")),
    ) is True
