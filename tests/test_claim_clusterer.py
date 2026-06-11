"""Claim clusterer tests — year extraction + recency cap, no live LLM.

These import agent.claim_clusterer directly (the module is otherwise only
lazy-loaded at build time, so an import-time break would slip the suite).
"""
from __future__ import annotations

import json

import pytest

from agent import claim_clusterer as clusterer


def test_fact_year_reads_field_variants() -> None:
    assert clusterer._fact_year({"canonical_year": 2023}) == 2023
    assert clusterer._fact_year({"source_paper": {"year": 2021}}) == 2021
    assert clusterer._fact_year({"source_paper": {"publication_year": 2019}}) == 2019
    assert clusterer._fact_year({"year": "not-a-year"}) == 0
    assert clusterer._fact_year({}) == 0


def _facts(n: int) -> dict[str, dict[str, object]]:
    return {
        str(i): {
            "canonical_phrase": f"finding {i} improves accuracy",
            "source_paper": {"doi": f"10/{i}", "year": 2000 + i},
        }
        for i in range(n)
    }


def test_cluster_cites_newest_first_and_caps_at_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts(15)
    lanes = {fid: "A_core" for fid in facts}
    content = json.dumps({
        "clusters": [{"claim": "improves accuracy", "fact_ids": list(facts)}],
    })
    monkeypatch.setattr(
        clusterer, "call_writer_with_fallback",
        lambda *a, **k: type("R", (), {"content": content})(),
    )

    out = clusterer.densest_claim_cluster(
        facts, lanes, "topic", min_sources=5,
        settings=type("S", (), {"writer_configured": True})(),
    )
    ids = out["lead_fact_ids"]
    years = [clusterer._fact_year(facts[i]) for i in ids]

    assert len(ids) == clusterer._MAX_CITED_SOURCES        # bounded
    assert years == sorted(years, reverse=True)            # newest-first
    assert years[0] == 2014                                # most recent cited
    assert min(years) == 2005                              # oldest dropped


def test_claim_is_focused_rejects_laundry_lists() -> None:
    assert clusterer._claim_is_focused(
        "Multi-agent systems beat single-agent baselines on SMAC win rate")
    assert not clusterer._claim_is_focused(
        "Gains including 92% containment, 43% signal, 3.31x CodeBLEU, "
        "8.56% detection, 15% downtime")
    assert not clusterer._claim_is_focused("")


def test_cluster_prefers_focused_claim_over_larger_laundry_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tight 3-source bounded claim must win over a sprawling 10-source figure
    list, even though M3 orders the larger cluster first — the larger one is the
    heterogeneous pile the reviewer rejects."""
    facts = _facts(13)
    lanes = {fid: "A_core" for fid in facts}
    big = list(facts)[:10]
    tight = list(facts)[10:13]
    content = json.dumps({"clusters": [
        {"claim": "Gains including 9% A, 4% B, 3x C, 8% D, 1% E, 2% F",
         "fact_ids": big},
        {"claim": "Method M beats baseline B on benchmark K accuracy",
         "fact_ids": tight},
    ]})
    monkeypatch.setattr(
        clusterer, "call_writer_with_fallback",
        lambda *a, **k: type("R", (), {"content": content})(),
    )

    out = clusterer.densest_claim_cluster(
        facts, lanes, "topic", min_sources=3,
        settings=type("S", (), {"writer_configured": True})(),
    )

    assert set(out["lead_fact_ids"]) == set(tight)
    assert out["claim"].startswith("Method M")


def test_cluster_keeps_full_set_below_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts(6)
    lanes = {fid: "A_core" for fid in facts}
    content = json.dumps({
        "clusters": [{"claim": "improves accuracy", "fact_ids": list(facts)}],
    })
    monkeypatch.setattr(
        clusterer, "call_writer_with_fallback",
        lambda *a, **k: type("R", (), {"content": content})(),
    )

    out = clusterer.densest_claim_cluster(
        facts, lanes, "topic", min_sources=5,
        settings=type("S", (), {"writer_configured": True})(),
    )
    assert len(out["lead_fact_ids"]) == 6  # all kept; under the cap
