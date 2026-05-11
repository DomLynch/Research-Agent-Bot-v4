"""Frozen `EvidenceState` — the single source of truth.

Holds every record in the evidence chain (hits, screening receipts,
included studies, extracted outcomes, effect-size records, results
packets). `EvidenceState.build()` validates every link and returns an
immutable container. Downstream code reads the container; no other module
may mint receipts or packets.

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
    EvidenceLinkError,
    IncludedStudy,
    ScreeningReceipt,
    validate_included,
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
    included: tuple[IncludedStudy, ...]
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
    def k_included(self) -> int:
        return len(self.included)

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
        included: tuple[IncludedStudy, ...] = (),
        outcomes: tuple[ExtractedOutcome, ...] = (),
        effects: tuple[EffectSizeRecord, ...] = (),
        packets: tuple[ResultsPacket, ...] = (),
    ) -> EvidenceState:
        """Validate the whole chain in dependency order, then freeze."""
        validate_screening(hits, receipts)
        validate_included(receipts, included)
        validate_outcomes(included, outcomes)
        validate_effects(outcomes, effects)
        validate_packets(effects, packets)
        return cls(topic, hits, receipts, included, outcomes, effects, packets)
