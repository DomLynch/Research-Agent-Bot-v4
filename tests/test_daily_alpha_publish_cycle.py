"""Daily alpha publish cycle tests.

Fixtures are domain-neutral; the orchestrator must not know topic-specific
rules.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NoReturn
from urllib.request import Request

from pytest import MonkeyPatch, raises

import scripts.daily_alpha_publish_cycle as daily
from agent.topic_discovery import cap_topic_slug
from scripts import alpha_publish_decisions as publish_decisions
from scripts import alpha_publish_literature as publish_literature
from scripts import alpha_publish_public as publish_public


def test_daily_alpha_publish_cycle_can_run_as_file() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/daily_alpha_publish_cycle.py", "--help"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--allow-tier2-repair" in result.stdout


def test_run_subprocess_timeout_kills_descendant_process(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-marker"
    grandchild = tmp_path / "grandchild.py"
    child = tmp_path / "child.py"
    grandchild.write_text(
        "import pathlib, sys, time\n"
        "time.sleep(2)\n"
        "pathlib.Path(sys.argv[1]).write_text('orphan', encoding='utf-8')\n",
        encoding="utf-8",
    )
    child.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(grandchild)!r}, {str(marker)!r}])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    try:
        daily._run_subprocess([sys.executable, str(child)], timeout=1)
    except subprocess.TimeoutExpired:
        pass
    else:  # pragma: no cover - defensive: the child should never finish.
        raise AssertionError("child unexpectedly completed")

    time.sleep(2.5)
    assert not marker.exists()


def _verdict(topic: str = "grid_storage", *, score: int = 90) -> dict[str, Any]:
    source_papers = [
        {"doi": f"10.1000/{i}", "title": f"Reserve threshold paper {i}"}
        for i in range(12)
    ]
    return {
        "run_dir": f"runs/{topic}-evidence-ts",
        "topic": topic,
        "decision": "ready_to_publish",
        "publish_tier": "TIER_1",
        "maturity_level": "L5",
        "headline": "Storage reserves flip after threshold pricing",
        "confidence_label": "evidence_backed_signal",
        "alpha_score": score,
        "surface_type": "publish_alpha_memo",
        "domain": {"slug": "longevity"},
        "axes": {
            "available_source_contexts": 12,
            "source_papers": source_papers,
        },
        "receipt_expansion": {
            "cited_bound_fact_ids": ["3", "1", "2"],
        },
    }


def _queue(*verdicts: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "ready_to_publish": list(verdicts),
        "needs_operator_review": [],
        "curation_needed": [],
    }


# Every rendered memo carries a "What would weaken this" section; the submit
# falsifier gate (memo_missing_falsifier) requires it, so fixtures include it.
_FALSIFIER = (
    "\n## What would weaken this\n\n"
    "- Independent receipts fail to reproduce the claimed contrast.\n"
)


def _memo(root: Path, verdict: dict[str, Any]) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    (run / "alpha_memo.md").write_text("# Alpha memo\n" + _FALSIFIER, encoding="utf-8")
    _audit_sidecars(run)


def _audit_sidecars(run: Path) -> None:
    run.joinpath("claim_receipt_matrix.json").write_text(
        json.dumps({"direct_sources": 5}), encoding="utf-8")
    run.joinpath("typed_counter_evidence.json").write_text(
        json.dumps({"items": []}), encoding="utf-8")
    run.joinpath("novelty_delta.json").write_text(
        json.dumps({"novelty_delta": {"label": "contradictory"}}), encoding="utf-8")
    run.joinpath("memo_audit.json").write_text(
        json.dumps({"verdict": "supported"}), encoding="utf-8")


def _memo_with_source_receipts(root: Path, verdict: dict[str, Any], count: int) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(count)]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": "Matched endpoint improved in the target population.",
            "population": "target population",
            "intervention": "matched intervention",
            "endpoint": "matched endpoint",
            "source_paper": {
                "doi": f"10.1000/memo-{fid}",
                "title": f"Memo source {fid}",
            },
        }
        for fid in ids
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in ids],
    }), encoding="utf-8")
    _audit_sidecars(run)


def _stored_map_run(
    root: Path,
    topic: str,
    *,
    shared_population: str | None,
    surface_type: str = "evidence_map",
    confidence_label: str = "evidence_map",
) -> dict[str, Any]:
    run = root / "runs" / f"{topic}-evidence-ts"
    run.mkdir(parents=True)
    fact_ids = [str(i) for i in range(1, 11)]
    verdict = _verdict(topic) | {
        "run_dir": str(run),
        "surface_type": surface_type,
        "confidence_label": confidence_label,
    }
    run.joinpath("publish_verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in fact_ids],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": f"bounded empirical finding {fid}",
            "population": shared_population or f"group{fid}",
            "intervention": f"agent{fid}",
            "comparator": f"control{fid}",
            "endpoint": f"marker{fid}",
            "source_paper": {
                "doi": f"10.1000/map-{fid}",
                "title": f"Empirical therapy source {fid}",
            },
        }
        for fid in fact_ids
    ]), encoding="utf-8")
    return verdict


def test_daily_build_queue_demotes_submit_held_evidence_maps(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _stored_map_run(root, "broad_map", shared_population=None)
    _stored_map_run(root, "bounded_map", shared_population="older adults")

    queue = daily._build_queue(root / "runs", include_archive=False)

    assert [r["topic"] for r in queue["ready_to_publish"]] == ["bounded_map"]
    assert [r["topic"] for r in queue["curation_needed"]] == ["broad_map"]
    assert queue["curation_needed"][0]["queue_status"] == "evidence_map_scope_mismatch"


def test_queue_ready_row_demotes_zero_alpha_ready_row(tmp_path: Path) -> None:
    row = daily._queue_ready_row(_verdict("zero_alpha", score=0), tmp_path)

    assert row["decision"] == "curation_needed"
    assert row["queue_status"] == "low_alpha_score"
    assert row["blockers"] == ["low_alpha_score"]


def test_daily_build_queue_demotes_submitted_duplicate_ready_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _stored_map_run(root, "bounded_map", shared_population="older adults")
    submitted_path = root / "runs" / "_daily_ledger" / "_submitted_fingerprints.json"
    daily._write_json(submitted_path, [{
        "domain": {"slug": "longevity"},
        "topic": "bounded_map",
        "fingerprint": daily.memo_fingerprint(verdict),
    }])

    queue = daily._build_queue(
        root / "runs",
        include_archive=False,
        domain="longevity",
        submitted_path=submitted_path,
    )

    assert queue["ready_to_publish"] == []
    assert [row["topic"] for row in queue["curation_needed"]] == ["bounded_map"]
    assert queue["curation_needed"][0]["queue_status"] == "duplicate_submission_fingerprint"
    assert queue["curation_needed"][0]["blockers"] == ["duplicate_submission_fingerprint"]


def test_daily_build_queue_demotes_evidence_map_label_even_with_alpha_surface(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _stored_map_run(
        root,
        "mislabelled_map",
        shared_population="older adults",
        surface_type="publish_alpha_memo",
        confidence_label="evidence_map",
    )
    run = root / str(verdict["run_dir"])
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    (run / "all_facts.json").write_text(json.dumps(facts[:5]), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": str(i), "lane": "A_core"} for i in range(1, 6)],
    }), encoding="utf-8")

    queue = daily._build_queue(root / "runs", include_archive=False)

    assert queue["ready_to_publish"] == []
    assert [row["topic"] for row in queue["curation_needed"]] == ["mislabelled_map"]
    assert queue["curation_needed"][0]["queue_status"] == (
        "evidence_map_below_citation_floor"
    )


def test_daily_build_queue_uses_stored_non_ready_verdict_without_recomputing(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("fast_probe") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_3",
        "blockers": ["source_floor_below_min"],
    }
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("opportunities_gate.json").write_text("{}", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps(verdict), encoding="utf-8")

    def fail_recompute(_run: Path) -> dict[str, Any]:
        raise AssertionError("queue probe should not recompute stored verdicts")

    monkeypatch.setattr(daily, "publish_verdict", fail_recompute)

    queue = daily._build_queue(root / "runs", include_archive=False)

    assert [row["topic"] for row in queue["curation_needed"]] == ["fast_probe"]


def test_daily_build_queue_revalidates_stale_ready_rows(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    ready = _verdict("stale_ready")
    current = ready | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["fact_shape_mismatch"],
    }
    _memo_with_source_receipts(root, ready, 5)
    run = root / str(ready["run_dir"])
    run.joinpath("opportunities_gate.json").write_text("{}", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps(ready), encoding="utf-8")

    monkeypatch.setattr(daily, "_verdict_for_run", lambda _run: current)

    queue = daily._build_queue(root / "runs", include_archive=False)

    assert queue["ready_to_publish"] == []
    assert [row["topic"] for row in queue["agent_repair_needed"]] == ["stale_ready"]
    assert queue["agent_repair_needed"][0]["blockers"] == ["fact_shape_mismatch"]


def test_daily_build_queue_skips_wrong_domain_before_recomputing_repair(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("RAG") | {
        "decision": "agent_repair_needed",
        "domain": {"slug": "ai_research"},
        "blockers": ["fact_shape_mismatch"],
    }
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("opportunities_gate.json").write_text("{}", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps(verdict), encoding="utf-8")

    def fail_recompute(_run: Path) -> dict[str, Any]:
        raise AssertionError("wrong-domain repair rows must not be recomputed")

    monkeypatch.setattr(daily, "publish_verdict", fail_recompute)

    queue = daily._build_queue(
        root / "runs", include_archive=False, domain="longevity_research",
    )

    assert queue["ready_to_publish"] == []
    assert queue["agent_repair_needed"] == []
    assert queue["curation_needed"] == []


def _memo_with_receipt_shapes(
    root: Path, verdict: dict[str, Any], shapes: list[dict[str, str]],
) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(len(shapes))]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            **shape,
            "source_paper": {
                "doi": f"10.1000/shape-{fid}",
                "title": f"Shape source {fid}",
            },
        }
        for fid, shape in zip(ids, shapes, strict=True)
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in ids],
    }), encoding="utf-8")
    _audit_sidecars(run)


def _publish_tier_run(root: Path, topic: str, *, stale: dict[str, Any]) -> None:
    run = root / "runs" / f"{topic}-evidence-ts"
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(5)]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage dispatch changes reserve reliability\n"
        "**Alpha score:** 80/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## Why this is surprising\n\nExpected result without a clear contrast.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n" + _FALSIFIER,
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
            {"fact_id": fid, "lane": "A_core"}
            for fid in [*ids, "6"]
        ],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": (
                "Grid storage dispatch improved reserve reliability "
                "after threshold changes."
            ),
            "source_paper": {
                "doi": f"10.1000/{fid}",
                "title": f"Reserve reliability dispatch paper {fid}",
                "journal": "Grid Systems",
                "year": 2026,
            },
        }
        for fid in ids
    ] + [{
        "fact_id": "6",
        "canonical_phrase": "Grid storage dispatch did not improve reserve reliability.",
        "source_paper": {
            "doi": "10.1000/counter",
            "title": "Reserve reliability counter-audit",
            "journal": "Grid Systems",
            "year": 2026,
        },
    }]), encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps(stale), encoding="utf-8")
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "longevity"},
    }), encoding="utf-8")
    _audit_sidecars(run)


def test_memo_fingerprint_is_stable_across_headline_rewording() -> None:
    left = _verdict()
    right = _verdict() | {"headline": "Reworded public headline"}

    assert daily.memo_fingerprint(left) == daily.memo_fingerprint(right)


def test_memo_fingerprint_and_source_count_use_full_source_identity() -> None:
    left = _verdict()
    right = _verdict()
    papers = [
        {"pmcid": "PMC1", "title": "Same title"},
        {"paper_id": "P2", "title": "Same title"},
        {"id": "I3", "title": "Same title"},
    ]
    left["axes"]["source_papers"] = papers
    right["axes"]["source_papers"] = [*papers[:2], papers[2] | {"id": "I9"}]

    assert daily.memo_fingerprint(left) != daily.memo_fingerprint(right)
    assert daily._source_count_from_verdict(left) == 3


def test_memo_fingerprint_is_domain_scoped() -> None:
    left = _verdict()
    right = _verdict() | {"domain": {"slug": "ai_research"}}

    assert daily.memo_fingerprint(left) != daily.memo_fingerprint(right)


def test_daily_queue_skips_runs_without_domain_metadata(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run = runs / "untagged-evidence-ts"
    run.mkdir(parents=True)
    verdict = _verdict("untagged")
    verdict.pop("domain")
    run.joinpath("alpha_memo.md").write_text("# Alpha memo\n", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(verdict), encoding="utf-8",
    )

    out = daily._build_queue(
        runs, include_archive=False, domain="longevity_research",
    )

    assert out["ready_to_publish"] == []
    assert out["_meta"]["missing_domain_count"] == 1


def test_daily_queue_claims_untagged_run_in_domain_seed_corpus(tmp_path: Path) -> None:
    # An untagged (pre-domain-metadata) run whose topic IS in the target domain's
    # seed corpus must be claimed for that domain, not dropped — this is the
    # universal seed-membership rescue that revives the legacy untagged backlog.
    runs = tmp_path / "runs"
    run = runs / "metformin-evidence-ts"
    run.mkdir(parents=True)
    verdict = _verdict("metformin")
    verdict.pop("domain")
    run.joinpath("alpha_memo.md").write_text("# Alpha memo\n", encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(verdict), encoding="utf-8",
    )

    out = daily._build_queue(
        runs, include_archive=False, domain="longevity_research",
    )

    assert out["_meta"]["missing_domain_count"] == 0
    assert out["_meta"]["untagged_seed_claimed_count"] == 1
    assert [r["topic"] for r in out["ready_to_publish"]] == ["metformin"]
    assert out["ready_to_publish"][0]["domain_slug"] == "longevity_research"


def test_run_cycle_rejects_injected_candidate_without_domain(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("untagged")
    verdict.pop("domain")
    _memo(root, verdict)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06",
        queue=_queue(verdict),
        retraction_mode="metadata",
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["considered"][0]["status"] == "missing_domain_metadata"


def test_ledger_stamp_includes_utc_time_for_twice_daily_runs() -> None:
    stamp = daily._ledger_stamp(dt.datetime(2026, 5, 26, 17, 30, 1, tzinfo=dt.UTC))

    assert stamp == "2026-05-26T17-30-01Z"


def test_dry_run_selects_best_candidate_and_writes_ledger(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    weak = _verdict("weak", score=80)
    strong = _verdict("strong", score=99)
    _memo(root, strong)

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-05-22",
        queue=_queue(weak, strong),
        retraction_mode="metadata",
    )

    assert ledger["status"] == "dry_run_selected"
    assert ledger["candidate"]["topic"] == "strong"
    written = json.loads(
        (root / "runs" / "_daily_ledger" / "2026-05-22.json").read_text(
            encoding="utf-8",
        )
    )
    assert written["published"] == 0
    assert written["queue_counts"]["ready_to_publish"] == 2


def test_run_cycle_persists_started_ledger_before_queue_build(tmp_path: Path) -> None:
    root = tmp_path / "repo"

    def fail_queue_builder(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("queue build stalled")

    with raises(RuntimeError, match="queue build stalled"):
        daily.run_cycle(
            runs_root=root / "runs",
            date="2026-05-22T01-30-01Z",
            queue_builder=fail_queue_builder,
            retraction_mode="metadata",
        )

    written = json.loads(
        (root / "runs" / "_daily_ledger" / "2026-05-22T01-30-01Z.json").read_text(
            encoding="utf-8",
        )
    )
    assert written["status"] == "started"
    assert written["publish_summary"]["status"] == "started"
    assert written["publish_summary"]["next_action"] == "building_current_publish_queue"


def test_refresh_cycle_marks_initial_queue_probe_before_queue_build(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"

    def fail_build_queue(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("queue probe stalled")

    monkeypatch.setattr(daily, "_build_queue", fail_build_queue)

    with raises(RuntimeError, match="queue probe stalled"):
        daily.run_cycle(
            runs_root=root / "runs",
            date="2026-05-22T01-30-01Z",
            refresh_candidates=True,
            queue_builder=daily._build_queue,
            retraction_mode="metadata",
        )

    written = json.loads(
        (root / "runs" / "_daily_ledger" / "2026-05-22T01-30-01Z.json").read_text(
            encoding="utf-8",
        )
    )
    assert written["status"] == "started"
    assert written["stage"] == "initial_queue_probe"
    assert written["next_action"] == "building_current_publish_queue"
    assert written["publish_summary"]["next_action"] == "building_current_publish_queue"


def test_refresh_cycle_probes_existing_ready_queue_before_discovery(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("ready")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(verdict), encoding="utf-8",
    )

    def fail_refresh(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("discovery refresh should not run before ready queue")

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fail_refresh)

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-05-22",
        refresh_candidates=True,
        retraction_mode="metadata",
    )

    assert ledger["status"] == "dry_run_selected"
    assert ledger["candidate"]["topic"] == "ready"
    assert ledger["refresh_batches"][0]["note"] == "skipped_initial_queue_probe"


def test_refresh_cycle_probes_claim_cluster_queue_before_discovery(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("curated_parent") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_3",
        "alpha_score": 100,
        "blockers": ["feed_scope_mismatch"],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "bounded claim",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(verdict), encoding="utf-8",
    )

    def fail_refresh(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("discovery refresh should not run before claim cluster")

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        assert refresh_verdict["_claim_cluster_candidate"] is True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        _audit_sidecars(run_dir)
        return True

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fail_refresh)
    monkeypatch.setattr(
        daily, "retraction_check",
        lambda *_args, **_kwargs: {"status": "clean", "checked_dois": [], "retracted": []},
    )

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-05-22",
        refresh_candidates=True,
        allow_tier2=True,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        decision_poll_attempts=0,
        memo_refresher=refresh,
    )

    assert ledger["submitted"] == 1
    assert ledger["submitted_topic"] == "curated_parent_bounded_claim"
    assert ledger["refresh_batches"][0]["note"] == "skipped_initial_queue_probe"


def test_refresh_cycle_recomputes_stale_verdict_before_discovery(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _publish_tier_run(root, "grid_storage", stale={
        "topic": "grid_storage",
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "alpha_score": 80,
        "blockers": ["weak_counter_consensus_tension"],
    })

    def fail_refresh(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("discovery refresh should not hide recomputed ready queue")

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fail_refresh)

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-05-22",
        refresh_candidates=True,
        retraction_mode="metadata",
    )

    assert ledger["status"] == "dry_run_selected"
    assert ledger["candidate"]["topic"] == "grid_storage"
    assert ledger["refresh_batches"][0]["note"] == "skipped_initial_queue_probe"


def test_write_publish_verdict_refreshes_stale_lane_sidecar_for_new_aliases(
    tmp_path: Path,
) -> None:
    run = tmp_path / "runs" / "exercise-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text("# Alpha memo\n" + _FALSIFIER, encoding="utf-8")
    run.joinpath("opportunities_gate.json").write_text(json.dumps({
        "audits": [{"status": "survives", "cited_fact_ids": ["1"]}],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([{
        "fact_id": "1",
        "canonical_phrase": "VO2 peak increased by 10.6% after resistance training",
        "population": "older adults",
        "intervention": "dynamic resistance training",
        "comparator": "usual care",
        "numeric_value": 10.6,
        "units": "%",
        "source_paper": {"doi": "10.1000/exercise", "title": "Exercise source"},
    }]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": "1", "lane": "C_noise"}],
    }), encoding="utf-8")
    run.joinpath("claim_cluster.json").write_text(
        json.dumps({"lead_fact_ids": [], "homogeneous": True}), encoding="utf-8",
    )
    _audit_sidecars(run)

    daily._write_publish_verdict(run)

    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    assert lanes["verdicts"][0]["lane"] == "A_core"


def test_weak_tension_candidate_enriches_before_rotation(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("weak_tension") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "blockers": ["weak_counter_consensus_tension"],
    }
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(5)]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## Why this is surprising\n\n"
        "Expected result without a clear contrast.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": (
                "Storage reserve reliability improves after threshold pricing."
            ),
            "population": "grid storage reserve markets",
            "intervention": "threshold pricing",
            "source_paper": {
                "doi": f"10.1000/weak-{fid}",
                "title": f"Storage reserve threshold paper {fid}",
                "journal": "Energy Systems",
            },
        }
        for fid in ids
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in ids],
    }), encoding="utf-8")

    def enrich(run_dir: Path, candidate: dict[str, Any]) -> bool:
        assert candidate["blockers"] == ["weak_counter_consensus_tension"]
        memo_path = run_dir / "alpha_memo.md"
        memo_path.write_text(
            memo_path.read_text(encoding="utf-8").replace(
                "Expected result without a clear contrast.",
                "Real tension: reliability improves while reserve pricing "
                "thresholds narrow where the result should generalize.",
            ),
            encoding="utf-8",
        )
        _audit_sidecars(run_dir)
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue={
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}},
        },
        memo_refresher=enrich,
    )

    refreshed = json.loads((run / "publish_verdict.json").read_text(encoding="utf-8"))
    assert refreshed["decision"] == "ready_to_publish"
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "weak_tension"
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["considered"][0]["status"] == "eligible"


def test_duplicate_fingerprint_skips_previous_submission(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    first = _verdict("first")
    second = _verdict("second") | {"receipt_expansion": {"cited_bound_fact_ids": ["9"]}}
    _memo(root, second)
    fp = daily.memo_fingerprint(first)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "first"},
    ])

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(first, second),
        retraction_mode="metadata",
    )

    assert ledger["status"] == "dry_run_selected"
    assert ledger["candidate"]["topic"] == "second"
    assert ledger["considered"][0]["status"] == "duplicate_submission_fingerprint"


def test_duplicate_underexpanded_memo_refreshes_before_reporting(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("already_seen") | {
        "axes": {
            "source_papers": [{"doi": "10.1000/old", "title": "Old lead"}],
        },
    }
    _memo_with_source_receipts(root, verdict, 1)
    run = root / str(verdict["run_dir"])
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    facts.extend({
        "fact_id": str(i + 1),
        "source_paper": {
            "doi": f"10.1000/unused-{i}",
            "title": f"Unused source {i}",
        },
    } for i in range(1, 5))
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": str(i + 1), "lane": "A_core"} for i in range(5)],
    }), encoding="utf-8")
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "already_seen"},
    ])

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n## Evidence receipts\n\n"
            + "\n".join(
                f"- `fact_id={i + 1}` (`A_core`) - receipt" for i in range(5)
            )
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="metadata",
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        memo_refresher=refresh,
    )

    row = ledger["considered"][0]
    assert ledger["status"] == "no_fresh_candidate"
    assert row["status"] == "duplicate_submission_fingerprint"
    assert row["memo_refreshed"] is True
    assert row["source_count"] == 5
    assert row["corpus_ab_paper_count"] == 5


def test_sync_backfills_decision_for_submitted_fingerprint_only_record(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("repairable")
    _memo(root, verdict)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-05-22T00-00-00Z",
        "topic": "repairable",
        "run_dir": verdict["run_dir"],
        "fingerprint": fp,
        "submission_id": "sub-1",
    }])

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _sid: {
            "status": "complete",
            "decision": "reject",
            "required_revisions": ["A complete scope reset is required."],
            "resubmission": {"allowed": True},
        },
        page_fetcher=lambda _url: {"ok": False, "status": 0},
    )

    assert summary["updated"] == 1
    ledgers = list((root / "_daily_ledger").glob("*decision-sub-1.json"))
    assert len(ledgers) == 1
    submitted = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert submitted[0]["status"] == "reviewer_rejected"
    assert submitted[0]["final_verdict"] == "rejected"
    assert fp in daily._repairable_rejected_fingerprints(root / "_daily_ledger")


def test_default_memo_refresher_never_mutates_archive(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "_archive" / "cycle" / "topic-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")

    assert daily._refresh_alpha_memo(run, {}) is False


def test_revision_refresher_edits_existing_memo_without_scratch_rewrite(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "metformin-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo — metformin\n\n"
        "**Headline:** Stage-Specific Efficacy: A Systematic Review of Survival Outcomes\n\n"
        "## One-sentence thesis\n\n"
        "The direct receipt reports one disease-specific signal.\n\n"
        "## Why this is surprising\n\n"
        "The context differs.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n\n"
        "- **Suggested citation:** Dom Lynch. (2026). Stage-Specific Efficacy: "
        "A Systematic Review of Survival Outcomes. ReseaRka Evidence Index.\n",
        encoding="utf-8",
    )

    changed = daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "decision": "revise",
            "required_revisions": [
                "Revise the title to remove 'systematic review'.",
                "Clarify that findings derive from a single primary study with contextual support.",
            ],
        },
    })

    memo = run.joinpath("alpha_memo.md").read_text(encoding="utf-8")
    assert changed is True
    assert "**Headline:** Stage-Specific Efficacy" in memo
    assert "**Headline:** Stage-Specific Efficacy:" not in memo
    assert "Systematic Review" not in memo
    assert "Scope clarification" in memo
    assert "## Evidence receipts" in memo
    assert "`fact_id=1`" in memo


def test_repairable_reject_refresher_can_patch_existing_memo(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "topic-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "**Headline:** Claim: A Meta-analysis of Effects\n\n"
        "## Why this is surprising\n\nBody.\n",
        encoding="utf-8",
    )

    changed = daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "decision": "reject",
            "review_summary": "Title should not claim meta-analysis.",
        },
    })

    assert changed is True
    assert "Meta-analysis" not in run.joinpath("alpha_memo.md").read_text(encoding="utf-8")


def test_repairable_reject_refresher_removes_meta_regression_title(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "topic-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "**Headline:** Claim: A Meta-regression of diagnostic criteria\n\n"
        "- **Suggested citation:** Claim: A meta regression of diagnostic criteria.\n\n"
        "## Why this is surprising\n\nBody.\n",
        encoding="utf-8",
    )

    changed = daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "decision": "reject",
            "review_summary": "Title should not claim meta-regression.",
        },
    })

    memo = run.joinpath("alpha_memo.md").read_text(encoding="utf-8")
    assert changed is True
    assert "Meta-regression" not in memo
    assert "meta regression" not in memo
    assert "**Headline:** Claim" in memo


def test_repairable_reject_refresher_softens_gate_reported_novelty(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "topic-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "**Headline:** A novel approach for metformin response\n\n"
        "## One-sentence thesis\n\n"
        "This is a groundbreaking signal and first to demonstrate the contrast.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n",
        encoding="utf-8",
    )

    changed = daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "decision": "reject",
            "gate_failures": [
                {"name": "unsupported_novelty", "reason": "Unsupported novelty language."},
            ],
        },
    })

    memo = run.joinpath("alpha_memo.md").read_text(encoding="utf-8")
    assert changed is True
    assert "novel approach" not in memo.lower()
    assert "groundbreaking" not in memo.lower()
    assert "first to demonstrate" not in memo.lower()
    assert "`fact_id=1`" in memo


def test_revision_refresher_materially_narrows_reviewer_revise_notes(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "glp-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "## One-sentence thesis\n\n"
        "The broad context settles the signal.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the effect is broader than expected.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n",
        encoding="utf-8",
    )

    changed = daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "decision": "revise",
            "required_revisions": [
                "Clarify the bounded research signal by separating the direct "
                "claim from broader context.",
                "Explicitly state the claim is hypothesis-generating.",
                "Ensure the surprising section does not overstate tension or novelty.",
            ],
        },
    })

    memo = run.joinpath("alpha_memo.md").read_text(encoding="utf-8")
    assert changed is True
    assert "Reviewer revision" in memo
    assert "hypothesis-generating" in memo
    assert "Real tension:" not in memo
    assert "Bounded signal:" in memo
    assert "`fact_id=1`" in memo


def test_reviewer_text_repair_regenerates_sidecars_and_verdict(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    run = tmp_path / "runs" / "topic-evidence-ts"
    run.mkdir(parents=True)
    for name in ("signal_post.md", "alpha_memo.md", "opportunities_gate.json",
                 "fact_lanes.json", "all_facts.json"):
        run.joinpath(name).write_text("{}" if name.endswith(".json") else "# Signal\n",
                                      encoding="utf-8")
    import agent.signal_memo_writer as smw

    called: dict[str, bool] = {}

    def _fake_write(run_dir: Path, signal_text: Any = None,
                    publish_verdict: Any = None, *, grounded: bool = False) -> Any:
        called["memo"] = True
        run_dir.joinpath("memo_audit.json").write_text("{}", encoding="utf-8")
        return run_dir / "alpha_memo.md", "# regenerated\n"

    def _fake_verdict(run_dir: Path) -> dict[str, Any]:
        called["verdict"] = True
        run_dir.joinpath("publish_verdict.json").write_text("{}", encoding="utf-8")
        return {}

    monkeypatch.setattr(smw, "write_signal_memo", _fake_write)
    monkeypatch.setattr(daily, "_write_publish_verdict", _fake_verdict)
    assert daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "decision": "revise",
            "required_revisions": ["Revise the title to remove 'systematic review'."],
        },
    }) is True

    assert called == {"memo": True, "verdict": True}
    assert run.joinpath("memo_audit.json").exists()
    assert run.joinpath("publish_verdict.json").exists()


def test_repairable_reject_refresher_handles_scope_reset_notes(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "glp-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Weight regain and lean mass dynamics\n\n"
        "## Why this is surprising\n\n"
        "The evidence is narrower.\n",
        encoding="utf-8",
    )

    changed = daily._refresh_alpha_memo(run, {
        "_repair_decision": {
            "status": "complete",
            "decision": "reject",
            "required_revisions": [
                "A complete scope reset is required. The memo must reconcile its "
                "title/abstract topic with the evidence actually presented.",
                "Supporting claims must be directly and verifiably grounded in "
                "the provided source bundle and cited DOIs.",
            ],
        },
    })

    memo = run.joinpath("alpha_memo.md").read_text(encoding="utf-8")
    assert changed is True
    # A scope reset rebuilds the memo around the grounded source angle on the
    # FIRST repair pass; it must not short-circuit to a cosmetic clarification.
    assert "**Selected angle:** `source`" in memo
    assert "Scope clarification" not in memo


def test_scope_reject_repair_regenerates_in_grounded_mode(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    scope_reject = {
        "decision": "reject",
        "required_revisions": [
            "A complete scope reset is required.",
            "Claims must be verifiably grounded in the provided source bundle.",
        ],
    }
    assert daily._is_grounding_reject(scope_reject) is True
    assert daily._is_grounding_reject(
        {"decision": "reject", "review_summary": "Tone too casual."}) is False

    # Cosmetic repair is a no-op here (the scope note is already present), so the
    # memo must be regenerated in grounded mode rather than left byte-identical.
    run = tmp_path / "runs" / "glp-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n**Headline:** Bounded signal\n\n"
        "## One-sentence thesis\n\nNarrow claim.\n\n"
        "**Scope clarification:** The lead claim should be read as a narrow "
        "direct-source signal. Other cited sources provide context and boundary "
        "checks, not independent confirmation of the lead claim.\n\n"
        "## Why this is surprising\n\nBody.\n",
        encoding="utf-8",
    )
    captured: dict[str, Any] = {}
    import agent.signal_memo_writer as smw

    def _fake(run_dir: Path, signal_text: Any = None,
              publish_verdict: Any = None, *, grounded: bool = False) -> Any:
        captured["grounded"] = grounded
        return run_dir / "alpha_memo.md", ""

    monkeypatch.setattr(smw, "write_signal_memo", _fake)
    changed = daily._refresh_alpha_memo(run, {"_repair_decision": scope_reject})
    assert changed is True
    assert captured["grounded"] is True


def test_low_grounding_score_reviewer_repair_forces_grounded_regen() -> None:
    decision = {
        "decision": "reject",
        "resubmission": {"allowed": True},
        "rubric_scores": {
            "claim_evidence_alignment": 2,
            "source_grounding": 3,
            "synthesis_quality": 3,
        },
    }

    assert daily._is_grounding_reject(decision) is True


def test_low_grounding_score_without_resubmission_does_not_force_regen() -> None:
    decision = {
        "decision": "reject",
        "resubmission": {"allowed": False},
        "rubric_scores": {
            "claim_evidence_alignment": 2,
            "source_grounding": 2,
            "synthesis_quality": 2,
        },
    }

    assert daily._is_grounding_reject(decision) is False


def test_resubmission_allowed_claim_alignment_reject_is_repairable() -> None:
    decision = {
        "decision": "reject",
        "major_issues": [
            "The claim_evidence_alignment is critically low.",
            "The strongest counter-evidence is irrelevant counter-evidence.",
        ],
        "required_revisions": [
            "Define a single, specific, and bounded research question.",
            "Restructure the evidence presentation around the cited bundle.",
            "Ensure the one-sentence thesis is directly supported.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True
    assert daily._is_grounding_reject(decision) is True


def test_explicit_resubmission_allowed_reject_is_repairable() -> None:
    decision = {
        "decision": "reject",
        "major_issues": ["The title overstates what the receipts prove."],
        "required_revisions": ["Rewrite the thesis around the cited receipts."],
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True


def test_tighten_evidence_receipts_revision_forces_grounded_regen() -> None:
    decision = {
        "decision": "revise",
        "required_revisions": [
            "Tighten the evidence receipts to those directly related to the thesis.",
            "State that the lead claim rests on a single systematic review.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._is_grounding_reject(decision) is True


def test_partially_supported_major_revision_with_resubmission_allowed_is_retried() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "revise",
        "major_issues": [
            "The core claim compares different populations and endpoints.",
        ],
        "required_revisions": [
            "Distinguish the biomarker from the intervention practice.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True


def test_partially_supported_revision_without_resubmission_allowed_is_not_retried() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "revise",
        "required_revisions": ["Clarify the exact supported claim."],
        "resubmission": {"allowed": False},
    }

    assert daily._repairable_rejection(decision) is False


def test_partially_supported_reject_with_explicit_resubmission_is_retried() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "reject",
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True


def test_partially_supported_reject_with_resubmission_instructions_is_retried() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "reject",
        "major_issues": [
            "The memo bundles unrelated statistics without a bounded claim.",
        ],
        "required_revisions": [
            "Define one bounded claim and integrate or remove unused receipts.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True


def test_unsupported_reject_with_resubmission_allowed_is_retried() -> None:
    decision = {
        "claim_support_verdict": "unsupported",
        "decision": "reject",
        "major_issues": ["The cited receipts do not support the thesis."],
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True


def test_unsupported_low_grounding_reject_is_not_retried() -> None:
    decision = {
        "claim_support_verdict": "unsupported",
        "decision": "reject",
        "resubmission": {"allowed": True},
        "rubric_scores": {
            "claim_evidence_alignment": 2,
            "source_grounding": 2,
            "synthesis_quality": 2,
        },
    }

    assert daily._repairable_rejection(decision) is False


def test_unsupported_scope_reset_reject_with_resubmission_allowed_is_retried() -> None:
    decision = {
        "claim_support_verdict": "unsupported",
        "decision": "reject",
        "major_issues": [
            "Fundamental misalignment between the title/thesis and the provided evidence bundle.",
        ],
        "required_revisions": [
            "Complete scope reset: change the title and thesis to match the actual evidence provided.",
            "The thesis must be a single, bounded research signal.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._is_grounding_reject(decision) is True
    assert daily._repairable_rejection(decision) is True


def test_reviewer_reject_repair_budget_allows_one_boundary_repair() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "reject",
        "required_revisions": ["Complete scope reset: define one bounded claim."],
        "resubmission": {"allowed": True},
    }
    decisions = {"fp": decision}

    assert daily._retry_after_rejection(
        "fp", attempt_count=1, retryable={"fp"}, decisions=decisions,
    ) is True
    assert daily._retry_after_rejection(
        "fp", attempt_count=2, retryable={"fp"}, decisions=decisions,
    ) is True
    assert daily._retry_after_rejection(
        "fp", attempt_count=3, retryable={"fp"}, decisions=decisions,
    ) is False


def test_reviewer_revise_keeps_existing_repair_budget() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "revise",
        "required_revisions": ["Tighten the evidence receipts."],
        "resubmission": {"allowed": True},
    }
    decisions = {"fp": decision}

    assert daily._retry_after_rejection(
        "fp", attempt_count=3, retryable={"fp"}, decisions=decisions,
    ) is True
    assert daily._retry_after_rejection(
        "fp", attempt_count=4, retryable={"fp"}, decisions=decisions,
    ) is False


def test_supported_revision_stays_repairable() -> None:
    decision = {
        "claim_support_verdict": "supported",
        "decision": "revise",
        "minor_issues": ["Tighten the title to match the receipts."],
        "required_revisions": ["Tighten the title to match the receipts."],
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is True


def test_title_abstract_scope_revision_forces_grounded_regen() -> None:
    decision = {
        "decision": "revise",
        "required_revisions": [
            "Tighten the title and abstract to the actual scope of the cited evidence.",
            "State that the extra endpoint is a separate parallel signal or remove it.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._is_grounding_reject(decision) is True


def test_scope_mismatch_revision_forces_grounded_regen() -> None:
    decision = {
        "decision": "revise",
        "minor_issues": [
            "The title mentions a broad endpoint, but the core evidence bundle "
            "and thesis are focused more tightly, creating a scope mismatch.",
        ],
        "required_revisions": [
            "Either narrow the title and thesis to better reflect the primary "
            "focus, or expand the synthesis to integrate the extra endpoint.",
        ],
        "resubmission": {"allowed": True},
    }

    assert daily._is_grounding_reject(decision) is True


def test_resubmission_allowed_revision_forces_structural_rerender(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    decision = {
        "decision": "revise",
        "required_revisions": [
            "Use clearer language and make the memo's purpose explicit.",
        ],
        "resubmission": {"allowed": True},
    }
    assert daily._resubmission_allowed(decision) is True

    run = tmp_path / "runs" / "hbot-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "## One-sentence thesis\n\nOld thesis.\n\n"
        "## Why this is surprising\n\nOld vague collision.\n",
        encoding="utf-8",
    )
    captured: dict[str, Any] = {}
    import agent.signal_memo_writer as smw

    def _fake(run_dir: Path, signal_text: Any = None,
              publish_verdict: Any = None, *, grounded: bool = False) -> Any:
        captured["run_dir"] = run_dir
        captured["grounded"] = grounded
        return run_dir / "alpha_memo.md", ""

    monkeypatch.setattr(smw, "write_signal_memo", _fake)

    assert daily._refresh_alpha_memo(run, {"_repair_decision": decision}) is True
    assert captured == {"run_dir": run, "grounded": False}


def test_resubmission_alignment_reject_requires_explicit_allow() -> None:
    decision = {
        "decision": "reject",
        "major_issues": ["The claim_evidence_alignment is critically low."],
        "required_revisions": [
            "Define a single, specific, and bounded research question.",
            "Restructure the evidence presentation around the cited bundle.",
        ],
        "resubmission": {"allowed": "true"},
    }

    assert daily._repairable_rejection(decision) is False


def test_resubmission_allowed_alignment_reject_triggers_regeneration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("alignment_retry")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    old_sha = daily._memo_sha256(verdict, root)
    decision = {
        "decision": "reject",
        "major_issues": ["The claim_evidence_alignment is critically low."],
        "required_revisions": [
            "Define a single, specific, and bounded research question.",
            "Restructure the evidence presentation around the cited bundle.",
            "Ensure the thesis is directly supported.",
        ],
        "resubmission": {"allowed": True},
    }
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "alignment_retry",
            "run_dir": verdict["run_dir"],
            "submission_id": "old-sub",
            "memo_sha256": old_sha,
        },
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "reviewer_rejected",
        "final_verdict": "rejected",
        "candidate": {
            "fingerprint": fp,
            "topic": "alignment_retry",
            "run_dir": verdict["run_dir"],
        },
        "researka_decision": decision,
    })
    refreshed: dict[str, Any] = {}

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed["decision"] = refresh_verdict["_repair_decision"]
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nGrounded regenerated memo.\n",
            encoding="utf-8",
        )
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "new-sub"}},
        },
        memo_refresher=refresh,
    )

    assert refreshed["decision"] == decision
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["considered"][0]["status"] == "eligible"


def test_repaired_resubmission_payload_uses_recomputed_verdict(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    stale = _verdict("retry_reload") | {
        "headline": "Stale paradox headline",
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3"]},
    }
    _publish_tier_run(root, "retry_reload", stale=stale)
    fp = daily.memo_fingerprint(stale)
    old_sha = daily._memo_sha256(stale, root / "runs")
    decision = {
        "decision": "reject",
        "major_issues": ["The claim_evidence_alignment is critically low."],
        "required_revisions": ["Rewrite around the cited source bundle."],
        "resubmission": {"allowed": True},
    }
    daily._write_json(root / "runs" / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "retry_reload",
            "run_dir": stale["run_dir"],
            "submission_id": "old-sub",
            "memo_sha256": old_sha,
        },
    ])
    daily._write_json(root / "runs" / "_daily_ledger" / "2026-05-21.json", {
        "status": "reviewer_rejected",
        "final_verdict": "rejected",
        "candidate": {
            "fingerprint": fp,
            "topic": "retry_reload",
            "run_dir": stale["run_dir"],
        },
        "researka_decision": decision,
    })
    payloads: list[dict[str, Any]] = []

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        assert refresh_verdict["_repair_decision"] == decision
        memo = run_dir / "alpha_memo.md"
        memo.write_text(
            memo.read_text(encoding="utf-8") + "\nSource-bundle repair.\n",
            encoding="utf-8",
        )
        _audit_sidecars(run_dir)
        return True

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        payloads.append(payload)
        return {"ok": True, "status": 200, "response": {"submission": {"id": "new-sub"}}}

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-05-22",
        queue=_queue(stale),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_poll_attempts=0,
        memo_refresher=refresh,
    )

    verdict = payloads[0]["evidence_bundle"]["publish_verdict"]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert verdict["headline"] == "Storage dispatch changes reserve reliability"
    assert verdict["headline"] != stale["headline"]
    assert verdict["counter_evidence"]["status"] == "found"
    assert verdict["receipt_expansion"]["cited_bound_fact_ids"] == [
        "1", "2", "3", "4", "5",
    ]


def test_repairable_rejected_submission_can_retry_once(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("retryable")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "retryable", "submission_id": "old-sub"},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "rejected",
        "candidate": {"fingerprint": fp, "topic": "retryable"},
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "failure_category": "source_bundle_schema",
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "new-sub"}},
        },
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["considered"][0]["status"] == "eligible"
    assert ledger["considered"][0]["retry_after_rejection"] is True


def test_reject_with_required_revisions_can_retry(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("scope_retry")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "scope_retry", "submission_id": "old-sub"},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "rejected",
        "candidate": {"fingerprint": fp, "topic": "scope_retry"},
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "required_revisions": [
                "A complete scope reset is required.",
                "Claims must be verifiably grounded in cited DOIs.",
            ],
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "new-sub"}},
        },
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["retry_after_rejection"] is True


def test_repairable_retry_refreshes_even_when_source_floor_passes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("retry_refresh")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "retry_refresh", "submission_id": "old-sub"},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "retry_refresh"},
        "researka_decision": {
            "status": "complete",
            "decision": "revise",
            "required_revisions": ["make thesis declarative"],
        },
    })
    refreshed = {"called": False}

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        assert _verdict["_repair_decision"]["required_revisions"] == [
            "make thesis declarative",
        ]
        text = run_dir.joinpath("alpha_memo.md").read_text(encoding="utf-8")
        run_dir.joinpath("alpha_memo.md").write_text(
            text + "\nRevision marker.\n",
            encoding="utf-8",
        )
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["status"] == "submitted_to_researka"


def test_stale_memo_headline_refreshes_before_submission(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("stale_surface")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    receipts = "\n".join(
        f"- `fact_id={i}` (`A_core`) - receipt" for i in range(1, 6)
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n**Headline:** stale speculative title\n\n"
        "## Evidence receipts\n\n" + receipts + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    seen_payload: dict[str, Any] = {}
    refreshed = {"called": False}

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        assert refresh_verdict["_repair_decision"] is None
        run_dir.joinpath("alpha_memo.md").write_text(
            f"# Alpha memo\n\n**Headline:** {verdict['headline']}\n\n"
            "## Evidence receipts\n\n" + receipts + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda payload: seen_payload.update(payload) or {
            "ok": True,
            "status": 200,
            "response": {},
        },
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["status"] == "submitted_to_researka"
    assert seen_payload["title"] == verdict["headline"]


def test_repairable_cycle_attempt_enables_duplicate_retry(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("cycle_attempt_retry")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    old_sha = daily._memo_sha256(verdict, root)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "cycle_attempt_retry",
            "submission_id": "old-sub",
            "memo_sha256": old_sha,
        },
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submit_retry_exhausted",
        "final_verdict": "revise",
        "candidate": {"fingerprint": "other", "topic": "other"},
        "cycle_attempts": [{
            "fingerprint": fp,
            "topic": "cycle_attempt_retry",
            "run_dir": verdict["run_dir"],
            "status": "reviewer_rejected",
            "researka_decision": {
                "status": "complete",
                "decision": "reject",
                "required_revisions": ["Complete scope reset required."],
            },
        }],
    })

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        text = run_dir.joinpath("alpha_memo.md").read_text(encoding="utf-8")
        run_dir.joinpath("alpha_memo.md").write_text(
            text + "\nCycle attempt repair.\n", encoding="utf-8")
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        memo_refresher=refresh,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["retry_after_rejection"] is True
    assert ledger["considered"][0]["memo_refreshed"] is True


def test_reviewer_revise_refresh_changes_memo_sha_before_retry(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("bounded_retry")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    memo_path = run / "alpha_memo.md"
    memo_path.write_text(
        memo_path.read_text(encoding="utf-8").replace(
            "## Evidence receipts",
            "## Why this is surprising\n\n"
            "Real tension: broader context makes this settled.\n\n"
            "## Evidence receipts",
        ),
        encoding="utf-8",
    )
    fp = daily.memo_fingerprint(verdict)
    old_sha = daily._memo_sha256(verdict, root)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "bounded_retry",
            "submission_id": "old-sub",
            "memo_sha256": old_sha,
        },
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "bounded_retry"},
        "researka_decision": {
            "status": "complete",
            "decision": "revise",
            "required_revisions": [
                "Clarify the bounded research signal and state it is "
                "hypothesis-generating.",
                "Ensure the surprising section does not overstate tension or novelty.",
            ],
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["considered"][0]["status"] == "eligible"
    assert daily._memo_sha256(verdict, root) != old_sha


def test_revise_rewrite_unchanged_memo_is_not_resubmitted(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    # A repairable revise whose rewrite leaves the memo byte-identical must NOT
    # be resubmitted: the reviewer would return the same verdict and the
    # submission burns a reviewer cycle. The fingerprint can shift on reload
    # (receipt_expansion re-derivation) even when the rendered memo does not, so
    # the guard keys on memo_sha256 (content), not the fingerprint. This is the
    # exact prod no-op-rewrite case that resubmitted the identical RAG memo.
    root = tmp_path / "repo"
    verdict = _verdict("unchanged_rewrite")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("signal_post.md").write_text("# Signal\n", encoding="utf-8")
    fp = daily.memo_fingerprint(verdict)
    old_sha = daily._memo_sha256(verdict, root)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "unchanged_rewrite",
            "submission_id": "old-sub",
            "memo_sha256": old_sha,
        },
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "unchanged_rewrite"},
        "researka_decision": {
            "status": "complete",
            "decision": "revise",
            "resubmission": {"allowed": True},
            "required_revisions": [
                "Exclude the unrelated benchmark from the convergence claim.",
            ],
        },
    })
    submitted: list[str] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {"ok": True, "status": 200, "response": {}}

    def refresh(_run_dir: Path, _refresh_verdict: dict[str, Any]) -> bool:
        return True  # rewrite leaves alpha_memo.md untouched -> memo_sha stable

    def reload_with_shifted_fingerprint(
        refresh_verdict: dict[str, Any], _run_dir: Path,
    ) -> dict[str, Any]:
        # Reload re-derives receipts -> the fingerprint shifts, but the on-disk
        # memo is byte-identical (refresh above did not touch it).
        return dict(refresh_verdict, receipt_expansion={
            "cited_bound_fact_ids": ["9", "8", "7"],
        })

    monkeypatch.setattr(
        daily, "_reload_verdict_after_memo_refresh",
        reload_with_shifted_fingerprint,
    )

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        memo_refresher=refresh,
    )

    # Fingerprint shifted on reload, but memo content did not -> no resubmit.
    assert submitted == []
    assert ledger["status"] != "submitted_to_researka"
    assert any(
        row.get("status") == "duplicate_submission_fingerprint"
        for row in ledger.get("considered") or []
    )


def test_recently_published_topic_is_skipped_for_fresh_topic(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    published = _verdict("published", score=100)
    fresh = _verdict("fresh", score=90)
    _memo_with_source_receipts(root, published, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "published",
        "final_verdict": "accepted",
        "published": 1,
        "published_topic": "published",
        "candidate": {
            "topic": "published",
            "fingerprint": daily.memo_fingerprint(published),
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(published, fresh),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["submitted_topic"] == "fresh"
    assert ledger["recently_published_topics_blocked"] == ["published"]
    assert ledger["considered"][0]["topic"] == "published"
    assert ledger["considered"][0]["status"] == "cycle_exhausted_topic"


def test_recently_published_topic_is_domain_scoped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("shared_topic")
    _memo_with_source_receipts(root, verdict, 5)
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "published",
        "final_verdict": "accepted",
        "published": 1,
        "published_topic": "shared_topic",
        "domain": {"slug": "ai_research"},
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "shared_topic"
    assert ledger["recently_published_topics_blocked"] == []
    assert ledger["considered"][0]["status"] == "eligible"


def test_recently_published_topic_family_blocks_child_slug(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    published = _verdict("vector_search_agent_eval", score=100)
    child = _verdict("agent_eval_vector_rerank", score=99) | {
        "topic_family": published["topic"],
    }
    fresh = _verdict("workflow_automation_trace", score=90)
    _memo_with_source_receipts(root, child, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "published",
        "final_verdict": "accepted",
        "published": 1,
        "published_topic": published["topic"],
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(child, fresh),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "workflow_automation_trace"
    assert ledger["considered"][0]["topic"] == "agent_eval_vector_rerank"
    assert ledger["considered"][0]["status"] == "cycle_exhausted_topic"
    assert ledger["considered"][0]["family_blocked"] is True
    assert ledger["family_blocked_count"] == 1
    assert ledger["seed_scope_dropped_count"] == 0


def test_recent_negative_topic_family_blocks_child_slug(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    child = _verdict("semaglutide_once_weekly", score=99) | {
        "topic_family": "glp_1_longevity",
    }
    fresh = _verdict("klotho_receptor_signaling", score=90)
    _memo_with_source_receipts(root, child, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "2026-06-08.json", {
        "status": "reviewer_rejected",
        "final_verdict": "rejected",
        "submitted_topic": "glp_1_longevity",
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "claim_support_verdict": "unsupported",
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09",
        queue=_queue(child, fresh),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "klotho_receptor_signaling"
    assert ledger["recent_negative_topics_blocked"] == ["glp_1_longevity"]
    assert ledger["considered"][0]["status"] == "cycle_exhausted_topic"
    assert ledger["considered"][0]["family_blocked"] is True


def test_same_seed_domain_inherits_recent_negative_topic_memory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    lane_domain = {"slug": "longevity_research"}
    child = _verdict("sglt2_inhibitors_reduction_hba1c_non_placebo", score=99) | {
        "topic_family": "sglt2_inhibitors_reduction",
        "domain": lane_domain,
    }
    fresh = _verdict("klotho_receptor_signaling", score=90) | {
        "domain": lane_domain,
    }
    _memo_with_source_receipts(root, child, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "2026-06-08.json", {
        "status": "reviewer_rejected",
        "final_verdict": "rejected",
        "submitted_topic": "sglt2_inhibitors_reduction",
        "domain": {"slug": "longevity"},
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "claim_support_verdict": "unsupported",
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09",
        domain="longevity_research",
        queue=_queue(child, fresh),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "klotho_receptor_signaling"
    assert ledger["recent_negative_topics_blocked"] == ["sglt2_inhibitors_reduction"]
    assert ledger["considered"][0]["status"] == "cycle_exhausted_topic"
    assert ledger["considered"][0]["family_blocked"] is True


def test_recent_submission_topic_family_blocks_child_slug(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    child = _verdict("agent_eval_vector_rerank", score=99) | {
        "topic_family": "vector_search_agent_eval",
    }
    fresh = _verdict("workflow_automation_trace", score=90)
    _memo_with_source_receipts(root, child, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-06-06T07-30-00Z",
        "topic": "vector_search_agent_eval",
        "run_dir": "runs/vector_search_agent_eval-evidence-ts",
        "fingerprint": "old",
    }])

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(child, fresh),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "workflow_automation_trace"
    assert "vector_search_agent_eval" in ledger["recently_submitted_topics_blocked"]
    assert ledger["considered"][0]["status"] == "cycle_exhausted_topic"
    assert ledger["considered"][0]["family_blocked"] is True
    assert ledger["family_blocked_count"] == 1


def test_recent_submission_topic_blocks_sibling_variant_by_tokens(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    sibling = _verdict("metformin_use_add_dorzagliatin", score=99)
    fresh = _verdict("resveratrol_supplementation", score=90)
    _memo_with_source_receipts(root, sibling, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-06-22T05-30-01Z",
        "topic": "metformin_treatment_add_dorzagliatin",
        "run_dir": "runs/metformin_treatment_add_dorzagliatin-evidence-ts",
        "fingerprint": "old",
    }])

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-22T09-30-00Z",
        queue=_queue(sibling, fresh),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "resveratrol_supplementation"
    assert ledger["considered"][0]["topic"] == "metformin_use_add_dorzagliatin"
    assert ledger["considered"][0]["status"] == "cycle_exhausted_topic"
    assert ledger["considered"][0]["family_blocked"] is True


def test_failed_cycle_attempts_feed_next_refresh_exclusions() -> None:
    ledger = {
        "cycle_attempts": [{
            "status": "reviewer_revise",
            "topic": "metformin use",
            "run_dir": "runs/metformin use-evidence-2026-06-22T05-33-24Z",
            "fingerprint": "fp-1",
        }],
    }
    blocked_fingerprints: set[str] = set()
    blocked_topics: set[str] = {"SGLT2 inhibitors"}

    daily._sync_failed_attempt_blocks(ledger, blocked_fingerprints, blocked_topics)

    assert blocked_fingerprints == {"fp-1"}
    assert "metformin use" in blocked_topics
    assert daily._family_blocked_topic("metformin_use", blocked_topics) is True


def test_recent_submission_topic_is_domain_scoped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("shared_topic")
    _memo_with_source_receipts(root, verdict, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-06-06T07-30-00Z",
        "domain": {"slug": "ai_research"},
        "topic": "shared_topic",
        "run_dir": "runs/shared_topic-evidence-ts",
        "fingerprint": "old-ai",
    }])

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(verdict),
        retraction_mode="metadata",
    )

    assert ledger["candidate"]["topic"] == "shared_topic"
    assert ledger["recently_submitted_topics_blocked"] == []
    assert ledger["considered"][0]["status"] == "eligible"


def test_seed_scope_metadata_populates_no_candidate_ledger(tmp_path: Path) -> None:
    ledger = daily.run_cycle(
        runs_root=tmp_path / "repo",
        date="2026-06-06T17-30-00Z",
        queue={
            "ready_to_publish": [],
            "agent_repair_needed": [],
            "curation_needed": [],
            "_meta": {
                "seed_scope_dropped_count": 1,
                "seed_scope_fallback_count": 2,
                "seed_scope_fallback_used": True,
            },
        },
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["family_blocked_count"] == 0
    assert ledger["seed_scope_dropped_count"] == 1
    assert ledger["seed_scope_fallback_count"] == 2
    assert ledger["seed_scope_fallback_used"] is True


def test_glp_longevity_cooldown_does_not_token_block_unrelated_families(tmp_path: Path) -> None:
    topics = ["omega_3_longevity", "telomere", "mediterranean_diet"]
    for block_kind in ("published", "submitted"):
        root = tmp_path / block_kind
        if block_kind == "published":
            daily._write_json(root / "_daily_ledger" / "2026-06-05.json", {
                "status": "published",
                "final_verdict": "accepted",
                "published": 1,
                "published_topic": "GLP_1_longevity",
            })
        else:
            daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
                "date": "2026-06-06T07-30-00Z",
                "topic": "GLP_1_longevity",
                "run_dir": "runs/GLP_1_longevity-evidence-ts",
                "fingerprint": "old-glp",
            }])
        for i, topic in enumerate(topics):
            verdict = _verdict(topic, score=100 - i)
            _memo_with_source_receipts(root, verdict, 5)
            ledger = daily.run_cycle(
                runs_root=root,
                date=f"2026-06-06T09-3{i}-00Z",
                queue=_queue(verdict),
                retraction_mode="metadata",
            )

            assert ledger["candidate"]["topic"] == topic
            assert ledger["considered"][0]["status"] == "eligible"
            assert ledger["considered"][0]["family_blocked"] is False
            assert ledger["family_blocked_count"] == 0


def test_acronym_family_blocks_expanded_topic_variant() -> None:
    assert daily._family_blocked_topic(
        "retrieval_augmented_generation", {"RAG"},
    ) is True
    assert daily._family_blocked_topic(
        "rag", {"retrieval_augmented_generation"},
    ) is True
    assert daily._family_blocked_topic(
        "multi_agent_systems", {"RAG"},
    ) is False


def test_receipt_shape_mismatch_reranks_before_submit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    bad = _verdict("mixed_direct_receipts", score=100)
    good = _verdict("matched_direct_receipts", score=90)
    _memo_with_receipt_shapes(root, bad, [
        {
            "canonical_phrase": "Tumor treating fields improved glioblastoma survival.",
            "population": "glioblastoma adults",
            "intervention": "tumor treating fields",
            "endpoint": "overall survival",
        },
        {
            "canonical_phrase": "Omega 3 supplementation reduced runner soreness.",
            "population": "distance runners",
            "intervention": "omega 3 supplementation",
            "endpoint": "muscle soreness",
        },
        {
            "canonical_phrase": "Cognitive training changed dementia recall.",
            "population": "older adults with dementia",
            "intervention": "cognitive training",
            "endpoint": "memory recall",
        },
        {
            "canonical_phrase": "Probiotic feeding changed neonatal enterocolitis rates.",
            "population": "preterm infants",
            "intervention": "probiotic feeding",
            "endpoint": "necrotizing enterocolitis",
        },
        {
            "canonical_phrase": "Metformin lowered glycemic markers in diabetes.",
            "population": "type 2 diabetes patients",
            "intervention": "metformin",
            "endpoint": "hemoglobin a1c",
        },
    ])
    _memo_with_source_receipts(root, good, 5)
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(bad, good),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["submitted_topic"] == "matched_direct_receipts"
    assert ledger["considered"][0]["status"] == "receipt_shape_mismatch"
    assert ledger["considered"][1]["status"] == "eligible"
    assert len(submissions) == 1
    assert submissions[0]["topic"] == "matched_direct_receipts"


def test_duplicate_study_evidence_reranks_before_submit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    bad = _verdict("duplicate_study_evidence", score=100)
    good = _verdict("distinct_study_evidence", score=90)
    _memo_with_source_receipts(root, bad, 5)
    _memo_with_source_receipts(root, good, 5)
    facts_path = root / str(bad["run_dir"]) / "all_facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    duplicate_title = "Contextual trust evaluation for robust coordination in large systems"
    facts[0]["source_paper"] = {"doi": "10.1109/example.1", "title": duplicate_title}
    facts[1]["source_paper"] = {"doi": "10.20944/preprints.example", "title": duplicate_title}
    for idx, fact in enumerate(facts[2:], start=2):
        fact["source_paper"]["title"] = f"Independent coordination source {idx}"
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-23T17-30-00Z",
        queue=_queue(bad, good),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["submitted_topic"] == "distinct_study_evidence"
    assert ledger["considered"][0]["status"] == "duplicate_source_evidence"
    assert ledger["considered"][0]["duplicate_source_evidence"]["count"] == 1
    assert ledger["considered"][1]["status"] == "eligible"
    assert len(submissions) == 1


def test_single_claim_outranks_evidence_map_for_submission(tmp_path: Path) -> None:
    """A bounded single-claim memo clears editorial review; an evidence map does
    not yet. The single claim must submit first even when a source-rich map has a
    higher alpha score, so passing memos are not jumped by maps that reject."""
    root = tmp_path / "repo"
    emap = _verdict("breadth_map", score=99) | {"surface_type": "evidence_map"}
    claim = _verdict("bounded_single_claim", score=70)
    _memo_with_receipt_shapes(root, emap, [
        {"canonical_phrase": "Containment reached 92% in networks.",
         "population": "networks", "intervention": "defense agent",
         "endpoint": "containment"},
        {"canonical_phrase": "Signal phases dropped 43% at intersections.",
         "population": "intersections", "intervention": "signal agent",
         "endpoint": "phases"},
        {"canonical_phrase": "Code scored 3.31x CodeBLEU.",
         "population": "code", "intervention": "coding agent",
         "endpoint": "codebleu"},
        {"canonical_phrase": "Sensing improved 8.56% over survey.",
         "population": "fields", "intervention": "sensor agent",
         "endpoint": "sensing"},
        {"canonical_phrase": "Queue time fell 15% with scheduling.",
         "population": "retail", "intervention": "scheduler agent",
         "endpoint": "queue"},
    ])
    _memo_with_source_receipts(root, claim, 5)
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(emap, claim),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["submitted_topic"] == "bounded_single_claim"
    assert submissions and submissions[0]["topic"] == "bounded_single_claim"


def test_single_claim_held_when_lane_disabled(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """The operator can hold the single-claim lane (submit_single_claim_alpha
    off) — an otherwise-eligible single claim is held, not submitted."""
    monkeypatch.setattr(
        daily, "_alpha_memo_bool",
        lambda name, default: False if name == "submit_single_claim_alpha" else default,
    )
    root = tmp_path / "repo"
    claim = _verdict("bounded_single_claim", score=80)
    _memo_with_source_receipts(root, claim, 5)
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root, date="2026-06-06T09-30-00Z", queue=_queue(claim),
        submit=True, retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}}, submitter=submitter,
    )

    assert ledger["considered"][0]["status"] == "single_claim_submission_held"
    assert submissions == []


def test_llm_cluster_backed_memo_with_shared_shape_submits(tmp_path: Path) -> None:
    """Cluster backing lowers the source floor; the receipts still need a shared
    claim shape before submit."""
    root = tmp_path / "repo"
    v = _verdict("metformin_mortality", score=90)
    _memo_with_receipt_shapes(root, v, [
        {"canonical_phrase": "Metformin lowered 30-day mortality vs non-use.",
         "population": "icu sepsis", "intervention": "metformin",
         "endpoint": "30-day mortality"},
        {"canonical_phrase": "Metformin cut mortality in heart failure cohort.",
         "population": "heart failure", "intervention": "metformin",
         "endpoint": "all-cause mortality"},
        {"canonical_phrase": "Metformin reduced post-op mortality after surgery.",
         "population": "surgical patients", "intervention": "metformin",
         "endpoint": "post-op mortality"},
        {"canonical_phrase": "Metformin associated with lower CKD mortality.",
         "population": "chronic kidney disease", "intervention": "metformin",
         "endpoint": "renal mortality"},
        {"canonical_phrase": "Metformin linked to reduced cancer mortality.",
         "population": "oncology", "intervention": "metformin",
         "endpoint": "cancer mortality"},
    ])
    run = root / str(v["run_dir"])
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "Metformin lowers mortality vs non-use",
        "lead_fact_ids": ["1", "2", "3"],
    }), encoding="utf-8")
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root, date="2026-06-06T09-30-00Z", queue=_queue(v),
        submit=True, retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}}, submitter=submitter,
    )

    assert ledger["considered"][0]["status"] != "receipt_shape_mismatch"
    assert ledger["submitted_topic"] == "metformin_mortality"


def test_intervention_only_overlap_is_not_enough_for_single_claim_shape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("metformin_mixed_bundle")
    _memo_with_receipt_shapes(root, verdict, [
        {"canonical_phrase": "Metformin changed gut bacteria in HFD mice.",
         "population": "mice on high-fat diet", "intervention": "metformin",
         "endpoint": ""},
        {"canonical_phrase": "Metformin changed HbA1c in trial patients.",
         "population": "trial patients", "intervention": "metformin",
         "endpoint": "HbA1c"},
        {"canonical_phrase": "Metformin plus rapamycin changed lifespan.",
         "population": "heterogeneous mice", "intervention": "metformin plus rapamycin",
         "endpoint": ""},
        {"canonical_phrase": "Metformin changed chylomicrons in diabetes.",
         "population": "individuals with diabetes", "intervention": "metformin",
         "endpoint": "chylomicrons"},
        {"canonical_phrase": "Metformin changed tumorigenesis in mice.",
         "population": "NNK-exposed mice", "intervention": "metformin injection",
         "endpoint": "tumorigenesis"},
    ])

    assert daily._direct_receipts_share_shape(verdict, root / "runs", 5) is False


def test_source_dispersion_cluster_backed_memo_still_requires_shape_gate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("heterogeneous_llm_eval") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion"],
        "_staging_refreshed": True,
    }
    _memo_with_receipt_shapes(root, verdict, [
        {"canonical_phrase": "GPT improved questionnaire accuracy.",
         "population": "llm evaluation accuracy tasks", "intervention": "GPT",
         "endpoint": "questionnaire accuracy"},
        {"canonical_phrase": "Claude improved surgery training answers.",
         "population": "llm evaluation accuracy tasks", "intervention": "Claude",
         "endpoint": "training answers"},
        {"canonical_phrase": "Gemini improved oral lesion diagnosis.",
         "population": "llm evaluation accuracy tasks", "intervention": "Gemini",
         "endpoint": "diagnosis"},
        {"canonical_phrase": "DeepSeek improved coding benchmark scores.",
         "population": "llm evaluation accuracy tasks", "intervention": "DeepSeek",
         "endpoint": "code score"},
        {"canonical_phrase": "Bing improved MRI report interpretation.",
         "population": "llm evaluation accuracy tasks", "intervention": "Bing",
         "endpoint": "MRI interpretation"},
    ])
    run = root / str(verdict["run_dir"])
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "LLMs improve accuracy across evaluation tasks",
        "lead_fact_ids": ["1", "2", "3"],
    }), encoding="utf-8")

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
    )

    assert cand is None
    assert considered[0]["status"] == "receipt_shape_mismatch"


def _heterogeneous_map(root: Path, topic: str, count: int = 5) -> dict[str, Any]:
    emap = _verdict(topic, score=90) | {"surface_type": "evidence_map"}
    shapes = [
        {"canonical_phrase": f"Agent task {i} improved metric {i} by {i}% vs baseline.",
         "population": f"setting {i}", "intervention": f"agent {i}",
         "endpoint": f"metric {i}"}
        for i in range(count)
    ]
    _memo_with_receipt_shapes(root, emap, shapes)
    return emap


def test_evidence_map_below_citation_floor_is_held(tmp_path: Path) -> None:
    """A map under the 10-citation intake floor is held (evidence_map_below_
    citation_floor) rather than submitted into a guaranteed intake reject."""
    root = tmp_path / "repo"
    emap = _heterogeneous_map(root, "ai_agents_breadth", count=5)
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(emap),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["considered"][0]["status"] == "evidence_map_below_citation_floor"
    assert submissions == []


def test_evidence_map_with_floor_citations_submits(tmp_path: Path) -> None:
    """A source-rich, bounded map submits as an evidence_map and is not blocked
    by the single-claim shape gate."""
    root = tmp_path / "repo"
    emap = _heterogeneous_map(root, "ai_agents_breadth", count=12)
    run = root / str(emap["run_dir"])
    facts = json.loads(run.joinpath("all_facts.json").read_text(encoding="utf-8"))
    for fact in facts:
        fact["endpoint"] = "bounded completion rate"
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(emap),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["considered"][0]["status"] == "eligible"
    assert ledger["submitted_topic"] == "ai_agents_breadth"
    assert submissions and submissions[0]["article_type"] == "evidence_map"


def test_source_rich_unbounded_evidence_map_is_held(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    emap = _heterogeneous_map(root, "ai_agents_breadth", count=12)
    run = root / str(emap["run_dir"])
    facts = json.loads(run.joinpath("all_facts.json").read_text(encoding="utf-8"))
    for fact in facts:
        fact["comparator"] = "usual care"
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(emap),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["considered"][0]["status"] == "evidence_map_scope_mismatch"
    assert submissions == []


def test_source_rich_map_not_held_when_memo_cites_few(tmp_path: Path) -> None:
    """The citation-floor gate counts the full A_core landscape the map ships,
    not the memo's narrowed cluster. A topic whose memo lists 6 receipts (clearing
    the source floor) but has 12 distinct A_core source papers must SUBMIT — the
    old gate held it at 6 < 10 even though the map cites all 12."""
    root = tmp_path / "repo"
    emap = _verdict("metformin_breadth", score=90) | {
        "surface_type": "evidence_map",
        "headline": "Metformin: evidence map — 6 findings across 6 sources",
    }
    run = root / str(emap["run_dir"])
    run.mkdir(parents=True)
    cited = [str(i + 1) for i in range(6)]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - cluster receipt" for fid in cited)
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    landscape = [str(i + 1) for i in range(12)]
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": f"Effect {fid} in population {fid}.",
            "population": f"population {fid}",
            "endpoint": "bounded completion rate",
            "comparator": "non-use",
            "source_paper": {"doi": f"10.1000/land-{fid}", "title": f"Source {fid}"},
        }
        for fid in landscape
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in landscape],
    }), encoding="utf-8")
    _audit_sidecars(run)
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(emap),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["considered"][0]["status"] == "eligible"
    assert submissions and submissions[0]["article_type"] == "evidence_map"
    assert len(submissions[0]["source_bundle"]) == 12


def test_evidence_map_floor_counts_empirical_rows_only(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    emap = _heterogeneous_map(root, "method_mixed_map", count=12)
    run = root / str(emap["run_dir"])
    facts = json.loads(run.joinpath("all_facts.json").read_text(encoding="utf-8"))
    for idx, fact in enumerate(facts[:4]):
        paper = fact["source_paper"]
        if idx == 0:
            paper["title"] = "Systematic review of agent results"
        elif idx == 1:
            paper["title"] = "Consensus endpoint selection for agent trials"
        elif idx == 2:
            fact["canonical_phrase"] = "Power to detect a 20% reduction was adequate."
        else:
            paper["title"] = "Availability and pricing of agent tools"
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    submissions: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submissions.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-06T09-30-00Z",
        queue=_queue(emap),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
    )

    assert ledger["considered"][0]["status"] == "evidence_map_below_citation_floor"
    assert submissions == []


def test_repairable_retry_does_not_resubmit_unchanged_memo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("unchanged_retry")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    memo_sha = daily._memo_sha256(verdict, root)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "unchanged_retry",
            "submission_id": "old-sub",
            "memo_sha256": memo_sha,
        },
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "unchanged_retry"},
        "researka_decision": {"status": "complete", "decision": "revise"},
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        memo_refresher=lambda _run, _verdict: True,
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["considered"][0]["status"] == "duplicate_submission_fingerprint"


def test_repairable_prior_candidate_reenters_empty_queue(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("retry_queue")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    daily._write_json(run / "publish_verdict.json", verdict)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "retry_queue", "submission_id": "old-sub"},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "retry_queue", "run_dir": verdict["run_dir"]},
        "researka_decision": {"status": "complete", "decision": "revise"},
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "retry_queue"
    assert ledger["considered"][0]["retry_after_rejection"] is True


def test_repairable_evidence_map_still_obeys_queue_scope_gate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _stored_map_run(root, "broad_retry", shared_population=None)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "runs" / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {
            "fingerprint": fp,
            "topic": "broad_retry",
            "run_dir": verdict["run_dir"],
        },
        "researka_decision": {"status": "complete", "decision": "revise"},
    })

    queue = daily._with_repairable_candidates(
        {"ready_to_publish": [], "curation_needed": [], "not_ready": []},
        root / "runs",
    )

    assert queue["ready_to_publish"] == []
    assert [r["topic"] for r in queue["curation_needed"]] == ["broad_retry"]
    assert queue["curation_needed"][0]["queue_status"] == "evidence_map_scope_mismatch"


def test_nonrepairable_rejection_does_not_retry_duplicate(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("nonretryable")
    _memo(root, verdict)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "nonretryable", "submission_id": "old-sub"},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "rejected",
        "candidate": {"fingerprint": fp, "topic": "nonretryable"},
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "failure_category": "quality_gate",
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["reason"] == "all candidates were duplicate submission fingerprints"
    assert ledger["considered"][0]["status"] == "duplicate_submission_fingerprint"


def test_repairable_rejection_retry_is_capped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("capped")
    _memo(root, verdict)
    fp = daily.memo_fingerprint(verdict)
    memo_sha = daily._memo_sha256(verdict, root)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "capped", "submission_id": "old-sub-1", "memo_sha256": memo_sha},
        {"fingerprint": fp, "topic": "capped", "submission_id": "old-sub-2", "memo_sha256": memo_sha},
        {"fingerprint": fp, "topic": "capped", "submission_id": "old-sub-3", "memo_sha256": memo_sha},
        {"fingerprint": fp, "topic": "capped", "submission_id": "old-sub-4", "memo_sha256": memo_sha},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "rejected",
        "candidate": {"fingerprint": fp, "topic": "capped"},
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "gate_failures": [{"name": "minimum_citations"}],
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["considered"][0]["status"] == "duplicate_submission_fingerprint"


def test_repairable_revision_allows_third_repair_retry_across_fingerprint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("revised")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "revised",
            "submission_id": f"old-sub-{i}",
            "memo_sha256": "old-memo",
        }
        for i in range(3)
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "revised"},
        "researka_decision": {
            "status": "complete",
            "decision": "revise",
            "resubmission": {"allowed": True},
        },
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "new-sub"}},
        },
    )

    records = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["retry_after_rejection"] is True
    assert ledger["considered"][0]["retry_attempt_count"] == 3
    assert records[-1]["memo_sha256"] == daily._memo_sha256(verdict, root)


def test_public_submission_markdown_strips_internal_diagnostics() -> None:
    """The public memo must never leak internal pipeline diagnostics — the
    extraction / disagreement / run-state artifacts Researka has rejected on.
    They live in internal-only sections and prefix lines the builder drops by
    construction; this fences that guard against a future render regression.
    """
    memo = (
        "# Alpha memo — topic\n\n"
        "**Headline:** A coherent claim\n"
        "**Alpha score:** 80/100\n"
        "**Confidence:** `evidence_backed_signal`\n"
        "**Run:** `topic-evidence-ts`\n"
        "**Direct source breadth:** `5` direct cited source(s)\n\n"
        "## One-sentence thesis\n\nThe public claim.\n\n"
        "## Evidence receipts\n\n- `fact_id=1` (`A_core`)\n\n"
        "## Next extraction\n\nextraction has not yet produced a bounded signal; "
        "487 disagreement rows; MSCR 49.89%.\n\n"
        "## Subtopic recommendations\n\nsplit into child topics.\n"
    )
    out = daily._public_submission_markdown(memo)
    for artifact in (
        "extraction has not yet produced", "disagreement", "MSCR",
        "Subtopic recommendations", "Next extraction",
    ):
        assert artifact not in out, artifact
    for prefix in ("Alpha score:", "Confidence:", "Run:", "Direct source breadth:"):
        assert prefix not in out, prefix
    assert "The public claim." in out
    assert "`fact_id=1`" in out


def test_submit_retry_exhausted_repairable_revise_can_publish_next_cycle(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("exhausted_repair")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    old_sha = daily._memo_sha256(verdict, root)
    old_public_memo = daily._public_submission_markdown(
        root.joinpath(str(verdict["run_dir"]), "alpha_memo.md").read_text(
            encoding="utf-8",
        )
    )
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": fp,
            "topic": "exhausted_repair",
            "submission_id": "old-sub",
            "memo_sha256": old_sha,
        },
    ])
    decision = {
        "status": "complete",
        "decision": "revise",
        "claim_support_verdict": "supported",
        "required_revisions": ["Remove uncited specifics before resubmission."],
        "resubmission": {"allowed": True, "parent_submission_id": "old-sub"},
    }
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submit_retry_exhausted",
        "final_verdict": "revise",
        "candidate": {"fingerprint": fp, "topic": "exhausted_repair"},
        "cycle_attempts": [{
            "fingerprint": fp,
            "topic": "exhausted_repair",
            "run_dir": verdict["run_dir"],
            "status": "reviewer_revise",
            "researka_decision": decision,
        }],
    })
    submitted: list[str] = []
    submitted_payloads: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        submitted_payloads.append(payload)
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "new-sub"}},
        }

    def decision_fetcher(submission_id: str) -> dict[str, Any]:
        if submission_id == "old-sub":
            return {"status": "pending"}
        return {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/exhausted-repair"},
        }

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nRepair changed memo.\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(daily, "_run_step", lambda *_a, **_k: (True, "ok"))

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=decision_fetcher,
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
        memo_refresher=refresh,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["exhausted_repair"]
    assert submitted_payloads[0]["markdown"] != old_public_memo
    assert "Repair changed memo." in submitted_payloads[0]["markdown"]
    assert ledger["status"] == "published"
    assert ledger["decision_sync"]["pending"] == 1
    assert ledger["considered"][0]["retry_after_rejection"] is True
    assert ledger["considered"][0]["memo_refreshed"] is True
    assert ledger["public_url"] == "https://researka.org/alpha/exhausted-repair"
    records = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert records[-1]["submission_id"] == "new-sub"
    assert records[-1]["memo_sha256"] != old_sha


def test_missing_alpha_memo_is_not_publishable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    missing = _verdict("missing")

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(missing),
        retraction_mode="metadata",
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["considered"][0]["status"] == "missing_alpha_memo"


def test_refresh_exits_early_when_queue_unchanged_across_batches(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """A refresh batch that yields an identical candidate queue and no
    publishable candidate escalates once to backlog warming, then stops
    instead of re-running discovery for every remaining batch."""
    root = tmp_path / "repo"
    thin = _verdict("thin")
    _memo_with_source_receipts(root, thin, 1)  # 1 cited source -> below 5 floor
    calls = {"n": 0}

    warm_flags: list[bool] = []

    def fake_batch(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        warm_flags.append(bool(kwargs.get("warm_backlog")))
        return {
            "ok": True, "ran_topics": [], "top": 20,
            "warm_backlog": bool(kwargs.get("warm_backlog")),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fake_batch)

    ledger = daily.run_cycle(
        runs_root=root, date="2026-05-22",
        queue=_queue(thin),  # same queue every batch -> unchanged signature
        refresh_candidates=True, max_refresh_batches=5,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert calls["n"] == 2  # fast empty refresh, then one warm-backlog try
    assert warm_flags == [False, True]
    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["refresh_backlog_escalation"] == {
        "after_batch": 1,
        "reason": "empty_refresh_no_candidate",
    }
    assert (ledger.get("refresh_early_exit", {}).get("reason")
            == "warm_backlog_empty_no_candidate")


def test_warm_backlog_timeout_degrades_to_no_candidate(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    thin = _verdict("thin")
    _memo_with_source_receipts(root, thin, 1)

    def fake_batch(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        warm = bool(kwargs.get("warm_backlog"))
        return {
            "ok": not warm,
            "note": "TimeoutExpired: warm backlog timed out" if warm else "ok",
            "ran_topics": [],
            "top": 20,
            "warm_backlog": warm,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fake_batch)

    ledger = daily.run_cycle(
        runs_root=root, date="2026-05-22",
        queue=_queue(thin),
        refresh_candidates=True, max_refresh_batches=5,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["published"] == 0
    assert ledger["refresh_early_exit"] == {
        "batch": 2,
        "reason": "warm_backlog_failed",
        "note": "TimeoutExpired: warm backlog timed out",
    }


def test_refresh_timeout_note_degrades_to_no_candidate(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    thin = _verdict("thin")
    _memo_with_source_receipts(root, thin, 1)

    def fake_batch(*_a: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "note": "TimeoutExpired: refresh timed out after 1200 seconds",
            "ran_topics": [],
            "top": 20,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fake_batch)

    ledger = daily.run_cycle(
        runs_root=root, date="2026-05-22",
        queue=_queue(thin),
        refresh_candidates=True, max_refresh_batches=5,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["refresh_early_exit"] == {
        "batch": 1,
        "reason": "refresh_timeout",
        "note": "TimeoutExpired: refresh timed out after 1200 seconds",
    }


def test_refresh_candidate_batch_can_warm_backlog(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(
        5, runs_root=tmp_path, warm_backlog=True)

    assert out["ok"] is True
    assert out["warm_backlog"] is True
    assert "--warm-backlog" in calls[0]
    assert "--derived-topic-limit" in calls[0]
    assert (
        calls[0][calls[0].index("--derived-topic-limit") + 1]
        == str(daily._SUBMIT_WARM_BACKLOG_MIN_PROBE_TOPICS)
    )
    assert "--fact-probe-topics" in calls[0]
    assert (
        calls[0][calls[0].index("--fact-probe-topics") + 1]
        == str(daily._SUBMIT_WARM_BACKLOG_MIN_PROBE_TOPICS)
    )
    assert "--no-editorial" in calls[0]
    assert "--no-frontier" in calls[0]


def test_refresh_candidate_batch_passes_priority_child_topics(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(
        5, runs_root=tmp_path,
        priority_topics=("parent_bounded_claim", "second_child"),
    )

    assert out["priority_topics"] == ["parent_bounded_claim", "second_child"]
    assert out["attempted_priority_topics"] == ["parent_bounded_claim"]
    assert "ran_topics" not in out
    assert calls[0].count("--priority-topic") == 2
    assert calls[0][calls[0].index("--top") + 1] == "1"
    assert out["top"] == 1
    assert "parent_bounded_claim" in calls[0]
    assert "second_child" in calls[0]


def test_refresh_candidate_batch_bounds_parent_priority_window(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(
        2, runs_root=tmp_path,
        priority_topics=("fresh_a", "fresh_b", "fresh_c", "fresh_d"),
    )

    assert out["priority_topics"] == ["fresh_a", "fresh_b", "fresh_c", "fresh_d"]
    assert calls[0].count("--priority-topic") == 4
    assert calls[0][calls[0].index("--top") + 1] == "1"
    assert out["top"] == 1


def test_refresh_candidate_batch_timeout_does_not_mark_all_priorities_ran(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        return False, "TimeoutExpired: first parent timed out after 1200 seconds"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(
        5,
        runs_root=tmp_path,
        priority_topics=("slow_parent", "next_parent"),
    )

    assert out["ok"] is False
    assert out["priority_topics"] == ["slow_parent", "next_parent"]
    assert "ran_topics" not in out


def test_refresh_candidate_batch_ignores_stale_cycle_summary(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    cycle_dir = root / "_curator_cycles"
    cycle_dir.mkdir(parents=True)
    daily._write_json(cycle_dir / "2026-06-22T09-02-26Z.json", {
        "ran": [{"topic": "resveratrol supplementation"}],
    })

    monkeypatch.setattr(
        daily, "_run_step",
        lambda _args, timeout=1800: (
            False, "[cycle] no discovery candidates; aborting.",
        ),
    )

    out = daily._refresh_candidate_batch(5, runs_root=root, domain="ai_research")

    assert out["ok"] is False
    assert "cycle" not in out
    assert "ran_topics" not in out


def test_refresh_candidate_batch_reads_current_domain_cycle(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        cycle_dir = root / "_curator_cycles"
        cycle_dir.mkdir(parents=True)
        daily._write_json(cycle_dir / "2026-06-22T09-37-46Z.json", {
            "domain": {"slug": "ai_research"},
            "ran": [{"topic": "model_eval"}],
        })
        return True, "[cycle] summary -> runs/_curator_cycles/2026-06-22T09-37-46Z.json"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(5, runs_root=root, domain="ai_research")

    assert out["ok"] is True
    assert out["cycle"] == "2026-06-22T09-37-46Z.json"
    assert out["ran_topics"] == ["model_eval"]


def test_refresh_candidate_batch_reads_skipped_excluded_topics(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        cycle_dir = root / "_curator_cycles"
        cycle_dir.mkdir(parents=True)
        daily._write_json(cycle_dir / "2026-06-22T09-37-46Z.json", {
            "domain": {"slug": "longevity_research"},
            "ran": [],
            "skipped_excluded": ["metformin_longevity", "spermidine_longevity"],
        })
        return True, "[cycle] summary -> runs/_curator_cycles/2026-06-22T09-37-46Z.json"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(
        5, runs_root=root, domain="longevity_research",
    )

    assert out["ok"] is True
    assert out["skipped_excluded"] == [
        "metformin_longevity", "spermidine_longevity",
    ]


def test_refresh_candidate_batch_ignores_current_wrong_domain_cycle(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        cycle_dir = root / "_curator_cycles"
        cycle_dir.mkdir(parents=True)
        daily._write_json(cycle_dir / "2026-06-22T09-37-46Z.json", {
            "domain": {"slug": "longevity_research"},
            "ran": [{"topic": "resveratrol supplementation"}],
        })
        return True, "[cycle] summary -> runs/_curator_cycles/2026-06-22T09-37-46Z.json"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(5, runs_root=root, domain="ai_research")

    assert out["ok"] is True
    assert "cycle" not in out
    assert "ran_topics" not in out


def test_child_topics_from_queue_uses_subtopic_recommendations() -> None:
    queue = {
        "agent_repair_needed": [{
            "topic": "parent topic",
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [
                    {"label": "bounded claim"},
                    {"label": "duplicate claim"},
                    {"label": "unlabeled"},
                ],
            },
        }],
        "curation_needed": [{
            "topic": "second",
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [{"label": "child"}],
            },
        }],
    }

    children = daily._child_topics_from_queue(
        queue, {"parent_topic_duplicate_claim"}, limit=2,
    )

    assert children == ["parent_topic_bounded_claim", "second_child"]


def test_child_topics_from_queue_skips_receipt_backed_repair_clusters() -> None:
    queue = {
        "agent_repair_needed": [{
            "topic": "parent topic",
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [
                    {
                        "label": "weak slug child",
                        "member_fact_ids": ["1", "2", "3", "4", "5"],
                    },
                    {"label": "fallback child", "member_fact_ids": ["1", "2"]},
                ],
            },
        }],
    }

    children = daily._child_topics_from_queue(queue, set(), limit=3)

    assert children == ["parent_topic_fallback_child"]


def test_child_topics_from_queue_runs_receipt_backed_curation_clusters() -> None:
    queue = {
        "curation_needed": [{
            "topic": "parent topic",
            "subtopic_recommendations": {
                "recommended": True,
                "clusters": [{
                    "label": "bounded claim",
                    "member_fact_ids": ["1", "2", "3", "4", "5"],
                }],
            },
        }],
    }

    children = daily._child_topics_from_queue(queue, set(), limit=3)

    assert children == ["parent_topic_bounded_claim"]


def test_child_topics_from_queue_prioritizes_source_coherent_clusters() -> None:
    queue = {
        "curation_needed": [
            {
                "topic": "noisy",
                "alpha_score": 100,
                "subtopic_recommendations": {
                    "recommended": True,
                    "reason": "high_d_bad_share_plus_semantic_dispersion",
                    "clusters": [{
                        "label": "large noisy",
                        "member_fact_ids": ["1", "2", "3", "4", "5", "6"],
                    }],
                },
            },
            {
                "topic": "coherent",
                "alpha_score": 10,
                "subtopic_recommendations": {
                    "recommended": True,
                    "reason": "source_coherent_child_cluster",
                    "clusters": [{
                        "label": "bounded claim",
                        "member_fact_ids": ["1", "2", "3", "4", "5"],
                    }],
                },
            },
        ],
    }

    children = daily._child_topics_from_queue(queue, set(), limit=2)

    assert children == ["coherent_bounded_claim", "noisy_large_noisy"]


def test_child_topics_from_queue_skips_underfloor_curation_clusters() -> None:
    queue = {
        "curation_needed": [{
            "topic": "weak",
            "subtopic_recommendations": {
                "recommended": True,
                "reason": "source_coherent_child_cluster",
                "clusters": [{
                    "label": "too thin",
                    "member_fact_ids": ["1", "2", "3", "4"],
                }],
            },
        }],
    }

    assert daily._child_topics_from_queue(queue, set(), limit=3) == []


def test_claim_cluster_candidate_bypasses_parent_topic_exhaustion(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("parent_topic") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion", "direct_source_floor_below_min"],
        "subtopic_recommendations": {
            "recommended": True,
            "clusters": [{
                "label": "bounded claim",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 5)
    refreshed: list[dict[str, Any]] = []

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed.append(refresh_verdict)
        assert refresh_verdict["_claim_cluster_candidate"] is True
        assert refresh_verdict["_parent_topic"] == "parent_topic"
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        _audit_sidecars(run_dir)
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "agent_repair_needed",
            "publish_tier": "TIER_2",
            "blockers": ["source_dispersion"],
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
        blocked_topics={"parent_topic"},
    )

    assert refreshed
    assert cand is not None
    assert cand["topic"] == "parent_topic_bounded_claim"
    assert cand["memo_fingerprint"] != daily.memo_fingerprint(verdict)
    assert considered[0]["topic"] == "parent_topic_bounded_claim"
    assert considered[0]["status"] == "eligible"


def test_claim_cluster_candidate_requires_direct_source_floor(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("thin_parent") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion", "direct_source_floor_below_min"],
        "subtopic_recommendations": {
            "recommended": True,
            "clusters": [{
                "label": "thin claim",
                "member_fact_ids": ["1", "2", "3", "4"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 4)

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert rows == []


def test_claim_cluster_candidate_requires_claim_coherence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("mixed_parent") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion"],
        "subtopic_recommendations": {
            "recommended": True,
            "clusters": [{
                "label": "adherence lower high",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    facts = json.loads(run.joinpath("all_facts.json").read_text(encoding="utf-8"))
    for fact, endpoint in zip(
        facts,
        ("cancer mortality", "sarcopenia", "cognitive impairment", "cardiovascular disease", "all-cause death"),
        strict=True,
    ):
        fact["canonical_phrase"] = f"Adherence was associated with lower {endpoint}."
        fact["population"] = f"{endpoint} population"
        fact["intervention"] = f"{endpoint} exposure"
        fact["endpoint"] = endpoint
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert rows == []


def test_claim_cluster_candidate_rejects_same_intervention_mixed_outcomes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("metformin_treatment") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_1",
        "alpha_score": 0,
        "blockers": ["evidence_map_below_citation_floor"],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "intraperitoneal mice abundances",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_receipt_shapes(root, verdict, [
        {
            "canonical_phrase": "Metformin reduced tumor burden.",
            "population": "A/J mice",
            "intervention": "intraperitoneal metformin",
            "endpoint": "tumor burden",
        },
        {
            "canonical_phrase": "Metformin increased gut microbiota abundance.",
            "population": "high-fat diet mice",
            "intervention": "metformin treatment",
            "endpoint": "microbiota abundance",
        },
        {
            "canonical_phrase": "Metformin combined with rapamycin extended lifespan.",
            "population": "heterogeneous mice",
            "intervention": "metformin and rapamycin",
            "endpoint": "lifespan",
        },
        {
            "canonical_phrase": "Metformin reduced lung tumorigenesis.",
            "population": "NNK-exposed mice",
            "intervention": "intraperitoneal metformin",
            "endpoint": "lung tumorigenesis",
        },
        {
            "canonical_phrase": "Metformin restored intestinal stem-cell expression.",
            "population": "old male mice",
            "intervention": "metformin",
            "endpoint": "stem-cell expression",
        },
    ])

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert rows == []


def test_high_alpha_curation_cluster_can_seed_claim_candidate(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("curated_parent") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_3",
        "alpha_score": 100,
        "blockers": ["feed_scope_mismatch"],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "bounded claim",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 5)

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert len(rows) == 1
    assert rows[0]["topic"] == "curated_parent_bounded_claim"
    assert rows[0]["decision"] == "agent_repair_needed"
    assert rows[0]["surface_type"] == "publish_alpha_memo"
    assert rows[0]["receipt_expansion"]["cited_bound_fact_ids"] == [
        "1", "2", "3", "4", "5",
    ]


def test_claim_cluster_reload_preserves_single_claim_surface(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    verdict = {
        "_claim_cluster_candidate": True,
        "_claim_cluster_topic": "parent_bounded_claim",
        "topic": "parent_bounded_claim",
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_1",
        "surface_type": "publish_alpha_memo",
        "blockers": ["source_dispersion"],
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        "subtopic_recommendations": {"recommended": True, "clusters": []},
    }

    monkeypatch.setattr(daily, "_can_recompute_verdict", lambda _run: True)
    monkeypatch.setattr(
        daily,
        "_write_publish_verdict",
        lambda _run: {
            "topic": "parent",
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "surface_type": "evidence_map",
            "blockers": [],
        },
    )

    refreshed = daily._reload_verdict_after_memo_refresh(verdict, run)

    assert refreshed["topic"] == "parent_bounded_claim"
    assert refreshed["surface_type"] == "publish_alpha_memo"
    assert refreshed["blockers"] == ["source_dispersion"]


def test_repaired_claim_cluster_child_with_shared_shape_can_submit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("parent_bounded_claim") | {
        "_claim_cluster_candidate": True,
        "_claim_cluster_fact_ids": ["1", "2", "3", "4", "5"],
        "_claim_cluster_topic": "parent_bounded_claim",
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_1",
        "surface_type": "publish_alpha_memo",
        "blockers": ["source_dispersion"],
        "_agent_repair_applied": True,
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
    }
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    facts = json.loads(run.joinpath("all_facts.json").read_text(encoding="utf-8"))
    for fact in facts:
        fact["canonical_phrase"] = "Shared mobility outcome improved."
        fact["population"] = "older adults"
        fact["endpoint"] = "mobility"
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    cand, considered = daily.select_candidate(
        {"ready_to_publish": [], "agent_repair_needed": [verdict], "curation_needed": []},
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
    )

    assert cand is not None
    assert considered[0]["status"] == "eligible"


def test_low_alpha_curation_cluster_does_not_seed_claim_candidate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("weak_curated_parent") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_3",
        "alpha_score": 0,
        "blockers": ["blocked_label:no_signal"],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "bounded claim",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 5)

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert rows == []


def test_low_alpha_map_floor_cluster_can_seed_claim_candidate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("broad_parent") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_1",
        "alpha_score": 0,
        "blockers": ["evidence_map_below_citation_floor"],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "bounded claim",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    _memo_with_source_receipts(root, verdict, 5)

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert [row["topic"] for row in rows] == ["broad_parent_bounded_claim"]


def test_claim_cluster_candidate_cites_only_coherent_component(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("exercise") | {
        "decision": "curation_needed",
        "publish_tier": "TIER_1",
        "alpha_score": 0,
        "blockers": ["evidence_map_below_citation_floor"],
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "resistance training",
                "member_fact_ids": ["1", "2", "3", "4", "5", "6"],
            }],
        },
    }
    _memo_with_receipt_shapes(root, verdict, [
        {
            "canonical_phrase": "Resistance training improved mobility.",
            "population": "older adults",
            "intervention": "resistance training",
            "endpoint": "mobility",
        }
        for _ in range(5)
    ] + [{
        "canonical_phrase": "Guideline adherence reduced cancer incidence.",
        "population": "adult cancer-prevention cohorts",
        "intervention": "diet and physical activity guidelines",
        "endpoint": "cancer incidence",
    }])

    rows = daily._claim_cluster_candidates(
        [verdict], root, min_direct_source_count=5,
    )

    assert len(rows) == 1
    assert rows[0]["_claim_cluster_fact_ids"] == ["1", "2", "3", "4", "5"]
    assert rows[0]["receipt_expansion"]["cited_bound_fact_ids"] == [
        "1", "2", "3", "4", "5",
    ]


def test_no_candidate_refreshes_queued_child_topics_next_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("parent") | {
        "decision": "agent_repair_needed",
        "blockers": ["source_dispersion"],
        "subtopic_recommendations": {
            "recommended": True,
            "clusters": [{"label": "bounded claim"}],
        },
    }
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [{
            "topic": "fresh_parent",
            "fact_source_count": 30,
            "paper_count": 30,
            "velocity_score": 100,
        }],
    })
    calls: list[tuple[str, ...]] = []

    def fake_batch(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        priority_topics = tuple(kwargs.get("priority_topics") or ())
        calls.append(priority_topics)
        return {
            "ok": True,
            "ran_topics": list(priority_topics),
            "top": 1,
            "warm_backlog": False,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fake_batch)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-03",
        queue={
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        refresh_candidates=True,
        allow_tier2=True,
        max_refresh_batches=3,
        refresh_top=1,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["refresh_child_topics"] == ["parent_bounded_claim"]
    assert calls == [(), ("parent_bounded_claim",), ("fresh_parent",)]


def test_empty_initial_queue_refreshes_latest_fresh_parent_first(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "newer_empty.json", {
        "domain": {"slug": "longevity"},
        "all": [],
    })
    daily._write_json(discovery / "older_with_parent.json", {
        "domain": {"slug": "longevity"},
        "all": [{
            "topic": "exercise",
            "fact_source_count": 8,
            "paper_count": 8,
            "velocity_score": 50,
        }],
    })
    os.utime(discovery / "newer_empty.json", (2, 2))
    os.utime(discovery / "older_with_parent.json", (1, 1))
    calls: list[tuple[str, ...]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        priority_topics = tuple(kwargs.get("priority_topics") or ())
        calls.append(priority_topics)
        return {
            "ok": True,
            "ran_topics": list(priority_topics),
            "top": 1,
            "warm_backlog": False,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-24",
        refresh_candidates=True,
        max_refresh_batches=1,
        refresh_top=1,
        submit=False,
    )

    assert ledger["refresh_parent_topics"] == ["exercise"]
    assert calls == [("exercise",)]


def test_fullraw_seed_discovery_still_uses_source_rich_parent_priority(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "https://fullraw/search")
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    (discovery / "stale.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "stale_parent",
            "fact_source_count": 30,
            "paper_count": 30,
            "velocity_score": 100,
        }],
    }), encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        priority_topics = tuple(kwargs.get("priority_topics") or ())
        calls.append(priority_topics)
        written = json.loads(
            (root / "_daily_ledger" / "2026-06-24.json").read_text(
                encoding="utf-8",
            )
        )
        assert written["stage"] == "refresh_batch_running"
        assert written["refresh_candidates"]["status"] == "running"
        assert tuple(written["refresh_candidates"]["priority_topics"]) == priority_topics
        return {
            "ok": True,
            "ran_topics": list(priority_topics),
            "top": 1,
            "warm_backlog": False,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-24",
        refresh_candidates=True,
        max_refresh_batches=1,
        refresh_top=1,
        submit=False,
        domain="longevity_research",
    )

    assert calls == [("stale_parent",)]
    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["refresh_parent_topics"] == ["stale_parent"]


def test_v5_client_fallback_counts_as_fullraw_seed_discovery(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    src = tmp_path / "v5-src"
    src.mkdir()
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SRC", str(src))
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK", "1")

    assert daily._fullraw_seed_discovery_enabled() is True


def test_parent_refresh_topic_limit_expands_bounded_candidate_window() -> None:
    assert daily._parent_refresh_topic_limit(1) == 1
    assert daily._parent_refresh_topic_limit(2) == 4
    assert daily._parent_refresh_topic_limit(5) == 4


def test_fresh_parent_discovery_prefers_broader_parent_over_newer_child(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "newer_child.json", {
        "domain": {"slug": "longevity"},
        "all": [{
            "topic": "exercise_difference",
            "fact_source_count": 5,
            "paper_count": 5,
            "velocity_score": 0,
        }],
    })
    daily._write_json(discovery / "older_parent.json", {
        "domain": {"slug": "longevity"},
        "all": [{
            "topic": "exercise",
            "fact_source_count": 5,
            "paper_count": 10,
            "velocity_score": 0,
        }],
    })
    os.utime(discovery / "newer_child.json", (2, 2))
    os.utime(discovery / "older_parent.json", (1, 1))

    topics = daily._fresh_parent_topics_from_discovery(
        root, "longevity_research", set(), limit=1, min_sources=5,
    )

    assert topics == ["exercise"]


def test_fresh_parent_discovery_skips_generic_seed_suffixes(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "ai_research"},
        "all": [
            {"topic": "model_eval_that", "fact_source_count": 100, "paper_count": 100},
            {"topic": "model_eval_our", "fact_source_count": 95, "paper_count": 95},
            {"topic": "model_eval_demonstrate", "fact_source_count": 94, "paper_count": 94},
            {"topic": "model_eval_achieving", "fact_source_count": 93, "paper_count": 93},
            {"topic": "model_eval_outperforming", "fact_source_count": 93, "paper_count": 93},
            {"topic": "model_eval_average", "fact_source_count": 93, "paper_count": 93},
            {"topic": "vitamin D supplementation", "fact_source_count": 92, "paper_count": 92},
            {"topic": "resveratrol supplementation", "fact_source_count": 91, "paper_count": 91},
            {"topic": "model_eval_results", "fact_source_count": 90, "paper_count": 90},
            {"topic": "LLMs", "fact_source_count": 7, "paper_count": 7},
            {"topic": "model_eval_calibration", "fact_source_count": 6, "paper_count": 6},
        ],
    })

    topics = daily._fresh_parent_topics_from_discovery(
        root, "ai_research", set(), limit=2, min_sources=5,
    )

    assert topics == ["LLMs", "model_eval_calibration"]


def test_empty_refresh_skips_recent_source_floor_parent_topics(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "runs"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(root / "_daily_ledger" / "2026-06-23.json", {
        "domain": {"slug": "longevity"},
        "source_floor_refresh_topics": ["NAD"],
        "refresh_batches": [{
            "skipped_below_source_floor": ["NMN"],
        }],
    })
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "NAD", "fact_source_count": 50, "paper_count": 50},
            {"topic": "NMN", "fact_source_count": 40, "paper_count": 40},
            {"topic": "exercise", "fact_source_count": 12, "paper_count": 12},
        ],
    })
    calls: list[tuple[str, ...]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        priority_topics = tuple(kwargs.get("priority_topics") or ())
        calls.append(priority_topics)
        return {
            "ok": True,
            "ran_topics": list(priority_topics),
            "top": 1,
            "warm_backlog": False,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-24",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=1,
        refresh_top=1,
        submit=False,
    )

    assert ledger["recent_source_floor_topics_blocked"] == ["NAD", "NMN"]
    assert ledger["refresh_parent_topics"] == ["exercise"]
    assert calls == [("exercise",)]


def test_latest_cycle_topics_ignores_cross_topic_sidecar(tmp_path: Path) -> None:
    cycles = tmp_path / "_curator_cycles"
    cycles.mkdir()
    cycles.joinpath("2026-06-03T10-00-00Z.json").write_text(
        json.dumps({"ran": [{"topic": "child_a"}]}), encoding="utf-8")
    cycles.joinpath("2026-06-03T10-00-00Z_cross_topic_alpha_memo.json").write_text(
        json.dumps({"headline": "cross topic"}), encoding="utf-8")

    out = daily._latest_cycle_topics(tmp_path)

    assert out["cycle"] == "2026-06-03T10-00-00Z.json"
    assert out["ran_topics"] == ["child_a"]


def test_refresh_candidate_batch_scales_live_probe_window_with_exclusions(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    out = daily._refresh_candidate_batch(
        5,
        excluded_topics={"old_a", "old_b", "old_c"},
        runs_root=tmp_path,
        warm_backlog=True,
    )

    assert out["ok"] is True
    assert (
        calls[0][calls[0].index("--fact-probe-topics") + 1]
        == str(daily._SUBMIT_WARM_BACKLOG_MIN_PROBE_TOPICS)
    )


def test_agent_repair_failed_fingerprint_is_not_repaired_twice_in_cycle(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("repair_still_underfloor") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion", "direct_source_floor_below_min"],
    }
    _memo_with_source_receipts(root, verdict, 6)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 4))
        + "\n\n## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - context" for i in range(4, 7))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    refresh_calls = {"n": 0}

    def refresh(_run_dir: Path, _refresh_verdict: dict[str, Any]) -> bool:
        refresh_calls["n"] += 1
        return True

    def fake_batch(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "ran_topics": [],
            "top": 20,
            "warm_backlog": bool(kwargs.get("warm_backlog")),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fake_batch)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue={
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        refresh_candidates=True,
        max_refresh_batches=2,
        allow_tier2=True,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        min_submit_sources=5,
        min_direct_submit_sources=5,
        memo_refresher=refresh,
    )

    statuses = [row["status"] for row in ledger["considered"]]
    assert refresh_calls["n"] == 1
    assert statuses == ["agent_repair_failed", "cycle_failed_submission"]


def test_submit_mode_holds_thin_source_memos(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    thin = _verdict("thin") | {
        "axes": {
            "source_papers": [
                {"doi": "10.1000/a", "title": "Thin source A"},
                {"doi": "10.1000/b", "title": "Thin source B"},
            ],
        },
    }
    _memo(root, thin)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(thin),
        submit=True,
        retraction_mode="metadata",
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["source_count"] == 2
    assert ledger["considered"][0]["corpus_ab_paper_count"] == 0
    assert ledger["considered"][0]["min_source_count"] == 5
    assert ledger["considered"][0]["status"] == "corpus_source_floor_below_min"


def test_submit_floor_uses_cited_sources_not_available_contexts(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    thin = _verdict("thin") | {
        "axes": {
            "available_source_contexts": 9,
            "bound_receipts": 4,
            "a_core_receipts": 4,
            "source_papers": [
                {"doi": "10.1000/only", "title": "Only cited source"},
            ],
        },
    }
    _memo(root, thin)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(thin),
        submit=True,
        retraction_mode="metadata",
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["source_count"] == 1
    assert ledger["considered"][0]["status"] == "corpus_source_floor_below_min"


def test_submit_floor_counts_sources_used_by_alpha_memo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    thin_metadata = _verdict("memo_sources") | {
        "axes": {
            "source_papers": [
                {"doi": "10.1000/old", "title": "Old lead source"},
            ],
        },
    }
    _memo_with_source_receipts(root, thin_metadata, 5)
    seen_payload: dict[str, Any] = {}

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        seen_payload.update(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(thin_metadata),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {"title": ["clean paper"]}},
        submitter=submitter,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["source_count"] == 5
    assert len(seen_payload["source_bundle"]) == 5


def test_submit_revalidates_stale_queue_row_before_payload(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    ready = _verdict("stale_model_eval")
    _memo_with_source_receipts(root, ready, 4)
    run = root / str(ready["run_dir"])
    current = ready | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_floor_below_min", "direct_source_floor_below_min"],
        "axes": {
            "source_papers": [
                {"doi": f"10.1000/current-{i}", "title": f"Current source {i}"}
                for i in range(4)
            ],
        },
    }
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(current), encoding="utf-8")
    selected_fp = daily.memo_fingerprint(ready)

    def stale_select(
        *_args: Any, **_kwargs: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return ready | {"memo_fingerprint": selected_fp}, [{
            "topic": ready["topic"],
            "decision": "ready_to_publish",
            "status": "eligible",
            "run_dir": ready["run_dir"],
            "fingerprint": selected_fp,
            "source_count": 5,
            "direct_source_count": 5,
        }]

    def should_not_submit(_payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("stale queue row should not be submitted")

    monkeypatch.setattr(daily, "select_candidate", stale_select)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-22",
        queue=_queue(ready),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {"title": ["clean paper"]}},
        submitter=should_not_submit,
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["submitted"] == 0
    assert ledger["cycle_attempts"][0]["status"] == "stale_publish_verdict"
    assert ledger["cycle_attempts"][0]["current_decision"] == "agent_repair_needed"
    assert ledger["cycle_attempts"][0]["source_count"] == 4
    assert ledger["considered"][0]["pre_attempt_status"] == "eligible"
    assert ledger["considered"][0]["status"] == "stale_publish_verdict"


def test_submit_floor_blocks_context_only_source_padding(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("context_sources") | {
        "axes": {"source_papers": [{"doi": "10.1000/old", "title": "Old source"}]},
    }
    _memo_with_source_receipts(root, verdict, 1)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - direct\n\n"
        "## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - context" for i in range(2, 6))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    facts = json.loads(run.joinpath("all_facts.json").read_text(encoding="utf-8"))
    for i in range(2, 6):
        facts.append({
            "fact_id": str(i),
            "source_paper": {"doi": f"10.1000/context-{i}", "title": f"Context {i}"},
        })
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["considered"][0]["source_count"] == 5
    assert ledger["considered"][0]["direct_source_count"] == 1
    assert ledger["considered"][0]["min_direct_source_count"] == 5
    assert ledger["considered"][0]["status"] == "direct_source_floor_below_min"


def test_submit_floor_allows_broad_context_when_direct_sources_pass(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("direct_and_context") | {
        "axes": {"source_papers": [{"doi": "10.1000/old", "title": "Old source"}]},
    }
    _memo_with_source_receipts(root, verdict, 1)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
        + "\n\n"
        "## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`B_context`) - context" for i in range(6, 8))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    facts = [
        {
            "fact_id": str(i),
            "source_paper": {"doi": f"10.1000/source-{i}", "title": f"Source {i}"},
        }
        for i in range(1, 8)
    ]
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": str(i), "lane": "A_core"} for i in range(1, 6)
        ] + [
            {"fact_id": str(i), "lane": "B_context"} for i in range(6, 8)
        ],
    }), encoding="utf-8")
    seen_payload: dict[str, Any] = {}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda payload: seen_payload.update(payload) or {
            "ok": True,
            "status": 200,
            "response": {},
        },
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["source_count"] == 7
    assert ledger["considered"][0]["direct_source_count"] == 5
    # Bundle carries all 7 cited receipts (5 A_core + 2 B_context) for
    # citation_membership; the source floor still keys off direct_source_count=5.
    assert len(seen_payload["source_bundle"]) == 7
    assert seen_payload["citations"] == seen_payload["source_bundle"]
    assert seen_payload["evidence_bundle"]["direct_source_count"] == 5
    assert seen_payload["evidence_bundle"]["context_source_count"] == 2
    assert len(seen_payload["evidence_bundle"]["source_papers"]) == 7


def test_submit_floor_has_no_two_source_alpha_exception(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    narrow = _verdict("narrow") | {
        "axes": {
            "bound_receipts": 2,
            "a_core_receipts": 2,
            "source_papers": [
                {"doi": "10.1000/a", "title": "Narrow source A"},
                {"doi": "10.1000/b", "title": "Narrow source B"},
            ],
        },
    }
    _memo(root, narrow)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(narrow),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["source_count"] == 2
    assert ledger["considered"][0]["status"] == "corpus_source_floor_below_min"


def test_ledger_distinguishes_memo_underuse_from_corpus_thinness(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("underused") | {
        "axes": {
            "source_papers": [{"doi": "10.1000/old", "title": "Old lead"}],
        },
    }
    _memo_with_source_receipts(root, verdict, 1)
    run = root / str(verdict["run_dir"])
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = {"verdicts": [{"fact_id": str(i + 1), "lane": "A_core"} for i in range(5)]}
    for i in range(1, 5):
        facts.append({
            "fact_id": str(i + 1),
            "source_paper": {
                "doi": f"10.1000/unused-{i}",
                "title": f"Unused source {i}",
            },
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="metadata",
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    row = ledger["considered"][0]
    assert row["source_count"] == 1
    assert row["corpus_ab_paper_count"] == 5
    assert row["status"] == "memo_source_floor_below_min"


def test_submit_refreshes_underexpanded_memo_once(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("underused") | {
        "axes": {
            "source_papers": [{"doi": "10.1000/old", "title": "Old lead"}],
        },
    }
    _memo_with_source_receipts(root, verdict, 1)
    run = root / str(verdict["run_dir"])
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    for i in range(1, 5):
        facts.append({
            "fact_id": str(i + 1),
            "source_paper": {
                "doi": f"10.1000/unused-{i}",
                "title": f"Unused source {i}",
            },
        })
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": str(i + 1), "lane": "A_core"} for i in range(5)],
    }), encoding="utf-8")
    seen_payload: dict[str, Any] = {}

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n## Evidence receipts\n\n"
            + "\n".join(
                f"- `fact_id={i + 1}` (`A_core`) - receipt" for i in range(5)
            )
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        seen_payload.update(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        memo_refresher=refresh,
    )

    row = ledger["considered"][0]
    assert row["memo_refreshed"] is True
    assert row["source_count"] == 5
    assert row["status"] == "eligible"
    assert ledger["status"] == "submitted_to_researka"
    assert len(seen_payload["source_bundle"]) == 5


def test_submit_refreshes_missing_audit_sidecars_before_submission(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("missing_sidecars")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    for name in daily._REQUIRED_AUDIT_SIDECARS:
        run.joinpath(name).unlink()

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        _audit_sidecars(run_dir)
        return True

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        memo_refresher=refresh,
    )

    row = ledger["considered"][0]
    assert row["memo_refreshed"] is True
    assert row["status"] == "eligible"
    assert "missing_audit_sidecars" not in row
    assert ledger["status"] == "submitted_to_researka"


def test_retraction_check_blocks_submission_and_writes_hold(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    _memo_with_source_receipts(root, verdict, 5)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {"update-to": [{"type": "retraction"}]}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "held_retraction_check"
    assert ledger["published"] == 0
    hold = root / "_retracted_holds" / "grid_storage-2026-05-22.json"
    assert hold.exists()


def test_crossref_title_retraction_word_does_not_block_clean_paper() -> None:
    check = daily.retraction_check(
        _verdict(),
        mode="crossref",
        fetcher=lambda _doi: {
            "message": {"title": ["Retraction notices in scholarly metadata"]},
        },
    )

    assert check["status"] == "clean"


def _http_error(doi: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.crossref.org/works/" + doi, code, "err", {}, None)  # type: ignore[arg-type]


def test_crossref_404_does_not_hold_submission() -> None:
    """A Crossref 404 (DOI absent from Crossref, e.g. arXiv DOIs) is not a
    retraction and not a transport failure, so it must not produce
    status=error that holds the submission."""
    def fetch_404(doi: str) -> dict[str, Any]:
        raise _http_error(doi, 404)

    check = daily.retraction_check(_verdict(), mode="crossref", fetcher=fetch_404)

    assert check["status"] == "clean"
    assert check["errors"] == []
    assert check["retracted"] == []


def test_crossref_5xx_still_errors() -> None:
    """A genuine transport error (5xx) still surfaces as error so a real
    inability to verify holds the submission."""
    def fetch_503(doi: str) -> dict[str, Any]:
        raise _http_error(doi, 503)

    check = daily.retraction_check(_verdict(), mode="crossref", fetcher=fetch_503)

    assert check["status"] == "error"


def test_submit_token_accepts_research_alias(monkeypatch: MonkeyPatch) -> None:
    for name in daily._SUBMIT_TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEARCH_API_KEY_V4", "alias-token")

    assert daily._submit_token() == ("alias-token", "RESEARCH_API_KEY_V4")


def test_submission_payload_preserves_alpha_memo_contract(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    _memo(root, verdict)
    run = root / str(verdict["run_dir"])
    run.joinpath("memo_audit.json").write_text(
        json.dumps({"verdict": "supported"}), encoding="utf-8")
    run.joinpath("novelty_delta.json").write_text(
        json.dumps({"novelty_delta": {"label": "contradictory"}}), encoding="utf-8")
    run.joinpath("typed_counter_evidence.json").write_text(
        json.dumps({"items": []}), encoding="utf-8")
    run.joinpath("claim_receipt_matrix.json").write_text(
        json.dumps({"direct_sources": 5}), encoding="utf-8")

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["artifact_type"] == "alpha_memo"
    assert payload["article_type"] == "alpha_memo"
    assert payload["author_agent_id"] == "agent-v4-alpha-memo"
    assert payload["agent_id"] == "agent-v4-alpha-memo"
    assert payload["domain"]["slug"] == "longevity"
    assert payload["evidence_bundle"]["domain"]["slug"] == "longevity"
    assert payload["topic"] == "grid_storage"
    assert "What would weaken this" in payload["markdown"]
    assert "sections" not in payload
    assert "source_bundle" in payload
    assert "source_papers" in payload["evidence_bundle"]
    assert payload["evidence_bundle"]["audit_sidecars"] == {
        "claim_receipt_matrix": {"direct_sources": 5},
        "memo_audit": {"verdict": "supported"},
        "novelty_delta": {"novelty_delta": {"label": "contradictory"}},
        "typed_counter_evidence": {"items": []},
    }


def test_submission_payload_declares_evidence_map_article_type(
    tmp_path: Path,
) -> None:
    """Researka routes on article_type: an evidence-map memo must declare
    itself or core review judges it against single-claim criteria."""
    root = tmp_path / "repo"
    verdict = _verdict() | {
        "surface_type": "evidence_map",
        "confidence_label": "evidence_map",
    }
    _memo(root, verdict)

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["article_type"] == "evidence_map"
    assert payload["metadata"]["article_type"] == "evidence_map"
    assert payload["artifact_type"] == "alpha_memo"
    # Researka validates a map on structured sections; intake reads
    # 'Evidence Landscape' for its >=30-word research-question gate.
    sections = payload["sections"]
    assert set(sections) >= {
        "Scope", "Search Summary", "Evidence Landscape", "Findings Map",
        "Tensions and Gaps", "Limitations",
    }
    assert len(sections["Evidence Landscape"].split()) >= 30
    # A map must NOT carry a body: the publish stage validates any non-alpha
    # body as a full manuscript (## Abstract/Methods/...), so an accepted
    # submission with a body fails its autonomous_publish job ('Abstract' 0
    # chars) and never lists. With no body, the platform compiles the body
    # from the sections — the designed evidence-map path.
    assert "markdown" not in payload


def test_evidence_map_cites_full_a_core_landscape_not_memo_cluster(
    tmp_path: Path,
) -> None:
    """A map must cite its whole A_core breadth, not the single-claim cluster the
    memo narrows to. A source-rich topic whose memo lists only 3 receipts but has
    15 distinct A_core source papers under-cites (3 < 10) and trips Researka's
    minimum-citations intake gate; the map path must recover all 15."""
    root = tmp_path / "repo"
    verdict = _verdict() | {
        "surface_type": "evidence_map",
        "confidence_label": "evidence_map",
        "headline": "Grid storage: evidence map — 3 findings across 3 sources",
    }
    run = root / "runs" / str(verdict["run_dir"]).split("/", 1)[1]
    run.mkdir(parents=True)
    cited = ["1", "2", "3"]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Grid storage: evidence map — 3 findings across 3 sources\n\n"
        "## One-sentence thesis\n\nScoping review: 3 distinct A_core findings "
        "across 3 independent sources map a heterogeneous landscape rather than "
        "one claim.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - cluster receipt" for fid in cited)
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    landscape = [str(i + 1) for i in range(15)]
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": f"Effect {fid} reported in population {fid}.",
            "population": f"population {fid}",
            "endpoint": "bounded completion rate",
            "comparator": "usual care",
            "canonical_year": 2024,
            "source_paper": {
                "doi": f"10.1000/land-{fid}",
                "title": f"Landscape source {fid}",
                "year": 2024,
            },
        }
        for fid in landscape
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in landscape],
    }), encoding="utf-8")
    _audit_sidecars(run)

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["article_type"] == "evidence_map"
    # The narrow memo cites 3; the map recovers all 15 A_core sources and clears
    # the >=10-citation intake floor.
    assert len(payload["source_bundle"]) == 15
    assert len(payload["citations"]) == 15
    # Title + abstract are rendered STRUCTURALLY from the one landscape count, not
    # patched from the memo's narrow prose by regex — so the "17 in title / 5 in
    # abstract" class of drift is unrepresentable, for any phrasing. Both are built
    # from the topic + count, so they begin with the canonical structure.
    assert payload["title"] == "Grid storage: evidence map — 15 findings across 15 sources"
    assert payload["abstract"].startswith(
        "Scoping review of Grid storage: 15 findings across 15 independent sources")
    assert payload["summary"] == payload["abstract"]
    # No residue of the memo's cluster count (3) under any phrasing.
    assert "3 findings across 3" not in payload["abstract"]
    assert " 3 " not in payload["title"]
    # The Findings Map is the domain-stratified table; every row is a landscape
    # source so it is verifiable 1:1 against the bundle.
    findings = payload["sections"]["Findings Map"]
    assert findings.count("doi:10.1000/land-") == 15
    assert "| Population | Comparator | Finding | Source |" in findings


def test_submission_payload_alpha_memo_sends_no_sections(tmp_path: Path) -> None:
    """The single-claim lane (word budget 0) keeps its proven section-free
    payload; only maps attach sections."""
    root = tmp_path / "repo"
    verdict = _verdict()
    _memo(root, verdict)

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["article_type"] == "alpha_memo"
    assert "sections" not in payload


def test_submission_payload_requires_domain_metadata(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    verdict.pop("domain")
    _memo(root, verdict)

    with raises(ValueError, match="missing domain metadata"):
        daily._submission_payload(verdict, root / "runs")


def test_submission_payload_uses_domain_specific_agent_identity(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("llm_judge_reliability") | {
        "domain": {"slug": "ai_research"},
    }
    _memo(root, verdict)

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["author_agent_id"] == "agent-v4-alpha-ai-research"
    assert payload["agent_id"] == "agent-v4-alpha-ai-research"
    assert payload["domain"]["slug"] == "ai_research"
    assert payload["evidence_bundle"]["domain"]["slug"] == "ai_research"


def test_submission_payload_strips_internal_alpha_scores(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Bounded endpoint signal\n"
        "**Alpha score:** 100/100\n"
        "**Alpha triage:** `high` (internal ranking; not a certainty claim)\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "Direct receipts support a bounded, testable signal.\n\n"
        "## Why this is surprising\n\n"
        "Narrow signal.\n\n"
        "## Evidence Landscape\n\n"
        "Bounded research question.\n\n"
        "## Context receipts\n\n"
        "- boundary receipt\n\n"
        "## What this changes\n\n"
        "Testable hypothesis.\n\n"
        "## Next extraction\n\n"
        "- internal extraction task\n\n"
        "## Subtopic recommendations\n\n"
        "- split this workflow-only child\n\n"
        "## Provenance / priority\n\n"
        "- **Run bundle SHA-256:** `internal`\n",
        encoding="utf-8",
    )

    payload = daily._submission_payload(verdict, root / "runs")

    assert not payload["markdown"].startswith("# Alpha memo")
    assert "**Alpha score:**" not in payload["markdown"]
    assert "**Alpha triage:**" not in payload["markdown"]
    assert "## Next extraction" not in payload["markdown"]
    assert "internal extraction task" not in payload["markdown"]
    assert "## Subtopic recommendations" not in payload["markdown"]
    assert "workflow-only child" not in payload["markdown"]
    assert "## Provenance / priority" not in payload["markdown"]
    assert "Run bundle SHA-256" not in payload["markdown"]
    assert payload["abstract"] == "Direct receipts support a bounded, testable signal."
    assert payload["summary"] == "Direct receipts support a bounded, testable signal."
    assert "hypothesis-generating alpha memo, not confirmatory evidence" in payload["markdown"]
    assert "not a pooled meta-analysis or settled conclusion" not in payload["markdown"]
    assert "this is a hypothesis-generating alpha map" not in payload["markdown"]
    assert "Boundary evidence only" in payload["markdown"]
    assert payload["evidence_bundle"]["context_sources_are_not_direct_support"] is True


def _cluster_run(tmp_path: Path, cluster: dict[str, Any]) -> Path:
    run = tmp_path / "metformin-evidence-ts"
    run.mkdir()
    run.joinpath("claim_cluster.json").write_text(json.dumps(cluster), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {"fact_id": "1", "population": "diabetics", "canonical_phrase": "a"},
        {"fact_id": "2", "population": "sepsis", "canonical_phrase": "b"},
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({"verdicts": [
        {"fact_id": "1", "lane": "A_core"}, {"fact_id": "2", "lane": "A_core"},
    ]}), encoding="utf-8")
    return run


def test_refresh_claim_cluster_skips_already_flagged(tmp_path: Path) -> None:
    """A fresh build already carries the homogeneity flag — never re-cluster it
    (no repeat model cost, flag preserved exactly)."""
    flagged = {"lead_fact_ids": ["1", "2"], "claim": "x",
               "homogeneous": False, "conformance": 0.4}
    run = _cluster_run(tmp_path, flagged)

    daily._refresh_claim_cluster(run)

    assert json.loads((run / "claim_cluster.json").read_text()) == flagged


def test_refresh_claim_cluster_no_clobber_on_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """A flagless (stale/pre-fix) cluster is left intact when re-clustering yields
    nothing (writer unavailable) — submission is never blocked or corrupted."""
    stale = {"lead_fact_ids": ["1", "2"], "claim": "x"}  # no homogeneous flag
    run = _cluster_run(tmp_path, stale)
    monkeypatch.setattr(
        "agent.claim_clusterer.densest_claim_cluster",
        lambda *a, **k: {"lead_fact_ids": []},
    )

    daily._refresh_claim_cluster(run)

    assert json.loads((run / "claim_cluster.json").read_text()) == stale


def test_refresh_claim_cluster_recomputes_flag_on_stale_run(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """The fix: a stale run with no flag IS re-clustered on the submit path, so a
    fresh homogeneity verdict (here heterogeneous) reaches publish_tier instead of
    the absent-flag default of homogeneous=True that surfaced doomed alpha memos."""
    run = _cluster_run(tmp_path, {"lead_fact_ids": ["1", "2"], "claim": "x"})
    fresh = {"lead_fact_ids": ["1", "2"], "claim": "metformin lowers mortality",
             "homogeneous": False, "conformance": 0.4}
    monkeypatch.setattr(
        "agent.claim_clusterer.densest_claim_cluster", lambda *a, **k: fresh,
    )

    daily._refresh_claim_cluster(run)

    assert json.loads((run / "claim_cluster.json").read_text()) == fresh


def test_submission_payload_excerpt_does_not_cut_mid_sentence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    long_tail = " ".join(["unfinished"] * 260)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Bounded endpoint signal\n\n"
        "## One-sentence thesis\n\n"
        "Direct receipts support the bounded claim. "
        f"{long_tail}\n\n"
        "## Why this is surprising\n\n"
        "Narrow signal.\n",
        encoding="utf-8",
    )

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["abstract"] == "Direct receipts support the bounded claim."
    assert payload["summary"] == "Direct receipts support the bounded claim."


def test_submission_payload_uses_complete_fallback_when_thesis_is_incomplete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Bounded endpoint signal\n\n"
        "## One-sentence thesis\n\n"
        "The cited receipts show an apparent collision between direct sources and hyperbaric oxy\n\n"
        "## Why this is surprising\n\n"
        "The evidence map is bounded to directly cited receipts.\n",
        encoding="utf-8",
    )

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["abstract"] == "The evidence map is bounded to directly cited receipts."
    assert payload["summary"] == "The evidence map is bounded to directly cited receipts."


def test_submission_payload_rejects_alpha_memo_placeholder_summary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo — metformin\n\n"
        "**Headline:** Alpha memo — metformin\n\n"
        "## One-sentence thesis\n\n"
        "Alpha memo — metformin.\n\n"
        "## Why this is surprising\n\n"
        "Review Summary: Alpha memo — metformin.\n",
        encoding="utf-8",
    )

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["abstract"] == "This alpha memo maps directly cited receipts and their limits."
    assert payload["summary"] == payload["abstract"]


def test_submission_payload_uses_researka_source_bundle_schema(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Endpoint-specific storage reserve signal\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n"
        "- `fact_id=2` (`B_context`) - receipt\n",
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": "1",
            "source_paper": {
                "doi": "10.1000/primary",
                "title": "Primary field trial",
                "url": "https://example.test/primary",
                "year": "2025",
                "journal": "Ignored by public source bundle",
                "is_retracted": False,
            },
        },
        {
            "fact_id": "2",
            "source_paper": {
                "doi": "10.1000/review",
                "title": "Systematic review of reserve markets",
                "source_url": "https://example.test/review",
                "year": 2024,
            },
        },
    ]), encoding="utf-8")

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["title"] == "Endpoint-specific storage reserve signal"
    # citation_membership: the submitted bundle must contain EVERY cited receipt
    # (A_core direct + B_context) or Researka rejects. The memo cites fact_id=2
    # (B_context), so its review source must appear in the bundle.
    assert payload["source_bundle"] == [
        {
            "title": "Primary field trial",
            "url": "https://example.test/primary",
            "doi": "10.1000/primary",
            "year": 2025,
            "evidence_type": "primary",
        },
        {
            "title": "Systematic review of reserve markets",
            "url": "https://example.test/review",
            "doi": "10.1000/review",
            "year": 2024,
            "evidence_type": "review",
        },
    ]
    assert payload["citations"] == payload["source_bundle"]
    assert payload["evidence_bundle"]["bound_receipt_count"] == 2
    assert payload["evidence_bundle"]["bound_source_count"] == 2
    assert payload["evidence_bundle"]["source_bundle_count"] == 2
    assert payload["evidence_bundle"]["context_source_count"] == 1


def test_http_submitter_sends_runtime_api_key_header(monkeypatch: MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"accepted": true}'

    def fake_urlopen(req: Request, timeout: int) -> Response:
        seen["timeout"] = timeout
        seen["headers"] = dict(req.header_items())
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = daily._http_submitter("https://api.example/submissions", "secret-token")(
        {"title": "memo"},
    )

    assert result["ok"] is True
    assert seen["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["headers"]["X-api-key"] == "secret-token"


def test_successful_submit_records_submission_not_publication(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    _memo_with_source_receipts(root, verdict, 5)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {"title": ["clean paper"]}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["published"] == 0
    records = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert records[0]["topic"] == "grid_storage"
    assert records[0]["domain"]["slug"] == "longevity"
    assert records[0]["fingerprint"] == daily.memo_fingerprint(verdict)


def test_submission_attempt_record_uses_submitted_fingerprint_lock(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    _memo_with_source_receipts(root, verdict, 5)
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    daily._record_submission_attempt(
        root / "_daily_ledger" / "_submitted_fingerprints.json",
        date="2026-05-22",
        candidate=verdict | {"memo_fingerprint": daily.memo_fingerprint(verdict)},
        runs_root=root / "runs",
        submission_id="sub_lock",
    )

    assert (
        "_submitted_fingerprints.json.lock",
        fcntl.LOCK_EX,
    ) in lock_calls


def test_sync_submission_decisions_records_async_rejection(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission": {
            "attempts": [
                {"response": {"submission": {"id": "sub_123"}}},
            ],
        },
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda submission_id: {
            "status": "complete",
            "decision": "reject",
            "gate_failures": [
                {"name": "minimum_citations", "reason": "source bundle too small"},
            ],
            "seen_id": submission_id,
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21.json").read_text(encoding="utf-8")
    )
    assert summary["checked"] == 1
    assert summary["updated"] == 1
    assert patched["submission_id"] == "sub_123"
    assert patched["final_verdict"] == "rejected"
    assert patched["researka_decision"]["gate_failures"][0]["name"] == "minimum_citations"
    assert patched["publish_summary"]["status"] == "reviewer_rejected"
    assert patched["publish_summary"]["next_action"] == "repair_researka_review_feedback"


def test_sync_submission_decisions_locks_daily_ledger_updates(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission_id": "sub_123",
    })
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    daily.sync_submission_decisions(
        root,
        fetcher=lambda _submission_id: {"status": "complete", "decision": "reject"},
    )

    assert ("2026-05-21.json.lock", fcntl.LOCK_EX) in lock_calls


def test_sync_submission_decisions_locks_submitted_fingerprint_updates(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-05-21T00-00-00Z",
        "topic": "async_reject",
        "submission_id": "sub_lock",
    }])
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _submission_id: {"status": "complete", "decision": "reject"},
    )

    assert summary["updated"] == 1
    assert (
        "_submitted_fingerprints.json.lock",
        fcntl.LOCK_EX,
    ) in lock_calls


def test_sync_submission_decisions_expires_stale_pending(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-05-21T00-00-00Z",
        "topic": "old_pending",
        "submission_id": "sub_pending",
    }])
    daily._write_json(root / "_daily_ledger" / "2026-05-21T00-00-00Z.json", {
        "date": "2026-05-21T00-00-00Z",
        "status": "submitted_to_researka",
        "submission_id": "sub_pending",
        "candidate": {"topic": "old_pending"},
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _submission_id: {"status": "pending", "decision": None},
        now=dt.datetime(2026, 5, 24, 1, 0, 0, tzinfo=dt.UTC),
        max_pending_age_hours=72,
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21T00-00-00Z.json").read_text(
            encoding="utf-8",
        )
    )
    submitted = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert summary["pending"] == 0
    assert summary["stale"] == 1
    assert patched["status"] == "decision_stale_pending"
    assert patched["final_verdict"] == "stale_pending"
    assert submitted[0]["status"] == "decision_stale_pending"
    assert submitted[0]["final_verdict"] == "stale_pending"


def test_sync_submission_decisions_uses_top_level_submission_id(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission_id": "sub_top",
        "submission": {"attempts": [{"response": {}}]},
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda submission_id: {
            "status": "complete",
            "decision": "reject",
            "seen_id": submission_id,
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21.json").read_text(encoding="utf-8")
    )
    assert summary["checked"] == 1
    assert patched["final_verdict"] == "rejected"
    assert patched["researka_decision"]["seen_id"] == "sub_top"


def test_sync_submission_decisions_records_revise_as_retryable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("revise")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": fp, "topic": "revise", "submission_id": "old-sub"},
    ])
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission_id": "old-sub",
        "candidate": {"fingerprint": fp, "topic": "revise"},
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "revise",
            "required_revisions": ["make thesis declarative"],
        },
    )
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert summary["updated"] == 1
    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21.json").read_text(encoding="utf-8")
    )
    assert patched["final_verdict"] == "revise"
    assert ledger["considered"][0]["retry_after_rejection"] is True
    assert ledger["status"] == "submitted_to_researka"


def test_run_cycle_syncs_prior_submission_decisions(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission": {"attempts": [{"response": {"submission": {"id": "sub_123"}}}]},
        "submitted_topic": "grid_storage",
    })
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-05-21T00-00-00Z",
        "topic": "grid_storage",
        "submission_id": "sub_123",
    }])

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "public_url": "https://researka.org/alpha/pub_123",
        },
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21.json").read_text(encoding="utf-8")
    )
    assert ledger["decision_sync"]["updated"] == 1
    assert ledger["decision_sync"]["published"] == 1
    assert patched["status"] == "published"
    assert patched["final_verdict"] == "accepted"
    assert patched["published"] == 1
    assert patched["public_url"] == "https://researka.org/alpha/pub_123"
    submitted = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert submitted[0]["status"] == "published"
    assert submitted[0]["final_verdict"] == "accepted"
    assert submitted[0]["public_url"] == "https://researka.org/alpha/pub_123"


def test_run_cycle_polls_pending_submission_until_publication_renders(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict()
    _memo_with_source_receipts(root, verdict, 5)
    decisions: list[dict[str, object]] = [
        {"status": "pending", "decision": None},
        {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/pub_after_poll"},
        },
    ]
    seen: list[str] = []

    def decision_fetcher(submission_id: str) -> dict[str, object]:
        seen.append(submission_id)
        return decisions[min(len(seen) - 1, len(decisions) - 1)]

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": "sub_poll"}},
        },
        decision_fetcher=decision_fetcher,
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
        decision_poll_attempts=2,
        decision_poll_seconds=0,
    )

    assert seen == ["sub_poll", "sub_poll"]
    assert ledger["status"] == "published"
    assert ledger["published"] == 1
    assert ledger["final_verdict"] == "accepted"
    assert ledger["decision_poll"] == {"attempts": 2, "final_verdict": "accepted"}
    assert ledger["public_url"] == "https://researka.org/alpha/pub_after_poll"


def test_sync_submission_decisions_rejects_accept_without_rendered_page(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission_id": "sub_123",
        "candidate": {"topic": "grid_storage"},
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "public_url": "https://researka.org/alpha/pub_404",
        },
        page_fetcher=lambda _url: {
            "ok": False,
            "status": 404,
            "body": "<html><title>404 Not Found</title></html>",
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21.json").read_text(encoding="utf-8")
    )
    assert summary["checked"] == 1
    assert summary["updated"] == 1
    assert summary["published"] == 0
    assert patched["final_verdict"] == "rejected"
    assert patched["status"] == "public_page_not_rendered"
    assert patched["published"] == 0
    assert patched["publish_failure_reason"] == "public_page_not_rendered"
    assert patched["public_page_check"]["status"] == "not_rendered"
    assert patched["publish_summary"]["status"] == "public_page_not_rendered"
    assert patched["publish_summary"]["public_page_status"] == "not_rendered"


def test_apply_submission_decision_keeps_accept_without_url_pending() -> None:
    ledger: dict[str, Any] = {
        "submitted": 1,
        "published": 0,
        "submitted_topic": "accepted_without_url",
    }

    final = publish_decisions.apply_submission_decision(
        ledger,
        submission_id_value="sub-accepted-without-url",
        decision={"status": "complete", "decision": "accept"},
        page_fetcher=lambda _url: {"ok": False, "status": 0},
    )

    assert final == "pending"
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["final_verdict"] == "pending"
    assert ledger["accepted_pending_public_url"] is True
    assert ledger["published"] == 0
    assert ledger["public_page_check"]["status"] == "missing_public_url"


def test_apply_submission_decision_reports_accepted_dedupe_without_url() -> None:
    ledger: dict[str, Any] = {
        "submitted": 1,
        "published": 0,
        "submitted_topic": "accepted_deduped",
    }

    final = publish_decisions.apply_submission_decision(
        ledger,
        submission_id_value="sub-accepted-deduped",
        decision={
            "status": "complete",
            "decision": "accept",
            "publication": None,
            "failure_category": "integrity_duplicate",
        },
        page_fetcher=lambda _url: {"ok": False, "status": 0},
    )

    assert final == "accepted"
    assert ledger["status"] == "deduped_publication"
    assert ledger["final_verdict"] == "accepted"
    assert ledger["published"] == 0
    assert ledger["published_topic"] == "accepted_deduped"


def test_public_alpha_urls_prefers_publication_url_over_artifact_ids() -> None:
    decision = {
        "dw_artifact_id": "claim_16e9ea4c16c74570",
        "publication": {
            "url": "https://researka.org/alpha/002f5fe8-38f1-4b5a-b1a1-3cdff72ddedd",
            "dw_artifact_id": "claim_b884f46fe51b4b25",
        },
    }

    urls = publish_public.public_alpha_urls(decision)

    assert urls[0] == "https://researka.org/alpha/002f5fe8-38f1-4b5a-b1a1-3cdff72ddedd"
    assert "https://researka.org/alpha/claim_16e9ea4c16c74570" not in urls
    assert "https://researka.org/alpha/claim_b884f46fe51b4b25" not in urls


def test_page_rendered_rejects_not_found_title_with_attrs() -> None:
    assert publish_public.page_rendered({
        "ok": True,
        "status": 200,
        "body": '<title data-next-head="">Alpha Memo Not Found</title>',
    }) is False


def test_sync_submission_decisions_demotes_published_not_found_page(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-06-10.json", {
        "status": "published",
        "submission_id": "sub_missing_page",
        "published": 1,
        "public_url": "https://researka.org/alpha/missing",
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _submission_id: {"status": "complete", "decision": "accept"},
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": '<title data-next-head="">Alpha Memo Not Found</title>',
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-06-10.json").read_text(encoding="utf-8")
    )
    assert summary["checked"] == 1
    assert summary["updated"] == 1
    assert patched["status"] == "public_page_not_rendered"
    assert patched["published"] == 0
    assert patched["publish_failure_reason"] == "public_page_not_rendered"
    assert patched["public_page_check"]["status"] == "not_rendered"


def test_cost_cap_writes_no_publish_ledger(tmp_path: Path) -> None:
    root = tmp_path / "repo"

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(_verdict()),
        estimated_cost_usd=6.0,
        max_cost_usd=5.0,
    )

    assert ledger["status"] == "cost_cap_exceeded"
    assert (root / "_daily_ledger" / "2026-05-22.json").exists()
    written = json.loads(
        (root / "_daily_ledger" / "2026-05-22.json").read_text(encoding="utf-8"),
    )
    assert written["publish_summary"]["next_action"] == "fix_runtime_configuration"


def test_submit_exit_code_fails_closed_for_no_publish_statuses() -> None:
    assert daily._cycle_exit_code(
        {"status": "published", "published": 1}, submit=True,
    ) == 0
    assert daily._cycle_exit_code(
        {"status": "submitted_to_researka", "published": 0}, submit=True,
    ) == 2
    assert daily._cycle_exit_code(
        {"status": "submitted_to_researka", "published": 0},
        submit=True,
        allow_pending_success=True,
    ) == 0
    for status in (
        "no_fresh_candidate",
        "preflight_qa_blocked",
        "submit_retry_exhausted",
        "domain_dry_run_only",
        "candidate_refresh_failed",
    ):
        assert daily._cycle_exit_code({"status": status, "published": 0}, submit=True) == 2


def test_main_emits_end_of_run_blocker_summary(
    monkeypatch: MonkeyPatch, capsys: Any,
) -> None:
    ledger = {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "publish_summary": {
            "status": "no_fresh_candidate",
            "submitted": 0,
            "published": 0,
            "considered": 2,
            "queue_counts": {"ready_to_publish": 0, "curation_needed": 3},
            "top_blockers": {"duplicate_submission_fingerprint": 1},
            "next_action": "refresh_or_expand_candidate_supply",
            "public_url": None,
            "public_url_status": None,
            "public_page_status": None,
        },
    }

    monkeypatch.setattr(sys, "argv", ["daily_alpha_publish_cycle.py", "--date", "2026-06-22"])
    monkeypatch.setattr(daily, "run_cycle", lambda **_kwargs: ledger)

    assert daily.main() == 0
    out = capsys.readouterr().out

    assert "[daily-alpha] status=no_fresh_candidate submitted=0 published=0" in out
    assert "[daily-alpha] summary=" in out
    assert '"considered": 2' in out
    assert '"queue_counts": {"curation_needed": 3, "ready_to_publish": 0}' in out
    assert '"top_blockers": {"duplicate_submission_fingerprint": 1}' in out
    assert '"next_action": "refresh_or_expand_candidate_supply"' in out
    assert '"public_url_status": null' in out
    assert '"public_page_status": null' in out


def test_main_submit_no_fresh_candidate_exits_nonzero_with_summary(
    monkeypatch: MonkeyPatch, capsys: Any,
) -> None:
    ledger = {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "publish_summary": {
            "status": "no_fresh_candidate",
            "submitted": 0,
            "published": 0,
            "considered": 2,
            "queue_counts": {"ready_to_publish": 0, "curation_needed": 3},
            "top_blockers": {"duplicate_submission_fingerprint": 1},
            "next_action": "refresh_or_expand_candidate_supply",
            "public_url": "https://researka.org/alpha/example",
            "public_url_status": 404,
            "public_page_status": "not_rendered",
        },
    }

    monkeypatch.setattr(sys, "argv", [
        "daily_alpha_publish_cycle.py", "--date", "2026-06-22", "--submit",
    ])
    monkeypatch.setattr(daily, "run_cycle", lambda **_kwargs: ledger)

    assert daily.main() == 2
    out = capsys.readouterr().out

    assert "[daily-alpha] status=no_fresh_candidate submitted=0 published=0" in out
    assert "[daily-alpha] summary=" in out
    assert '"considered": 2' in out
    assert '"queue_counts": {"curation_needed": 3, "ready_to_publish": 0}' in out
    assert '"top_blockers": {"duplicate_submission_fingerprint": 1}' in out
    assert '"next_action": "refresh_or_expand_candidate_supply"' in out
    assert '"public_url": "https://researka.org/alpha/example"' in out
    assert '"public_url_status": 404' in out
    assert '"public_page_status": "not_rendered"' in out


def test_main_submitted_pending_only_succeeds_when_explicitly_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    ledger = {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "publish_summary": {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
        },
    }

    monkeypatch.setattr(daily, "run_cycle", lambda **_kwargs: ledger)
    monkeypatch.setattr(sys, "argv", [
        "daily_alpha_publish_cycle.py", "--date", "2026-06-22", "--submit",
    ])
    assert daily.main() == 2

    monkeypatch.setattr(sys, "argv", [
        "daily_alpha_publish_cycle.py", "--date", "2026-06-22", "--submit",
        "--allow-pending-success",
    ])
    assert daily.main() == 0


def test_legacy_allow_tier2_flag_is_removed_from_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/daily_alpha_publish_cycle.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--allow-tier2-repair" in result.stdout
    assert "--allow-tier2 " not in result.stdout


def test_domain_source_floors_are_policy_owned() -> None:
    assert daily._domain_alpha_memo_int(
        "longevity_research", "min_source_papers", 99,
    ) == 5
    assert daily._domain_alpha_memo_int(
        "ai_research", "min_direct_source_papers", 99,
    ) == 5


def test_publish_summary_counts_blockers_and_attempts(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    ledger = {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "queue_counts": {"ready_to_publish": 1, "not_ready": 2},
        "cycle_attempts": [{"status": "reviewer_rejected"}],
        "refresh_candidates": {
            "fullraw_probe_events": [{"status": "no_hits", "query": "metformin"}],
        },
        "considered": [
            {"status": "duplicate_submission_fingerprint"},
            {"status": "agent_repair_needed", "blockers": ["receipt_shape_mismatch"]},
        ],
    }

    daily._write_ledger(path, ledger)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["publish_summary"] == {
        "attempts": 1,
        "considered": 2,
        "last_attempt_status": "reviewer_rejected",
        "next_action": "refresh_or_expand_candidate_supply",
        "public_page_status": None,
        "public_url": None,
        "public_url_status": None,
        "published": 0,
        "queue_counts": {"ready_to_publish": 1, "not_ready": 2},
        "status": "no_fresh_candidate",
        "submitted": 0,
        "top_blockers": {
            "agent_repair_needed": 1,
            "duplicate_submission_fingerprint": 1,
            "fullraw_no_hits": 1,
            "receipt_shape_mismatch": 1,
        },
    }


def test_cycle_topics_carries_fullraw_probe_events(tmp_path: Path) -> None:
    cycle = tmp_path / "cycle.json"
    payload = {
        "domain": {"slug": "longevity_research"},
        "ran": [{"topic": "metformin"}],
        "fullraw_seed_probe": {"events": [{"status": "no_hits", "query": "metformin"}]},
    }

    result = daily._cycle_topics_from_payload(
        cycle, payload, domain="longevity_research",
    )

    assert result["fullraw_probe_events"] == [
        {"status": "no_hits", "query": "metformin"},
    ]


def test_refresh_candidates_builds_one_topic_per_submit_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append((args, timeout))
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-22",
        refresh_candidates=True,
        queue=_queue(),
    )

    assert ledger["refresh_candidates"]["ok"] is True
    assert ledger["refresh_top"] == 5
    assert "--stop-on-ready" in calls[0][0]
    assert calls[0][0][calls[0][0].index("--domain") + 1] == "longevity"
    assert "--with-pico-enrich" not in calls[0][0]
    assert "--no-editorial" in calls[0][0]
    assert "--no-frontier" in calls[0][0]
    assert calls[0][0][calls[0][0].index("--top") + 1] == "5"
    assert calls[0][0][calls[0][0].index("--cooldown-hours") + 1] == "2"
    assert calls[0][1] == 1200


def test_refresh_candidates_passes_ai_research_domain(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-22",
        domain="ai_research",
        refresh_candidates=True,
        queue=_queue(),
    )

    assert calls
    assert calls[0][calls[0].index("--domain") + 1] == "ai_research"


def test_systemd_legacy_daily_longevity_publisher_is_disabled() -> None:
    service = Path("deploy/systemd/researka-alpha-daily.service").read_text(
        encoding="utf-8",
    )
    timer = Path("deploy/systemd/researka-alpha-daily.timer").read_text(
        encoding="utf-8",
    )

    assert "DISABLED legacy generic longevity" in service
    assert "ExecStart=/bin/true" in service
    assert "daily_alpha_publish_cycle.py" not in service
    assert "DISABLED legacy generic longevity" in timer
    assert "OnCalendar=*-*-* 01/8:30:00" in timer


def test_systemd_ai_research_timer_offsets_global_four_hour_submitter() -> None:
    service = Path("deploy/systemd/researka-alpha-ai-research.service").read_text(
        encoding="utf-8",
    )
    timer = Path("deploy/systemd/researka-alpha-ai-research.timer").read_text(
        encoding="utf-8",
    )

    assert "scripts/daily_alpha_publish_cycle.py" in service
    assert "--domain ai_research" in service
    assert "--submit" in service
    assert "--allow-tier2-repair" in service
    assert "--allow-tier2 " not in service
    assert "--max-refresh-batches 5" in service
    assert "OnCalendar=*-*-* 05/8:30:00" in timer
    assert "Unit=researka-alpha-ai-research.service" in timer


def test_systemd_longevity_research_timer_uses_explicit_domain() -> None:
    service = Path(
        "deploy/systemd/researka-alpha-longevity-research.service",
    ).read_text(encoding="utf-8")
    timer = Path(
        "deploy/systemd/researka-alpha-longevity-research.timer",
    ).read_text(encoding="utf-8")

    assert "scripts/daily_alpha_publish_cycle.py" in service
    assert "--domain longevity_research" in service
    assert "--submit" in service
    assert "--allow-tier2-repair" in service
    assert "--allow-tier2 " not in service
    assert "--max-refresh-batches 5" in service
    assert "TimeoutStartSec=2700" in service
    assert "OnCalendar=*-*-* 01/8:30:00" in timer
    assert "Unit=researka-alpha-longevity-research.service" in timer


def test_systemd_cache_warmer_fills_source_rich_backlog() -> None:
    service = Path("deploy/systemd/researka-alpha-cache-warm.service").read_text(
        encoding="utf-8",
    )
    timer = Path("deploy/systemd/researka-alpha-cache-warm.timer").read_text(
        encoding="utf-8",
    )

    assert "scripts/run_topic_discovery.py" in service
    assert "--domain longevity_research" in service
    assert "--warm-backlog" in service
    assert "--derived-topic-limit 5000" in service
    assert "--fact-probe-topics 250" in service
    assert "--cache-only" not in service
    assert "TimeoutStartSec=2700" in service
    assert "OnCalendar=*-*-* 01/4:05:00" in timer
    assert "Persistent=true" in timer
    assert "Unit=researka-alpha-cache-warm.service" in timer


def test_systemd_publish_health_monitor_enforces_sla() -> None:
    service = Path("deploy/systemd/researka-alpha-publish-health.service").read_text(
        encoding="utf-8",
    )
    timer = Path("deploy/systemd/researka-alpha-publish-health.timer").read_text(
        encoding="utf-8",
    )

    assert "scripts/check_alpha_publish_health.py" in service
    assert "--domains longevity_research,ai_research,business_research" in service
    assert ",management_research,economics_research,finance_research,marketing_research" in service
    assert "--expect-published" in service
    assert "--check-url" in service
    assert "--sync-pending-decisions" in service
    assert "--show-next-candidate" in service
    assert "OnCalendar=*-*-* 02/8:45:00" in timer
    assert "Unit=researka-alpha-publish-health.service" in timer


def test_alpha_systemd_services_do_not_mask_no_publish_exits() -> None:
    services = sorted(Path("deploy/systemd").glob("researka-alpha-*.service"))
    expected = {
        "researka-alpha-ai-research.service",
        "researka-alpha-business-research.service",
        "researka-alpha-cache-warm.service",
        "researka-alpha-daily.service",
        "researka-alpha-economics-research.service",
        "researka-alpha-finance-research.service",
        "researka-alpha-longevity-research.service",
        "researka-alpha-management-research.service",
        "researka-alpha-marketing-research.service",
        "researka-alpha-publish-health.service",
    }

    assert {path.name for path in services} == expected
    for service_path in services:
        service = service_path.read_text(encoding="utf-8")
        assert "SuccessExitStatus=2" not in service, service_path.name
        assert "SuccessExitStatus=3" not in service, service_path.name
        assert "SuccessExitStatus=" not in service, service_path.name
        assert "--allow-pending-success" not in service, service_path.name


def test_refresh_cooldown_is_cycle_configurable(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-22",
        refresh_candidates=True,
        refresh_cooldown_hours=0.5,
        queue=_queue(),
    )

    assert "--no-editorial" in calls[0]
    assert "--no-frontier" in calls[0]
    assert calls[0][calls[0].index("--top") + 1] == "5"
    assert calls[0][calls[0].index("--cooldown-hours") + 1] == "0.5"


def test_empty_refresh_escalates_to_zero_cooldown(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    fresh = _verdict("fresh")
    _memo_with_source_receipts(root, fresh, 5)
    queues = iter([_queue(), _queue(fresh)])
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        cycle_dir = root / "_curator_cycles"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            {"ran": [], "skipped_in_cooldown": ["fresh"]}
            if len(calls) == 1 else
            {"ran": [{"topic": "fresh"}], "skipped_in_cooldown": []}
        )
        name = f"cycle-{len(calls)}.json"
        daily._write_json(cycle_dir / name, payload)
        return True, f"[cycle] summary -> runs/_curator_cycles/{name}"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "fresh"
    assert calls[0][calls[0].index("--cooldown-hours") + 1] == "2"
    assert calls[1][calls[1].index("--cooldown-hours") + 1] == "0"
    assert ledger["refresh_batches"][1]["cooldown_reason"] == "retry_after_empty_refresh"


def test_nonpublishable_refresh_topics_are_excluded_next_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    fresh = _verdict("fresh")
    _memo_with_source_receipts(root, fresh, 5)
    queues = iter([_queue(), _queue(fresh)])
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        cycle_dir = root / "_curator_cycles"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            {"ran": [{"topic": "curation_only"}], "skipped_in_cooldown": []}
            if len(calls) == 1 else
            {"ran": [{"topic": "fresh"}], "skipped_in_cooldown": []}
        )
        name = f"cycle-{len(calls)}.json"
        daily._write_json(cycle_dir / name, payload)
        return True, f"[cycle] summary -> runs/_curator_cycles/{name}"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "fresh"
    assert calls[1][-2:] == ["--exclude-topic", "curation_only"]
    assert ledger["refresh_batches"][1]["cooldown_reason"] == "retry_after_blocked_topic"


def test_refresh_batches_continue_until_eligible_candidate(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    thin = _verdict("thin") | {
        "axes": {"source_papers": [{"doi": "10.1000/thin", "title": "Thin source"}]},
    }
    good = _verdict("good")
    _memo_with_source_receipts(root, thin, 1)
    _memo_with_source_receipts(root, good, 5)
    calls: list[list[str]] = []
    queues = iter([_queue(thin), _queue(good)])

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "good"
    assert len(calls) == 2
    assert [row["batch"] for row in ledger["considered"]] == [1, 2]
    assert ledger["considered"][0]["status"] == "corpus_source_floor_below_min"
    assert ledger["considered"][1]["status"] == "eligible"


def test_priority_refresh_runs_one_topic_per_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        cycle_dir = tmp_path / "_curator_cycles"
        cycle_dir.mkdir(parents=True)
        name = "cycle-priority.json"
        daily._write_json(cycle_dir / name, {
            "domain": {"slug": "longevity_research"},
            "ran": [{"topic": "topic_a"}],
            "skipped_in_cooldown": [],
        })
        return True, f"[cycle] summary -> runs/_curator_cycles/{name}"

    monkeypatch.setattr(daily, "_run_step", fake_step)
    result = daily._refresh_candidate_batch(
        5,
        runs_root=tmp_path,
        priority_topics=["topic_a", "topic_b", "topic_c", "topic_d"],
        domain="longevity_research",
    )

    assert calls[0][calls[0].index("--top") + 1] == "1"
    assert calls[0].count("--priority-topic") == 4
    assert result["top"] == 1
    assert result["priority_topics"] == ["topic_a", "topic_b", "topic_c", "topic_d"]
    assert result["attempted_priority_topics"] == ["topic_a"]
    assert result["ran_topics"] == ["topic_a"]


def test_priority_refresh_timeout_marks_only_attempted_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        return False, "TimeoutExpired: curator timed out"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    result = daily._refresh_candidate_batch(
        5,
        runs_root=tmp_path,
        priority_topics=["topic_a", "topic_b", "topic_c", "topic_d"],
        domain="longevity_research",
    )

    assert result["ok"] is False
    assert result["attempted_priority_topics"] == ["topic_a"]
    assert "ran_topics" not in result


def test_source_floor_topics_stay_refreshable_next_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    thin = _verdict("thin") | {
        "axes": {"source_papers": [{"doi": "10.1000/thin", "title": "Thin source"}]},
    }
    fresh = _verdict("fresh")
    _memo_with_source_receipts(root, thin, 1)
    _memo_with_source_receipts(root, fresh, 5)
    calls: list[list[str]] = []
    queues = iter([_queue(thin), _queue(fresh)])

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["source_floor_refresh_topics"] == ["thin"]
    assert calls[1][calls[1].index("--exclude-topic") + 1] == "thin"


def test_sync_rejection_tries_next_refresh_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    rejected = _verdict("rejected")
    accepted = _verdict("accepted", score=80) | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, rejected, 5)
    _memo_with_source_receipts(root, accepted, 5)
    queues = iter([_queue(rejected), _queue(rejected, accepted)])
    responses = iter([
        {"ok": False, "status": 422, "response": "needs evidence"},
        {"ok": True, "status": 200, "response": {"submission": {"id": "sub-ok"}}},
    ])

    monkeypatch.setattr(daily, "_run_step", lambda _args, timeout=1800: (True, "ok"))

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: next(responses),
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "accepted"
    assert ledger["cycle_attempts"][0]["status"] == "rejected_needs_evidence"
    assert ledger["cycle_attempts"][1]["status"] == "submitted_to_researka"
    assert any(row["status"] == "cycle_failed_submission" for row in ledger["considered"])


def test_duplicate_topic_is_excluded_from_next_refresh_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("duplicate")
    fresh = _verdict("fresh") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, duplicate, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": daily.memo_fingerprint(duplicate), "topic": "duplicate"},
    ])
    calls: list[list[str]] = []
    queues = iter([_queue(duplicate), _queue(duplicate, fresh)])

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "fresh"
    assert calls[0].count("--exclude-topic") == 0
    assert calls[1][calls[1].index("--cooldown-hours") + 1] == "0"
    assert calls[1][-2:] == ["--exclude-topic", "duplicate"]
    assert ledger["refresh_batches"][1]["cooldown_reason"] == "retry_after_blocked_topic"
    assert [row["status"] for row in ledger["considered"]] == [
        "duplicate_submission_fingerprint",
        "duplicate_submission_fingerprint",
        "eligible",
    ]


def test_ai_duplicate_exhaustion_reports_duplicate_starvation(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("llm_evaluation_methods_fine_lora") | {
        "domain": {"slug": "ai_research"},
    }
    _memo_with_source_receipts(root, duplicate, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {
            "fingerprint": daily.memo_fingerprint(duplicate),
            "topic": "llm_evaluation_methods_fine_lora",
            "domain": "ai_research",
        },
    ])
    calls: list[dict[str, Any]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "ran_topics": [],
            "top": 20,
            "warm_backlog": bool(kwargs.get("warm_backlog")),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        domain="ai_research",
        queue=_queue(duplicate),
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["reason"] == "all candidates were duplicate submission fingerprints"
    assert daily._cycle_exit_code(ledger, submit=True) == 2
    assert [call["domain"] for call in calls] == ["ai_research", "ai_research"]
    assert [bool(call.get("warm_backlog")) for call in calls] == [False, True]
    assert {
        row["status"] for row in ledger["considered"]
    } == {"duplicate_submission_fingerprint"}
    assert {
        row["domain_slug"] for row in ledger["considered"]
    } == {"ai_research"}


def test_exhausted_duplicate_queue_prioritizes_fresh_parent_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("SGLT2 inhibitors")
    fresh = _verdict("metformin") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, duplicate, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": daily.memo_fingerprint(duplicate), "topic": "SGLT2 inhibitors"},
    ])
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [
            {
                "topic": "sglt2_inhibitors_empagliflozin_placebo",
                "fact_source_count": 24,
                "paper_count": 24,
                "velocity_score": 100,
            },
            {
                "topic": "metformin",
                "fact_source_count": 31,
                "paper_count": 31,
                "velocity_score": 90,
            },
        ],
    })
    calls: list[dict[str, Any]] = []
    queues = iter([_queue(duplicate), _queue(duplicate, fresh)])

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": list(kwargs.get("priority_topics") or []),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "metformin"
    assert ledger["refresh_parent_topics"] == ["metformin"]
    assert calls[-1]["priority_topics"] == ["metformin"]


def test_exhausted_duplicate_queue_batches_fresh_parent_topics(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("SGLT2 inhibitors")
    fresh = _verdict("metformin") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, duplicate, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": daily.memo_fingerprint(duplicate), "topic": "SGLT2 inhibitors"},
    ])
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [
            {
                "topic": "sglt2_inhibitors_empagliflozin_placebo",
                "fact_source_count": 50,
                "paper_count": 50,
                "velocity_score": 100,
            },
            {"topic": "fasting", "fact_source_count": 40, "paper_count": 40},
            {"topic": "metformin", "fact_source_count": 31, "paper_count": 31},
            {"topic": "creatine", "fact_source_count": 25, "paper_count": 25},
            {"topic": "rapamycin", "fact_source_count": 20, "paper_count": 20},
            {"topic": "acarbose", "fact_source_count": 18, "paper_count": 18},
        ],
    })
    calls: list[dict[str, Any]] = []
    queues = iter([_queue(duplicate), _queue(duplicate, fresh)])

    def refresh(refresh_top: int, *_args: Any, **kwargs: Any) -> dict[str, Any]:
        priorities = list(kwargs.get("priority_topics") or [])
        calls.append({"top": refresh_top, "priority_topics": priorities})
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": priorities,
            "priority_topics": priorities,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        refresh_top=5,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    expected = ["fasting", "metformin", "creatine", "rapamycin"]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "metformin"
    assert ledger["refresh_parent_topics"] == expected
    assert calls[-1] == {"top": 5, "priority_topics": expected}


def test_duplicate_queue_prefers_fresh_parent_over_child_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("SGLT2 inhibitors")
    child_source = _verdict("rapamycin") | {
        "decision": "curation_needed",
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "control vehicle encapsulated",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    fresh = _verdict("metformin") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, duplicate, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": daily.memo_fingerprint(duplicate), "topic": "SGLT2 inhibitors"},
    ])
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [{
            "topic": "metformin",
            "fact_source_count": 31,
            "paper_count": 31,
            "velocity_score": 90,
        }],
    })
    calls: list[dict[str, Any]] = []
    first_queue = {
        "ready_to_publish": [duplicate],
        "agent_repair_needed": [],
        "needs_operator_review": [],
        "curation_needed": [child_source],
    }
    queues = iter([first_queue, _queue(fresh)])

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": list(kwargs.get("priority_topics") or []),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert daily._child_topics_from_queue(
        first_queue, {"SGLT2 inhibitors"}, limit=1, domain="longevity",
    ) == ["rapamycin_control_vehicle_encapsulated"]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "metformin"
    assert ledger["refresh_parent_topics"] == ["metformin"]
    assert "refresh_child_topics" not in ledger
    assert calls[-1]["priority_topics"] == ["metformin"]


def test_duplicate_queue_with_repair_rows_still_prefers_fresh_parent_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("SGLT2 inhibitors")
    repair = _verdict("rapamycin_control_vehicle_encapsulated") | {
        "decision": "agent_repair_needed",
        "blockers": ["source_dispersion"],
    }
    fresh = _verdict("metformin") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, duplicate, 5)
    _memo_with_source_receipts(root, repair, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": daily.memo_fingerprint(duplicate), "topic": "SGLT2 inhibitors"},
    ])
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [{
            "topic": "metformin",
            "fact_source_count": 31,
            "paper_count": 31,
            "velocity_score": 90,
        }],
    })
    calls: list[dict[str, Any]] = []
    queues = iter([
        {
            "ready_to_publish": [duplicate],
            "agent_repair_needed": [repair],
            "needs_operator_review": [],
            "curation_needed": [],
        },
        _queue(fresh),
    ])

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": list(kwargs.get("priority_topics") or []),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["refresh_parent_topics"] == ["metformin"]
    assert "refresh_child_topics" not in ledger
    assert calls[-1]["priority_topics"] == ["metformin"]


def test_scope_mismatch_map_prioritizes_fresh_parent_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    broad = _heterogeneous_map(root, "SGLT2 inhibitors", count=12)
    fresh = _verdict("metformin") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [
            {
                "topic": "sglt2_inhibitors_empagliflozin_placebo",
                "fact_source_count": 24,
                "paper_count": 24,
                "velocity_score": 100,
            },
            {
                "topic": "metformin",
                "fact_source_count": 31,
                "paper_count": 31,
                "velocity_score": 90,
            },
        ],
    })
    calls: list[dict[str, Any]] = []
    queues = iter([_queue(broad), _queue(broad, fresh)])

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": list(kwargs.get("priority_topics") or []),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["status"] == "evidence_map_scope_mismatch"
    assert ledger["submitted_topic"] == "metformin"
    assert ledger["refresh_parent_topics"] == ["metformin"]
    assert calls[-1]["priority_topics"] == ["metformin"]


def test_agent_repair_needed_queue_prioritizes_fresh_parent_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    assert daily._family_blocked_topic("rag_engineering_existing_fine", {"RAG"})
    assert daily._family_blocked_topic(
        "llm_evaluation_benchmark_methods", {"llm_evaluation"},
    )
    assert not daily._family_blocked_topic("model_routing", {"llm_evaluation"})

    root = tmp_path / "repo"
    repair = _verdict("RAG") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "domain": {"slug": "ai_research"},
        "run_dir": "runs/RAG-repair-ts",
        "blockers": ["fact_shape_mismatch"],
    }
    fresh = _verdict("model_routing") | {
        "domain": {"slug": "ai_research"},
        "run_dir": "runs/model_routing-fresh-ts",
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, repair, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "ai_research"},
        "all": [
            {
                "topic": "rag_engineering_existing_fine",
                "fact_source_count": 40,
                "paper_count": 40,
                "velocity_score": 100,
            },
            {
                "topic": "model_routing",
                "fact_source_count": 30,
                "paper_count": 30,
                "velocity_score": 90,
            },
        ],
    })
    calls: list[dict[str, Any]] = []
    queues = iter([
        {
            "ready_to_publish": [],
            "agent_repair_needed": [repair],
            "needs_operator_review": [],
            "curation_needed": [],
        },
        _queue(fresh),
    ])

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": list(kwargs.get("priority_topics") or []),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        allow_tier2=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
        domain="ai_research",
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["considered"][0]["status"] == "agent_repair_needed"
    assert ledger["submitted_topic"] == "model_routing"
    assert ledger["refresh_parent_topics"] == ["model_routing"]
    assert calls[-1]["priority_topics"] == ["model_routing"]


def test_timed_out_priority_parent_tries_next_fresh_parent_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    duplicate = _verdict("SGLT2 inhibitors")
    fresh = _verdict("acarbose")
    _memo_with_source_receipts(root, duplicate, 5)
    _memo_with_source_receipts(root, fresh, 5)
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [
        {"fingerprint": daily.memo_fingerprint(duplicate), "topic": "SGLT2 inhibitors"},
    ])
    daily._write_json(root / "_topics_discovery" / "latest.json", {
        "domain": {"slug": "longevity"},
        "all": [
            {
                "topic": "resveratrol supplementation",
                "fact_source_count": 22,
                "paper_count": 20,
                "velocity_score": 100,
            },
            {
                "topic": "acarbose",
                "fact_source_count": 17,
                "paper_count": 16,
                "velocity_score": 90,
            },
        ],
    })
    calls: list[dict[str, Any]] = []
    queues = iter([_queue(duplicate), _queue(duplicate, fresh)])

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        priorities = list(kwargs.get("priority_topics") or [])
        if priorities and priorities[0] == "resveratrol supplementation":
            return {
                "ok": False,
                "note": "TimeoutExpired: resveratrol timed out after 1200 seconds",
                "ran_topics": ["resveratrol supplementation"],
                "priority_topics": priorities,
                "top": 1,
            }
        return {
            "ok": True,
            "note": "ok",
            "ran_topics": priorities,
            "priority_topics": priorities,
            "top": 1,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        max_refresh_batches=3,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "acarbose"
    assert ledger["refresh_timeout_deferrals"] == [{
        "batch": 2,
        "timed_out_topics": ["resveratrol supplementation"],
        "next_priority_topics": ["acarbose"],
        "note": "TimeoutExpired: resveratrol timed out after 1200 seconds",
    }]
    assert [call["priority_topics"] for call in calls if call.get("priority_topics")] == [
        ["resveratrol supplementation", "acarbose"], ["acarbose"],
    ]


def test_child_topic_refresh_stays_inside_active_domain() -> None:
    wrong_domain = _verdict("hormone_optimization") | {
        "decision": "curation_needed",
        "domain": {"slug": "longevity_research"},
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "hrt hormonal",
                "member_fact_ids": ["1", "2", "3", "4", "5"],
            }],
        },
    }
    mistagged_domain = wrong_domain | {"domain": {"slug": "ai_research"}}
    right_domain = _verdict("model_eval") | {
        "decision": "curation_needed",
        "domain": {"slug": "ai_research"},
        "subtopic_recommendations": {
            "recommended": True,
            "reason": "source_coherent_child_cluster",
            "clusters": [{
                "label": "benchmark methods",
                "member_fact_ids": ["6", "7", "8", "9", "10"],
            }],
        },
    }
    queue = {
        "agent_repair_needed": [],
        "curation_needed": [wrong_domain, mistagged_domain, right_domain],
    }

    assert daily._child_topics_from_queue(
        queue, set(), limit=5, domain="ai_research",
    ) == ["model_eval_benchmark_methods"]


def test_source_rich_review_row_submits_without_human_exhaustion(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    topic = "shared_topic"
    review = _verdict(topic) | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "run_dir": f"runs/{topic}-review-ts",
    }
    fresh = _verdict(topic) | {"run_dir": f"runs/{topic}-fresh-ts"}
    _memo_with_source_receipts(root, review, 5)
    _memo_with_source_receipts(root, fresh, 5)
    calls: list[list[str]] = []
    queues = iter([
        {
            "ready_to_publish": [],
            "needs_operator_review": [review],
            "curation_needed": [],
        },
        _queue(fresh),
    ])

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        allow_tier2=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == topic
    assert len(calls) == 1
    assert [row["status"] for row in ledger["considered"]] == ["eligible"]


def test_human_approval_status_is_not_a_publish_cycle_terminal() -> None:
    assert "needs_operator_approval" not in daily._EXHAUSTED_STATUSES
    assert "needs_operator_approval" in daily._AGENT_REPAIR_DECISIONS
    assert "agent_repair_failed" in daily._EXHAUSTED_STATUSES
    assert "evidence_map_below_citation_floor" in daily._TOPIC_EXHAUSTED_STATUSES


def test_source_rich_review_row_does_not_wait_for_human_approval(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    review = _verdict("review_topic") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
    }
    _memo_with_source_receipts(root, review, 5)
    queues = iter([
        {
            "ready_to_publish": [],
            "needs_operator_review": [review],
            "curation_needed": [],
        },
        {
            "ready_to_publish": [],
            "needs_operator_review": [review],
            "curation_needed": [],
        },
    ])

    monkeypatch.setattr(daily, "_run_step", lambda *_args, **_kwargs: (True, "ok"))

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        allow_tier2=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "review_topic"
    assert [row["status"] for row in ledger["considered"]] == ["eligible"]


def test_submit_duplicates_rotate_topics_until_success(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    first = _verdict("first")
    second = _verdict("second")
    third = _verdict("third") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    for verdict in (first, second, third):
        _memo_with_source_receipts(root, verdict, 5)
    queues = iter([
        _queue(first),
        _queue(first, second),
        _queue(first, second, third),
    ])
    responses = iter([
        {
            "ok": False,
            "status": 409,
            "response": '{"detail":{"error":"duplicate_submission","submission_id":"dup-1"}}',
        },
        {
            "ok": False,
            "status": 409,
            "response": '{"detail":{"error":"duplicate_submission","submission_id":"dup-2"}}',
        },
        {"ok": True, "status": 200, "response": {"submission": {"id": "sub-ok"}}},
    ])
    calls: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        refresh_candidates=True,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _payload: next(responses),
        queue_builder=lambda _root, _include_archive: next(queues),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted_topic"] == "third"
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == [
        "rejected_duplicate",
        "rejected_duplicate",
        "submitted_to_researka",
    ]
    records = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        )
    )
    assert [row.get("submit_status") for row in records[:2]] == [
        "rejected_duplicate",
        "rejected_duplicate",
    ]
    assert [row.get("submission_id") for row in records[:2]] == ["dup-1", "dup-2"]
    assert calls[1][calls[1].index("--cooldown-hours") + 1] == "0"
    assert calls[1][-2:] == ["--exclude-topic", "first"]
    assert calls[2][calls[2].index("--cooldown-hours") + 1] == "0"
    assert calls[2][-4:] == ["--exclude-topic", "first", "--exclude-topic", "second"]


def test_unrendered_accept_rotates_to_next_topic(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    first = _verdict("first")
    second = _verdict("second") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    for verdict in (first, second):
        _memo_with_source_receipts(root, verdict, 5)
    calls: list[list[str]] = []
    submitted: list[str] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": f"sub-{payload['topic']}"}},
        }

    def decision_fetcher(submission_id: str) -> dict[str, Any]:
        public_id = "bad" if submission_id == "sub-first" else "good"
        return {
            "status": "complete",
            "decision": "accept",
            "public_url": f"https://researka.org/alpha/{public_id}",
        }

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(first, second),
        refresh_candidates=True,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=decision_fetcher,
        page_fetcher=lambda url: {
            "ok": "good" in url,
            "status": 200 if "good" in url else 404,
            "body": "<html><title>Alpha memo</title></html>"
            if "good" in url else
            "<html><title>404 Not Found</title></html>",
        },
    )

    assert submitted == ["first", "second"]
    assert ledger["status"] == "published"
    assert ledger["final_verdict"] == "accepted"
    assert ledger["published"] == 1
    assert ledger["published_topic"] == "second"
    assert ledger["public_url"] == "https://researka.org/alpha/good"
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == [
        "public_page_not_rendered",
        "published",
    ]
    assert calls[1][-2:] == ["--exclude-topic", "first"]


def test_repairable_reject_retries_same_topic_before_refreshing(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("repair_first")
    _memo_with_source_receipts(root, verdict, 5)
    calls: list[list[str]] = []
    submitted: list[str] = []
    decisions: list[dict[str, Any]] = [
        {
            "status": "complete",
            "decision": "reject",
            "required_revisions": ["A complete scope reset is required."],
        },
        {
            "status": "complete",
            "decision": "accept",
            "public_url": "https://researka.org/alpha/good",
        },
    ]

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        calls.append(args)
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": f"sub-{len(submitted)}"}},
        }

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        text = run_dir.joinpath("alpha_memo.md").read_text(encoding="utf-8")
        run_dir.joinpath("alpha_memo.md").write_text(
            text + "\nScope repair.\n", encoding="utf-8",
        )
        return True

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=2,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=lambda _submission_id: decisions.pop(0),
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
        memo_refresher=refresh,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["repair_first"]
    assert len(calls) == 2
    assert ledger["status"] == "submit_retry_exhausted"
    assert ledger["repair_retry_deferred"] == {
        "topic": "repair_first",
        "reason": "reviewer_rejected",
        "requires": "new_memo_fingerprint",
    }
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == ["reviewer_rejected"]


def test_repairable_revise_stops_at_fingerprint_attempt_cap(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("never_satisfies_reviewer")
    _memo_with_source_receipts(root, verdict, 5)
    submitted: list[str] = []
    refreshes = 0

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": f"sub-{len(submitted)}"}},
        }

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        nonlocal refreshes
        refreshes += 1
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + f"\nRevision attempt {refreshes}.\n",
            encoding="utf-8",
        )
        return True

    def revise(_submission_id: str) -> dict[str, Any]:
        return {
            "status": "complete",
            "decision": "revise",
            "required_revisions": [
                "Tighten the evidence receipts to those directly related to the thesis.",
            ],
            "resubmission": {"allowed": True},
        }

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=5,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=revise,
        page_fetcher=lambda _url: {"ok": False, "status": 0},
        memo_refresher=refresh,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["never_satisfies_reviewer"]
    assert refreshes == 1
    assert ledger["status"] == "submit_retry_exhausted"
    assert ledger["repair_retry_deferred"] == {
        "topic": "never_satisfies_reviewer",
        "reason": "reviewer_revise",
        "requires": "new_memo_fingerprint",
    }
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == ["reviewer_revise"]
    # The cap is enforced by submit_retry_exhausted + submitted-once above. The
    # repairable-revise no longer reports as cycle_exhausted_topic (topic pre-block);
    # it reports cycle_failed_submission — accurate, since the memo WAS submitted and
    # failed after the capped revise. (Revise-retry-unblock: a repairable revise is
    # exempted from the recently-submitted/family block so it can re-enter for the
    # feedback re-write; the attempt cap still stops it.)
    assert ledger["considered"][-1]["status"] == "cycle_failed_submission"


def test_repairable_revise_does_not_resubmit_same_topic_in_cycle(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("same_cycle_revise")
    _memo_with_source_receipts(root, verdict, 5)
    submitted: list[str] = []
    refreshes: list[list[str]] = []

    def fake_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        refreshes.append(args)
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": f"sub-{len(submitted)}"}},
        }

    def revise(_submission_id: str) -> dict[str, Any]:
        return {
            "status": "complete",
            "decision": "revise",
            "required_revisions": ["Repair source alignment before resubmission."],
            "resubmission": {"allowed": True},
        }

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=3,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=revise,
        page_fetcher=lambda _url: {"ok": False, "status": 0},
        memo_refresher=lambda _run, _verdict: True,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["same_cycle_revise"]
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == [
        "reviewer_revise",
    ]
    assert ledger["repair_retry_deferred"] == {
        "topic": "same_cycle_revise",
        "reason": "reviewer_revise",
        "requires": "new_memo_fingerprint",
    }
    assert len(refreshes) >= 2
    assert all("same_cycle_revise" in call for call in refreshes[1:])


def test_repairable_revise_on_final_search_batch_gets_repair_slot(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("final_batch_repair")
    _memo_with_source_receipts(root, verdict, 5)
    submitted: list[str] = []
    refreshes = 0
    decisions: list[dict[str, Any]] = [
        {
            "status": "complete",
            "decision": "revise",
            "claim_support_verdict": "partially_supported",
            "required_revisions": ["Narrow the source bundle before resubmission."],
            "resubmission": {"allowed": True},
        },
        {
            "status": "complete",
            "decision": "accept",
            "public_url": "https://researka.org/alpha/final-batch-repair",
        },
    ]

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": f"sub-{len(submitted)}"}},
        }

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        nonlocal refreshes
        refreshes += 1
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nRepair slot used.\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(daily, "_run_step", fake_step)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=lambda _submission_id: decisions.pop(0),
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
        memo_refresher=refresh,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["final_batch_repair"]
    assert refreshes == 1
    assert ledger["status"] == "submit_retry_exhausted"
    assert ledger["repair_retry_deferred"] == {
        "topic": "final_batch_repair",
        "reason": "reviewer_revise",
        "requires": "new_memo_fingerprint",
    }
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == ["reviewer_revise"]


def test_current_cycle_repairable_revise_does_not_depend_on_ledger_rescan(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("current_cycle_repair")
    _memo_with_source_receipts(root, verdict, 5)
    submitted: list[str] = []
    refresh_decisions: list[dict[str, Any] | None] = []
    decisions: list[dict[str, Any]] = [
        {
            "status": "complete",
            "decision": "revise",
            "claim_support_verdict": "supported",
            "required_revisions": ["Remove uncited specifics before resubmission."],
            "resubmission": {"allowed": True},
        },
        {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/current-cycle-repair"},
        },
    ]

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["topic"]))
        return {
            "ok": True,
            "status": 200,
            "response": {"submission": {"id": f"sub-{len(submitted)}"}},
        }

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refresh_decisions.append(refresh_verdict.get("_repair_decision"))
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nCurrent-cycle repair.\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(daily, "_run_step", fake_step)
    monkeypatch.setattr(
        daily, "_repairable_rejected_fingerprints",
        lambda _path, _domain=None: set(),
    )
    monkeypatch.setattr(
        daily, "_repairable_decisions_by_fingerprint",
        lambda _path, _domain=None: {},
    )

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=lambda _submission_id: decisions.pop(0),
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
        memo_refresher=refresh,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["current_cycle_repair"]
    assert refresh_decisions == [None]
    assert ledger["status"] == "submit_retry_exhausted"
    assert ledger["repair_retry_deferred"] == {
        "topic": "current_cycle_repair",
        "reason": "reviewer_revise",
        "requires": "new_memo_fingerprint",
    }
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == ["reviewer_revise"]


def test_regenerate_on_resubmit_rerenders_clean_candidate_before_submit(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    # A clean (non-staging-refreshed) candidate must be re-rendered through the
    # current writer before submission, so a writer fix reaches the submitted
    # memo even when the run dir was built by older code. Repair candidates are
    # exercised separately (they skip this re-render to avoid reverting the
    # staging repair) by the revise tests above.
    root = tmp_path / "repo"
    # headline="" => no headline-mismatch, so the staging pipeline does NOT
    # re-render this clean candidate; the only re-render is the pre-submit pass.
    verdict = _verdict("clean_publishable")
    verdict["headline"] = ""
    _memo_with_source_receipts(root, verdict, 5)
    submitted: list[str] = []
    refresh_run_dirs: list[Path] = []

    def fake_step(_args: list[str], timeout: int = 1800) -> tuple[bool, str]:
        return True, "ok"

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload.get("topic")))
        return {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        refresh_run_dirs.append(run_dir)
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nWRITER_FIX_APPLIED\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(daily, "_run_step", fake_step)
    daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=submitter,
        decision_fetcher=lambda _submission_id: {"status": "complete", "decision": "accept"},
        page_fetcher=lambda _url: {
            "ok": True,
            "status": 200,
            "body": "<html><title>Alpha memo</title></html>",
        },
        memo_refresher=refresh,
        sleep=lambda _seconds: None,
    )

    assert submitted == ["clean_publishable"]
    # The pre-submit pass re-rendered the staging-untouched candidate exactly once.
    assert refresh_run_dirs == [root / str(verdict["run_dir"])]
    assert "WRITER_FIX_APPLIED" in (root / str(verdict["run_dir"]) / "alpha_memo.md").read_text(
        encoding="utf-8",
    )


def test_regenerate_on_resubmit_kill_switch_disables_rerender(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("clean_publishable")
    verdict["headline"] = ""  # staging won't re-render; isolate the pre-submit pass
    _memo_with_source_receipts(root, verdict, 5)
    refresh_run_dirs: list[Path] = []
    monkeypatch.setenv("REGENERATE_ON_RESUBMIT", "off")
    monkeypatch.setattr(daily, "_run_step", lambda _a, timeout=1800: (True, "ok"))

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        refresh_run_dirs.append(run_dir)
        return True

    daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(verdict),
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        submitter=lambda _p: {"ok": True, "status": 200, "response": {"submission": {"id": "s"}}},
        decision_fetcher=lambda _i: {"status": "complete", "decision": "accept"},
        page_fetcher=lambda _u: {"ok": True, "status": 200, "body": "<html><title>t</title></html>"},
        memo_refresher=refresh,
        sleep=lambda _s: None,
    )
    assert refresh_run_dirs == []  # kill switch off => no pre-submit re-render


def test_accepted_shape_bias_breaks_candidate_tie(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    matching = _verdict("matching", score=90) | {
        "axes": {"source_papers": [{"doi": f"10.1/{i}"} for i in range(5)]},
    }
    raw_higher = _verdict("raw_higher", score=93) | {
        "axes": {"source_papers": [{"doi": f"10.2/{i}"} for i in range(12)]},
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_source_receipts(root, matching, 5)
    _memo_with_source_receipts(root, raw_higher, 12)
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "final_verdict": "accepted",
        "candidate": {
            "fingerprint": "accepted-shape",
            "run_dir": matching["run_dir"],
        },
        "considered": [
            {
                "fingerprint": "accepted-shape",
                "source_count": 5,
                "alpha_score": 88,
                "publish_tier": "TIER_1",
                "surface_type": "publish_alpha_memo",
            },
        ],
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(raw_higher, matching),
        retraction_mode="metadata",
    )

    assert ledger["status"] == "dry_run_selected"
    assert ledger["candidate"]["topic"] == "matching"
    assert ledger["considered"][0]["accepted_shape_bonus"] > 0


def test_source_literature_fallback_submits_after_empty_fact_lane(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    longevity_path = root / "_topics_discovery" / "longevity.json"
    longevity_path.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "glycation_AGEs",
            "paper_count": 25,
            "fact_source_count": 0,
            "top_paper_title": "Advanced Glycation End Products",
        }],
    }), encoding="utf-8")
    business_path = root / "_topics_discovery" / "business.json"
    business_path.write_text(json.dumps({
        "domain": {"slug": "business_research"},
        "all": [{
            "topic": "minimum_wage_employment",
            "paper_count": 25,
            "fact_source_count": 0,
        }],
    }), encoding="utf-8")
    os.utime(business_path, (time.time() + 5, time.time() + 5))
    papers = [
        {"title": "AGE-RAGE signalling and skin collagen aging", "doi": "10.1234/1", "year": 2024},
        {"title": "Glycation stress and RAGE activation in vascular aging", "doi": "10.1234/2", "year": 2024},
        {"title": "Collagen crosslinking in advanced glycation biology", "doi": "10.1234/3", "year": 2024},
        {"title": "RAGE pathways in age-related tissue injury", "doi": "10.1234/4", "year": 2024},
        {"title": "Glycation-derived collagen stiffening review", "doi": "10.1234/5", "year": 2024},
    ]
    seen_payload: dict[str, Any] = {}
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        seen_payload.update(payload)
        return {"ok": True, "status": 200,
                "response": {"submission": {"id": "sub-1"}}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=submitter,
        source_paper_fetcher=lambda _topic, _limit: papers,
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {
            "ok": True, "status": 200, "body": "<title>Source</title>",
        },
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "glycation_AGEs"
    assert ledger["source_literature_fallback"]["status"] == "selected"
    assert seen_payload["domain"]["slug"] == "longevity_research"
    assert seen_payload["topic"] == "glycation_AGEs"
    assert seen_payload["evidence_bundle"]["surface_type"] == "source_literature_boundary"
    assert seen_payload["evidence_bundle"]["direct_source_count"] == 5
    assert len(seen_payload["source_bundle"]) == 5
    assert "Boundary map" in seen_payload["markdown"]
    assert "rage" in seen_payload["markdown"].lower()
    assert "collagen" in seen_payload["markdown"].lower()
    run_dir = root / "glycation_AGEs-source-literature-2026-06-09T18-00-00Z"
    assert (run_dir / "source_literature_payload.json").exists()
    records = json.loads(
        (root / "_daily_ledger" / "_submitted_fingerprints.json").read_text(
            encoding="utf-8",
        ),
    )
    assert records[0]["topic"] == "glycation_AGEs"
    assert records[0]["memo_sha256"]
    assert records[0]["bundle_signature"]


def test_source_literature_fallback_blocks_under_citable_source_floor(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "economics.json").write_text(json.dumps({
        "domain": {"slug": "economics_research"},
        "all": [{"topic": "minimum_wage", "paper_count": 25}],
    }), encoding="utf-8")
    papers = [
        {
            "title": "THE EFFECT OF MINIMUM WAGES ON EMPLOYMENT: A FACTOR MODEL APPROACH",
            "doi": "10.1234/minwage-1",
            "year": 2024,
        },
        {
            "title": "Revisiting the Minimum Wage-Employment Debate",
            "doi": "10.1234/minwage-2",
            "year": 2024,
        },
        {
            "title": "European Minimum Wage Policy: Wage-Led Growth and Fair Wages",
            "id": "local-3",
            "year": 2024,
        },
        {
            "title": "At What Level Should Countries Set Their Minimum Wages",
            "id": "local-4",
            "year": 2024,
        },
        {
            "title": "Nominal Wage Rigidity in Village Labor Markets",
            "doi": "10.1234/minwage-5",
            "year": 2024,
        },
    ]
    submitted = {"called": False}

    def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        submitted["called"] = True
        return {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-30-00Z",
        domain="economics_research",
        queue=_queue(),
        submit=True,
        submitter=submitter,
        source_paper_fetcher=lambda _topic, _limit: papers,
        sleep=lambda _seconds: None,
    )

    assert submitted["called"] is False
    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["source_literature_fallback"]["status"] == "blocked"
    assert ledger["source_literature_fallback"]["reason"] == "source_bundle_below_min"
    assert ledger["source_literature_fallback"]["direct_source_count"] == 3


def test_source_literature_fallback_runs_after_refresh_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "glycation_AGEs", "paper_count": 25}],
    }), encoding="utf-8")
    papers = [
        {"title": "AGE-RAGE signalling and skin collagen aging", "doi": "10.1234/1", "year": 2024},
        {"title": "Glycation stress and RAGE activation in vascular aging", "doi": "10.1234/2", "year": 2024},
        {"title": "Collagen crosslinking in advanced glycation biology", "doi": "10.1234/3", "year": 2024},
        {"title": "RAGE pathways in age-related tissue injury", "doi": "10.1234/4", "year": 2024},
        {"title": "Glycation-derived collagen stiffening review", "doi": "10.1234/5", "year": 2024},
    ]
    seen_payload: dict[str, Any] = {}
    monkeypatch.setattr(
        daily, "_refresh_candidate_batch",
        lambda *_args, **_kwargs: {"ok": False, "note": "simulated refresh failure"},
    )

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-45-00Z",
        domain="longevity_research",
        queue=_queue(),
        refresh_candidates=True,
        submit=True,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        source_paper_fetcher=lambda _topic, _limit: papers,
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["refresh_early_exit"]["reason"] == "refresh_failed_before_source_literature"
    assert ledger["source_literature_fallback"]["status"] == "selected"
    assert seen_payload["topic"] == "glycation_AGEs"


def test_long_submit_refresh_reaches_source_lit_after_fullraw_batches(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "glycation_AGEs",
            "paper_count": 25,
            "fact_source_count": 0,
        }],
    }), encoding="utf-8")
    papers = [
        {
            "title": title,
            "doi": f"10.1234/glycation-{idx}",
            "year": 2024,
        }
        for idx, title in enumerate((
            "AGE-RAGE signalling and skin collagen aging",
            "Glycation stress and RAGE activation in vascular aging",
            "Collagen crosslinking in advanced glycation biology",
            "RAGE pathways in age-related tissue injury",
            "Glycation-derived collagen stiffening review",
        ))
    ]
    refresh_calls: list[int] = []

    def refresh(refresh_top: int, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        refresh_calls.append(refresh_top)
        return {"ok": True, "note": "empty_refresh", "top": refresh_top}

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)
    monkeypatch.setattr(
        daily, "_fetch_source_literature_papers",
        lambda _topic, _limit, **_kwargs: papers,
    )

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue_builder=lambda *_args, **_kwargs: _queue(),
        refresh_candidates=True,
        max_refresh_batches=5,
        refresh_top=5,
        submit=True,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {
            "ok": True, "status": 200, "body": "<title>Source</title>",
        },
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert refresh_calls == [5, 5, 5, 5, 5]
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "glycation_AGEs"
    assert ledger["source_literature_fallback"]["status"] == "selected"


def test_source_literature_fallback_uses_default_fetcher_after_empty_submit_lane(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "source_rich_parent", "paper_count": 10, "fact_source_count": 20},
            {"topic": "thin_parent", "paper_count": 5, "fact_source_count": 30},
        ],
    }), encoding="utf-8")
    papers = [
        {"title": "Metabolic pathway review in aging", "doi": "10.1234/1", "year": 2024},
        {"title": "Inflammation signalling across lifespan", "doi": "10.1234/2", "year": 2024},
        {"title": "Mitochondrial stress response biology", "doi": "10.1234/3", "year": 2024},
        {"title": "Cellular senescence intervention map", "doi": "10.1234/4", "year": 2024},
        {"title": "Proteostasis mechanisms in age-related decline", "doi": "10.1234/5", "year": 2024},
    ]
    seen_payload: dict[str, Any] = {}
    monkeypatch.setattr(daily, "_fetch_source_literature_papers", lambda *_args, **_kwargs: papers)
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "source_rich_parent"
    assert seen_payload["evidence_bundle"]["surface_type"] == "source_literature_boundary"
    assert "scoping note" in seen_payload["abstract"]
    assert "## Context separation" in seen_payload["markdown"]
    assert "## Research question" in seen_payload["markdown"]
    assert "## Selection criteria" in seen_payload["markdown"]
    assert seen_payload["source_bundle"][0] == {
        "title": "Metabolic pathway review in aging",
        "url": "https://doi.org/10.1234/1",
        "doi": "10.1234/1",
        "year": 2024,
        "evidence_type": "review",
    }
    assert seen_payload["citations"] == seen_payload["source_bundle"]
    assert not seen_payload["abstract"].startswith("Answer:")
    assert "not uniformly convergent" in seen_payload["abstract"]
    assert "Grouped by direction" in seen_payload["markdown"]
    assert "latest Longevity" not in seen_payload["markdown"]
    assert "matched PICO" in seen_payload["markdown"]


def test_source_literature_candidate_skips_refresh_before_submit(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "glycation_AGEs", "paper_count": 10, "fact_source_count": 20}],
    })
    papers: list[dict[str, Any]] = [
        {"title": "AGE-RAGE signalling and skin collagen aging", "doi": "10.1234/1"},
        {"title": "Glycation stress and RAGE activation in vascular aging", "doi": "10.1234/2"},
        {"title": "Collagen crosslinking in advanced glycation biology", "doi": "10.1234/3"},
        {"title": "RAGE pathways in age-related tissue injury", "doi": "10.1234/4"},
        {"title": "Glycation-derived collagen stiffening review", "doi": "10.1234/5"},
    ]
    for idx, paper in enumerate(papers):
        paper["source_fact"] = {
            "canonical_phrase": f"glycation AGE boundary finding {idx}",
            "population": "adults",
            "intervention": "glycation biology",
            "comparator": "control",
        }

    def fail_refresh(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("source-literature candidate should skip refresh")

    monkeypatch.setattr(daily, "_refresh_candidate_batch", fail_refresh)
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-30-00Z",
        domain="longevity_research",
        refresh_candidates=True,
        submit=True,
        source_paper_fetcher=lambda *_args, **_kwargs: papers,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["refresh_batches"][0]["note"] == (
        "skipped_source_literature_candidate_available"
    )
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "glycation_AGEs"


def test_thin_source_literature_candidate_does_not_skip_refresh(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "melatonin_aging", "paper_count": 10, "fact_source_count": 20}],
    })
    thin_papers = [
        {
            "title": f"Melatonin aging source {idx}",
            "doi": f"10.1234/m{idx}",
            "source_fact": {
                "canonical_phrase": f"melatonin aging finding {idx}",
                "population": "adults",
                "intervention": "melatonin",
                "endpoint": "aging biology",
            },
        }
        for idx in range(4)
    ]
    refresh_calls: list[dict[str, Any]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        refresh_calls.append(kwargs)
        return {"ok": True, "ran_topics": kwargs.get("priority_topics") or []}

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-45-00Z",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        source_paper_fetcher=lambda *_args, **_kwargs: thin_papers,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert refresh_calls
    assert ledger["refresh_batches"][0].get("note") != (
        "skipped_source_literature_candidate_available"
    )
    assert ledger["source_literature_fallback"]["reason"] == "source_floor_below_min"


def test_source_literature_preflight_uses_default_fullraw_supply_before_refresh(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "cellular_reprogramming_safety",
            "paper_count": 10,
            "fact_source_count": 10,
        }],
    })
    refresh_calls: list[dict[str, Any]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        refresh_calls.append(kwargs)
        return {"ok": True, "ran_topics": []}

    titles = [
        "Cellular reprogramming safety in aging tissue",
        "Partial reprogramming tumor risk and longevity",
        "Epigenetic rejuvenation safety endpoints",
        "Transient Yamanaka factor reprogramming adverse events",
        "Cellular reprogramming senescence safety review",
    ]
    papers = [
        {
            "title": title,
            "doi": f"10.1234/r{idx}",
            "source_fact": {
                "canonical_phrase": f"reprogramming safety boundary finding {idx}",
                "population": "adults",
                "intervention": "cellular reprogramming",
                "endpoint": "safety",
            },
        }
        for idx, title in enumerate(titles)
    ]

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)
    fetches: list[tuple[str, int, str]] = []

    def fetch(topic: str, limit: int, *, domain: str) -> list[dict[str, Any]]:
        fetches.append((topic, limit, domain))
        return papers

    monkeypatch.setattr(daily, "_fetch_source_literature_papers", fetch)
    assert daily._source_literature_fetch_topics(
        "cellular_reprogramming_safety_longevity_anti_aging",
    ) == [
        "cellular_reprogramming_safety_longevity_anti_aging",
        "cellular_reprogramming_aging",
    ]
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-50-00Z",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert fetches == [
        ("cellular_reprogramming_safety", 15, "longevity_research"),
    ]
    assert not refresh_calls
    assert ledger["source_literature_preflight_attempts"] == [{
        "topic": "cellular_reprogramming_safety",
        "status": "selected",
        "reason": "ok",
        "paper_count": 5,
        "relevant_paper_count": 5,
    }]
    assert ledger["refresh_batches"][0]["note"] == (
        "skipped_source_literature_candidate_available"
    )
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "cellular_reprogramming_safety"


def test_source_literature_reuses_discovery_source_papers_before_refetch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    papers = [
        {
            "title": title,
            "doi": f"10.1234/reuse-{idx}",
            "source_fact": {
                "canonical_phrase": f"reprogramming safety source finding {idx}",
                "population": "adults",
                "intervention": "cellular reprogramming",
                "endpoint": "safety",
            },
        }
        for idx, title in enumerate((
            "Cellular reprogramming safety in aging tissue",
            "Partial reprogramming tumor risk and longevity",
            "Epigenetic rejuvenation safety endpoints",
            "Transient Yamanaka factor reprogramming adverse events",
            "Cellular reprogramming senescence safety review",
        ))
    ]
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "cellular_reprogramming_safety",
            "paper_count": 5,
            "fact_source_count": 5,
            "source_papers": papers,
        }],
    })
    monkeypatch.setattr(
        daily, "_fetch_source_literature_papers",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("refetched")),
    )

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-50-30Z",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "cellular_reprogramming_safety"
    assert ledger["source_literature_preflight_attempts"][0]["paper_count"] == 5


def test_source_literature_reuses_fullraw_metadata_papers_as_fact_backed(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    papers = [
        {"title": title, "doi": f"10.1234/acarbose-fullraw-{idx}"}
        for idx, title in enumerate((
            "Acarbose mice longevity inflammatory markers",
            "Acarbose mice longevity inflammatory markers",
            "Acarbose mice aging glucose homeostasis",
            "Acarbose mice lifespan intervention review",
            "Acarbose mice late life metabolic response",
            "Acarbose mice geroscience translational evidence",
        ))
    ]
    daily._write_json(root / "_topics_discovery" / "fullraw.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "acarbose",
            "paper_count": 6,
            "fact_source_count": 6,
            "source_papers": papers,
        }],
    })
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)
    monkeypatch.setattr(
        daily,
        "_fetch_source_literature_papers",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("refetched")),
    )
    seen_payload: dict[str, Any] = {}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-50-45Z",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=1,
        submit=True,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "acarbose"
    assert "Title-level source match: Acarbose" in seen_payload["markdown"]
    assert ledger["source_literature_preflight_attempts"][0]["paper_count"] == 5


def test_source_backed_literature_candidate_bypasses_broad_exhausted_parent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    ledger_dir = root / "_daily_ledger"
    ledger_dir.mkdir()
    for idx in range(daily._MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT):
        daily._write_json(ledger_dir / f"2026-06-09T18-0{idx}-00Z.json", {
            "domain": {"slug": "longevity_research"},
            "submitted": 1,
            "candidate": {
                "topic": "metformin use",
                "run_dir": f"metformin use-source-literature-2026-06-09T18-0{idx}-00Z",
            },
        })
    papers = [
        {"title": f"Metformin longevity source {idx}", "doi": f"10.1234/met-{idx}"}
        for idx in range(5)
    ]
    daily._write_json(root / "_topics_discovery" / "fullraw.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {
                "topic": "metformin use",
                "paper_count": 5,
                "fact_source_count": 5,
                "source_papers": papers,
            },
            {
                "topic": "metformin_longevity",
                "paper_count": 5,
                "fact_source_count": 5,
                "source_papers": papers,
            },
        ],
    })

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5,
    ) == ["metformin_longevity"]


def test_source_literature_candidate_papers_refetches_repeated_discovery_bundle(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    repeated = [
        {"title": f"Metformin longevity repeated title {idx % 2}", "doi": f"10.1/r{idx}"}
        for idx in range(5)
    ]
    fetched_titles = [
        "Metformin longevity AMPK geroscience signal",
        "Metformin longevity methylation aging profile",
        "Metformin longevity mortality cohort boundary",
        "Metformin longevity mitochondrial stress response",
        "Metformin longevity healthspan translational review",
    ]
    fetched = [
        {"title": title, "doi": f"10.1/f{idx}"}
        for idx, title in enumerate(fetched_titles)
    ]
    daily._write_json(root / "_topics_discovery" / "fullraw.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "metformin_longevity",
            "paper_count": 5,
            "fact_source_count": 5,
            "source_papers": repeated,
        }],
    })
    calls: list[tuple[str, int, str]] = []

    def fetch(topic: str, limit: int, *, domain: str) -> list[dict[str, Any]]:
        calls.append((topic, limit, domain))
        return fetched

    monkeypatch.setattr(daily, "_fetch_source_literature_papers", fetch)

    papers = daily._source_literature_candidate_papers(
        root, "longevity_research", "metformin_longevity", 5, 15,
    )

    assert papers == fetched
    assert calls == [("metformin_longevity", 15, "longevity_research")]
    assert daily._source_literature_boundary_quality(
        "metformin_longevity", papers, 5,
    ) == (True, "ok")


def test_source_literature_preflight_uses_single_current_candidate_window(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    limits: list[int] = []

    class StopAfterPreflight(Exception):
        pass

    def candidates(*_args: Any, limit: int, **_kwargs: Any) -> list[str]:
        limits.append(limit)
        raise StopAfterPreflight

    monkeypatch.setattr(daily, "_source_literature_topic_candidates", candidates)

    with raises(StopAfterPreflight):
        daily.run_cycle(
            runs_root=root,
            date="2026-06-09T18-51-00Z",
            domain="longevity_research",
            refresh_candidates=True,
            submit=True,
            submitter=lambda _payload: {"ok": False, "status": 500},
            fetcher=lambda _doi: {"message": {}},
            sleep=lambda _seconds: None,
        )

    assert limits == [1]


def test_metadata_only_source_literature_does_not_stop_fullraw_refresh(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "cellular_reprogramming_safety", "paper_count": 10, "fact_source_count": 10},
            {"topic": "vitamin_k2_vascular_aging", "paper_count": 9, "fact_source_count": 9},
            {"topic": "physical_activity", "paper_count": 8, "fact_source_count": 8},
        ],
    })
    calls: list[tuple[str, ...]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        priorities = tuple(kwargs.get("priority_topics") or ())
        calls.append(priorities)
        return {
            "ok": True,
            "ran_topics": list(priorities[:1]),
            "top": 1,
            "warm_backlog": False,
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)
    monkeypatch.setattr(daily, "_fetch_source_literature_papers", lambda *_a, **_k: [])

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-55-00Z",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=3,
        refresh_top=3,
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 200, "response": {}},
        queue_builder=lambda _root, _include_archive: _queue(),
    )

    priority_calls = [call for call in calls if call]
    assert len(priority_calls) >= 2
    assert priority_calls[0][0] == "cellular_reprogramming_safety"
    assert priority_calls[1][0] == "vitamin_k2_vascular_aging"
    assert ledger.get("refresh_early_exit", {}).get("reason") != (
        "source_literature_candidate_available"
    )


def test_source_literature_fallback_tries_fresh_topic_before_repair(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    ledger_dir = root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    old_run = root / "metformin use-source-literature-2026-06-09T18-00-00Z"
    old_run.mkdir()
    old_run.joinpath("source_literature_memo.md").write_text(
        "# Source literature boundary memo\n", encoding="utf-8",
    )
    old_ledger = {
        "domain": {"slug": "longevity_research"},
        "submitted": 1,
        "candidate": {
            "topic": "metformin use",
            "run_dir": old_run.name,
            "fingerprint": "old-fingerprint",
        },
        "researka_decision": {
            "decision": "revise",
            "required_revisions": ["required revision"],
        },
    }
    daily._write_json(ledger_dir / "2026-06-09T18-00-00Z.json", old_ledger)
    (root / "_topics_discovery").mkdir()
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "acarbose", "paper_count": 10, "fact_source_count": 10}],
    })
    repair_papers: list[dict[str, Any]] = []
    for idx, title in enumerate((
        "Metformin exposure and sepsis mortality",
        "Metformin use and neurodegenerative disease incidence",
        "Metformin therapy and hepatocellular carcinoma risk",
        "Metformin safety and cardiovascular outcomes",
        "Metformin prevention in type 2 diabetes risk",
    )):
        phrase = (
            "metformin was associated with lower mortality"
            if idx in {0, 2, 3} else
            "no significant effect was found with metformin exposure"
        )
        repair_papers.append({
            "title": title,
            "doi": f"10.1234/met{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": phrase,
                "population": "adults",
                "intervention": "metformin",
                "comparator": "control",
            },
        })
    repair_papers.insert(3, {
        "title": "Diabetes mortality patterns in national cohorts",
        "doi": "10.1234/background",
        "year": 2023,
        "source_fact": {
            "canonical_phrase": "diabetes mortality hazard ratio",
            "population": "adults",
            "intervention": "diabetes mellitus status",
            "comparator": "nondiabetic individuals",
        },
    })
    repair_papers.insert(4, {
        "title": "Metformin incomplete effect estimate",
        "doi": "10.1234/truncated",
        "year": 2024,
        "source_fact": {
            "canonical_phrase": "metformin effect was RR 1.11 (95% CI 0.41 to 3.01",
            "population": "adults",
            "intervention": "metformin",
            "comparator": "control",
        },
    })
    fresh_papers = [
        {
            "title": title,
            "doi": f"10.1234/acarbose-{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": "acarbose shifted an aging endpoint",
                "population": "mice",
                "intervention": "acarbose",
                "endpoint": "aging endpoint",
            },
        }
        for idx, title in enumerate((
            "Acarbose mouse lifespan and metabolic aging",
            "Acarbose murine glucose homeostasis response",
            "Acarbose mouse microbiome longevity signal",
            "Acarbose murine inflammation aging marker",
            "Acarbose mouse healthspan intervention study",
        ))
    ]
    seen_payload: dict[str, Any] = {}

    def source_papers(topic: str, _limit: int) -> list[dict[str, Any]]:
        if topic == "acarbose":
            return fresh_papers
        if topic == "metformin use":
            raise AssertionError("stale repair should not run before fresh source-lit candidate")
        return repair_papers

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-10T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=source_papers,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "acarbose"
    assert "repair_submission" not in ledger["source_literature_fallback"]
    assert seen_payload["topic"] == "acarbose"
    assert (root / "acarbose-source-literature-2026-06-10T18-00-00Z").exists()


def test_repairable_source_literature_revise_runs_after_refresh(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    ledger_dir = root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    old_run = root / "metformin use-source-literature-2026-06-09T18-00-00Z"
    old_run.mkdir()
    old_run.joinpath("source_literature_memo.md").write_text(
        "# Source literature boundary memo\n", encoding="utf-8",
    )
    daily._write_json(ledger_dir / "2026-06-09T18-00-00Z.json", {
        "domain": {"slug": "longevity_research"},
        "submitted": 1,
        "candidate": {
            "topic": "metformin use",
            "run_dir": old_run.name,
            "fingerprint": "old-fingerprint",
        },
        "researka_decision": {
            "decision": "revise",
            "required_revisions": ["repair before broad refresh"],
        },
    })
    titles = [
        "Metformin use and frailty outcomes",
        "Metformin exposure in dementia cohorts",
        "Metformin treatment and cardiovascular mortality",
        "Metformin prevention signals in diabetes risk",
        "Metformin therapy and inflammatory biomarkers",
    ]
    papers = [
        {
            "title": title,
            "doi": f"10.1234/met-refresh-{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": "metformin use showed mixed endpoint signals",
                "population": "adults",
                "intervention": "metformin",
                "comparator": "control",
                "endpoint": "mortality",
            },
        }
        for idx, title in enumerate(titles)
    ]
    seen_payload: dict[str, Any] = {}

    refresh_calls: list[dict[str, Any]] = []

    def refresh(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        refresh_calls.append(kwargs)
        return {"ok": True, "ran_topics": []}

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh)

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-10T19-00-00Z",
        domain="longevity_research",
        refresh_candidates=True,
        max_refresh_batches=1,
        queue=None,
        submit=True,
        source_paper_fetcher=lambda topic, _limit: papers if topic == "metformin use" else [],
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert refresh_calls
    assert ledger["source_literature_fallback"]["repair_submission"] is True
    assert ledger["submitted_topic"] == "metformin use"
    assert "repair before broad refresh" not in seen_payload["markdown"]
    assert (
        seen_payload["metadata"]["reviewer_repair_notes"]
        == "repair before broad refresh"
    )


def _usable_boundary_papers() -> list[dict[str, str]]:
    return [
        {"title": "Usable boundary signaling in aging metabolism", "doi": "10.1234/u0"},
        {"title": "Boundary markers for usable inflammation evidence", "doi": "10.1234/u1"},
        {
            "title": "Usable lifespan boundary conditions in mitochondrial stress",
            "doi": "10.1234/u2",
        },
        {
            "title": "Proteostasis evidence for a usable intervention boundary",
            "doi": "10.1234/u3",
        },
        {
            "title": "Cellular senescence and usable translational boundaries",
            "doi": "10.1234/u4",
        },
    ]


def test_published_source_literature_topic_is_not_repaired_again(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    ledger_dir = root / "_daily_ledger"
    old_run = root / "mtor-source-literature-2026-06-09T18-00-00Z"
    old_run.mkdir(parents=True)
    old_run.joinpath("source_literature_memo.md").write_text("# Source\n", encoding="utf-8")
    daily._write_json(ledger_dir / "2026-06-09T18-00-00Z.json", {
        "domain": {"slug": "longevity_research"},
        "submitted": 1,
        "candidate": {"topic": "mtor", "run_dir": old_run.name, "fingerprint": "old"},
        "researka_decision": {
            "decision": "revise",
            "required_revisions": ["required revision"],
        },
    })
    daily._write_json(ledger_dir / "2026-06-10T18-00-00Z.json", {
        "domain": {"slug": "longevity_research"},
        "submitted": 1,
        "published": 1,
        "final_verdict": "accepted",
        "candidate": {"topic": "mtor", "run_dir": old_run.name, "fingerprint": "new"},
    })
    (root / "_topics_discovery").mkdir()
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "usable_boundary", "paper_count": 9, "fact_source_count": 9}],
    })
    papers = _usable_boundary_papers()
    seen_topics: list[str] = []

    def fetch(topic: str, _limit: int) -> list[dict[str, Any]]:
        seen_topics.append(topic)
        if topic == "mtor":
            raise AssertionError("published source-literature topic should be blocked")
        return papers

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-11T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=fetch,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert seen_topics == ["usable_boundary"]
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "usable_boundary"


def test_source_literature_fallback_records_rejected_submit_status(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "usable_boundary", "paper_count": 9, "fact_source_count": 9}],
    })
    papers = _usable_boundary_papers()

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-11T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=lambda _topic, _limit: papers,
        submitter=lambda _payload: {
            "ok": False, "status": 409, "response": "duplicate publication",
        },
        fetcher=lambda _doi: {"message": {}},
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["source_literature_fallback"] == {
        "topic": "usable_boundary",
        "status": "blocked",
        "reason": "rejected_duplicate",
        "paper_count": 5,
        "relevant_paper_count": 5,
        "submit_status": "rejected_duplicate",
    }


def test_source_literature_fallback_records_reviewer_revise_decision(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "usable_boundary", "paper_count": 9, "fact_source_count": 9}],
    })
    decision = {
        "status": "complete",
        "decision": "revise",
        "claim_support_verdict": "partially_supported",
        "required_revisions": ["tighten source-to-claim alignment"],
    }

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-11T19-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=lambda _topic, _limit: _usable_boundary_papers(),
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-revise"}},
        },
        decision_fetcher=lambda _submission_id: decision,
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "reviewer_revise"
    assert ledger["final_verdict"] == "revise"
    assert ledger["researka_decision"] == decision
    assert ledger["cycle_attempts"] == [{
        "topic": "usable_boundary",
        "run_dir": "usable_boundary-source-literature-2026-06-11T19-00-00Z",
        "fingerprint": ledger["candidate"]["fingerprint"],
        "status": "reviewer_revise",
        "researka_decision": decision,
        "public_page_check": None,
    }]


def test_source_literature_fallback_tries_next_after_reviewer_revise(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "usable_boundary", "paper_count": 9, "fact_source_count": 9},
            {"topic": "second_boundary", "paper_count": 9, "fact_source_count": 9},
        ],
    })
    submitted_topics: list[str] = []

    def papers_for(topic: str, _limit: int) -> list[dict[str, Any]]:
        stems = (
            "metabolic signal",
            "inflammation marker",
            "mitochondrial stress",
            "cellular senescence",
            "proteostasis map",
        )
        return [
            {
                "title": f"{topic.replace('_', ' ')} {stem}",
                "doi": f"10.1234/{topic}-{idx}",
                "source_fact": {
                    "canonical_phrase": f"{topic} fact-level receipt {idx}",
                    "population": f"population {idx}",
                    "intervention": topic.replace("_", " "),
                    "comparator": "control",
                },
            }
            for idx, stem in enumerate(stems)
        ]

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        topic = str(payload.get("topic") or "")
        submitted_topics.append(topic)
        return {
            "ok": True, "status": 200,
            "response": {"submission": {"id": f"sub-{topic}"}},
        }

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-11T19-30-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=papers_for,
        submitter=submitter,
        decision_fetcher=lambda submission_id: {
            "status": "complete",
            "decision": "revise" if submission_id == "sub-usable_boundary" else "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert submitted_topics == ["usable_boundary", "second_boundary"]
    assert ledger["submitted_topic"] == "second_boundary"
    assert [row["status"] for row in ledger["cycle_attempts"]] == [
        "reviewer_revise", "published",
    ]


def test_source_literature_fallback_is_disabled_without_explicit_submit_flag(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "metabolic_pathway", "paper_count": 10, "fact_source_count": 20}],
    }), encoding="utf-8")
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)

    def fail_submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("disabled source-literature fallback must not submit")

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=lambda *_args, **_kwargs: [
            {"title": title, "doi": f"10.1234/{idx}"}
            for idx, title in enumerate((
                "Metabolic pathway source in aging",
                "Inflammation signalling lifespan source",
                "Mitochondrial stress response source",
                "Cellular senescence intervention source",
                "Proteostasis decline source",
            ))
        ],
        submitter=fail_submitter,
    )

    assert ledger["status"] == "no_fresh_candidate"
    assert ledger["published"] == 0
    assert ledger["reason"] == "requires_fact_level_source_synthesis"
    assert ledger["source_literature_fallback"]["status"] == "disabled"
    assert (
        ledger["source_literature_fallback"]["reason"]
        == "requires_fact_level_source_synthesis"
    )


def test_fact_backed_source_literature_fallback_submits_without_flag(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "metabolic_pathway", "paper_count": 10, "fact_source_count": 20}],
    }), encoding="utf-8")
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)
    papers = [
        {
            "title": title,
            "doi": f"10.1234/{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": f"metabolic pathway finding {idx} for bounded synthesis",
                "population": f"population {idx}",
                "intervention": "metabolic pathway intervention",
                "comparator": "control",
            },
        }
        for idx, title in enumerate((
            "Metabolic pathway source in aging",
            "Inflammation signalling lifespan source",
            "Mitochondrial stress response source",
            "Cellular senescence intervention source",
            "Proteostasis decline source",
        ))
    ]
    seen_payload: dict[str, Any] = {}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=lambda *_args, **_kwargs: papers,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert "Metabolic pathway source in aging" in seen_payload["markdown"]
    assert "Finding: metabolic pathway finding 0 for bounded synthesis" in seen_payload["markdown"]
    assert "receipt-backed scoping note" in seen_payload["abstract"]


def test_fullraw_metadata_source_literature_fallback_submits_without_flag(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "acarbose", "paper_count": 8, "fact_source_count": 5}],
    }), encoding="utf-8")
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "",
        "researka_database_token": "",
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())
    monkeypatch.setattr(publish_literature, "_fullraw_topic_papers", lambda *_args: [
        {"doi": "10.1/a", "title": "Acarbose mice longevity inflammatory markers"},
        {"doi": "10.1/b", "title": "Acarbose mice aging glucose homeostasis"},
        {"doi": "10.1/c", "title": "Acarbose mice lifespan intervention review"},
        {"doi": "10.1/d", "title": "Acarbose mice late life metabolic response"},
        {"doi": "10.1/e", "title": "Acarbose mice geroscience translational evidence"},
    ])
    seen_payload: dict[str, Any] = {}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {"ok": True, "status": 200, "response": {"submission": {"id": "sub-1"}}}
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "acarbose"
    assert ledger["source_literature_fallback"]["status"] == "selected"
    assert "Title-level source match: Acarbose" in seen_payload["markdown"]
    assert "source-level receipts" in seen_payload["markdown"]


def test_source_literature_fallback_ignores_stale_source_floor_block(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    daily._write_json(root / "_daily_ledger" / "2026-06-10T00-00-00Z.json", {
        "domain": {"slug": "longevity_research"},
        "source_floor_refresh_topics": ["source_rich_parent"],
    })
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "source_rich_parent", "paper_count": 9, "fact_source_count": 9}],
    })
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)
    papers = [
        {
            "title": f"Source rich parent {stem}",
            "doi": f"10.1234/source-rich-{idx}",
            "source_fact": {
                "canonical_phrase": f"source-rich fact {idx}",
                "population": f"population {idx}",
                "intervention": "source rich parent",
                "comparator": "control",
            },
        }
        for idx, stem in enumerate((
            "metabolic signal", "inflammation marker", "mitochondrial stress",
            "cellular senescence", "proteostasis map",
        ))
    ]

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-11T20-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=lambda *_args, **_kwargs: papers,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-source-rich"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-rich"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["recent_source_floor_topics_blocked"] == ["source_rich_parent"]
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "source_rich_parent"


def test_source_literature_candidates_use_latest_domain_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    older = discovery / "older.json"
    older.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "stale_high_count", "paper_count": 50, "fact_source_count": 50}],
    }), encoding="utf-8")
    newer = discovery / "newer.json"
    newer.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "current_parent", "paper_count": 6, "fact_source_count": 6}],
    }), encoding="utf-8")
    os.utime(newer, (time.time() + 5, time.time() + 5))

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=1,
    ) == ["current_parent"]


def test_source_literature_candidates_skip_domain_only_placeholder(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "longevity_anti_aging", "paper_count": 6, "fact_source_count": 6},
            {"topic": "metformin_longevity", "paper_count": 5, "fact_source_count": 5},
        ],
    }), encoding="utf-8")

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=1,
    ) == ["metformin_longevity"]


def test_source_literature_candidates_fill_from_older_snapshots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    older = discovery / "older.json"
    older.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "older_source_rich", "paper_count": 50, "fact_source_count": 50}],
    }), encoding="utf-8")
    newer = discovery / "newer.json"
    newer.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "current_parent", "paper_count": 6, "fact_source_count": 6}],
    }), encoding="utf-8")
    os.utime(older, (100.0, 100.0))
    os.utime(newer, (200.0, 200.0))

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=2,
    ) == ["current_parent", "older_source_rich"]


def test_source_literature_candidates_require_domain_seed_scope(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "anti_tumor", "paper_count": 25, "fact_source_count": 25},
            {"topic": "caloric_restriction", "paper_count": 7, "fact_source_count": 7},
        ],
    }), encoding="utf-8")

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=3,
    ) == ["caloric_restriction"]


def test_source_literature_candidates_skip_generic_fragments(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "low_dose", "paper_count": 30, "fact_source_count": 30},
            {"topic": "age_related", "paper_count": 29, "fact_source_count": 29},
            {"topic": "anti_aging", "paper_count": 28, "fact_source_count": 28},
            {"topic": "low_dose_lithium", "paper_count": 6, "fact_source_count": 6},
        ],
    })

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=5,
    ) == ["low_dose_lithium"]


def test_source_literature_candidates_require_fact_source_floor(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", raising=False)
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "paper_rich_fact_thin", "paper_count": 20, "fact_source_count": 1},
            {"topic": "source_rich_parent", "paper_count": 6, "fact_source_count": 6},
        ],
    })

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=5,
    ) == ["source_rich_parent"]


def test_source_literature_candidates_use_domain_queue_not_ready_topics(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_publish_queue.business_research.json", {
        "not_ready": [
            {
                "topic": "business_model_performance",
                "domain_slug": "business_research",
                "queue_status": "no_source_diverse_bundle",
            },
            {
                "topic": "employee_engagement_turnover",
                "domain_slug": "management_research",
                "queue_status": "no_source_diverse_bundle",
            },
        ],
    })

    assert daily._source_literature_topic_candidates(
        root, "business_research", 5, limit=3,
    ) == ["business_model_performance"]


def test_source_literature_fullraw_fetch_uses_separate_query_budget(
    monkeypatch: MonkeyPatch,
) -> None:
    from scripts import run_topic_discovery

    seen: dict[str, str | None] = {}

    def fake_seed_fullraw_papers(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        for key in (
            "TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS",
            "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS",
            "TOPIC_DISCOVERY_SEED_PAPER_TIMEOUT_SECONDS",
            "TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS",
            "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
            "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS",
            "TOPIC_DISCOVERY_V5_MAX_VARIANTS",
            "TOPIC_DISCOVERY_V5_MIN_SHARDS_SEARCHED",
            "TOPIC_DISCOVERY_V5_MIN_SOURCES_SEARCHED",
        ):
            seen[key] = os.environ.get(key)
        return []

    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FULLRAW_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FULLRAW_BUDGET_SECONDS", "88")
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FULLRAW_SWEEP_WAIT_SECONDS", "9")
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FULLRAW_MAX_VARIANTS", "3")
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FULLRAW_MIN_SHARDS_SEARCHED", "25")
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FULLRAW_MIN_SOURCES_SEARCHED", "2")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", "45")
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_seed_fullraw_papers)

    assert publish_literature._fullraw_topic_papers("plant based diet", 5) == []
    assert seen == {
        "TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS": "7",
        "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS": "7",
        "TOPIC_DISCOVERY_SEED_PAPER_TIMEOUT_SECONDS": "7",
        "TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS": "88",
        "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS": "88",
        "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS": "9",
        "TOPIC_DISCOVERY_V5_MAX_VARIANTS": "3",
        "TOPIC_DISCOVERY_V5_MIN_SHARDS_SEARCHED": "25",
        "TOPIC_DISCOVERY_V5_MIN_SOURCES_SEARCHED": "2",
    }
    assert os.environ["TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS"] == "99"
    assert os.environ["TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"] == "45"


def test_source_literature_fullraw_fetch_defaults_to_supply_bounds(
    monkeypatch: MonkeyPatch,
) -> None:
    from scripts import run_topic_discovery

    seen: dict[str, str | None] = {}

    def fake_seed_fullraw_papers(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        for key in (
            "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS",
            "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
            "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS",
            "TOPIC_DISCOVERY_V5_MAX_VARIANTS",
            "TOPIC_DISCOVERY_V5_MIN_SHARDS_SEARCHED",
            "TOPIC_DISCOVERY_V5_MIN_SOURCES_SEARCHED",
        ):
            seen[key] = os.environ.get(key)
        return []

    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "120")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "300")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS", "120")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_MAX_VARIANTS", "4")
    monkeypatch.setattr(run_topic_discovery, "_seed_fullraw_papers", fake_seed_fullraw_papers)

    assert publish_literature._fullraw_topic_papers("plant based diet", 5) == []
    assert seen == {
        "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS": "35",
        "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS": "45",
        "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS": "15",
        "TOPIC_DISCOVERY_V5_MAX_VARIANTS": "2",
        "TOPIC_DISCOVERY_V5_MIN_SHARDS_SEARCHED": "1",
        "TOPIC_DISCOVERY_V5_MIN_SOURCES_SEARCHED": "1",
    }


def test_source_literature_candidates_skip_exhausted_topic_family(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "metformin use", "paper_count": 12, "fact_source_count": 12},
            {"topic": "metformin treatment", "paper_count": 11, "fact_source_count": 11},
            {"topic": "acarbose", "paper_count": 8, "fact_source_count": 8},
        ],
    })
    for idx in range(daily._MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT):
        daily._write_json(root / "_daily_ledger" / f"2026-06-0{idx + 1}T00-00-00Z.json", {
            "domain": {"slug": "longevity_research"},
            "submitted": 1,
            "candidate": {
                "topic": "metformin use",
                "run_dir": f"runs/metformin use-source-literature-2026-06-0{idx + 1}",
            },
        })

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, limit=3,
    ) == ["acarbose"]


def test_source_literature_negative_parent_allows_domain_child(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "cellular_reprogramming_aging",
            "paper_count": 8,
            "fact_source_count": 8,
        }],
    })

    assert daily._source_literature_topic_candidates(
        root,
        "longevity_research",
        5,
        {"cellular_reprogramming"},
        limit=3,
        soft_broad_blocked_topics={"cellular_reprogramming"},
    ) == ["cellular_reprogramming_aging"]
    assert daily._source_literature_family_blocked_topic(
        "cellular_reprogramming",
        {"cellular_reprogramming"},
        soft_broad_blocked_topics={"cellular_reprogramming"},
    )


def test_source_literature_strict_parent_blocks_domain_child(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    discovery = root / "_topics_discovery"
    discovery.mkdir(parents=True)
    daily._write_json(discovery / "latest.json", {
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "cellular_reprogramming_aging",
            "paper_count": 8,
            "fact_source_count": 8,
        }],
    })

    assert daily._source_literature_topic_candidates(
        root, "longevity_research", 5, {"cellular_reprogramming"}, limit=3,
    ) == []


def test_source_literature_fallback_tries_next_quality_candidate(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "title_series", "paper_count": 10, "fact_source_count": 10},
            {"topic": "usable_boundary", "paper_count": 9, "fact_source_count": 9},
        ],
    }), encoding="utf-8")
    repeated = [
        {"title": f"Annual report {year}", "doi": f"10.1234/{year}"}
        for year in range(2020, 2025)
    ]
    usable = [
        {"title": "Metabolic pathway review in aging", "doi": "10.1234/1"},
        {"title": "Inflammation signalling across lifespan", "doi": "10.1234/2"},
        {"title": "Mitochondrial stress response biology", "doi": "10.1234/3"},
        {"title": "Cellular senescence intervention map", "doi": "10.1234/4"},
        {"title": "Proteostasis mechanisms in age-related decline", "doi": "10.1234/5"},
    ]
    monkeypatch.setattr(
        daily,
        "_fetch_source_literature_papers",
        lambda topic, *_args, **_kwargs: repeated if topic == "title_series" else usable,
    )
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert [a["status"] for a in ledger["source_literature_fallback_attempts"]] == [
        "blocked", "selected",
    ]
    assert ledger["submitted_topic"] == "usable_boundary"


def test_source_literature_fallback_overfetches_for_coherent_subset(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "acarbose", "paper_count": 15, "fact_source_count": 15}],
    }), encoding="utf-8")
    limits: list[int] = []

    def fetcher(_topic: str, limit: int, **_kwargs: Any) -> list[dict[str, Any]]:
        limits.append(limit)
        human_titles = (
            "Acarbose human observational aging signal",
            "Acarbose human diabetes cohort marker",
        )
        mouse_titles = (
            "Acarbose mouse lifespan and metabolic aging",
            "Acarbose murine glucose homeostasis response",
            "Acarbose mouse microbiome longevity signal",
            "Acarbose murine inflammation aging marker",
            "Acarbose mouse healthspan intervention study",
        )
        human = [
            {
                "title": title,
                "doi": f"10.1234/acarbose-human-{idx}",
                "source_fact": {
                    "canonical_phrase": "acarbose was associated with an aging marker",
                    "population": "adult human cohort",
                    "intervention": "acarbose",
                    "endpoint": "aging marker",
                },
            }
            for idx, title in enumerate(human_titles)
        ]
        mouse = [
            {
                "title": title,
                "doi": f"10.1234/acarbose-mouse-{idx}",
                "source_fact": {
                    "canonical_phrase": "acarbose changed an aging endpoint",
                    "population": "mice",
                    "intervention": "acarbose",
                    "endpoint": "aging endpoint",
                },
            }
            for idx, title in enumerate(mouse_titles)
        ]
        return human + mouse

    monkeypatch.setattr(daily, "_fetch_source_literature_papers", fetcher)
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())
    seen_payload: dict[str, Any] = {}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-05-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda payload: (
            seen_payload.update(payload)
            or {
                "ok": True, "status": 200,
                "response": {"submission": {"id": "sub-1"}},
            }
        ),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert limits == [15]
    assert "adult human cohort" not in seen_payload["markdown"]
    assert "mice" in seen_payload["markdown"]


def test_source_literature_fallback_scans_past_first_five_thin_rows(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    topics = [f"thin_{idx}" for idx in range(5)] + ["usable_boundary"]
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": topic, "paper_count": 10, "fact_source_count": 10}
            for topic in topics
        ],
    }), encoding="utf-8")
    thin = [
        {
            "title": f"Thin source {idx}",
            "doi": f"10.1234/thin-{idx}",
            "source_fact": {
                "canonical_phrase": f"thin finding {idx}",
                "intervention": "thin topic",
            },
        }
        for idx in range(4)
    ]
    usable_titles = (
        "Usable boundary mitochondrial aging signal",
        "Inflammation pathway source for usable boundary",
        "Cellular senescence intervention boundary",
        "Proteostasis response in aging tissue",
        "Metabolic stress adaptation and lifespan",
    )
    usable = [
        {
            "title": title,
            "doi": f"10.1234/use-{idx}",
            "source_fact": {
                "canonical_phrase": f"usable boundary finding {idx}",
                "intervention": "usable boundary",
            },
        }
        for idx, title in enumerate(usable_titles)
    ]
    def fetch_source_papers(topic: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return usable if topic == "usable_boundary" else thin

    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-10-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        source_paper_fetcher=fetch_source_papers,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "usable_boundary"
    assert [a["status"] for a in ledger["source_literature_fallback_attempts"]] == [
        "blocked", "blocked", "blocked", "blocked", "blocked", "selected",
    ]


def test_source_literature_fallback_caps_default_live_fetch_window(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    ledger_dir = root / "_daily_ledger"
    ledger_dir.mkdir()
    old_run = root / "repair_topic-source-literature-2026-06-09T17-00-00Z"
    old_run.mkdir()
    old_run.joinpath("source_literature_memo.md").write_text("# Source\n", encoding="utf-8")
    daily._write_json(ledger_dir / "2026-06-09T17-00-00Z.json", {
        "domain": {"slug": "longevity_research"},
        "submitted": 1,
        "candidate": {"topic": "repair_topic", "run_dir": old_run.name},
        "researka_decision": {"decision": "revise"},
    })
    daily._write_json(root / "_topics_discovery" / "longevity.json", {
        "domain": {"slug": "longevity_research"},
        "all": [
            {
                "topic": f"candidate_{idx}",
                "paper_count": 10,
                "fact_source_count": 10,
            }
            for idx in range(6)
        ],
    })
    fetches: list[str] = []

    def fetch(topic: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        fetches.append(topic)
        return []

    monkeypatch.setattr(daily, "_fetch_source_literature_papers", fetch)
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda _payload: {"ok": False, "status": 500},
        sleep=lambda _seconds: None,
    )

    assert fetches == ["candidate_0", "candidate_1", "candidate_2", "candidate_3"]
    assert len(ledger["source_literature_fallback_attempts"]) == 4
    assert "repair_topic" not in fetches
    assert ledger["status"] == "no_fresh_candidate"


def test_source_literature_fallback_skips_misaligned_candidate(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT", "1")
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "ACE_inhibitors_aging", "paper_count": 10, "fact_source_count": 10},
            {"topic": "metformin", "paper_count": 9, "fact_source_count": 9},
        ],
    }), encoding="utf-8")
    misaligned = [
        {
            "title": title,
            "doi": f"10.1234/mis-{i}",
            "source_fact": {
                "canonical_phrase": "reported a directional association",
                "intervention": "SGLT2 inhibitors",
                "endpoint": "cardiovascular outcome",
            },
        }
        for i, title in enumerate((
            "SGLT2 inhibitors and cardiovascular outcomes",
            "Proteasome inhibitors and cardiac toxicity",
            "SGLT2 inhibitors in fatty liver disease",
            "SGLT2 inhibitors in acute heart failure",
            "Empagliflozin cardiovascular outcome trial",
        ), start=1)
    ]
    aligned = [
        {
            "title": title,
            "doi": f"10.1234/met-{i}",
            "source_fact": {
                "canonical_phrase": "reported a metformin-associated signal",
                "intervention": "metformin",
                "endpoint": "aging-related endpoint",
            },
        }
        for i, title in enumerate((
            "Metformin mitochondrial aging biology",
            "Metformin insulin signaling and lifespan",
            "Metformin inflammation and age-related disease",
            "Metformin AMPK response in aging tissue",
            "Metformin geroscience trial boundary",
        ), start=1)
    ]
    monkeypatch.setattr(
        daily,
        "_fetch_source_literature_papers",
        lambda topic, *_args, **_kwargs: misaligned
        if topic == "ACE_inhibitors_aging" else aligned,
    )
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    attempts = ledger["source_literature_fallback_attempts"]
    assert [(a["topic"], a["status"]) for a in attempts] == [
        ("ACE_inhibitors_aging", "blocked"),
        ("metformin", "selected"),
    ]
    assert attempts[0]["paper_count"] == 5
    assert attempts[0]["relevant_paper_count"] == 0
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "metformin"


def test_source_literature_fetcher_prefers_tier2_fact_backed_papers(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK", "0")
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "https://db.test",
        "researka_database_token": "tok",
    })())
    calls: list[str] = []
    timeouts: list[float] = []

    class Response:
        status = 200

        def __init__(self, payload: Any) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(req: Any, timeout: int) -> Response:
        url = str(req.full_url)
        calls.append(url)
        timeouts.append(timeout)
        return Response([
            {
                "paper_id": "p1",
                "paper": {"doi": "10.1/a", "title": "Acarbose lifespan trial"},
                "canonical_phrase": "Acarbose increased lifespan in mice.",
                "population": "mice",
                "intervention": "acarbose",
            },
            {
                "paper_id": "p2",
                "paper": {"doi": "10.1/b", "title": "Acarbose microbiome study"},
                "canonical_phrase": "Acarbose changed gut microbiome structure.",
                "population": "mice",
                "intervention": "acarbose",
            },
        ])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    papers = daily._fetch_source_literature_papers(
        "acarbose", 5, domain="longevity_research",
    )

    assert [p["doi"] for p in papers] == ["10.1/a", "10.1/b"]
    assert papers[0]["source_fact"]["canonical_phrase"] == "Acarbose increased lifespan in mice."
    assert calls == ["https://db.test/api/v1/tier2/facts/search"]
    assert timeouts == [12.0]


def test_source_literature_fetcher_supplements_thin_fact_search_with_fullraw(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "https://db.test",
        "researka_database_token": "tok",
    })())

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps([
                {
                    "paper_id": f"pa-{idx}",
                    "paper": {
                        "doi": f"10.1/acarbose-fact-{idx}",
                        "title": (
                            "Acarbose aging lifespan trial"
                            if idx == 0 else
                            "Acarbose microbiome aging mouse study"
                        ),
                    },
                    "canonical_phrase": "Acarbose changed an aging endpoint.",
                    "population": "mice",
                    "intervention": "acarbose",
                }
                for idx in range(2)
            ]).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: Response())
    monkeypatch.setattr(
        publish_literature,
        "_fullraw_topic_papers",
        lambda _query, _limit: [
            {
                "doi": "10.1/acarbose-fullraw-0",
                "title": "Acarbose mice longevity inflammatory markers",
            },
            {
                "doi": "10.1/acarbose-fullraw-1",
                "title": "Acarbose mice aging glucose homeostasis",
            },
            {
                "doi": "10.1/acarbose-fullraw-2",
                "title": "Acarbose mice lifespan intervention review",
            },
            {
                "doi": "10.1/acarbose-fullraw-3",
                "title": "Acarbose mice late life metabolic response",
            },
            {
                "doi": "10.1/acarbose-fullraw-4",
                "title": "Acarbose mice geroscience translational evidence",
            },
        ],
    )

    papers = daily._fetch_source_literature_papers(
        "acarbose", 5, domain="longevity_research",
    )

    assert [p["doi"] for p in papers] == [
        "10.1/acarbose-fact-0",
        "10.1/acarbose-fact-1",
        "10.1/acarbose-fullraw-0",
        "10.1/acarbose-fullraw-1",
        "10.1/acarbose-fullraw-2",
    ]
    assert "source_fact" in papers[0]
    assert papers[-1]["source_fact"]["source_tier"] == "paper_metadata"
    assert "Title-level source match: Acarbose" in papers[-1]["source_fact"]["canonical_phrase"]
    assert daily._source_literature_fact_count(papers) == 5
    assert daily._source_literature_boundary_quality("acarbose", papers, 5) == (True, "ok")


def test_source_literature_fetcher_tries_fullraw_query_variants(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "",
        "researka_database_token": "",
    })())
    queries: list[str] = []

    def fullraw(query: str, _limit: int) -> list[dict[str, Any]]:
        queries.append(query)
        titles = (
            [
                "Deuterium depleted water adaptation source",
                "Deuterium depleted water isotope regulation",
            ] if query == "deuterium depleted water" else [
                "Deuterium depleted water aging mouse intervention source",
                "Deuterium depleted water aging mice oxidative stress",
                "Deuterium depleted water aging rat physiology",
                "Deuterium depleted water aging animal survival",
                "Deuterium depleted water aging murine adaptation",
            ]
        )
        return [{"doi": f"10.1/ddw-{idx}-{len(queries)}", "title": title}
                for idx, title in enumerate(titles)]

    monkeypatch.setattr(publish_literature, "_fullraw_topic_papers", fullraw)

    papers = daily._fetch_source_literature_papers(
        "deuterium_depleted_water_aging", 5, domain="longevity_research",
    )

    assert queries[:2] == ["deuterium depleted water", "deuterium depleted water aging"]
    assert len(papers) == 5
    assert daily._source_literature_fact_count(papers) == 5
    assert daily._source_literature_boundary_quality(
        "deuterium_depleted_water_aging", papers, 5,
    ) == (True, "ok")


def test_source_literature_query_variants_include_two_token_windows() -> None:
    variants = publish_literature.query_variants("business_model_performance")

    assert "business model" in variants
    assert "model performance" in variants


def test_fullraw_metadata_relevance_requires_title_context(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "",
        "researka_database_token": "",
    })())
    monkeypatch.setattr(publish_literature, "_fullraw_topic_papers", lambda *_args: [
        {"doi": "10.1/a", "title": "Deuterium depleted water chromium intoxicated rats"},
        {"doi": "10.1/b", "title": "Deuterium depleted water hepatic oxidative injury"},
        {"doi": "10.1/c", "title": "Deuterium depleted water reproductive physiology"},
        {"doi": "10.1/d", "title": "Deuterium depleted water cultured cell growth"},
        {"doi": "10.1/e", "title": "Deuterium depleted water isotope regulation"},
    ])

    papers = daily._fetch_source_literature_papers(
        "deuterium_depleted_water_longevity_anti_aging", 5,
        domain="longevity_research",
    )

    assert papers == []


def test_default_source_literature_fallback_tries_core_topic_after_modifier_slug(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "cellular_reprogramming_safety_longevity_anti_aging",
            "paper_count": 20,
            "fact_source_count": 20,
        }],
    }), encoding="utf-8")
    daily._write_json(root / "_daily_ledger" / "2026-06-08.json", {
        "domain": {"slug": "longevity_research"},
        "final_verdict": "rejected",
        "submitted_topic": "cellular_reprogramming",
        "researka_decision": {
            "status": "complete",
            "decision": "reject",
            "claim_support_verdict": "unsupported",
        },
    })
    daily._write_json(root / "_daily_ledger" / "_submitted_fingerprints.json", [{
        "date": "2026-06-08T09-30-00Z",
        "domain": {"slug": "longevity_research"},
        "topic": "cellular_reprogramming",
        "run_dir": "runs/cellular_reprogramming-source-literature-2026-06-08",
        "fingerprint": "broad-old",
    }])
    thin = [
        {"title": f"Cellular reprogramming safety paper {idx}", "doi": f"10.1/thin-{idx}"}
        for idx in range(4)
    ]
    core_titles = (
        "Cellular reprogramming aging tissue repair",
        "Cellular reprogramming epigenetic aging reset",
        "Cellular reprogramming senescence aging reversal",
        "Cellular reprogramming rejuvenation aging biology",
        "Cellular reprogramming aging safety review",
    )
    core = [
        {
            "title": title,
            "doi": f"10.1/core-{idx}",
            "source_fact": {
                "canonical_phrase": "cellular reprogramming changed an aging endpoint",
                "intervention": "cellular reprogramming",
                "endpoint": "aging endpoint",
            },
        }
        for idx, title in enumerate(core_titles)
    ]
    fetches: list[str] = []
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    def fetch(topic: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        fetches.append(topic)
        return core if topic == "cellular_reprogramming_aging" else thin

    monkeypatch.setattr(daily, "_fetch_source_literature_papers", fetch)
    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T18-00-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=lambda _payload: {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-1"}},
        },
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
            "publication": {"url": "https://researka.org/alpha/source-lit"},
        },
        page_fetcher=lambda _url: {"ok": True, "status": 200, "body": "<title>Source</title>"},
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert fetches[:2] == [
        "cellular_reprogramming_safety_longevity_anti_aging",
        "cellular_reprogramming_aging",
    ]
    assert [row["status"] for row in ledger["source_literature_fallback_attempts"]] == [
        "blocked", "selected",
    ]
    assert ledger["status"] == "published"
    assert ledger["submitted_topic"] == "cellular_reprogramming_aging"
    assert ledger["recent_negative_topics_blocked"] == ["cellular_reprogramming"]


def test_source_literature_fetcher_enriches_fullraw_with_matching_fact_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "https://db.test",
        "researka_database_token": "tok",
    })())
    queries: list[str] = []
    timeouts: list[float] = []
    fullraw_titles = [
        "Acarbose mice longevity inflammatory markers",
        "Acarbose mice aging glucose homeostasis",
        "Acarbose mice lifespan intervention review",
    ]

    class Response:
        status = 200

        def __init__(self, payload: list[dict[str, Any]]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fact_row(doi: str, title: str, phrase: str) -> dict[str, Any]:
        return {
            "paper_id": doi,
            "paper": {"doi": doi, "title": title},
            "canonical_phrase": phrase,
            "population": "mice",
            "intervention": "acarbose",
            "endpoint": "aging-related endpoint",
        }

    def fake_urlopen(req: Any, timeout: float) -> Response:
        query = str(json.loads(req.data.decode("utf-8"))["query"])
        queries.append(query)
        timeouts.append(timeout)
        if query == "acarbose":
            return Response([
                fact_row(
                    "10.1/acarbose-fact-0", "Acarbose aging lifespan trial",
                    "Acarbose changed lifespan in mice.",
                ),
                fact_row(
                    "10.1/acarbose-fact-1", "Acarbose microbiome aging mouse study",
                    "Acarbose changed microbiome aging markers.",
                ),
            ])
        if query in fullraw_titles:
            idx = fullraw_titles.index(query)
            return Response([fact_row(
                f"10.1/acarbose-fullraw-{idx}", query,
                f"Acarbose fullraw receipt {idx} reported an aging endpoint.",
            )])
        return Response([])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        publish_literature,
        "_fullraw_topic_papers",
        lambda _query, _limit: [
            {"doi": f"10.1/acarbose-fullraw-{idx}", "title": title}
            for idx, title in enumerate(fullraw_titles)
        ],
    )

    papers = daily._fetch_source_literature_papers(
        "acarbose", 5, domain="longevity_research",
    )

    assert [p["doi"] for p in papers] == [
        "10.1/acarbose-fact-0",
        "10.1/acarbose-fact-1",
        "10.1/acarbose-fullraw-0",
        "10.1/acarbose-fullraw-1",
        "10.1/acarbose-fullraw-2",
    ]
    assert daily._source_literature_fact_count(papers) == 5
    assert daily._source_literature_boundary_quality("acarbose", papers, 5) == (True, "ok")
    assert fullraw_titles[0] in queries
    assert timeouts[-3:] == [3.0, 3.0, 3.0]


def test_source_literature_fetcher_retries_focused_query_variant(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "https://db.test",
        "researka_database_token": "tok",
    })())
    queries: list[str] = []

    class Response:
        status = 200

        def __init__(self, payload: Any) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fact_row(index: int) -> dict[str, Any]:
        return {
            "paper_id": f"pa-{index}",
            "paper": {
                "doi": f"10.1/physical-activity-{index}",
                "title": f"Physical activity aging cohort {index}",
            },
            "canonical_phrase": "Physical activity was associated with aging-related function.",
            "population": "older adults",
            "intervention": "physical activity",
            "endpoint": "aging-related function",
        }

    def fake_urlopen(req: Any, timeout: int) -> Response:
        payload = json.loads(req.data.decode("utf-8"))
        query = str(payload["query"])
        queries.append(query)
        if query == "physical activity aging":
            return Response([fact_row(i) for i in range(5)])
        return Response([fact_row(i) for i in range(2)])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    papers = daily._fetch_source_literature_papers(
        "physical_activity_longevity_anti_aging", 5, domain="longevity_research",
    )

    assert queries == ["physical activity", "physical activity aging"]
    assert len(papers) == 5
    assert [paper["doi"] for paper in papers] == [
        "10.1/physical-activity-0",
        "10.1/physical-activity-1",
        "10.1/physical-activity-2",
        "10.1/physical-activity-3",
        "10.1/physical-activity-4",
    ]
    assert {paper["source_fact"]["intervention"] for paper in papers} == {"physical activity"}


def test_source_literature_fullraw_requires_multi_token_title_alignment(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "",
        "researka_database_token": "",
    })())
    queries: list[tuple[str, int]] = []

    def fullraw_papers(query: str, limit: int) -> list[dict[str, str]]:
        queries.append((query, limit))
        return [
            {
                "doi": "10.1/hiit",
                "title": "High intensity interval training improves insulin resistance",
            },
            {
                "doi": "10.1/resistance",
                "title": "Resistance training improves muscle function in aging adults",
            },
        ]

    monkeypatch.setattr(
        publish_literature,
        "_fullraw_topic_papers", fullraw_papers,
    )

    papers = daily._fetch_source_literature_papers(
        "resistance_training", 2, domain="longevity_research",
    )

    assert [paper["doi"] for paper in papers] == ["10.1/resistance"]
    assert queries == [("resistance training", 25)]


def test_source_literature_fullraw_uses_relevance_not_exact_phrase(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "researka_database_url": "",
        "researka_database_token": "",
    })())

    titles = (
        "Sarcopenia and aging muscle mass in older adults",
        "Aging muscle strength decline and sarcopenia risk",
        "Sarcopenia prevention study in aging skeletal muscle",
        "Aging adult sarcopenia and muscle function trajectories",
        "Aging-related muscle preservation and sarcopenia biology",
    )
    monkeypatch.setattr(
        publish_literature,
        "_fullraw_topic_papers",
        lambda *_args: [
            {"doi": f"10.1/sarc-{idx}", "title": title}
            for idx, title in enumerate(titles)
        ],
    )

    papers = daily._fetch_source_literature_papers(
        "sarcopenia_muscle_preservation_longevity_anti_aging",
        5,
        domain="longevity_research",
    )

    assert [paper["doi"] for paper in papers] == [
        "10.1/sarc-0", "10.1/sarc-1", "10.1/sarc-2",
        "10.1/sarc-3", "10.1/sarc-4",
    ]
    assert daily._source_literature_boundary_quality(
        "sarcopenia_muscle_preservation_longevity_anti_aging", papers, 5,
    ) == (True, "ok")


def test_source_literature_boundary_quality_rejects_title_series() -> None:
    papers = [
        {"title": f"RAGE collagen pathway review {year}", "doi": f"10.1234/{year}"}
        for year in range(2020, 2025)
    ]

    ok, reason = daily._source_literature_boundary_quality("glycation_AGEs", papers, 5)

    assert ok is False
    assert reason == "repeated_title_series"


def test_source_literature_boundary_requires_multi_token_topic_alignment() -> None:
    papers = [
        {
            "title": "The Effects of Vitamin D Supplementation on Metabolic Markers",
            "doi": "10.1234/1",
            "source_fact": {
                "canonical_phrase": "oral daily doses of vitamin D improve HbA1c levels",
            },
        },
        {
            "title": "Direct oral anticoagulants for cancer-associated thrombosis",
            "doi": "10.1234/2",
            "source_fact": {
                "canonical_phrase": "direct oral anticoagulants changed bleeding risk",
            },
        },
        {
            "title": "Modulation of ketamine effects by oral rapamycin",
            "doi": "10.1234/3",
            "source_fact": {
                "canonical_phrase": "oral rapamycin was given before ketamine",
            },
        },
        {
            "title": "Prevalence of periodontal disease",
            "doi": "10.1234/4",
            "source_fact": {
                "canonical_phrase": "periodontal disease increased cardiovascular risk",
            },
        },
        {
            "title": "Human Skin, Oral, and Gut Microbiomes Predict Chronological Age",
            "doi": "10.1234/5",
            "source_fact": {
                "canonical_phrase": "the oral microbiome predicted chronological age",
            },
        },
    ]

    ok, reason = daily._source_literature_boundary_quality(
        "oral_microbiome_periodontal_aging", papers, 5,
    )

    assert ok is False
    assert reason == "source_floor_below_min"


def test_source_literature_boundary_rejects_outcome_only_topic_mentions() -> None:
    papers = [
        {
            "title": f"Caplacizumab trial report {idx}",
            "doi": f"10.1234/tpe-{idx}",
            "source_fact": {
                "canonical_phrase": "median therapeutic plasma exchange days were lower",
                "intervention": "caplacizumab",
                "comparator": "placebo",
            },
        }
        for idx in range(5)
    ]

    ok, reason = daily._source_literature_boundary_quality(
        "therapeutic_plasma_exchange", papers, 5,
    )

    assert ok is False
    assert reason == "source_floor_below_min"


def test_source_literature_boundary_requires_slug_domain_context() -> None:
    papers = [
        {
            "title": f"Therapeutic plasma exchange in acute indication {idx}",
            "doi": f"10.1234/tpe-aging-{idx}",
            "source_fact": {
                "canonical_phrase": "therapeutic plasma exchange improved liver function tests",
                "intervention": "therapeutic plasma exchange",
                "comparator": "standard care",
            },
        }
        for idx in range(5)
    ]

    ok, reason = daily._source_literature_boundary_quality(
        "therapeutic_plasma_exchange_longevity_anti_aging", papers, 5,
    )

    assert ok is False
    assert reason == "source_floor_below_min"


def test_source_literature_boundary_rejects_generic_patient_age_context() -> None:
    papers = [
        {
            "title": title,
            "doi": f"10.1234/tpe-live-{idx}",
            "source_fact": {
                "canonical_phrase": "therapeutic plasma exchange improved acute disease markers",
                "population": "hospitalized adults aged 65 years",
                "intervention": "therapeutic plasma exchange",
                "endpoint": endpoint,
            },
        }
        for idx, (title, endpoint) in enumerate((
            ("Therapeutic plasma exchange in acute liver failure", "liver function"),
            ("Plasma exchange for toxic overdose", "toxin clearance"),
            ("Therapeutic plasma exchange in Still's disease", "inflammation"),
            ("Therapeutic plasma exchange in immune hepatitis", "hepatitis severity"),
            ("Therapeutic plasma exchange for thrombotic thrombocytopenia", "TPE days"),
        ), start=1)
    ]

    ok, reason = daily._source_literature_boundary_quality(
        "therapeutic_plasma_exchange_longevity_anti_aging", papers, 5,
    )

    assert ok is False
    assert reason == "source_floor_below_min"


def test_source_literature_boundary_quality_accepts_distinct_boundary_papers() -> None:
    papers = [
        {"title": "AGE-RAGE signalling and skin collagen aging", "doi": "10.1234/1"},
        {"title": "Glycation stress and RAGE activation in vascular aging", "doi": "10.1234/2"},
        {"title": "Collagen crosslinking in advanced glycation biology", "doi": "10.1234/3"},
        {"title": "RAGE pathways in age-related tissue injury", "doi": "10.1234/4"},
        {"title": "Glycation-derived collagen stiffening review", "doi": "10.1234/5"},
    ]

    ok, reason = daily._source_literature_boundary_quality("glycation_AGEs", papers, 5)

    assert ok is True
    assert reason == "ok"


def test_source_literature_boundary_rejects_uniform_favorable_cross_pico_bundle() -> None:
    endpoints = [
        "cognitive decline", "cancer mortality", "cardiovascular disease",
        "systolic blood pressure", "fasting glucose",
    ]
    papers = [
        {
            "title": f"Dietary pattern and {endpoint}",
            "doi": f"10.1234/pico-{idx}",
            "source_fact": {
                "canonical_phrase": "intervention reduced the endpoint risk",
                "population": "adults",
                "intervention": "dietary pattern",
                "comparator": "usual care",
                "endpoint": endpoint,
            },
        }
        for idx, endpoint in enumerate(endpoints)
    ]

    ok, reason = daily._source_literature_boundary_quality("dietary pattern", papers, 5)

    assert ok is False
    assert reason == "directionally_uniform_cross_pico_bundle"


def test_source_literature_boundary_rejects_mixed_model_context_bundle() -> None:
    papers = [
        {
            "title": "Melatonin improves age-induced fertility decline in mice",
            "doi": "10.1234/mouse-1",
            "source_fact": {
                "canonical_phrase": "melatonin increased ovarian-aging fertility markers",
                "population": "female mice",
                "intervention": "melatonin",
                "endpoint": "ovarian aging",
            },
        },
        {
            "title": "Long-term melatonin treatment delays ovarian aging",
            "doi": "10.1234/mouse-2",
            "source_fact": {
                "canonical_phrase": "melatonin delayed ovarian aging",
                "population": "female mice",
                "intervention": "melatonin",
                "endpoint": "ovarian aging",
            },
        },
        {
            "title": "Melatonin application delays senescence of leaves",
            "doi": "10.1234/plant-1",
            "source_fact": {
                "canonical_phrase": "melatonin pretreatment delayed leaf senescence",
                "population": "plant leaves",
                "intervention": "exogenous melatonin",
                "endpoint": "leaf senescence",
            },
        },
        {
            "title": "Melatonin improves fruit senescence and shelf life",
            "doi": "10.1234/plant-2",
            "source_fact": {
                "canonical_phrase": "melatonin improved fruit senescence and shelf life",
                "population": "fruit plants",
                "intervention": "melatonin",
                "endpoint": "fruit senescence",
            },
        },
        {
            "title": "Melatonin and skin aging mechanisms",
            "doi": "10.1234/skin",
            "source_fact": {
                "canonical_phrase": "mitochondria generate intracellular ROS",
                "population": "intracellular ROS",
                "intervention": "mitochondria",
                "endpoint": "skin aging biology",
            },
        },
    ]

    ok, reason = daily._source_literature_boundary_quality("melatonin_aging", papers, 5)

    assert ok is False
    assert reason == "mixed_source_context_family"


def test_source_literature_boundary_selects_coherent_subset_from_wider_bundle() -> None:
    papers = [
        {
            "title": f"Acarbose human observational aging signal {idx}",
            "doi": f"10.1234/human-{idx}",
            "source_fact": {
                "canonical_phrase": "acarbose was associated with aging markers",
                "population": "adult human cohort",
                "intervention": "acarbose",
                "endpoint": "aging marker",
            },
        }
        for idx in range(2)
    ]
    mouse_titles = (
        "Acarbose mouse lifespan source",
        "Acarbose murine glucose aging response",
        "Acarbose mouse microbiome longevity signal",
        "Acarbose murine inflammation aging marker",
        "Acarbose mouse metabolic healthspan study",
    )
    papers += [
        {
            "title": title,
            "doi": f"10.1234/mouse-{idx}",
            "source_fact": {
                "canonical_phrase": "acarbose changed an aging endpoint",
                "population": "mice",
                "intervention": "acarbose",
                "endpoint": "aging endpoint",
            },
        }
        for idx, title in enumerate(mouse_titles)
    ]

    ok, reason = daily._source_literature_boundary_quality("acarbose", papers, 5)
    selected = publish_literature.select_boundary_papers("acarbose", papers, 5)

    assert ok is True
    assert reason == "ok"
    assert {paper["doi"] for paper in selected} == {
        f"10.1234/mouse-{idx}" for idx in range(5)
    }


def test_source_literature_boundary_requires_specific_topic_alignment() -> None:
    papers = [
        {
            "title": "Sodium-glucose cotransporter 2 inhibitors and cardiovascular outcomes",
            "doi": "10.1234/1",
            "source_fact": {
                "canonical_phrase": "major adverse cardiac events (OR 0.8)",
                "intervention": "SGLT2 inhibitors",
                "endpoint": "cardiovascular outcomes",
            },
        },
        {
            "title": "Cardiovascular toxicity of proteasome inhibitors",
            "doi": "10.1234/2",
            "source_fact": {
                "canonical_phrase": "ixazomib reduced risk of progression or death by 28%",
                "intervention": "ixazomib maintenance",
                "endpoint": "progression-free survival",
            },
        },
        {
            "title": "SGLT2 inhibitors for nonalcoholic fatty liver disease",
            "doi": "10.1234/3",
            "source_fact": {
                "canonical_phrase": "decreased serum alanine aminotransferase",
                "intervention": "SGLT2 inhibitors",
                "endpoint": "alanine aminotransferase",
            },
        },
        {
            "title": "SGLT2 inhibitors in acute heart failure",
            "doi": "10.1234/4",
            "source_fact": {
                "canonical_phrase": "reduced rehospitalization for heart failure",
                "intervention": "SGLT2 inhibitors",
                "endpoint": "heart-failure rehospitalization",
            },
        },
        {
            "title": "Sodium glucose cotransporter 2 inhibitors in diabetes mellitus",
            "doi": "10.1234/5",
            "source_fact": {
                "canonical_phrase": "14% reduction in the primary composite outcome",
                "intervention": "empagliflozin",
                "endpoint": "cardiovascular death, myocardial infarction, or stroke",
            },
        },
    ]

    ok, reason = daily._source_literature_boundary_quality(
        "ACE_inhibitors_aging", papers, 5,
    )

    assert ok is False
    assert reason == "source_floor_below_min"


def test_source_literature_boundary_rejects_partial_three_token_topic_bundle() -> None:
    papers = [
        {
            "title": "THE EFFECT OF MINIMUM WAGES ON EMPLOYMENT: A FACTOR MODEL APPROACH",
            "doi": "10.1234/1",
            "source_fact": {
                "canonical_phrase": "minimum wage employment elasticity estimates were null",
                "intervention": "minimum wage",
                "endpoint": "employment elasticity",
            },
        },
        {
            "title": "Revisiting the Minimum Wage-Employment Debate",
            "doi": "10.1234/2",
            "source_fact": {
                "canonical_phrase": "teen employment elasticities near -0.15",
                "population": "teen workers",
                "intervention": "minimum wages",
                "endpoint": "employment elasticity",
            },
        },
        {
            "title": "European Minimum Wage Policy",
            "doi": "10.1234/3",
            "source_fact": {
                "canonical_phrase": "minimum wage policy prevalence across countries",
                "intervention": "minimum wage policy",
                "endpoint": "policy prevalence",
            },
        },
        {
            "title": "At What Level Should Countries Set Their Minimum Wages",
            "doi": "10.1234/4",
            "source_fact": {
                "canonical_phrase": "minimum wages are common across countries",
                "intervention": "minimum wage policy",
                "endpoint": "policy level",
            },
        },
        {
            "title": "Nominal Wage Rigidity in Village Labor Markets",
            "doi": "10.1234/5",
            "source_fact": {
                "canonical_phrase": "wage rigidity reduced employment",
                "intervention": "rainfall shocks",
                "endpoint": "employment",
            },
        },
    ]

    ok, reason = daily._source_literature_boundary_quality(
        "minimum_wage_employment", papers, 5, "economics_research",
    )
    selected = publish_literature.select_boundary_papers(
        "minimum_wage_employment", papers, 5, strict_topic_coverage=True,
    )

    assert ok is False
    assert reason == "source_floor_below_min"
    assert len(selected) == 2


def test_source_literature_boundary_rejects_generic_only_topic() -> None:
    papers = [
        {
            "title": f"Aging intervention evidence map {i}",
            "doi": f"10.1234/generic-{i}",
            "source_fact": {"canonical_phrase": "reported a directional association"},
        }
        for i in range(5)
    ]

    ok, reason = daily._source_literature_boundary_quality("longevity", papers, 5)

    assert ok is False
    assert reason == "source_floor_below_min"


def test_source_literature_bundle_resolves_doi_url_openalex_and_cochrane_review() -> None:
    title = (
        "Metformin for prevention or delay of type 2 diabetes mellitus and "
        "its associated complications in persons at increased risk"
    )
    url_title = "Deuterium depleted water behavior in chromium intoxicated rats"
    assert daily._source_bundle([{
        "title": title,
        "doi": "10.1002/14651858.CD008558.pub2",
        "year": 2019,
    }, {
        "title": url_title,
        "url": "https://www.semanticscholar.org/paper/example",
        "year": 2010,
    }, {
        "title": "European Minimum Wage Policy",
        "id": "W330803907",
        "year": 2015,
    }]) == [{
        "title": title,
        "url": "https://doi.org/10.1002/14651858.CD008558.pub2",
        "doi": "10.1002/14651858.CD008558.pub2",
        "year": 2019,
        "evidence_type": "review",
    }, {
        "title": url_title,
        "url": "https://www.semanticscholar.org/paper/example",
        "doi": None,
        "year": 2010,
        "evidence_type": "primary",
    }, {
        "title": "European Minimum Wage Policy",
        "url": "https://openalex.org/W330803907",
        "doi": None,
        "year": 2015,
        "evidence_type": "primary",
    }]


def test_source_literature_payload_is_deterministic_boundary_only(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {"title": "AGE-RAGE signalling and skin collagen aging", "doi": "10.1234/1", "year": 2024},
        {"title": "Glycation stress and RAGE activation in vascular aging", "doi": "10.1234/2", "year": 2024},
        {"title": "Collagen crosslinking in advanced glycation biology", "doi": "10.1234/3", "year": 2024},
        {"title": "RAGE pathways in age-related tissue injury", "doi": "10.1234/4", "year": 2024},
        {"title": "Glycation-derived collagen stiffening review", "doi": "10.1234/5", "year": 2024},
    ]

    def fail_writer(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("source-literature boundary payload must not call writer")

    monkeypatch.setattr(daily, "call_writer", fail_writer, raising=False)

    _candidate, payload = daily._source_literature_payload(
        profile_slug="longevity_research", topic="glycation_AGEs",
        papers=papers, runs_root=root, date="2026-06-09T20-00-00Z",
    )

    writer = payload["evidence_bundle"]["source_literature_writer"]
    run_dir = root / "glycation_AGEs-source-literature-2026-06-09T20-00-00Z"
    sidecar = json.loads((run_dir / "source_literature_writer.json").read_text(
        encoding="utf-8",
    ))
    assert "## Source synthesis" in payload["markdown"]
    assert "## Research question" in payload["markdown"]
    assert "## Selection criteria" in payload["markdown"]
    assert "without establishing" in payload["markdown"]
    assert "## Context separation" in payload["markdown"]
    assert "## Next gaps" in payload["markdown"]
    assert "primary; 2024" in payload["markdown"]
    assert writer["status"] == "skipped"
    assert writer["reason"] == "deterministic_boundary_only"
    assert sidecar["content_hash"] == writer["content_hash"]
    assert (run_dir / "source_literature_memo.md").read_text(
        encoding="utf-8",
    ) == payload["markdown"]


def test_source_literature_payload_labels_consistent_favorable_receipts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {
            "title": "Diet and cognitive outcomes cohort",
            "doi": "10.1234/md1",
            "year": 2023,
            "source_fact": {
                "canonical_phrase": "higher adherence reduced dementia risk",
                "population": "older adults",
                "intervention": "Mediterranean diet",
                "comparator": "lower adherence",
                "endpoint": "cognitive outcome",
            },
        },
        {
            "title": "Diet and cancer mortality meta analysis",
            "doi": "10.1234/md2",
            "year": 2022,
            "source_fact": {
                "canonical_phrase": "adherence reduced cancer mortality",
                "population": "general population",
                "intervention": "Mediterranean diet",
                "comparator": "lower adherence",
                "endpoint": "mortality",
            },
        },
        {
            "title": "Diet and glycemic control network meta analysis",
            "doi": "10.1234/md3",
            "year": 2021,
            "source_fact": {
                "canonical_phrase": "Mediterranean diet was ranked as the best approach",
                "population": "adults with type 2 diabetes",
                "intervention": "Mediterranean diet",
                "comparator": "control diet",
                "endpoint": "fasting glucose",
            },
        },
        {
            "title": "Diet and blood pressure trial",
            "doi": "10.1234/md4",
            "year": 2020,
            "source_fact": {
                "canonical_phrase": "intervention reduced systolic blood pressure",
                "population": "older adults",
                "intervention": "Mediterranean diet",
                "comparator": "usual diet",
                "endpoint": "systolic blood pressure",
            },
        },
        {
            "title": "Diet and cardiovascular incidence review",
            "doi": "10.1234/md5",
            "year": 2019,
            "source_fact": {
                "canonical_phrase": "diet reduced cardiovascular disease incidence",
                "population": "adults",
                "intervention": "Mediterranean diet",
                "comparator": "usual care",
                "endpoint": "cardiovascular disease incidence",
            },
        },
    ]

    _candidate, payload = daily._source_literature_payload(
        profile_slug="longevity_research", topic="Mediterranean diet",
        papers=papers, runs_root=root, date="2026-06-09T21-00-00Z",
    )

    assert payload["title"] == (
        "Mediterranean diet: one bounded, context-dependent signal across receipts"
    )
    assert "..." not in payload["abstract"]
    assert "directional disagreement" in payload["abstract"]
    assert "Concrete source-level examples" not in payload["abstract"]
    assert "directionally consistent signals across heterogeneous contexts" in payload["markdown"]
    assert "Direction is homogeneous: all selected receipts are directionally favorable" in payload["markdown"]
    assert "not convergent" not in payload["abstract"]
    assert "directionally favorable: 5 receipt(s)" in payload["markdown"]
    assert "study design/evidence type (primary/review)" in payload["markdown"]
    assert "fasting glucose" in payload["markdown"]
    assert "Single primary-study estimates are separated" in payload["markdown"]


def test_source_literature_payload_uses_economics_language(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {
            "title": f"Minimum wage employment elasticity source {idx}",
            "doi": f"10.1234/minwage-{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": phrase,
                "population": "local labor markets",
                "intervention": "minimum wage policy",
                "comparator": "lower minimum wage baseline",
                "endpoint": "employment elasticity",
            },
        }
        for idx, phrase in enumerate((
            "minimum wage employment elasticity was not statistically different from zero",
            "minimum wage employment elasticity was negative in teen labor markets",
            "minimum wage employment response varied by local labor demand",
            "minimum wage employment estimates differed across model specifications",
            "minimum wage employment effects were heterogeneous across settings",
        ))
    ]

    _candidate, payload = daily._source_literature_payload(
        profile_slug="economics_research", topic="minimum_wage_employment",
        papers=papers, runs_root=root, date="2026-06-26T09-00-00Z",
    )

    markdown = payload["markdown"]
    lower = markdown.lower()
    for phrase in (
        "clinical",
        "species",
        "comparative-efficacy",
        "endpoint-specific favorable",
        "directionally favorable",
        "intervention efficacy",
        "human clinical",
    ):
        assert phrase not in lower
    assert "directional estimate:" in markdown
    assert "policy/exposure/practice" in markdown
    assert "matched design" in markdown
    assert "pooled elasticity" in markdown


def test_source_literature_payload_separates_comparator_and_economic_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {
            "title": "Iron Deficiency in Heart Failure and Effect of Dapagliflozin",
            "doi": "10.1234/dapa1",
            "year": 2022,
            "source_fact": {
                "canonical_phrase": "hazard ratio, 0.74 [95% CI, 0.58-0.92]",
                "population": "iron-deficient patients with heart failure",
                "intervention": "dapagliflozin",
                "comparator": "placebo",
                "endpoint": "heart failure outcome",
            },
        },
        {
            "title": "Dapagliflozin and cardiovascular death in heart failure",
            "doi": "10.1234/dapa2",
            "year": 2022,
            "source_fact": {
                "canonical_phrase": "Dapagliflozin reduced cardiovascular death risk (HR 0.86)",
                "population": "patients with heart failure",
                "intervention": "dapagliflozin",
                "comparator": "placebo",
                "endpoint": "cardiovascular death",
            },
        },
        {
            "title": "Dapagliflozin renal outcomes in chronic kidney disease",
            "doi": "10.1234/dapa3",
            "year": 2020,
            "source_fact": {
                "canonical_phrase": "hazard ratio for the primary end point was 0.71",
                "population": "patients with chronic kidney disease",
                "intervention": "dapagliflozin",
                "comparator": "placebo",
                "endpoint": "renal composite",
            },
        },
        {
            "title": "Cost-Effectiveness of Dapagliflozin for Heart Failure",
            "doi": "10.1234/dapa4",
            "year": 2020,
            "source_fact": {
                "canonical_phrase": "GBP 5822/QALY in the UK",
                "population": "patients with heart failure",
                "intervention": "dapagliflozin added to standard therapy",
                "comparator": "standard therapy only",
                "endpoint": "cost-effectiveness",
            },
        },
        {
            "title": "Semaglutide versus dapagliflozin in type 2 diabetes",
            "doi": "10.1234/dapa5",
            "year": 2024,
            "source_fact": {
                "canonical_phrase": "Semaglutide induced a larger HbA1c reduction than dapagliflozin",
                "population": "patients with type 2 diabetes",
                "intervention": "semaglutide",
                "comparator": "dapagliflozin",
                "endpoint": "HbA1c",
            },
        },
    ]

    _candidate, payload = daily._source_literature_payload(
        profile_slug="longevity_research", topic="dapagliflozin",
        papers=papers, runs_root=root, date="2026-06-24T14-17-40Z",
    )

    markdown = payload["markdown"]
    assert "directionally favorable: 3 receipt(s)" in markdown
    assert "economic/context only: 1 receipt(s)" in markdown
    assert "comparator/not favorable: 1 receipt(s)" in markdown
    assert "directionally favorable: dapagliflozin is the intervention/exposure" in markdown
    assert "comparator/not favorable: dapagliflozin is the comparator arm" in markdown
    assert (
        "- comparator/not favorable: Semaglutide versus dapagliflozin"
        in markdown
    )
    assert "topic is comparator here; label is endpoint-specific" in markdown
    assert "- economic/context only: Cost-Effectiveness of Dapagliflozin" in markdown
    assert "not pooled or averaged" in markdown
    assert "Routing domain `longevity_research` is publication-lane metadata only" in markdown


def test_source_literature_payload_separates_intervention_from_predictive_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {
            "title": "Effect of gut microbiome modulation on muscle function and cognition",
            "doi": "10.1234/gut1",
            "year": 2024,
            "source_fact": {
                "canonical_phrase": "The prebiotic improves cognition versus placebo",
                "population": "older adults",
                "intervention": "prebiotic daily for 12 weeks",
                "comparator": "placebo",
                "endpoint": "cognitive factor score",
            },
        },
        {
            "title": "Fasting alters the gut microbiome reducing blood pressure",
            "doi": "10.1234/gut2",
            "year": 2021,
            "source_fact": {
                "canonical_phrase": "a 5-day fast reduces systolic blood pressure",
                "population": "hypertensive metabolic syndrome patients",
                "intervention": "5-day fast followed by DASH diet",
                "comparator": "DASH diet alone",
                "endpoint": "systolic blood pressure",
            },
        },
        {
            "title": "Gut microbiome remodeling improves with intermittent fasting",
            "doi": "10.1234/gut3",
            "year": 2024,
            "source_fact": {
                "canonical_phrase": "combined IF-P versus calorie restriction",
                "population": "adults with overweight or obesity",
                "intervention": "intermittent fasting with protein pacing",
                "comparator": "calorie restriction",
                "endpoint": "gut microbiome remodeling",
            },
        },
        {
            "title": "Human Skin, Oral, and Gut Microbiomes Predict Chronological Age",
            "doi": "10.1234/gut4",
            "year": 2020,
            "source_fact": {
                "canonical_phrase": "gut microbiome predicted chronological age",
                "population": "adults",
                "intervention": "microbiome age prediction",
                "endpoint": "chronological age prediction",
            },
        },
        {
            "title": "The human gut microbiome and aging",
            "doi": "10.1234/gut5",
            "year": 2024,
            "source_fact": {
                "canonical_phrase": "Machine-learning analysis predicted chronologic age",
                "population": "published gut microbiome datasets",
                "intervention": "machine-learning analysis",
                "endpoint": "age prediction error",
            },
        },
    ]

    _candidate, payload = daily._source_literature_payload(
        profile_slug="longevity_research", topic="gut_microbiome",
        papers=papers, runs_root=root, date="2026-06-25T00-15-00Z",
    )

    markdown = payload["markdown"]
    assert "directionally favorable: 2 receipt(s)" in markdown
    assert "non-clinical/predictive: 2 receipt(s)" in markdown
    assert "other/mixed: 1 receipt(s)" in markdown
    assert "other/mixed: 5 receipt(s)" not in markdown
    assert "Descriptive receipt labels, not pooled effect counts" in payload["abstract"]
    assert "not one pooled evidence front" in markdown
    assert "intervention signals plus separate predictive evidence" in payload["abstract"]
    assert payload["title"] == (
        "gut microbiome: separated intervention and predictive evidence fronts"
    )


def test_source_literature_payload_classifies_restored_attenuated_rows_as_favorable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {
            "title": f"Quercetin source {idx}",
            "doi": f"10.1234/quercetin-{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": phrase,
                "population": "animal model",
                "intervention": "quercetin",
                "comparator": "control",
                "endpoint": "metabolic or hepatic marker",
            },
        }
        for idx, phrase in enumerate((
            "quercetin reduced postprandial glucose by 64%",
            "quercetin attenuated ethanol-induced hepatic damage",
            "quercetin restored body weight insulin and glucose markers",
            "quercetin dampened inflammatory response markers",
        ))
    ] + [{
        "title": "Quercetin alleviates lung injury via the Sirt1 pathway",
        "doi": "10.1234/quercetin-mechanism",
        "year": 2024,
        "source_fact": {
            "canonical_phrase": (
                "Sirt1 knockdown significantly reduced the anti-ferroptotic "
                "functions of quercetin"
            ),
            "population": "mouse and cell injury models",
            "intervention": "Sirt1 knockdown",
            "comparator": "quercetin treatment",
            "endpoint": "anti-ferroptotic function",
        },
    }]

    _candidate, payload = daily._source_literature_payload(
        profile_slug="longevity_research", topic="quercetin",
        papers=papers, runs_root=root, date="2026-06-25T01-05-00Z",
    )

    markdown = payload["markdown"]
    assert "directionally favorable: 5 receipt(s)" in markdown
    assert "comparator/not favorable: 1 receipt(s)" not in markdown
    assert "- comparator/not favorable: Quercetin alleviates lung injury" not in markdown
    assert "- directionally favorable: Quercetin alleviates lung injury" in markdown
    assert "mechanistic ablation supports the topic effect" in markdown
    assert "heterogeneous indication/context map" in markdown
    assert "Concrete source-level examples" not in payload["abstract"]
    assert "\n- other/mixed:" not in markdown


def test_source_literature_payload_omits_heterogeneous_note_for_matched_context(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    papers = [
        {
            "title": f"Matched quercetin source {idx}",
            "doi": f"10.1234/quercetin-matched-{idx}",
            "year": 2020 + idx,
            "source_fact": {
                "canonical_phrase": "quercetin reduced glucose versus control",
                "population": "diabetic mice",
                "intervention": "quercetin",
                "comparator": "control",
                "endpoint": "glucose",
            },
        }
        for idx in range(5)
    ]

    _candidate, payload = daily._source_literature_payload(
        profile_slug="longevity_research", topic="quercetin",
        papers=papers, runs_root=root, date="2026-06-25T01-07-00Z",
    )

    assert "directionally favorable: 5 receipt(s)" in payload["markdown"]
    assert "heterogeneous indication/context map" not in payload["abstract"]


def test_source_literature_fallback_blocks_repeated_report_series(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "longevity.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "report_primary_brain", "paper_count": 25}],
    }), encoding="utf-8")
    papers = [
        {
            "title": (
                "CBTRUS Statistical Report: Primary Brain and Other Central "
                f"Nervous System Tumors Diagnosed in the United States in {year}-{year + 4}"
            ),
            "doi": f"10.1093/neuonc/{year}",
        }
        for year in (2013, 2014, 2015, 2016)
    ] + [{
        "title": "The Liver Tumor Segmentation Benchmark (LiTS)",
        "doi": "10.1016/j.media.2022.102680",
    }]
    submitted: list[dict[str, Any]] = []
    monkeypatch.setattr(daily, "load_settings", lambda: type("S", (), {
        "writer_configured": False,
        "mimo_model": "",
        "mimo_base_url": "",
    })())

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        return {"ok": True, "status": 200}

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-10T05-30-00Z",
        domain="longevity_research",
        queue=_queue(),
        submit=True,
        submitter=submitter,
        source_paper_fetcher=lambda _topic, _limit: papers,
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert submitted == []
    assert ledger["status"] == "no_fresh_candidate"
    assert daily._source_literature_boundary_quality(
        "report_primary_brain", papers, 5,
    ) == (False, "repeated_title_series")


def test_source_literature_fallback_is_not_used_for_ai_domain(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "_topics_discovery").mkdir(parents=True)
    (root / "_topics_discovery" / "ai.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
        "all": [{
            "topic": "llm_evaluation",
            "paper_count": 25,
            "fact_source_count": 0,
        }],
    }), encoding="utf-8")
    papers = [
        {"title": f"LLM evaluation benchmark paper {idx}", "doi": f"10.1234/{idx}"}
        for idx in range(5)
    ]
    submitted: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        return {
            "ok": True, "status": 200,
            "response": {"submission": {"id": "sub-ai"}},
        }

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-06-09T19-00-00Z",
        domain="ai_research",
        queue=_queue(),
        submit=True,
        submitter=submitter,
        source_paper_fetcher=lambda _topic, _limit: papers,
        fetcher=lambda _doi: {"message": {}},
        sleep=lambda _seconds: None,
    )

    assert submitted == []
    assert ledger["status"] == "no_fresh_candidate"
    assert "source_literature_fallback" not in ledger


def test_initial_probe_refreshes_when_ready_row_recomputes_unactionable(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("open_source_models") | {"domain": {"slug": "ai_research"}}
    _memo_with_source_receipts(root, verdict, 5)
    ledger_dir = root / "runs" / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    daily._write_json(ledger_dir / "_submitted_fingerprints.json", [{
        "topic": "open_source_models",
        "domain_slug": "ai_research",
        "date": "2026-06-24T11:00:00Z",
        "fingerprint": "older-fingerprint",
    }])
    run = root / str(verdict["run_dir"])
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(verdict), encoding="utf-8",
    )
    current = verdict | {
        "decision": "agent_repair_needed",
        "surface_type": "subtopic_rerun_memo",
        "blockers": ["metric_type_mismatch", "fact_shape_mismatch"],
    }
    monkeypatch.setattr(daily, "_current_selection_verdict", lambda _v, _root: current)
    monkeypatch.setattr(
        daily,
        "_claim_cluster_candidates",
        lambda *_args, **_kwargs: [current | {
            "_claim_cluster_candidate": True,
            "_claim_cluster_topic": "open_source_models_child",
            "topic": "open_source_models_child",
        }],
    )
    refresh_calls: list[dict[str, Any]] = []

    def refresh_batch(
        refresh_top: int,
        excluded_topics: set[str],
        cooldown_hours: float,
        runs_root: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        refresh_calls.append({
            "refresh_top": refresh_top,
            "excluded_topics": sorted(excluded_topics),
            "cooldown_hours": cooldown_hours,
            "runs_root": str(runs_root),
            **kwargs,
        })
        return {
            "ok": True,
            "note": "refresh-ran",
            "top": refresh_top,
            "cooldown_hours": cooldown_hours,
            "excluded_topics": sorted(excluded_topics),
        }

    monkeypatch.setattr(daily, "_refresh_candidate_batch", refresh_batch)

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-06-24T12-00-00Z",
        domain="ai_research",
        refresh_candidates=True,
        refresh_top=1,
        max_refresh_batches=1,
        submit=False,
        sleep=lambda _seconds: None,
    )

    assert refresh_calls
    assert ledger["preflight_queue_counts"]["ready_to_publish"] == 1
    assert sum(ledger["preflight_considered_counts"].values()) >= 1
    assert ledger["refresh_batches"][0]["note"] == "refresh-ran"


def test_memo_without_falsifier_is_blocked(tmp_path: Path) -> None:
    """C4 submit gate: an approved memo that omits 'What would weaken this' is
    held as memo_missing_falsifier and never selected."""
    root = tmp_path / "repo"
    verdict = _verdict("no_falsifier")
    run_dir = root / str(verdict["run_dir"])
    run_dir.mkdir(parents=True)
    (run_dir / "alpha_memo.md").write_text(
        "# Alpha memo\n\n**Headline:** A bounded signal\n\n"
        "## Evidence receipts\n\n- `fact_id=1` (`A_core`) - receipt\n",
        encoding="utf-8",
    )
    cand, considered = daily.select_candidate(
        _queue(verdict), runs_root=root, submitted_path=root / "submitted.json",
        min_source_count=5, min_direct_source_count=2,
    )
    assert cand is None
    assert considered[0]["status"] == "memo_missing_falsifier"


def test_memo_missing_audit_sidecars_is_blocked(tmp_path: Path) -> None:
    """Published alpha memos must carry the machine-readable audit pack."""
    root = tmp_path / "repo"
    verdict = _verdict("missing_sidecars")
    _memo_with_source_receipts(root, verdict, 5)
    run_dir = root / str(verdict["run_dir"])
    run_dir.joinpath("memo_audit.json").unlink()

    cand, considered = daily.select_candidate(
        _queue(verdict), runs_root=root, submitted_path=root / "submitted.json",
        min_source_count=5, min_direct_source_count=5,
    )

    assert cand is None
    assert considered[0]["status"] == "memo_missing_audit_sidecars"
    assert considered[0]["missing_audit_sidecars"] == ["memo_audit.json"]


def test_memo_with_falsifier_passes_the_gate(tmp_path: Path) -> None:
    """A memo carrying a concrete 'What would weaken this' bullet clears the
    falsifier gate (it then proceeds to the normal source-floor checks)."""
    root = tmp_path / "repo"
    verdict = _verdict("has_falsifier")
    run_dir = root / str(verdict["run_dir"])
    run_dir.mkdir(parents=True)
    (run_dir / "alpha_memo.md").write_text(
        "# Alpha memo\n\n**Headline:** A bounded signal\n\n"
        "## What would weaken this\n\n"
        "- Independent receipts fail to reproduce the claimed contrast.\n",
        encoding="utf-8",
    )
    _cand, considered = daily.select_candidate(
        _queue(verdict), runs_root=root, submitted_path=root / "submitted.json",
        min_source_count=5, min_direct_source_count=2,
    )
    assert considered[0]["status"] != "memo_missing_falsifier"


def test_receipt_map_verdict_does_not_submit_on_raw_source_count(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("receipt_map") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "surface_type": "receipt_map",
        "blockers": ["claim_alignment_partial"],
    }
    _memo_with_source_receipts(root, verdict, 5)
    _audit_sidecars(root / str(verdict["run_dir"]))

    cand, considered = daily.select_candidate(
        _queue(verdict),
        runs_root=root,
        submitted_path=root / "submitted.json",
        min_source_count=5,
        min_direct_source_count=5,
    )

    assert cand is None
    assert considered[0]["status"] == "agent_repair_needed"


def test_unlabeled_source_floor_review_candidate_repairs_before_approval(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("repair_sources") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4"]},
    }
    _memo_with_source_receipts(root, verdict, 6)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 5))
        + "\n\n## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - context" for i in range(5, 7))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    refreshed = {"called": False}

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        assert refresh_verdict["decision"] == "needs_operator_review"
        assert refresh_verdict["_repair_decision"]["agent_repair"] is True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n\n## Context receipts\n\n"
            "- `fact_id=6` (`A_core`) - context\n"
            + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {
                "cited_bound_fact_ids": ["1", "2", "3", "4", "5"],
            },
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert cand is not None
    assert cand["topic"] == "repair_sources"
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"
    assert considered[0]["direct_source_count"] == 5


def test_agent_repair_bucket_refreshes_without_human_approval(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("agent_repair_sources") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion"],
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4"]},
    }
    _memo_with_source_receipts(root, verdict, 6)
    refresh_decisions: list[dict[str, Any] | None] = []

    def refresh(_run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        decision = refresh_verdict.get("_repair_decision")
        refresh_decisions.append(decision if isinstance(decision, dict) else None)
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    monkeypatch.setattr(daily, "_current_selection_verdict", lambda v, _root: v)

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refresh_decisions[0] is not None
    assert refresh_decisions[0]["agent_repair"] is True
    assert cand is not None
    assert considered[0]["status"] == "eligible"


def test_retryable_revision_keeps_agent_repair_contract(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("retry_agent_repair") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion", "direct_source_floor_below_min"],
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4"]},
    }
    _memo_with_source_receipts(root, verdict, 6)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "submitted.json", [{"fingerprint": fp, "topic": "retry_agent_repair"}])
    retry_decision = {
        "decision": "revise",
        "required_revisions": ["Narrow the memo around the direct receipts."],
        "resubmission": {"allowed": True},
    }
    refresh_decisions: list[dict[str, Any] | None] = []

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        decision = refresh_verdict.get("_repair_decision")
        refresh_decisions.append(decision if isinstance(decision, dict) else None)
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    monkeypatch.setattr(daily, "_current_selection_verdict", lambda v, _root: v)

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
        retryable_fingerprints={fp},
        retry_decision_overrides={fp: retry_decision},
    )

    assert cand is not None
    assert cand["memo_fingerprint"] != fp
    assert refresh_decisions[0] is not None
    assert refresh_decisions[0]["agent_repair"] is True
    assert refresh_decisions[0]["required_revisions"] == retry_decision["required_revisions"]
    assert considered[0]["status"] == "eligible"


def test_retryable_selection_rechecks_current_verdict_before_resubmit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    stale = _verdict("retry_stale_metric_gate")
    _memo_with_source_receipts(root, stale, 5)
    stale_fp = daily.memo_fingerprint(stale)
    current = stale | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": ["metric_type_mismatch"],
    }

    monkeypatch.setattr(daily, "_current_selection_verdict", lambda _v, _root: current)

    cand, considered = daily.select_candidate(
        _queue(stale),
        runs_root=root,
        submitted_path=root / "submitted.json",
        retryable_fingerprints={stale_fp},
        retry_decision_overrides={
            stale_fp: {
                "decision": "reject",
                "resubmission": {"allowed": True},
            },
        },
    )

    assert cand is None
    assert considered[0]["decision"] == "agent_repair_needed"
    assert considered[0]["status"] == "agent_repair_needed"
    assert considered[0]["blockers"] == ["metric_type_mismatch"]


def test_retryable_revision_allows_changed_memo_same_fingerprint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("same_bundle_new_text")
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    old_sha = daily._memo_sha256(verdict, root)
    daily._write_json(root / "submitted.json", [{
        "fingerprint": fp,
        "memo_sha256": old_sha,
        "topic": "same_bundle_new_text",
    }])
    decision = {
        "decision": "revise",
        "required_revisions": ["Clarify the bounded claim without changing sources."],
        "resubmission": {"allowed": True},
    }

    def refresh(run_dir: Path, _refresh_verdict: dict[str, Any]) -> bool:
        path = run_dir / "alpha_memo.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nReviewer-requested clarification.\n",
            encoding="utf-8",
        )
        return True

    cand, considered = daily.select_candidate(
        _queue(verdict),
        runs_root=root,
        submitted_path=root / "submitted.json",
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
        retryable_fingerprints={fp},
        retry_decision_overrides={fp: decision},
    )

    assert cand is not None
    assert cand["memo_fingerprint"] == fp
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"


def test_stale_queue_verdict_reloads_current_disk_verdict(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    stale = _verdict("stale_ready") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion"],
    }
    current = _verdict("stale_ready")
    _memo_with_source_receipts(root, stale, 5)
    run = root / str(stale["run_dir"])
    run.joinpath("publish_verdict.json").write_text(
        json.dumps(current), encoding="utf-8")

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [stale],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
    )

    assert cand is not None
    assert cand["topic"] == "stale_ready"
    assert considered[0]["decision"] == "ready_to_publish"
    assert considered[0]["publish_tier"] == "TIER_1"
    assert considered[0]["status"] == "eligible"


def test_self_counter_signal_memo_refreshes_before_selection(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("self_counter")
    _memo_with_source_receipts(root, verdict, 5)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Self counter has a live counter-signal\n\n"
        "**Selected angle:** `counter_signal`\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - receipt" for i in range(1, 6))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    run.joinpath("memo_audit.json").write_text(json.dumps({
        "contradiction_receipts": [{"fact_id": "1"}],
    }), encoding="utf-8")
    refreshed = {"called": False}

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Self counter bounded signal\n\n"
            "**Selected angle:** `source`\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - receipt" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        _audit_sidecars(run_dir)
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)

    cand, considered = daily.select_candidate(
        _queue(verdict),
        runs_root=root,
        submitted_path=root / "submitted.json",
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert cand is not None
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"


def test_source_rich_tier2_frontier_candidate_submits_without_human_gate(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("source_rich_review") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "surface_type": "frontier_hypothesis_memo",
        "alpha_score": 100,
        "blockers": ["source_dispersion"],
    }
    _memo_with_source_receipts(root, verdict, 5)

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
    )

    assert cand is not None
    assert considered[0]["status"] == "eligible"


def test_unrepaired_agent_repair_needed_source_dispersion_does_not_submit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("unrepaired_source_dispersion") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "surface_type": "receipt_map",
        "blockers": ["source_dispersion"],
    }
    _memo_with_source_receipts(root, verdict, 5)

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
    )

    assert cand is None
    assert considered[0]["status"] == "agent_repair_needed"


def test_repaired_source_rich_candidate_submits_with_only_dispersion(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("source_rich_repaired") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "surface_type": "frontier_hypothesis_memo",
        "alpha_score": 100,
        "blockers": ["source_dispersion", "direct_source_floor_below_min"],
    }
    _memo_with_source_receipts(root, verdict, 6)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 3))
        + "\n\n## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - context" for i in range(3, 7))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )

    def refresh(run_dir: Path, _refresh_verdict: dict[str, Any]) -> bool:
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "agent_repair_needed",
            "publish_tier": "TIER_2",
            "blockers": ["source_dispersion"],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert cand is not None
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["source_count"] == 5
    assert considered[0]["direct_source_count"] == 5
    assert considered[0]["status"] == "eligible"


def test_rich_incoherent_review_candidate_repairs_before_approval(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("rich_repair") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "surface_type": "frontier_hypothesis_memo",
        "alpha_score": 100,
        "blockers": ["source_dispersion", "weak_counter_consensus_tension"],
    }
    _memo_with_source_receipts(root, verdict, 8)
    refreshed = {"called": False}

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        assert refresh_verdict["topic"] == "rich_repair"
        assert refresh_verdict["_repair_decision"]["agent_repair"] is True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert cand is not None
    assert cand["topic"] == "rich_repair"
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"


def test_exhausted_review_candidate_does_not_repair_dirty(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("cooldown_rich_repair") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "surface_type": "frontier_hypothesis_memo",
        "alpha_score": 100,
        "blockers": ["source_dispersion", "weak_counter_consensus_tension"],
    }
    _memo_with_source_receipts(root, verdict, 8)
    refreshed = {"called": False}

    def refresh(_run_dir: Path, _refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        return True

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
        blocked_topics={"cooldown_rich_repair"},
    )

    assert refreshed["called"] is False
    assert cand is None
    assert considered[0]["status"] == "cycle_exhausted_topic"
    assert "memo_refreshed" not in considered[0]


def test_duplicate_ready_candidate_does_not_repair_dirty(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("duplicate_ready") | {
        "headline": "Expected headline differs from memo",
    }
    _memo_with_source_receipts(root, verdict, 5)
    fp = daily.memo_fingerprint(verdict)
    daily._write_json(root / "submitted.json", [{"fingerprint": fp}])
    refreshed = {"called": False}

    def refresh(_run_dir: Path, _refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        return True

    cand, considered = daily.select_candidate(
        _queue(verdict),
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is False
    assert cand is None
    assert considered[0]["status"] == "duplicate_submission_fingerprint"
    assert "memo_refreshed" not in considered[0]


def test_source_dispersion_direct_floor_review_candidate_repairs_before_approval(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("source_dispersion_repair") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "blockers": ["source_dispersion", "direct_source_floor_below_min"],
    }
    _memo_with_source_receipts(root, verdict, 6)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 4))
        + "\n\n## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - context" for i in range(4, 7))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    refreshed = {"called": False}

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        assert refresh_verdict["_repair_decision"]["agent_repair"] is True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n\n## Context receipts\n\n"
            "- `fact_id=6` (`A_core`) - context\n"
            + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert cand is not None
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"


def test_cross_domain_direct_floor_candidate_repairs_before_approval(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("cross_domain_repair") | {
        "decision": "needs_operator_review",
        "publish_tier": "TIER_2",
        "blockers": ["cross_domain_forced", "direct_source_floor_below_min"],
    }
    _memo_with_source_receipts(root, verdict, 6)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 4))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    refreshed = {"called": False}

    def refresh(run_dir: Path, _verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)

    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "needs_operator_review": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert cand is not None
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"


def test_cross_domain_tension_source_floor_candidate_repairs_from_corpus_supply(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("cross_domain_tension_repair") | {
        "decision": "agent_repair_needed",
        "publish_tier": "TIER_2",
        "blockers": [
            "cross_domain_forced",
            "weak_counter_consensus_tension",
            "source_floor_below_min",
            "direct_source_floor_below_min",
        ],
    }
    _memo_with_source_receipts(root, verdict, 6)
    run = root / str(verdict["run_dir"])
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 3))
        + "\n\n## Context receipts\n\n"
        + "\n".join(f"- `fact_id={i}` (`A_core`) - context" for i in range(3, 7))
        + "\n" + _FALSIFIER,
        encoding="utf-8",
    )
    refreshed = {"called": False}

    def refresh(run_dir: Path, refresh_verdict: dict[str, Any]) -> bool:
        refreshed["called"] = True
        assert refresh_verdict["_repair_decision"]["agent_repair"] is True
        run_dir.joinpath("alpha_memo.md").write_text(
            "# Alpha memo\n\n"
            "**Headline:** Storage reserves flip after threshold pricing\n\n"
            "## Evidence receipts\n\n"
            + "\n".join(f"- `fact_id={i}` (`A_core`) - direct" for i in range(1, 6))
            + "\n" + _FALSIFIER,
            encoding="utf-8",
        )
        return True

    def reload_verdict(refresh_verdict: dict[str, Any], _run_dir: Path) -> dict[str, Any]:
        return refresh_verdict | {
            "decision": "ready_to_publish",
            "publish_tier": "TIER_1",
            "blockers": [],
            "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
        }

    monkeypatch.setattr(daily, "_reload_verdict_after_memo_refresh", reload_verdict)
    cand, considered = daily.select_candidate(
        {
            "ready_to_publish": [],
            "agent_repair_needed": [verdict],
            "curation_needed": [],
        },
        runs_root=root,
        submitted_path=root / "submitted.json",
        allow_tier2=True,
        min_source_count=5,
        min_direct_source_count=5,
        memo_refresher=refresh,
    )

    assert refreshed["called"] is True
    assert cand is not None
    assert considered[0]["memo_refreshed"] is True
    assert considered[0]["status"] == "eligible"


def test_public_page_check_polls_until_rendered() -> None:
    # Researka serves the "Not Found" SPA shell on the first fetch and the real
    # page on the second; the bounded poll must catch the eventual render
    # rather than falsely reporting not_rendered (the bug that left accepted
    # memos stuck at published=0).
    calls = {"n": 0}

    def fetcher(_url: str) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": True, "status": 200,
                    "body": '<title data-next-head="">Alpha Memo Not Found</title>'}
        return {"ok": True, "status": 200, "body": "<title>Real Memo</title>"}

    page = publish_public.public_page_check(
        {"public_url": "https://researka.org/alpha/x"},
        page_fetcher=fetcher, attempts=3, delay_s=0.0,
    )
    assert page["ok"] is True
    assert page["status"] == "rendered"
    assert calls["n"] == 2


def test_public_page_check_default_is_single_shot() -> None:
    # Default attempts=1 preserves the original single-fetch behaviour for the
    # reconcile/demote callers (no surprise retries).
    calls = {"n": 0}

    def fetcher(_url: str) -> dict[str, Any]:
        calls["n"] += 1
        return {"ok": True, "status": 200,
                "body": '<title data-next-head="">Alpha Memo Not Found</title>'}

    page = publish_public.public_page_check(
        {"public_url": "https://researka.org/alpha/x"}, page_fetcher=fetcher,
    )
    assert page["ok"] is False
    assert page["status"] == "not_rendered"
    assert calls["n"] == 1


def test_sync_submission_decisions_promotes_recovered_public_page(tmp_path: Path) -> None:
    # Inverse of the demote path: a memo Researka accepted whose page was not
    # built at submit time and got marked public_page_not_rendered must be
    # promoted to published once the page renders, instead of staying stuck.
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-06-11.json", {
        "status": "public_page_not_rendered",
        "published": 0,
        "publish_failure_reason": "public_page_not_rendered",
        "public_url": "https://researka.org/alpha/recovered",
        "submission_id": "sub_recovered",
    })

    summary = daily.sync_submission_decisions(
        root,
        fetcher=lambda _sid: {"status": "complete", "decision": "accept"},
        page_fetcher=lambda _url: {
            "ok": True, "status": 200, "body": "<title>Live Memo</title>",
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-06-11.json").read_text(encoding="utf-8")
    )
    assert patched["status"] == "published"
    assert patched["published"] == 1
    assert "publish_failure_reason" not in patched
    assert summary["published"] >= 1


def test_public_alpha_urls_accepts_papers_scheme() -> None:
    # Researka migrated published alpha memos from /alpha/<id> to /papers/<id>;
    # the extractor must recognise the current scheme or accepted memos can
    # never be verified/promoted (they stay stuck at published=0).
    assert publish_public.public_alpha_urls(
        {"public_url": "https://researka.org/papers/0df073d3"}
    ) == ["https://researka.org/papers/0df073d3"]
    # Legacy form still works.
    assert publish_public.public_alpha_urls(
        {"public_url": "https://researka.org/alpha/d3c55248"}
    ) == ["https://researka.org/alpha/d3c55248"]


def test_fresh_parent_topics_scan_recent_domain_discovery_snapshots(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    older = discovery / "2026-06-21T19-29-17Z.json"
    older.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "source rich parent",
            "fact_source_count": 17,
            "paper_count": 9,
            "velocity_score": 1.0,
        }],
    }), encoding="utf-8")
    newer = discovery / "2026-06-21T19-31-38Z.json"
    newer.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "thin latest",
            "fact_source_count": 2,
            "paper_count": 1,
            "velocity_score": 9.0,
        }],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=1,
        min_sources=5,
    ) == ["source rich parent"]


def test_fresh_parent_topics_prefer_source_breadth_over_newest_snapshot(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    older = discovery / "2026-06-21T19-29-17Z.json"
    older.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "source diverse parent",
            "fact_source_count": 24,
            "paper_count": 18,
            "velocity_score": 50.0,
        }],
    }), encoding="utf-8")
    newer = discovery / "2026-06-21T19-31-38Z.json"
    newer.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "adequate newer parent",
            "fact_source_count": 7,
            "paper_count": 7,
            "velocity_score": 100.0,
        }],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=1,
        min_sources=5,
    ) == ["source diverse parent"]


def test_fresh_parent_topics_prefer_fullraw_receipt_snapshot(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "older_broad.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{
            "topic": "older broad parent",
            "fact_source_count": 40,
            "paper_count": 40,
        }],
    }), encoding="utf-8")
    (discovery / "fullraw.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "fullraw_seed_probe": {"receipts": [{"shards_searched": 1514}]},
        "all": [{
            "topic": "metformin",
            "fact_source_count": 5,
            "paper_count": 5,
        }],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=1,
        min_sources=5,
    ) == ["metformin"]


def test_fresh_parent_topics_prefer_newer_fullraw_receipt_snapshot(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    older = discovery / "older_fullraw.json"
    older.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "fullraw_seed_probe": {"receipts": [{"shards_searched": 2000}]},
        "all": [{
            "topic": "source_diverse_parent",
            "fact_source_count": 30,
            "paper_count": 30,
        }],
    }), encoding="utf-8")
    newer = discovery / "newer_fullraw.json"
    newer.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "fullraw_seed_probe": {"receipts": [{"shards_searched": 10}]},
        "all": [{
            "topic": "metformin_longevity",
            "fact_source_count": 5,
            "paper_count": 5,
        }],
    }), encoding="utf-8")
    os.utime(older, (100.0, 100.0))
    os.utime(newer, (200.0, 200.0))

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=1,
        min_sources=5,
    ) == ["metformin_longevity"]


def test_fresh_parent_topics_preserve_discovery_order_after_source_floor(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {
                "topic": "thin_first_parent",
                "fact_source_count": 2,
                "paper_count": 2,
                "velocity_score": 100.0,
            },
            {
                "topic": "first_eligible_parent",
                "fact_source_count": 18,
                "paper_count": 14,
                "velocity_score": 80.0,
            },
        ],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=1,
        min_sources=5,
    ) == ["first_eligible_parent"]


def test_fresh_parent_topics_skip_locally_failed_stale_parent(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    latest = discovery / "latest.json"
    latest.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "acarbose", "fact_source_count": 9, "paper_count": 9},
            {"topic": "source_rich_parent", "fact_source_count": 8, "paper_count": 8},
        ],
    }), encoding="utf-8")
    run = tmp_path / "acarbose-evidence-ts"
    run.mkdir()
    (run / "publish_verdict.json").write_text(json.dumps({
        "decision": "curation_needed",
        "domain_slug": "longevity_research",
        "blockers": ["blocked_label:no_signal", "source_floor_below_min"],
    }), encoding="utf-8")
    os.utime(latest, (100.0, 100.0))
    os.utime(run / "publish_verdict.json", (200.0, 200.0))

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=2,
        min_sources=5,
    ) == ["source_rich_parent"]


def test_fresh_parent_topics_skip_queue_demoted_low_alpha_parent(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    latest = discovery / "latest.json"
    latest.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "fullraw_seed_probe": {"receipts": [{"shards_searched": 10}]},
        "all": [
            {"topic": "metformin_longevity", "fact_source_count": 9, "paper_count": 9},
            {"topic": "source_rich_parent", "fact_source_count": 8, "paper_count": 8},
        ],
    }), encoding="utf-8")
    run = tmp_path / "metformin_longevity-evidence-ts"
    run.mkdir()
    (run / "publish_verdict.json").write_text(json.dumps({
        "decision": "ready_to_publish",
        "domain_slug": "longevity_research",
        "topic": "metformin_longevity",
        "alpha_score": 0,
    }), encoding="utf-8")
    os.utime(latest, (100.0, 100.0))
    os.utime(run / "publish_verdict.json", (200.0, 200.0))

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=2,
        min_sources=5,
    ) == ["source_rich_parent"]


def test_fresh_parent_topics_allow_newer_discovery_after_local_failure(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    latest = discovery / "latest.json"
    latest.write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [{"topic": "acarbose", "fact_source_count": 9, "paper_count": 9}],
    }), encoding="utf-8")
    run = tmp_path / "acarbose-evidence-ts"
    run.mkdir()
    (run / "publish_verdict.json").write_text(json.dumps({
        "decision": "curation_needed",
        "domain_slug": "longevity_research",
        "blockers": ["blocked_label:no_signal", "source_floor_below_min"],
    }), encoding="utf-8")
    os.utime(run / "publish_verdict.json", (100.0, 100.0))
    os.utime(latest, (200.0, 200.0))

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=1,
        min_sources=5,
    ) == ["acarbose"]


def test_fresh_parent_topics_dedupe_acronym_family_variants(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
        "all": [
            {
                "topic": "RAG",
                "fact_source_count": 20,
                "paper_count": 20,
                "velocity_score": 100.0,
            },
            {
                "topic": "retrieval_augmented_generation",
                "fact_source_count": 19,
                "paper_count": 19,
                "velocity_score": 99.0,
            },
            {
                "topic": "multi_agent_systems",
                "fact_source_count": 12,
                "paper_count": 12,
                "velocity_score": 80.0,
            },
        ],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "ai_research",
        set(),
        limit=3,
        min_sources=5,
    ) == ["RAG", "multi_agent_systems"]

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "ai_research",
        {"RAG"},
        limit=3,
        min_sources=5,
    ) == ["multi_agent_systems"]


def test_fresh_parent_topics_skip_recent_single_token_parent_family(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "metformin", "fact_source_count": 10, "paper_count": 10},
            {"topic": "metformin use", "fact_source_count": 9, "paper_count": 9},
            {"topic": "exercise", "fact_source_count": 7, "paper_count": 7},
        ],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        {"metformin treatment"},
        limit=3,
        min_sources=5,
    ) == ["exercise"]


def test_fresh_parent_topics_require_domain_seed_scope_for_anti_only_topics(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "anti_cancer", "fact_source_count": 20, "paper_count": 20},
            {"topic": "anti_tumor", "fact_source_count": 18, "paper_count": 18},
            {"topic": "caloric_restriction", "fact_source_count": 7, "paper_count": 7},
        ],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=3,
        min_sources=5,
    ) == ["caloric_restriction"]


def test_fresh_parent_topics_skip_generic_parent_fragments(tmp_path: Path) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "latest.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "all": [
            {"topic": "low_dose", "fact_source_count": 30, "paper_count": 30},
            {"topic": "age_related", "fact_source_count": 29, "paper_count": 29},
            {"topic": "anti_aging", "fact_source_count": 28, "paper_count": 28},
            {"topic": "low_dose_lithium", "fact_source_count": 6, "paper_count": 6},
        ],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=3,
        min_sources=5,
    ) == ["low_dose_lithium"]


def test_fresh_parent_topics_skip_stale_fullraw_offdomain_parents(
    tmp_path: Path,
) -> None:
    discovery = tmp_path / "_topics_discovery"
    discovery.mkdir()
    (discovery / "stale_fullraw.json").write_text(json.dumps({
        "domain": {"slug": "longevity_research"},
        "fullraw_seed_probe": {"receipts": [{"shards_searched": 42}]},
        "all": [
            {
                "topic": "inflammatory_bowel",
                "fact_source_count": 6,
                "paper_count": 6,
                "top_paper_title": (
                    "Serious infections in children born to mothers with "
                    "inflammatory bowel disease"
                ),
            },
            {
                "topic": "physical_activity",
                "fact_source_count": 8,
                "paper_count": 8,
                "top_paper_title": "The effect of physical activity on anti-infection immunity",
            },
            {
                "topic": "GDF11",
                "fact_source_count": 5,
                "paper_count": 5,
                "top_paper_title": "Anti-Aging Effects of GDF11 on Skin",
            },
            {
                "topic": "resveratrol",
                "fact_source_count": 5,
                "paper_count": 5,
                "top_paper_title": "Resveratrol transport and metabolism",
            },
        ],
    }), encoding="utf-8")

    assert daily._fresh_parent_topics_from_discovery(
        tmp_path,
        "longevity_research",
        set(),
        limit=4,
        min_sources=5,
    ) == ["GDF11", "resveratrol"]


def test_child_topics_from_queue_caps_slug_to_four_tokens() -> None:
    # A multi-word cluster label must not emit a 6-9 token word-salad child slug
    # (those are probed raw by the curator subprocess and exhaust the refresh
    # timeout). cap_topic_slug keeps every child at <= 4 tokens.
    queue = {
        "agent_repair_needed": [],
        "curation_needed": [{
            "topic": "metformin_treatment",
            "alpha_score": 50,
            "subtopic_recommendations": {
                "recommended": True,
                "reason": "source_coherent_child_cluster",
                "clusters": [
                    {
                        "label": "experienced_add_dorzagliatin_dose_baseline_group",
                        "member_fact_ids": [],
                    },
                ],
            },
        }],
    }
    children = daily._child_topics_from_queue(queue, set(), limit=10)
    assert children, "expected a child topic"
    for child in children:
        assert len([t for t in child.split("_") if t]) <= 4
        assert cap_topic_slug(child) == child


def test_child_topics_from_queue_skips_blocked_parent_family() -> None:
    queue = {
        "agent_repair_needed": [],
        "curation_needed": [{
            "topic": "exercise",
            "alpha_score": 90,
            "domain": {"slug": "longevity_research"},
            "subtopic_recommendations": {
                "recommended": True,
                "reason": "source_coherent_child_cluster",
                "clusters": [{
                    "label": "resistance_training_aerobic",
                    "member_fact_ids": ["1", "2", "3", "4", "5"],
                }],
            },
        }],
    }

    assert daily._child_topics_from_queue(
        queue, {"exercise"}, limit=10, domain="longevity_research",
    ) == []
