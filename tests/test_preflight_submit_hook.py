from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

import scripts.daily_alpha_publish_cycle as daily


def _payload(body: str) -> dict[str, Any]:
    return {
        "artifact_type": "alpha_memo",
        "title": "Bounded memo",
        "abstract": "This may be limited.",
        "markdown": body,
        "source_bundle": [
            {"title": "Limited trial", "doi": "10.1000/abc", "excerpt": "limited signal"},
        ],
        "evidence_bundle": {},
        "content_hash": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def _enable_preflight(monkeypatch: MonkeyPatch, mode: str = "enforce") -> None:
    polish_root = Path(__file__).resolve().parents[2] / "researka-preflight-qa"
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", mode)
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(polish_root))


def test_preflight_enforce_cleans_payload_and_updates_hash(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    _enable_preflight(monkeypatch)
    body = "## Result\n\nThis may be limited.\n\nThis may be limited."

    checked, report = daily._run_preflight_qa(_payload(body), tmp_path)

    assert checked is not None
    assert report is not None
    assert report["status"] == "pass"
    assert checked["markdown"].count("This may be limited.") == 1
    assert checked["content_hash"] == (
        "sha256:" + hashlib.sha256(str(checked["markdown"]).encode("utf-8")).hexdigest()
    )
    assert checked["evidence_bundle"]["preflight_qa"]["status"] == "pass"
    assert (tmp_path / "researka_preflight_report.json").exists()
    assert (tmp_path / "researka_preflight_cleaned_payload.json").exists()


def test_preflight_shadow_reports_but_keeps_original_payload(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    _enable_preflight(monkeypatch, "shadow")
    payload = _payload("## Result\n\nThis cites DOI 10.9999/missing.")
    original_hash = payload["content_hash"]

    checked, report = daily._run_preflight_qa(payload, tmp_path)

    assert checked is payload
    assert report is not None
    assert report["status"] == "block"
    assert checked["content_hash"] == original_hash
    assert checked["evidence_bundle"]["preflight_qa"]["status"] == "block"
    assert "doi_not_in_source_bundle" in checked["evidence_bundle"]["preflight_qa"][
        "blocked_reason_codes"
    ]


def _verdict(topic: str = "grid_storage") -> dict[str, Any]:
    return {
        "run_dir": f"runs/{topic}-evidence-ts",
        "topic": topic,
        "decision": "ready_to_publish",
        "publish_tier": "TIER_1",
        "maturity_level": "L5",
        "headline": "Storage reserves flip after threshold pricing",
        "confidence_label": "evidence_backed_signal",
        "alpha_score": 90,
        "surface_type": "publish_alpha_memo",
        "domain": {"slug": "longevity"},
        "axes": {"source_papers": [{"doi": "10.1000/abc", "title": "Limited trial"}]},
    }


def _queue(verdict: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "ready_to_publish": [verdict],
        "needs_operator_review": [],
        "curation_needed": [],
    }


def _memo(root: Path, verdict: dict[str, Any]) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "**Headline:** Storage reserves flip after threshold pricing\n\n"
        "## Why this is surprising\n\n"
        "This cites DOI 10.9999/missing.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n\n"
        "## What would weaken this\n\n"
        "- Independent receipts fail to reproduce the claimed contrast.\n",
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps([{
        "fact_id": "1",
        "canonical_phrase": "Matched endpoint improved in the target population.",
        "source_paper": {"doi": "10.1000/abc", "title": "Limited trial"},
    }]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": "1", "lane": "A_core"}],
    }), encoding="utf-8")
    for name, payload in {
        "claim_receipt_matrix.json": {"direct_sources": 1},
        "typed_counter_evidence.json": {"items": []},
        "novelty_delta.json": {"novelty_delta": {"label": "contradictory"}},
        "memo_audit.json": {"verdict": "supported"},
    }.items():
        run.joinpath(name).write_text(json.dumps(payload), encoding="utf-8")


def test_run_cycle_enforce_blocks_before_submit(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    _enable_preflight(monkeypatch)
    verdict = _verdict()
    _memo(tmp_path, verdict)
    submitted = False

    def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal submitted
        submitted = True
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-10",
        domain="longevity",
        queue=_queue(verdict),
        submit=True,
        submitter=submitter,
        min_submit_sources=1,
        min_direct_submit_sources=1,
        retraction_mode="crossref",
        fetcher=lambda _doi: {"message": {}},
        decision_poll_attempts=0,
    )

    assert submitted is False
    assert ledger["status"] == "preflight_qa_blocked"
    assert ledger["preflight_qa"]["status"] == "block"
    assert "doi_not_in_source_bundle" in ledger["preflight_qa"]["blocked_reason_codes"]
