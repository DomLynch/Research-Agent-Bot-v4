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
    EligibilityReceipt,
    EvidenceLinkError,
    FullTextReceipt,
    ParsedFullTextReceipt,
    ScreeningReceipt,
    upgrade_candidate_stages,
    validate_candidates,
    validate_eligibility_receipts,
    validate_full_text_receipts,
    validate_parsed_receipts,
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
    full_text_receipts: tuple[FullTextReceipt, ...]
    parsed_receipts: tuple[ParsedFullTextReceipt, ...]
    eligibility_receipts: tuple[EligibilityReceipt, ...]
    outcomes: tuple[ExtractedOutcome, ...]
    effects: tuple[EffectSizeRecord, ...]
    packets: tuple[ResultsPacket, ...]

    @property
    def k_full_text_retrieved(self) -> int:
        return sum(1 for r in self.full_text_receipts if r.retrieved)

    @property
    def k_full_text_parsed(self) -> int:
        return sum(1 for r in self.parsed_receipts if r.parsed)

    @property
    def k_eligibility_included(self) -> int:
        return sum(1 for r in self.eligibility_receipts if r.decision == "include")

    @property
    def k_eligibility_excluded(self) -> int:
        return sum(1 for r in self.eligibility_receipts if r.decision == "exclude")

    @property
    def k_eligibility_unclear(self) -> int:
        return sum(1 for r in self.eligibility_receipts if r.decision == "unclear")

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
        full_text_receipts: tuple[FullTextReceipt, ...] = (),
        parsed_receipts: tuple[ParsedFullTextReceipt, ...] = (),
        eligibility_receipts: tuple[EligibilityReceipt, ...] = (),
        outcomes: tuple[ExtractedOutcome, ...] = (),
        effects: tuple[EffectSizeRecord, ...] = (),
        packets: tuple[ResultsPacket, ...] = (),
    ) -> EvidenceState:
        """Validate the whole chain in dependency order, upgrade candidate stages, freeze."""
        validate_screening(hits, receipts)
        validate_candidates(receipts, candidates)
        validate_full_text_receipts(candidates, full_text_receipts)
        validate_parsed_receipts(candidates, full_text_receipts, parsed_receipts)
        validate_eligibility_receipts(
            candidates, full_text_receipts, eligibility_receipts, parsed_receipts,
        )
        validate_outcomes(candidates, outcomes)
        validate_effects(outcomes, effects)
        validate_packets(effects, packets)
        upgraded = upgrade_candidate_stages(
            candidates,
            full_text_receipts,
            eligibility_receipts,
            frozenset(e.study_id for e in effects),
            parsed_receipts=parsed_receipts,
        )
        return cls(
            topic, hits, receipts, upgraded,
            full_text_receipts, parsed_receipts, eligibility_receipts,
            outcomes, effects, packets,
        )
