"""Sprint 20 — manual_audit overlay tests.

Covers parser robustness + the two accessor methods downstream layers
consult. Universal: generic study/sentinel ids; no domain literals.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.manual_audit import (
    ManualAuditEntry,
    ManualAuditOverlay,
    load_manual_audit,
)


def _write(p: Path, payload: object) -> None:
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_missing_file_returns_empty_overlay(tmp_path: Path) -> None:
    o = load_manual_audit(tmp_path)
    assert isinstance(o, ManualAuditOverlay)
    assert o.k_total == 0
    assert o.approved_extractions() == frozenset()
    assert o.resolved_sentinels() == frozenset()


def test_malformed_json_returns_empty_overlay(tmp_path: Path) -> None:
    (tmp_path / "manual_audit.json").write_text("not json", encoding="utf-8")
    assert load_manual_audit(tmp_path).k_total == 0


def test_loads_well_formed_extraction_approval(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "s01", "action": "approve",
         "reviewer": "dl", "notes": "table 2 cross-checked"},
    ]})
    o = load_manual_audit(tmp_path)
    assert o.k_total == 1
    assert o.approved_extractions() == frozenset({"s01"})
    e = o.entries[0]
    assert e.target_id == "s01"
    assert e.kind == "extraction"
    assert e.action == "approve"
    assert e.notes == "table 2 cross-checked"


def test_loads_sentinel_action_with_correct_kind_and_id(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "sentinel", "sentinel_id": "10.1/x", "action": "uploaded",
         "reviewer": "dl", "notes": "PDF added via crossref"},
    ]})
    o = load_manual_audit(tmp_path)
    assert o.resolved_sentinels() == frozenset({"10.1/x"})


def test_rejects_unknown_kind_and_action(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "s01", "action": "bogus"},
        {"kind": "other", "study_id": "s02", "action": "approve"},
        {"kind": "sentinel", "sentinel_id": "10.1/x", "action": "approve"},  # wrong action set
    ]})
    o = load_manual_audit(tmp_path)
    assert o.k_total == 0


def test_rejects_entries_missing_required_fields(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "action": "approve"},        # no study_id
        {"kind": "extraction", "study_id": "s01"},          # no action
        {"kind": "sentinel", "action": "uploaded"},          # no sentinel_id
    ]})
    o = load_manual_audit(tmp_path)
    assert o.k_total == 0


def test_mixed_valid_and_invalid_keeps_only_valid(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "s01", "action": "approve"},
        {"kind": "garbage"},
        {"kind": "sentinel", "sentinel_id": "10.1/x", "action": "uploaded"},
    ]})
    o = load_manual_audit(tmp_path)
    assert o.k_total == 2


def test_overlay_handles_non_dict_root(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", [1, 2, 3])
    assert load_manual_audit(tmp_path).k_total == 0


def test_overlay_supports_multiple_extraction_approvals(tmp_path: Path) -> None:
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "s01", "action": "approve"},
        {"kind": "extraction", "study_id": "s02", "action": "approve"},
        {"kind": "extraction", "study_id": "s03", "action": "reject"},
    ]})
    o = load_manual_audit(tmp_path)
    assert o.approved_extractions() == frozenset({"s01", "s02"})
    # rejected entries are recorded but not in approved set
    assert any(e.action == "reject" and e.target_id == "s03" for e in o.entries)


def test_overlay_universal_for_non_biomedical_ids(tmp_path: Path) -> None:
    """Climate / finance ids round-trip just fine — no domain coupling."""
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "city-stockholm-2022",
         "action": "approve", "reviewer": "policy-dl"},
        {"kind": "sentinel", "sentinel_id": "fred-fedfunds-1955",
         "action": "deferred", "reviewer": "policy-dl"},
    ]})
    o = load_manual_audit(tmp_path)
    assert o.approved_extractions() == frozenset({"city-stockholm-2022"})
    assert o.resolved_sentinels() == frozenset({"fred-fedfunds-1955"})


def test_entry_dataclass_is_frozen() -> None:
    e = ManualAuditEntry(
        kind="extraction", target_id="s01", action="approve",
        reviewer="dl", notes="",
    )
    import dataclasses
    assert dataclasses.is_dataclass(e)
    try:
        e.action = "reject"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ManualAuditEntry should be immutable")


# -----------------------------------------------------------------------------
# Integration: overlay clears flags in Sprint 18 + Sprint 19 sidecars.
# -----------------------------------------------------------------------------


def test_overlay_clears_extraction_audit_flag(tmp_path: Path) -> None:
    """When the overlay approves a low-confidence extraction, the
    Sprint 19 score_extractions() reports needs_human_audit=False."""
    from types import MappingProxyType

    from agent.effect_extraction import ExtractionReceipt
    from agent.extraction_confidence import score_extractions

    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "extraction", "study_id": "s01", "action": "approve",
         "reviewer": "dl"},
    ]})
    overlay = load_manual_audit(tmp_path)
    r = ExtractionReceipt(
        study_id="s01", status="extracted", metric="m",
        treated_value=1.0, control_value=1.0, treated_n=10, control_n=10,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=None, moderators=MappingProxyType({}),
        evidence_quotes=(), failure_reason="",
        reviewer="mimo-dual-pass-adjudicator-failed",  # 0.3 confidence
        text_hash="h", timestamp_utc="t",
    )
    # Without overlay → flagged.
    rep_no = score_extractions([r])
    assert rep_no.entries[0].needs_human_audit is True
    # With overlay approval → cleared.
    rep_yes = score_extractions([r], audit_approved=overlay.approved_extractions())
    assert rep_yes.entries[0].needs_human_audit is False
    # Confidence value itself is unchanged — provenance is the truth.
    assert rep_yes.entries[0].confidence == 0.3


def test_overlay_clears_sentinel_repair_entry(tmp_path: Path) -> None:
    """When the overlay records a sentinel action, the Sprint 18
    repair plan no longer lists that sentinel."""
    from types import MappingProxyType

    from agent.sentinel_recall import SentinelRecallReceipt, SentinelStatus
    from agent.sentinel_repair import compute_repair_plan
    from agent.topic_pack import TopicPack

    pack = TopicPack(
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
    )
    r = SentinelRecallReceipt(
        statuses=(
            SentinelStatus("10.1/uploaded", "primary", False, False, "not_retrieved"),
            SentinelStatus("10.2/open", "primary", False, False, "not_retrieved"),
        ),
        expected_primary=2, expected_prior_meta=0,
        retrieved_primary=0, retrieved_prior_meta=0,
        candidate_primary=0, candidate_prior_meta=0, included_primary=0,
    )
    _write(tmp_path / "manual_audit.json", {"audits": [
        {"kind": "sentinel", "sentinel_id": "10.1/uploaded",
         "action": "uploaded", "reviewer": "dl"},
    ]})
    overlay = load_manual_audit(tmp_path)
    plan_no = compute_repair_plan(r, pack)
    assert plan_no.k_repair_needed == 2
    plan_yes = compute_repair_plan(r, pack, audit_resolved=overlay.resolved_sentinels())
    assert plan_yes.k_repair_needed == 1
    assert plan_yes.entries[0].sentinel_id == "10.2/open"
