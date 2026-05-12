"""Results-packet compiler.

Reads a frozen `EvidenceState` and emits a list of packets that the
Results writer consumes. Two packet shapes:

  - `InformationalPacket`: counts / descriptive content (study selection,
    corpus characteristics, translational evidence map). No effect estimate.
  - `ResultsPacket` (from agent.results_packets): pooled effect estimates
    with k_studies / k_effects / metric / source_effect_ids.

Universal: nothing biomedical in this module. Packet IDs are stable
strings. Packets that have no evidence simply aren't emitted. Refusal
output lives downstream in the writer / results_contract.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from agent.effect_sizes import EffectSizeRecord
from agent.evidence_state import EvidenceState
from agent.manual_resolution import ManualResolutionReceipt
from agent.results_packets import ResultsPacket
from agent.sentinel_recall import audit_sentinel_recall
from agent.topic_pack import TopicPack


@dataclass(frozen=True, slots=True)
class InformationalPacket:
    """Counts / descriptive packet with no effect estimate."""

    packet_id: str
    description: str
    counts: Mapping[str, int]
    notes: tuple[str, ...] = ()
    source_study_ids: tuple[str, ...] = ()


PacketLike = InformationalPacket | ResultsPacket


def compile_sentinel_recall(
    state: EvidenceState, pack: TopicPack,
    manual_overlay: dict[str, ManualResolutionReceipt] | None = None,
) -> InformationalPacket | None:
    if not (pack.sentinel_primary or pack.sentinel_prior_meta):
        return None
    r = audit_sentinel_recall(state, pack, manual_overlay=manual_overlay)
    counts: dict[str, int] = {
        "expected_primary": r.expected_primary,
        "retrieved_primary": r.retrieved_primary,
        "candidate_primary": r.candidate_primary,
        "included_primary": r.included_primary,
        "expected_prior_meta": r.expected_prior_meta,
        "retrieved_prior_meta": r.retrieved_prior_meta,
        "candidate_prior_meta": r.candidate_prior_meta,
        "gate_passes": 1 if r.gate_passes else 0,
    }
    notes: tuple[str, ...] = tuple(
        f"{s.role}:{s.sentinel_id}:"
        f"{'retrieved' if s.retrieved else 'missing'}/"
        f"{'candidate' if s.candidate else 'no-candidate'}/"
        f"{s.eligibility}"
        for s in r.statuses
    )
    return InformationalPacket(
        packet_id="sentinel_recall",
        description=(
            "Sentinel-paper audit: canonical anchors must be retrieved + "
            "auto-contract-pass; manuals can only resolve sentinel STATUS, "
            "they cannot launder unresolved evidence into the corpus."
        ),
        counts=MappingProxyType(counts),
        notes=notes,
    )


def compile_study_selection(state: EvidenceState) -> InformationalPacket:
    counts: dict[str, int] = {
        "identified": state.k_hits,
        "screened_title_abstract": sum(1 for r in state.receipts if r.stage == "title-abstract"),
        "candidates_after_title_abstract": state.k_candidates,
        "full_text_availability_located": state.k_full_text_retrieved,
        "full_text_parsed": state.k_full_text_parsed,
        "eligibility_decisions_made": len(state.eligibility_receipts),
        "eligibility_included": state.k_eligibility_included,
        "eligibility_excluded": state.k_eligibility_excluded,
        "eligibility_unclear": state.k_eligibility_unclear,
        "eligible_after_full_text": state.k_eligible,
    }
    return InformationalPacket(
        packet_id="study_selection",
        description="PRISMA-style flow counts (identified -> candidates -> availability -> parsed -> eligibility).",
        counts=MappingProxyType(counts),
    )


def compile_corpus_characteristics(state: EvidenceState) -> InformationalPacket | None:
    """Only emit when at least one full-text-eligible study exists.

    A corpus characterisation drawn from title-abstract candidates only
    would lie about year range, venue diversity, and inclusion count, so
    the compiler refuses and the writer will emit a [RESULTS_BLOCKED:].
    """
    eligible = state.eligible_studies
    if not eligible:
        return None
    years = [s.year for s in eligible if s.year is not None]
    venues = sorted({s.venue for s in eligible if s.venue})
    counts: dict[str, int] = {
        "eligible": len(eligible),
        "year_min": min(years) if years else 0,
        "year_max": max(years) if years else 0,
        "distinct_venues": len(venues),
    }
    return InformationalPacket(
        packet_id="corpus_characteristics",
        description="Corpus characteristics (eligible studies only): year range, venues, count.",
        counts=MappingProxyType(counts),
        source_study_ids=tuple(s.study_id for s in eligible),
    )


def _pool_inverse_variance(
    estimates: list[float], standard_errors: list[float | None]
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return (pooled_estimate, se, ci_low, ci_high) or (None, None, None, None)."""
    weights: list[float] = []
    values: list[float] = []
    for est, se in zip(estimates, standard_errors, strict=True):
        if se is None or se <= 0:
            continue
        weights.append(1.0 / (se * se))
        values.append(est)
    if not weights:
        return None, None, None, None
    total_w = sum(weights)
    pooled = sum(w * v for w, v in zip(weights, values, strict=True)) / total_w
    pooled_se = math.sqrt(1.0 / total_w)
    return pooled, pooled_se, pooled - 1.96 * pooled_se, pooled + 1.96 * pooled_se


def _packet_for_effects(
    packet_id: str,
    description: str,
    effects: list[EffectSizeRecord],
    moderator_levels: Mapping[str, str],
) -> ResultsPacket:
    estimates = [e.estimate for e in effects]
    errors = [e.se for e in effects]
    pooled, pooled_se, ci_low, ci_high = _pool_inverse_variance(estimates, errors)
    source_ids = tuple((e.study_id, e.outcome_id) for e in effects)
    return ResultsPacket(
        packet_id=packet_id,
        description=description,
        k_studies=len({sid for sid, _ in source_ids}),
        k_effects=len(source_ids),
        metric=effects[0].metric,
        moderator_levels=moderator_levels,
        source_effect_ids=source_ids,
        estimate=pooled,
        se=pooled_se,
        ci_low=ci_low,
        ci_high=ci_high,
    )


def compile_primary_effect(state: EvidenceState) -> ResultsPacket | None:
    if not state.effects:
        return None
    primary_metric = Counter(e.metric for e in state.effects).most_common(1)[0][0]
    in_scope = [e for e in state.effects if e.metric == primary_metric]
    return _packet_for_effects(
        packet_id="primary_effect",
        description=f"Pooled inverse-variance-weighted estimate ({primary_metric}).",
        effects=in_scope,
        moderator_levels={},
    )


def compile_moderator_effects(
    state: EvidenceState, moderator: str
) -> list[ResultsPacket]:
    if not state.effects:
        return []
    by_level: dict[str, list[EffectSizeRecord]] = {}
    for e in state.effects:
        level = e.moderators.get(moderator)
        if level is None:
            continue
        by_level.setdefault(level, []).append(e)
    return [
        _packet_for_effects(
            packet_id=f"moderator_effect.{moderator}.{level}",
            description=f"Pooled estimate for {moderator}={level}.",
            effects=group,
            moderator_levels=MappingProxyType({moderator: level}),
        )
        for level, group in sorted(by_level.items())
    ]


def compile_all(
    state: EvidenceState,
    *,
    moderators: tuple[str, ...] = (),
    pack: TopicPack | None = None,
    manual_overlay: dict[str, ManualResolutionReceipt] | None = None,
) -> list[PacketLike]:
    """Run all compilers. Skips packets that lack evidence.

    When `pack` is provided and declares sentinels, also runs the recall
    audit and emits a `sentinel_recall` packet. `manual_overlay` is the
    status-only sentinel overlay (see agent.manual_resolution).
    """
    packets: list[PacketLike] = [compile_study_selection(state)]
    if pack is not None:
        sentinel_pkt = compile_sentinel_recall(
            state, pack, manual_overlay=manual_overlay,
        )
        if sentinel_pkt is not None:
            packets.append(sentinel_pkt)
    corpus = compile_corpus_characteristics(state)
    if corpus is not None:
        packets.append(corpus)
    primary = compile_primary_effect(state)
    if primary is not None:
        packets.append(primary)
    for m in moderators:
        packets.extend(compile_moderator_effects(state, m))
    return packets
