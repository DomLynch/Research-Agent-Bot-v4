"""Sprint 12.0 — Researka facts client tests.

Mocked HTTP only; no live network. Live verification is documented in
the Sprint 12.0 commit message. (Crosscheck tests removed with the
legacy extraction_crosscheck module in the v5 strip.)
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
import pytest

from agent.researka_facts import (
    ResearkaFact,
    filter_facts_by_doi,
    search_facts,
)
from agent.settings import load_settings


def _settings_with(**overrides: Any) -> Any:
    return replace(load_settings(), **overrides)


def _fact(**kw: Any) -> ResearkaFact:
    defaults: dict[str, Any] = dict(
        id="t/x/y", paper_id="10.1/abc",
        doi="10.1/abc", pmid=None,
        paper_title="T", journal="J",
        claim_type="effect_size", numeric_value=10.0,
        units="%", confidence="canonical", validated=True,
    )
    defaults.update(kw)
    return ResearkaFact(**defaults)


# ---------- search_facts ---------------------------------------------------

@pytest.mark.asyncio
async def test_search_facts_parses_live_response_shape() -> None:
    """Response shape verified live 2026-05-12 from database.researka.org."""
    body = [{
        "id": "rapamycin/transient/bitto_2016/lifespan_extension",
        "paper_id": "10.7554/eLife.16351",
        "paper": {
            "title": "Transient rapamycin treatment can increase lifespan",
            "doi": "10.7554/eLife.16351", "pmid": "27549339",
            "publication_year": 2016, "journal_name": "eLife",
        },
        "claim_type": "effect_size", "numeric_value": 60.0,
        "units": "%", "extraction_confidence": "canonical",
        "validation": {"status": "canonical", "delta": 0.0},
    }]
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["token"] = request.headers.get("X-Researka-Token", "")
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        facts = await search_facts(
            "rapamycin lifespan mice",
            client=client,
            settings=_settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="t",
            ),
        )

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/tier2/facts/search"
    assert captured["token"] == "t"
    assert captured["body"]["domain"] == "longevity"
    assert captured["body"]["query"] == "rapamycin lifespan mice"
    assert captured["body"]["numeric_only"] is True
    assert len(facts) == 1
    assert facts[0].numeric_value == 60.0
    assert facts[0].units == "%"
    assert facts[0].doi == "10.7554/elife.16351"  # normalised lowercase
    assert facts[0].confidence == "canonical"
    assert facts[0].validated is True


@pytest.mark.asyncio
async def test_search_facts_can_pass_ai_research_domain() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await search_facts(
            "ai agents",
            client=client,
            settings=_settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="t",
            ),
            domain="ai_research",
        )

    assert captured["body"]["domain"] == "ai_research"


@pytest.mark.asyncio
async def test_search_facts_returns_empty_when_unconfigured() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=[{"id": "x"}]))
    ) as client:
        facts = await search_facts(
            "x", client=client,
            settings=_settings_with(researka_database_token=""),
        )
    assert facts == ()


@pytest.mark.asyncio
async def test_search_facts_swallows_http_500() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(500, text="boom"))
    ) as client:
        facts = await search_facts(
            "x", client=client,
            settings=_settings_with(
                researka_database_url="https://database.researka.org",
                researka_database_token="t",
            ),
        )
    assert facts == ()


def test_filter_facts_by_doi_normalises_case() -> None:
    facts = (
        _fact(doi="10.7554/elife.16351"),
        _fact(id="other", paper_id="10.1/xyz", doi="10.1/xyz"),
    )
    out = filter_facts_by_doi(facts, "10.7554/eLife.16351")  # mixed case
    assert len(out) == 1
    assert out[0].doi == "10.7554/elife.16351"


def test_filter_facts_by_doi_empty_target_returns_empty() -> None:
    facts = (_fact(),)
    assert filter_facts_by_doi(facts, None) == ()
    assert filter_facts_by_doi(facts, "") == ()
