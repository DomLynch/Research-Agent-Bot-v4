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

from pytest import MonkeyPatch

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


def test_partially_supported_reject_without_revision_text_is_not_retried() -> None:
    decision = {
        "claim_support_verdict": "partially_supported",
        "decision": "reject",
        "resubmission": {"allowed": True},
    }

    assert daily._repairable_rejection(decision) is False


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


def test_unsupported_reject_with_resubmission_allowed_is_not_retried() -> None:
    decision = {
        "claim_support_verdict": "unsupported",
        "decision": "reject",
        "major_issues": ["The cited receipts do not support the thesis."],
        "resubmission": {"allowed": True},
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

    assert calls["n"] == 3  # baseline, fast unchanged, one warm-backlog try
    assert warm_flags == [False, False, True]
    assert ledger["status"] == "no_publishable_candidate"
    assert ledger["refresh_backlog_escalation"] == {
        "after_batch": 2,
        "reason": "queue_unchanged_no_candidate",
    }
    assert (ledger.get("refresh_early_exit", {}).get("reason")
            == "queue_unchanged_no_candidate")


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
        "## Context receipts\n\n"
        "- boundary receipt\n\n"
        "## Provenance / priority\n\n"
        "- **Run bundle SHA-256:** `internal`\n",
        encoding="utf-8",
    )

    payload = daily._submission_payload(verdict, root / "runs")

    assert not payload["markdown"].startswith("# Alpha memo")
    assert "**Alpha score:**" not in payload["markdown"]
    assert "**Alpha triage:**" not in payload["markdown"]
    assert "## Provenance / priority" not in payload["markdown"]
    assert "Run bundle SHA-256" not in payload["markdown"]
    assert payload["abstract"] == "Direct receipts support a bounded, testable signal."
    assert payload["summary"] == "Direct receipts support a bounded, testable signal."
    assert "hypothesis-generating alpha memo, not confirmatory evidence" in payload["markdown"]
    assert "Boundary evidence only" in payload["markdown"]
    assert payload["evidence_bundle"]["context_sources_are_not_direct_support"] is True


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
    assert "--with-pico-enrich" not in calls[0][0]
    assert calls[0][0][-4:] == ["--top", "5", "--cooldown-hours", "2"]
    assert calls[0][1] == 1200


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

    assert calls[0][-4:] == ["--top", "5", "--cooldown-hours", "0.5"]


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

    assert submitted == ["repair_first", "repair_first"]
    assert len(calls) == 1
    assert ledger["status"] == "published"
    assert ledger["refresh_batches"][1]["note"] == "skipped_after_repairable_submission"
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == [
        "reviewer_rejected",
        "published",
    ]


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

    assert submitted == ["never_satisfies_reviewer"] * 4
    assert refreshes == 4
    assert ledger["status"] == "submit_retry_exhausted"
    assert ledger["last_attempt_status"] == "reviewer_revise"
    assert [attempt["status"] for attempt in ledger["cycle_attempts"]] == [
        "reviewer_revise",
        "reviewer_revise",
        "reviewer_revise",
        "reviewer_revise",
    ]
    assert ledger["considered"][-1]["status"] == "duplicate_submission_fingerprint"
    assert not ledger["considered"][-1].get("retry_after_rejection")


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
