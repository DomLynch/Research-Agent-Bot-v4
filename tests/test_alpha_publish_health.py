from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import scripts.check_alpha_publish_health as health


def _write_ledger(root: Path, name: str, payload: dict[str, object]) -> Path:
    path = root / "_daily_ledger" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_health_summary_reports_latest_published_ledger(tmp_path: Path) -> None:
    stale = _write_ledger(tmp_path, "2026-05-31T00-00-00Z.json", {
        "status": "no_publishable_candidate",
        "submitted": 0,
        "published": 0,
    })
    latest = _write_ledger(tmp_path, "2026-06-01T02-06-49Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "grid_storage",
        "public_url": "https://researka.org/alpha/example",
        "queue_counts": {"ready_to_publish": 1, "not_ready": 2},
        "publish_summary": {
            "top_blockers": {"direct_source_floor_below_min": 3},
            "next_action": "watch_decision_or_public_page",
        },
        "cycle_attempts": [{"batch": 1, "topic": "grid_storage", "status": "published"}],
        "considered": [{"status": "eligible"}, {"status": "cycle_exhausted_topic"}],
    })
    os.utime(stale, (1, 1))
    os.utime(latest, (2, 2))

    summary = health.summarize_latest(
        tmp_path,
        now=dt.datetime.fromtimestamp(latest.stat().st_mtime, tz=dt.UTC),
    )

    assert summary["ok"] is True
    assert summary["status"] == "published"
    assert summary["topic"] == "grid_storage"
    assert summary["attempts"] == [{"batch": 1, "topic": "grid_storage", "status": "published"}]
    assert summary["considered_counts"] == {"cycle_exhausted_topic": 1, "eligible": 1}
    assert summary["queue_counts"] == {"ready_to_publish": 1, "not_ready": 2}
    assert summary["top_blockers"] == {"direct_source_floor_below_min": 3}
    assert summary["next_action"] == "watch_decision_or_public_page"


def test_check_url_requires_rendered_public_page(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T02-06-49Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "grid_storage",
        "public_url": "https://researka.org/papers/page-shell",
    })
    monkeypatch.setattr(
        health,
        "_public_url_status",
        lambda *_args, **_kwargs: {
            "http_status": 200,
            "rendered": False,
            "status": "not_rendered",
        },
    )

    summary = health.summarize_latest(tmp_path, check_url=True)

    assert summary["ok"] is False
    assert summary["public_url_status"] == 200
    assert summary["public_page_status"] == "not_rendered"


def test_check_url_accepts_rendered_public_page(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T02-06-49Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "grid_storage",
        "public_url": "https://researka.org/papers/live",
    })
    monkeypatch.setattr(
        health,
        "_public_url_status",
        lambda *_args, **_kwargs: {
            "http_status": 200,
            "rendered": True,
            "status": "rendered",
        },
    )

    summary = health.summarize_latest(tmp_path, check_url=True)

    assert summary["ok"] is True
    assert summary["public_url_status"] == 200
    assert summary["public_page_status"] == "rendered"


def test_health_summary_prefers_ledger_timestamp_over_sync_mtime(tmp_path: Path) -> None:
    latest = _write_ledger(tmp_path, "2026-06-01T21-59-41Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "caloric_restriction",
        "public_url": "https://researka.org/alpha/latest",
    })
    stale_pending = _write_ledger(tmp_path, "2026-06-01T08-29-49Z.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "klotho",
    })
    os.utime(latest, (1, 1))
    os.utime(stale_pending, (2, 2))

    summary = health.summarize_latest(tmp_path)

    assert summary["ledger"] == "2026-06-01T21-59-41Z.json"
    assert summary["ok"] is True
    assert summary["topic"] == "caloric_restriction"


def test_health_summary_includes_suffixed_cycle_ledgers(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "2026-06-01T21-59-41Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "caloric_restriction",
        "public_url": "https://researka.org/alpha/latest",
    })
    _write_ledger(tmp_path, "2026-06-01t22-04-11z-decision-f61706f7.json", {
        "status": "reviewer_revise",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "ignored_decision_probe",
    })
    _write_ledger(tmp_path, "probe-20260601T220500Z.json", {
        "status": "dry_run_selected",
        "submitted": 0,
        "published": 0,
    })
    _write_ledger(tmp_path, "2026-06-01T22-06-49Z-repair-source-lit-v3.json", {
        "status": "reviewer_revise",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "metformin use",
    })

    summary = health.summarize_latest(tmp_path)

    assert summary["ledger"] == "2026-06-01T22-06-49Z-repair-source-lit-v3.json"
    assert summary["ok"] is False
    assert summary["status"] == "reviewer_revise"
    assert summary["topic"] == "metformin use"


def test_health_summary_includes_manual_proof_cycle_ledgers(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "2026-06-01T02-38-47Z.json", {
        "status": "submit_retry_exhausted",
        "submitted": 0,
        "published": 0,
        "reason": "stale failed ledger",
    })
    _write_ledger(tmp_path, "2026-06-01Tlive-submit-reprobe-proofZ.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "exercise",
        "public_url": "https://researka.org/papers/exercise",
    })
    _write_ledger(tmp_path, "2026-06-01Tlive-submit-reprobe-proofZ-decision-f61706f7.json", {
        "status": "reviewer_revise",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "ignored_decision_probe",
    })

    summary = health.summarize_latest(tmp_path)

    assert summary["ledger"] == "2026-06-01Tlive-submit-reprobe-proofZ.json"
    assert summary["ok"] is True
    assert summary["status"] == "published"
    assert summary["topic"] == "exercise"


def test_health_summary_ignores_probe_and_decision_ledgers(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "probe-20260601T080818Z.json", {
        "status": "dry_run_selected",
        "submitted": 0,
        "published": 0,
    })
    _write_ledger(tmp_path, "2026-06-01t21-59-41z-decision-f61706f7.json", {
        "status": "reviewer_revise",
        "submitted": 1,
        "published": 0,
    })
    _write_ledger(tmp_path, "2026-06-01T21-59-41Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "caloric_restriction",
        "public_url": "https://researka.org/alpha/latest",
    })

    summary = health.summarize_latest(tmp_path)

    assert summary["ledger"] == "2026-06-01T21-59-41Z.json"
    assert summary["ok"] is True


def test_expect_published_exits_nonzero_for_failed_latest_ledger(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "no_publishable_candidate",
        "submitted": 0,
        "published": 0,
        "reason": "no eligible non-duplicate memo",
    })

    assert health.main(["--runs-root", str(tmp_path), "--expect-published"]) == 2


def test_next_candidate_summary_reports_retry_risk(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def select_candidate(*_args: object, **_kwargs: object) -> tuple[dict[str, str], list[dict[str, Any]]]:
        seen.update(_kwargs)
        return (
            {"topic": "grid_storage", "decision": "ready_to_publish", "run_dir": "runs/grid"},
            [
                {"topic": "old", "status": "cycle_exhausted_topic"},
                {
                    "topic": "grid_storage",
                    "status": "eligible",
                    "retry_after_rejection": True,
                    "retry_attempt_count": 2,
                },
            ],
        )

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: {
            "ready_to_publish": [{"topic": "grid_storage"}],
            "agent_repair_needed": [],
            "curation_needed": [{"topic": "old"}],
            "not_ready": [],
        },
        _recently_published_topics=lambda *_args, **_kwargs: {"old"},
        _recent_submission_topics=lambda *_args, **_kwargs: {"submitted"},
        _recent_negative_topics=lambda *_args, **_kwargs: {"rejected"},
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(
        tmp_path, cycle_module=fake_cycle, domain="ai_research",
    )

    assert summary["topic"] == "grid_storage"
    assert seen["domain"] == "ai_research"
    assert seen["blocked_topics"] == {"old", "submitted", "rejected"}
    assert summary["queue_counts"] == {
        "ready_to_publish": 1,
        "agent_repair_needed": 0,
        "curation_needed": 1,
        "not_ready": 0,
    }
    assert summary["retry_after_rejection"] is True
    assert summary["retry_attempt_count"] == 2
    assert summary["considered_counts"] == {"cycle_exhausted_topic": 1, "eligible": 1}


def test_health_summary_can_sync_pending_submission(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path, "2026-06-01T08-29-49Z.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "klotho",
        "submission_id": "sub-1",
    })

    def sync_submission_decisions(runs_root: Path) -> dict[str, int]:
        data = json.loads(ledger.read_text(encoding="utf-8"))
        data.update({
            "status": "published",
            "published": 1,
            "published_topic": "klotho",
            "public_url": "https://researka.org/alpha/klotho",
            "final_verdict": "accepted",
        })
        ledger.write_text(json.dumps(data), encoding="utf-8")
        return {"checked": 1, "updated": 1, "published": 1, "pending": 0}

    fake_cycle = SimpleNamespace(sync_submission_decisions=sync_submission_decisions)

    summary = health.summarize_latest(
        tmp_path,
        sync_pending_decisions=True,
        cycle_module=fake_cycle,
        now=dt.datetime.fromtimestamp(ledger.stat().st_mtime, tz=dt.UTC),
    )

    assert summary["ok"] is True
    assert summary["status"] == "published"
    assert summary["published"] == 1
    assert summary["decision_sync"] == {
        "checked": 1, "updated": 1, "published": 1, "pending": 0,
    }


def test_health_summary_falls_back_to_considered_counts_for_old_ledgers(
    tmp_path: Path,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "considered": [
            {"status": "agent_repair_needed"},
            {"status": "agent_repair_needed"},
            {"status": "memo_missing_audit_sidecars"},
        ],
    })

    summary = health.summarize_latest(tmp_path)

    assert summary["top_blockers"] == {
        "agent_repair_needed": 2,
        "memo_missing_audit_sidecars": 1,
    }


def test_health_summary_derives_duplicate_exhaustion_reason_for_old_ledgers(
    tmp_path: Path,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "reason": "no eligible non-duplicate memo",
        "considered": [
            {"status": "duplicate_submission_fingerprint"},
            {"status": "duplicate_published_bundle"},
            {"status": "cycle_exhausted_topic"},
        ],
    })

    summary = health.summarize_latest(tmp_path)

    assert (
        summary["reason"]
        == "all candidates were duplicate, already published, or topic/family exhausted"
    )
