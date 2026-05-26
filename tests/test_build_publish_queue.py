"""Publish queue assembly tests."""
from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

import scripts.build_publish_queue as queue


def _run(root: Path, name: str, *, label: str, lanes: tuple[str, ...]) -> Path:
    run = root / name
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(len(lanes))]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Dispatch threshold paradox\n"
        "**Alpha score:** 80/100\n"
        f"**Confidence:** `{label}`\n\n"
        "## Why this is surprising\n\nReal tension: costs fall while reserves rise.\n",
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
            "canonical_phrase": f"Receipt {fid}",
            "source_paper": {
                "doi": "10.same/a",
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
        lanes=("A_core", "A_core", "A_core"),
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
        lanes=("A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["ready_to_publish"]] == ["tariff"]
    assert [r["topic"] for r in out["curation_needed"]] == ["grid_storage"]


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
        lanes=("A_core", "A_core", "A_core"),
    )
    current_run = _run(
        runs,
        "current-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core"),
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["ready_to_publish"]] == ["archived", "current"]
    assert not archived_run.joinpath("publish_verdict.json").exists()
    assert not current_run.joinpath("publish_verdict.json").exists()
