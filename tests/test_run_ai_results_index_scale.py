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
