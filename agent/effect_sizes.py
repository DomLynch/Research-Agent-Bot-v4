"""Extracted outcomes and effect-size records.

ExtractedOutcome is the raw coded data from one study; EffectSizeRecord
is the computed effect (log ratio, hazard ratio, SMD, etc.) derived from
one outcome. Both keep `moderators` as `Mapping[str, str]` so the schema
stays domain-agnostic: biomedical packs use {sex, strain, dose, ...};
climate packs would use {region, year_range, model_class, ...}; etc.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from agent.screening import EvidenceLinkError, IncludedStudy


@dataclass(frozen=True, slots=True)
class ExtractedOutcome:
    study_id: str
    outcome_id: str
    metric_name: str
    moderators: Mapping[str, str]
    treated_value: float | None = None
    control_value: float | None = None
    treated_n: int | None = None
    control_n: int | None = None
    raw_unit: str = ""

    @staticmethod
    def freeze_moderators(moderators: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(moderators))


@dataclass(frozen=True, slots=True)
class EffectSizeRecord:
    study_id: str
    outcome_id: str
    metric: str
    estimate: float
    moderators: Mapping[str, str]
    se: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


def validate_outcomes(
    included: tuple[IncludedStudy, ...], outcomes: tuple[ExtractedOutcome, ...]
) -> None:
    study_ids = {s.study_id for s in included}
    seen_pairs: set[tuple[str, str]] = set()
    for o in outcomes:
        if o.study_id not in study_ids:
            raise EvidenceLinkError(
                f"ExtractedOutcome.study_id {o.study_id!r} not in IncludedStudy list"
            )
        key = (o.study_id, o.outcome_id)
        if key in seen_pairs:
            raise EvidenceLinkError(
                f"Duplicate ExtractedOutcome (study={o.study_id!r}, outcome={o.outcome_id!r})"
            )
        seen_pairs.add(key)


def validate_effects(
    outcomes: tuple[ExtractedOutcome, ...], effects: tuple[EffectSizeRecord, ...]
) -> None:
    outcome_keys = {(o.study_id, o.outcome_id) for o in outcomes}
    for e in effects:
        key = (e.study_id, e.outcome_id)
        if key not in outcome_keys:
            raise EvidenceLinkError(
                f"EffectSizeRecord references unknown outcome "
                f"(study={e.study_id!r}, outcome={e.outcome_id!r})"
            )
