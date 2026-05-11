"""Screening receipts and included-study records.

Two frozen records link the evidence chain from raw `PaperHit`s through to
`IncludedStudy`. Universal: no domain-specific fields; every value is
either a stable identifier, a free-text reason, or a metadata field that
applies to any synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.retrieval.base import PaperHit


@dataclass(frozen=True, slots=True)
class ScreeningReceipt:
    hit_key: str
    decision: Literal["include", "exclude"]
    stage: Literal["title-abstract", "full-text"]
    reason: str
    reviewer: str = ""


@dataclass(frozen=True, slots=True)
class IncludedStudy:
    study_id: str
    hit_key: str
    title: str
    year: int | None
    venue: str | None
    pmid: str | None = None
    doi: str | None = None


class EvidenceLinkError(ValueError):
    """A receipt, study, outcome, effect, or packet references a missing record."""


def validate_screening(
    hits: tuple[PaperHit, ...], receipts: tuple[ScreeningReceipt, ...]
) -> None:
    keys = {h.dedupe_key for h in hits}
    for r in receipts:
        if r.hit_key not in keys:
            raise EvidenceLinkError(
                f"ScreeningReceipt references unknown hit_key {r.hit_key!r}"
            )


def validate_included(
    receipts: tuple[ScreeningReceipt, ...], included: tuple[IncludedStudy, ...]
) -> None:
    full_text_includes = {
        r.hit_key
        for r in receipts
        if r.decision == "include" and r.stage == "full-text"
    }
    seen_ids: set[str] = set()
    for s in included:
        if s.hit_key not in full_text_includes:
            raise EvidenceLinkError(
                f"IncludedStudy {s.study_id!r} has no full-text include receipt"
            )
        if s.study_id in seen_ids:
            raise EvidenceLinkError(f"Duplicate IncludedStudy.study_id {s.study_id!r}")
        seen_ids.add(s.study_id)
