"""OSF Preprints (Center for Open Science) search.

Public JSON-API. No auth required. Supports filter[q] for full-text
keyword query. Smaller corpus than bioRxiv but covers social-science,
psychology, and policy preprints that don't land on bioRxiv.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_SEARCH = "https://api.osf.io/v2/preprints/"


class OSFSource:
    name = "osf"

    def __init__(self, settings: Settings) -> None:
        # Public endpoint — settings unused but kept on the constructor for
        # protocol symmetry with the other sources.
        _ = settings

    @property
    def configured(self) -> bool:
        return True

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "filter[q]": clean_text(query, limit=1024),
            "page[size]": str(min(retmax, 100)),
        }
        try:
            r = await client.get(_SEARCH, params=params, timeout=20.0)
            r.raise_for_status()
            data: Any = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        items = data.get("data", []) if isinstance(data, dict) else []
        hits: list[PaperHit] = []
        for item in items:
            hit = _parse_item(item)
            if hit is not None:
                hits.append(hit)
        return hits


def _parse_item(item: Any) -> PaperHit | None:
    if not isinstance(item, dict):
        return None
    attrs = item.get("attributes") or {}
    title = clean_text(attrs.get("title"), limit=500)
    if not title:
        return None
    doi = normalize_doi(attrs.get("doi"))
    date_published = clean_text(attrs.get("date_published"), limit=32)
    year = int_or_none(date_published[:4]) if date_published else None
    links = item.get("links") or {}
    return PaperHit(
        source="osf",
        title=title,
        abstract=clean_text(attrs.get("description"), limit=8000),
        year=year,
        url=clean_text(links.get("html"), limit=500)
        or (f"https://doi.org/{doi}" if doi else ""),
        doi=doi,
        pmid=None,
        venue="OSF Preprints",
    )
