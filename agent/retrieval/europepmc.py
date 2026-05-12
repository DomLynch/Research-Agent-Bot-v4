"""Europe PMC search (covers PubMed mirror + preprints incl. bioRxiv/medRxiv).

Public endpoint, no API key. The result list normalises PMID, DOI, and
year so the universal dedup catches overlaps with PubMed/Crossref/
OpenAlex without keeping duplicate rows.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMCSource:
    name = "europepmc"

    def __init__(self, settings: Settings) -> None:
        # Public endpoint; no per-request auth required.
        self._email = settings.crossref_polite_email.strip()

    @property
    def configured(self) -> bool:
        return True

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "query": clean_text(query, limit=2000),
            "format": "json",
            "pageSize": str(min(retmax, 1000)),
            "resultType": "core",
        }
        if self._email:
            params["email"] = self._email
        try:
            r = await client.get(_SEARCH, params=params, timeout=20.0)
            r.raise_for_status()
            data: Any = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        items = (
            data.get("resultList", {}).get("result", [])
            if isinstance(data, dict) else []
        )
        hits: list[PaperHit] = []
        for item in items:
            hit = _parse_item(item)
            if hit is not None:
                hits.append(hit)
        return hits


def _parse_item(item: Any) -> PaperHit | None:
    if not isinstance(item, dict):
        return None
    title = clean_text(item.get("title"), limit=500)
    if not title:
        return None
    pmid = clean_text(item.get("pmid"), limit=32) or None
    doi = normalize_doi(item.get("doi"))
    venue = clean_text(item.get("journalTitle"), limit=200) or None
    year = int_or_none(item.get("pubYear"))
    abstract = clean_text(item.get("abstractText"), limit=8000)
    source_db = clean_text(item.get("source"), limit=16) or "MED"
    eid = clean_text(item.get("id"), limit=64)
    url = (
        f"https://europepmc.org/article/{source_db}/{eid}"
        if eid else (f"https://doi.org/{doi}" if doi else "")
    )
    return PaperHit(
        source="europepmc",
        title=title,
        abstract=abstract,
        year=year,
        url=url,
        doi=doi,
        pmid=pmid,
        venue=venue,
    )
