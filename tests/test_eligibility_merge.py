"""Eligibility Pass-3 deterministic-merge tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.eligibility_judge import EligibilityProposal
from agent.eligibility_merge import CONF_FLOOR, adjudicate
from agent.eligibility_rules import EligibilityTriage, TriageLabel
from agent.full_text_parse import ParsedFullText


def _parsed(text: str = "x") -> ParsedFullText:
    return ParsedFullText(
        study_id="s1", source_url="u", source_kind="pmc-xml",
        text=text, char_count=len(text), sha256="hash-abc",
        fetched_at_utc="2026-05-11T00:00:00+00:00",
    )


def _triage(label: TriageLabel, fields: dict[str, bool] | None = None) -> EligibilityTriage:
    default = {
        "species_match": True, "intervention_match": True,
        "endpoint_present": True, "control_present": True,
        "primary_research_design": True, "rapalog_only_intervention": False,
        "parsed_text_adequate": True,
    }
    if fields:
        default.update(fields)
    return EligibilityTriage(
        study_id="s1", label=label,
        mandatory_fields=MappingProxyType(default), reasons=("baseline",),
    )


def _proposal(
    decision: str = "include", confidence: float = 0.9,
    fields: dict[str, bool] | None = None, parse_error: str = "",
    reasons: tuple[str, ...] = (),
) -> EligibilityProposal:
    default = {
        "species_match": True, "intervention_match": True,
        "endpoint_present": True, "control_present": True,
        "primary_research_design": True, "rapalog_only_intervention": False,
        "combination_only_no_isolated_arm": False,
    }
    if fields:
        default.update(fields)
    return EligibilityProposal(
        study_id="s1", decision=decision,  # type: ignore[arg-type]
        confidence=confidence, reasons=reasons or ("ok",),
        evidence_quotes=("verbatim",),
        eligibility_fields=MappingProxyType(default),
        model="m", raw_response="raw",
        parse_error=parse_error,
    )


def test_include_when_all_conditions_pass() -> None:
    r = adjudicate(_triage("eligible_likely"), _proposal(), _parsed())
    assert r.decision == "include"
    assert r.reviewer == "llm-judge"
    assert r.confidence == 0.9
    assert r.rule_decision == "eligible_likely"
    assert r.source_text_hash == "hash-abc"
    assert r.timestamp_utc
    assert r.evidence_quotes == ("verbatim",)


def test_triage_exclude_overrides_judge_include() -> None:
    r = adjudicate(_triage("exclude_likely"), _proposal(decision="include"), _parsed())
    assert r.decision == "exclude"
    assert r.reviewer == "rule-triage"
    assert "Pass-1 hard excluder" in r.reason


def test_rapalog_only_flag_excludes_even_on_judge_include() -> None:
    r = adjudicate(
        _triage("unclear", fields={"rapalog_only_intervention": True}),
        _proposal(),
        _parsed(),
    )
    assert r.decision == "exclude"
    assert "rapalog-only" in r.reason


def test_combination_only_flag_from_judge_excludes() -> None:
    r = adjudicate(
        _triage("unclear"),
        _proposal(fields={"combination_only_no_isolated_arm": True}),
        _parsed(),
    )
    assert r.decision == "exclude"
    assert "combination-only" in r.reason


def test_low_confidence_yields_unclear() -> None:
    r = adjudicate(_triage("eligible_likely"), _proposal(confidence=0.5), _parsed())
    assert r.decision == "unclear"
    assert "low judge confidence" in r.reason


def test_or_merge_unclear_only_when_both_rule_and_judge_miss_field() -> None:
    # Sprint 7.7: rule says True (title scan), judge says False (abstract
    # framing fooled it) - OR-merge keeps True. The Harrison-2009 rescue.
    r = adjudicate(
        _triage("eligible_likely"),
        _proposal(fields={"endpoint_present": False}),
        _parsed(),
    )
    assert r.decision == "include", "rule positive should override judge negative"


def test_missing_mandatory_field_yields_unclear_when_neither_finds_it() -> None:
    # Both rule AND judge miss endpoint_present -> unclear is correct.
    triage_no_endpoint = _triage(
        "unclear", fields={"endpoint_present": False},
    )
    r = adjudicate(
        triage_no_endpoint,
        _proposal(fields={"endpoint_present": False}),
        _parsed(),
    )
    assert r.decision == "unclear"
    assert "endpoint_present" in r.reason


def test_judge_exclude_with_high_confidence_excludes() -> None:
    r = adjudicate(
        _triage("unclear"),
        _proposal(decision="exclude", confidence=0.85, reasons=("not lifespan",)),
        _parsed(),
    )
    assert r.decision == "exclude"
    assert "not lifespan" in r.reason
    assert r.reviewer == "llm-judge"


def test_proposal_parse_error_falls_back_to_unclear() -> None:
    r = adjudicate(
        _triage("eligible_likely"),
        _proposal(parse_error="json parse failed", confidence=0.0),
        _parsed(),
    )
    assert r.decision == "unclear"
    assert "json parse failed" in r.reason
    assert r.reviewer == "rule-triage"


def test_audit_trail_carries_judge_and_rule_info() -> None:
    r = adjudicate(
        _triage("eligible_likely"),
        _proposal(),
        _parsed(),
    )
    assert r.judge_model == "m"
    assert r.rule_decision == "eligible_likely"
    assert dict(r.mandatory_fields)["species_match"] is True


def test_conf_floor_constant_is_documented_threshold() -> None:
    assert CONF_FLOOR == 0.75
