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
    names = list(pack.retrieval_sources) if pack and pack.retrieval_sources else available_sources()
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
    return flat


def _register_default_sources() -> None:
    """Lazy bind of in-tree sources to avoid circular imports."""
    from agent.retrieval.pubmed import PubMedSource
    from agent.retrieval.researka_database import ResearkaDatabaseSource

    register("pubmed", PubMedSource)
    register("researka_database", ResearkaDatabaseSource)


_register_default_sources()
