"""Semantic Scholar Graph API.

API key (settings.semantic_scholar_api_key) goes in the `x-api-key`
header. Without a key the endpoint still serves but at much lower
quota; we gate `configured` on the key so a misconfigured environment
silently skips this source instead of getting throttled.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarSource:
    name = "semantic_scholar"

    def __init__(self, settings: Settings) -> None:
        self._key = settings.semantic_scholar_api_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "query": clean_text(query, limit=300),
            "limit": str(min(retmax, 100)),
            "fields": "title,abstract,year,externalIds,venue,url",
        }
        headers: dict[str, str] = {"x-api-key": self._key} if self._key else {}
        try:
            r = await client.get(_SEARCH, params=params, headers=headers, timeout=20.0)
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
    title = clean_text(item.get("title"), limit=500)
    if not title:
        return None
    ext = item.get("externalIds") or {}
    doi = normalize_doi(ext.get("DOI"))
    pmid = clean_text(ext.get("PubMed"), limit=32) or None
    return PaperHit(
        source="semantic_scholar",
        title=title,
        abstract=clean_text(item.get("abstract"), limit=8000),
        year=int_or_none(item.get("year")),
        url=clean_text(item.get("url"), limit=500),
        doi=doi,
        pmid=pmid,
        venue=clean_text(item.get("venue"), limit=200) or None,
    )
