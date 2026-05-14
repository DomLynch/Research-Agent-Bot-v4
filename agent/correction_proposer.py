"""Sprint 57 (Layer 7) — machine-actionable DB correction proposer.

For every `dies` verdict from the source-audit pipeline, this module
parses the abstract / PMC full-text to find what the source ACTUALLY
says, then emits a structured CorrectionProposal that the Researka DB
team can ingest as a canonical correction patch. Closes the audit
loop: dies verdict -> proposed correction -> DB curator workflow.

Universal: no biomedical literals. Operates over Sprint 54 + 55 + 57
primitives (NumericAnchor, subgroup_score) — all generic text-mining.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.source_audit import FactVerdict
from agent.source_corpus import (
    NumericAnchor,
    extract_all_anchors,
    subgroup_score,
)


@dataclass(frozen=True, slots=True)
class CorrectionProposal:
    fact_id: str
    current_value: str         # DB-stored e.g. "9.0%"
    proposed_value: str        # parsed from source e.g. "9.0%"
    current_population: str
    proposed_population: str   # best-matching span near the proposed value
    evidence_quote: str        # source span supporting the proposed value
    confidence: float          # 0..1 — high when one clean match in source
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id,
                "current_value": self.current_value,
                "proposed_value": self.proposed_value,
                "current_population": self.current_population,
                "proposed_population": self.proposed_population,
                "evidence_quote": self.evidence_quote,
                "confidence": self.confidence,
                "rationale": self.rationale}


def _format_value(anchor: NumericAnchor) -> str:
    return f"{anchor.value:g}{anchor.units}"


def propose_correction(
    verdict: FactVerdict, fact: dict[str, Any], abstract: str,
    fulltext: str = "",
) -> CorrectionProposal | None:
    """Build a structured correction patch from a `dies` verdict +
    its source text. Universal scoring: rank source-text anchors by
    (subgroup_match_to_db_population, -distance_to_db_value); the top
    anchor is the proposed correction. Returns None when verdict isn't
    `dies`, fact has no numeric_value, or no anchors found in source."""
    if verdict.verdict != "dies":
        return None
    target_val = fact.get("numeric_value")
    if not isinstance(target_val, (int, float)):
        return None
    source = fulltext if fulltext else abstract
    if not source:
        return None
    anchors = extract_all_anchors(source)
    if not anchors:
        return None
    population = str(fact.get("population") or "")
    intervention = str(fact.get("intervention") or "")
    tv = float(target_val)

    def _rank(a: NumericAnchor) -> tuple[float, float, float]:
        sg = subgroup_score(population, intervention, a.span)
        # Penalize anchors equal to the DB value (proposing no change
        # is a no-op). Among genuine alternatives, prefer the closer
        # one — far-out values like '90%' from 'age at 90% mortality'
        # lose to plausible effect-size alternatives.
        is_same = 1.0 if abs(a.value - tv) < 1e-9 else 0.0
        dist = (min(1.0, abs(a.value - tv) / abs(tv))
                if tv != 0 else 0.0)
        return (sg, -is_same, -dist)

    best = max(anchors, key=_rank)
    sg = subgroup_score(population, intervention, best.span)
    same_value = abs(best.value - tv) < 1e-9
    confidence = round(min(1.0, sg + 0.3), 3)
    rationale = (
        "Source quotes the DB value but attributes it to a different "
        "subgroup; proposed value carries the abstract-matched subgroup."
        if same_value else
        "Source's strongest subgroup match has a different value than "
        "the DB; the proposed value is what the abstract supports."
    )
    return CorrectionProposal(
        fact_id=verdict.fact_id,
        current_value=verdict.db_value,
        proposed_value=_format_value(best),
        current_population=population,
        proposed_population=best.span[:200],
        evidence_quote=verdict.source_quote or best.span[:300],
        confidence=confidence,
        rationale=rationale,
    )


def propose_corrections_for_run(
    verdicts: list[FactVerdict], facts: list[dict[str, Any]],
    abstracts: dict[str, str], fulltexts: dict[str, str],
) -> list[CorrectionProposal]:
    """Batch helper: walk verdicts + facts, emit proposals for every
    `dies` verdict that has enough source context to suggest a fix."""
    facts_by_id = {str(f.get("fact_id") or ""): f
                   for f in facts if isinstance(f, dict)}
    out: list[CorrectionProposal] = []
    for v in verdicts:
        f = facts_by_id.get(v.fact_id)
        if not f:
            continue
        paper = f.get("source_paper") or {}
        pmid = str(paper.get("pmid") or "")
        pmcid = str(paper.get("pmcid") or "")
        proposal = propose_correction(
            v, f, abstract=abstracts.get(pmid, ""),
            fulltext=fulltexts.get(pmcid, ""),
        )
        if proposal is not None:
            out.append(proposal)
    return out
