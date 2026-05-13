"""Sprint 27 — universal dual-agent extraction audit.

Builds `dual_agent_extraction_audit.json` from the reviewer-provenance
tag already present on each ExtractionReceipt. The Sprint 12.9 Task C
dual-pass orchestrator (scripts/extract_effects.py) tags
ExtractionReceipt.reviewer with one of:

  mimo-dual-pass-agreed:<modelB>
  mimo-dual-pass-adjudicated:<modelC>;disagreements=metric,treated_n,...
  mimo-dual-pass-pass-b-failed
  mimo-dual-pass-adjudicator-failed;disagreements=...
  mimo:<modelA>                            (single-pass legacy)
  extract-cli                              (placeholder / parse_failed)

This module parses that tag and emits the per-study agreement state
across the 10 pool-critical fields. Universal: keys are the canonical
_POOL_FIELDS from effect_extraction, no domain literals.

Schema (one entry per receipt):
  study_id, extractor_a, extractor_b, status, field_agreement,
  confidence_score, blocking_flags, reviewer
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agent.effect_extraction import ExtractionReceipt
from agent.extraction_confidence import _score as _confidence_score

# Pool-critical fields — must match agent.effect_extraction._POOL_FIELDS.
_POOL_FIELDS: tuple[str, ...] = (
    "status", "metric", "treated_value", "control_value",
    "treated_n", "control_n",
    "hazard_ratio", "hazard_ratio_ci_low", "hazard_ratio_ci_high",
    "percent_change",
)
_AUDIT_THRESHOLD: float = 0.6


def _parse_reviewer(rv: str) -> tuple[str, str | None, str | None, tuple[str, ...]]:
    """Return (status, extractor_a, extractor_b, disagreed_fields)
    from the canonical reviewer-tag string."""
    if not rv:
        return "unknown", None, None, ()
    # Extract "disagreements=field1,field2" suffix if present.
    disagreed: tuple[str, ...] = ()
    if "disagreements=" in rv:
        suffix = rv.split("disagreements=", 1)[1]
        disagreed = tuple(s.strip() for s in suffix.split(",") if s.strip())
    if "dual-pass-agreed" in rv:
        model_b = rv.split("dual-pass-agreed:", 1)[1].split(";")[0] if ":" in rv else None
        return "agent_agreed", "mimo", model_b, ()
    if "dual-pass-adjudicated" in rv:
        model_c = rv.split("dual-pass-adjudicated:", 1)[1].split(";")[0] if ":" in rv else None
        return "agent_adjudicated", "mimo", model_c, disagreed
    if "dual-pass-adjudicator-failed" in rv:
        return "agent_disputed", "mimo", None, disagreed
    if "dual-pass-pass-b-failed" in rv:
        return "pass_b_failed", "mimo", None, ()
    if rv == "extract-cli":
        return "placeholder", None, None, ()
    if rv.startswith("mimo:"):
        return "single_pass", rv.split(":", 1)[1], None, ()
    return "unknown", None, None, ()


@dataclass(frozen=True, slots=True)
class DualAgentAuditEntry:
    study_id: str
    status: str
    extractor_a: str | None
    extractor_b: str | None
    field_agreement: tuple[tuple[str, bool], ...]
    confidence_score: float
    blocking_flags: tuple[str, ...]
    reviewer: str


@dataclass(frozen=True, slots=True)
class DualAgentAuditReport:
    entries: tuple[DualAgentAuditEntry, ...]

    @property
    def k_total(self) -> int:
        return len(self.entries)

    @property
    def k_agent_agreed(self) -> int:
        return sum(1 for e in self.entries if e.status == "agent_agreed")

    @property
    def k_agent_adjudicated(self) -> int:
        return sum(1 for e in self.entries if e.status == "agent_adjudicated")

    @property
    def k_single_pass(self) -> int:
        return sum(1 for e in self.entries if e.status == "single_pass")

    @property
    def k_blocking(self) -> int:
        return sum(1 for e in self.entries if e.blocking_flags)

    def as_dict(self) -> dict[str, object]:
        return {
            "k_total": self.k_total,
            "k_agent_agreed": self.k_agent_agreed,
            "k_agent_adjudicated": self.k_agent_adjudicated,
            "k_single_pass": self.k_single_pass,
            "k_blocking": self.k_blocking,
            "audit_threshold": _AUDIT_THRESHOLD,
            "entries": [{
                "study_id": e.study_id, "status": e.status,
                "extractor_a": e.extractor_a, "extractor_b": e.extractor_b,
                "field_agreement": dict(e.field_agreement),
                "confidence_score": e.confidence_score,
                "blocking_flags": list(e.blocking_flags),
                "reviewer": e.reviewer,
            } for e in self.entries],
        }


def _agreement_for(
    status: str, disagreed: tuple[str, ...],
) -> tuple[tuple[str, bool], ...]:
    """Per-field agreement booleans from status + disagreed-field list."""
    if status == "agent_agreed":
        return tuple((f, True) for f in _POOL_FIELDS)
    if status in {"agent_adjudicated", "agent_disputed"}:
        bad = frozenset(disagreed)
        return tuple((f, f not in bad) for f in _POOL_FIELDS)
    # single_pass / pass_b_failed / placeholder / unknown: no evidence
    # of cross-check — emit all False to signal "not verified".
    return tuple((f, False) for f in _POOL_FIELDS)


def _blocking_for(status: str, extraction_status: str) -> tuple[str, ...]:
    flags: list[str] = []
    if extraction_status != "extracted":
        flags.append(f"extraction_status={extraction_status}")
    if status == "agent_disputed":
        flags.append("adjudicator_failed")
    if status == "pass_b_failed":
        flags.append("pass_b_failed_no_cross_check")
    if status in {"single_pass", "placeholder", "unknown"}:
        flags.append("no_dual_agent_review")
    return tuple(flags)


def audit_extractions(
    receipts: Iterable[ExtractionReceipt],
) -> DualAgentAuditReport:
    """Build the per-study dual-agent audit from extraction receipts."""
    entries: list[DualAgentAuditEntry] = []
    for r in receipts:
        rv = r.reviewer or ""
        status, ext_a, ext_b, disagreed = _parse_reviewer(rv)
        conf, _ = _confidence_score(r)
        entries.append(DualAgentAuditEntry(
            study_id=r.study_id, status=status,
            extractor_a=ext_a, extractor_b=ext_b,
            field_agreement=_agreement_for(status, disagreed),
            confidence_score=conf,
            blocking_flags=_blocking_for(status, r.status),
            reviewer=rv,
        ))
    return DualAgentAuditReport(entries=tuple(entries))
