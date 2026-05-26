"""Daily alpha publish cycle tests.

Fixtures are domain-neutral; the orchestrator must not know topic-specific
rules.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any
from urllib.request import Request

from pytest import MonkeyPatch

import scripts.daily_alpha_publish_cycle as daily


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


def _memo(root: Path, verdict: dict[str, Any]) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    (run / "alpha_memo.md").write_text("# Alpha memo\n", encoding="utf-8")


def _memo_with_source_receipts(root: Path, verdict: dict[str, Any], count: int) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    ids = [str(i + 1) for i in range(count)]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n",
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


def test_memo_fingerprint_is_stable_across_headline_rewording() -> None:
    left = _verdict()
    right = _verdict() | {"headline": "Reworded public headline"}

    assert daily.memo_fingerprint(left) == daily.memo_fingerprint(right)


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
            + "\n",
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
    _memo(root, verdict)

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

    payload = daily._submission_payload(verdict, root / "runs")

    assert payload["artifact_type"] == "alpha_memo"
    assert payload["article_type"] == "alpha_memo"
    assert payload["author_agent_id"] == "agent-v4-alpha-memo"
    assert payload["agent_id"] == "agent-v4-alpha-memo"
    assert payload["topic"] == "grid_storage"
    assert payload["markdown"] == "# Alpha memo\n"
    assert "sections" not in payload
    assert "source_bundle" in payload
    assert "source_papers" in payload["evidence_bundle"]


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
    _memo(root, verdict)

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


def test_run_cycle_syncs_prior_submission_decisions(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    daily._write_json(root / "_daily_ledger" / "2026-05-21.json", {
        "status": "submitted_to_researka",
        "submission": {"attempts": [{"response": {"submission": {"id": "sub_123"}}}]},
    })

    ledger = daily.run_cycle(
        runs_root=root,
        date="2026-05-22",
        queue=_queue(),
        decision_fetcher=lambda _submission_id: {
            "status": "complete",
            "decision": "accept",
        },
    )

    patched = json.loads(
        (root / "_daily_ledger" / "2026-05-21.json").read_text(encoding="utf-8")
    )
    assert ledger["decision_sync"]["updated"] == 1
    assert patched["final_verdict"] == "accepted"


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
