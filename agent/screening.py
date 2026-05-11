"""Screening receipts and candidate-study records.

A `CandidateStudy` is the result of automated screening — it has NOT
yet been confirmed as included in the meta-analysis. The `stage` field
tracks where in the screening pipeline the candidate currently sits:

  - title_abstract_candidate : passed automated title/abstract rules
  - full_text_retrieved      : full text has been obtained
  - full_text_eligible       : full text confirmed to meet PICO
  - effect_extractable       : effect-size data has been parsed

Only studies at `full_text_eligible` or `effect_extractable` count as
"included" for downstream pooling and corpus characterisation.

Universal: no domain-specific fields here; every value is either a
stable identifier or a free-text reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.retrieval.base import PaperHit

ScreeningStage = Literal[
    "title_abstract_candidate",
    "full_text_retrieved",
    "full_text_eligible",
    "effect_extractable",
]

_ELIGIBLE_STAGES: frozenset[ScreeningStage] = frozenset(
    ("full_text_eligible", "effect_extractable")
)


@dataclass(frozen=True, slots=True)
class ScreeningReceipt:
    hit_key: str
    decision: Literal["include", "exclude"]
    stage: Literal["title-abstract", "full-text"]
    reason: str
    reviewer: str = ""


@dataclass(frozen=True, slots=True)
class CandidateStudy:
    study_id: str
    hit_key: str
    title: str
    year: int | None
    venue: str | None
    screening_stage: ScreeningStage = "title_abstract_candidate"
    pmid: str | None = None
    doi: str | None = None

    @property
    def is_eligible(self) -> bool:
        return self.screening_stage in _ELIGIBLE_STAGES


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


def validate_candidates(
    receipts: tuple[ScreeningReceipt, ...], candidates: tuple[CandidateStudy, ...]
) -> None:
    """A CandidateStudy must have at least one include receipt (any stage)."""
    include_keys = {r.hit_key for r in receipts if r.decision == "include"}
    seen_ids: set[str] = set()
    for s in candidates:
        if s.hit_key not in include_keys:
            raise EvidenceLinkError(
                f"CandidateStudy {s.study_id!r} has no include screening receipt"
            )
        if s.study_id in seen_ids:
            raise EvidenceLinkError(f"Duplicate CandidateStudy.study_id {s.study_id!r}")
        seen_ids.add(s.study_id)
