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


def test_moderator_p_resolves_from_placeholders_table() -> None:
    body = "Moderators: [MODERATOR_P:sex] and [MODERATOR_P:dose]."
    pack = _pack({
        "MODERATOR_P:sex": "biological sex",
        "MODERATOR_P:dose": "dose level (mg/kg)",
    })
    out = resolve_placeholders(body, summary={}, strict={}, pack=pack)
    assert out.body == "Moderators: biological sex and dose level (mg/kg)."
    assert set(out.resolved) == {"MODERATOR_P:sex", "MODERATOR_P:dose"}
    assert out.unresolved == ()


def test_unknown_moderator_p_surfaces_unresolved() -> None:
    body = "[MODERATOR_P:not-in-pack] should surface."
    out = resolve_placeholders(body, summary={}, strict={}, pack=_pack({}))
    assert "[MODERATOR_P:not-in-pack][UNRESOLVED]" in out.body
    assert out.unresolved == ("MODERATOR_P:not-in-pack",)


def test_count_aware_noun_agreement_pluralises_correctly() -> None:
    """Sprint 12.5: [<LANE>_COUNT:<noun>] returns 'N noun' (singular at 1)
    or 'N nouns' (plural at >1), with universal English rules."""
    strict = {
        "A_core_direct_lifespan": [
            {"study_id": "s1"}, {"study_id": "s2"}, {"study_id": "s3"},
        ],
        "B_disease_model_survival": [{"study_id": "s246"}],
        "C_secondary_contextual": [],
    }
    body = (
        "A=[A_CORE_COUNT:study], "
        "B=[B_LANE_COUNT:record], "
        "C=[C_LANE_COUNT:study], "
        "verb=[B_LANE_COUNT:effect]"
    )
    out = resolve_placeholders(body, summary={}, strict=strict, pack=_pack({}))
    assert out.body == "A=3 studies, B=1 record, C=0 studies, verb=1 effect"


def test_count_aware_noun_agreement_pluralises_y_consonant_to_ies() -> None:
    """study -> studies (y->ies); but ratio -> ratios (-o/-os simple plural)."""
    strict = {"A_core_direct_lifespan": [{"study_id": "s1"}, {"study_id": "s2"}]}
    body = "[A_CORE_COUNT:study] / [A_CORE_COUNT:effect] / [A_CORE_COUNT:bus]"
    out = resolve_placeholders(body, summary={}, strict=strict, pack=_pack({}))
    assert out.body == "2 studies / 2 effects / 2 buses"


def test_k_poolable_count_noun_resolves_from_pool() -> None:
    body = "k=[K_POOLABLE_COUNT:effect]"
    out = resolve_placeholders(
        body, summary={}, strict={}, pack=_pack({}),
        pool={"effects": [{"study_id": "a"}, {"study_id": "b"}]},
    )
    assert out.body == "k=2 effects"


def test_lane_tokens_resolve_a_b_c_counts_and_ids() -> None:
    """Sprint 12.3 universal lane tokens: B + C count/ids alongside A-core."""
    strict = {
        "A_core_direct_lifespan": [{"study_id": "s126"}, {"study_id": "s235"}],
        "B_disease_model_survival": [{"study_id": "s246"}],
        "C_secondary_contextual": [{"study_id": "s086"}, {"study_id": "s230"}],
    }
    body = (
        "A=[STRICT_A_CORE_COUNT] ([STRICT_A_CORE_IDS]); "
        "B=[B_LANE_COUNT] ([B_LANE_IDS]); "
        "C=[C_LANE_COUNT] ([C_LANE_IDS])."
    )
    out = resolve_placeholders(body, summary={}, strict=strict, pack=_pack({}))
    assert out.body == (
        "A=2 (s126, s235); B=1 (s246); C=2 (s086, s230)."
    )


def test_empty_b_c_lanes_render_none() -> None:
    """Honest framing when a lane is empty — '(none)' not a blank gap."""
    strict = {"A_core_direct_lifespan": [{"study_id": "s126"}]}
    body = "B=[B_LANE_IDS]; C=[C_LANE_IDS]"
    out = resolve_placeholders(body, summary={}, strict=strict, pack=_pack({}))
    assert out.body == "B=(none); C=(none)"


def test_strict_a_core_count_and_ids_resolve_from_receipts() -> None:
    """Universal corpus tokens: counts + comma-joined IDs from strict.json."""
    strict = {"A_core_direct_lifespan": [
        {"study_id": "s126"}, {"study_id": "s235"}, {"study_id": "s288"},
    ]}
    body = (
        "After strict A-core auditing, [STRICT_A_CORE_COUNT] records remain "
        "eligible ([STRICT_A_CORE_IDS])."
    )
    out = resolve_placeholders(body, summary={}, strict=strict, pack=_pack({}))
    assert out.body == (
        "After strict A-core auditing, 3 records remain eligible "
        "(s126, s235, s288)."
    )
    assert set(out.resolved) == {"STRICT_A_CORE_COUNT", "STRICT_A_CORE_IDS"}


def test_k_poolable_resolves_from_pool_when_supplied() -> None:
    pool = {"effects": [{"study_id": "s126"}, {"study_id": "s235"}]}
    body = "Inverse-variance pool currently contains [K_POOLABLE] effects."
    out = resolve_placeholders(
        body, summary={}, strict={}, pack=_pack({}), pool=pool,
    )
    assert out.body == "Inverse-variance pool currently contains 2 effects."


def test_incomplete_recovery_ids_lists_non_extracted_studies() -> None:
    extractions = {"receipts": [
        {"study_id": "s086", "status": "extracted"},
        {"study_id": "s230", "status": "parse_failed"},
        {"study_id": "s288", "status": "parse_failed"},
        {"study_id": "s126", "status": "extracted"},
    ]}
    body = "Sample-size recovery incomplete for [INCOMPLETE_RECOVERY_IDS]."
    out = resolve_placeholders(
        body, summary={}, strict={}, pack=_pack({}), extractions=extractions,
    )
    assert out.body == "Sample-size recovery incomplete for s230, s288."


def test_incomplete_recovery_renders_none_when_all_extracted() -> None:
    extractions = {"receipts": [
        {"study_id": "s126", "status": "extracted"},
        {"study_id": "s235", "status": "extracted"},
    ]}
    out = resolve_placeholders(
        "Incomplete: [INCOMPLETE_RECOVERY_IDS].", summary={}, strict={},
        pack=_pack({}), extractions=extractions,
    )
    assert out.body == "Incomplete: (none)."


def test_corpus_tokens_unresolved_when_receipts_missing() -> None:
    body = "k=[K_POOLABLE] missing=[INCOMPLETE_RECOVERY_IDS]"
    out = resolve_placeholders(body, summary={}, strict={}, pack=_pack({}))
    assert "[K_POOLABLE][UNRESOLVED]" in out.body
    assert "[INCOMPLETE_RECOVERY_IDS][UNRESOLVED]" in out.body


def test_packet_and_cit_markers_are_left_alone() -> None:
    """[PACKET:...] are audit anchors; [CIT:...] are citation markers.

    Neither belongs to the placeholder family; the resolver must not touch
    them or downstream handlers (reference_resolver, packet auditor) get
    silently broken.
    """
    body = "See [PACKET:primary_effect] and [CIT:harrison-2009|primary-study]."
    out = resolve_placeholders(body, summary={}, strict={}, pack=_pack({}))
    assert out.body == body
    assert out.resolved == ()
    assert out.unresolved == ()
