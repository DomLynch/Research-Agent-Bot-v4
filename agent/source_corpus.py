"""Sprint 54 — abstract -> PMC -> Researka cascade + focused spans.

When PubMed abstract can't verify a fact (numeric value lives in body
text / figures / tables), escalates to PMC OA full-text then Researka
corpus search. Returns ±window-char passages around each numeric
anchor so the LLM judge sees candidate spans, not the full paper.
Universal: no domain literals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from agent.settings import Settings

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"\w+")
TIERS = ("abstract", "pmc_fulltext", "researka_corpus")


@dataclass(frozen=True, slots=True)
class SourcePassage:
    tier: str           # one of TIERS
    text: str           # focused span (or full text if no anchor matched)
    full_length: int    # bytes of original retrieved source (audit trail)
    anchor_hits: int    # how many numeric-anchor matches were found
    subgroup_top_score: float = 0.0  # 0..1, best span's DB-population match


def fetch_pmc_fulltext(
    pmcid: str, *, client: httpx.Client, ncbi_api_key: str = "",
) -> str:
    """eutils efetch db=pmc, XML stripped to plain text. '' on failure."""
    pid = pmcid.strip().lstrip("PMC")
    if not pid:
        return ""
    params: dict[str, str] = {"db": "pmc", "id": pid,
                              "rettype": "full", "retmode": "xml"}
    if ncbi_api_key.strip():
        params["api_key"] = ncbi_api_key.strip()
    try:
        r = client.get(_EUTILS, params=params, timeout=30.0)
        r.raise_for_status()
        return _WS.sub(" ", _TAG.sub(" ", r.text)).strip()
    except (httpx.HTTPError, ValueError):
        return ""


def fetch_researka_corpus(
    query: str, *, client: httpx.Client, settings: Settings,
    top_k: int = 3,
) -> str:
    """Tertiary fallback: vector retrieval over the Researka corpus.
    Concatenates abstracts of the top-k matches."""
    base = settings.researka_database_url.rstrip("/")
    tok = settings.researka_database_token.strip()
    if not base or not tok or not query.strip():
        return ""
    try:
        r = client.post(
            f"{base}/api/v1/corpus/search",
            headers={"X-Researka-Token": tok},
            json={"query": query[:512], "top_k": top_k},
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return ""
    if not isinstance(data, list):
        return ""
    chunks: list[str] = []
    for item in data:
        if isinstance(item, dict):
            txt = str(item.get("abstract") or item.get("text") or "")
            if txt:
                chunks.append(txt)
    return "\n\n".join(chunks)


def _value_patterns(target: float, units: str) -> list[str]:
    """Anchor regex set: value as-is + int form, with unit variants."""
    units_s = units.strip()
    forms = {f"{target:g}",
             f"{int(target)}" if target == int(target) else f"{target:g}"}
    pats: list[str] = []
    for v in forms:
        ve = re.escape(v)
        if units_s == "%":
            pats += [rf"\b{ve}\s*%", rf"~\s*{ve}\s*%", rf"about\s+{ve}\s*%"]
        elif units_s:
            pats += [rf"\b{ve}\s*{re.escape(units_s)}", rf"\b{ve}\b"]
        else:
            pats.append(rf"\b{ve}\b")
    return pats


def extract_focused_spans(
    text: str, target_value: float | None, units: str = "",
    window: int = 300, max_spans: int = 5,
) -> list[str]:
    """Find each occurrence of target_value in `text`, return ±window
    chars around it. Dedupes near-identical spans."""
    if target_value is None or not text:
        return []
    raw_spans: list[str] = []
    for pat in _value_patterns(target_value, units or ""):
        try:
            for m in re.finditer(pat, text):
                lo = max(0, m.start() - window)
                hi = min(len(text), m.end() + window)
                raw_spans.append(text[lo:hi])
        except re.error:
            continue
    # Dedup: drop spans that are substrings of an already-kept span.
    out: list[str] = []
    for s in raw_spans:
        if not any(s in prev for prev in out):
            out.append(s)
        if len(out) >= max_spans:
            break
    return out


def _tokenize(s: str) -> frozenset[str]:
    return frozenset(t.lower() for t in _TOKEN.findall(s) if len(t) >= 2)


def subgroup_score(
    population: str, intervention: str, span: str,
) -> float:
    """Token-recall: fraction of DB population+intervention tokens
    that appear in `span`. 0..1, higher = better population match.
    Universal: word-char tokenization, no domain literals."""
    db_tokens = _tokenize(f"{population} {intervention}")
    if not db_tokens:
        return 0.0
    overlap = db_tokens & _tokenize(span)
    return round(len(overlap) / len(db_tokens), 3)


def rank_spans_by_subgroup(
    spans: list[str], population: str, intervention: str,
) -> list[tuple[float, str]]:
    """Stable-sort spans by subgroup score desc; preserves original
    order when scores tie."""
    return sorted(
        ((subgroup_score(population, intervention, s), s) for s in spans),
        key=lambda p: p[0], reverse=True,
    )


def get_best_source(
    fact: dict[str, Any], *, abstract: str, client: httpx.Client,
    settings: Settings, ncbi_api_key: str = "",
) -> SourcePassage:
    """Cascade abstract -> PMC OA -> Researka corpus; return the first
    tier with numeric-anchor matches, spans pre-ranked by subgroup
    match. Falls back to raw abstract if nothing anchors."""
    paper = fact.get("source_paper") or {}
    nv = fact.get("numeric_value")
    units = str(fact.get("units") or "")
    target = float(nv) if isinstance(nv, (int, float)) else None
    pop = str(fact.get("population") or "")
    intv = str(fact.get("intervention") or "")

    def _build(spans: list[str], tier: str, full_len: int) -> SourcePassage:
        if pop or intv:
            ranked = rank_spans_by_subgroup(spans, pop, intv)
            ordered = [s for _, s in ranked]
            top = ranked[0][0] if ranked else 0.0
        else:
            ordered, top = spans, 0.0
        return SourcePassage(
            tier=tier, text="\n---\n".join(ordered[:5]),
            full_length=full_len, anchor_hits=len(spans),
            subgroup_top_score=top,
        )

    abs_spans = extract_focused_spans(abstract, target, units)
    if abs_spans:
        return _build(abs_spans, "abstract", len(abstract))

    pmcid = str(paper.get("pmcid") or "")
    if pmcid:
        full = fetch_pmc_fulltext(
            pmcid, client=client, ncbi_api_key=ncbi_api_key,
        )
        if full:
            spans = extract_focused_spans(full, target, units)
            if spans:
                return _build(spans, "pmc_fulltext", len(full))

    query = str(fact.get("canonical_phrase") or paper.get("title") or "")
    corpus = fetch_researka_corpus(query, client=client, settings=settings)
    if corpus:
        spans = extract_focused_spans(corpus, target, units)
        if spans:
            return _build(spans, "researka_corpus", len(corpus))

    return SourcePassage(
        tier="abstract", text=abstract, full_length=len(abstract),
        anchor_hits=0, subgroup_top_score=0.0,
    )
