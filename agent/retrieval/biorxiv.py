"""bioRxiv / medRxiv preprint search.

bioRxiv has no native keyword-search endpoint; we use Europe PMC's
preprint filter (`SRC:PPR`) as the search backend and tag the source as
`biorxiv` so downstream dedup still works. Pure preprint slice (PPR =
preprints, excludes peer-reviewed mirrors).
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class BioRxivSource:
    name = "biorxiv"

    def __init__(self, settings: Settings) -> None:
        self._email = settings.crossref_polite_email.strip()

    @property
    def configured(self) -> bool:
        return True

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "query": f"({clean_text(query, limit=1800)}) AND SRC:PPR",
            "format": "json",
            "pageSize": str(min(retmax, 500)),
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
    doi = normalize_doi(item.get("doi"))
    eid = clean_text(item.get("id"), limit=64)
    return PaperHit(
        source="biorxiv",
        title=title,
        abstract=clean_text(item.get("abstractText"), limit=8000),
        year=int_or_none(item.get("pubYear")),
        url=(
            f"https://europepmc.org/article/PPR/{eid}"
            if eid else (f"https://doi.org/{doi}" if doi else "")
        ),
        doi=doi,
        pmid=clean_text(item.get("pmid"), limit=32) or None,
        venue=clean_text(item.get("journalTitle") or "preprint", limit=200) or None,
    )
