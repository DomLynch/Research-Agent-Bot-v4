"""LLM claim clustering — group a topic's A_core facts into single-claim
clusters so a memo can lead with the densest agreeing cluster (one
outcome/endpoint, one direction of effect) instead of a scattered pile of a
broad topic's many sub-claims.

The deterministic token-overlap clusterer cannot group synonymous endpoints
(survival / all-cause mortality / overall survival) and is fooled by shared
statistical boilerplate (hazard ratio / confidence interval). This pass asks
the locked writer model (MiMo, Gemma fallback) to read the candidate phrases
and return claim groups. Every returned fact_id is validated to exist, be
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


def _phrase(fact: dict[str, Any]) -> str:
    return str(fact.get("canonical_phrase") or fact.get("source_excerpt") or "").strip()


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
        "into coherent claim clusters. A cluster is a set of findings that all "
        "support ONE specific claim: the SAME outcome/endpoint and the SAME "
        "direction of effect (for example, all show reduced all-cause "
        "mortality), even when worded differently. Never group findings about "
        "different outcomes, different interventions, or opposite directions.\n\n"
        f"Findings (id and phrase):\n{listing}\n\n"
        'Return JSON only: {"clusters":[{"claim":"<one sentence>",'
        '"fact_ids":["id",...]}, ...]}. Order clusters largest first. Only use '
        "ids from the list above."
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
            best = {"lead_fact_ids": picked, "claim": str(cluster.get("claim") or "")}
    return best
