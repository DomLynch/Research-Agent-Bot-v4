"""Sprint 8 - effect-extraction contract + parser tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.effect_extraction import (
    build_extraction_prompt,
    parse_extraction_response,
    receipt_from_response,
    validate_extraction,
)
from agent.topic_pack import TopicPack


def _pack() -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=("mouse",), discouraged_terms=(),
        endpoint="lifespan", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("rapamycin",),
        translational_only_interventions=(), retrieval_sources=(),
        eligibility_endpoint_terms=("median_lifespan", "survival"),
        eligibility_control_terms=("control", "vehicle"),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(), secondary_design_quote_markers=(),
    )


def test_prompt_includes_pack_metric_and_intervention_vocab() -> None:
    msgs = build_extraction_prompt(_pack(), "s1", "Test title", "body text")
    assert len(msgs) == 2
    user = msgs[1]["content"]
    assert "median_lifespan" in user and "survival" in user
    assert "rapamycin" in user
    assert "control" in user and "vehicle" in user
    assert "JSON" in user


def test_parser_strips_json_fence() -> None:
    raw = '```json\n{"status": "extracted", "metric": "median_lifespan"}\n```'
    parsed = parse_extraction_response(raw)
    assert parsed["status"] == "extracted"


def test_parser_extracts_object_after_prose() -> None:
    raw = (
        "Some reasoning prose first.\n\n"
        '{"status": "extracted", "metric": "median_lifespan", '
        '"treated_value": 1100}'
    )
    parsed = parse_extraction_response(raw)
    assert parsed["treated_value"] == 1100


def test_parser_raises_on_unparseable() -> None:
    try:
        parse_extraction_response("no json here")
    except ValueError as e:
        assert "JSON" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_receipt_from_response_normalises_types() -> None:
    parsed = {
        "status": "extracted",
        "metric": "median_lifespan",
        "treated_value": "1100",  # string -> float
        "control_value": 900,
        "treated_n": "120",        # string -> int
        "control_n": 118,
        "hazard_ratio": 0.78,
        "hazard_ratio_ci_low": None,
        "hazard_ratio_ci_high": None,
        "percent_change": 12.5,
        "moderators": {"sex": "male", "strain": "C57BL/6"},
        "evidence_quotes": ["Rapamycin extended median lifespan by 12%."],
        "failure_reason": "",
    }
    r = receipt_from_response(
        parsed, study_id="s1", text_hash="hash",
        reviewer="mimo", timestamp_utc="2026-05-12T00:00:00+00:00",
    )
    assert r.status == "extracted"
    assert r.treated_value == 1100.0
    assert r.treated_n == 120
    assert r.moderators["sex"] == "male"
    assert r.evidence_quotes == ("Rapamycin extended median lifespan by 12%.",)


def test_receipt_from_response_handles_unknown_status() -> None:
    r = receipt_from_response(
        {"status": "junk"}, study_id="s1", text_hash="",
        reviewer="mimo", timestamp_utc="t",
    )
    assert r.status == "no_numerics"


def test_contract_passes_on_complete_extraction() -> None:
    r = receipt_from_response(
        {
            "status": "extracted", "metric": "median_lifespan",
            "treated_value": 1100, "control_value": 900,
            "evidence_quotes": ["Rapamycin extended median lifespan in mice."],
        },
        study_id="s1", text_hash="", reviewer="mimo", timestamp_utc="t",
    )
    res = validate_extraction(r, _pack())
    assert res.passes
    assert res.violations == ()


def test_contract_fails_when_status_not_extracted() -> None:
    r = receipt_from_response(
        {"status": "no_numerics", "metric": "", "failure_reason": "no data"},
        study_id="s1", text_hash="", reviewer="mimo", timestamp_utc="t",
    )
    res = validate_extraction(r, _pack())
    assert not res.passes
    assert any("status=no_numerics" in v for v in res.violations)


def test_contract_fails_when_metric_off_vocabulary() -> None:
    r = receipt_from_response(
        {
            "status": "extracted", "metric": "weight_grams",
            "treated_value": 30, "control_value": 28,
            "evidence_quotes": ["weight diff"],
        },
        study_id="s1", text_hash="", reviewer="mimo", timestamp_utc="t",
    )
    res = validate_extraction(r, _pack())
    assert not res.passes
    assert any("endpoint vocabulary" in v for v in res.violations)


def test_contract_accepts_hazard_ratio_only() -> None:
    r = receipt_from_response(
        {
            "status": "extracted", "metric": "survival",
            "treated_value": 100, "control_value": None,
            "hazard_ratio": 0.78,
            "evidence_quotes": ["HR 0.78 (95% CI 0.65-0.93)"],
        },
        study_id="s1", text_hash="", reviewer="mimo", timestamp_utc="t",
    )
    res = validate_extraction(r, _pack())
    assert res.passes


def test_contract_requires_evidence_quote() -> None:
    r = receipt_from_response(
        {
            "status": "extracted", "metric": "median_lifespan",
            "treated_value": 1100, "control_value": 900,
            "evidence_quotes": [],
        },
        study_id="s1", text_hash="", reviewer="mimo", timestamp_utc="t",
    )
    res = validate_extraction(r, _pack())
    assert not res.passes
    assert any("evidence quote" in v for v in res.violations)
