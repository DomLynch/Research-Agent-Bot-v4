"""Sprint 7.8 include-contract tests + lane classifier."""
from __future__ import annotations

from types import MappingProxyType

from agent.include_contract import (
    MIN_CHARS,
    classify_lane,
    demote_failed_includes,
    strict_a_core_check,
    validate_include,
)
from agent.screening import EligibilityReceipt, ParsedFullTextReceipt
from agent.topic_pack import TopicPack


def _pack() -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=("mouse",), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("rapamycin",),
        translational_only_interventions=(), retrieval_sources=(),
        eligibility_endpoint_terms=("lifespan", "survival"),
        eligibility_control_terms=("control", "vehicle"),
        eligibility_exclude_design_terms=("review",),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=2000,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(), secondary_design_quote_markers=(),
    )


def _receipt(
    decision: str = "include", quotes: tuple[str, ...] = (), parsed_ok: bool = True,
) -> EligibilityReceipt:
    return EligibilityReceipt(
        study_id="s1", decision=decision,  # type: ignore[arg-type]
        reason="ok", reviewer="llm-judge", confidence=1.0,
        mandatory_fields=MappingProxyType({
            "species_match": True, "intervention_match": True,
            "endpoint_present": True, "control_present": True,
            "primary_research_design": True, "parsed_text_adequate": parsed_ok,
        }),
        evidence_quotes=quotes,
    )


def _parsed(char_count: int = 10_000) -> ParsedFullTextReceipt:
    return ParsedFullTextReceipt(
        study_id="s1", source_url="u", parsed=True,
        text_hash="h", char_count=char_count,
    )


def test_validate_include_passes_on_clean_receipt() -> None:
    r = _receipt(quotes=(
        "We treated mice with rapamycin for lifespan analysis.",
        "Vehicle control animals were monitored alongside.",
    ))
    res = validate_include(r, _parsed(), "Rapamycin in C57BL/6 mice", _pack())
    assert res.passes
    assert res.violations == ()


def test_validate_include_fails_when_parsed_text_inadequate() -> None:
    # The s237 bug: parsed_text_adequate=False sneaks through merge.
    r = _receipt(quotes=("a rapamycin lifespan quote", "vehicle control quote"), parsed_ok=False)
    res = validate_include(r, _parsed(char_count=54), "Rapamycin Survival in Mice", _pack())
    assert not res.passes
    assert any("parsed_text_adequate" in v for v in res.violations)
    assert any("char_count 54" in v for v in res.violations)


def test_validate_include_fails_when_only_title_evidence() -> None:
    title = "Rapamycin extends lifespan in mice"
    # Only quote is the title itself - judge never saw real content.
    r = _receipt(quotes=(title,))
    res = validate_include(r, _parsed(), title, _pack())
    assert not res.passes
    assert any("non-title evidence quote" in v for v in res.violations)


def test_validate_include_fails_when_no_endpoint_quote() -> None:
    r = _receipt(quotes=(
        "We treated mice with rapamycin daily.",
        "Vehicle was administered to control animals.",
    ))  # no "lifespan" or "survival"
    res = validate_include(r, _parsed(), "Rapamycin in mice", _pack())
    assert not res.passes
    assert any("endpoint term" in v for v in res.violations)


def test_validate_include_fails_when_no_intervention_quote() -> None:
    r = _receipt(quotes=(
        "Lifespan was measured in all cohorts.",
        "Survival curves were estimated.",
    ))  # no "rapamycin" or "control"
    res = validate_include(r, _parsed(), "Lifespan study in mice", _pack())
    assert not res.passes
    assert any("intervention or control" in v for v in res.violations)


def test_classify_lane_review_title() -> None:
    assert classify_lane(
        "A systematic review of rapamycin", 10_000, "include", _pack(),
    ) == "D_review_background"


def test_classify_lane_secondary_molecular() -> None:
    assert classify_lane(
        "Proteomic patterns of lifespan-extending interventions",
        80_000, "include", _pack(),
    ) == "C_secondary_molecular"


def test_classify_lane_disease_model() -> None:
    assert classify_lane(
        "Rapamycin in a mouse model of Alzheimer disease",
        50_000, "include", _pack(),
    ) == "B_disease_model_survival"


def test_classify_lane_direct_lifespan() -> None:
    assert classify_lane(
        "Long-term rapamycin treatment effects on lifespan in male mice",
        50_000, "include", _pack(),
    ) == "A_direct_lifespan"


def test_classify_lane_exclude_below_min_chars() -> None:
    # Direct-lifespan-style title but char_count below MIN_CHARS -> E.
    assert classify_lane(
        "Rapamycin lifespan in mice", 100, "include", _pack(),
    ) == "E_exclude"


def test_classify_lane_handles_unclear_decision() -> None:
    assert classify_lane(
        "Rapamycin lifespan in mice", 50_000, "unclear", _pack(),
    ) == "E_exclude"


def _pack_strict() -> TopicPack:
    """Pack with non-mouse-species + secondary-design markers populated."""
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=("mouse", "mice"), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("rapamycin",),
        translational_only_interventions=(), retrieval_sources=(),
        eligibility_endpoint_terms=("lifespan", "survival"),
        eligibility_control_terms=("control", "vehicle"),
        eligibility_exclude_design_terms=("review",),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=2000,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=("c. elegans", "drosophila"),
        secondary_design_quote_markers=("proteomic", "dirac"),
    )


def test_strict_a_core_passes_when_quotes_cover_all_four_signals() -> None:
    quotes = (
        "We treated mice with rapamycin and measured median lifespan.",
        "Vehicle control animals were monitored alongside survival curves.",
    )
    ok, reasons = strict_a_core_check("include", quotes, _pack_strict())
    assert ok
    assert reasons == ()


def test_strict_a_core_demotes_only_non_mouse_quotes() -> None:
    # Quotes about rapamycin extending lifespan in C. elegans / Drosophila
    # only - no mouse evidence.
    quotes = (
        "Rapamycin extended C. elegans lifespan by 30 percent with control comparison.",
        "Drosophila survival was similarly extended in vehicle-controlled trials.",
    )
    ok, reasons = strict_a_core_check("include", quotes, _pack_strict())
    assert not ok
    assert any("non-mouse" in r for r in reasons)
    assert any("mouse" in r for r in reasons)


def test_strict_a_core_demotes_secondary_marker_quotes() -> None:
    quotes = (
        "We treated mice with rapamycin and measured median lifespan.",
        "DIRAC analysis of liver proteomic signatures versus control samples.",
    )
    ok, reasons = strict_a_core_check("include", quotes, _pack_strict())
    assert not ok
    assert any("secondary" in r for r in reasons)


def test_strict_a_core_rejects_non_include_decision() -> None:
    ok, reasons = strict_a_core_check("unclear", (), _pack_strict())
    assert not ok
    assert any("decision" in r for r in reasons)


def test_strict_a_core_missing_each_field_lists_it() -> None:
    # Only quotes mention mouse + rapamycin (no control, no endpoint).
    quotes = ("We treated mice with rapamycin in this experiment.",)
    ok, reasons = strict_a_core_check("include", quotes, _pack_strict())
    assert not ok
    assert any("control" in r for r in reasons)
    assert any("lifespan/survival" in r for r in reasons)


def test_demote_failed_includes_rewrites_decision_to_unclear() -> None:
    bad = _receipt(quotes=(), parsed_ok=False)
    parsed_by_id = {"s1": _parsed(char_count=54)}
    titles = {"s1": "Some paper"}
    new_receipts, results = demote_failed_includes(
        (bad,), parsed_by_id, titles, _pack(),
    )
    assert new_receipts[0].decision == "unclear"
    assert "include_contract failed" in new_receipts[0].reason
    assert "s1" in results
    assert not results["s1"].passes


def test_demote_failed_includes_leaves_clean_includes_alone() -> None:
    good = _receipt(quotes=(
        "rapamycin extends lifespan in mice",
        "vehicle control animals were used",
    ))
    parsed_by_id = {"s1": _parsed(char_count=20_000)}
    titles = {"s1": "Clean title without keywords"}
    new_receipts, results = demote_failed_includes(
        (good,), parsed_by_id, titles, _pack(),
    )
    assert new_receipts[0].decision == "include"
    assert results["s1"].passes


def test_min_chars_constant_documented() -> None:
    assert MIN_CHARS == 5_000
