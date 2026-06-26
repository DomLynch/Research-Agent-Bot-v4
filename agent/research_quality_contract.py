"""Research-quality contract for alpha publish decisions.

The existing publish-tier gate is intentionally structural: it checks receipt binding,
source floors, source coherence, metric coherence, and retrieval-artifact claims. This
module adds the missing product contract for the queue boundary: a structurally valid
memo must still contain a specific, non-boilerplate insight before it can enter the
ready-to-publish bucket.

Universal: the checks use memo structure, generic research-language markers, and
receipt/title token overlap. No topic names or domain vocabularies live here.
"""
from __future__ import annotations

import re
from typing import Any

_FIELD_RE = re.compile(r"^\*\*(?P<name>[^:*]+):\*\*\s*(?P<value>.+)$", re.M)
_WORD_RE = re.compile(r"[a-z][a-z0-9]{2,}")

_GENERIC_TOKENS = frozenset({
    "alpha", "analysis", "based", "because", "bounded", "bundle", "claim",
    "claims", "context", "could", "direct", "effect", "effects", "evidence",
    "finding", "findings", "hypothesis", "independent", "memo", "paper",
    "papers", "receipt", "receipts", "research", "result", "results", "signal",
    "signals", "source", "sources", "specific", "study", "studies", "support",
    "supports", "test", "testing", "this", "topic", "would",
})

_ANGLE_MARKERS = (
    "real tension:", "whereas", "while", "despite", "but not", "however",
    "opposite", "paradox", "reversal", "tradeoff", "diverge", "diverges",
    "divergent", "null", "no effect", "failed", "without", "boundary",
)

_BOILERPLATE_PHRASES = (
    "worth checking because",
    "source-backed effect",
    "source backed effect",
    "bounded receipt bundle",
    "cited receipt bundle",
    "cited direct receipts",
    "direct receipts define the claim",
    "more research is needed",
    "future research is needed",
    "new angle",
    "non-obvious bridge term",
    "bridge explains a boundary condition",
    "what independent receipt would confirm",
    "specific result would falsify",
)

_FALSIFIABILITY_MARKERS = (
    "falsify", "falsifies", "break the idea", "what would break",
    "would disconfirm", "would confirm", "next question", "repeatability",
)


def evaluate_research_quality(verdict: dict[str, Any], memo_md: str) -> dict[str, Any]:
    """Return a queue-time quality verdict for a rendered alpha memo."""
    axes = _dict(verdict.get("axes"))
    claim_text = _claim_text(memo_md)
    source_text = _source_text(axes)
    claim_tokens = _content_tokens(claim_text)
    source_tokens = _content_tokens(source_text)
    overlap = claim_tokens & source_tokens

    evidence_floor = _has_structural_evidence_floor(axes)
    non_obvious_angle = _has_non_obvious_angle(claim_text, axes)
    specific_claim = len(claim_tokens) >= 4 and len(overlap) >= 2
    falsifiable = _has_falsifiability(memo_md)
    boilerplate_hits = _boilerplate_hits(claim_text)
    boilerplate_surface = len(boilerplate_hits) >= 2

    score = 0
    strengths: list[str] = []
    weaknesses: list[str] = []

    if evidence_floor:
        score += 25
        strengths.append("source_diverse_direct_receipt_floor")
    else:
        weaknesses.append("evidence_floor_not_met")

    if non_obvious_angle:
        score += 25
        strengths.append("non_obvious_angle_present")
    else:
        weaknesses.append("missing_non_obvious_angle")

    if specific_claim:
        score += 20
        strengths.append("claim_uses_receipt_owned_terms")
    else:
        weaknesses.append("claim_too_generic_or_not_receipt_owned")

    if falsifiable:
        score += 10
        strengths.append("falsifiable_next_step_present")
    else:
        weaknesses.append("missing_falsifiable_next_step")

    if boilerplate_surface:
        weaknesses.append("boilerplate_insight_surface")
    else:
        score += 20
        strengths.append("not_boilerplate_surface")

    publishable = (
        score >= 70
        and evidence_floor
        and non_obvious_angle
        and specific_claim
        and not boilerplate_surface
    )
    return {
        "publishable": publishable,
        "score": min(100, score),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "claim_receipt_token_overlap": sorted(overlap)[:12],
        "boilerplate_hits": boilerplate_hits,
    }


def apply_publish_quality_contract(
    verdict: dict[str, Any],
    memo_md: str,
) -> dict[str, Any]:
    """Attach quality data and demote structurally-ready but weak memos.

    The function never mutates the input verdict. It only demotes rows that would
    otherwise enter the publish queue as ready_to_publish; curation/repair rows keep
    their existing routing and simply gain the diagnostic sidecar.
    """
    quality = evaluate_research_quality(verdict, memo_md)
    out = dict(verdict)
    out["research_quality"] = quality
    if str(out.get("decision") or "") != "ready_to_publish" or quality["publishable"]:
        return out

    blockers = [str(x) for x in out.get("blockers", []) if str(x)]
    if "research_quality_contract" not in blockers:
        blockers.append("research_quality_contract")
    out.update({
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "maturity_level": "L4",
        "surface_type": "quality_repair_memo",
        "blockers": blockers,
    })
    return out


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _field(md: str, name: str) -> str:
    for match in _FIELD_RE.finditer(md):
        if match.group("name").strip().casefold() == name.casefold():
            return match.group("value").strip()
    return ""


def _section(md: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        md,
        flags=re.M | re.S,
    )
    return match.group(1).strip() if match else ""


def _claim_text(md: str) -> str:
    return "\n".join((
        _field(md, "Headline"),
        _section(md, "One-sentence thesis"),
        _section(md, "Why this is surprising"),
        _section(md, "What this changes"),
        _section(md, "Evidence Landscape"),
    )).strip()


def _source_text(axes: dict[str, Any]) -> str:
    papers = axes.get("source_papers")
    if not isinstance(papers, list):
        return ""
    parts: list[str] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        parts.extend([
            str(paper.get("title") or ""),
            str(paper.get("journal") or ""),
        ])
    return " ".join(parts)


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(text.casefold())
        if token not in _GENERIC_TOKENS
    }


def _has_structural_evidence_floor(axes: dict[str, Any]) -> bool:
    return (
        _int(axes.get("direct_source_papers")) >= 5
        and _int(axes.get("direct_match_receipts")) >= 3
        and _int(axes.get("a_core_receipts")) >= 2
        and axes.get("claim_coherent_source_diversity") is True
        and axes.get("direct_receipt_shape_coherent") is not False
        and axes.get("direct_metric_type_coherent") is not False
        and axes.get("retrieval_artifact_claim") is not True
        and axes.get("cross_domain_forced") is not True
        and axes.get("feed_scope_mismatch") is not True
    )


def _has_non_obvious_angle(text: str, axes: dict[str, Any]) -> bool:
    lowered = text.casefold()
    return axes.get("counter_consensus_tension") is True or any(
        marker in lowered for marker in _ANGLE_MARKERS
    )


def _has_falsifiability(md: str) -> bool:
    text = "\n".join((
        _section(md, "Next question"),
        _section(md, "What would break the idea"),
        _section(md, "What would falsify it"),
        _section(md, "Safety note"),
    )).casefold()
    return any(marker in text for marker in _FALSIFIABILITY_MARKERS)


def _boilerplate_hits(text: str) -> list[str]:
    lowered = text.casefold()
    return [phrase for phrase in _BOILERPLATE_PHRASES if phrase in lowered]


def _int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
