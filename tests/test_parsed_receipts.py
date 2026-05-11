"""ParsedFullTextReceipt + tightened eligibility validator tests.

Sprint 7 strictness: eligibility requires a parsed=True receipt, not just
a retrieved=True FullTextReceipt. ParsedFullText.to_receipt() shrinks the
heavy parsed document down to the slim audit-trail record.
"""
from __future__ import annotations

import pytest

from agent.evidence_state import EvidenceLinkError, EvidenceState
from agent.full_text_parse import ParsedFullText
from agent.retrieval.base import PaperHit
from agent.screening import (
    CandidateStudy,
    EligibilityReceipt,
    FullTextReceipt,
    ParsedFullTextReceipt,
    ScreeningReceipt,
    validate_eligibility_receipts,
    validate_parsed_receipts,
)


def _hit() -> PaperHit:
    return PaperHit(
        source="pubmed", title="t", abstract="", year=2020, url="u",
        doi="10.1/x", pmid="1", venue="J",
    )


def _scaffolding() -> tuple[
    tuple[PaperHit, ...], tuple[ScreeningReceipt, ...],
    tuple[CandidateStudy, ...], tuple[FullTextReceipt, ...],
]:
    h = _hit()
    sr = ScreeningReceipt(h.dedupe_key, "include", "title-abstract", "ok")
    cand = CandidateStudy(
        study_id="s1", hit_key=h.dedupe_key, title=h.title, year=h.year,
        venue=h.venue, doi=h.doi, pmid=h.pmid,
    )
    ftr = FullTextReceipt(study_id="s1", retrieved=True, source="PMC", reason="PMC123")
    return (h,), (sr,), (cand,), (ftr,)


def test_parsed_receipt_dataclass_is_frozen_and_immutable() -> None:
    r = ParsedFullTextReceipt(
        study_id="s1", source_url="u", parsed=True,
        text_hash="abc", char_count=42, failure_reason="",
    )
    with pytest.raises((AttributeError, TypeError)):
        r.parsed = False  # type: ignore[misc]


def test_parsed_receipt_minimal_construction_with_defaults() -> None:
    r = ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=False)
    assert r.text_hash == ""
    assert r.char_count == 0
    assert r.failure_reason == ""


def test_full_text_parse_to_receipt_round_trip() -> None:
    doc = ParsedFullText(
        study_id="s1", source_url="https://example.org/x", source_kind="html",
        text="abc body", char_count=8, sha256="hash-abc",
        fetched_at_utc="t", error="",
    )
    r = doc.to_receipt()
    assert isinstance(r, ParsedFullTextReceipt)
    assert r.parsed is True
    assert r.text_hash == "hash-abc"
    assert r.char_count == 8
    assert r.failure_reason == ""


def test_full_text_parse_to_receipt_marks_empty_text_unparsed() -> None:
    doc = ParsedFullText(
        study_id="s2", source_url="", source_kind="unsupported",
        text="", char_count=0, sha256="", fetched_at_utc="t",
        error="no open-access source",
    )
    r = doc.to_receipt()
    assert r.parsed is False
    assert r.failure_reason == "no open-access source"


def test_validate_parsed_receipts_rejects_unknown_study_id() -> None:
    _hits, _sr, cands, ftrs = _scaffolding()
    bad = ParsedFullTextReceipt(study_id="ghost", source_url="u", parsed=True)
    with pytest.raises(EvidenceLinkError, match="references unknown study_id"):
        validate_parsed_receipts(cands, ftrs, (bad,))


def test_validate_parsed_receipts_requires_full_text_located() -> None:
    _hits, _sr, cands, _ftrs = _scaffolding()
    not_located = FullTextReceipt(study_id="s1", retrieved=False, source="none", reason="")
    bad = ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=True)
    with pytest.raises(EvidenceLinkError, match="no full-text-located receipt"):
        validate_parsed_receipts(cands, (not_located,), (bad,))


def test_eligibility_validator_requires_parsed_receipt() -> None:
    _hits, _sr, cands, ftrs = _scaffolding()
    # FullTextReceipt(retrieved=True) but NO parsed receipt -> validator rejects
    parsed: tuple[ParsedFullTextReceipt, ...] = (
        ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=False, failure_reason="empty"),
    )
    elig = (EligibilityReceipt(study_id="s1", decision="include", reason="ok"),)
    with pytest.raises(EvidenceLinkError, match="parsed full-text receipt"):
        validate_eligibility_receipts(cands, ftrs, elig, parsed)


def test_eligibility_validator_passes_with_parsed_true() -> None:
    _hits, _sr, cands, ftrs = _scaffolding()
    parsed = (ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=True),)
    elig = (EligibilityReceipt(study_id="s1", decision="include", reason="ok"),)
    # No exception
    validate_eligibility_receipts(cands, ftrs, elig, parsed)


def test_evidence_state_promotes_through_parsed_to_eligible() -> None:
    hits, sr, cands, ftrs = _scaffolding()
    parsed = (ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=True, char_count=9000),)
    elig = (EligibilityReceipt(study_id="s1", decision="include", reason="meets PICO"),)
    state = EvidenceState.build(
        topic="t", hits=hits, receipts=sr, candidates=cands,
        full_text_receipts=ftrs, parsed_receipts=parsed,
        eligibility_receipts=elig,
    )
    assert state.k_full_text_retrieved == 1
    assert state.k_full_text_parsed == 1
    assert state.k_eligibility_included == 1
    assert state.k_eligible == 1
    assert state.candidates[0].screening_stage == "full_text_eligible"


def test_evidence_state_stops_at_parsed_when_no_eligibility_decision() -> None:
    hits, sr, cands, ftrs = _scaffolding()
    parsed = (ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=True),)
    state = EvidenceState.build(
        topic="t", hits=hits, receipts=sr, candidates=cands,
        full_text_receipts=ftrs, parsed_receipts=parsed,
    )
    assert state.candidates[0].screening_stage == "full_text_parsed"
    assert state.k_eligible == 0


def test_eligibility_breakdown_counters_match_decisions() -> None:
    hits, sr, cands, ftrs = _scaffolding()
    parsed = (ParsedFullTextReceipt(study_id="s1", source_url="u", parsed=True),)
    elig = (EligibilityReceipt(study_id="s1", decision="unclear", reason="conflict"),)
    state = EvidenceState.build(
        topic="t", hits=hits, receipts=sr, candidates=cands,
        full_text_receipts=ftrs, parsed_receipts=parsed,
        eligibility_receipts=elig,
    )
    assert state.k_eligibility_included == 0
    assert state.k_eligibility_excluded == 0
    assert state.k_eligibility_unclear == 1
