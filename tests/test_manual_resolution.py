"""Sprint 7.10 - manual sentinel override tests."""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from agent.manual_resolution import (
    ManualResolutionReceipt,
    apply_manual_resolutions,
    load_manual_resolutions,
)
from agent.screening import CandidateStudy, EligibilityReceipt


def _cand(study_id: str, doi: str = "", pmid: str = "") -> CandidateStudy:
    return CandidateStudy(
        study_id=study_id, hit_key=study_id, title=f"title-{study_id}",
        year=2020, venue="J", doi=doi or None, pmid=pmid or None,
    )


def _receipt(study_id: str, decision: str = "exclude") -> EligibilityReceipt:
    return EligibilityReceipt(
        study_id=study_id, decision=decision,  # type: ignore[arg-type]
        reason="auto-judge: off-scope", reviewer="llm-judge",
        confidence=1.0, mandatory_fields=MappingProxyType({}),
    )


def test_load_returns_empty_when_no_resolutions_file(tmp_path: Path) -> None:
    assert load_manual_resolutions("nonexistent", pack_dir=tmp_path) == ()


def test_load_parses_topic_pack_resolutions(tmp_path: Path) -> None:
    (tmp_path / "t_manual_resolutions.toml").write_text(
        '[[resolutions]]\n'
        'doi = "10.1/x"\n'
        'pmid = "123"\n'
        'decision = "include"\n'
        'reason = "foundational"\n'
        'evidence_quote = "X extends lifespan"\n'
        'reviewer = "human-dom"\n',
        encoding="utf-8",
    )
    out = load_manual_resolutions("t", pack_dir=tmp_path)
    assert len(out) == 1
    r = out[0]
    assert r.doi == "10.1/x" and r.pmid == "123"
    assert r.decision == "include"
    assert r.reviewer == "human-dom"


def test_apply_overrides_auto_exclude_with_manual_include() -> None:
    cands = (_cand("s1", doi="10.1/x"),)
    receipts = (_receipt("s1", decision="exclude"),)
    res = (ManualResolutionReceipt(
        doi="10.1/x", pmid="", decision="include",
        reason="foundational", evidence_quote="X extends lifespan",
        reviewer="human-dom",
    ),)
    new, applied = apply_manual_resolutions(receipts, cands, res)
    assert new[0].decision == "include"
    assert new[0].reviewer == "human-dom"
    assert new[0].evidence_quotes == ("X extends lifespan",)
    assert applied == ("s1",)


def test_apply_matches_by_pmid_when_doi_missing() -> None:
    cands = (_cand("s1", pmid="123"),)
    receipts = (_receipt("s1", decision="unclear"),)
    res = (ManualResolutionReceipt(
        doi="", pmid="123", decision="include",
        reason="r", evidence_quote="q", reviewer="r",
    ),)
    new, applied = apply_manual_resolutions(receipts, cands, res)
    assert new[0].decision == "include"
    assert applied == ("s1",)


def test_apply_handles_unavailable_decision() -> None:
    cands = (_cand("s1", doi="10.1/m"),)
    receipts = (_receipt("s1", decision="exclude"),)
    res = (ManualResolutionReceipt(
        doi="10.1/m", pmid="", decision="unavailable",
        reason="paywalled-OA", evidence_quote="", reviewer="human-dom",
    ),)
    new, _ = apply_manual_resolutions(receipts, cands, res)
    assert new[0].decision == "unavailable"
    assert "unavailable" in new[0].reason


def test_apply_secondary_decision_maps_to_exclude_with_lane_reason() -> None:
    cands = (_cand("s1", doi="10.1/sec"),)
    receipts = (_receipt("s1", decision="include"),)
    res = (ManualResolutionReceipt(
        doi="10.1/sec", pmid="", decision="secondary",
        reason="proteomics analysis of lifespan cohort",
        evidence_quote="", reviewer="human-dom",
    ),)
    new, _ = apply_manual_resolutions(receipts, cands, res)
    assert new[0].decision == "exclude"
    assert "secondary" in new[0].reason


def test_apply_silently_skips_unmatched_resolutions() -> None:
    cands = (_cand("s1", doi="10.1/x"),)
    receipts = (_receipt("s1"),)
    res = (ManualResolutionReceipt(
        doi="10.1/missing", pmid="", decision="include",
        reason="r", evidence_quote="q", reviewer="r",
    ),)
    new, applied = apply_manual_resolutions(receipts, cands, res)
    assert new == receipts  # unchanged
    assert applied == ()


def test_apply_doi_match_is_case_insensitive() -> None:
    cands = (_cand("s1", doi="10.1038/NATURE08221"),)
    receipts = (_receipt("s1", decision="exclude"),)
    res = (ManualResolutionReceipt(
        doi="10.1038/nature08221", pmid="", decision="include",
        reason="r", evidence_quote="q", reviewer="r",
    ),)
    new, applied = apply_manual_resolutions(receipts, cands, res)
    assert new[0].decision == "include"
    assert applied == ("s1",)
