"""Sprint 11.2 — methods honesty rewriter tests.

Cover:
  - phrase rewrites declared in topic_pack.methods_honesty_rewrites fire in
    longest-first order (so longer phrases consume shorter sub-phrases)
  - phrases not present in body are silently skipped (no error)
  - empty rewrite table = no-op pass-through
  - returned `rewrites_applied` tuple lists exactly the source phrases that
    matched (auditable receipt of which overclaim verbs were corrected)
"""
from __future__ import annotations

from types import MappingProxyType

from agent.methods_honesty import apply_honesty_rewrites
from agent.topic_pack import TopicPack


def _pack(rewrites: dict[str, str]) -> TopicPack:
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
        placeholders=MappingProxyType({}),
        methods_honesty_rewrites=MappingProxyType(rewrites),
    )


def test_single_rewrite_fires() -> None:
    body = "We will perform independent dual extraction across studies."
    pack = _pack({"independent dual extraction": "single-pass automated extraction"})
    out = apply_honesty_rewrites(body, pack)
    assert "single-pass automated extraction" in out.body
    assert "independent dual extraction" not in out.body
    assert out.rewrites_applied == ("independent dual extraction",)


def test_longer_phrase_consumes_shorter_substring() -> None:
    body = "leave-one-out analysis with Egger's regression test was planned."
    pack = _pack({
        # The shorter sub-phrase must NOT clobber the longer one. Sort by
        # length DESC means the longer rewrite fires first; the shorter
        # one then has no remaining match.
        "Egger's regression test": "Egger's regression test (planned, k<10)",
        "leave-one-out analysis with Egger's regression test":
            "leave-one-out and Egger (both planned once k accrues)",
    })
    out = apply_honesty_rewrites(body, pack)
    assert "leave-one-out and Egger (both planned once k accrues)" in out.body
    # The longer one ate the shorter substring; only the longer key applied.
    assert out.rewrites_applied == (
        "leave-one-out analysis with Egger's regression test",
    )


def test_phrase_not_in_body_skipped_without_error() -> None:
    body = "Plain prose containing nothing to rewrite."
    pack = _pack({"some unmatched phrase": "replacement"})
    out = apply_honesty_rewrites(body, pack)
    assert out.body == body
    assert out.rewrites_applied == ()


def test_empty_rewrites_returns_body_unchanged() -> None:
    body = "Some methods text."
    out = apply_honesty_rewrites(body, _pack({}))
    assert out.body == body
    assert out.rewrites_applied == ()


def test_multiple_rewrites_apply_in_order() -> None:
    body = (
        "We will assess SYRCLE risk-of-bias and run Egger's test for funnel "
        "asymmetry."
    )
    pack = _pack({
        "SYRCLE risk-of-bias": "automated SYRCLE-style screen",
        "Egger's test": "Egger's test (planned, k<10)",
    })
    out = apply_honesty_rewrites(body, pack)
    assert "automated SYRCLE-style screen" in out.body
    assert "Egger's test (planned, k<10)" in out.body
    assert set(out.rewrites_applied) == {"SYRCLE risk-of-bias", "Egger's test"}
