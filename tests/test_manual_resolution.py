"""Sprint 7.11.1 - manual sentinel-status overlay tests.

Manuals are status-only: they cannot create primary inclusion. The
overlay is consumed by the sentinel-recall gate (informational) and by
freeze_primary_set (resolved_excluded subtracts from primary corpus)."""
from __future__ import annotations

from pathlib import Path

from agent.manual_resolution import (
    ManualResolutionReceipt,
    build_manual_status_overlay,
    load_manual_resolutions,
)
from agent.screening import CandidateStudy


def _cand(study_id: str, doi: str = "", pmid: str = "") -> CandidateStudy:
    return CandidateStudy(
        study_id=study_id, hit_key=study_id, title=f"title-{study_id}",
        year=2020, venue="J", doi=doi or None, pmid=pmid or None,
    )


def test_load_returns_empty_when_no_resolutions_file(tmp_path: Path) -> None:
    assert load_manual_resolutions("nonexistent", pack_dir=tmp_path) == ()


def test_load_parses_topic_pack_resolutions(tmp_path: Path) -> None:
    (tmp_path / "t_manual_resolutions.toml").write_text(
        '[[resolutions]]\n'
        'doi = "10.1/x"\n'
        'pmid = "123"\n'
        'status = "resolved_available"\n'
        'reason = "foundational"\n'
        'evidence_quote = "X extends lifespan"\n'
        'reviewer = "human-dom"\n'
        'action_required = "wire OA mirror"\n',
        encoding="utf-8",
    )
    out = load_manual_resolutions("t", pack_dir=tmp_path)
    assert len(out) == 1
    r = out[0]
    assert r.doi == "10.1/x" and r.pmid == "123"
    assert r.status == "resolved_available"
    assert r.reviewer == "human-dom"
    assert r.action_required == "wire OA mirror"


def test_load_rejects_invalid_status(tmp_path: Path) -> None:
    (tmp_path / "t_manual_resolutions.toml").write_text(
        '[[resolutions]]\n'
        'doi = "10.1/x"\n'
        'status = "include"\n'  # invalid - manuals cannot include
        'reason = "r"\n'
        'evidence_quote = ""\n'
        'reviewer = "r"\n',
        encoding="utf-8",
    )
    try:
        load_manual_resolutions("t", pack_dir=tmp_path)
    except ValueError as e:
        assert "include" in str(e)
        return
    raise AssertionError("expected ValueError for invalid status")


def test_overlay_indexes_by_study_id_via_doi() -> None:
    cands = (_cand("s1", doi="10.1/x"), _cand("s2", doi="10.1/y"))
    res = (ManualResolutionReceipt(
        doi="10.1/x", pmid="", status="resolved_available",
        reason="r", evidence_quote="q", reviewer="human-dom",
    ),)
    overlay = build_manual_status_overlay(res, cands)
    assert set(overlay) == {"s1"}
    assert overlay["s1"].status == "resolved_available"


def test_overlay_matches_by_pmid_when_doi_missing() -> None:
    cands = (_cand("s1", pmid="123"),)
    res = (ManualResolutionReceipt(
        doi="", pmid="123", status="resolved_unavailable",
        reason="r", evidence_quote="", reviewer="human-dom",
    ),)
    overlay = build_manual_status_overlay(res, cands)
    assert overlay["s1"].status == "resolved_unavailable"


def test_overlay_silently_skips_unmatched_resolutions() -> None:
    cands = (_cand("s1", doi="10.1/x"),)
    res = (ManualResolutionReceipt(
        doi="10.1/missing", pmid="", status="resolved_available",
        reason="r", evidence_quote="q", reviewer="human-dom",
    ),)
    overlay = build_manual_status_overlay(res, cands)
    assert overlay == {}


def test_overlay_doi_match_is_case_insensitive() -> None:
    cands = (_cand("s1", doi="10.1038/NATURE08221"),)
    res = (ManualResolutionReceipt(
        doi="10.1038/nature08221", pmid="", status="resolved_available",
        reason="r", evidence_quote="q", reviewer="human-dom",
    ),)
    overlay = build_manual_status_overlay(res, cands)
    assert "s1" in overlay


def test_overlay_supports_all_four_statuses() -> None:
    cands = (
        _cand("s1", doi="10.1/a"),
        _cand("s2", doi="10.1/b"),
        _cand("s3", doi="10.1/c"),
        _cand("s4", doi="10.1/d"),
    )
    res = (
        ManualResolutionReceipt(
            doi="10.1/a", pmid="", status="resolved_available",
            reason="r", evidence_quote="", reviewer="r"),
        ManualResolutionReceipt(
            doi="10.1/b", pmid="", status="resolved_unavailable",
            reason="r", evidence_quote="", reviewer="r"),
        ManualResolutionReceipt(
            doi="10.1/c", pmid="", status="resolved_excluded",
            reason="r", evidence_quote="", reviewer="r"),
        ManualResolutionReceipt(
            doi="10.1/d", pmid="", status="needs_review",
            reason="r", evidence_quote="", reviewer="r"),
    )
    overlay = build_manual_status_overlay(res, cands)
    assert {overlay[k].status for k in overlay} == {
        "resolved_available", "resolved_unavailable",
        "resolved_excluded", "needs_review",
    }
