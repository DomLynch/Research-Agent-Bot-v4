"""Crossref Works API.

Public endpoint, no API key required. The polite-pool email is sent via
the `mailto` query param so Crossref routes the request through their
higher-throughput pool. Failures (HTTP, JSON, schema) are silent: an
empty list lets the unified search fall back to other sources.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_WORKS = "https://api.crossref.org/works"


class CrossrefSource:
    name = "crossref"

    def __init__(self, settings: Settings) -> None:
        self._email = settings.crossref_polite_email.strip()

    @property
    def configured(self) -> bool:
        # Polite-pool email is optional; Crossref still serves without it.
        return True

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "query": clean_text(query, limit=1024),
            "rows": str(retmax),
            "select": "DOI,title,abstract,issued,container-title,URL",
        }
        if self._email:
            params["mailto"] = self._email
        try:
            r = await client.get(_WORKS, params=params, timeout=20.0)
            r.raise_for_status()
            data: Any = r.json()
        except (httpx.HTTPError, ValueError):
            return []
        items = data.get("message", {}).get("items", []) if isinstance(data, dict) else []
        hits: list[PaperHit] = []
        for item in items:
            hit = _parse_item(item)
            if hit is not None:
                hits.append(hit)
        return hits


def _parse_item(item: Any) -> PaperHit | None:
    if not isinstance(item, dict):
        return None
    titles = item.get("title") or []
    title = clean_text(titles[0] if titles else "", limit=500)
    if not title:
        return None
    doi = normalize_doi(item.get("DOI"))
    venues = item.get("container-title") or []
    venue = clean_text(venues[0] if venues else "", limit=200) or None
    abstract = clean_text(item.get("abstract"), limit=8000)
    year = _issued_year(item.get("issued"))
    url = clean_text(item.get("URL"), limit=500) or (
        f"https://doi.org/{doi}" if doi else ""
    )
    return PaperHit(
        source="crossref",
        title=title,
        abstract=abstract,
        year=year,
        url=url,
        doi=doi,
        pmid=None,
        venue=venue,
    )


def _issued_year(issued: object) -> int | None:
    if not isinstance(issued, dict):
        return None
    parts = issued.get("date-parts") or []
    if not parts or not isinstance(parts[0], list) or not parts[0]:
        return None
    return int_or_none(parts[0][0])
