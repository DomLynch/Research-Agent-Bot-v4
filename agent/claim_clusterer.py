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


def _claim_is_focused(claim: str) -> bool:
    """Whether a cluster's claim reads as one bounded comparison, not a run-on
    list of disparate figures. M3 sometimes lumps unrelated endpoints into a
    single cluster whose "claim" is a laundry-list (";"-joined, "including ...",
    many distinct numbers) — the reviewer's terminal reject. A focused claim is
    concise, names one comparison, and carries at most a couple of figures."""
    text = claim.strip()
    if not text or len(text) > 200:
        return False
    if ";" in text or "including" in text.lower():
        return False
    return len(re.findall(r"\d+(?:\.\d+)?", text)) <= 3


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
        "into claim clusters. A cluster is the set of findings that support ONE "
        "bounded claim: the SAME intervention, the SAME outcome (treat synonyms "
        "and one outcome family as the same — survival / lifespan / mortality are "
        "ONE outcome; accuracy / % correct are ONE outcome), and the SAME "
        "direction of effect. GROUP findings that differ only by a SUBGROUP of "
        "one model or population — age, sex, dose, strain, cohort, or benchmark "
        "within one task family; the claim then summarises the range across "
        "subgroups. For example, 'rapamycin extends median lifespan in middle-"
        "aged mice' and 'rapamycin reduces mortality in NIA-ITP female mice' are "
        "the SAME cluster (one intervention, survival outcome, same direction, "
        "mouse subgroups). Only SPLIT into different clusters when a finding is "
        "about a genuinely DIFFERENT disease/indication or domain, a DIFFERENT "
        "outcome, or the OPPOSITE direction — e.g. 'metformin lowers mortality in "
        "diabetics' vs 'metformin lowers mortality in sepsis patients' are "
        "DIFFERENT clusters (different diseases), and 'reduces cancer incidence' "
        "is a DIFFERENT cluster from 'extends lifespan'. Prefer the LARGEST "
        "bounded cluster the evidence supports; never merge across the split "
        "lines above. The claim names the intervention, the population class, and "
        "the outcome.\n\n"
        f"Findings (id and phrase):\n{listing}\n\n"
        'Return JSON only: {"clusters":[{"claim":"<one sentence naming the '
        'intervention, population class, and outcome>","fact_ids":["id",...]}, '
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
        # Surface the population to the model: the canonical_phrase alone is often
        # organism/indication-blind (a house-cricket survival finding reads as
        # "treated individuals survived longer, HR 0.42" — indistinguishable from a
        # mouse one), so a different-organism or different-disease receipt gets
        # lumped into a claim it contradicts. The split rule keys on this field.
        population = str(fact.get("population") or "").strip()
        text = (f"{phrase[:200]} [population: {population[:80]}]"
                if population else phrase[:240])
        rows.append((fid, text))
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
    best_key: tuple[int, int] = (-1, 0)
    for cluster in _parse_clusters(resp.content):
        ids = [str(x) for x in (cluster.get("fact_ids") or []) if str(x) in valid_ids]
        picked: list[str] = []
        used: set[str] = set()
        for fid in ids:
            source = _source_key(facts[fid])
            if source and source not in used:
                used.add(source)
                picked.append(fid)
        if len(used) < min_sources:
            continue
        claim = str(cluster.get("claim") or "")
        # Prefer a FOCUSED single-claim cluster over a larger laundry-list one:
        # M3 orders clusters largest-first, but the biggest cluster is often the
        # heterogeneous pile the reviewer rejects. Rank by (focused, sources) so a
        # tight 3-source bounded claim wins over a sprawling 10-source figure list;
        # fall back to the largest only when none is focused.
        key = (1 if _claim_is_focused(claim) else 0, len(used))
        if key > best_key:
            best_key = key
            # Cite a bounded, newest-first subset of the agreeing sources: a tight
            # recent bundle reads as one bounded claim and lifts the citation
            # recency ratio, while the floor is preserved (never trim below
            # min_sources).
            picked.sort(key=lambda fid: _fact_year(facts[fid]), reverse=True)
            best = {
                "lead_fact_ids": picked[:max(_MAX_CITED_SOURCES, min_sources)],
                "claim": claim,
            }
    return best
