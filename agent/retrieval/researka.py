"""Researka internal canonical index — POST /api/v1/search.

Auth: `X-Researka-Token: <RESEARKA_DATABASE_TOKEN>` (verified spec).
Endpoint: POST `{base}/api/v1/search` with JSON body
  `{"query": <str>, "established_k": <int>, "discovery_k": <int>,
    "semantic_k": <int>}`.

Response carries three lanes — `established` (high-confidence known
papers), `discovery` (newer/high-velocity candidates), `semantic`
(vector similarity hits). All three are merged into a single flat
`list[PaperHit]`; downstream dedup in `unified.search_all` collapses
overlaps with PubMed / Crossref / Europe PMC by DOI / PMID.

Both `RESEARKA_DATABASE_URL` and `RESEARKA_DATABASE_TOKEN` must be set;
otherwise the source is skipped at search_all() time. Errors (auth,
HTTP, JSON) surface as an empty list so one bad source can't sink the
unified sweep.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_LANES: tuple[str, ...] = ("established", "discovery", "semantic")


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
        # The API takes per-lane caps. Split retmax 4:1:5 so the bulk of
        # the budget goes to the high-precision `established` + semantic
        # lanes, with a slimmer `discovery` allowance.
        established_k = max(1, retmax * 4 // 10)
        discovery_k = max(1, retmax // 10)
        semantic_k = max(1, retmax * 5 // 10)
        body = {
            "query": clean_text(query, limit=1024),
            "established_k": established_k,
            "discovery_k": discovery_k,
            "semantic_k": semantic_k,
        }
        headers = {
            "X-Researka-Token": self._token,
            "Content-Type": "application/json",
        }
        try:
            r = await client.post(
                f"{self._base}/api/v1/search",
                json=body, headers=headers, timeout=20.0,
            )
            r.raise_for_status()
            data: Any = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        hits: list[PaperHit] = []
        for lane in _LANES:
            items = data.get(lane) or []
            if not isinstance(items, list):
                continue
            for item in items:
                hit = _parse_item(item, lane=lane)
                if hit is not None:
                    hits.append(hit)
        return hits


def _parse_item(item: Any, *, lane: str) -> PaperHit | None:
    if not isinstance(item, dict):
        return None
    title = clean_text(item.get("title"), limit=500)
    if not title:
        return None
    doi = normalize_doi(item.get("doi") or item.get("paper_id"))
    return PaperHit(
        source=f"researka:{lane}",
        title=title,
        abstract=clean_text(item.get("abstract") or item.get("summary"), limit=8000),
        year=int_or_none(item.get("year") or item.get("publication_year")),
        url=clean_text(item.get("url") or item.get("link"), limit=500)
        or (f"https://doi.org/{doi}" if doi else ""),
        doi=doi,
        pmid=clean_text(item.get("pmid"), limit=32) or None,
        venue=clean_text(item.get("venue") or item.get("journal"), limit=200) or None,
    )
