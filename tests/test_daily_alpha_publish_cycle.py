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
            "source_papers": [
                {"doi": "10.1000/a", "title": "Reserve threshold paper"},
                {"doi": "10.1000/b", "title": "Reserve replication"},
            ],
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
    assert payload["author_agent_id"] == "agent-v4-alpha-memo"
    assert payload["agent_id"] == "agent-v4-alpha-memo"
    assert payload["topic"] == "grid_storage"
    assert payload["markdown"] == "# Alpha memo\n"
    assert "sections" not in payload
    assert "source_bundle" not in payload


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
