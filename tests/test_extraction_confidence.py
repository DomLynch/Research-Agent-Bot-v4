"""Sprint 19 — extraction confidence tests.

Locks the provenance-tag → confidence mapping and the
needs_human_audit threshold. Universal: every fixture uses generic
field shapes; no biomedical literals.
"""
from __future__ import annotations

from types import MappingProxyType

from agent.effect_extraction import ExtractionReceipt
from agent.extraction_confidence import (
    ExtractionConfidenceReport,
    score_extractions,
)


def _receipt(study_id: str, *, status: str, reviewer: str) -> ExtractionReceipt:
    return ExtractionReceipt(
        study_id=study_id, status=status,  # type: ignore[arg-type]
        metric="primary_endpoint",
        treated_value=1.0, control_value=1.0,
        treated_n=10, control_n=10,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=None,
        moderators=MappingProxyType({}),
        evidence_quotes=(), failure_reason="",
        reviewer=reviewer, text_hash="hash", timestamp_utc="2026-05-13T00:00:00Z",
    )


def test_dual_pass_agreed_scores_one() -> None:
    r = _receipt("s01", status="extracted", reviewer="mimo-dual-pass-agreed:m")
    rep = score_extractions([r])
    e = rep.entries[0]
    assert e.confidence == 1.0
    assert e.needs_human_audit is False
    assert "agreed" in e.reason.lower()


def test_dual_pass_adjudicated_scores_seven_tenths() -> None:
    r = _receipt(
        "s02", status="extracted",
        reviewer="mimo-dual-pass-adjudicated:gemma;disagreements=metric",
    )
    rep = score_extractions([r])
    assert rep.entries[0].confidence == 0.7
    assert rep.entries[0].needs_human_audit is False  # 0.7 >= 0.6


def test_adjudicator_failed_scores_below_threshold_and_flags_audit() -> None:
    r = _receipt(
        "s03", status="extracted",
        reviewer="mimo-dual-pass-adjudicator-failed;disagreements=hazard_ratio",
    )
    rep = score_extractions([r])
    assert rep.entries[0].confidence == 0.3
    assert rep.entries[0].needs_human_audit is True


def test_pass_b_failed_flags_audit() -> None:
    r = _receipt("s04", status="extracted",
                 reviewer="mimo-dual-pass-pass-b-failed")
    rep = score_extractions([r])
    assert rep.entries[0].confidence == 0.4
    assert rep.entries[0].needs_human_audit is True


def test_non_extracted_status_scores_zero() -> None:
    """no_numerics / parse_failed / llm_refused → confidence = 0 → audit."""
    for status in ("no_numerics", "parse_failed", "llm_refused"):
        r = _receipt("s05", status=status, reviewer="mimo-dual-pass-agreed:m")
        rep = score_extractions([r])
        assert rep.entries[0].confidence == 0.0
        assert rep.entries[0].needs_human_audit is True
        assert status in rep.entries[0].reason


def test_unknown_reviewer_tag_scores_moderate() -> None:
    """Receipts with no recognised dual-pass provenance (e.g. single-pass
    fallback) default to 0.5 — below audit threshold by design."""
    r = _receipt("s06", status="extracted", reviewer="mimo-only-primary:m")
    rep = score_extractions([r])
    assert rep.entries[0].confidence == 0.5
    assert rep.entries[0].needs_human_audit is True


def test_aggregate_report_counts_and_mean() -> None:
    rep = score_extractions([
        _receipt("a", status="extracted", reviewer="mimo-dual-pass-agreed"),
        _receipt("b", status="extracted", reviewer="mimo-dual-pass-adjudicated"),
        _receipt("c", status="no_numerics", reviewer=""),
    ])
    assert rep.k_total == 3
    # a=1.0, b=0.7, c=0.0 → mean = 0.566..
    assert abs(rep.mean_confidence - (1.0 + 0.7 + 0.0) / 3) < 1e-9
    assert rep.k_needs_audit == 1  # only c flags audit


def test_as_dict_round_trips_for_json_serialization() -> None:
    import json
    rep = score_extractions([
        _receipt("a", status="extracted", reviewer="mimo-dual-pass-agreed"),
    ])
    d = rep.as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["k_total"] == 1
    assert d["audit_threshold"] == 0.6


def test_empty_input_returns_empty_report() -> None:
    rep = score_extractions([])
    assert isinstance(rep, ExtractionConfidenceReport)
    assert rep.k_total == 0
    assert rep.k_needs_audit == 0
    assert rep.mean_confidence == 0.0


def test_scoring_universal_for_non_biomedical_topic() -> None:
    """Same provenance mapping; topic-agnostic study IDs."""
    rep = score_extractions([
        _receipt("city-stockholm-2022", status="extracted",
                 reviewer="mimo-dual-pass-agreed"),
        _receipt("country-norway-2019", status="extracted",
                 reviewer="mimo-dual-pass-adjudicator-failed"),
    ])
    assert rep.entries[0].confidence == 1.0
    assert rep.entries[1].confidence == 0.3
    assert rep.k_needs_audit == 1
