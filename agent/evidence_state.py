"""Frozen `EvidenceState` — the single source of truth.

Holds every record in the evidence chain (hits, screening receipts,
candidate studies, extracted outcomes, effect-size records, results
packets). `EvidenceState.build()` validates every link and returns an
immutable container. Downstream code reads the container; no other module
may mint receipts or packets.

`k_candidates` counts every CandidateStudy regardless of stage.
`k_eligible` counts only candidates with stage `full_text_eligible`
or `effect_extractable` — these are the studies that can legitimately
be described as "included" in the meta-analysis.

Universal: this module is domain-agnostic. Topic packs supply the
moderator vocabulary; the records themselves carry only stable identifiers
and free-form values.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.effect_sizes import (
    EffectSizeRecord,
    ExtractedOutcome,
    validate_effects,
    validate_outcomes,
)
from agent.results_packets import ResultsPacket, validate_packets
from agent.retrieval.base import PaperHit
from agent.screening import (
    CandidateStudy,
    EvidenceLinkError,
    ScreeningReceipt,
    validate_candidates,
    validate_screening,
)

__all__ = [
    "EvidenceLinkError",
    "EvidenceState",
]


@dataclass(frozen=True, slots=True)
class EvidenceState:
    topic: str
    hits: tuple[PaperHit, ...]
    receipts: tuple[ScreeningReceipt, ...]
    candidates: tuple[CandidateStudy, ...]
    outcomes: tuple[ExtractedOutcome, ...]
    effects: tuple[EffectSizeRecord, ...]
    packets: tuple[ResultsPacket, ...]

    @property
    def k_hits(self) -> int:
        return len(self.hits)

    @property
    def k_screened(self) -> int:
        return len({r.hit_key for r in self.receipts})

    @property
    def k_candidates(self) -> int:
        return len(self.candidates)

    @property
    def k_eligible(self) -> int:
        return sum(1 for s in self.candidates if s.is_eligible)

    @property
    def eligible_studies(self) -> tuple[CandidateStudy, ...]:
        return tuple(s for s in self.candidates if s.is_eligible)

    @property
    def k_outcomes(self) -> int:
        return len(self.outcomes)

    @property
    def k_effects(self) -> int:
        return len(self.effects)

    @property
    def k_packets(self) -> int:
        return len(self.packets)

    @classmethod
    def build(
        cls,
        *,
        topic: str,
        hits: tuple[PaperHit, ...] = (),
        receipts: tuple[ScreeningReceipt, ...] = (),
        candidates: tuple[CandidateStudy, ...] = (),
        outcomes: tuple[ExtractedOutcome, ...] = (),
        effects: tuple[EffectSizeRecord, ...] = (),
        packets: tuple[ResultsPacket, ...] = (),
    ) -> EvidenceState:
        """Validate the whole chain in dependency order, then freeze."""
        validate_screening(hits, receipts)
        validate_candidates(receipts, candidates)
        validate_outcomes(candidates, outcomes)
        validate_effects(outcomes, effects)
        validate_packets(effects, packets)
        return cls(topic, hits, receipts, candidates, outcomes, effects, packets)
