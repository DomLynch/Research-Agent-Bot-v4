"""Publish queue assembly tests."""
from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

import scripts.build_publish_queue as queue


def test_write_queue_uses_output_lock(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    queue._write_json(tmp_path / "_publish_queue.json", {"ready_to_publish": []})

    assert ("_publish_queue.json.lock", fcntl.LOCK_EX) in lock_calls


def _run(root: Path, name: str, *, label: str, lanes: tuple[str, ...]) -> Path:
    run = root / name
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(len(lanes))]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Dispatch threshold paradox\n"
        "**Alpha score:** 80/100\n"
        f"**Confidence:** `{label}`\n\n"
        "## Why this is surprising\n\nReal tension: costs fall while reserves rise.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(
            f"- `fact_id={fid}` (`{lane}`) - receipt"
            for fid, lane in zip(ids, lanes, strict=True)
        )
        + "\n",
        encoding="utf-8",
    )
    run.joinpath("opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "status": "survives",
            "capped_opportunity": 80,
            "cited_fact_ids": ids,
        }],
    }), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": fid, "lane": lane}
            for fid, lane in zip(ids, lanes, strict=True)
        ],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": (
                f"Grid dispatch threshold improves reserve reliability receipt {fid}"
            ),
            "source_paper": {
                "doi": f"10.same/{fid}",
                "title": "Grid dispatch threshold improves reserve reliability",
                "journal": "Grid Systems",
                "year": 2026,
            },
        }
        for fid in ids
    ]), encoding="utf-8")
    return run


def test_build_queue_keeps_latest_run_per_topic(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    archive = runs / "_archive" / "old"
    _run(
        archive,
        "grid_storage-evidence-2026-01-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    _run(
        runs,
        "grid_storage-evidence-2026-02-01T00-00-00Z",
        label="no_signal",
        lanes=("D_bad_extraction",),
    )
    _run(
        runs,
        "tariff-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["ready_to_publish"]] == ["tariff"]
    assert [r["topic"] for r in out["curation_needed"]] == ["grid_storage"]


def test_build_queue_routes_tier2_to_agent_repair_bucket(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    _run(
        runs,
        "thin-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["agent_repair_needed"]] == ["thin"]
    assert "needs_operator_review" not in out


def test_build_queue_does_not_mutate_run_verdict_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    archive = runs / "_archive" / "old"
    archived_run = _run(
        archive,
        "archived-evidence-2026-01-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    current_run = _run(
        runs,
        "current-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["ready_to_publish"]] == ["archived", "current"]
    assert not archived_run.joinpath("publish_verdict.json").exists()
    assert not current_run.joinpath("publish_verdict.json").exists()


def test_build_queue_recomputes_stale_verdict_sidecar(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run = _run(
        runs,
        "grid_storage-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    run.joinpath("publish_verdict.json").write_text(json.dumps({
        "topic": "grid_storage",
        "decision": "curation_needed",
        "publish_tier": "TIER_3",
        "alpha_score": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["ready_to_publish"]] == ["grid_storage"]


def test_build_queue_normalises_legacy_operator_decision(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run = runs / "legacy-evidence-2026-02-01T00-00-00Z"
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text("# Legacy memo\n", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps({
        "topic": "legacy",
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "alpha_score": 80,
    }), encoding="utf-8")
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["agent_repair_needed"]] == ["legacy"]
    assert "needs_operator_review" not in out


def test_build_queue_filters_by_domain_metadata(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    _run(
        runs,
        "grid_storage-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    ai_run = _run(
        runs,
        "ai_agents-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    ai_run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True, domain="ai_research")

    assert [r["topic"] for r in out["ready_to_publish"]] == ["ai_agents"]


def test_build_queue_domain_filter_excludes_seed_mismatched_ai_runs(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    stale = _run(
        runs,
        "SGLT2_inhibitors-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    stale.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    ai_run = _run(
        runs,
        "ai_agents-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    ai_run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True, domain="ai_research")

    assert [r["topic"] for r in out["ready_to_publish"]] == ["ai_agents"]


def test_build_queue_domain_filter_defaults_untagged_runs_to_longevity(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    _run(
        runs,
        "grid_storage-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True, domain="longevity")

    assert [r["topic"] for r in out["ready_to_publish"]] == ["grid_storage"]


def test_build_queue_domain_filter_excludes_untagged_runs_for_ai(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    _run(
        runs,
        "grid_storage-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True, domain="ai_research")

    assert out["ready_to_publish"] == []


def test_build_queue_reports_pre_memo_stage_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run = runs / "ai_agents-evidence-2026-02-01T00-00-00Z"
    run.mkdir(parents=True)
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True, domain="ai_research")

    assert out["ready_to_publish"] == []
    assert [row["topic"] for row in out["not_ready"]] == ["ai_agents"]
    assert out["not_ready"][0]["domain"]["slug"] == "ai_research"
    assert "missing_alpha_memo" in out["not_ready"][0]["blockers"]
