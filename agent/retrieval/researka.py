"""Researka internal canonical index — two-endpoint adapter.

Auth: `X-Researka-Token: <RESEARKA_DATABASE_TOKEN>` (verified spec).

Sprint 12.9.B: `ResearkaSource.search()` calls both endpoints in
order:

1. POST `{base}/api/v1/papers/topic` — tier-1 curated papers for the
   topic, with per-paper tier / quality_score / topic_score metadata.
   This is the canonical Researka-as-primary-spine source. Body:
   `{"topic": <str>, "limit": <int>, "include_facts": false}`.
   Response: `list[Paper]` — 16 fields per paper. Hits get
   `source='researka:topic'`. Returns empty on 404 so the adapter
   still works against older Researka installs that don't have the
   new endpoint deployed.

2. POST `{base}/api/v1/search` — the legacy 3-lane (`established`,
   `discovery`, `semantic`) ranked retrieval. Body:
   `{"query": <str>, "established_k": <int>, "discovery_k": <int>,
     "semantic_k": <int>}`. Hits get
   `source='researka:established|discovery|semantic'`.

Both result lists are concatenated; `unified.search_all` dedupes
across the full multi-source sweep by DOI/PMID, with the curated
`/papers/topic` hits appearing first so they win ties.

Both `RESEARKA_DATABASE_URL` and `RESEARKA_DATABASE_TOKEN` must be
set; otherwise the source is skipped at search_all() time. Errors
(auth, HTTP, JSON) surface as an empty list so one bad source can't
sink the unified sweep.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.api_client import async_api_request
from agent.retrieval.base import PaperHit, clean_text, int_or_none, normalize_doi
from agent.settings import Settings

_LANES: tuple[str, ...] = ("established", "discovery", "semantic")


class ResearkaSource:
    name = "researka"

    def __init__(self, settings: Settings) -> None:
        self._base = settings.researka_database_url.rstrip("/")
        self._token = settings.researka_database_token.strip()
        # Sprint 12.9: Researka-as-primary-spine bumps the per-call budget
        # so the spine has 3x the candidates the legacy retmax=100 default
        # produced. Override via `RESEARKA_SPINE_RETMAX` env var if needed.
        self._spine_retmax = int(settings.researka_spine_retmax)

    @property
    def configured(self) -> bool:
        return bool(self._base) and bool(self._token)

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int | None = None,
    ) -> list[PaperHit]:
        if not self.configured:
            return []
        budget = int(retmax) if retmax is not None else self._spine_retmax
        # Sprint 12.9.B: query the new /api/v1/papers/topic endpoint
        # FIRST — it returns tier-1 curated papers for the topic with
        # per-paper tier / quality_score / topic_score metadata. This
        # is the canonical Researka-as-primary-spine source. The
        # legacy 3-lane /api/v1/search call below adds discovery +
        # semantic gap-fillers; unified.search_all() dedupes by
        # DOI/PMID so duplicates are dropped, with the curated hit
        # winning (it appears first in the returned list).
        topic_hits = await self._fetch_topic_papers(
            query, limit=budget, client=client,
        )
        lane_hits = await self._fetch_search_lanes(
            query, budget=budget, client=client,
        )
        return [*topic_hits, *lane_hits]

    async def _fetch_topic_papers(
        self, topic: str, *, limit: int, client: httpx.AsyncClient,
    ) -> list[PaperHit]:
        """POST /api/v1/papers/topic — tier-1 curated papers for the
        topic. Returns hits tagged `source='researka:topic'` so the
        eligibility-judge curated-proposal short-circuit fires for
        them (it triggers on any `researka:*` source). Returns empty
        on 404 (endpoint not yet deployed on older Researka installs)
        or any HTTP/JSON error — caller falls back to the 3-lane
        /search path automatically.
        """
        topic = clean_text(topic, limit=512)
        if not topic:
            return []
        body = {
            "topic": topic, "limit": int(limit), "include_facts": False,
        }
        headers = {
            "X-Researka-Token": self._token,
            "Content-Type": "application/json",
        }
        r = await async_api_request(
            client, "POST", f"{self._base}/api/v1/papers/topic",
            service=self.name, json=body, headers=headers, timeout=20.0,
        )
        if r is None:
            return []
        try:
            data: Any = r.json()
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        hits: list[PaperHit] = []
        for item in data:
            hit = _parse_item(item, lane="topic")
            if hit is not None:
                hits.append(hit)
        return hits

    async def _fetch_search_lanes(
        self, query: str, *, budget: int, client: httpx.AsyncClient,
    ) -> list[PaperHit]:
        """POST /api/v1/search — the legacy 3-lane (established /
        discovery / semantic) ranked retrieval. Split budget 4:1:5 so
        the bulk goes to high-precision lanes."""
        established_k = max(1, budget * 4 // 10)
        discovery_k = max(1, budget // 10)
        semantic_k = max(1, budget * 5 // 10)
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
        r = await async_api_request(
            client, "POST", f"{self._base}/api/v1/search",
            service=self.name, json=body, headers=headers, timeout=20.0,
        )
        if r is None:
            return []
        try:
            data: Any = r.json()
        except ValueError:
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
    # `paper_id` is an alt DOI key on the legacy 3-lane response; `id` on
    # the Sprint-12.9.B /api/v1/papers/topic response carries a DOI.
    doi = normalize_doi(
        item.get("doi") or item.get("paper_id") or item.get("id")
    )
    # Venue lookup spans both response shapes:
    #   - legacy 3-lane: `venue` or `journal`
    #   - new /papers/topic: `journal_name`
    venue = clean_text(
        item.get("venue") or item.get("journal") or item.get("journal_name"),
        limit=200,
    ) or None
    return PaperHit(
        source=f"researka:{lane}",
        title=title,
        abstract=clean_text(item.get("abstract") or item.get("summary"), limit=8000),
        year=int_or_none(item.get("year") or item.get("publication_year")),
        url=clean_text(item.get("url") or item.get("link"), limit=500)
        or (f"https://doi.org/{doi}" if doi else ""),
        doi=doi,
        pmid=clean_text(item.get("pmid"), limit=32) or None,
        venue=venue,
    )
