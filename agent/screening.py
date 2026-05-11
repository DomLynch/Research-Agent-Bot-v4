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

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
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


@dataclass(frozen=True, slots=True)
class FullTextReceipt:
    """Records whether full-text retrieval was attempted for a candidate."""

    study_id: str
    retrieved: bool
    source: str = ""
    reason: str = ""


_EMPTY_FIELDS: Mapping[str, bool] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class EligibilityReceipt:
    """Records the eligibility decision after full-text review.

    Decision values:
      - "include"  : eligible for downstream pooling
      - "exclude"  : disqualified by hard rule or judge
      - "unclear"  : rule/judge conflict or low confidence; needs manual review

    Sprint 7 audit-trail fields (optional, default to empty so legacy callers
    that only pass study_id/decision/reason continue to work):
      confidence       : judge confidence in [0, 1]
      mandatory_fields : per-criterion boolean checklist (immutable mapping)
      evidence_quotes  : verbatim snippets supporting the decision
      judge_model      : model id that produced the proposal
      rule_decision    : Pass-1 triage label
      source_text_hash : hash of the parsed full-text that fed the judge
      timestamp_utc    : ISO-8601 UTC when adjudication ran
    """

    study_id: str
    decision: Literal["include", "exclude", "unclear"]
    reason: str
    reviewer: str = ""
    confidence: float = 0.0
    mandatory_fields: Mapping[str, bool] = field(default_factory=lambda: _EMPTY_FIELDS)
    evidence_quotes: tuple[str, ...] = ()
    judge_model: str = ""
    rule_decision: str = ""
    source_text_hash: str = ""
    timestamp_utc: str = ""


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


def validate_full_text_receipts(
    candidates: tuple[CandidateStudy, ...], receipts: tuple[FullTextReceipt, ...]
) -> None:
    study_ids = {s.study_id for s in candidates}
    for r in receipts:
        if r.study_id not in study_ids:
            raise EvidenceLinkError(
                f"FullTextReceipt references unknown study_id {r.study_id!r}"
            )


def validate_eligibility_receipts(
    candidates: tuple[CandidateStudy, ...],
    ft_receipts: tuple[FullTextReceipt, ...],
    elig_receipts: tuple[EligibilityReceipt, ...],
) -> None:
    """An eligibility decision presupposes successful full-text retrieval."""
    study_ids = {s.study_id for s in candidates}
    retrieved = {r.study_id for r in ft_receipts if r.retrieved}
    for r in elig_receipts:
        if r.study_id not in study_ids:
            raise EvidenceLinkError(
                f"EligibilityReceipt references unknown study_id {r.study_id!r}"
            )
        if r.study_id not in retrieved:
            raise EvidenceLinkError(
                f"EligibilityReceipt for {r.study_id!r} lacks a full-text-retrieved receipt"
            )


def upgrade_candidate_stages(
    candidates: tuple[CandidateStudy, ...],
    ft_receipts: tuple[FullTextReceipt, ...],
    elig_receipts: tuple[EligibilityReceipt, ...],
    effect_study_ids: frozenset[str] = frozenset(),
) -> tuple[CandidateStudy, ...]:
    """Promote each candidate to the highest stage its receipts justify."""
    retrieved = {r.study_id for r in ft_receipts if r.retrieved}
    eligible = {r.study_id for r in elig_receipts if r.decision == "include"}
    out: list[CandidateStudy] = []
    for s in candidates:
        stage: ScreeningStage = s.screening_stage
        if s.study_id in retrieved:
            stage = "full_text_retrieved"
        if s.study_id in eligible:
            stage = "full_text_eligible"
        if s.study_id in effect_study_ids:
            stage = "effect_extractable"
        if stage == s.screening_stage:
            out.append(s)
        else:
            out.append(
                CandidateStudy(
                    study_id=s.study_id,
                    hit_key=s.hit_key,
                    title=s.title,
                    year=s.year,
                    venue=s.venue,
                    screening_stage=stage,
                    pmid=s.pmid,
                    doi=s.doi,
                )
            )
    return tuple(out)
