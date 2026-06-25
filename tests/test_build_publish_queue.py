"""Publish queue assembly tests."""
from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

import scripts.build_publish_queue as queue
from scripts import daily_alpha_publish_cycle as daily


def test_write_queue_uses_output_lock(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    queue._write_json(tmp_path / "_publish_queue.json", {"ready_to_publish": []})

    assert ("_publish_queue.json.lock", fcntl.LOCK_EX) in lock_calls


def test_domain_queue_cli_writes_domain_sidecar_without_global_overwrite(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
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
    monkeypatch.setattr(sys, "argv", [
        "build_publish_queue.py", "--domain", "ai_research",
    ])

    assert queue.main() == 0

    sidecar = json.loads(
        (runs / "_publish_queue.ai_research.json").read_text(encoding="utf-8"),
    )
    assert not (runs / "_publish_queue.json").exists()
    rows = [
        row
        for bucket_rows in sidecar.values()
        if isinstance(bucket_rows, list)
        for row in bucket_rows
    ]
    assert rows
    assert {row["domain_slug"] for row in rows} == {"ai_research"}


def test_build_queue_includes_pre_memo_diagnostic_failures(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    diagnostics = runs / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    diagnostics.joinpath("business_research-pricing_strategy_margin.json").write_text(
        json.dumps({
            "domain": "business_research",
            "topic": "pricing_strategy_margin",
            "raw_fact_count": 1,
            "normalized_fact_count": 1,
            "a_core_fact_count": 1,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=False, domain="business_research")

    assert out["ready_to_publish"] == []
    assert len(out["not_ready"]) == 1
    row = out["not_ready"][0]
    assert row["topic"] == "pricing_strategy_margin"
    assert row["domain_slug"] == "business_research"
    assert row["domain"]["slug"] == "business_research"
    assert row["decision"] == "not_ready"
    assert row["publish_tier"] == "UNBUILT"
    assert row["stage"] == "no_source_diverse_bundle"
    assert row["queue_status"] == "no_source_diverse_bundle"
    assert row["blockers"] == ["no_source_diverse_bundle"]
    assert row["diagnostics_path"] == str(
        diagnostics.joinpath("business_research-pricing_strategy_margin.json"),
    )
    assert row["raw_fact_count"] == 1
    assert row["normalized_fact_count"] == 1
    assert row["a_core_fact_count"] == 1


def test_build_queue_prefers_run_row_over_matching_diagnostic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run = _run(
        runs,
        "ai_agents-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    diagnostics = runs / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    diagnostics.joinpath("ai_research-ai_agents.json").write_text(
        json.dumps({
            "domain": "ai_research",
            "topic": "ai_agents",
            "raw_fact_count": 0,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=False, domain="ai_research")

    rows = sum(len(rows) for rows in out.values())
    assert rows == 1
    assert out["not_ready"] == []
    assert out["ready_to_publish"][0]["topic"] == "ai_agents"


def test_duplicate_runs_do_not_mutate_run_verdict_files(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run = _run(
        runs,
        "open_source_models-evidence-2026-02-01T00-00-00Z",
        label="evidence_backed_signal",
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
    )
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    monkeypatch.setattr(queue, "_RUNS", runs)
    first = queue.build_queue(include_archive=False, domain="ai_research")
    ready = first["ready_to_publish"][0]
    verdict_path = run / "publish_verdict.json"
    before = verdict_path.read_text(encoding="utf-8") if verdict_path.exists() else ""
    submitted = runs / "_daily_ledger" / "_submitted_fingerprints.json"
    submitted.parent.mkdir(parents=True)
    submitted.write_text(json.dumps([{
        "domain_slug": "ai_research",
        "fingerprint": daily.memo_fingerprint(ready),
        "memo_sha256": daily._memo_sha256(ready, runs),
        "topic": "open_source_models",
    }]), encoding="utf-8")

    out = queue.build_queue(include_archive=False, domain="ai_research")

    after = verdict_path.read_text(encoding="utf-8") if verdict_path.exists() else ""
    assert after == before
    assert out["ready_to_publish"] == []
    assert [r["topic"] for r in out["curation_needed"]] == ["open_source_models"]
    assert out["curation_needed"][0]["queue_status"] == (
        "duplicate_submission_fingerprint"
    )


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
    assert out["not_ready"][0]["domain_slug"] == "ai_research"
    assert "missing_alpha_memo" in out["not_ready"][0]["blockers"]


def _stored_evidence_map_run(
    root: Path,
    name: str,
    *,
    shared_axis: str | None,
) -> Path:
    run = root / name
    run.mkdir(parents=True)
    fact_ids = [str(i) for i in range(1, 11)]
    run.joinpath("business_candidate_bundle.json").write_text("{}", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps({
        "topic": name.split("-evidence-", 1)[0],
        "decision": "ready_to_publish",
        "publish_tier": "TIER_1",
        "surface_type": "evidence_map",
        "alpha_score": 90,
        "run_dir": str(run),
    }), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": fid, "lane": "A_core"} for fid in fact_ids
        ],
    }), encoding="utf-8")
    facts = []
    for fid in fact_ids:
        population = shared_axis or f"group{fid}"
        facts.append({
            "fact_id": fid,
            "canonical_phrase": f"bounded empirical finding {fid}",
            "population": population,
            "intervention": f"agent{fid}",
            "comparator": f"control{fid}",
            "endpoint": f"marker{fid}",
            "source_paper": {
                "doi": f"10.1234/{fid}",
                "title": f"Empirical therapy trial {fid}",
                "year": 2024,
            },
        })
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return run


def test_build_queue_demotes_scope_mismatched_evidence_maps(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    _stored_evidence_map_run(
        runs,
        "broad_map-evidence-2026-02-01T00-00-00Z",
        shared_axis=None,
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert out["ready_to_publish"] == []
    assert [r["topic"] for r in out["curation_needed"]] == ["broad_map"]
    assert out["curation_needed"][0]["queue_status"] == "evidence_map_scope_mismatch"
    assert "evidence_map_scope_mismatch" in out["curation_needed"][0]["blockers"]


def test_build_queue_keeps_bounded_evidence_maps_ready(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    _stored_evidence_map_run(
        runs,
        "bounded_map-evidence-2026-02-01T00-00-00Z",
        shared_axis="older adults",
    )
    monkeypatch.setattr(queue, "_RUNS", runs)

    out = queue.build_queue(include_archive=True)

    assert [r["topic"] for r in out["ready_to_publish"]] == ["bounded_map"]
    assert out["curation_needed"] == []
