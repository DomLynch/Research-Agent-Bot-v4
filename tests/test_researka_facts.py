"""Sprint 12.0 — Researka facts client + crosscheck tests.

Mocked HTTP only; no live network. Live verification is documented in
the Sprint 12.0 commit message.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import httpx
import pytest

from agent.extraction_crosscheck import (
    CrosscheckResult,
    crosscheck_one,
    crosscheck_receipts,
)
from agent.researka_facts import (
    ResearkaFact,
    filter_facts_by_doi,
    search_facts,
    tier2_source_count,
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


# ---------- crosscheck_one verdict matrix ----------------------------------

def test_crosscheck_matched_within_tolerance() -> None:
    facts = (_fact(numeric_value=10.0, units="%"),)
    out = crosscheck_one("s1", "10.1/abc", percent_change=11.0, facts=facts)
    assert out.verdict == "matched"
    assert out.best_match_fact_id == "t/x/y"
    assert out.delta_percent == 1.0


def test_crosscheck_discrepant_outside_tolerance() -> None:
    facts = (_fact(numeric_value=10.0, units="%"),)
    out = crosscheck_one("s1", "10.1/abc", percent_change=60.0, facts=facts)
    assert out.verdict == "discrepant"
    assert out.delta_percent == 50.0


def test_crosscheck_no_receipt_numerics_when_pct_none() -> None:
    facts = (_fact(),)
    out = crosscheck_one("s1", "10.1/abc", percent_change=None, facts=facts)
    assert out.verdict == "no_receipt_numerics"
    assert out.delta_percent is None


def test_crosscheck_no_canonical_fact_when_doi_misses() -> None:
    facts = (_fact(doi="10.99/other"),)
    out = crosscheck_one("s1", "10.1/abc", percent_change=11.0, facts=facts)
    assert out.verdict == "no_canonical_fact"
    assert out.canonical_facts == ()


def test_crosscheck_skips_non_percent_units() -> None:
    """Only %-units facts can be compared to receipt.percent_change.
    Facts with units like 'days' or 'mg/kg/day' don't fail the receipt;
    they just don't supply a comparison."""
    facts = (_fact(units="days", numeric_value=913.0),)
    out = crosscheck_one("s1", "10.1/abc", percent_change=11.0, facts=facts)
    assert out.verdict == "no_canonical_fact"  # no %-units fact to compare
    assert out.canonical_facts == facts  # still surfaces the facts for audit


def test_crosscheck_picks_best_delta_among_multiple_percent_facts() -> None:
    facts = (
        _fact(id="f1", numeric_value=60.0, units="%"),
        _fact(id="f2", numeric_value=12.0, units="%"),
        _fact(id="f3", numeric_value=8.0, units="%"),
    )
    # receipt 11% should pick f2 (delta=1) as best, within tolerance.
    out = crosscheck_one("s1", "10.1/abc", percent_change=11.0, facts=facts)
    assert out.best_match_fact_id == "f2"
    assert out.delta_percent == 1.0
    assert out.verdict == "matched"


# ---------- crosscheck_receipts integration ------------------------------

@pytest.mark.asyncio
async def test_crosscheck_receipts_handles_empty_list() -> None:
    # Empty-receipts short-circuit; the pack contents are irrelevant
    # here, so use a minimal in-test fixture instead of touching disk.
    from types import MappingProxyType

    from agent.topic_pack import TopicPack
    pack = TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=(), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(),
        subjects_extra=(),
        primary_interventions=(), translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=(), eligibility_control_terms=(),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
    )
    results = await crosscheck_receipts(
        (), settings=_settings_with(), pack=pack,
    )
    assert results == ()


@pytest.mark.asyncio
async def test_crosscheck_result_dataclass_is_immutable() -> None:
    r = CrosscheckResult(
        study_id="s1", doi="10.1/a", verdict="matched",
        receipt_percent_change=11.0, canonical_facts=(),
        best_match_fact_id=None, delta_percent=None,
    )
    with pytest.raises(AttributeError):
        r.verdict = "discrepant"  # type: ignore[misc]


def _count_settings() -> Any:
    return _settings_with(
        researka_database_url="https://database.researka.org",
        researka_database_token="t",
    )


def test_tier2_source_count_reports_zero_on_504_without_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 504 (gateway timeout under extraction load) is transient, NOT a
    verified empty corpus: it degrades to 0 but is logged distinctly (so it is
    not a silent mask). No in-call retry — a 60s gateway timeout would only
    re-spend the probe budget for the same failure."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(504, text="gateway timeout")

    with caplog.at_level(logging.WARNING, logger="agent.researka_facts"), \
            httpx.Client(transport=httpx.MockTransport(handler)) as client:
        n = tier2_source_count(
            "labor_economics", client=client, settings=_count_settings(),
            domain="business_research",
        )

    assert n == 0
    assert calls["n"] == 1  # no retry on a 60s gateway timeout
    assert any("transient API failure" in m for m in caplog.messages)


def test_tier2_source_count_does_not_retry_on_genuine_empty() -> None:
    """A 200 with an empty list is a real empty result — count 0, no retry."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        n = tier2_source_count(
            "x", client=client, settings=_count_settings(),
        )

    assert n == 0
    assert calls["n"] == 1  # genuine empty is authoritative — no retry


def test_tier2_source_count_counts_distinct_papers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            {"paper": {"doi": "10.1/a"}}, {"paper": {"doi": "10.1/a"}},
            {"paper": {"doi": "10.1/b"}},
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        n = tier2_source_count("x", client=client, settings=_count_settings())

    assert n == 2  # distinct papers, not facts
