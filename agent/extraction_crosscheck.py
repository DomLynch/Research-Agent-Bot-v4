"""Cross-check an extraction receipt against Researka canonical facts.

For each extracted receipt with numerics, search the Researka Tier 2
facts index for the paper, filter to that paper's DOI, and emit a
verdict:

  matched      receipt's percent_change is within tolerance of a
               canonical fact with units='%' for the same paper
  discrepant   a percent-change-units canonical fact exists for the
               paper but its value is outside tolerance — receipt
               numerics conflict with Researka's record
  no_canonical_fact   no facts found for the DOI (Researka may not have
               indexed this paper, or has only non-numeric facts)
  no_receipt_numerics   receipt.percent_change is null; nothing to
               cross-check (e.g. parse_failed / no_numerics receipts)

The crosscheck is a non-binding audit layer: it does NOT modify the
extraction receipt or alter the pool. It writes a sidecar JSON
(`extraction_crosscheck.json`) that downstream supplement S5 / S6 can
inline as a third-party-validation receipt. Audit > silent rewrite.

Universal: nothing biomedical here; the verdict logic is metric-
agnostic (% comparison only). Future: extend with units-aware
normalisation for days / months / hazard-ratio when receipt + fact
units match.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from agent.researka_facts import (
    ResearkaFact,
    filter_facts_by_doi,
    search_facts,
)
from agent.settings import Settings
from agent.topic_pack import TopicPack

_TOLERANCE_PERCENT = 25.0  # |Δ| / canonical_value ≤ 25% → matched


@dataclass(frozen=True, slots=True)
class CrosscheckResult:
    study_id: str
    doi: str | None
    verdict: str
    receipt_percent_change: float | None
    canonical_facts: tuple[ResearkaFact, ...]
    best_match_fact_id: str | None
    delta_percent: float | None  # |receipt% - canonical%| in absolute %


def _percent_compare(
    receipt_pct: float | None, fact: ResearkaFact,
) -> tuple[float, bool] | None:
    """Return (|delta|, within_tolerance) when both values are percent;
    None when units don't align."""
    if receipt_pct is None or fact.numeric_value is None:
        return None
    if fact.units.strip() not in {"%", "percent"}:
        return None
    delta = abs(receipt_pct - fact.numeric_value)
    tolerance = abs(fact.numeric_value) * (_TOLERANCE_PERCENT / 100.0)
    return delta, delta <= tolerance


def crosscheck_one(
    study_id: str, doi: str | None, percent_change: float | None,
    *, facts: tuple[ResearkaFact, ...],
) -> CrosscheckResult:
    """Compute the verdict for a single receipt given the candidate facts."""
    paper_facts = filter_facts_by_doi(facts, doi)
    if percent_change is None:
        return CrosscheckResult(
            study_id=study_id, doi=doi, verdict="no_receipt_numerics",
            receipt_percent_change=None,
            canonical_facts=paper_facts,
            best_match_fact_id=None, delta_percent=None,
        )
    if not paper_facts:
        return CrosscheckResult(
            study_id=study_id, doi=doi, verdict="no_canonical_fact",
            receipt_percent_change=percent_change,
            canonical_facts=(),
            best_match_fact_id=None, delta_percent=None,
        )
    best_id: str | None = None
    best_delta: float | None = None
    matched = False
    for fact in paper_facts:
        cmp_pair = _percent_compare(percent_change, fact)
        if cmp_pair is None:
            continue
        delta, in_tol = cmp_pair
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_id = fact.id
        if in_tol:
            matched = True
    if best_delta is None:
        verdict = "no_canonical_fact"  # facts exist but none in % units
    elif matched:
        verdict = "matched"
    else:
        verdict = "discrepant"
    return CrosscheckResult(
        study_id=study_id, doi=doi, verdict=verdict,
        receipt_percent_change=percent_change,
        canonical_facts=paper_facts,
        best_match_fact_id=best_id, delta_percent=best_delta,
    )


async def crosscheck_receipts(
    receipts: tuple[dict[str, Any], ...], *, settings: Settings,
    pack: TopicPack,
    a_core_ids: tuple[str, ...] = (),
) -> tuple[CrosscheckResult, ...]:
    """Cross-check every receipt against Researka canonical facts.

    Topic query terms are derived from the topic pack — no hardcoded
    biomedical vocabulary. The per-receipt query uses the topic name +
    study_id + DOI; the A-core broader sweep uses topic + endpoint +
    primary_system (e.g. for climate packs that'd be 'forest-fire +
    burn-area + ecosystem'). The DOI filter then narrows to the right
    paper.
    """
    results: list[CrosscheckResult] = []
    if not receipts:
        return ()
    topic = pack.topic
    broader_terms = " ".join(
        t for t in (pack.topic, pack.endpoint, pack.primary_system) if t
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        for r in receipts:
            sid = str(r.get("study_id") or "")
            doi = r.get("doi")  # callers fold doi into receipt before call
            pct = r.get("percent_change")
            if pct is not None:
                try:
                    pct = float(pct)
                except (TypeError, ValueError):
                    pct = None
            facts = await search_facts(
                f"{topic} {sid} {doi or ''}".strip(),
                client=client, settings=settings, top_k=20,
                min_confidence="medium", numeric_only=True,
            )
            results.append(crosscheck_one(sid, doi, pct, facts=facts))
            if sid in a_core_ids and broader_terms:
                broader = await search_facts(
                    broader_terms, client=client, settings=settings,
                    top_k=50, min_confidence="medium", numeric_only=True,
                )
                results[-1] = crosscheck_one(
                    sid, doi, pct, facts=facts + broader,
                )
    return tuple(results)


def _runner(
    receipts: tuple[dict[str, Any], ...], *, settings: Settings,
    pack: TopicPack, a_core_ids: tuple[str, ...] = (),
) -> tuple[CrosscheckResult, ...]:
    """Sync wrapper around the async crosscheck for CLI/script use."""
    return asyncio.run(crosscheck_receipts(
        receipts, settings=settings, pack=pack, a_core_ids=a_core_ids,
    ))
