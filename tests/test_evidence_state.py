"""Evidence-spine tests: linking constraints across the whole chain.

Tests are written first; each constraint maps to exactly one validator
in agent.evidence_state.EvidenceState.build().
"""
from __future__ import annotations

import pytest

from agent.effect_sizes import EffectSizeRecord, ExtractedOutcome
from agent.evidence_state import EvidenceLinkError, EvidenceState
from agent.results_packets import ResultsPacket
from agent.retrieval.base import PaperHit
from agent.screening import CandidateStudy, ScreeningReceipt


def _hit(doi: str = "10.1/x") -> PaperHit:
    return PaperHit(
        source="pubmed",
        title="t",
        abstract="a",
        year=2020,
        url="u",
        doi=doi,
        pmid=None,
        venue=None,
    )


def _receipts_for(hit: PaperHit) -> tuple[ScreeningReceipt, ...]:
    return (
        ScreeningReceipt(hit_key=hit.dedupe_key, decision="include",
                          stage="title-abstract", reason="meets PICO"),
        ScreeningReceipt(hit_key=hit.dedupe_key, decision="include",
                          stage="full-text", reason="all data extractable"),
    )


def _candidate(hit: PaperHit, study_id: str = "s1") -> CandidateStudy:
    return CandidateStudy(
        study_id=study_id,
        hit_key=hit.dedupe_key,
        title=hit.title,
        year=hit.year,
        venue=hit.venue,
        pmid=hit.pmid,
        doi=hit.doi,
    )


def _outcome(study_id: str, outcome_id: str = "o1") -> ExtractedOutcome:
    return ExtractedOutcome(
        study_id=study_id,
        outcome_id=outcome_id,
        metric_name="median_lifespan_days",
        moderators={"sex": "female"},
        treated_value=1100.0,
        control_value=1000.0,
        raw_unit="days",
    )


def _effect(study_id: str, outcome_id: str = "o1") -> EffectSizeRecord:
    return EffectSizeRecord(
        study_id=study_id,
        outcome_id=outcome_id,
        metric="log_lifespan_ratio",
        estimate=0.0953,
        se=0.02,
        ci_low=0.05,
        ci_high=0.14,
        moderators={"sex": "female"},
    )


def _packet(effects: tuple[EffectSizeRecord, ...], packet_id: str = "primary-pooled") -> ResultsPacket:
    sources = tuple((e.study_id, e.outcome_id) for e in effects)
    studies = {sid for sid, _ in sources}
    return ResultsPacket(
        packet_id=packet_id,
        description="primary pooled estimate",
        k_studies=len(studies),
        k_effects=len(sources),
        metric="log_lifespan_ratio",
        moderator_levels={},
        source_effect_ids=sources,
        estimate=0.10,
        ci_low=0.05,
        ci_high=0.15,
    )


# ---------- happy path ------------------------------------------------------

def test_evidence_state_build_happy_path() -> None:
    h = _hit()
    receipts = _receipts_for(h)
    inc = _candidate(h)
    out = _outcome("s1")
    eff = _effect("s1")
    pkt = _packet((eff,))
    state = EvidenceState.build(
        topic="rapamycin",
        hits=(h,),
        receipts=receipts,
        candidates=(inc,),
        outcomes=(out,),
        effects=(eff,),
        packets=(pkt,),
    )
    assert state.topic == "rapamycin"
    assert state.k_hits == 1
    assert state.k_screened == 1
    assert state.k_candidates == 1
    assert state.k_outcomes == 1
    assert state.k_effects == 1
    assert state.k_packets == 1


def test_evidence_state_is_frozen() -> None:
    state = EvidenceState.build(topic="t")
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        state.topic = "mutated"  # type: ignore[misc]


# ---------- screening links -------------------------------------------------

def test_validate_screening_fires_on_unknown_hit_key() -> None:
    h = _hit()
    bad_receipt = ScreeningReceipt(
        hit_key="doi:does-not-exist", decision="include",
        stage="title-abstract", reason="ghost",
    )
    with pytest.raises(EvidenceLinkError, match="unknown hit_key"):
        EvidenceState.build(topic="t", hits=(h,), receipts=(bad_receipt,))


# ---------- included links --------------------------------------------------

def test_candidate_requires_at_least_one_include_receipt() -> None:
    h = _hit()
    # exclude-only receipt — no include of any stage
    receipts = (
        ScreeningReceipt(h.dedupe_key, "exclude", "title-abstract", "out of scope"),
    )
    inc = _candidate(h)
    with pytest.raises(EvidenceLinkError, match="no include screening receipt"):
        EvidenceState.build(topic="t", hits=(h,), receipts=receipts, candidates=(inc,))


def test_included_duplicate_study_id_rejected() -> None:
    h1, h2 = _hit("10.1/a"), _hit("10.1/b")
    receipts = _receipts_for(h1) + _receipts_for(h2)
    inc1 = _candidate(h1, "dup")
    inc2 = _candidate(h2, "dup")
    with pytest.raises(EvidenceLinkError, match=r"Duplicate CandidateStudy\.study_id"):
        EvidenceState.build(
            topic="t", hits=(h1, h2), receipts=receipts, candidates=(inc1, inc2)
        )


# ---------- outcome links ---------------------------------------------------

def test_outcome_must_reference_included_study() -> None:
    h = _hit()
    receipts = _receipts_for(h)
    inc = _candidate(h, "s1")
    ghost_outcome = _outcome("s-ghost")
    with pytest.raises(EvidenceLinkError, match="not in CandidateStudy"):
        EvidenceState.build(
            topic="t", hits=(h,), receipts=receipts, candidates=(inc,),
            outcomes=(ghost_outcome,),
        )


# ---------- effect links ----------------------------------------------------

def test_effect_must_reference_real_outcome() -> None:
    h = _hit()
    receipts = _receipts_for(h)
    inc = _candidate(h, "s1")
    out = _outcome("s1", "o1")
    ghost_effect = _effect("s1", "o-ghost")
    with pytest.raises(EvidenceLinkError, match="unknown outcome"):
        EvidenceState.build(
            topic="t", hits=(h,), receipts=receipts, candidates=(inc,),
            outcomes=(out,), effects=(ghost_effect,),
        )


# ---------- packet invariants -----------------------------------------------

def test_packet_must_have_at_least_one_source() -> None:
    with pytest.raises(EvidenceLinkError, match="cite at least one source"):
        ResultsPacket(
            packet_id="empty",
            description="x",
            k_studies=1,
            k_effects=1,
            metric="log_lifespan_ratio",
            moderator_levels={},
            source_effect_ids=(),
        )


def test_packet_must_declare_metric() -> None:
    with pytest.raises(EvidenceLinkError, match="must declare a metric"):
        ResultsPacket(
            packet_id="x", description="d", k_studies=1, k_effects=1,
            metric="", moderator_levels={},
            source_effect_ids=(("s1", "o1"),),
        )


def test_packet_k_studies_must_match_source_studies() -> None:
    with pytest.raises(EvidenceLinkError, match="k_studies"):
        ResultsPacket(
            packet_id="x", description="d", k_studies=99, k_effects=1,
            metric="log_lifespan_ratio", moderator_levels={},
            source_effect_ids=(("s1", "o1"),),
        )


def test_packet_must_cite_known_effects() -> None:
    h = _hit()
    receipts = _receipts_for(h)
    inc = _candidate(h, "s1")
    out = _outcome("s1")
    eff = _effect("s1")
    ghost_packet = ResultsPacket(
        packet_id="ghost", description="d", k_studies=1, k_effects=1,
        metric="log_lifespan_ratio", moderator_levels={},
        source_effect_ids=(("s1", "o-unknown"),),
    )
    with pytest.raises(EvidenceLinkError, match="cites unknown effect"):
        EvidenceState.build(
            topic="t", hits=(h,), receipts=receipts, candidates=(inc,),
            outcomes=(out,), effects=(eff,), packets=(ghost_packet,),
        )
