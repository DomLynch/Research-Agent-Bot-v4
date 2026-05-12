"""CORE (CORE.ac.uk) Works API.

Open-access aggregator across institutional repositories + publishers.
Auth: `Authorization: Bearer <CORE_API_KEY>`. Without a key the endpoint
still serves on a low-quota anonymous tier; we gate `configured` on the
key so the source is skipped when not provisioned.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_SEARCH = "https://api.core.ac.uk/v3/search/works"


class COREsource:
    name = "core"

    def __init__(self, settings: Settings) -> None:
        self._key = settings.core_api_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "q": clean_text(query, limit=1024),
            "limit": str(min(retmax, 100)),
        }
        headers: dict[str, str] = (
            {"Authorization": f"Bearer {self._key}"} if self._key else {}
        )
        try:
            r = await client.get(_SEARCH, params=params, headers=headers, timeout=20.0)
            r.raise_for_status()
            data: Any = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        items = data.get("results", []) if isinstance(data, dict) else []
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
    url = clean_text(
        item.get("downloadUrl") or item.get("sourceFulltextUrls") or item.get("displayUrl"),
        limit=500,
    )
    return PaperHit(
        source="core",
        title=title,
        abstract=clean_text(item.get("abstract"), limit=8000),
        year=int_or_none(item.get("yearPublished")),
        url=url,
        doi=doi,
        pmid=None,
        venue=clean_text(item.get("publisher"), limit=200) or None,
    )
