"""Sprint 54 — multi-source full-text cascade + focused-span retrieval.

When PubMed abstract alone can't verify a DB fact (numeric value lives
in body text / figures / tables, not the summary), this module
escalates to richer sources and returns a focused passage centered on
the target value:

    abstract  ->  PMC OA full-text (eutils efetch db=pmc)
              ->  Researka corpus search (vector retrieval, tertiary)

Focused-span retrieval: regex-anchor every occurrence of the target
numeric value in the retrieved text, return ±window chars around each
match. The LLM judge then sees the candidate passages (~600 chars
each) instead of a 150KB full paper.

Universal: no domain literals. PMC is generic-biomedical; corpus
search is general-purpose.
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
TIERS = ("abstract", "pmc_fulltext", "researka_corpus")


@dataclass(frozen=True, slots=True)
class SourcePassage:
    tier: str           # one of TIERS
    text: str           # focused span (or full text if no anchor matched)
    full_length: int    # bytes of original retrieved source (audit trail)
    anchor_hits: int    # how many numeric-anchor matches were found


def _strip_xml(xml: str) -> str:
    """Naive XML -> plain text. Drops tags, collapses whitespace."""
    return _WS.sub(" ", _TAG.sub(" ", xml)).strip()


def fetch_pmc_fulltext(
    pmcid: str, *, client: httpx.Client, ncbi_api_key: str = "",
) -> str:
    """eutils efetch db=pmc -> plain-text body. '' on any failure."""
    pid = pmcid.strip().lstrip("PMC")
    if not pid:
        return ""
    params: dict[str, str] = {
        "db": "pmc", "id": pid, "rettype": "full", "retmode": "xml",
    }
    if ncbi_api_key.strip():
        params["api_key"] = ncbi_api_key.strip()
    try:
        r = client.get(_EUTILS, params=params, timeout=30.0)
        r.raise_for_status()
        return _strip_xml(r.text)
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
    """Universal numeric-anchor regex set. Matches the value as-is,
    its integer form, ~-prefixed, and 'about' variants."""
    units_s = units.strip()
    raw = f"{target:g}"
    intval = f"{int(target)}" if target == int(target) else raw
    base = [raw, intval]
    unit_alt = re.escape(units_s) if units_s else r""
    patterns: list[str] = []
    for v in set(base):
        ve = re.escape(v)
        if units_s == "%":
            patterns += [rf"\b{ve}\s*%", rf"~\s*{ve}\s*%",
                         rf"about\s+{ve}\s*%"]
        elif unit_alt:
            patterns += [rf"\b{ve}\s*{unit_alt}", rf"\b{ve}\b"]
        else:
            patterns.append(rf"\b{ve}\b")
    return patterns


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


def get_best_source(
    fact: dict[str, Any], *, abstract: str, client: httpx.Client,
    settings: Settings, ncbi_api_key: str = "",
) -> SourcePassage:
    """Cascade: try abstract; if no numeric anchor, escalate to PMC
    OA; if still none, try Researka corpus. Returns the tier with the
    most numeric-anchor matches (PMC almost always wins for sex-
    stratified body-text claims)."""
    paper = fact.get("source_paper") or {}
    nv = fact.get("numeric_value")
    units = str(fact.get("units") or "")
    target = float(nv) if isinstance(nv, (int, float)) else None

    abs_spans = extract_focused_spans(abstract, target, units)
    if abs_spans:
        return SourcePassage(
            tier="abstract",
            text="\n---\n".join(abs_spans),
            full_length=len(abstract), anchor_hits=len(abs_spans),
        )

    pmcid = str(paper.get("pmcid") or "")
    if pmcid:
        full = fetch_pmc_fulltext(
            pmcid, client=client, ncbi_api_key=ncbi_api_key,
        )
        if full:
            spans = extract_focused_spans(full, target, units)
            if spans:
                return SourcePassage(
                    tier="pmc_fulltext",
                    text="\n---\n".join(spans),
                    full_length=len(full), anchor_hits=len(spans),
                )

    query = str(fact.get("canonical_phrase") or paper.get("title") or "")
    corpus = fetch_researka_corpus(query, client=client, settings=settings)
    if corpus:
        spans = extract_focused_spans(corpus, target, units)
        if spans:
            return SourcePassage(
                tier="researka_corpus",
                text="\n---\n".join(spans),
                full_length=len(corpus), anchor_hits=len(spans),
            )

    return SourcePassage(
        tier="abstract", text=abstract, full_length=len(abstract),
        anchor_hits=0,
    )
