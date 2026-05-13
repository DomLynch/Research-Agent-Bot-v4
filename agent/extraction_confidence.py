"""Sprint 19 — dual-pass extraction confidence scoring.

Reads the ExtractionReceipt.reviewer provenance tag (set by the
dual-pass orchestrator) + status to derive a per-study confidence
(0..1) and a needs_human_audit flag. Universal: no domain literals.

Scale:
  1.0  dual-pass-agreed   |  0.7 dual-pass-adjudicated
  0.4  pass-b-failed       |  0.3 adjudicator-failed
  0.5  single-pass         |  0.0 status != 'extracted'
needs_human_audit fires when confidence < 0.6.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agent.effect_extraction import ExtractionReceipt

_AUDIT_THRESHOLD: float = 0.6
_TAG_SCORES: tuple[tuple[str, float, str], ...] = (
    ("dual-pass-agreed", 1.0, "both passes agreed on pool-critical fields"),
    ("dual-pass-adjudicated", 0.7, "passes disagreed; adjudicator resolved with quotes"),
    ("dual-pass-adjudicator-failed", 0.3, "passes disagreed AND adjudicator failed"),
    ("dual-pass-pass-b-failed", 0.4, "Pass-B threw; only primary receipt survives"),
)


def _score(receipt: ExtractionReceipt) -> tuple[float, str]:
    if receipt.status != "extracted":
        return 0.0, f"status={receipt.status}"
    rv = receipt.reviewer or ""
    for tag, conf, reason in _TAG_SCORES:
        if tag in rv:
            return conf, reason
    return 0.5, "single-pass extraction (no dual-pass provenance)"


@dataclass(frozen=True, slots=True)
class ExtractionConfidenceEntry:
    study_id: str
    confidence: float
    needs_human_audit: bool
    reason: str
    reviewer: str


@dataclass(frozen=True, slots=True)
class ExtractionConfidenceReport:
    entries: tuple[ExtractionConfidenceEntry, ...]

    @property
    def k_total(self) -> int:
        return len(self.entries)

    @property
    def k_needs_audit(self) -> int:
        return sum(1 for e in self.entries if e.needs_human_audit)

    @property
    def mean_confidence(self) -> float:
        return (sum(e.confidence for e in self.entries) / len(self.entries)
                if self.entries else 0.0)

    def as_dict(self) -> dict[str, object]:
        return {
            "k_total": self.k_total, "k_needs_audit": self.k_needs_audit,
            "mean_confidence": round(self.mean_confidence, 3),
            "audit_threshold": _AUDIT_THRESHOLD,
            "entries": [{
                "study_id": e.study_id, "confidence": e.confidence,
                "needs_human_audit": e.needs_human_audit,
                "reason": e.reason, "reviewer": e.reviewer,
            } for e in self.entries],
        }


def score_extractions(
    receipts: Iterable[ExtractionReceipt],
) -> ExtractionConfidenceReport:
    """Score every receipt; flag low-confidence ones for human audit."""
    entries = tuple(
        ExtractionConfidenceEntry(
            study_id=r.study_id, confidence=c,
            needs_human_audit=c < _AUDIT_THRESHOLD,
            reason=reason, reviewer=r.reviewer or "",
        )
        for r in receipts
        for c, reason in (_score(r),)
    )
    return ExtractionConfidenceReport(entries=entries)
