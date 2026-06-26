"""Research-quality contract tests for alpha publish decisions."""
from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

import scripts.build_publish_queue as queue
from agent.publish_tier import publish_verdict
from agent.research_quality_contract import (
    apply_publish_quality_contract,
    evaluate_research_quality,
)


def _ready_verdict() -> dict[str, object]:
    return {
        "topic": "grid_storage",
        "decision": "ready_to_publish",
        "publish_tier": "TIER_1",
        "maturity_level": "L5",
        "alpha_score": 90,
        "surface_type": "publish_alpha_memo",
        "blockers": [],
        "axes": {
            "direct_source_papers": 5,
            "direct_match_receipts": 5,
            "a_core_receipts": 5,
            "claim_coherent_source_diversity": True,
            "direct_receipt_shape_coherent": True,
            "direct_metric_type_coherent": True,
            "retrieval_artifact_claim": False,
            "counter_consensus_tension": True,
            "cross_domain_forced": False,
            "feed_scope_mismatch": False,
            "source_papers": [
                {
                    "doi": f"10.grid/{idx}",
                    "title": "Grid storage threshold separates reserve reliability from cost exposure",
                    "journal": "Grid Systems",
                    "year": 2026,
                }
                for idx in range(5)
            ],
        },
    }


def test_contract_accepts_specific_receipt_owned_angle() -> None:
    memo = (
        "# Alpha memo\n\n"
        "**Headline:** Storage threshold separates reserve reliability from cost exposure\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "Reserve reliability improves at the storage threshold, while cost exposure remains protocol-sensitive.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the same threshold behaves like a reliability gain but not a pooled cost win.\n\n"
        "## Next question\n\n"
        "What repeated reserve-market receipt would falsify the reliability/cost split?\n"
    )

    quality = evaluate_research_quality(_ready_verdict(), memo)

    assert quality["publishable"] is True
    assert "non_obvious_angle_present" in quality["strengths"]
    assert "boilerplate_insight_surface" not in quality["weaknesses"]


def test_contract_requires_falsifiable_next_step() -> None:
    memo = (
        "# Alpha memo\n\n"
        "**Headline:** Storage threshold separates reserve reliability from cost exposure\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "Reserve reliability improves at the storage threshold, while cost exposure remains protocol-sensitive.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the same threshold behaves like a reliability gain but not a pooled cost win.\n"
    )

    quality = evaluate_research_quality(_ready_verdict(), memo)

    assert quality["publishable"] is False
    assert "missing_falsifiable_next_step" in quality["weaknesses"]


def test_contract_demotes_structurally_ready_boilerplate_memo() -> None:
    memo = (
        "# Alpha memo\n\n"
        "**Headline:** Storage threshold signal is source bounded\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "The direct receipts define the claim.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: this is worth checking because it ties a measured threshold signal "
        "to a source-backed effect and a new angle.\n"
    )

    verdict = apply_publish_quality_contract(_ready_verdict(), memo)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["publish_tier"] == "TIER_2"
    assert verdict["surface_type"] == "quality_repair_memo"
    assert "research_quality_contract" in verdict["blockers"]
    assert verdict["research_quality"]["publishable"] is False
    assert "boilerplate_insight_surface" in verdict["research_quality"]["weaknesses"]


def _queue_run(root: Path, *, memo_body: str) -> Path:
    run = root / "grid_storage-evidence-2026-02-01T00-00-00Z"
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(5)]
    run.joinpath("alpha_memo.md").write_text(memo_body, encoding="utf-8")
    run.joinpath("opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "status": "survives",
            "capped_opportunity": 90,
            "cited_fact_ids": ids,
        }],
    }), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": fid, "lane": "A_core"}
            for fid in ids
        ],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": (
                "Storage threshold improved reserve reliability while cost exposure varied."
            ),
            "population": "reserve market operators",
            "intervention": "storage threshold reliability",
            "source_paper": {
                "doi": f"10.grid/{fid}",
                "title": "Grid storage threshold separates reserve reliability from cost exposure",
                "journal": "Grid Systems",
                "year": 2026,
            },
        }
        for fid in ids
    ]), encoding="utf-8")
    return run


def test_publish_queue_demotes_ready_but_boilerplate_memo(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run = _queue_run(
        runs,
        memo_body=(
            "# Alpha memo\n\n"
            "**Headline:** Storage threshold signal is source bounded\n"
            "**Alpha score:** 90/100\n"
            "**Confidence:** `evidence_backed_signal`\n\n"
            "## One-sentence thesis\n\n"
            "The direct receipts define the claim.\n\n"
            "## Why this is surprising\n\n"
            "Real tension: this is worth checking because reserve reliability and cost exposure "
            "tie a measured threshold signal to a source-backed effect and a new angle.\n\n"
            "## What would break the idea\n\n"
            "A repeated storage threshold receipt would falsify the claimed reserve reliability split.\n\n"
            "## Evidence receipts\n\n"
            "- `fact_id=1` (`A_core`) - receipt\n"
            "- `fact_id=2` (`A_core`) - receipt\n"
            "- `fact_id=3` (`A_core`) - receipt\n"
            "- `fact_id=4` (`A_core`) - receipt\n"
            "- `fact_id=5` (`A_core`) - receipt\n"
        ),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    pre_quality = publish_verdict(run)
    assert pre_quality["decision"] == "ready_to_publish"
    assert pre_quality["surface_type"] == "publish_alpha_memo"

    out = queue.build_queue(include_archive=True)

    assert out["ready_to_publish"] == []
    assert [row["topic"] for row in out["agent_repair_needed"]] == ["grid_storage"]
    row = out["agent_repair_needed"][0]
    assert row["surface_type"] == "quality_repair_memo"
    assert "research_quality_contract" in row["blockers"]
    assert row["research_quality"]["boilerplate_hits"]
    assert "missing_falsifiable_next_step" not in row["research_quality"]["weaknesses"]
