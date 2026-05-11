"""Retrieval tests — mock httpx; no live network."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
import pytest

from agent.retrieval.base import PaperHit
from agent.retrieval.pubmed import PubMedSource, _parse_pubmed_xml
from agent.retrieval.unified import available_sources, register, search_all
from agent.settings import Settings, load_settings
from agent.topic_pack import load_topic_pack

_ESEARCH_RESP = {"esearchresult": {"idlist": ["19587680"]}}

_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID>19587680</PMID>
    <Article>
      <Journal><Title>Nature</Title></Journal>
      <ArticleTitle>Rapamycin fed late in life extends lifespan in genetically heterogeneous mice</ArticleTitle>
      <Abstract><AbstractText>Inhibition of mTOR ...</AbstractText></Abstract>
      <PubDate><Year>2009</Year></PubDate>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="doi">10.1038/nature08221</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""


def _mock_pubmed_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "esearch.fcgi" in request.url.path:
            return httpx.Response(200, json=_ESEARCH_RESP)
        if "efetch.fcgi" in request.url.path:
            return httpx.Response(200, text=_EFETCH_XML)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


# ---------- PubMed parser ---------------------------------------------------

def test_pubmed_xml_parser_extracts_doi_and_pmid() -> None:
    hits = _parse_pubmed_xml(_EFETCH_XML)
    assert len(hits) == 1
    assert hits[0].pmid == "19587680"
    assert hits[0].doi == "10.1038/nature08221"
    assert hits[0].year == 2009
    assert "Rapamycin" in hits[0].title


def test_pubmed_xml_parser_handles_malformed_xml() -> None:
    assert _parse_pubmed_xml("<<<not xml>>>") == []


# ---------- PubMedSource HTTP flow ------------------------------------------

@pytest.mark.asyncio
async def test_pubmed_source_full_search() -> None:
    settings = load_settings()
    source = PubMedSource(settings)
    assert source.configured is True
    async with httpx.AsyncClient(transport=_mock_pubmed_transport()) as client:
        hits = await source.search("rapamycin lifespan", client=client)
    assert len(hits) == 1
    assert hits[0].pmid == "19587680"


@pytest.mark.asyncio
async def test_pubmed_source_returns_empty_on_no_results() -> None:
    settings = load_settings()
    source = PubMedSource(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        hits = await source.search("no-results-query", client=client)
    assert hits == []


# ---------- Unified search registry + dedupe --------------------------------

class _FakeSource:
    """Deterministic source for unified-search tests."""

    name = "fake"
    configured = True

    def __init__(self, settings: Settings, hits: list[PaperHit]) -> None:
        self._hits = hits

    async def search(self, query: str, *, client: httpx.AsyncClient) -> list[PaperHit]:
        return self._hits


def _make_fake_class(hits: list[PaperHit]) -> type:
    captured: list[PaperHit] = list(hits)

    def init(self: Any, settings: Settings) -> None:
        return None

    async def search(
        self: Any, query: str, *, client: httpx.AsyncClient
    ) -> list[PaperHit]:
        return captured

    return type(
        "FakeSource",
        (),
        {"name": "fake", "configured": True, "__init__": init, "search": search},
    )


def test_pubmed_registered_by_default() -> None:
    assert "pubmed" in available_sources()


@pytest.mark.asyncio
async def test_search_all_dedupes_across_sources() -> None:
    settings = load_settings()
    hit_a = PaperHit(source="src-a", title="t", abstract="a", year=2020, url="u",
                     doi="10.1/abc", pmid=None, venue=None)
    hit_b_same = PaperHit(source="src-b", title="t", abstract="b", year=2020, url="u",
                          doi="10.1/abc", pmid=None, venue=None)
    hit_c_new = PaperHit(source="src-b", title="other", abstract="", year=2021, url="u",
                         doi="10.1/xyz", pmid=None, venue=None)
    register("test-a", _make_fake_class([hit_a]))
    register("test-b", _make_fake_class([hit_b_same, hit_c_new]))
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    pack_override = replace(pack, retrieval_sources=("test-a", "test-b"))
    hits = await search_all("q", settings=settings, pack=pack_override)
    assert len(hits) == 2
    keys = {h.dedupe_key for h in hits}
    assert keys == {"doi:10.1/abc", "doi:10.1/xyz"}


@pytest.mark.asyncio
async def test_search_all_swallows_source_failures() -> None:
    settings = load_settings()

    class Broken:
        name = "broken"
        configured = True

        def __init__(self, s: Settings) -> None:
            pass

        async def search(
            self, query: str, *, client: httpx.AsyncClient
        ) -> list[PaperHit]:
            raise httpx.HTTPError("boom")

    register("broken", Broken)
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    pack_override = replace(pack, retrieval_sources=("broken",))
    hits = await search_all("q", settings=settings, pack=pack_override)
    assert hits == []
