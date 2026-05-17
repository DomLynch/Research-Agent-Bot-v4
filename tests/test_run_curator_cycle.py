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


def test_recent_signal_topics_no_signal_post_yet(tmp_path: Path) -> None:
    """Run folder exists but no signal_post.md -> topic isn't in cooldown."""
    (tmp_path / "rapamycin-evidence-ts1").mkdir()
    recent = _recent_signal_topics(
        tmp_path, cooldown_hours=24.0,
        now=dt.datetime(2026, 5, 15, tzinfo=dt.UTC))
    assert recent == set()


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


def test_universal_non_biomedical_topic(tmp_path: Path) -> None:
    """Cooldown filter works on any topic identifier — no biomedical
    assumption."""
    now = dt.datetime(2026, 5, 15, tzinfo=dt.UTC)
    _make_run_with_signal(tmp_path, "carbon_tax", "ts1",
                          now - dt.timedelta(hours=2))
    recent = _recent_signal_topics(tmp_path, cooldown_hours=24.0, now=now)
    assert recent == {"carbon_tax"}
