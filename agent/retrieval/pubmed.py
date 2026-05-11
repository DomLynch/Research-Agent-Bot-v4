"""PubMed via NCBI E-utilities.

Two-stage flow:
  1. esearch — query -> list of PMIDs
  2. efetch — PMIDs -> XML metadata
Both stages honour the NCBI rate-limit boost when an API key is supplied
(3/sec -> 10/sec) and the polite-pool email when provided. Failures are
silent: an exception returns an empty list so the unified search can fall
back to other sources.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedSource:
    name = "pubmed"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.ncbi_api_key.strip()
        self._email = settings.crossref_polite_email.strip()

    @property
    def configured(self) -> bool:
        return True  # public; api_key only affects rate limit

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 500
    ) -> list[PaperHit]:
        pmids = await self._esearch(client, query, retmax)
        if not pmids:
            return []
        return await self._efetch(client, pmids)

    async def _esearch(
        self, client: httpx.AsyncClient, query: str, retmax: int
    ) -> list[str]:
        params: dict[str, str] = {
            "db": "pubmed",
            "term": clean_text(query, limit=2000),
            "retmax": str(retmax),
            "retmode": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        if self._email:
            params["email"] = self._email
        try:
            r = await client.get(_ESEARCH, params=params, timeout=20.0)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        ids = data.get("esearchresult", {}).get("idlist") or []
        return [str(p) for p in ids if p]

    async def _efetch(
        self, client: httpx.AsyncClient, pmids: list[str]
    ) -> list[PaperHit]:
        """Batch-fetch in chunks; PubMed rejects long GET URLs at ~200+ ids."""
        hits: list[PaperHit] = []
        for i in range(0, len(pmids), 100):
            chunk = pmids[i : i + 100]
            params: dict[str, str] = {
                "db": "pubmed",
                "id": ",".join(chunk),
                "retmode": "xml",
            }
            if self._api_key:
                params["api_key"] = self._api_key
            if self._email:
                params["email"] = self._email
            try:
                r = await client.get(_EFETCH, params=params, timeout=30.0)
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            hits.extend(_parse_pubmed_xml(r.text))
        return hits


def _parse_pubmed_xml(xml: str) -> list[PaperHit]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    hits: list[PaperHit] = []
    for article in root.findall(".//PubmedArticle"):
        hit = _parse_article(article)
        if hit is not None:
            hits.append(hit)
    return hits


def _parse_article(article: Element) -> PaperHit | None:
    pmid_el = article.find(".//PMID")
    pmid = clean_text(pmid_el.text if pmid_el is not None else "", limit=32) or None
    title_el = article.find(".//ArticleTitle")
    title = clean_text(title_el.text if title_el is not None else "", limit=500)
    if not title:
        return None
    abstract_parts: list[str] = []
    for ab in article.findall(".//AbstractText"):
        if ab.text:
            abstract_parts.append(ab.text)
    abstract = clean_text(" ".join(abstract_parts), limit=8000)
    year_el = article.find(".//PubDate/Year")
    year = int_or_none(year_el.text if year_el is not None else None)
    journal_el = article.find(".//Journal/Title")
    venue = clean_text(journal_el.text if journal_el is not None else "", limit=200) or None
    doi: str | None = None
    for aid in article.findall(".//ArticleId"):
        if aid.get("IdType") == "doi" and aid.text:
            doi = normalize_doi(aid.text)
            break
    return PaperHit(
        source="pubmed",
        title=title,
        abstract=abstract,
        year=year,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        doi=doi,
        pmid=pmid,
        venue=venue,
    )
