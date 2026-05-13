"""Sprint 11.1 — reference resolver tests.

Sprint 17 extension: universal citation-sanity audit covered at bottom.
"""
from __future__ import annotations

from types import MappingProxyType

from agent.reference_resolver import (
    ResolvedReferences,
    audit_citations,
    resolve_citations,
)
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


# -----------------------------------------------------------------------------
# Sprint 17 — universal citation/reference sanity audit.
# -----------------------------------------------------------------------------


def test_cite_audit_clean_when_in_text_matches_references() -> None:
    """[1] and [2] both appear in body AND in the reference list, every
    cited anchor key is in the bibliography → audit.clean = True."""
    pack = _pack_with_biblio({
        "a-2020": "Author A 2020.", "b-2021": "Author B 2021.",
    })
    body = (
        "Foundational [CIT:a-2020|primary-study] extended by "
        "[CIT:b-2021|primary-study]."
    )
    resolved = resolve_citations(body, pack)
    audit = audit_citations(resolved, pack)
    assert audit.clean is True
    assert audit.in_text_numbers == (1, 2)
    assert audit.reference_numbers == (1, 2)
    assert audit.in_text_without_entry == ()
    assert audit.entry_without_in_text == ()
    assert audit.unresolved_anchors == ()


def test_cite_audit_flags_unresolved_anchors() -> None:
    """A [CIT:key|role] whose key isn't in the bibliography surfaces as
    an unresolved anchor — the gate that prevents [UNRESOLVED] markers
    in shipped paper.md."""
    pack = _pack_with_biblio({"a-2020": "Author A 2020."})
    body = (
        "Known [CIT:a-2020|primary-study] vs unknown "
        "[CIT:phantom|primary-study]."
    )
    resolved = resolve_citations(body, pack)
    audit = audit_citations(resolved, pack)
    assert audit.clean is False
    assert audit.unresolved_anchors == ("phantom",)
    assert audit.in_text_numbers == (1,)
    assert 1 in audit.reference_numbers  # the resolved entry


def test_cite_audit_flags_in_text_number_without_reference_entry() -> None:
    """A bare `[7]` injected by the writer that doesn't match a numbered
    reference entry must surface as in_text_without_entry — catches
    writer hallucinations of citation numbers."""
    pack = _pack_with_biblio({"a-2020": "Author A 2020."})
    resolved = ResolvedReferences(
        body="Foundational [1] and bogus [7].",
        references_section="## References\n\n1. Author A 2020.\n",
        citations_used=("a-2020",), unresolved=(),
    )
    audit = audit_citations(resolved, pack)
    assert audit.clean is False
    assert 7 in audit.in_text_without_entry
    assert 1 not in audit.in_text_without_entry


def test_cite_audit_flags_reference_entry_without_in_text_number() -> None:
    """A numbered reference entry that no [N] cites is the dual case:
    extra entry in the references section that body prose doesn't
    point to — the writer-or-stitcher drift gate."""
    pack = _pack_with_biblio({"a-2020": "Author A 2020.",
                              "b-2021": "Author B 2021."})
    resolved = ResolvedReferences(
        body="Only [1] is cited.",
        references_section=(
            "## References\n\n1. Author A 2020.\n2. Author B 2021.\n"
        ),
        citations_used=("a-2020", "b-2021"), unresolved=(),
    )
    audit = audit_citations(resolved, pack)
    assert 2 in audit.entry_without_in_text
    assert 1 not in audit.entry_without_in_text


def test_cite_audit_reports_dead_bibliography_anchors() -> None:
    """Bibliography entries that the writer never cited are flagged as
    dead (informational, not a failure) so the operator can see drift
    between topic-pack curation and what's actually used."""
    pack = _pack_with_biblio({
        "a-2020": "Author A 2020.", "b-2021": "Author B 2021.",
        "ghost-2019": "Author Ghost 2019.",
    })
    body = "Foundational [CIT:a-2020|primary-study]."
    resolved = resolve_citations(body, pack)
    audit = audit_citations(resolved, pack)
    assert "ghost-2019" in audit.dead_bibliography_anchors
    assert "b-2021" in audit.dead_bibliography_anchors
    assert "a-2020" not in audit.dead_bibliography_anchors


def test_cite_audit_as_dict_round_trips_through_json() -> None:
    """Receipt-writing safety: every field is JSON-primitive."""
    import json
    pack = _pack_with_biblio({"a-2020": "Author A 2020."})
    resolved = resolve_citations("Foo [CIT:a-2020|primary-study].", pack)
    d = audit_citations(resolved, pack).as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["clean"] is True


def test_cite_audit_universal_across_non_biomedical_vocabulary() -> None:
    """No domain literals: a climate-style anchor + bibliography produces
    the same audit shape and clean=True signal."""
    pack = _pack_with_biblio({
        "stockholm-carbon-2022": "City of Stockholm. Carbon pricing report 2022.",
    })
    body = "Carbon tax adoption [CIT:stockholm-carbon-2022|primary-study]."
    resolved = resolve_citations(body, pack)
    audit = audit_citations(resolved, pack)
    assert audit.clean is True
    assert audit.in_text_numbers == (1,)
