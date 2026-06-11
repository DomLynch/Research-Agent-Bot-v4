"""Researka Tier 2 facts API — POST /api/v1/tier2/facts/search.

Live-verified shape (2026-05-12):
  - POST {base}/api/v1/tier2/facts/search
  - Header: X-Researka-Token: <token>
  - Body: {"query": <str>, "top_k": <int>, "min_confidence": <str>,
           "numeric_only": <bool>}
  - Response: list[FactDict] where each FactDict has:
      id              canonical-fact identifier
      paper_id        DOI
      paper           {title, doi, pmid, publication_year, journal_name}
      claim_type      e.g. "effect_size"
      numeric_value   the actual number
      units           e.g. "%", "days", "mg/kg/day"
      extraction_confidence  "canonical" | "high" | "medium"
      validation      {status, matched_number, delta, checked_at}

The `by-paper` endpoint exists (HTTP 200) but returned empty for every
A-core DOI we probed; `search` is the practical surface. We expose a
thin search wrapper plus a DOI-filtered helper for cross-checking a
specific extracted receipt against canonical facts.

Universal: nothing biomedical in the loader. All Researka facts carry
their own topic/sub_topic; callers can filter by `topic` field in the
returned dicts if needed. Errors return [] silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from agent.retrieval.base import normalize_doi
from agent.settings import Settings


@dataclass(frozen=True, slots=True)
class ResearkaFact:
    id: str
    paper_id: str
    doi: str | None
    pmid: str | None
    paper_title: str
    journal: str
    claim_type: str
    numeric_value: float | None
    units: str
    confidence: str  # "canonical" | "high" | "medium"
    validated: bool


def _parse_fact(item: Any) -> ResearkaFact | None:
    if not isinstance(item, dict):
        return None
    fid = str(item.get("id") or "")
    paper_id = str(item.get("paper_id") or "")
    if not fid or not paper_id:
        return None
    paper = item.get("paper") or {}
    try:
        nv = item.get("numeric_value")
        numeric: float | None = float(nv) if nv is not None else None
    except (TypeError, ValueError):
        numeric = None
    val = item.get("validation") or {}
    return ResearkaFact(
        id=fid,
        paper_id=paper_id,
        doi=normalize_doi(paper.get("doi") or paper_id),
        pmid=str(paper.get("pmid") or "") or None,
        paper_title=str(paper.get("title") or ""),
        journal=str(paper.get("journal_name") or ""),
        claim_type=str(item.get("claim_type") or ""),
        numeric_value=numeric,
        units=str(item.get("units") or ""),
        confidence=str(item.get("extraction_confidence") or ""),
        validated=bool(val.get("status") == "canonical"),
    )


def tier2_source_count(
    topic: str, *, client: httpx.Client, settings: Settings,
    domain: str = "longevity", min_confidence: str = "medium",
) -> int:
    """Distinct Tier-2 corpus source papers for a topic (sync).

    A topic whose facts are not yet topic-tagged reads 0 from the per-topic
    facts endpoint, yet the evidence build binds the same literature from the
    Tier-2 corpus via crosscheck. Counting Tier-2 source papers lets such
    topics clear the build-selection floor instead of being filtered out
    unbuilt. Universal: no per-topic logic; returns 0 on any failure.
    """
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token:
        return 0
    try:
        r = client.post(
            f"{base}/api/v1/tier2/facts/search",
            json={
                # top_k only needs to exceed the source floor: we count distinct
                # papers, not facts. Latency is the corpus scan, not result size.
                "domain": domain, "query": topic[:512], "top_k": 15,
                "min_confidence": min_confidence, "numeric_only": False,
            },
            headers={"X-Researka-Token": token, "Content-Type": "application/json"},
            # The Tier-2 semantic search runs ~40-90s from the VPS; a short
            # timeout silently yields 0 and defeats the rescue. Callers bound
            # how many sub-floor topics are probed per cycle (probe budget).
            timeout=90.0,
        )
        r.raise_for_status()
        data: Any = r.json()
    except (httpx.HTTPError, ValueError):
        return 0
    if not isinstance(data, list):
        return 0
    papers: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_paper = item.get("paper")
        paper = raw_paper if isinstance(raw_paper, dict) else {}
        key = str(paper.get("doi") or paper.get("pmid") or item.get("paper_id") or "")
        if key:
            papers.add(key)
    return len(papers)


async def search_facts(
    query: str, *, client: httpx.AsyncClient, settings: Settings,
    top_k: int = 20, min_confidence: str = "medium", numeric_only: bool = True,
    domain: str = "longevity",
) -> tuple[ResearkaFact, ...]:
    """Hit /api/v1/tier2/facts/search; return parsed facts.

    Empty list on HTTP failure / JSON error / missing token — never raises
    so the crosscheck pipeline degrades gracefully when Researka is
    unreachable.
    """
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token:
        return ()
    try:
        r = await client.post(
            f"{base}/api/v1/tier2/facts/search",
            json={
                "domain": domain,
                "query": query[:512],
                "top_k": min(top_k, 50),
                "min_confidence": min_confidence,
                "numeric_only": numeric_only,
            },
            headers={
                "X-Researka-Token": token,
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        r.raise_for_status()
        data: Any = r.json()
    except (httpx.HTTPError, ValueError):
        return ()
    items = data if isinstance(data, list) else []
    facts = tuple(f for f in (_parse_fact(it) for it in items) if f is not None)
    return facts


def filter_facts_by_doi(
    facts: tuple[ResearkaFact, ...], target_doi: str | None,
) -> tuple[ResearkaFact, ...]:
    """Keep only the facts whose paper DOI matches the target (case-insensitive)."""
    if not target_doi:
        return ()
    norm = (normalize_doi(target_doi) or "").casefold()
    return tuple(
        f for f in facts
        if f.doi and f.doi.casefold() == norm
    )
