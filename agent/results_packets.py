"""Aggregate result packets with full provenance.

Every `ResultsPacket` must declare its k_studies, k_effects, metric, and
the exact `source_effect_ids` it draws from. The Results writer consumes
packets; no Results sentence may exist without at least one packet behind
it. This enforces the "no fake claims" rule at the type level.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent.effect_sizes import EffectSizeRecord
from agent.screening import EvidenceLinkError


@dataclass(frozen=True, slots=True)
class ResultsPacket:
    packet_id: str
    description: str
    k_studies: int
    k_effects: int
    metric: str
    moderator_levels: Mapping[str, str]
    source_effect_ids: tuple[tuple[str, str], ...]  # (study_id, outcome_id)
    estimate: float | None = None
    se: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    n_participants: int | None = None

    def __post_init__(self) -> None:
        if self.k_studies < 1:
            raise EvidenceLinkError(
                f"ResultsPacket {self.packet_id!r} must have k_studies >= 1"
            )
        if self.k_effects < 1:
            raise EvidenceLinkError(
                f"ResultsPacket {self.packet_id!r} must have k_effects >= 1"
            )
        if not self.metric:
            raise EvidenceLinkError(
                f"ResultsPacket {self.packet_id!r} must declare a metric"
            )
        if not self.source_effect_ids:
            raise EvidenceLinkError(
                f"ResultsPacket {self.packet_id!r} must cite at least one source effect id"
            )
        unique_studies = {sid for sid, _ in self.source_effect_ids}
        if len(unique_studies) != self.k_studies:
            raise EvidenceLinkError(
                f"ResultsPacket {self.packet_id!r} claims k_studies={self.k_studies} "
                f"but source_effect_ids cover {len(unique_studies)} distinct studies"
            )
        if len(self.source_effect_ids) != self.k_effects:
            raise EvidenceLinkError(
                f"ResultsPacket {self.packet_id!r} claims k_effects={self.k_effects} "
                f"but source_effect_ids list has {len(self.source_effect_ids)} entries"
            )


def validate_packets(
    effects: tuple[EffectSizeRecord, ...], packets: tuple[ResultsPacket, ...]
) -> None:
    """Cross-validate packets against the effects pool. Per-packet count
    invariants are already enforced in `ResultsPacket.__post_init__`.
    """
    effect_keys = {(e.study_id, e.outcome_id) for e in effects}
    for p in packets:
        for sid, oid in p.source_effect_ids:
            if (sid, oid) not in effect_keys:
                raise EvidenceLinkError(
                    f"ResultsPacket {p.packet_id!r} cites unknown effect "
                    f"(study={sid!r}, outcome={oid!r})"
                )
