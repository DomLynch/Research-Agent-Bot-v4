"""Sprint 27 — dual-agent extraction audit tests.

Locks the reviewer-tag → status mapping for every dual-pass provenance
shape the orchestrator emits. Universal: every fixture uses generic
study IDs; no domain literals.
"""
from __future__ import annotations

from types import MappingProxyType

from agent.dual_agent_audit import (
    DualAgentAuditReport,
    _parse_reviewer,
    audit_extractions,
)
from agent.effect_extraction import ExtractionReceipt


def _receipt(study_id: str, *, status: str, reviewer: str) -> ExtractionReceipt:
    return ExtractionReceipt(
        study_id=study_id, status=status,  # type: ignore[arg-type]
        metric="m", treated_value=1.0, control_value=1.0,
        treated_n=10, control_n=10,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=None,
        moderators=MappingProxyType({}),
        evidence_quotes=(), failure_reason="",
        reviewer=reviewer, text_hash="h", timestamp_utc="t",
    )


def test_parse_reviewer_recognises_dual_pass_agreed() -> None:
    status, a, b, disagreed = _parse_reviewer("mimo-dual-pass-agreed:gemma-4-31b-it")
    assert status == "agent_agreed"
    assert a == "mimo"
    assert b == "gemma-4-31b-it"
    assert disagreed == ()


def test_parse_reviewer_recognises_adjudicated_with_disagreed_fields() -> None:
    status, a, b, disagreed = _parse_reviewer(
        "mimo-dual-pass-adjudicated:claude;disagreements=metric,treated_n"
    )
    assert status == "agent_adjudicated"
    assert a == "mimo"
    assert b == "claude"
    assert set(disagreed) == {"metric", "treated_n"}


def test_parse_reviewer_recognises_adjudicator_failed() -> None:
    status, _, _, disagreed = _parse_reviewer(
        "mimo-dual-pass-adjudicator-failed;disagreements=hazard_ratio"
    )
    assert status == "agent_disputed"
    assert disagreed == ("hazard_ratio",)


def test_parse_reviewer_adjudicated_carries_pass_b_model_id_not_adjudicator() -> None:
    """Sprint 30: the `:model` slot in the adjudicated tag is Pass-B's
    Gemma model id (so extractor_b attribution is correct). The
    adjudicator's model lives in a separate `;adjudicator=` segment."""
    status, ext_a, ext_b, disagreed = _parse_reviewer(
        "mimo-dual-pass-adjudicated:google/gemma-4-31b-it;"
        "adjudicator=mimo-v2.5-pro;disagreements=treated_n,control_n"
    )
    assert status == "agent_adjudicated"
    assert ext_a == "mimo"
    assert ext_b == "google/gemma-4-31b-it"  # Pass-B, NOT adjudicator
    assert set(disagreed) == {"treated_n", "control_n"}


def test_parse_reviewer_adjudicator_failed_carries_pass_b_model_id() -> None:
    """Sprint 30: same fidelity on the adjudicator-failed path — Pass-B's
    model survives in the `:model` slot even when the adjudicator dies."""
    status, ext_a, ext_b, disagreed = _parse_reviewer(
        "mimo-dual-pass-adjudicator-failed:google/gemma-4-31b-it;"
        "disagreements=metric"
    )
    assert status == "agent_disputed"
    assert ext_a == "mimo"
    assert ext_b == "google/gemma-4-31b-it"
    assert disagreed == ("metric",)


def test_parse_reviewer_recognises_pass_b_failed() -> None:
    status, a, b, _ = _parse_reviewer("mimo-dual-pass-pass-b-failed")
    assert status == "pass_b_failed"
    assert a == "mimo"
    assert b is None


def test_parse_reviewer_recognises_single_pass_legacy() -> None:
    status, a, b, _ = _parse_reviewer("mimo:mimo-v2.5-pro")
    assert status == "single_pass"
    assert a == "mimo-v2.5-pro"
    assert b is None


def test_parse_reviewer_recognises_placeholder() -> None:
    status, a, b, _ = _parse_reviewer("extract-cli")
    assert status == "placeholder"
    assert a is None and b is None


def test_parse_reviewer_unknown_returns_unknown_status() -> None:
    status, a, b, _ = _parse_reviewer("some-other-string")
    assert status == "unknown"
    assert a is None and b is None


def test_audit_full_agreement_marks_every_pool_field_true() -> None:
    r = _receipt("s01", status="extracted",
                 reviewer="mimo-dual-pass-agreed:gemma-4-31b-it")
    rep = audit_extractions([r])
    e = rep.entries[0]
    assert e.status == "agent_agreed"
    assert all(agreed for _, agreed in e.field_agreement)
    assert e.confidence_score == 1.0
    assert e.blocking_flags == ()


def test_audit_adjudicated_marks_only_disagreed_fields_false() -> None:
    r = _receipt(
        "s02", status="extracted",
        reviewer="mimo-dual-pass-adjudicated:gemma;disagreements=metric,treated_n",
    )
    rep = audit_extractions([r])
    by_field = dict(rep.entries[0].field_agreement)
    assert by_field["metric"] is False
    assert by_field["treated_n"] is False
    # All other pool-critical fields stay True.
    assert by_field["status"] is True
    assert by_field["treated_value"] is True
    assert by_field["hazard_ratio"] is True


def test_audit_single_pass_marks_no_agreement_and_flags_blocking() -> None:
    r = _receipt("s03", status="extracted", reviewer="mimo:mimo-v2.5-pro")
    rep = audit_extractions([r])
    e = rep.entries[0]
    assert e.status == "single_pass"
    assert all(not agreed for _, agreed in e.field_agreement)
    assert "no_dual_agent_review" in e.blocking_flags


def test_audit_placeholder_status_flags_extraction_failure() -> None:
    r = _receipt("s04", status="parse_failed", reviewer="extract-cli")
    rep = audit_extractions([r])
    e = rep.entries[0]
    assert e.status == "placeholder"
    assert any("extraction_status=parse_failed" in f for f in e.blocking_flags)


def test_audit_report_aggregate_counts_and_as_dict() -> None:
    rep = audit_extractions([
        _receipt("a", status="extracted",
                 reviewer="mimo-dual-pass-agreed:gemma"),
        _receipt("b", status="extracted",
                 reviewer="mimo-dual-pass-adjudicated:gemma;disagreements=metric"),
        _receipt("c", status="extracted", reviewer="mimo:mimo-v2.5-pro"),
        _receipt("d", status="parse_failed", reviewer="extract-cli"),
    ])
    assert isinstance(rep, DualAgentAuditReport)
    assert rep.k_total == 4
    assert rep.k_agent_agreed == 1
    assert rep.k_agent_adjudicated == 1
    assert rep.k_single_pass == 1
    # Both single_pass + placeholder produce blocking flags.
    assert rep.k_blocking == 2
    import json
    d = rep.as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["audit_threshold"] == 0.6


def test_audit_handles_empty_input() -> None:
    rep = audit_extractions([])
    assert rep.k_total == 0
    assert rep.entries == ()


def test_audit_universal_for_non_biomedical_topic() -> None:
    """Climate/finance study IDs round-trip cleanly — no biomedical
    vocabulary in the reviewer-parser logic."""
    rep = audit_extractions([
        _receipt("city-stockholm-2022", status="extracted",
                 reviewer="mimo-dual-pass-agreed:gemma"),
        _receipt("fred-fedfunds-1955", status="extracted",
                 reviewer="mimo-dual-pass-adjudicator-failed;disagreements=treated_value"),
    ])
    assert rep.k_agent_agreed == 1
    assert rep.entries[1].status == "agent_disputed"
