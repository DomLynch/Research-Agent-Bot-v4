"""Sprint 7.10 - manual sentinel overrides.

The auto-judge ladder will sometimes fail on a paper that the human
reviewer KNOWS belongs in the corpus (foundational sentinel buried by
NCBI rate-limit reCAPTCHA, paywalled-OA gap, etc.). This module lets
the user declare those overrides in a topic-pack TOML file:

    topic_packs/<topic>_manual_resolutions.toml

Each [[resolutions]] block requires:
    doi (or pmid) - identifier to match
    decision - "include" | "exclude" | "unavailable" | "secondary"
    reason - free-text justification (becomes EligibilityReceipt.reason)
    evidence_quote - verbatim quote from the paper (for audit trail)
    reviewer - user identifier (e.g. "human-dom")

Application semantics (run AFTER the contract demotion in the
orchestrator):
    - If a manual resolution matches a candidate (by DOI or PMID), the
      auto-judge receipt is REPLACED by a synthetic receipt with
      reviewer set to the declared reviewer.
    - "secondary" maps to decision='exclude' in the receipt (so it
      doesn't enter the primary pool) but the reason names secondary
      so freeze_primary_set / lane classifier can route it correctly.
    - Universal: no biomedical literals; all data comes from the TOML.

LLM proposes, code disposes, HUMAN overrides. The override is the
top of the stack.
"""
from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from agent.retrieval.base import normalize_doi
from agent.screening import CandidateStudy, EligibilityReceipt

_PACK_DIR = Path(__file__).resolve().parent.parent / "topic_packs"

ManualDecision = Literal["include", "exclude", "unavailable", "secondary"]
ManualLane = Literal[
    "direct_lifespan", "disease_model_survival",
    "secondary_molecular", "healthspan_only", "exclude", "",
]


@dataclass(frozen=True, slots=True)
class ManualResolutionReceipt:
    """One human-declared override for a sentinel or known-relevant paper."""

    doi: str
    pmid: str
    decision: ManualDecision
    reason: str
    evidence_quote: str
    reviewer: str
    lane: ManualLane = ""  # optional - when set, freeze_primary_set honors it


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
        out.append(ManualResolutionReceipt(
            doi=str(entry.get("doi", "")).strip(),
            pmid=str(entry.get("pmid", "")).strip(),
            decision=str(entry.get("decision", "exclude")),  # type: ignore[arg-type]
            reason=str(entry.get("reason", "")),
            evidence_quote=str(entry.get("evidence_quote", "")),
            reviewer=str(entry.get("reviewer", "human")),
            lane=str(entry.get("lane", "")),  # type: ignore[arg-type]
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


def _now_utc() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def apply_manual_resolutions(
    receipts: tuple[EligibilityReceipt, ...],
    candidates: tuple[CandidateStudy, ...],
    resolutions: tuple[ManualResolutionReceipt, ...],
) -> tuple[tuple[EligibilityReceipt, ...], tuple[str, ...]]:
    """Replace auto-judged receipts for any candidate matched by a
    manual resolution. Returns (new_receipts, applied_study_ids).

    A resolution that doesn't match any candidate is silently skipped
    (caller / orchestrator is responsible for logging the miss)."""
    by_id: dict[str, EligibilityReceipt] = {r.study_id: r for r in receipts}
    applied: list[str] = []
    for res in resolutions:
        study_id = _lookup_study_id(res, candidates)
        if study_id is None:
            continue
        receipt_decision: Literal["include", "exclude", "unclear", "unavailable"]
        if res.decision == "secondary":
            receipt_decision = "exclude"
            reason = f"manual override (secondary lane): {res.reason}"
        elif res.decision == "unavailable":
            receipt_decision = "unavailable"
            reason = f"manual override (unavailable): {res.reason}"
        else:
            receipt_decision = res.decision
            reason = f"manual override ({res.decision}): {res.reason}"
        by_id[study_id] = EligibilityReceipt(
            study_id=study_id,
            decision=receipt_decision,
            reason=reason,
            reviewer=res.reviewer,
            confidence=1.0,
            mandatory_fields=MappingProxyType({}),
            evidence_quotes=(res.evidence_quote,) if res.evidence_quote else (),
            judge_model="(manual)",
            rule_decision="manual-override",
            source_text_hash="",
            timestamp_utc=_now_utc(),
        )
        applied.append(study_id)
    new_receipts = tuple(by_id[r.study_id] for r in receipts)
    # Add any new manual receipts for candidates that had no prior receipt
    existing_ids = {r.study_id for r in receipts}
    for sid in applied:
        if sid not in existing_ids:
            new_receipts = (*new_receipts, by_id[sid])
    return new_receipts, tuple(applied)
