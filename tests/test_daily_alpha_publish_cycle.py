"""Daily alpha publish cycle tests.

Fixtures are domain-neutral; the orchestrator must not know topic-specific
rules.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.request import Request

from pytest import MonkeyPatch, raises

import scripts.daily_alpha_publish_cycle as daily


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

    assert ledger["status"] == "no_publishable_candidate"
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


def test_refresh_cycle_probes_existing_ready_queue_before_discovery(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    verdict = _verdict("ready")
    _memo(root, verdict)
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
    assert ledger["submitted_topic"] == "weak_curated_parent_bounded_claim"
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
    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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
    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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
    assert str(daily._DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT) in calls[0]
    assert "--fact-probe-topics" in calls[0]
    assert (
        calls[0][calls[0].index("--fact-probe-topics") + 1]
        == str(daily._DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT)
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
    assert out["ran_topics"] == ["parent_bounded_claim", "second_child"]
    assert calls[0].count("--priority-topic") == 2
    assert "parent_bounded_claim" in calls[0]
    assert "second_child" in calls[0]


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
    assert rows[0]["receipt_expansion"]["cited_bound_fact_ids"] == [
        "1", "2", "3", "4", "5",
    ]


def test_low_alpha_curation_cluster_can_seed_claim_candidate_when_source_coherent(
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

    assert len(rows) == 1
    assert rows[0]["topic"] == "weak_curated_parent_bounded_claim"
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
    assert calls == [(), ("parent_bounded_claim",), ()]


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
        == str(daily._DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT)
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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

    assert ledger["status"] == "no_publishable_candidate"
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
    assert len(seen_payload["source_bundle"]) == 5
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

    assert ledger["status"] == "no_publishable_candidate"
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
    assert payload["source_bundle"] == [
        {
            "title": "Primary field trial",
            "url": "https://example.test/primary",
            "doi": "10.1000/primary",
            "year": 2025,
            "evidence_type": "primary",
        },
    ]
    assert payload["citations"] == payload["source_bundle"]
    assert payload["evidence_bundle"]["bound_receipt_count"] == 2
    assert payload["evidence_bundle"]["bound_source_count"] == 2
    assert payload["evidence_bundle"]["source_bundle_count"] == 1
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


def test_apply_submission_decision_keeps_accept_without_url_pending() -> None:
    ledger: dict[str, Any] = {
        "submitted": 1,
        "published": 0,
        "submitted_topic": "accepted_without_url",
    }

    final = daily._apply_submission_decision(
        ledger,
        submission_id="sub-accepted-without-url",
        decision={"status": "complete", "decision": "accept"},
        page_fetcher=lambda _url: {"ok": False, "status": 0},
    )

    assert final == "pending"
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["final_verdict"] == "pending"
    assert ledger["accepted_pending_public_url"] is True
    assert ledger["published"] == 0
    assert ledger["public_page_check"]["status"] == "missing_public_url"


def test_public_alpha_urls_prefers_publication_url_over_artifact_ids() -> None:
    decision = {
        "dw_artifact_id": "claim_16e9ea4c16c74570",
        "publication": {
            "url": "https://researka.org/alpha/002f5fe8-38f1-4b5a-b1a1-3cdff72ddedd",
            "dw_artifact_id": "claim_b884f46fe51b4b25",
        },
    }

    urls = daily._public_alpha_urls(decision)

    assert urls[0] == "https://researka.org/alpha/002f5fe8-38f1-4b5a-b1a1-3cdff72ddedd"
    assert "https://researka.org/alpha/claim_16e9ea4c16c74570" not in urls
    assert "https://researka.org/alpha/claim_b884f46fe51b4b25" not in urls


def test_page_rendered_rejects_not_found_title_with_attrs() -> None:
    assert daily._page_rendered({
        "ok": True,
        "status": 200,
        "body": '<title data-next-head="">Alpha Memo Not Found</title>',
    }) is False


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


def test_systemd_publish_timer_has_full_refresh_budget() -> None:
    service = Path("deploy/systemd/researka-alpha-daily.service").read_text(
        encoding="utf-8",
    )
    timer = Path("deploy/systemd/researka-alpha-daily.timer").read_text(
        encoding="utf-8",
    )

    assert "--allow-tier2" in service
    assert "--max-refresh-batches 5" in service
    assert "--max-refresh-batches 2" not in service
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
    assert "--max-refresh-batches 5" in service
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
    assert "--warm-backlog" in service
    assert "--derived-topic-limit 5000" in service
    assert "--fact-probe-topics 250" in service
    assert "--cache-only" not in service
    assert "TimeoutStartSec=2700" in service
    assert "OnCalendar=*-*-* 01/4:05:00" in timer
    assert "Persistent=true" in timer
    assert "Unit=researka-alpha-cache-warm.service" in timer


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
        daily._write_json(cycle_dir / f"cycle-{len(calls)}.json", payload)
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
        daily._write_json(cycle_dir / f"cycle-{len(calls)}.json", payload)
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
    assert calls[1][-2:] == ["--exclude-topic", "curation_only"]
    assert ledger["refresh_batches"][1]["cooldown_reason"] == "retry_after_blocked_topic"


def test_source_floor_skipped_topics_are_excluded_next_batch(
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
            {"ran": [], "skipped_below_source_floor": ["acarbose"]}
            if len(calls) == 1 else
            {"ran": [{"topic": "fresh"}], "skipped_below_source_floor": []}
        )
        daily._write_json(cycle_dir / f"cycle-{len(calls)}.json", payload)
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
    assert calls[1][-2:] == ["--exclude-topic", "acarbose"]
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
    assert "--exclude-topic" not in calls[1]


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
        "cycle_exhausted_topic",
        "eligible",
    ]


def test_receipt_shape_mismatch_topic_is_excluded_from_next_refresh_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    mismatch = _verdict("mismatch")
    fresh = _verdict("fresh") | {
        "receipt_expansion": {"cited_bound_fact_ids": ["9", "8", "7"]},
    }
    _memo_with_receipt_shapes(root, mismatch, [
        {
            "canonical_phrase": "Exercise changed usual-care fatigue.",
            "population": "cancer survivors",
            "intervention": "exercise training",
            "endpoint": "fatigue",
        },
        {
            "canonical_phrase": "Qigong changed balance scores.",
            "population": "older adults",
            "intervention": "qigong",
            "endpoint": "balance",
        },
        {
            "canonical_phrase": "Resistance training changed strength.",
            "population": "frail adults",
            "intervention": "resistance training",
            "endpoint": "grip strength",
        },
        {
            "canonical_phrase": "Prehabilitation changed complications.",
            "population": "surgery patients",
            "intervention": "prehabilitation",
            "endpoint": "postoperative complications",
        },
        {
            "canonical_phrase": "Aerobic exercise changed walking distance.",
            "population": "heart failure patients",
            "intervention": "aerobic exercise",
            "endpoint": "six-minute walk distance",
        },
    ])
    _memo_with_source_receipts(root, fresh, 5)
    calls: list[list[str]] = []
    queues = iter([_queue(mismatch), _queue(mismatch, fresh)])

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
    assert calls[1][calls[1].index("--exclude-topic") + 1] == "mismatch"
    assert [row["status"] for row in ledger["considered"]] == [
        "receipt_shape_mismatch",
        "eligible",
    ]


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
    assert ledger["considered"][-1]["status"] == "cycle_exhausted_topic"


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
