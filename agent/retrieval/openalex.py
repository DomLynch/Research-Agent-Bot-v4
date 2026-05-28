"""OpenAlex Works API.

Public endpoint, no key required. The polite-pool email goes in `mailto`.
Abstracts are encoded as inverted indexes (position -> token); we
reconstruct the linear text. Failures return an empty list so the
unified search degrades gracefully.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_WORKS = "https://api.openalex.org/works"


class OpenAlexSource:
    name = "openalex"

    def __init__(self, settings: Settings) -> None:
        # OpenAlex reuses the Crossref polite-pool address by convention.
        self._email = settings.crossref_polite_email.strip()

    @property
    def configured(self) -> bool:
        return True

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "search": clean_text(query, limit=1024),
            "per_page": str(min(retmax, 200)),
            "select": (
                "id,title,doi,ids,publication_year,primary_location,"
                "abstract_inverted_index"
            ),
        }
        if self._email:
            params["mailto"] = self._email
        try:
            r = await client.get(_WORKS, params=params, timeout=20.0)
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
    ids = item.get("ids") or {}
    pmid = clean_text(ids.get("pmid"), limit=64).rsplit("/", 1)[-1] or None
    primary = item.get("primary_location") or {}
    source = primary.get("source") or {}
    legacy = item.get("host_venue") or {}
    venue = clean_text(
        source.get("display_name") or legacy.get("display_name"), limit=200,
    ) or None
    year = int_or_none(item.get("publication_year"))
    url = clean_text(item.get("id"), limit=500)
    abstract = _invert_abstract(item.get("abstract_inverted_index"))
    return PaperHit(
        source="openalex",
        title=title,
        abstract=abstract,
        year=year,
        url=url,
        doi=doi,
        pmid=pmid,
        venue=venue,
    )


def _invert_abstract(idx: object) -> str:
    """OpenAlex stores abstracts as {token: [position, ...]}. Linearise."""
    if not isinstance(idx, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for token, locs in idx.items():
        if not isinstance(token, str) or not isinstance(locs, list):
            continue
        for loc in locs:
            if isinstance(loc, int):
                positions.append((loc, token))
    positions.sort()
    return clean_text(" ".join(t for _, t in positions), limit=8000)
