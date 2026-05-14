"""Sprint 58 — curator-quality aggregator tests.

Locks the contract:
  - error_rate = dies / facts_audited
  - empty runs dir -> empty tuple
  - skips non-evidence dirs + dirs without source_audit/all_facts
  - joins verdicts to facts via fact_id; recovers validator field
  - tolerates malformed JSON (skips, doesn't raise)
  - aggregates across multiple runs / topics
  - sort order: error_rate desc, dies desc
  - dashboard renders markdown with curator rows
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.curator_quality import (
    CuratorStats,
    aggregate_from_runs,
    render_dashboard_md,
)


def _write(p: Path, obj: object) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _make_run(root: Path, topic: str, ts: str,
              verdicts: list[dict[str, object]],
              facts: list[dict[str, object]]) -> Path:
    run = root / f"{topic}-evidence-{ts}"
    _write(run / "source_audit.json",
           {"topic": topic, "snapshot_utc": ts, "verdicts": verdicts})
    _write(run / "all_facts.json", facts)
    return run


def test_empty_runs_root_returns_empty() -> None:
    assert aggregate_from_runs(Path("/nonexistent-dir-xyz")) == ()


def test_missing_files_skip_silently(tmp_path: Path) -> None:
    (tmp_path / "rapamycin-evidence-001").mkdir()  # empty
    (tmp_path / "non-evidence-dir").mkdir()         # wrong name
    assert aggregate_from_runs(tmp_path) == ()


def test_aggregates_single_run(tmp_path: Path) -> None:
    _make_run(
        tmp_path, "rapamycin", "ts-1",
        verdicts=[
            {"fact_id": "f/a", "verdict": "dies"},
            {"fact_id": "f/b", "verdict": "survives"},
            {"fact_id": "f/c", "verdict": "needs_extraction"},
        ],
        facts=[
            {"fact_id": "f/a", "validator": "curator-x"},
            {"fact_id": "f/b", "validator": "curator-x"},
            {"fact_id": "f/c", "validator": "curator-y"},
        ],
    )
    stats = aggregate_from_runs(tmp_path)
    by_id = {s.curator_id: s for s in stats}
    assert "curator-x" in by_id and "curator-y" in by_id
    x = by_id["curator-x"]
    assert x.facts_audited == 2
    assert x.survives == 1 and x.dies == 1
    assert x.error_rate == 0.5


def test_aggregates_across_multiple_runs(tmp_path: Path) -> None:
    _make_run(tmp_path, "rapamycin", "ts-1",
              verdicts=[{"fact_id": "f/1", "verdict": "dies"}],
              facts=[{"fact_id": "f/1", "validator": "curator-bad"}])
    _make_run(tmp_path, "metformin", "ts-2",
              verdicts=[{"fact_id": "f/2", "verdict": "dies"},
                        {"fact_id": "f/3", "verdict": "survives"}],
              facts=[{"fact_id": "f/2", "validator": "curator-bad"},
                     {"fact_id": "f/3", "validator": "curator-good"}])
    stats = aggregate_from_runs(tmp_path)
    by_id = {s.curator_id: s for s in stats}
    bad = by_id["curator-bad"]
    assert bad.facts_audited == 2
    assert bad.dies == 2
    assert sorted(bad.topics_touched) == ["metformin", "rapamycin"]


def test_sort_order_error_rate_descending(tmp_path: Path) -> None:
    _make_run(tmp_path, "topicA", "ts-1",
              verdicts=[{"fact_id": "f/a", "verdict": "dies"},
                        {"fact_id": "f/b", "verdict": "survives"}],
              facts=[{"fact_id": "f/a", "validator": "low-error"},
                     {"fact_id": "f/b", "validator": "low-error"}])
    _make_run(tmp_path, "topicB", "ts-2",
              verdicts=[{"fact_id": "f/c", "verdict": "dies"},
                        {"fact_id": "f/d", "verdict": "dies"}],
              facts=[{"fact_id": "f/c", "validator": "high-error"},
                     {"fact_id": "f/d", "validator": "high-error"}])
    stats = aggregate_from_runs(tmp_path)
    assert stats[0].curator_id == "high-error"
    assert stats[0].error_rate == 1.0
    assert stats[1].curator_id == "low-error"
    assert stats[1].error_rate == 0.5


def test_missing_validator_buckets_to_unknown(tmp_path: Path) -> None:
    _make_run(tmp_path, "topicA", "ts-1",
              verdicts=[{"fact_id": "f/a", "verdict": "dies"}],
              facts=[{"fact_id": "f/a"}])  # no validator field
    stats = aggregate_from_runs(tmp_path)
    assert stats[0].curator_id == "unknown"


def test_malformed_json_skipped(tmp_path: Path) -> None:
    run = tmp_path / "topicA-evidence-bad"
    run.mkdir(parents=True)
    (run / "source_audit.json").write_text("not json", encoding="utf-8")
    (run / "all_facts.json").write_text("[]", encoding="utf-8")
    # Should not raise.
    assert aggregate_from_runs(tmp_path) == ()


def test_disagreement_counted(tmp_path: Path) -> None:
    _make_run(tmp_path, "topicA", "ts-1",
              verdicts=[{"fact_id": "f/a", "verdict": "disagreement"}],
              facts=[{"fact_id": "f/a", "validator": "c"}])
    stats = aggregate_from_runs(tmp_path)
    assert stats[0].disagreement == 1
    assert stats[0].dies == 0


def test_render_dashboard_includes_curators(tmp_path: Path) -> None:
    _make_run(tmp_path, "topicA", "ts-1",
              verdicts=[{"fact_id": "f/a", "verdict": "dies"}],
              facts=[{"fact_id": "f/a", "validator": "curator-x"}])
    md = render_dashboard_md(aggregate_from_runs(tmp_path))
    assert "Curator-quality dashboard" in md
    assert "curator-x" in md
    assert "1" in md  # facts audited


def test_render_dashboard_empty_message() -> None:
    md = render_dashboard_md(())
    assert "No source_audit.json files found" in md


def test_curator_stats_round_trip() -> None:
    s = CuratorStats(
        curator_id="bootstrap-claude", facts_audited=10, survives=3,
        dies=5, needs_extraction=2, disagreement=0,
        topics_touched=("rapamycin", "metformin"),
    )
    assert s.error_rate == 0.5
    d = s.as_dict()
    assert d["error_rate"] == 0.5
    assert d["topics_touched"] == ["rapamycin", "metformin"]


def test_universal_non_biomedical(tmp_path: Path) -> None:
    """Non-biomedical curator-id (climate policy) aggregates identically."""
    _make_run(tmp_path, "carbon_tax", "ts-1",
              verdicts=[{"fact_id": "ct/swe", "verdict": "dies"}],
              facts=[{"fact_id": "ct/swe", "validator": "ipcc-wg3-2026"}])
    stats = aggregate_from_runs(tmp_path)
    assert stats[0].curator_id == "ipcc-wg3-2026"
    assert stats[0].topics_touched == ("carbon_tax",)
