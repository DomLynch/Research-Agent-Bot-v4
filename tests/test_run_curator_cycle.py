"""Sprint 65 — curator-cycle orchestrator tests.

Locks the orchestration logic that's testable without subprocess:
  - cooldown filter detects recent signal_post.md files
  - discovery JSON parsing finds top-N candidates
  - dry-run plan respects top-N cap + cooldown skip
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_curator_cycle import (
    TopicResult,
    _child_topics_from_verdict,
    _discovery_top_for_plan,
    _plan_topics,
    _read_discovery_top,
    _recent_signal_topics,
    _summarize_md,
    _top_card_summary,
)


def _make_run_with_signal(
    runs_root: Path, topic: str, ts: str, mtime: dt.datetime,
) -> Path:
    """Create a runs/<topic>-evidence-<ts>/signal_post.md with given mtime."""
    run_dir = runs_root / f"{topic}-evidence-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    sig = run_dir / "signal_post.md"
    sig.write_text("# Signal — test\n", encoding="utf-8")
    import os
    epoch = mtime.timestamp()
    os.utime(sig, (epoch, epoch))
    return run_dir


def _write_ready_alpha_run(run_dir: Path, *, source_count: int) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    facts = [
        {
            "fact_id": str(i),
            "source_paper": {
                "doi": f"10.1000/{run_dir.name}-{i}",
                "title": f"Source {i}",
            },
        }
        for i in range(source_count)
    ]
    run_dir.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - receipt" for i in range(source_count))
        + "\n",
        encoding="utf-8",
    )
    run_dir.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run_dir.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": str(i), "lane": "A_core"} for i in range(source_count)
        ],
    }), encoding="utf-8")
    run_dir.joinpath("publish_verdict.json").write_text(
        json.dumps({
            "decision": "ready_to_publish",
            "run_dir": f"runs/{run_dir.name}",
        }),
        encoding="utf-8",
    )


def test_recent_signal_topics_picks_up_recent(tmp_path: Path) -> None:
    now = dt.datetime(2026, 5, 15, 18, 0, tzinfo=dt.UTC)
    # 1h ago — within 24h cooldown
    _make_run_with_signal(tmp_path, "rapamycin", "ts1",
                          now - dt.timedelta(hours=1))
    # 48h ago — outside 24h cooldown
    _make_run_with_signal(tmp_path, "metformin", "ts2",
                          now - dt.timedelta(hours=48))
    recent = _recent_signal_topics(tmp_path, cooldown_hours=24.0, now=now)
    assert recent == {"rapamycin"}


def test_recent_signal_topics_empty_runs_dir() -> None:
    assert _recent_signal_topics(
        Path("/nonexistent"), cooldown_hours=24.0,
        now=dt.datetime(2026, 5, 15, tzinfo=dt.UTC),
    ) == set()


def test_recent_signal_topics_partial_run_without_signal_post(tmp_path: Path) -> None:
    """Partial run folder exists but no signal_post.md -> still cooldown."""
    now = dt.datetime(2026, 5, 15, tzinfo=dt.UTC)
    run = tmp_path / "rapamycin-evidence-ts1"
    run.mkdir()
    import os
    epoch = now.timestamp()
    os.utime(run, (epoch, epoch))
    recent = _recent_signal_topics(
        tmp_path, cooldown_hours=24.0, now=now)
    assert recent == {"rapamycin"}


def test_recent_signal_topics_ignores_non_evidence_dirs(tmp_path: Path) -> None:
    """Folders without '-evidence-' in name are skipped."""
    (tmp_path / "_topics_discovery").mkdir()
    (tmp_path / "_curator_cycles").mkdir()
    recent = _recent_signal_topics(
        tmp_path, cooldown_hours=24.0,
        now=dt.datetime(2026, 5, 15, tzinfo=dt.UTC))
    assert recent == set()


def test_recent_signal_topics_scans_archive(tmp_path: Path) -> None:
    now = dt.datetime(2026, 5, 15, 18, 0, tzinfo=dt.UTC)
    archive = tmp_path / "_archive" / "2026-05-15T18-00-00Z"
    _make_run_with_signal(
        archive, "carbon_tax", "ts1", now - dt.timedelta(hours=2),
    )

    recent = _recent_signal_topics(tmp_path, cooldown_hours=24.0, now=now)

    assert recent == {"carbon_tax"}


def test_read_discovery_top_returns_candidates(tmp_path: Path) -> None:
    p = tmp_path / "2026-05-15T18-00-00Z.json"
    payload: dict[str, Any] = {
        "snapshot_utc": "2026-05-15T18-00-00Z",
        "all": [
            {"topic": "exercise", "velocity_score": 1.57},
            {"topic": "metformin", "velocity_score": 1.38},
        ],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    out = _read_discovery_top(tmp_path)
    assert len(out) == 2
    assert out[0]["topic"] == "exercise"


def test_read_discovery_top_uses_newest_matching_domain(tmp_path: Path) -> None:
    older = tmp_path / "2026-06-09T06-39-50Z.json"
    older.write_text(json.dumps({
        "domain": {"slug": "longevity"},
        "all": [{"topic": "SGLT2_inhibitors", "velocity_score": 1.0}],
    }), encoding="utf-8")
    newer = tmp_path / "2026-06-09T06-42-25Z.json"
    newer.write_text(json.dumps({
        "domain": {"slug": "ai_research"},
        "all": [{"topic": "retrieval_augmented_generation", "velocity_score": 2.0}],
    }), encoding="utf-8")

    out = _read_discovery_top(tmp_path, domain="longevity")

    assert [row["topic"] for row in out] == ["SGLT2_inhibitors"]


def test_read_discovery_top_handles_missing_dir() -> None:
    assert _read_discovery_top(Path("/nonexistent")) == []


def test_read_discovery_top_handles_malformed_json(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    assert _read_discovery_top(tmp_path) == []


def test_read_discovery_top_falls_back_to_top_when_no_all(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({
        "top": [{"topic": "rapamycin", "velocity_score": 0.91}],
    }), encoding="utf-8")
    out = _read_discovery_top(tmp_path)
    assert len(out) == 1
    assert out[0]["topic"] == "rapamycin"


def test_read_discovery_top_skips_topicless_entries(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({
        "all": [
            {"topic": "rapamycin"},
            {"velocity_score": 0.5},          # no topic
            "not-a-dict",
        ],
    }), encoding="utf-8")
    out = _read_discovery_top(tmp_path)
    assert len(out) == 1


def test_stop_on_ready_discovery_overfetches_past_exclusions() -> None:
    assert _discovery_top_for_plan(
        1, stop_on_ready=True, excluded_count=46,
    ) == 47
    assert _discovery_top_for_plan(
        1, stop_on_ready=True, excluded_count=0,
    ) == 20
    assert _discovery_top_for_plan(
        2, stop_on_ready=False, excluded_count=46,
    ) == 20


def test_plan_topics_honors_excluded_before_cooldown() -> None:
    ranked = [
        {"topic": "duplicate", "velocity_score": 9.0},
        {"topic": "recent", "velocity_score": 8.0},
        {"topic": "fresh", "velocity_score": 7.0},
    ]

    plan, skipped, skipped_excluded, below_floor = _plan_topics(
        ranked,
        recent={"recent"},
        excluded={"duplicate"},
        top=1,
    )

    assert [row["topic"] for row in plan] == ["fresh"]
    assert skipped == ["recent"]
    assert skipped_excluded == ["duplicate"]
    assert below_floor == []


def test_plan_topics_dedups_near_identical_phrasings() -> None:
    """Token-shuffled phrasings of one topic are the same submission — only the
    first is planned; a genuinely distinct topic is kept."""
    ranked = [
        {"topic": "multi_agent_systems_higher_accuracy", "velocity_score": 9.0},
        {"topic": "multi_agent_systems_accuracy_higher", "velocity_score": 8.0},
        {"topic": "rapamycin_lifespan_mice", "velocity_score": 7.0},
    ]

    plan, skipped, _, _ = _plan_topics(
        ranked, recent=set(), excluded=set(), top=5,
    )

    topics = [row["topic"] for row in plan]
    assert "multi_agent_systems_higher_accuracy" in topics
    assert "multi_agent_systems_accuracy_higher" not in topics
    assert "rapamycin_lifespan_mice" in topics
    assert "multi_agent_systems_accuracy_higher" in skipped


def test_plan_topics_skips_below_direct_source_floor() -> None:
    ranked = [
        {"topic": "thin", "velocity_score": 9.0, "fact_source_count": 4},
        {"topic": "ready", "velocity_score": 8.0, "fact_source_count": 5},
    ]

    plan, skipped, skipped_excluded, below_floor = _plan_topics(
        ranked, recent=set(), excluded=set(), top=2, min_fact_sources=5,
    )

    assert [row["topic"] for row in plan] == ["ready"]
    assert skipped == []
    assert skipped_excluded == []
    assert below_floor == []


def test_plan_topics_falls_back_to_underfloor_for_exploratory_cycles() -> None:
    ranked = [
        {"topic": "blocked", "velocity_score": 9.0, "fact_source_count": 5},
        {"topic": "thin", "velocity_score": 8.0, "fact_source_count": 2},
    ]

    plan, skipped, skipped_excluded, below_floor = _plan_topics(
        ranked, recent=set(), excluded={"blocked"}, top=1,
    )

    assert [row["topic"] for row in plan] == ["thin"]
    assert skipped == []
    assert skipped_excluded == ["blocked"]
    assert below_floor == []


def test_plan_topics_does_not_rescue_underfloor_in_submit_cycle() -> None:
    ranked = [
        {"topic": "blocked", "velocity_score": 9.0, "fact_source_count": 5},
        {"topic": "thin", "velocity_score": 8.0, "fact_source_count": 2},
    ]

    plan, skipped, skipped_excluded, below_floor = _plan_topics(
        ranked, recent=set(), excluded={"blocked"}, top=1, min_fact_sources=5,
    )

    assert plan == []
    assert skipped == []
    assert skipped_excluded == ["blocked"]
    assert below_floor == []


def test_cached_tier2_supply_caches_hits_and_retries_transient_zeros() -> None:
    """A successful (>0) probe is cached and served without re-probing; a
    transient 0 is not cached, so the next call probes again."""
    from scripts.run_curator_cycle import _cached_tier2_supply

    cache: dict[str, Any] = {}
    calls = {"n": 0}

    def probe_ok() -> int:
        calls["n"] += 1
        return 8

    assert _cached_tier2_supply("longevity:metformin", cache=cache, now=1000.0,
                                probe=probe_ok) == 8
    assert _cached_tier2_supply("longevity:metformin", cache=cache, now=1001.0,
                                probe=probe_ok) == 8
    assert calls["n"] == 1  # second call served from cache, no re-probe

    zero_calls = {"n": 0}

    def probe_zero() -> int:
        zero_calls["n"] += 1
        return 0

    assert _cached_tier2_supply("longevity:senolytic", cache=cache, now=1000.0,
                                probe=probe_zero) == 0
    assert _cached_tier2_supply("longevity:senolytic", cache=cache, now=1001.0,
                                probe=probe_zero) == 0
    assert zero_calls["n"] == 2  # transient 0 not cached → probed both times


def test_plan_topics_tier2_supply_rescues_untagged_rich_topic() -> None:
    """A topic the per-topic facts endpoint reports as 0 is still built when
    the Tier-2 corpus carries >= floor source papers (the build binds them via
    crosscheck). A topic with no Tier-2 supply stays below floor."""
    ranked = [
        {"topic": "metformin", "velocity_score": 9.0, "fact_source_count": 0},
        {"topic": "obscure", "velocity_score": 8.0, "fact_source_count": 0},
    ]
    tier2 = {"metformin": 52}

    plan, _skipped, _skipped_excluded, below_floor = _plan_topics(
        ranked, recent=set(), excluded=set(), top=2, min_fact_sources=5,
        hard_floor=3, tier2_supply=lambda topic: tier2.get(topic, 0),
    )

    assert [row["topic"] for row in plan] == ["metformin"]
    assert below_floor == ["obscure"]


def test_plan_topics_never_builds_zero_source_candidate() -> None:
    """Submit-seeking cycles do not build known-underfloor topics."""
    ranked = [
        {"topic": "dead", "velocity_score": 9.0, "fact_source_count": 0},
        {"topic": "thin", "velocity_score": 8.0, "fact_source_count": 2},
    ]

    plan, _skipped, _excluded, below_floor = _plan_topics(
        ranked, recent=set(), excluded=set(), top=5,
        min_fact_sources=5, hard_floor=3,
    )

    assert plan == []
    assert below_floor == ["dead", "thin"]


def test_plan_topics_builds_candidate_meeting_preferred_floor() -> None:
    """A topic at/above the preferred floor still builds; a 3-4 source topic is
    rescued only via fallback; sub-floor (<3) is never built."""
    ranked = [
        {"topic": "ready", "velocity_score": 7.0, "fact_source_count": 5},
        {"topic": "mid", "velocity_score": 9.0, "fact_source_count": 3},
        {"topic": "dead", "velocity_score": 8.0, "fact_source_count": 1},
    ]

    plan, _skipped, _excluded, below_floor = _plan_topics(
        ranked, recent=set(), excluded=set(), top=5,
        min_fact_sources=5, hard_floor=3,
    )

    assert [row["topic"] for row in plan] == ["ready"]  # only >=5 planned
    assert below_floor == ["dead"]  # <3 dropped; 'mid' (3) kept in reserve


def test_submit_plan_skips_zero_paper_cached_candidates() -> None:
    ranked = [
        {"topic": "count_only", "velocity_score": 9.0, "fact_source_count": 12, "paper_count": 0},
        {"topic": "paper_backed", "velocity_score": 8.0, "fact_source_count": 5, "paper_count": 3},
    ]

    plan, _skipped, _excluded, below_floor = _plan_topics(
        ranked,
        recent=set(),
        excluded=set(),
        top=1,
        min_fact_sources=5,
        hard_floor=3,
        require_papers=True,
    )

    assert [row["topic"] for row in plan] == ["paper_backed"]
    assert below_floor == ["count_only"]


def test_summarize_md_renders_table() -> None:
    results = [
        TopicResult(topic="rapamycin", velocity=0.91, status="ran",
                    run_dir="runs/rapamycin-evidence-x",
                    signal_label="frontier_hypothesis", notes=""),
        TopicResult(topic="metformin", velocity=1.38, status="failed",
                    run_dir="", signal_label="",
                    notes="build_step: timeout"),
    ]
    md = _summarize_md("2026-05-15T19-00-00Z", results,
                        skipped=["exercise"],
                        cooldown_hours=24.0, top_requested=3)
    assert "Curator cycle" in md
    assert "rapamycin" in md and "metformin" in md
    assert "frontier_hypothesis" in md
    assert "Skipped" in md and "exercise" in md


def test_top_card_summary_reads_first_finding_and_alpha_cues(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "topic-evidence-ts"
    run_dir.mkdir(parents=True)
    (run_dir / "top_5.md").write_text(
        "# Top 1\n\n"
        "## #1 — score 90\n\n"
        "**Finding:** mortality was lower by 11%.\n"
        "- **Alpha cues:** functional_endpoint\n",
        encoding="utf-8",
    )
    import run_curator_cycle
    old_root = run_curator_cycle._ROOT
    try:
        run_curator_cycle._ROOT = tmp_path
        finding, cues = _top_card_summary("runs/topic-evidence-ts")
    finally:
        run_curator_cycle._ROOT = old_root
    assert finding == "mortality was lower by 11%."
    assert cues == "functional_endpoint"


def test_topic_result_round_trips() -> None:
    r = TopicResult(topic="x", velocity=1.0, status="ran",
                    run_dir="runs/x-evidence-y", signal_label="x", notes="")
    d = r.as_dict()
    assert d["topic"] == "x"
    assert d["velocity"] == 1.0


def test_topic_pipeline_skips_pico_by_default(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    run_dir = tmp_path / "runs" / "topic-evidence-ts"
    run_dir.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_step(args: list[str], _step: str) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)

    run_curator_cycle._run_topic_pipeline(
        "topic", 1.0, with_editorial=True, top_n=5, py="python",
        frontier_review=False,
    )

    assert calls[0][calls[0].index("--domain") + 1] == "longevity"
    assert "--with-editorial" in calls[0]
    assert "--no-frontier" in calls[0]
    assert "--no-pico-enrich" in calls[0]


def test_topic_pipeline_passes_explicit_ai_research_domain(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    run_dir = tmp_path / "runs" / "topic-evidence-ts"
    run_dir.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_step(args: list[str], _step: str) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)

    run_curator_cycle._run_topic_pipeline(
        "topic", 1.0, with_editorial=False, top_n=5, py="python",
        frontier_review=False, domain="ai_research",
    )

    assert calls[0][calls[0].index("--domain") + 1] == "ai_research"


def test_cycle_rebuilds_publish_queue_for_selected_domain(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    calls: list[tuple[str, list[str]]] = []

    def fake_step(
        args: list[str], step_name: str, *, timeout: int = 600,
    ) -> tuple[bool, str]:
        calls.append((step_name, args))
        return True, "ok"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)
    monkeypatch.setattr(
        run_curator_cycle,
        "_run_topic_pipeline",
        lambda *_args, **_kwargs: TopicResult(
            topic="ai_agents", velocity=1.0, status="ran",
            run_dir="runs/ai_agents-evidence-ts",
            signal_label="frontier_hypothesis", notes="",
        ),
    )
    monkeypatch.setattr(
        run_curator_cycle, "_read_discovery_top",
        lambda _out, **_kwargs: [{
            "topic": "ai_agents", "velocity_score": 1.0,
            "fact_source_count": 5, "paper_count": 3,
        }],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--domain", "ai_research", "--top", "1",
    ])

    assert run_curator_cycle.main() == 0
    queue_args = next(args for step, args in calls if step == "publish_queue")
    assert queue_args[queue_args.index("--domain") + 1] == "ai_research"


def test_discovery_failure_aborts_before_stale_plan(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    calls: list[tuple[str, int]] = []

    def fake_step(
        _args: list[str], step_name: str, *, timeout: int = 600,
    ) -> tuple[bool, str]:
        calls.append((step_name, timeout))
        return False, "discovery: TimeoutExpired"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)
    monkeypatch.setattr(
        run_curator_cycle, "_run_topic_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError),
    )
    monkeypatch.setattr(sys, "argv", ["run_curator_cycle.py", "--top", "2"])

    assert run_curator_cycle.main() == 1
    assert calls == [("discovery", 1800)]


def test_warm_backlog_passes_full_probe_flag_to_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    calls: list[list[str]] = []

    def fake_step(
        args: list[str], step_name: str, *, timeout: int = 600,
    ) -> tuple[bool, str]:
        calls.append(args)
        return False, "stop after discovery"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--warm-backlog",
    ])

    assert run_curator_cycle.main() == 1
    assert "--warm-backlog" in calls[0]


def test_stop_on_ready_uses_cache_first_discovery(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    calls: list[list[str]] = []

    def fake_step(
        args: list[str], step_name: str, *, timeout: int = 600,
    ) -> tuple[bool, str]:
        calls.append(args)
        return False, "stop after discovery"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--stop-on-ready",
    ])

    assert run_curator_cycle.main() == 1
    assert "--cache-first" in calls[0]
    assert calls[0][calls[0].index("--top") + 1] == "20"


def test_stop_on_ready_warm_backlog_probes_beyond_cache(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    calls: list[list[str]] = []

    def fake_step(
        args: list[str], step_name: str, *, timeout: int = 600,
    ) -> tuple[bool, str]:
        calls.append(args)
        return False, "stop after discovery"

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_curator_cycle, "_run_step", fake_step)
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--stop-on-ready", "--warm-backlog",
        "--fact-probe-topics", "5", "--exclude-topic", "old_winner",
    ])

    assert run_curator_cycle.main() == 1
    assert "--cache-first" not in calls[0]
    assert "--warm-backlog" in calls[0]
    assert "--cache-only" not in calls[0]
    assert "--fact-probe-topics" in calls[0]
    assert calls[0][calls[0].index("--fact-probe-topics") + 1] == "5"
    assert "--exclude-topic" in calls[0]
    assert calls[0][calls[0].index("--exclude-topic") + 1] == "old_winner"


def test_stop_on_ready_halts_plan(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        run_dir = runs / f"{topic}-evidence-ts"
        _write_ready_alpha_run(run_dir, source_count=5)
        return TopicResult(
            topic=topic, velocity=velocity, status="ran",
            run_dir=f"runs/{topic}-evidence-ts",
            signal_label="evidence_backed_signal", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(
        run_curator_cycle, "_read_discovery_top",
        lambda _out, **_kwargs: [
            {"topic": "ready", "velocity_score": 2.0, "fact_source_count": 5, "paper_count": 3},
            {"topic": "later", "velocity_score": 1.0, "fact_source_count": 5, "paper_count": 3},
        ],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "2", "--stop-on-ready",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == ["ready"]
    payload = json.loads(next(cycles.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["stopped_on_ready"] is True


def test_stop_on_ready_ignores_under_source_candidate(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []
    top_values: list[int] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        top_values.append(top_n)
        run_dir = runs / f"{topic}-evidence-ts"
        _write_ready_alpha_run(run_dir, source_count=4 if topic == "thin" else 5)
        return TopicResult(
            topic=topic, velocity=velocity, status="ran",
            run_dir=f"runs/{topic}-evidence-ts",
            signal_label="evidence_backed_signal", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(
        run_curator_cycle, "_read_discovery_top",
        lambda _out, **_kwargs: [
            {"topic": "thin", "velocity_score": 2.0, "fact_source_count": 5, "paper_count": 3},
            {"topic": "ready", "velocity_score": 1.0, "fact_source_count": 5, "paper_count": 3},
        ],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "2", "--stop-on-ready",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == ["thin", "ready"]
    assert top_values == [10, 10]
    payload = json.loads(next(cycles.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["stopped_on_ready"] is True


def test_stop_on_ready_skips_count_only_cached_candidate(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        run_dir = runs / f"{topic}-evidence-ts"
        _write_ready_alpha_run(run_dir, source_count=5)
        return TopicResult(
            topic=topic, velocity=velocity, status="ran",
            run_dir=f"runs/{topic}-evidence-ts",
            signal_label="evidence_backed_signal", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(
        run_curator_cycle, "_read_discovery_top",
        lambda _out, **_kwargs: [
            {
                "topic": "count_only_cached", "velocity_score": 9.0,
                "fact_source_count": 12, "paper_count": 0,
            },
            {
                "topic": "paper_backed", "velocity_score": 8.0,
                "fact_source_count": 5, "paper_count": 3,
            },
        ],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "1", "--stop-on-ready",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == ["paper_backed"]
    payload = json.loads(next(cycles.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["skipped_below_source_floor"] == ["count_only_cached"]
    assert payload["stopped_on_ready"] is True


def test_stop_on_ready_runs_structural_child_topic_before_giving_up(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []
    parents: list[str] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        parents.append(parent_topic)
        run_dir = runs / f"{topic}-evidence-ts"
        if topic == "parent":
            run_dir.mkdir(parents=True)
            run_dir.joinpath("publish_verdict.json").write_text(json.dumps({
                "decision": "agent_repair_needed",
                "topic": "parent",
                "run_dir": "runs/parent-evidence-ts",
                "subtopic_recommendations": {
                    "recommended": True,
                    "clusters": [{"label": "bounded_claim_cluster"}],
                },
            }), encoding="utf-8")
            return TopicResult(
                topic=topic, velocity=velocity, status="ran",
                run_dir="runs/parent-evidence-ts",
                signal_label="frontier_hypothesis", notes="",
            )
        _write_ready_alpha_run(run_dir, source_count=5)
        return TopicResult(
            topic=topic, velocity=velocity, status="ran",
            run_dir=f"runs/{topic}-evidence-ts",
            signal_label="evidence_backed_signal", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(
        run_curator_cycle, "_read_discovery_top",
        lambda _out, **_kwargs: [
            {"topic": "parent", "velocity_score": 2.0, "fact_source_count": 5, "paper_count": 3},
        ],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "1", "--stop-on-ready",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == ["parent", "parent_bounded_claim_cluster"]
    assert parents == ["", "parent"]
    payload = json.loads(next(cycles.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["stopped_on_ready"] is True


def test_stop_on_ready_does_not_chain_child_topic_reruns(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        run_dir = runs / f"{topic}-evidence-ts"
        run_dir.mkdir(parents=True)
        run_dir.joinpath("publish_verdict.json").write_text(json.dumps({
            "decision": "agent_repair_needed",
            "topic": topic,
            "run_dir": f"runs/{topic}-evidence-ts",
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [{"label": "bounded_claim_cluster"}],
            },
        }), encoding="utf-8")
        return TopicResult(
            topic=topic, velocity=velocity, status="ran",
            run_dir=f"runs/{topic}-evidence-ts",
            signal_label="frontier_hypothesis", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(
        run_curator_cycle, "_read_discovery_top",
        lambda _out, **_kwargs: [
            {"topic": "parent", "velocity_score": 2.0, "fact_source_count": 5, "paper_count": 3},
        ],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "1", "--stop-on-ready",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == ["parent", "parent_bounded_claim_cluster"]


def test_deep_parent_spawns_no_child_topics(tmp_path: Path, monkeypatch: Any) -> None:
    """A parent that is already an accreted child (>= _MAX_TOPIC_TOKENS tokens)
    spawns no further children, so the slug cannot grow into word-salad across
    cycles. A shallow parent still splits, but the child is token-capped."""
    import run_curator_cycle

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)

    def _write(topic: str) -> str:
        run_dir = f"runs/{topic}-evidence-ts"
        (tmp_path / run_dir).mkdir(parents=True)
        (tmp_path / run_dir / "publish_verdict.json").write_text(json.dumps({
            "topic": topic,
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [{"label": "training_control_resistance_care_usual"}],
            },
        }), encoding="utf-8")
        return run_dir

    deep = _write("exercise_difference_training_control")
    assert run_curator_cycle._child_topics_from_verdict(deep, set()) == []

    shallow = _write("exercise")
    children = run_curator_cycle._child_topics_from_verdict(shallow, set())
    assert children == ["exercise_training_control_resistance"]
    assert all(run_curator_cycle.topic_token_count(c) <= 4 for c in children)


def test_priority_repair_topic_does_not_spawn_child_rerun(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        run_dir = runs / f"{topic}-evidence-ts"
        run_dir.mkdir(parents=True)
        run_dir.joinpath("publish_verdict.json").write_text(json.dumps({
            "decision": "agent_repair_needed",
            "topic": topic,
            "run_dir": f"runs/{topic}-evidence-ts",
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [{"label": "next_child"}],
            },
        }), encoding="utf-8")
        return TopicResult(
            topic=topic, velocity=velocity, status="ran",
            run_dir=f"runs/{topic}-evidence-ts",
            signal_label="frontier_hypothesis", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(run_curator_cycle, "_read_discovery_top", lambda _out, **_kwargs: [])
    monkeypatch.setattr(
        run_curator_cycle, "_priority_ranked_topics",
        lambda _topics, **_kwargs: [{
            "topic": "queued_child",
            "velocity_score": 0.0,
            "fact_source_count": 5,
            "paper_count": 1,
            "child_depth": 1,
        }],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "1", "--stop-on-ready",
        "--priority-topic", "queued_child",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == ["queued_child"]


def test_priority_ranked_topics_uses_fact_source_probe(monkeypatch: Any) -> None:
    import run_curator_cycle

    class DummyClient:
        def __enter__(self) -> DummyClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    calls: list[tuple[str, str]] = []
    counts = {"strong_child": 5, "weak_child": 0}
    monkeypatch.setattr(run_curator_cycle, "load_settings", lambda: object())
    monkeypatch.setattr(run_curator_cycle.httpx, "Client", DummyClient)

    def fake_count(topic: str, *, client: Any, settings: Any, domain: str) -> int:
        calls.append((topic, domain))
        return counts[topic]

    monkeypatch.setattr(run_curator_cycle, "_fetch_topic_fact_source_count", fake_count)

    ranked = run_curator_cycle._priority_ranked_topics([
        "strong_child", "weak_child",
    ], domain="ai_research")

    assert [
        (row["topic"], row["fact_source_count"], row["paper_count"], row["child_depth"])
        for row in ranked
    ] == [
        ("strong_child", 5, 1, 1),
        ("weak_child", 0, 0, 1),
    ]
    assert calls == [("strong_child", "ai_research"), ("weak_child", "ai_research")]


def test_underfloor_priority_repair_topic_is_not_built(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import run_curator_cycle

    runs = tmp_path / "runs"
    cycles = runs / "_curator_cycles"
    cycles.mkdir(parents=True)
    seen: list[str] = []

    def fake_pipeline(
        topic: str, velocity: float, *, with_editorial: bool,
        top_n: int, py: str, pico_enrich: bool = False,
        frontier_review: bool = True, parent_topic: str = "",
        domain: str = "longevity",
    ) -> TopicResult:
        seen.append(topic)
        return TopicResult(
            topic=topic, velocity=velocity, status="ran", run_dir="",
            signal_label="", notes="",
        )

    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)
    monkeypatch.setattr(run_curator_cycle, "_RUNS", runs)
    monkeypatch.setattr(run_curator_cycle, "_CYCLES_DIR", cycles)
    monkeypatch.setattr(run_curator_cycle, "_run_topic_pipeline", fake_pipeline)
    monkeypatch.setattr(run_curator_cycle, "_read_discovery_top", lambda _out, **_kwargs: [])
    monkeypatch.setattr(
        run_curator_cycle, "_priority_ranked_topics",
        lambda _topics, **_kwargs: [{
            "topic": "weak_child",
            "velocity_score": 0.0,
            "fact_source_count": 0,
            "paper_count": 0,
            "child_depth": 1,
        }],
    )
    monkeypatch.setattr(run_curator_cycle, "_recent_signal_topics",
                        lambda *_args, **_kwargs: set())
    monkeypatch.setattr(run_curator_cycle, "_run_step",
                        lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(sys, "argv", [
        "run_curator_cycle.py", "--top", "1", "--stop-on-ready",
        "--priority-topic", "weak_child",
    ])

    assert run_curator_cycle.main() == 0
    assert seen == []
    payload = json.loads(next(cycles.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["skipped_below_source_floor"] == ["weak_child"]


def test_universal_non_biomedical_topic(tmp_path: Path) -> None:
    """Cooldown filter works on any topic identifier — no biomedical
    assumption."""
    now = dt.datetime(2026, 5, 15, tzinfo=dt.UTC)
    _make_run_with_signal(tmp_path, "carbon_tax", "ts1",
                          now - dt.timedelta(hours=2))
    recent = _recent_signal_topics(tmp_path, cooldown_hours=24.0, now=now)
    assert recent == {"carbon_tax"}


def test_child_topics_drop_function_word_labels(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """A cluster label that reduces to a stopword ('was') must never become a
    child topic — the live "..._was" regression that bound zero receipts."""
    import run_curator_cycle

    run_dir = tmp_path / "runs" / "therapeutic_plasma_exchange-evidence-ts"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("publish_verdict.json").write_text(json.dumps({
        "decision": "agent_repair_needed",
        "topic": "therapeutic_plasma_exchange",
        "subtopic_recommendations": {
            "recommended": True,
            "clusters": [
                {"label": "was"},      # pure stopword -> dropped
                {"label": "parabiosis"},  # real content -> kept (within token cap)
            ],
        },
    }), encoding="utf-8")
    monkeypatch.setattr(run_curator_cycle, "_ROOT", tmp_path)

    children = _child_topics_from_verdict(
        "runs/therapeutic_plasma_exchange-evidence-ts", set(),
    )

    assert children == ["therapeutic_plasma_exchange_parabiosis"]
    assert not any(c.endswith("_was") for c in children)
