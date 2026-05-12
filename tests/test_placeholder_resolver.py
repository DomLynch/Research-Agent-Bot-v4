"""Sprint 11.2 — placeholder resolver tests.

Cover:
  - count placeholders ([N_SCREENED], [N_ACCEPTED], [K_STUDIES]) resolve
    from eligibility_summary + strict A-core receipts
  - [PLACEHOLDER:<key>] resolves from topic_pack.placeholders
  - unknown keys surface as [<token>][UNRESOLVED] (never silently dropped)
  - zero counts (k_hits=0) resolve to "0" and are NOT marked unresolved
"""
from __future__ import annotations

from types import MappingProxyType

from agent.placeholder_resolver import resolve_placeholders
from agent.topic_pack import TopicPack


def _pack(placeholders: dict[str, str]) -> TopicPack:
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
        references_bibliography=MappingProxyType({}),
        placeholders=MappingProxyType(placeholders),
        methods_honesty_rewrites=MappingProxyType({}),
    )


def test_count_placeholders_resolve_from_receipts() -> None:
    summary = {"k_hits": 502, "k_eligible": 8}
    strict = {"A_core_direct_lifespan": [{"study_id": "a"}, {"study_id": "b"}]}
    body = "screened [N_SCREENED] -> accepted [N_ACCEPTED] -> pooled [K_STUDIES]."
    out = resolve_placeholders(body, summary=summary, strict=strict, pack=_pack({}))
    assert out.body == "screened 502 -> accepted 8 -> pooled 2."
    assert set(out.resolved) == {"N_SCREENED", "N_ACCEPTED", "K_STUDIES"}
    assert out.unresolved == ()


def test_topic_pack_placeholder_resolves() -> None:
    summary: dict[str, object] = {}
    strict: dict[str, object] = {}
    body = "Search ran across [PLACEHOLDER:databases] within [PLACEHOLDER:date-range]."
    pack = _pack({
        "databases": "PubMed + OpenAlex",
        "date-range": "2001-2026",
    })
    out = resolve_placeholders(body, summary=summary, strict=strict, pack=pack)
    assert out.body == "Search ran across PubMed + OpenAlex within 2001-2026."
    assert set(out.resolved) == {"PLACEHOLDER:databases", "PLACEHOLDER:date-range"}
    assert out.unresolved == ()


def test_unknown_token_surfaces_unresolved() -> None:
    summary: dict[str, object] = {}
    strict: dict[str, object] = {}
    body = "Threshold [PLACEHOLDER:not-in-pack]."
    out = resolve_placeholders(body, summary=summary, strict=strict, pack=_pack({}))
    assert "[PLACEHOLDER:not-in-pack][UNRESOLVED]" in out.body
    assert out.unresolved == ("PLACEHOLDER:not-in-pack",)


def test_missing_count_surfaces_unresolved() -> None:
    summary: dict[str, object] = {}  # no k_hits
    strict: dict[str, object] = {}
    body = "Identified [N_SCREENED] records."
    out = resolve_placeholders(body, summary=summary, strict=strict, pack=_pack({}))
    assert "[N_SCREENED][UNRESOLVED]" in out.body
    assert out.unresolved == ("N_SCREENED",)


def test_zero_count_resolves_to_zero_not_unresolved() -> None:
    summary: dict[str, object] = {"k_hits": 0, "k_eligible": 0}
    strict: dict[str, object] = {"A_core_direct_lifespan": []}
    body = "[N_SCREENED] hits -> [N_ACCEPTED] accepted -> [K_STUDIES] pooled."
    out = resolve_placeholders(body, summary=summary, strict=strict, pack=_pack({}))
    assert out.body == "0 hits -> 0 accepted -> 0 pooled."
    assert out.unresolved == ()


def test_no_placeholders_in_body_returns_unchanged() -> None:
    body = "Plain prose with no placeholders."
    out = resolve_placeholders(
        body, summary={}, strict={}, pack=_pack({}),
    )
    assert out.body == body
    assert out.resolved == ()
    assert out.unresolved == ()
