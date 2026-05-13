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
