"""Locks the alpha evidence run's Researka DB access order.

Universal: tests endpoint contracts and fallback behavior only.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from agent.settings import load_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_topic_evidence_run as evidence_run


def _settings() -> Any:
    return replace(
        load_settings(),
        researka_database_url="https://database.researka.org",
        researka_database_token="token",
    )


def _fact(fid: str, doi: str, *, bindable: bool = True) -> dict[str, Any]:
    out = {
        "id": fid,
        "paper": {
            "doi": doi,
            "title": f"Paper {fid}",
            "publication_year": 2026,
            "journal_name": "Journal",
        },
        "claim_type": "effect_size",
        "numeric_value": 10,
        "units": "%",
        "extraction_confidence": "high",
        "canonical_phrase": f"topicA signal {fid}",
    }
    if bindable:
        out["population"] = "adults"
        out["intervention"] = "topicA"
    return out


def _mock_client(monkeypatch: Any, handler: Any) -> None:
    real_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "Client", factory)
    monkeypatch.setattr(evidence_run, "load_settings", _settings)


def test_fetch_facts_strict_first_then_normal_until_source_floor(
    monkeypatch: Any,
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/api/v1/topics/topicA/facts"
            assert request.url.params.get("validated_only") == "true"
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("strict_audit_required"):
            return httpx.Response(200, json=[_fact("strict", "10.1/strict")])
        return httpx.Response(
            200,
            json=[_fact(f"normal-{i}", f"10.1/normal-{i}") for i in range(5)],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    assert bodies[0]["strict_audit_required"] is True
    assert bodies[0]["numeric_only"] is True
    assert bodies[1].get("strict_audit_required") is None
    assert bodies[1]["numeric_only"] is True
    assert len(bodies) == 2
    assert evidence_run._source_count(facts) == 6
    assert evidence_run._a_core_source_count(facts, "topicA") == 6


def test_fetch_facts_widens_when_strict_sources_are_not_direct_bindable(
    monkeypatch: Any,
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("strict_audit_required"):
            return httpx.Response(
                200,
                json=[_fact(f"strict-{i}", f"10.1/strict-{i}", bindable=False)
                      for i in range(5)],
            )
        return httpx.Response(
            200,
            json=[_fact(f"normal-{i}", f"10.1/normal-{i}") for i in range(5)],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    assert [body["numeric_only"] for body in bodies] == [True, True]
    assert evidence_run._source_count(facts) == 10
    assert evidence_run._a_core_source_count(facts, "topicA") == 5


def test_fetch_facts_caps_strict_synonym_probes_before_normal(
    monkeypatch: Any,
) -> None:
    bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        evidence_run, "expand_topic_queries",
        lambda _topic, max_queries=16: ("topicA", "q1", "q2", "q3", "q4"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("strict_audit_required"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[_fact(f"normal-{i}", f"10.1/normal-{i}") for i in range(5)],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    assert [b.get("strict_audit_required") for b in bodies[:3]] == [True, True, None]
    assert evidence_run._a_core_source_count(facts, "topicA") == 5


def test_fetch_facts_falls_back_when_strict_endpoint_rejects_flag(
    monkeypatch: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={"detail": "not found"})
        body = json.loads(request.content)
        if body.get("strict_audit_required"):
            return httpx.Response(422, json={"detail": "unknown flag"})
        return httpx.Response(200, json=[_fact("normal", "10.1/normal")])

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    assert [f["fact_id"] for f in facts] == ["normal"]


def test_fetch_facts_respects_total_budget(monkeypatch: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("fact fetch should not call DB after budget expires")

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(evidence_run, "_FACT_FETCH_BUDGET_SECONDS", 0.0)

    assert evidence_run._fetch_facts("topicA") == []


def test_select_tier2_items_filters_with_expanded_topic_queries() -> None:
    items = [
        {
            "canonical_phrase": "vitamin D changed mortality by 8%",
            "paper": {"title": "Vitamin D trial"},
        },
        {
            "canonical_phrase": "MK-7 reduced vascular calcification by 12%",
            "paper": {"title": "Menaquinone and vascular calcification"},
        },
    ]

    selected = evidence_run._select_tier2_items(
        items, "vitamin_K2_vascular_aging",
    )

    assert selected == [items[1]]


def test_fetch_papers_merges_elite_topic_and_broad_search(
    monkeypatch: Any,
) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v1/papers/topic":
            return httpx.Response(200, json=[{
                "doi": "10.1/a",
                "title": "Elite paper",
            }])
        return httpx.Response(200, json={
            "established": [{"doi": "10.1/a", "title": "Duplicate"}],
            "discovery": [{"doi": "10.1/b", "title": "Broad paper"}],
            "semantic": [],
        })

    _mock_client(monkeypatch, handler)

    papers = evidence_run._fetch_papers("topicA")

    assert paths == ["/api/v1/papers/topic", "/api/v1/search"]
    assert [p["doi"] for p in papers] == ["10.1/a", "10.1/b"]
