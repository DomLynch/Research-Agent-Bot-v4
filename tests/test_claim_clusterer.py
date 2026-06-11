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
