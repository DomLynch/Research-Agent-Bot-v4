"""Researka internal canonical index.

Internal hot-index at `RESEARKA_DATABASE_URL` (default
https://database.researka.org/api/v1/search). Auth: bearer token
`RESEARKA_DATABASE_TOKEN`. Both must be configured or the source is
skipped. Endpoint contract: GET with `q=<query>&limit=<n>`; response
`{results: [{title, abstract, doi, pmid, year, venue, url}, ...]}`.
Tolerant parser — unknown extra fields are ignored.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings


class ResearkaSource:
    name = "researka"

    def __init__(self, settings: Settings) -> None:
        self._base = settings.researka_database_url.rstrip("/")
        self._token = settings.researka_database_token.strip()

    @property
    def configured(self) -> bool:
        return bool(self._base) and bool(self._token)

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        if not self.configured:
            return []
        params: dict[str, str] = {
            "q": clean_text(query, limit=1024),
            "limit": str(min(retmax, 200)),
        }
        headers: dict[str, str] = {"Authorization": f"Bearer {self._token}"}
        try:
            r = await client.get(
                f"{self._base}/api/v1/search",
                params=params, headers=headers, timeout=20.0,
            )
            r.raise_for_status()
            data: Any = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        items: list[Any]
        if isinstance(data, dict):
            items = data.get("results") or data.get("hits") or data.get("data") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
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
    return PaperHit(
        source="researka",
        title=title,
        abstract=clean_text(item.get("abstract"), limit=8000),
        year=int_or_none(item.get("year")),
        url=clean_text(item.get("url"), limit=500),
        doi=normalize_doi(item.get("doi")),
        pmid=clean_text(item.get("pmid"), limit=32) or None,
        venue=clean_text(item.get("venue") or item.get("journal"), limit=200) or None,
    )
