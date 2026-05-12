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
    "full_text_parsed",
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
    """Records whether an open-access full-text URL was *located* for a
    candidate. `retrieved=True` means we know where the bytes live; it does
    NOT mean the bytes were downloaded or parsed - that is recorded in
    `ParsedFullTextReceipt`.
    """

    study_id: str
    retrieved: bool
    source: str = ""
    reason: str = ""
    # Optional fallback URL (e.g. Unpaywall PDF) used when the primary
    # source parses to too-little text. Empty string = no fallback.
    fallback_url: str = ""


@dataclass(frozen=True, slots=True)
class ParsedFullTextReceipt:
    """Records whether the OA full-text bytes were fetched and parsed into
    plain text. `parsed=True` is the gate for eligibility adjudication;
    `parsed=False` with a populated `failure_reason` is fail-soft truth.
    `text_hash` is the sha256 of the parsed text (or sha256("") on failure)
    so the audit trail can confirm which content the judge saw.
    """

    study_id: str
    source_url: str
    parsed: bool
    text_hash: str = ""
    char_count: int = 0
    failure_reason: str = ""


_EMPTY_FIELDS: Mapping[str, bool] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class EligibilityReceipt:
    """Final eligibility verdict. Audit-trail fields default to empty so
    legacy callers passing only study_id/decision/reason still work."""

    study_id: str
    decision: Literal["include", "exclude", "unclear", "unavailable"]
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


def validate_parsed_receipts(
    candidates: tuple[CandidateStudy, ...],
    ft_receipts: tuple[FullTextReceipt, ...],
    parsed_receipts: tuple[ParsedFullTextReceipt, ...],
) -> None:
    """A ParsedFullTextReceipt must reference a candidate that has a
    FullTextReceipt with retrieved=True. You cannot parse what was never
    located."""
    study_ids = {s.study_id for s in candidates}
    retrieved = {r.study_id for r in ft_receipts if r.retrieved}
    for r in parsed_receipts:
        if r.study_id not in study_ids:
            raise EvidenceLinkError(
                f"ParsedFullTextReceipt references unknown study_id {r.study_id!r}"
            )
        if r.study_id not in retrieved:
            raise EvidenceLinkError(
                f"ParsedFullTextReceipt for {r.study_id!r} has no full-text-located receipt"
            )


def validate_eligibility_receipts(
    candidates: tuple[CandidateStudy, ...],
    ft_receipts: tuple[FullTextReceipt, ...],
    elig_receipts: tuple[EligibilityReceipt, ...],
    parsed_receipts: tuple[ParsedFullTextReceipt, ...] = (),
) -> None:
    """An eligibility decision presupposes successful parsing.

    Sprint 7 strictness: prior to the truth patch, eligibility could be
    written off the back of a FullTextReceipt(retrieved=True) — that meant
    "we know a URL exists", not "we have the content". This validator now
    requires a ParsedFullTextReceipt(parsed=True) so eligibility cannot be
    laundered through metadata-only receipts.

    For backward compatibility, if `parsed_receipts` is empty (legacy
    callers that haven't yet wired Sprint 7 plumbing), the old retrieved-only
    check applies and a warning-equivalent path is preserved. Once all
    callers pass parsed_receipts the empty-tuple shortcut becomes dead code
    and should be removed."""
    study_ids = {s.study_id for s in candidates}
    retrieved = {r.study_id for r in ft_receipts if r.retrieved}
    parsed_ok = {r.study_id for r in parsed_receipts if r.parsed}
    use_parsed = bool(parsed_receipts)
    for r in elig_receipts:
        if r.study_id not in study_ids:
            raise EvidenceLinkError(
                f"EligibilityReceipt references unknown study_id {r.study_id!r}"
            )
        if use_parsed:
            if r.study_id not in parsed_ok:
                raise EvidenceLinkError(
                    f"EligibilityReceipt for {r.study_id!r} lacks a "
                    f"parsed full-text receipt (parsed=True)"
                )
        elif r.study_id not in retrieved:
            raise EvidenceLinkError(
                f"EligibilityReceipt for {r.study_id!r} lacks a full-text-located receipt"
            )


def upgrade_candidate_stages(
    candidates: tuple[CandidateStudy, ...],
    ft_receipts: tuple[FullTextReceipt, ...],
    elig_receipts: tuple[EligibilityReceipt, ...],
    effect_study_ids: frozenset[str] = frozenset(),
    parsed_receipts: tuple[ParsedFullTextReceipt, ...] = (),
) -> tuple[CandidateStudy, ...]:
    """Promote each candidate to the highest stage its receipts justify.

    Promotion ladder (each level requires the previous level's evidence):
      title_abstract_candidate
        -> full_text_retrieved   (FullTextReceipt.retrieved=True)
        -> full_text_parsed      (ParsedFullTextReceipt.parsed=True)
        -> full_text_eligible    (EligibilityReceipt.decision='include')
        -> effect_extractable    (study_id in effect_study_ids)
    """
    retrieved = {r.study_id for r in ft_receipts if r.retrieved}
    parsed_ok = {r.study_id for r in parsed_receipts if r.parsed}
    eligible = {r.study_id for r in elig_receipts if r.decision == "include"}
    out: list[CandidateStudy] = []
    for s in candidates:
        stage: ScreeningStage = s.screening_stage
        if s.study_id in retrieved:
            stage = "full_text_retrieved"
        if s.study_id in parsed_ok:
            stage = "full_text_parsed"
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
