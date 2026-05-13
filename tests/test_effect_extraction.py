"""Sprint 8 - effect-extraction contract + parser tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.effect_extraction import (
    build_adjudicator_prompt,
    build_extraction_prompt,
    build_extraction_prompt_strict_verify,
    compare_receipts,
    merge_agreed_receipts,
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


# --- Sprint 12.9 Task C: dual-pass extraction tests -----------------------


def _r(study_id: str = "s1", **kw: object) -> object:
    """Build an ExtractionReceipt via the parsed-dict path; tests
    override individual fields via kw. Universal helper — no biomedical
    literals beyond the rapamycin metric vocabulary kept consistent
    with the rest of the test file."""
    base: dict[str, object] = {
        "status": "extracted", "metric": "median_lifespan",
        "treated_value": 1000.0, "control_value": 900.0,
        "treated_n": 30, "control_n": 30,
        "evidence_quotes": ["The treated group survived 1000 days vs 900 days control."],
    }
    base.update(kw)
    return receipt_from_response(
        base, study_id=study_id, text_hash="h",
        reviewer="mimo-test", timestamp_utc="t",
    )


def test_strict_verify_prompt_appends_discipline_to_system_message() -> None:
    """Pass-B (strict-verify) keeps the Pass-A user message verbatim
    but appends a stricter system suffix instructing the model to
    reject any numeric not tied to a verbatim sentence."""
    pack = _pack()
    pass_a = build_extraction_prompt(pack, "s1", "Mock title", "Mouse text " * 200)
    pass_b = build_extraction_prompt_strict_verify(pack, "s1", "Mock title", "Mouse text " * 200)
    # User message identical (same field schema, same excerpt).
    assert pass_a[1]["content"] == pass_b[1]["content"]
    # System message DIVERGES — Pass-B has the strict-verify suffix.
    assert len(pass_b[0]["content"]) > len(pass_a[0]["content"])
    assert "STRICT-VERIFY MODE" in pass_b[0]["content"]


def test_compare_receipts_agreement_returns_empty_tuple() -> None:
    """Two passes returning the same pool-critical values agree
    (numerics within the 2% noise tolerance)."""
    a = _r(treated_value=1000.0, control_value=900.0)
    b = _r(treated_value=1005.0, control_value=895.0)  # <1% noise
    assert compare_receipts(a, b) == ()  # type: ignore[arg-type]


def test_compare_receipts_flags_numeric_disagreement() -> None:
    """Pool-critical numeric outside the tolerance band -> flagged."""
    a = _r(treated_value=1000.0)
    b = _r(treated_value=1500.0)  # 50% off
    assert "treated_value" in compare_receipts(a, b)  # type: ignore[arg-type]


def test_compare_receipts_flags_status_or_metric_change() -> None:
    """Status and metric are exact-match (case-insensitive). A pass
    that says 'no_numerics' while the other says 'extracted' is a
    poolable-state disagreement; the adjudicator must arbitrate."""
    a = _r(status="extracted")
    b = _r(status="no_numerics", treated_value=None, control_value=None)
    out = compare_receipts(a, b)  # type: ignore[arg-type]
    assert "status" in out


def test_merge_agreed_receipts_averages_numerics_and_unions_quotes() -> None:
    """When two passes agree (within noise), the merged receipt
    averages numerics, unions evidence quotes by casefold-dedup, and
    tags reviewer with the dual-pass provenance string."""
    a = _r(treated_value=1000.0, control_value=900.0,
           evidence_quotes=["The treated group survived 1000 days."])
    b = _r(treated_value=1004.0, control_value=898.0,
           evidence_quotes=["The TREATED group survived 1000 days.", "Methods: 30 mice per arm."])
    merged = merge_agreed_receipts(a, b, reviewer="mimo-dual-pass-agreed")  # type: ignore[arg-type]
    assert merged.reviewer == "mimo-dual-pass-agreed"
    assert merged.treated_value == 1002.0  # averaged
    assert merged.control_value == 899.0
    # Quotes unioned (casefold dedup; the duplicate "TREATED" form drops).
    assert len(merged.evidence_quotes) == 2


def test_adjudicator_prompt_lists_disagreements_and_pool_state() -> None:
    """The adjudicator system message names the two-pass disagreement
    inputs; the user message includes both pool dicts + disagreement
    diff + the excerpt. Universal — no biomedical literals required."""
    a = _r(treated_value=1000.0)
    b = _r(treated_value=1500.0)
    msgs = build_adjudicator_prompt(
        a, b, ("treated_value",),  # type: ignore[arg-type]
        "Excerpt body: the treated group survived 1000 days." * 5,
    )
    assert msgs[0]["role"] == "system"
    assert "adjudicator" in msgs[0]["content"].lower()
    assert "MAY NOT invent" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "Pass-A receipt" in user
    assert "Pass-B receipt" in user
    assert "treated_value" in user
    assert "1000.0" in user and "1500.0" in user


def test_compare_receipts_handles_one_null_one_value_as_disagreement() -> None:
    """If Pass-A found a value and Pass-B didn't, that's a disagreement
    — exactly the case where dual-pass rescues a parse_failed (one
    pass succeeds, the other doesn't, adjudicator picks the supported
    answer)."""
    a = _r(treated_value=1000.0)
    b = _r(treated_value=None)
    out = compare_receipts(a, b)  # type: ignore[arg-type]
    assert "treated_value" in out
