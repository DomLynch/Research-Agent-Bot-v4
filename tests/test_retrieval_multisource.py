"""Sprint 11.3 — multi-source retrieval client tests.

Each new source gets:
  - a successful-response test that verifies the JSON parser emits a
    well-formed PaperHit with DOI/PMID/title/year/venue normalised;
  - a failure-mode test (HTTP 500 or malformed body) that verifies the
    client swallows the exception and returns an empty list rather than
    sinking the unified search.

All tests use `httpx.MockTransport`; no live network.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest

from agent.retrieval.biorxiv import BioRxivSource
from agent.retrieval.core import COREsource
from agent.retrieval.crossref import CrossrefSource
from agent.retrieval.ctgov import ClinicalTrialsGovSource
from agent.retrieval.europepmc import EuropePMCSource
from agent.retrieval.openalex import OpenAlexSource
from agent.retrieval.osf import OSFSource
from agent.retrieval.researka import ResearkaSource
from agent.retrieval.semantic_scholar import SemanticScholarSource
from agent.retrieval.unified import available_sources
from agent.settings import Settings, load_settings


def _settings_with(**overrides: Any) -> Settings:
    return replace(load_settings(), **overrides)


def _mock(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _err_500(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="boom")


# ---------- registry ---------------------------------------------------------

def test_all_ten_sources_register_by_default() -> None:
    expected = {
        "biorxiv", "core", "crossref", "ctgov", "europepmc",
        "openalex", "osf", "pubmed", "researka", "semantic_scholar",
    }
    assert expected.issubset(set(available_sources()))


# ---------- Crossref --------------------------------------------------------

@pytest.mark.asyncio
async def test_crossref_parses_doi_title_year_venue() -> None:
    body = {"message": {"items": [{
        "DOI": "10.1038/nature08221",
        "title": ["Rapamycin fed late in life extends lifespan"],
        "container-title": ["Nature"],
        "issued": {"date-parts": [[2009]]},
        "URL": "https://doi.org/10.1038/nature08221",
        "abstract": "<p>Inhibition of mTOR ...</p>",
    }]}}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await CrossrefSource(load_settings()).search("rapamycin", client=client)
    assert len(hits) == 1
    assert hits[0].doi == "10.1038/nature08221"
    assert hits[0].year == 2009
    assert hits[0].venue == "Nature"


@pytest.mark.asyncio
async def test_crossref_swallows_http_500() -> None:
    async with httpx.AsyncClient(transport=_mock(_err_500)) as client:
        assert await CrossrefSource(load_settings()).search("x", client=client) == []


# ---------- OpenAlex --------------------------------------------------------

@pytest.mark.asyncio
async def test_openalex_inverts_abstract_index_and_extracts_pmid() -> None:
    body = {"results": [{
        "id": "https://openalex.org/W123",
        "title": "Rapamycin extends lifespan",
        "doi": "https://doi.org/10.1038/nature08221",
        "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/19587680"},
        "publication_year": 2009,
        "host_venue": {"display_name": "Nature"},
        "abstract_inverted_index": {"Rapamycin": [0], "extends": [1], "lifespan": [2]},
    }]}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await OpenAlexSource(load_settings()).search("rapamycin", client=client)
    assert hits[0].pmid == "19587680"
    assert hits[0].doi == "10.1038/nature08221"
    assert hits[0].abstract == "Rapamycin extends lifespan"


@pytest.mark.asyncio
async def test_openalex_swallows_malformed_json() -> None:
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, text="not-json"))
    ) as client:
        assert await OpenAlexSource(load_settings()).search("x", client=client) == []


# ---------- Europe PMC ------------------------------------------------------

@pytest.mark.asyncio
async def test_europepmc_parses_pmid_doi_and_url() -> None:
    body = {"resultList": {"result": [{
        "id": "19587680", "source": "MED",
        "pmid": "19587680", "doi": "10.1038/nature08221",
        "title": "Rapamycin extends lifespan in mice",
        "abstractText": "Inhibition of mTOR...",
        "journalTitle": "Nature", "pubYear": "2009",
    }]}}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await EuropePMCSource(load_settings()).search("rapamycin", client=client)
    assert hits[0].pmid == "19587680"
    assert hits[0].doi == "10.1038/nature08221"
    assert "europepmc.org/article/MED/19587680" in hits[0].url


@pytest.mark.asyncio
async def test_europepmc_swallows_500() -> None:
    async with httpx.AsyncClient(transport=_mock(_err_500)) as client:
        assert await EuropePMCSource(load_settings()).search("x", client=client) == []


# ---------- Semantic Scholar ------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_scholar_requires_api_key_to_be_configured() -> None:
    no_key = _settings_with(semantic_scholar_api_key="")
    assert SemanticScholarSource(no_key).configured is False
    with_key = _settings_with(semantic_scholar_api_key="abc")
    assert SemanticScholarSource(with_key).configured is True


@pytest.mark.asyncio
async def test_semantic_scholar_parses_externalids_to_doi_pmid() -> None:
    body = {"data": [{
        "title": "Rapamycin extends lifespan",
        "abstract": "We show...",
        "year": 2009,
        "externalIds": {"DOI": "10.1038/nature08221", "PubMed": "19587680"},
        "venue": "Nature",
        "url": "https://semanticscholar.org/paper/xyz",
    }]}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await SemanticScholarSource(
            _settings_with(semantic_scholar_api_key="k"),
        ).search("x", client=client)
    assert hits[0].doi == "10.1038/nature08221"
    assert hits[0].pmid == "19587680"


# ---------- CORE ------------------------------------------------------------

@pytest.mark.asyncio
async def test_core_requires_key_to_be_configured() -> None:
    assert COREsource(_settings_with(core_api_key="")).configured is False
    assert COREsource(_settings_with(core_api_key="k")).configured is True


@pytest.mark.asyncio
async def test_core_parses_doi_and_year() -> None:
    body = {"results": [{
        "title": "Rapamycin extends lifespan",
        "abstract": "...", "doi": "10.1038/nature08221",
        "yearPublished": 2009, "publisher": "NPG",
        "downloadUrl": "https://core.ac.uk/download/123.pdf",
    }]}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await COREsource(
            _settings_with(core_api_key="k"),
        ).search("x", client=client)
    assert hits[0].doi == "10.1038/nature08221"
    assert hits[0].year == 2009


# ---------- bioRxiv ---------------------------------------------------------

@pytest.mark.asyncio
async def test_biorxiv_parses_preprint_with_ppr_source() -> None:
    body = {"resultList": {"result": [{
        "id": "PPR123", "source": "PPR",
        "doi": "10.1101/2024.01.01.000000",
        "title": "Rapamycin preprint",
        "abstractText": "Preprint of...",
        "pubYear": "2024",
    }]}}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await BioRxivSource(load_settings()).search("rapamycin", client=client)
    assert hits[0].source == "biorxiv"
    assert hits[0].doi == "10.1101/2024.01.01.000000"
    assert "PPR/PPR123" in hits[0].url


# ---------- OSF -------------------------------------------------------------

@pytest.mark.asyncio
async def test_osf_parses_preprint_attributes() -> None:
    body = {"data": [{
        "type": "preprints",
        "attributes": {
            "title": "Living evidence-contract synthesis",
            "description": "Methodology paper...",
            "doi": "10.31219/osf.io/abc12",
            "date_published": "2024-05-01T00:00:00Z",
        },
        "links": {"html": "https://osf.io/preprints/xyz"},
    }]}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await OSFSource(load_settings()).search("synthesis", client=client)
    assert hits[0].doi == "10.31219/osf.io/abc12"
    assert hits[0].year == 2024
    assert hits[0].venue == "OSF Preprints"


# ---------- ClinicalTrials.gov ---------------------------------------------

@pytest.mark.asyncio
async def test_ctgov_parses_nct_id_and_title() -> None:
    body = {"studies": [{
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT01234567",
                "briefTitle": "Sirolimus in aging",
            },
            "descriptionModule": {
                "briefSummary": "A trial to evaluate sirolimus.",
            },
            "statusModule": {
                "startDateStruct": {"date": "2024-06-15"},
            },
        },
    }]}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await ClinicalTrialsGovSource(load_settings()).search(
            "sirolimus", client=client,
        )
    assert hits[0].title == "Sirolimus in aging"
    assert hits[0].url == "https://clinicaltrials.gov/study/NCT01234567"
    assert hits[0].year == 2024
    assert hits[0].venue == "ClinicalTrials.gov"


# ---------- Researka --------------------------------------------------------

@pytest.mark.asyncio
async def test_researka_skips_when_unconfigured() -> None:
    no_token = _settings_with(researka_database_token="")
    assert ResearkaSource(no_token).configured is False


@pytest.mark.asyncio
async def test_researka_parses_three_lane_response() -> None:
    """Verified API shape: POST /api/v1/search returns three lanes
    (established/discovery/semantic). Each lane contributes hits tagged
    with `researka:<lane>` so downstream auditors can see provenance."""
    body = {
        "established": [{
            "title": "Rapamycin lifespan study (established)",
            "doi": "10.1038/nature08221", "pmid": "19587680",
            "year": 2009, "venue": "Nature",
            "abstract": "Established corpus...",
        }],
        "discovery": [{
            "title": "Newer rapamycin work (discovery)",
            "doi": "10.1101/2024.01.01", "year": 2024,
            "venue": "bioRxiv",
        }],
        "semantic": [{
            "title": "Similar by vector (semantic)",
            "paper_id": "10.7554/elife.16351",  # paper_id is an alt DOI key
            "year": 2016, "venue": "eLife",
        }],
    }
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["token"] = request.headers.get("X-Researka-Token", "")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=_mock(handler)) as client:
        hits = await ResearkaSource(
            _settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="my-agent-token",
            ),
        ).search("rapamycin lifespan", client=client)

    # Verify wire-protocol: POST, X-Researka-Token header, per-lane budgets.
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/search"
    assert captured["token"] == "my-agent-token"
    assert captured["body"]["query"] == "rapamycin lifespan"
    assert "established_k" in captured["body"]
    assert "discovery_k" in captured["body"]
    assert "semantic_k" in captured["body"]

    # All three lanes merge into one flat list, tagged for provenance.
    by_source = {h.source for h in hits}
    assert by_source == {
        "researka:established", "researka:discovery", "researka:semantic",
    }
    dois = {h.doi for h in hits}
    assert "10.1038/nature08221" in dois
    assert "10.7554/elife.16351" in dois  # paper_id fallback worked


@pytest.mark.asyncio
async def test_researka_401_returns_empty_not_raise() -> None:
    """Token rejection should not sink the unified sweep — empty list."""
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(401, json={"detail": "invalid token"}))
    ) as client:
        hits = await ResearkaSource(
            _settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="bad-token",
            ),
        ).search("x", client=client)
    assert hits == []


@pytest.mark.asyncio
async def test_researka_topic_endpoint_returns_curated_hits() -> None:
    """Sprint 12.9.B: POST /api/v1/papers/topic — tier-1 curated paper
    enumeration. Hits are tagged source='researka:topic' so the
    eligibility-judge curated-proposal short-circuit (which fires for
    any `researka:*` source) handles them automatically. Wire-protocol
    verified: POST + X-Researka-Token + list[Paper] response."""
    curated_body = [
        {
            "id": "10.1111/acel.12194",
            "doi": "10.1111/acel.12194",
            "pmid": "24489881",
            "title": "Rapamycin-mediated lifespan increase in mice",
            "abstract": "Median lifespan increased by 23-26%...",
            "publication_year": 2014,
            "journal_name": "Aging Cell",
            "is_oa": True,
            "tier": 1, "topic_score": 1.0, "quality_score": 0.62,
        },
    ]
    captured_paths: list[str] = []
    captured_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_paths.append(request.url.path)
        captured_bodies.append(json.loads(request.content))
        if request.url.path == "/api/v1/papers/topic":
            return httpx.Response(200, json=curated_body)
        # Legacy /search endpoint — empty 3-lane response for this test.
        return httpx.Response(200, json={
            "established": [], "discovery": [], "semantic": [],
        })

    async with httpx.AsyncClient(transport=_mock(handler)) as client:
        hits = await ResearkaSource(
            _settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="my-agent-token",
            ),
        ).search("rapamycin lifespan", client=client)

    # Both endpoints get hit on every search() call — /papers/topic
    # FIRST (curated spine), then /search (gap-fill).
    assert "/api/v1/papers/topic" in captured_paths
    assert "/api/v1/search" in captured_paths
    topic_body = next(
        b for p, b in zip(captured_paths, captured_bodies, strict=True)
        if p == "/api/v1/papers/topic"
    )
    assert topic_body["topic"] == "rapamycin lifespan"
    assert topic_body["limit"] > 0
    assert topic_body["include_facts"] is False
    # Curated paper materialised into the hit list with topic-lane tag.
    assert len(hits) == 1
    assert hits[0].source == "researka:topic"
    assert hits[0].doi == "10.1111/acel.12194"
    assert hits[0].year == 2014
    assert hits[0].venue == "Aging Cell"


@pytest.mark.asyncio
async def test_researka_topic_endpoint_404_falls_back_silently() -> None:
    """Older Researka installs without the new endpoint return 404. The
    adapter must swallow that and let the legacy 3-lane /search call
    still run — never sink the unified sweep on a missing endpoint."""
    search_lane_body = {
        "established": [{
            "title": "Legacy 3-lane hit", "doi": "10.1/legacy", "year": 2020,
        }],
        "discovery": [], "semantic": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/papers/topic":
            return httpx.Response(404, json={"detail": "endpoint not found"})
        return httpx.Response(200, json=search_lane_body)

    async with httpx.AsyncClient(transport=_mock(handler)) as client:
        hits = await ResearkaSource(
            _settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="my-agent-token",
            ),
        ).search("x", client=client)
    # Topic-endpoint 404 -> 0 topic hits; 3-lane /search still works.
    assert len(hits) == 1
    assert hits[0].source == "researka:established"


@pytest.mark.asyncio
async def test_researka_partial_lane_response_handles_missing_keys() -> None:
    """Server may return only one or two lanes (e.g. cold cache, narrow
    query). Adapter should not raise; should return whatever is present."""
    body = {"established": [{"title": "T", "doi": "10.1/x"}]}  # no discovery/semantic
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await ResearkaSource(
            _settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="t",
            ),
        ).search("x", client=client)
    assert len(hits) == 1
    assert hits[0].source == "researka:established"
