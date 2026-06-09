from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.build_topic_evidence_run as evidence_run
import scripts.daily_alpha_publish_cycle as daily


def _ai_fact(
    idx: int,
    *,
    benchmark: str = "SWE-bench Verified",
    task: str = "software issue resolution",
    dataset: str = "SWE-bench Verified",
    metric: str = "resolve rate",
    model: str = "AgentX",
    baseline: str = "baseline agent",
    protocol: str = "matched-budget benchmark evaluation",
) -> dict[str, Any]:
    return {
        "fact_id": f"ai-{idx}",
        "canonical_phrase": (
            f"{model} reports {metric} on {benchmark} against {baseline}."
        ),
        "benchmark": benchmark,
        "task": task,
        "dataset": dataset,
        "metric": metric,
        "model_system": model,
        "baseline_comparator": baseline,
        "evaluation_protocol": protocol,
        "source_paper": {
            "doi": f"10.ai/{idx}",
            "title": f"{benchmark} result {idx}",
        },
    }


def test_ai_evidence_shape_filter_keeps_matched_and_drops_mismatched() -> None:
    matched = [_ai_fact(i) for i in range(1, 5)]
    mismatched = [
        _ai_fact(
            10,
            benchmark="MMLU",
            task="multiple choice QA",
            dataset="MMLU",
            metric="accuracy",
            model="ClassifierZ",
            baseline="few-shot baseline",
            protocol="MMLU benchmark evaluation",
        ),
        _ai_fact(
            11,
            benchmark="HumanEval",
            task="code generation",
            dataset="HumanEval",
            metric="pass@1",
            model="CoderY",
            baseline="Codex baseline",
            protocol="HumanEval benchmark evaluation",
        ),
        _ai_fact(
            12,
            benchmark="MT-Bench",
            task="chat preference",
            dataset="MT-Bench",
            metric="win rate",
            model="ChatModel",
            baseline="arena baseline",
            protocol="pairwise judge evaluation",
        ),
    ]

    coherent = evidence_run._ai_axis_coherent_facts(
        [*mismatched, *matched],
        "swe_bench_success",
        min_sources=4,
    )

    assert [fact["fact_id"] for fact in coherent] == [
        "ai-1",
        "ai-2",
        "ai-3",
        "ai-4",
    ]
    assert {fact["result_shape"]["benchmark"] for fact in coherent} == {
        "Swe Bench Verified",
    }
    assert {fact["result_shape"]["metric"] for fact in coherent} == {
        "Resolve Rate",
    }
    assert evidence_run._source_count(coherent) == 4


def test_ai_shape_filter_composes_with_claim_cluster_qa_selection(
    tmp_path: Path,
) -> None:
    coherent = evidence_run._ai_axis_coherent_facts(
        [_ai_fact(i) for i in range(1, 4)],
        "swe_bench_success",
        min_sources=3,
    )
    run = tmp_path / "runs" / "swe_bench_success-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("all_facts.json").write_text(
        json.dumps(coherent),
        encoding="utf-8",
    )
    run.joinpath("fact_lanes.json").write_text(
        json.dumps({
            "verdicts": [
                {"fact_id": fact["fact_id"], "lane": "A_core"}
                for fact in coherent
            ],
        }),
        encoding="utf-8",
    )
    cluster = {
        "label": "verified resolve rate",
        "member_fact_ids": [fact["fact_id"] for fact in coherent],
    }
    verdict = {
        "topic": "swe_bench_success",
        "run_dir": "swe_bench_success-evidence-ts",
        "decision": "curation_needed",
        "alpha_score": 42,
        "blockers": [],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [cluster],
        },
        "receipt_expansion": {},
    }

    candidates = daily._claim_cluster_candidates(
        [verdict],
        tmp_path / "runs",
        min_direct_source_count=3,
    )
    blocked = daily._claim_cluster_candidates(
        [verdict | {"blockers": ["receipt_shape_mismatch"]}],
        tmp_path / "runs",
        min_direct_source_count=3,
    )

    assert len(candidates) == 1
    assert candidates[0]["topic"] == "swe_bench_success_verified_resolve_rate"
    assert candidates[0]["decision"] == "agent_repair_needed"
    assert candidates[0]["receipt_expansion"]["cited_bound_fact_ids"] == [
        "ai-1",
        "ai-2",
        "ai-3",
    ]
    assert blocked == []
