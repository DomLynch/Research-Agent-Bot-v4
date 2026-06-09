"""Evidence extraction reliability tests for the v4 fact pipeline."""
from __future__ import annotations

import json
from pathlib import Path

from agent.source_reliability import source_reliability_tier
from scripts.build_topic_evidence_run import _normalize_tier2
from scripts.daily_alpha_publish_cycle import _claim_cluster_candidates


def test_reliability_tier_heuristics_cover_source_classes() -> None:
    assert source_reliability_tier({"journal": "Management Science"}) == "high"
    assert source_reliability_tier({"source_url": "https://census.gov/report"}) == "high"
    assert source_reliability_tier({"source_url": "https://reuters.com/markets/"}) == "medium"
    assert source_reliability_tier({"source_url": "https://example.substack.com/p/take"}) == "low"


def test_tier2_normalization_exposes_reliability_attribute() -> None:
    fact = _normalize_tier2({
        "id": "f1",
        "claim_type": "productivity",
        "numeric_value": 1.2,
        "units": "%",
        "paper": {
            "title": "Field experiment on work practices",
            "journal_name": "Quarterly Journal of Economics",
            "doi": "10.1234/qje.1",
            "publication_year": 2025,
        },
    }, "management_research")

    assert fact["reliability"] == "high"
    assert fact["source_reliability"] == "high"


def test_claim_cluster_selection_counts_shape_matched_reliable_sources(
    tmp_path: Path,
) -> None:
    verdict = _claim_cluster_verdict(["h1", "m1", "l1"])
    run = _write_claim_cluster_run(tmp_path, [
        _fact("h1", "10.1/high", reliability="high"),
        _fact("m1", "10.1/medium", reliability="medium"),
        _fact("l1", "10.1/low", reliability="low"),
    ])

    out = _claim_cluster_candidates(
        [verdict | {"run_dir": f"runs/{run.name}"}],
        tmp_path / "runs",
        min_direct_source_count=2,
    )

    assert len(out) == 1
    assert out[0]["_claim_cluster_fact_ids"] == ["h1", "m1", "l1"]


def test_claim_cluster_selection_drops_low_reliability_from_source_floor(
    tmp_path: Path,
) -> None:
    verdict = _claim_cluster_verdict(["h1", "l1"])
    run = _write_claim_cluster_run(tmp_path, [
        _fact("h1", "10.1/high", reliability="high"),
        _fact("l1", "10.1/low", reliability="low"),
    ])

    out = _claim_cluster_candidates(
        [verdict | {"run_dir": f"runs/{run.name}"}],
        tmp_path / "runs",
        min_direct_source_count=2,
    )

    assert out == []


def _claim_cluster_verdict(ids: list[str]) -> dict[str, object]:
    return {
        "topic": "grid_storage",
        "decision": "curation_needed",
        "alpha_score": 80,
        "blockers": [],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "reserve_threshold",
                "member_fact_ids": ids,
            }],
        },
    }


def _fact(fid: str, doi: str, *, reliability: str) -> dict[str, object]:
    return {
        "fact_id": fid,
        "canonical_phrase": "Reserve threshold pricing improves dispatch reliability.",
        "population": "reserve markets",
        "intervention": "threshold pricing",
        "endpoint": "dispatch reliability",
        "source_reliability": reliability,
        "reliability": reliability,
        "source_paper": {"doi": doi, "title": f"Source {fid}"},
    }


def _write_claim_cluster_run(tmp_path: Path, facts: list[dict[str, object]]) -> Path:
    run = tmp_path / "runs" / "grid-storage-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(
        json.dumps({
            "verdicts": [
                {"fact_id": fact["fact_id"], "lane": "A_core"}
                for fact in facts
            ],
        }),
        encoding="utf-8",
    )
    return run
