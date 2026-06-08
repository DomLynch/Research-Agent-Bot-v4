import json
from pathlib import Path

import scripts.run_ai_results_index_scale as scale


def test_plan_topics_dedupes_caps_and_uses_requested_topics(tmp_path: Path) -> None:
    seed = tmp_path / "seeds.toml"
    seed.write_text(
        "[seeds]\ntopics = ['unused']\n",
        encoding="utf-8",
    )

    out = scale._plan_topics(
        ["rag", "rag", "llm_evaluation", "model_eval"],
        seed_path=seed,
        max_topics=2,
    )

    assert out == ["rag", "llm_evaluation"]


def test_plan_topics_reads_seed_file_when_no_requested_topics(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seeds.toml"
    seed.write_text(
        "[seeds]\ntopics = ['ai_agents', 'rag', 'rag']\n",
        encoding="utf-8",
    )

    assert scale._plan_topics([], seed_path=seed, max_topics=10) == [
        "ai_agents",
        "rag",
    ]


def test_topic_build_args_force_no_mimo_ai_results_path() -> None:
    args = scale._topic_build_args("python", "rag", 5)

    assert args == [
        "python",
        "scripts/build_topic_evidence_run.py",
        "--domain",
        "ai_research",
        "--topic",
        "rag",
        "--top",
        "5",
        "--no-frontier",
        "--no-pico-enrich",
    ]


def test_display_path_accepts_log_outside_repo(tmp_path: Path) -> None:
    path = tmp_path / "scale.jsonl"

    assert scale._display_path(path) == str(path)


def test_coverage_summary_separates_ready_from_gaps() -> None:
    rows = [
        {"event": "topic", "topic": "rag", "status": "ok",
         "coverage_status": "ready"},
        {"event": "topic", "topic": "swe_bench", "status": "ok",
         "coverage_status": "coverage_gap"},
        {"event": "topic", "topic": "bad", "status": "failed"},
    ]

    assert scale._coverage_summary(rows) == {
        "topics_run": 3,
        "ready_count": 1,
        "coverage_gap_count": 1,
        "failed_count": 1,
        "planned_count": 0,
        "ready_topics": ["rag"],
        "coverage_gap_topics": ["swe_bench"],
        "failed_topics": ["bad"],
        "planned_topics": [],
    }


def test_run_snapshot_marks_result_index_ready(tmp_path: Path) -> None:
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"data_tier": "ai_results_index"}),
        encoding="utf-8",
    )
    (tmp_path / "opportunities_gate.json").write_text(
        json.dumps({"audits": [{"status": "survives"}]}),
        encoding="utf-8",
    )
    (tmp_path / "publish_verdict.json").write_text(
        json.dumps({"decision": "ready_to_publish", "publish_tier": "TIER_1"}),
        encoding="utf-8",
    )
    (tmp_path / "all_facts.json").write_text(
        json.dumps([{"_tier": "ai_results_index", "result_key": "rag::x::y"}]),
        encoding="utf-8",
    )

    out = scale._run_snapshot(tmp_path)

    assert out["coverage_status"] == "ready"
    assert out["result_key_facts"] == 1
    assert out["audit_count"] == 1


def test_run_snapshot_marks_fallback_as_coverage_gap(tmp_path: Path) -> None:
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"data_tier": "tier2"}),
        encoding="utf-8",
    )
    (tmp_path / "publish_verdict.json").write_text(
        json.dumps({"decision": "curation_needed"}),
        encoding="utf-8",
    )
    (tmp_path / "all_facts.json").write_text(
        json.dumps([{"_tier": "tier2"}]),
        encoding="utf-8",
    )

    assert scale._run_snapshot(tmp_path)["coverage_status"] == "coverage_gap"
