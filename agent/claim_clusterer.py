"""LLM claim clustering — group a topic's A_core facts into single-claim
clusters so a memo can lead with the densest agreeing cluster (one
outcome/endpoint, one direction of effect) instead of a scattered pile of a
broad topic's many sub-claims.

The deterministic token-overlap clusterer cannot group synonymous endpoints
(survival / all-cause mortality / overall survival) and is fooled by shared
statistical boilerplate (hazard ratio / confidence interval). This pass asks
the locked writer model (MiniMax M3, Gemma fallback) to read the candidate
phrases and return claim groups. Every returned fact_id is validated to exist, be
A_core, and resolve to a distinct source paper before use; on any LLM/parse
failure the result is empty so callers keep the deterministic fallback.

Universal: no domain literals.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from agent.llm_client import call_writer_with_fallback
from agent.settings import Settings, load_settings

_MAX_FACTS = 40  # cap prompt size; callers pre-rank by source diversity
# A coherent claim cites a tight, recent bundle, not the whole cluster: the
# narrower set reads as one bounded claim (reviewers reject sprawling bundles)
# and newest-first ordering maximises the citation recency ratio the platform
# enforces — without hardcoding any year cutoff. The floor still holds because
# the cite count is never trimmed below the caller's min_sources.
_MAX_CITED_SOURCES = 10


def _phrase(fact: dict[str, Any]) -> str:
    return str(fact.get("canonical_phrase") or fact.get("source_excerpt") or "").strip()


def _fact_year(fact: dict[str, Any]) -> int:
    raw = fact.get("source_paper")
    paper = raw if isinstance(raw, dict) else {}
    for value in (fact.get("canonical_year"), paper.get("year"),
                  paper.get("publication_year"), fact.get("year")):
        try:
            year = int(str(value))
        except (TypeError, ValueError):
            continue
        if 1000 <= year <= 3000:
            return year
    return 0


def _source_key(fact: dict[str, Any]) -> str:
    paper = fact.get("source_paper")
    if isinstance(paper, dict):
        return str(paper.get("doi") or paper.get("pmid") or paper.get("title") or "")
    return ""


def _parse_clusters(content: str) -> list[dict[str, Any]]:
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, content, re.S)
        if not match:
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        clusters = data.get("clusters") if isinstance(data, dict) else data
        if isinstance(clusters, list):
            return [c for c in clusters if isinstance(c, dict)]
    return []


def _build_prompt(topic: str, rows: list[tuple[str, str]]) -> str:
    listing = "\n".join(f"[{fid}] {phrase}" for fid, phrase in rows)
    return (
        f'You are grouping research findings about "{topic.replace("_", " ")}" '
        "into HOMOGENEOUS claim clusters. A cluster is a set of findings that "
        "are directly comparable: the SAME population/setting, the SAME "
        "comparator or baseline, the SAME outcome/endpoint, AND the SAME "
        "direction of effect — not merely the same metric word. For example, "
        "'higher accuracy on medical QA vs GPT-4' and 'higher accuracy on SQL "
        "generation vs a rule baseline' belong to DIFFERENT clusters: same word "
        "(accuracy), but different task and comparator. Never group findings "
        "about different populations, comparators, outcomes, or opposite "
        "directions. Prefer a tight homogeneous cluster of 2-3 aligned findings "
        "over a large heterogeneous one. The claim must name the specific "
        "population, comparator, and endpoint.\n\n"
        f"Findings (id and phrase):\n{listing}\n\n"
        'Return JSON only: {"clusters":[{"claim":"<one specific sentence naming '
        'the population, comparator, and endpoint>","fact_ids":["id",...]}, '
        "...]}. Order clusters largest first. Only use ids from the list above."
    )


def densest_claim_cluster(
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    topic: str,
    *,
    min_sources: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Densest single-claim cluster with >= min_sources distinct source papers.

    Returns {"lead_fact_ids": [...], "claim": str}; "lead_fact_ids" is empty
    when no qualifying cluster exists or the writer model is unavailable.
    """
    settings = settings or load_settings()
    if not settings.writer_configured:
        return {"lead_fact_ids": []}
    seen_src: set[str] = set()
    rows: list[tuple[str, str]] = []
    for fid, fact in facts.items():
        if lanes.get(fid) != "A_core":
            continue
        phrase = _phrase(fact)
        source = _source_key(fact)
        if not phrase or not source or source in seen_src:
            continue
        seen_src.add(source)
        rows.append((fid, phrase[:240]))
        if len(rows) >= _MAX_FACTS:
            break
    if len(rows) < min_sources:
        return {"lead_fact_ids": []}
    try:
        resp = call_writer_with_fallback(
            settings,
            [{"role": "user", "content": _build_prompt(topic, rows)}],
            temperature=0.1,
            max_tokens=2000,
        )
    except (RuntimeError, ValueError, OSError, httpx.HTTPError):
        return {"lead_fact_ids": []}
    valid_ids = {fid for fid, _ in rows}
    best: dict[str, Any] = {"lead_fact_ids": []}
    best_sources = 0
    for cluster in _parse_clusters(resp.content):
        ids = [str(x) for x in (cluster.get("fact_ids") or []) if str(x) in valid_ids]
        picked: list[str] = []
        used: set[str] = set()
        for fid in ids:
            source = _source_key(facts[fid])
            if source and source not in used:
                used.add(source)
                picked.append(fid)
        if len(used) >= min_sources and len(used) > best_sources:
            best_sources = len(used)
            # Cite a bounded, newest-first subset of the agreeing sources: a tight
            # recent bundle reads as one bounded claim and lifts the citation
            # recency ratio, while the floor is preserved (never trim below
            # min_sources).
            picked.sort(key=lambda fid: _fact_year(facts[fid]), reverse=True)
            best = {
                "lead_fact_ids": picked[:max(_MAX_CITED_SOURCES, min_sources)],
                "claim": str(cluster.get("claim") or ""),
            }
    return best
