"""Sprint 11.1 — reference resolver tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.reference_resolver import resolve_citations
from agent.topic_pack import TopicPack


def _pack_with_biblio(entries: dict[str, str]) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=(), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}),
        length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=(), translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=(),
        eligibility_control_terms=(),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
        references_bibliography=MappingProxyType(entries),
    )


def test_resolver_assigns_first_seen_numbers() -> None:
    pack = _pack_with_biblio({
        "harrison-2009-rapamycin": "Harrison DE et al. Nature 2009.",
        "miller-2011-rapamycin": "Miller RA et al. J Gerontol 2011.",
    })
    body = (
        "Foundational mouse data [CIT:harrison-2009-rapamycin|primary-study] "
        "were extended by [CIT:miller-2011-rapamycin|primary-study]."
    )
    out = resolve_citations(body, pack)
    assert "Harrison DE" in out.references_section
    assert "[1]" in out.body and "[2]" in out.body
    assert out.citations_used == (
        "harrison-2009-rapamycin", "miller-2011-rapamycin",
    )
    assert out.unresolved == ()


def test_resolver_collapses_duplicate_keys_to_one_number() -> None:
    pack = _pack_with_biblio(
        {"harrison-2009-rapamycin": "Harrison DE et al. Nature 2009."}
    )
    body = (
        "Twice cited [CIT:harrison-2009-rapamycin|primary-study] and "
        "again [CIT:harrison-2009-rapamycin|primary-study]."
    )
    out = resolve_citations(body, pack)
    assert out.body.count("[1]") == 2
    assert out.citations_used == ("harrison-2009-rapamycin",)
    # Reference list emits each key exactly once.
    assert out.references_section.count("Harrison DE") == 1


def test_resolver_surfaces_unresolved_keys_without_dropping_them() -> None:
    pack = _pack_with_biblio(
        {"harrison-2009-rapamycin": "Harrison DE et al. Nature 2009."}
    )
    body = (
        "Known [CIT:harrison-2009-rapamycin|primary-study] vs unknown "
        "[CIT:not-in-pack|primary-study]."
    )
    out = resolve_citations(body, pack)
    assert "[1]" in out.body
    assert "[UNRESOLVED]" in out.body
    assert out.unresolved == ("not-in-pack",)
    assert "Unresolved citation keys" in out.references_section
    assert "- not-in-pack" in out.references_section


def test_resolver_returns_empty_section_when_no_citations() -> None:
    pack = _pack_with_biblio({"harrison-2009-rapamycin": "Harrison DE et al."})
    out = resolve_citations("Plain prose without citations.", pack)
    assert out.body == "Plain prose without citations."
    assert out.references_section == ""
    assert out.citations_used == ()
    assert out.unresolved == ()
