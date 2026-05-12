"""Unified search across multiple retrieval sources.

Topic-pack-driven: each topic's TOML lists which sources to query under
[retrieval].sources. Sources run in parallel, hits are deduped by
PaperHit.dedupe_key (DOI > PMID > title-year), and a single flat list is
returned. Source failures are swallowed silently — one bad source must not
sink the whole search.

Universal: any module-level source class can be registered via `register()`
and used by any topic that names it. Adding a new domain (climate,
materials, economics) is purely data: write the source client, register it
under a name, and reference that name from the topic pack.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

import httpx

from agent.retrieval.base import PaperHit
from agent.settings import Settings
from agent.topic_pack import TopicPack


class AsyncSource(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    async def search(
        self, query: str, *, client: httpx.AsyncClient
    ) -> list[PaperHit]: ...


_REGISTRY: dict[str, type] = {}


def register(name: str, source_cls: type) -> None:
    _REGISTRY[name] = source_cls


def available_sources() -> list[str]:
    return sorted(_REGISTRY)


async def search_all(
    query: str,
    *,
    settings: Settings,
    pack: TopicPack | None = None,
) -> list[PaperHit]:
    names = (
        list(pack.retrieval_sources)
        if pack and pack.retrieval_sources
        else available_sources()
    )
    sources = [_REGISTRY[n](settings) for n in names if n in _REGISTRY]
    sources = [s for s in sources if getattr(s, "configured", False)]
    if not sources:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        results = await asyncio.gather(
            *[s.search(query, client=client) for s in sources],
            return_exceptions=True,
        )
        flat: list[PaperHit] = []
        seen: set[str] = set()
        for r in results:
            if isinstance(r, BaseException):
                continue
            for hit in r:
                if hit.dedupe_key in seen:
                    continue
                seen.add(hit.dedupe_key)
                flat.append(hit)
        # Sentinel injection: canonical anchors PubMed relevance-sort buried
        # may still be needed for the recall gate. Fetch each sentinel
        # explicitly and merge whatever's not already in the dedup set.
        sentinel_ids = (
            tuple(pack.sentinel_primary) + tuple(pack.sentinel_prior_meta)
            if pack else ()
        )
        if sentinel_ids:
            flat.extend(
                await _inject_sentinels(sentinel_ids, sources, client=client, seen=seen)
            )
    return flat


async def _inject_sentinels(
    sentinel_ids: tuple[str, ...],
    sources: list[AsyncSource],
    *,
    client: httpx.AsyncClient,
    seen: set[str],
) -> list[PaperHit]:
    """Look up each sentinel identifier explicitly on any source that
    exposes `fetch_by_identifier`. Idempotent: hits already in `seen` are
    skipped."""
    added: list[PaperHit] = []
    for sid in sentinel_ids:
        for src in sources:
            fetch = getattr(src, "fetch_by_identifier", None)
            if fetch is None:
                continue
            try:
                hits = await fetch(sid, client=client)
            except Exception:
                continue
            for hit in hits:
                if hit.dedupe_key in seen:
                    continue
                seen.add(hit.dedupe_key)
                added.append(hit)
    return added


def _register_default_sources() -> None:
    """Lazy bind of in-tree sources to avoid circular imports."""
    from agent.retrieval.biorxiv import BioRxivSource
    from agent.retrieval.core import COREsource
    from agent.retrieval.crossref import CrossrefSource
    from agent.retrieval.ctgov import ClinicalTrialsGovSource
    from agent.retrieval.europepmc import EuropePMCSource
    from agent.retrieval.openalex import OpenAlexSource
    from agent.retrieval.osf import OSFSource
    from agent.retrieval.pubmed import PubMedSource
    from agent.retrieval.researka import ResearkaSource
    from agent.retrieval.semantic_scholar import SemanticScholarSource

    register("pubmed", PubMedSource)
    register("crossref", CrossrefSource)
    register("openalex", OpenAlexSource)
    register("europepmc", EuropePMCSource)
    register("semantic_scholar", SemanticScholarSource)
    register("core", COREsource)
    register("biorxiv", BioRxivSource)
    register("osf", OSFSource)
    register("ctgov", ClinicalTrialsGovSource)
    register("researka", ResearkaSource)


_register_default_sources()
