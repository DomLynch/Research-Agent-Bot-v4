"""Sprint 24 — Researka publishing object model.

Three typed schemas that compose the unit of upload to a Researka-style
receipts portal:

  StudyCard      one extracted study: id, citation, metric, effect,
                 sample sizes, evidence-quote, provenance, optional RoB
  ClaimCard      one quantitative claim: pooled effect / CI / k / heterogeneity
                 (built from effect_pool.json + readiness)
  EvidenceReceipt the wrapper carrying the paper + all study cards + claim
                 cards + the L-level readiness + cite-audit state +
                 paper-type decision + manual-audit count

`bundle_research_object(paper_dir)` reads the canonical receipts a
stitched paper folder carries and returns an EvidenceReceipt ready for
JSON serialisation. Universal: every field reads from existing
receipts; no domain literals introduced.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StudyCard:
    study_id: str
    metric: str
    treated_value: float | None
    control_value: float | None
    treated_n: int | None
    control_n: int | None
    percent_change: float | None
    hazard_ratio: float | None
    evidence_quotes: tuple[str, ...]
    reviewer: str
    extraction_status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "study_id": self.study_id, "metric": self.metric,
            "treated_value": self.treated_value,
            "control_value": self.control_value,
            "treated_n": self.treated_n, "control_n": self.control_n,
            "percent_change": self.percent_change,
            "hazard_ratio": self.hazard_ratio,
            "evidence_quotes": list(self.evidence_quotes),
            "reviewer": self.reviewer,
            "extraction_status": self.extraction_status,
        }


@dataclass(frozen=True, slots=True)
class ClaimCard:
    k_effects: int
    pooled_effect: float | None
    pooled_ci_low: float | None
    pooled_ci_high: float | None
    i_squared: float | None
    metric: str

    def as_dict(self) -> dict[str, object]:
        return {
            "k_effects": self.k_effects,
            "pooled_effect": self.pooled_effect,
            "pooled_ci_low": self.pooled_ci_low,
            "pooled_ci_high": self.pooled_ci_high,
            "i_squared": self.i_squared, "metric": self.metric,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    topic: str
    paper_dir_name: str
    readiness_level: int
    readiness_label: str
    # None == cite_audit.json was absent (unknown), not False (defective).
    # Honest tri-state prevents the silent "missing == broken" false-alarm.
    cite_audit_clean: bool | None
    paper_type: str
    manual_audits_count: int
    studies: tuple[StudyCard, ...]
    claims: tuple[ClaimCard, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic, "paper_dir_name": self.paper_dir_name,
            "readiness_level": self.readiness_level,
            "readiness_label": self.readiness_label,
            "cite_audit_clean": self.cite_audit_clean,
            "paper_type": self.paper_type,
            "manual_audits_count": self.manual_audits_count,
            "studies": [s.as_dict() for s in self.studies],
            "claims": [c.as_dict() for c in self.claims],
        }


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v) if isinstance(v, (int, float, str)) else None
    except (TypeError, ValueError):
        return None


def _safe_int(v: object) -> int | None:
    if v is None:
        return None
    try:
        return int(v) if isinstance(v, (int, float, str)) else None
    except (TypeError, ValueError):
        return None


def _study_cards_from_extractions(
    extractions: dict[str, object],
) -> tuple[StudyCard, ...]:
    receipts = extractions.get("receipts")
    if not isinstance(receipts, list):
        return ()
    cards: list[StudyCard] = []
    for r in receipts:
        if not isinstance(r, dict):
            continue
        quotes_raw = r.get("evidence_quotes") or ()
        quotes = tuple(str(q) for q in quotes_raw if isinstance(quotes_raw, list))
        cards.append(StudyCard(
            study_id=str(r.get("study_id") or ""),
            metric=str(r.get("metric") or ""),
            treated_value=_safe_float(r.get("treated_value")),
            control_value=_safe_float(r.get("control_value")),
            treated_n=_safe_int(r.get("treated_n")),
            control_n=_safe_int(r.get("control_n")),
            percent_change=_safe_float(r.get("percent_change")),
            hazard_ratio=_safe_float(r.get("hazard_ratio")),
            evidence_quotes=quotes,
            reviewer=str(r.get("reviewer") or ""),
            extraction_status=str(r.get("status") or ""),
        ))
    return tuple(cards)


def _claim_cards_from_pool(pool: dict[str, object]) -> tuple[ClaimCard, ...]:
    """Read the inverse-variance pool summary from effect_pool.json.

    Bug fix (GPT-auditor 2026-05-13): the previous reader looked for
    pooled-effect fields inside `pool["outcomes"]`, but `outcomes` is the
    per-study record list — the pooled claim itself lives in
    `pool["pooled_a_core_summary"]` (canonical key written by
    compile_pool / regen_section3) and optionally
    `pool["pooled_sensitivity_summary"]` for the sensitivity pool.
    Universal: keys are pool-writer-canonical, no domain literals.
    """
    cards: list[ClaimCard] = []
    for key in ("pooled_a_core_summary", "pooled_sensitivity_summary"):
        s = pool.get(key)
        if not isinstance(s, dict):
            continue
        cards.append(ClaimCard(
            k_effects=_safe_int(s.get("k")) or 0,
            pooled_effect=_safe_float(s.get("estimate")),
            pooled_ci_low=_safe_float(s.get("ci_low")),
            pooled_ci_high=_safe_float(s.get("ci_high")),
            i_squared=_safe_float(s.get("i_squared")),
            metric=str(s.get("metric") or ""),
        ))
    return tuple(cards)


def bundle_research_object(
    paper_dir: Path, *, topic: str = "",
) -> EvidenceReceipt:
    """Read the canonical receipts in `paper_dir` and assemble an
    EvidenceReceipt. Missing receipts → defaults (never raises)."""
    readiness = _read_json(paper_dir / "readiness_report.json")
    cite_audit_path = paper_dir / "cite_audit.json"
    cite_audit = _read_json(cite_audit_path)
    paper_type_doc = _read_json(paper_dir / "paper_type_decision.json")
    manual_audit = _read_json(paper_dir / "manual_audit.json")
    extractions = _read_json(paper_dir / "effect_extractions.json")
    pool = _read_json(paper_dir / "effect_pool.json")

    audits_raw = manual_audit.get("audits") if isinstance(manual_audit.get("audits"), list) else []
    audits_count = len(audits_raw) if isinstance(audits_raw, list) else 0

    # Honest tri-state: None == file absent (unknown); False == file
    # present but defective; True == file present and clean.
    if not cite_audit_path.exists():
        clean: bool | None = None
    else:
        clean = bool(cite_audit.get("clean", False))

    return EvidenceReceipt(
        topic=topic or str(extractions.get("topic") or ""),
        paper_dir_name=paper_dir.name,
        readiness_level=_safe_int(readiness.get("level")) or 0,
        readiness_label=str(readiness.get("label") or ""),
        cite_audit_clean=clean,
        paper_type=str(paper_type_doc.get("name") or ""),
        manual_audits_count=audits_count,
        studies=_study_cards_from_extractions(extractions),
        claims=_claim_cards_from_pool(pool),
    )
