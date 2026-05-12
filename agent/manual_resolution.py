"""Sprint 7.11.1 - Manual resolution overlay (status-only, no inclusion power).

The universal-engine rule: a manual entry can RESOLVE sentinel status
(retrieved/available/excluded/needs_review), but it cannot CREATE primary
inclusion. Primary inclusion is the sole gate of
`agent.include_contract.EvidenceEligibilityContract`:

    can_enter_primary_effect_set = (
        evidence_artifact_present
        AND source_hash_or_pointer_present
        AND domain_fields_complete
        AND comparator_present
        AND endpoint_present
        AND current_study_quote_present
        AND extraction_field_present
    )

That contract applies to every paper, including sentinels. A sentinel
that the system failed to retrieve is a SYSTEM BUG (retrieval/parser
needs fixing), not a license to manually launder it into the corpus.

Symmetry:
    - Manuals MAY exclude (status='resolved_excluded') because exclusion
      is conservative.
    - Manuals MAY mark unavailable (status='resolved_unavailable') so the
      sentinel-recall gate can recognise documented retrieval gaps as
      resolved rather than as unresolved misses.
    - Manuals MAY flag for human review (status='needs_review').
    - Manuals MAY assert availability (status='resolved_available') so
      the sentinel-recall gate can WARN with "system bug" framing rather
      than FAIL with "not retrieved" — but availability does NOT confer
      primary-corpus membership.

TOML schema (`topic_packs/<topic>_manual_resolutions.toml`):

    [[resolutions]]
    doi = "..."
    pmid = "..."
    status = "resolved_available" | "resolved_unavailable" |
             "resolved_excluded" | "needs_review"
    reason = "..."
    evidence_quote = "..."     # optional audit-only quote
    reviewer = "human-..."
    action_required = "..."    # optional remediation hint
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent.retrieval.base import normalize_doi
from agent.screening import CandidateStudy

_PACK_DIR = Path(__file__).resolve().parent.parent / "topic_packs"

ManualStatus = Literal[
    "resolved_available",
    "resolved_unavailable",
    "resolved_excluded",
    "needs_review",
]

_VALID_STATUSES: frozenset[str] = frozenset(
    ("resolved_available", "resolved_unavailable",
     "resolved_excluded", "needs_review")
)


@dataclass(frozen=True, slots=True)
class ManualResolutionReceipt:
    """One human-declared sentinel-status assertion.

    Crucially: this record has no `decision` field and no `lane` field.
    It cannot mint an EligibilityReceipt and cannot promote a paper into
    the primary-effect set. It only resolves SENTINEL STATUS for the
    recall audit and (when status='resolved_excluded') subtracts from the
    primary corpus."""

    doi: str
    pmid: str
    status: ManualStatus
    reason: str
    evidence_quote: str
    reviewer: str
    action_required: str = ""


def load_manual_resolutions(
    topic: str, *, pack_dir: Path | None = None,
) -> tuple[ManualResolutionReceipt, ...]:
    """Load topic_packs/<topic>_manual_resolutions.toml if present."""
    base = pack_dir or _PACK_DIR
    path = base / f"{topic}_manual_resolutions.toml"
    if not path.exists():
        return ()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[ManualResolutionReceipt] = []
    for entry in raw.get("resolutions", []):
        status = str(entry.get("status", "needs_review"))
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"manual_resolutions: invalid status {status!r} "
                f"(must be one of {sorted(_VALID_STATUSES)})"
            )
        out.append(ManualResolutionReceipt(
            doi=str(entry.get("doi", "")).strip(),
            pmid=str(entry.get("pmid", "")).strip(),
            status=status,  # type: ignore[arg-type]
            reason=str(entry.get("reason", "")),
            evidence_quote=str(entry.get("evidence_quote", "")),
            reviewer=str(entry.get("reviewer", "human")),
            action_required=str(entry.get("action_required", "")),
        ))
    return tuple(out)


def _lookup_study_id(
    resolution: ManualResolutionReceipt, candidates: tuple[CandidateStudy, ...],
) -> str | None:
    norm_doi = normalize_doi(resolution.doi) if resolution.doi else None
    for c in candidates:
        if norm_doi and c.doi and normalize_doi(c.doi) == norm_doi:
            return c.study_id
        if resolution.pmid and c.pmid and c.pmid == resolution.pmid:
            return c.study_id
    return None


def build_manual_status_overlay(
    resolutions: tuple[ManualResolutionReceipt, ...],
    candidates: tuple[CandidateStudy, ...],
) -> dict[str, ManualResolutionReceipt]:
    """Index manual resolutions by candidate study_id. Returns a dict
    so downstream code can ask `overlay.get(study_id)` without iterating.

    Resolutions that don't match any candidate are silently skipped; the
    caller (orchestrator) is responsible for logging the miss."""
    overlay: dict[str, ManualResolutionReceipt] = {}
    for res in resolutions:
        sid = _lookup_study_id(res, candidates)
        if sid is not None:
            overlay[sid] = res
    return overlay
