"""Sprint 39 — Evidence Index.

The platform pivot: paper writer is one export module; the core
product is a living evidence map. This module aggregates per-topic
paper-folder receipts into a typed `EvidenceIndex` snapshot.

A snapshot per topic captures:
  - the primary claim (intervention → endpoint, from the topic pack)
  - 0..100 confidence score derived from existing receipts
  - supporting + contradicting study IDs (from extractions + pool)
  - paper-type latest classification (scoping / pilot / meta-analysis)
  - readiness level + k_pool
  - timestamp + iteration provenance

Universal: every field reads canonical paper-folder receipts; no
biomedical literals. The same code computes an index for rapamycin,
acarbose, climate, finance, etc.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent.topic_pack import load_topic_pack

# 0..100 confidence weights, summed where signals exist.
_W_K_POOL = 35      # k_pool >= 3 = full; pro-rated below
_W_READINESS = 30    # readiness level 1..6 → 0..30
_W_CITE_AUDIT = 15   # clean cite_audit
_W_DUAL_AGENT = 20   # mean agent confidence
_MAX_SCORE = _W_K_POOL + _W_READINESS + _W_CITE_AUDIT + _W_DUAL_AGENT  # = 100


@dataclass(frozen=True, slots=True)
class ClaimAtom:
    """One atomic claim — typically the topic's primary intervention →
    endpoint relationship — scored against current evidence.

    Sprint 42: `score_breakdown` exposes the per-component contributions
    that sum to `confidence_0_100`, so any reviewer can reconstruct the
    score. Sprint 43: `publication_opportunity` flags claims that have
    crossed the journal-grade threshold (confidence >= 70 AND k_pool >= 2)."""
    topic: str
    claim_text: str
    confidence_0_100: int
    score_breakdown: tuple[tuple[str, int], ...]  # ordered (component, points)
    publication_opportunity: bool
    paper_type: str
    readiness_level: int
    k_pool: int
    supporting_study_ids: tuple[str, ...]
    contradicting_study_ids: tuple[str, ...]
    cite_audit_clean: bool | None
    mean_agent_confidence: float

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic, "claim_text": self.claim_text,
            "confidence_0_100": self.confidence_0_100,
            "score_breakdown": dict(self.score_breakdown),
            "publication_opportunity": self.publication_opportunity,
            "paper_type": self.paper_type,
            "readiness_level": self.readiness_level, "k_pool": self.k_pool,
            "supporting_study_ids": list(self.supporting_study_ids),
            "contradicting_study_ids": list(self.contradicting_study_ids),
            "cite_audit_clean": self.cite_audit_clean,
            "mean_agent_confidence": round(self.mean_agent_confidence, 3),
        }


@dataclass(frozen=True, slots=True)
class EvidenceIndex:
    topic: str
    snapshot_utc: str
    paper_dir_name: str
    claims: tuple[ClaimAtom, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic, "snapshot_utc": self.snapshot_utc,
            "paper_dir_name": self.paper_dir_name,
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


def _safe_int(d: dict[str, object], key: str) -> int:
    v = d.get(key, 0)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _safe_list(d: dict[str, object], key: str) -> list[object]:
    v = d.get(key)
    return v if isinstance(v, list) else []


def _confidence_from_receipts(
    *, readiness: dict[str, object], pool: dict[str, object],
    cite_audit_present: bool, cite_audit_clean: bool,
    dual_agent: dict[str, object],
) -> tuple[int, float, tuple[tuple[str, int], ...]]:
    """Combine receipt-derived signals into a 0..100 confidence + mean
    agent confidence + per-component score breakdown. Universal weight
    table; no biomedical literals. The breakdown is the GPT-auditor-
    required transparency: any reviewer can reconstruct the score from
    the four component points."""
    level = _safe_int(readiness, "level")
    k = _safe_int(pool, "k_effects")
    k_factor = min(k, 3) / 3.0
    confs: list[float] = []
    for e in _safe_list(dual_agent, "entries"):
        if not isinstance(e, dict):
            continue
        cs = e.get("confidence_score")
        if isinstance(cs, (int, float)) and not isinstance(cs, bool):
            confs.append(float(cs))
    mean_conf = sum(confs) / len(confs) if confs else 0.0

    k_points = round(_W_K_POOL * k_factor)
    readiness_points = round(_W_READINESS * (level / 6.0))
    cite_points = _W_CITE_AUDIT if cite_audit_present and cite_audit_clean else 0
    agent_points = round(_W_DUAL_AGENT * mean_conf)
    total = k_points + readiness_points + cite_points + agent_points
    breakdown: tuple[tuple[str, int], ...] = (
        ("k_pool", k_points),
        ("readiness_level", readiness_points),
        ("cite_audit_clean", cite_points),
        ("mean_agent_confidence", agent_points),
    )
    return int(max(0, min(_MAX_SCORE, total))), mean_conf, breakdown


def compute_evidence_index(
    paper_dir: Path, *, topic: str, snapshot_utc: str,
) -> EvidenceIndex:
    """Build a single-topic EvidenceIndex from a stitched paper folder.

    Universal — never raises; missing/malformed receipts coerce to
    defaults. The claim_text is derived from the topic pack's primary
    intervention + endpoint, so it stays accurate per topic."""
    pack = load_topic_pack(topic)
    intervention = (pack.primary_interventions[0] if pack and pack.primary_interventions else topic)
    endpoint = (pack.endpoint if pack and pack.endpoint else "primary endpoint")
    claim_text = f"{intervention} influences {endpoint} (per current evidence-contract corpus)"

    readiness = _read_json(paper_dir / "readiness_report.json")
    pool = _read_json(paper_dir / "effect_pool.json")
    cite_audit_path = paper_dir / "cite_audit.json"
    cite_audit = _read_json(cite_audit_path)
    dual_agent = _read_json(paper_dir / "dual_agent_extraction_audit.json")
    paper_type_doc = _read_json(paper_dir / "paper_type_decision.json")

    cite_clean_signal = bool(cite_audit.get("clean", False))
    score, mean_conf, breakdown = _confidence_from_receipts(
        readiness=readiness, pool=pool,
        cite_audit_present=cite_audit_path.exists(),
        cite_audit_clean=cite_clean_signal,
        dual_agent=dual_agent,
    )

    # Supporting = study_ids in pool.effects; contradicting = pool.skipped.
    supporting = tuple(
        str(e.get("study_id", "")) for e in _safe_list(pool, "effects")
        if isinstance(e, dict) and e.get("study_id")
    )
    contradicting = tuple(
        str(s) for s in _safe_list(pool, "skipped_study_ids") if s
    )

    # Sprint 43: publication-opportunity flag. Simple, transparent rule
    # — claim is journal-ready when confidence >= 70 AND k_pool >= 2.
    # The threshold is intentionally conservative so the flag means
    # something; a topic snapshot at L4 with k=0 will never fire it.
    k_pool_count = _safe_int(pool, "k_effects")
    pub_opportunity = score >= 70 and k_pool_count >= 2

    claim = ClaimAtom(
        topic=topic, claim_text=claim_text,
        confidence_0_100=score,
        score_breakdown=breakdown,
        publication_opportunity=pub_opportunity,
        paper_type=str(paper_type_doc.get("name") or "unknown"),
        readiness_level=_safe_int(readiness, "level"),
        k_pool=k_pool_count,
        supporting_study_ids=supporting,
        contradicting_study_ids=contradicting,
        cite_audit_clean=(cite_clean_signal if cite_audit_path.exists() else None),
        mean_agent_confidence=mean_conf,
    )
    return EvidenceIndex(
        topic=topic, snapshot_utc=snapshot_utc,
        paper_dir_name=paper_dir.name, claims=(claim,),
    )
