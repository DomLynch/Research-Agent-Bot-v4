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


def test_chained_rewrite_converges_in_multi_pass() -> None:
    """Sprint 11.7A regression: rewrite A produces text that rewrite B
    is supposed to consume. With a single pass + length-DESC ordering,
    B was being considered before A had fired and missed its source.
    Multi-pass converges within max_passes.
    """
    body = "We will write everything in future tense."
    pack = _pack({
        # A: long source, target injects "future tense" -> a phrase that B
        # should rewrite to "present tense".
        "We will write everything in future tense.": "We rewrite in future tense.",
        "future tense": "present tense",
    })
    out = apply_honesty_rewrites(body, pack)
    assert "We rewrite in present tense." in out.body
    # Both rewrites must be in applied list (A then B).
    assert set(out.rewrites_applied) == {
        "We will write everything in future tense.",
        "future tense",
    }


def test_each_rewrite_fires_at_most_once_no_cycle() -> None:
    """A -> 'A' (target contains source) must not loop forever; the
    fired-set guard prevents re-firing within the same call.
    """
    body = "trigger phrase appears here"
    pack = _pack({"trigger phrase": "trigger phrase plus tail"})
    out = apply_honesty_rewrites(body, pack)
    # Even though target contains source, it fires once globally.
    assert out.body == "trigger phrase plus tail appears here"
    assert out.rewrites_applied == ("trigger phrase",)


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


def test_future_tense_intro_overclaims_rewritten_to_past_tense() -> None:
    """GPT-auditor catch 2026-05-13: the Methods template borrows future-
    tense framing from SR protocols, but the pipeline has already run
    by stitch time. Universal rewrite fixes any topic that hits these
    patterns — no domain literals required."""
    body = (
        "## Methods\n"
        "This synthesis will be implemented using a reproducible pipeline. "
        "The search strategy will query PubMed and Crossref. "
        "The query-term structure will combine intervention terms with "
        "outcome vocabulary. Eligibility screening will follow PRISMA-2020. "
        "Data extraction will capture metric, n, and evidence quotes.\n"
    )
    out = apply_honesty_rewrites(body, _pack({}))
    # None of these future-tense phrases should remain.
    for phrase in (
        "will be implemented", "will query", "will combine",
        "will follow", "will capture",
    ):
        assert phrase not in out.body, f"future-tense leak: {phrase!r}"
    # The honest past-tense replacements should be present.
    assert "was implemented" in out.body
    assert "queried" in out.body
    assert "combined" in out.body
    assert "followed" in out.body
    assert "captured" in out.body
    # All five rewrites must register in the audit trail.
    expected = {
        "This synthesis will be implemented",
        "The search strategy will query",
        "The query-term structure will combine",
        "Eligibility screening will follow",
        "Data extraction will capture",
    }
    assert expected.issubset(set(out.rewrites_applied))
