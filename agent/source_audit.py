"""Sprint 52 — source-fact audit layer.

For each Tier-1 fact (with a PMID), fetches the source-paper abstract
via PubMed eutils and asks Gemma whether the DB's stored numeric /
directional claim is actually supported by the abstract. Catches the
DB-curation failure mode discovered live on the rapamycin run (Sprint
51): DB stored 'male 14% / female 9%' for Harrison 2009 when the
abstract actually says '14% females / 9% males' for 90th-percentile
mortality (not median lifespan). That thesis dies on this audit.

Pipeline:
    frontier_review -> source_audit -> survives | dies | needs_extraction

Universal: no domain literals. PubMed eutils used as a generic
abstract retriever; facts without a PMID bucket into needs_extraction.
Tolerant of HTTP / JSON / LLM failures — never raises.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from agent.llm_client import call_judge, call_writer_with_fallback
from agent.settings import Settings
from agent.source_corpus import SourcePassage, get_best_source

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_VERDICTS = ("survives", "dies", "needs_extraction")
_JUDGES = ("gemma", "mimo", "both")  # 'both' runs dual-judge consensus
_CONSENSUS_DISAGREE = "disagreement"  # survives-vs-dies -> human review


@dataclass(frozen=True, slots=True)
class FactVerdict:
    fact_id: str
    verdict: str
    db_value: str
    source_quote: str
    reason: str
    pmid: str
    judge: str = "gemma"
    source_tier: str = "abstract"  # abstract | pmc_fulltext | researka_corpus
    anchor_hits: int = 0           # numeric-anchor matches in source
    # Dual-judge fields (populated only when judge='both'):
    secondary_verdict: str = ""    # other judge's verdict
    secondary_judge: str = ""      # 'mimo' or 'gemma'
    secondary_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, "verdict": self.verdict,
                "db_value": self.db_value, "pmid": self.pmid,
                "judge": self.judge, "source_tier": self.source_tier,
                "anchor_hits": self.anchor_hits,
                "source_quote": self.source_quote, "reason": self.reason,
                "secondary_verdict": self.secondary_verdict,
                "secondary_judge": self.secondary_judge,
                "secondary_reason": self.secondary_reason}


@dataclass(frozen=True, slots=True)
class SourceAuditReport:
    topic: str
    snapshot_utc: str
    facts_inspected: int
    survives: int
    dies: int
    needs_extraction: int
    verdicts: tuple[FactVerdict, ...]
    disagreement: int = 0  # dual-judge survives-vs-dies splits

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "snapshot_utc": self.snapshot_utc,
                "facts_inspected": self.facts_inspected,
                "survives": self.survives, "dies": self.dies,
                "needs_extraction": self.needs_extraction,
                "disagreement": self.disagreement,
                "verdicts": [v.as_dict() for v in self.verdicts]}


def fetch_pubmed_abstract(
    pmid: str, *, client: httpx.Client, ncbi_api_key: str = "",
) -> str:
    """eutils efetch; returns abstract text or '' on any error."""
    if not pmid.strip():
        return ""
    params: dict[str, str] = {
        "db": "pubmed", "id": pmid.strip(),
        "rettype": "abstract", "retmode": "text",
    }
    if ncbi_api_key.strip():
        params["api_key"] = ncbi_api_key.strip()
    try:
        r = client.get(_EUTILS, params=params, timeout=15.0)
        r.raise_for_status()
        return str(r.text).strip()
    except (httpx.HTTPError, ValueError):
        return ""


def _fact_summary(fact: dict[str, Any]) -> str:
    paper = fact.get("source_paper") or {}
    nv = fact.get("numeric_value")
    units = str(fact.get("units") or "")
    return (
        f"Claim: '{fact.get('canonical_phrase', '')}' | "
        f"value: {nv}{units} | "
        f"population: '{fact.get('population') or '?'}' | "
        f"intervention: '{fact.get('intervention') or '?'}' | "
        f"source: {paper.get('title', '?')!r} ({paper.get('year', '?')})"
    )


def _parse_verdict(raw: str) -> dict[str, Any]:
    """Tolerant JSON parser — strips code fences, returns {} on failure."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def verify_fact(
    fact: dict[str, Any], abstract: str, *, settings: Settings,
    judge: str = "gemma", passage: SourcePassage | None = None,
) -> FactVerdict:
    """Single LLM call: does the abstract support the DB fact?
    judge='gemma' (default, fast) or 'mimo' (stronger nuance, Gemma
    fallback on runaway). Neither generated the inputs.
    `passage` (optional) carries source-cascade provenance so the
    verdict knows whether it was checked against abstract vs PMC
    full-text vs Researka corpus."""
    fact_id = str(fact.get("fact_id") or "")
    paper = fact.get("source_paper") or {}
    pmid = str(paper.get("pmid") or "")
    nv = fact.get("numeric_value")
    units = str(fact.get("units") or "")
    db_value = f"{nv}{units}" if nv is not None else "(no numeric)"
    if judge not in _JUDGES:
        judge = "gemma"
    tier = passage.tier if passage else "abstract"
    hits = passage.anchor_hits if passage else 0
    text_to_judge = passage.text if passage else abstract
    if not text_to_judge:
        return FactVerdict(
            fact_id=fact_id, verdict="needs_extraction",
            db_value=db_value, pmid=pmid, source_quote="",
            reason="abstract_unavailable", judge=judge,
            source_tier=tier, anchor_hits=hits,
        )
    configured = (settings.writer_configured if judge == "mimo"
                  else settings.judge_configured)
    if not configured:
        return FactVerdict(
            fact_id=fact_id, verdict="needs_extraction",
            db_value=db_value, pmid=pmid, source_quote="",
            reason=f"{judge}_not_configured", judge=judge,
            source_tier=tier, anchor_hits=hits,
        )
    tier_label = {
        "abstract": "PUBMED ABSTRACT",
        "pmc_fulltext": "PMC FULL-TEXT (focused passages around target value)",
        "researka_corpus": "RESEARKA CORPUS PASSAGES",
    }.get(tier, "SOURCE TEXT")
    if passage and passage.subgroup_top_score > 0:
        tier_label += (f" — passages pre-sorted by DB-population match; "
                       f"top span subgroup_score={passage.subgroup_top_score}")
    user = (
        f"FACT TO VERIFY:\n{_fact_summary(fact)}\n\n"
        f"{tier_label} (first 5000 chars):\n{text_to_judge[:5000]}\n\n"
        "Decide whether the abstract supports the fact AS STATED. Check "
        "BOTH the numeric value AND which subgroup it applies to "
        "(sex / strain / dose / metric type — e.g. median lifespan vs "
        "90th-percentile mortality vs maximum lifespan). The fact 'dies' "
        "if the abstract states a different value, attributes the value "
        "to a different subgroup, or labels the metric differently. The "
        "fact 'survives' only when both the value AND its attribution "
        "match. Use 'needs_extraction' only when the abstract does not "
        "discuss the value at all (e.g. number is in body text, not "
        "abstract).\n\nRespond as VALID JSON only:\n"
        '{"verdict": "survives|dies|needs_extraction", '
        '"source_quote": "<exact phrase from abstract supporting the verdict>", '
        '"reason": "<1 sentence explanation>"}'
    )
    msgs = [
        {"role": "system",
         "content": "You are a source-truth auditor. Reply with JSON only."},
        {"role": "user", "content": user},
    ]
    try:
        if judge == "mimo":
            resp = call_writer_with_fallback(
                settings, msgs, temperature=0.0, max_tokens=1500,
            )
        else:
            resp = call_judge(settings, msgs, temperature=0.0)
    except (RuntimeError, OSError, httpx.HTTPError) as e:
        return FactVerdict(
            fact_id=fact_id, verdict="needs_extraction",
            db_value=db_value, pmid=pmid, source_quote="",
            reason=f"{judge}_call_failed:{type(e).__name__}", judge=judge,
            source_tier=tier, anchor_hits=hits,
        )
    parsed = _parse_verdict(resp.content)
    verdict = str(parsed.get("verdict") or "needs_extraction").lower()
    if verdict not in _VERDICTS:
        verdict = "needs_extraction"
    return FactVerdict(
        fact_id=fact_id, verdict=verdict, db_value=db_value, pmid=pmid,
        source_quote=str(parsed.get("source_quote") or "")[:400],
        reason=str(parsed.get("reason") or "")[:400], judge=judge,
        source_tier=tier, anchor_hits=hits,
    )


def _reconcile(primary: FactVerdict, secondary: FactVerdict) -> FactVerdict:
    """Merge two judges' verdicts into one consensus FactVerdict.
    Consensus rules (`p`, `s` = primary, secondary verdict):
      same -> p (high confidence)
      survives + needs_extraction -> survives (weak confirm)
      dies + needs_extraction -> dies (strong — silent contradict)
      survives + dies -> 'disagreement' (human review)
      both needs_extraction -> needs_extraction
    Carries the secondary verdict + judge + reason for full audit trail."""
    p, s = primary.verdict, secondary.verdict
    if p == s:
        consensus = p
    elif _CONSENSUS_DISAGREE in (p, s) or {p, s} == {"survives", "dies"}:
        consensus = _CONSENSUS_DISAGREE
    elif "dies" in (p, s):
        consensus = "dies"
    elif "survives" in (p, s):
        consensus = "survives"
    else:
        consensus = "needs_extraction"
    return FactVerdict(
        fact_id=primary.fact_id, verdict=consensus,
        db_value=primary.db_value, pmid=primary.pmid,
        judge="both", source_tier=primary.source_tier,
        anchor_hits=primary.anchor_hits,
        source_quote=primary.source_quote, reason=primary.reason,
        secondary_verdict=secondary.verdict,
        secondary_judge=secondary.judge,
        secondary_reason=secondary.reason,
    )


def run_source_audit(
    *, topic: str, snapshot_utc: str, facts: list[dict[str, Any]],
    settings: Settings, client: httpx.Client, ncbi_api_key: str = "",
    judge: str = "gemma", escalate: bool = True,
) -> SourceAuditReport:
    """Audit each fact against its source-paper abstract, escalating
    to PMC full-text and Researka corpus when the abstract lacks a
    numeric anchor for the target value. Caches abstracts per-PMID.
    Never raises.

    `escalate=False` keeps v1 behaviour (abstract only)."""
    cache: dict[str, str] = {}
    verdicts: list[FactVerdict] = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        paper = f.get("source_paper") or {}
        pmid = str(paper.get("pmid") or "")
        if pmid and pmid not in cache:
            cache[pmid] = fetch_pubmed_abstract(
                pmid, client=client, ncbi_api_key=ncbi_api_key,
            )
        abstract = cache.get(pmid, "")
        passage = (get_best_source(
            f, abstract=abstract, client=client, settings=settings,
            ncbi_api_key=ncbi_api_key,
        ) if escalate else None)
        if judge == "both":
            v_gemma = verify_fact(f, abstract, settings=settings,
                                  judge="gemma", passage=passage)
            v_mimo = verify_fact(f, abstract, settings=settings,
                                 judge="mimo", passage=passage)
            verdicts.append(_reconcile(v_gemma, v_mimo))
        else:
            verdicts.append(verify_fact(
                f, abstract, settings=settings, judge=judge, passage=passage,
            ))
    counts: dict[str, int] = dict.fromkeys(_VERDICTS, 0)
    counts[_CONSENSUS_DISAGREE] = 0
    for vd in verdicts:
        counts[vd.verdict] = counts.get(vd.verdict, 0) + 1
    return SourceAuditReport(
        topic=topic, snapshot_utc=snapshot_utc,
        facts_inspected=len(verdicts), survives=counts["survives"],
        dies=counts["dies"], needs_extraction=counts["needs_extraction"],
        disagreement=counts[_CONSENSUS_DISAGREE],
        verdicts=tuple(verdicts),
    )
