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
async def test_researka_parses_results_envelope() -> None:
    body = {"results": [{
        "title": "Rapamycin lifespan study",
        "abstract": "We tested...",
        "doi": "10.1038/nature08221",
        "pmid": "19587680",
        "year": 2009,
        "venue": "Nature",
        "url": "https://example.test/article",
    }]}
    async with httpx.AsyncClient(transport=_mock(
        lambda r: httpx.Response(200, json=body))
    ) as client:
        hits = await ResearkaSource(
            _settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="t",
            ),
        ).search("x", client=client)
    assert hits[0].doi == "10.1038/nature08221"
    assert hits[0].pmid == "19587680"


@pytest.mark.asyncio
async def test_researka_tolerates_alt_envelope_shapes() -> None:
    """Server might use {hits:[...]}, {data:[...]}, or a bare list."""
    for envelope in (
        {"hits": [{"title": "T", "doi": "10.1/x"}]},
        {"data": [{"title": "T", "doi": "10.1/x"}]},
        [{"title": "T", "doi": "10.1/x"}],
    ):
        async with httpx.AsyncClient(transport=_mock(
            lambda r, e=envelope: httpx.Response(200, content=json.dumps(e).encode()))
        ) as client:
            hits = await ResearkaSource(
                _settings_with(
                    researka_database_url="https://database.researka.org",
                    researka_database_token="t",
                ),
            ).search("x", client=client)
        assert hits[0].doi == "10.1/x"
