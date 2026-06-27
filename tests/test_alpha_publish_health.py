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


def test_health_summary_does_not_let_future_ledgers_shadow_fresher_runs(
    tmp_path: Path,
) -> None:
    future_stale = _write_ledger(tmp_path, "9999-06-01T21-59-41Z-business.json", {
        "status": "candidate_refresh_failed",
        "submitted": 0,
        "published": 0,
        "domain_slug": "business_research",
        "considered": [{
            "status": "no_bundle",
            "blockers": ["no_source_diverse_bundle", "fullraw_complete_receipt_missing"],
        }],
    })
    current = _write_ledger(tmp_path, "2026-06-01T08-29-49Z-business.json", {
        "status": "candidate_refresh_failed",
        "submitted": 0,
        "published": 0,
        "domain_slug": "business_research",
        "considered": [{
            "status": "no_bundle",
            "blockers": ["no_source_diverse_bundle", "fullraw_probe_busy"],
        }],
    })
    os.utime(future_stale, (1, 1))
    os.utime(current, (2, 2))

    summary = health.summarize_latest(tmp_path, domain="business_research")

    assert summary["ledger"] == "2026-06-01T08-29-49Z-business.json"
    assert summary["top_blockers"] == {
        "candidate_refresh_failed": 1,
        "fullraw_probe_busy": 1,
        "no_bundle": 1,
        "no_source_diverse_bundle": 1,
    }


def test_health_summary_can_scope_latest_ledger_by_domain(
    tmp_path: Path, capsys: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T08-29-49Z-business.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "domain_slug": "business_research",
        "queue_counts": {"ready_to_publish": 0, "not_ready": 2},
    })
    _write_ledger(tmp_path, "2026-06-01T21-59-41Z-longevity.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "domain": {"slug": "longevity_research"},
        "published_topic": "fisetin",
        "public_url": "https://researka.org/alpha/fisetin",
    })

    assert health.summarize_latest(tmp_path)["ok"] is True

    summary = health.summarize_latest(tmp_path, domain="business_research")
    assert summary["ok"] is False
    assert summary["domain"] == "business_research"
    assert summary["ledger"] == "2026-06-01T08-29-49Z-business.json"
    assert summary["status"] == "no_fresh_candidate"
    assert summary["queue_counts"] == {"ready_to_publish": 0, "not_ready": 2}

    assert health.main([
        "--runs-root", str(tmp_path), "--domain", "business_research",
        "--expect-published",
    ]) == 2
    assert json.loads(capsys.readouterr().out)["domain"] == "business_research"


def test_health_main_reports_multi_domain_failures(tmp_path: Path, capsys: Any) -> None:
    _write_ledger(tmp_path, "2026-06-01T08-29-49Z-business.json", {
        "status": "candidate_refresh_failed",
        "submitted": 0,
        "published": 0,
        "domain_slug": "business_research",
    })
    _write_ledger(tmp_path, "2026-06-01T21-59-41Z-longevity.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "domain_slug": "longevity_research",
    })

    assert health.main([
        "--runs-root", str(tmp_path),
        "--domains", "longevity_research,business_research",
        "--expect-published",
    ]) == 2
    summary = json.loads(capsys.readouterr().out)

    assert summary["ok"] is False
    assert summary["failed_domains"] == ["business_research"]
    assert summary["domains"]["longevity_research"]["ok"] is True
    assert summary["domains"]["business_research"]["status"] == "candidate_refresh_failed"


def test_health_summary_reports_active_systemd_run_without_greenlighting(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T08-29-49Z-business.json", {
        "status": "candidate_refresh_failed",
        "submitted": 0,
        "published": 0,
        "domain_slug": "business_research",
    })

    def fake_run(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "ActiveState=activating\n"
                "SubState=start\n"
                "Result=success\n"
                "ExecMainStatus=0\n"
                "MainPID=1234\n"
            ),
        )

    monkeypatch.setattr(health.__dict__["subprocess"], "run", fake_run)

    summary = health.summarize_latest(
        tmp_path,
        domain="business_research",
        systemd_unit="researka-alpha-business-research.service",
    )

    assert summary["ok"] is False
    assert summary["published"] == 0
    assert summary["active_run"] == {
        "unit": "researka-alpha-business-research.service",
        "returncode": 0,
        "ActiveState": "activating",
        "SubState": "start",
        "Result": "success",
        "ExecMainStatus": "0",
        "MainPID": "1234",
        "running": True,
    }


def test_health_main_writes_blocker_summary_artifact(tmp_path: Path, capsys: Any) -> None:
    _write_ledger(tmp_path, "2026-06-01T08-29-49Z-business.json", {
        "status": "candidate_refresh_failed",
        "reason": "no_source_diverse_bundle",
        "submitted": 0,
        "published": 0,
        "domain_slug": "business_research",
        "queue_counts": {
            "ready_to_publish": 0,
            "agent_repair_needed": 1,
            "curation_needed": 2,
            "not_ready": 0,
        },
        "considered": [{
            "status": "no_bundle",
            "blockers": ["no_source_diverse_bundle", "fullraw_probe_busy"],
        }],
        "publish_summary": {
            "top_blockers": {
                "candidate_refresh_failed": 1,
                "no_source_diverse_bundle": 1,
            },
            "next_action": "wait_for_fullraw_completion",
            "public_url_status": None,
        },
    })

    assert health.main([
        "--runs-root", str(tmp_path),
        "--domains", "business_research",
        "--expect-published",
        "--check-url",
        "--show-next-candidate",
        "--write-summary",
    ]) == 2

    stdout = json.loads(capsys.readouterr().out)
    artifact = tmp_path / "_daily_ledger" / "alpha_publish_health_summary.json"
    assert stdout["summary_artifact"] == str(artifact)
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    business = summary["domains"]["business_research"]
    assert summary["failed_domains"] == ["business_research"]
    assert summary["published"] == 0
    assert summary["submitted"] == 0
    assert summary["candidates_considered"] == 1
    assert summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 0,
    }
    assert summary["top_blockers"] == {
        "candidate_refresh_failed": 1,
        "no_source_diverse_bundle": 1,
    }
    assert summary["next_action"] == "wait_for_fullraw_completion"
    assert summary["public_url_status"] == {"business_research": None}
    assert business["top_blockers"]["candidate_refresh_failed"] == 1
    assert business["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 0,
    }
    assert business["ledger_queue_counts"]["curation_needed"] == 2
    assert business["considered_counts"] == {"no_bundle": 1}
    assert business["next_action"] == "wait_for_fullraw_completion"
    assert business["public_url_status"] is None
    assert business["next_candidate"]["supply_status"] == "no_ready_rows"


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
    alphabetically_later = _write_ledger(tmp_path, "2026-06-01Tsource-floor-cooldown-proofZ.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "reason": "stale alphabetically later manual ledger",
    })
    latest = _write_ledger(tmp_path, "2026-06-01Tlive-submit-reprobe-proofZ.json", {
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
    stale_manual_time = dt.datetime(2026, 6, 1, 3, 0, 0, tzinfo=dt.UTC).timestamp()
    latest_manual_time = dt.datetime(2026, 6, 1, 4, 0, 0, tzinfo=dt.UTC).timestamp()
    os.utime(alphabetically_later, (stale_manual_time, stale_manual_time))
    os.utime(latest, (latest_manual_time, latest_manual_time))

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


def test_health_summary_ignores_newer_dry_run_ledgers(tmp_path: Path) -> None:
    published = _write_ledger(tmp_path, "2026-06-01T21-59-41Z.json", {
        "status": "published",
        "submitted": 1,
        "published": 1,
        "published_topic": "telomere",
        "public_url": "https://researka.org/alpha/telomere",
    })
    dry_run = _write_ledger(tmp_path, "2026-06-01Tdryrun-fullraw2Z.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "reason": "manual dry-run smoke",
    })
    os.utime(published, (1, 1))
    os.utime(dry_run, (2, 2))

    summary = health.summarize_latest(tmp_path)

    assert summary["ledger"] == "2026-06-01T21-59-41Z.json"
    assert summary["ok"] is True
    assert summary["topic"] == "telomere"


def test_expect_published_exits_nonzero_for_failed_latest_ledger(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "no_publishable_candidate",
        "submitted": 0,
        "published": 0,
        "reason": "no eligible non-duplicate memo",
    })

    assert health.main(["--runs-root", str(tmp_path), "--expect-published"]) == 2


def test_started_latest_ledger_reports_terminal_status_blocker(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "started",
        "submitted": 0,
        "published": 0,
    })

    summary = health.summarize_latest(tmp_path)

    assert summary["ok"] is False
    assert summary["status"] == "started"
    assert summary["reason"] == "cycle_started_no_terminal_status"
    assert summary["top_blockers"] == {"cycle_started_no_terminal_status": 1}
    assert summary["next_action"] == "building_current_publish_queue"


def test_expect_published_prints_no_publish_blocker_summary(
    tmp_path: Path, capsys: Any, monkeypatch: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "public_url": "https://researka.org/alpha/missing",
        "queue_counts": {"ready_to_publish": 0, "curation_needed": 3},
        "publish_summary": {
            "top_blockers": {"direct_source_floor_below_min": 3},
            "next_action": "refresh_or_expand_candidate_supply",
        },
    })
    monkeypatch.setattr(
        health,
        "_public_url_status",
        lambda *_args, **_kwargs: {
            "http_status": 404,
            "rendered": False,
            "status": "not_rendered",
        },
    )

    assert health.main([
        "--runs-root", str(tmp_path), "--expect-published", "--check-url",
    ]) == 2
    summary = json.loads(capsys.readouterr().out)

    assert summary["ok"] is False
    assert summary["status"] == "no_fresh_candidate"
    assert summary["queue_counts"] == {"ready_to_publish": 0, "curation_needed": 3}
    assert summary["top_blockers"] == {
        "direct_source_floor_below_min": 3,
        "no_fresh_candidate": 1,
    }
    assert summary["next_action"] == "refresh_or_expand_candidate_supply"
    assert summary["public_url_status"] == 404
    assert summary["public_page_status"] == "not_rendered"


def test_sla_monitor_full_command_fails_red_with_blocker_summary(
    tmp_path: Path, capsys: Any, monkeypatch: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z-finance.json", {
        "status": "candidate_refresh_failed",
        "submitted": 0,
        "published": 0,
        "domain_slug": "finance_research",
        "public_url": "https://researka.org/alpha/missing-finance",
        "queue_counts": {"ready_to_publish": 0, "not_ready": 4},
        "publish_summary": {
            "considered": 4,
            "top_blockers": {"no_source_diverse_bundle": 4},
            "next_action": "inspect_refresh_failure",
        },
    })
    monkeypatch.setattr(
        health,
        "_public_url_status",
        lambda *_args, **_kwargs: {
            "http_status": 404,
            "rendered": False,
            "status": "not_rendered",
        },
    )

    assert health.main([
        "--runs-root", str(tmp_path),
        "--domain", "finance_research",
        "--expect-published",
        "--check-url",
        "--sync-pending-decisions",
        "--show-next-candidate",
    ]) == 2
    summary = json.loads(capsys.readouterr().out)

    assert summary["ok"] is False
    assert summary["domain"] == "finance_research"
    assert summary["status"] == "candidate_refresh_failed"
    assert summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 0,
    }
    assert summary["ledger_queue_counts"] == {"ready_to_publish": 0, "not_ready": 4}
    assert summary["top_blockers"] == {
        "no_source_diverse_bundle": 4,
        "candidate_refresh_failed": 1,
    }
    assert summary["next_action"] == "inspect_refresh_failure"
    assert summary["public_url_status"] == 404
    assert summary["public_page_status"] == "not_rendered"
    assert summary["current_actionable_ready_to_publish"] == 0
    assert summary["next_candidate"]["supply_status"] == "no_ready_rows"


def test_health_summary_does_not_double_count_stored_terminal_blocker(
    tmp_path: Path,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z-finance.json", {
        "status": "candidate_refresh_failed",
        "submitted": 0,
        "published": 0,
        "domain_slug": "finance_research",
        "publish_summary": {
            "top_blockers": {
                "candidate_refresh_failed": 1,
                "no_bundle": 12,
                "no_source_diverse_bundle": 12,
            },
            "next_action": "inspect_refresh_failure",
        },
    })

    summary = health.summarize_latest(tmp_path, domain="finance_research")

    assert summary["top_blockers"] == {
        "candidate_refresh_failed": 1,
        "no_bundle": 12,
        "no_source_diverse_bundle": 12,
    }


def test_expect_published_exits_nonzero_for_real_no_publish_statuses(
    tmp_path: Path,
) -> None:
    for idx, status in enumerate((
        "no_fresh_candidate",
        "domain_dry_run_only",
        "candidate_refresh_failed",
        "submit_retry_exhausted",
        "preflight_qa_blocked",
    ), start=1):
        _write_ledger(tmp_path, f"2026-06-01T01-04-0{idx}Z.json", {
            "status": status,
            "submitted": int(status == "submit_retry_exhausted"),
            "published": 0,
            "reason": status,
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


def test_next_candidate_summary_separates_raw_ready_from_actionable(
    tmp_path: Path,
) -> None:
    seen: dict[str, Any] = {}

    def build_queue(*_args: object, **kwargs: object) -> dict[str, list[dict[str, str]]]:
        seen.update(kwargs)
        return {
            "ready_to_publish": [{"topic": "exercise"}],
            "agent_repair_needed": [],
            "curation_needed": [],
            "not_ready": [],
        }

    def select_candidate(
        *_args: object, **_kwargs: object,
    ) -> tuple[None, list[dict[str, Any]]]:
        return None, [{
            "topic": "exercise",
            "status": "duplicate_submission_fingerprint",
            "blockers": ["source_dispersion"],
        }]

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=build_queue,
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(
        tmp_path, cycle_module=fake_cycle, domain="longevity_research",
    )

    assert summary["queue_counts"]["ready_to_publish"] == 1
    assert summary["actionable_ready_to_publish"] == 0
    assert summary["non_actionable_ready_to_publish"] == 1
    assert summary["supply_status"] == "ready_queue_blocked"
    assert summary["considered_counts"] == {"duplicate_submission_fingerprint": 1}
    assert summary["blocked_ready_reasons"] == {"duplicate_submission_fingerprint": 1}
    assert summary["blocked_ready_blockers"] == {"source_dispersion": 1}
    assert Path(seen["submitted_path"]).name == "_submitted_fingerprints.json"


def test_next_candidate_summary_falls_back_to_domain_queue_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "_publish_queue.business_research.json"
    sidecar.write_text(json.dumps({
        "ready_to_publish": [],
        "agent_repair_needed": [],
        "curation_needed": [],
        "not_ready": [{"topic": "business_model_performance"}],
    }), encoding="utf-8")
    seen: dict[str, Any] = {}

    def select_candidate(
        queue: dict[str, list[dict[str, str]]],
        *_args: object,
        **kwargs: object,
    ) -> tuple[None, list[dict[str, Any]]]:
        seen["queue"] = queue
        seen.update(kwargs)
        return None, [{"topic": "business_model_performance", "status": "no_ready_rows"}]

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("current queue unavailable")
        ),
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(
        tmp_path, cycle_module=fake_cycle, domain="business_research",
    )

    assert seen["queue"]["not_ready"] == [{"topic": "business_model_performance"}]
    assert seen["domain"] == "business_research"
    assert summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 1,
    }
    assert summary["supply_status"] == "no_ready_rows"


def test_next_candidate_summary_uses_not_ready_sidecar_without_rebuild(tmp_path: Path) -> None:
    sidecar = tmp_path / "_publish_queue.business_research.json"
    sidecar.write_text(json.dumps({
        "ready_to_publish": [],
        "agent_repair_needed": [],
        "curation_needed": [],
        "not_ready": [{
            "topic": "platform_strategy_network",
            "domain_slug": "business_research",
            "blockers": ["no_source_diverse_bundle", "fullraw_probe_busy"],
        }],
    }), encoding="utf-8")
    seen: dict[str, Any] = {}

    def select_candidate(queue: dict[str, Any], *_args: Any, **_kwargs: Any) -> tuple[None, list[dict[str, Any]]]:
        seen["queue"] = queue
        return None, [{"topic": "platform_strategy_network", "status": "no_ready_rows"}]

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("not-ready sidecar should avoid rebuilding queue")
        ),
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(
        tmp_path, cycle_module=fake_cycle, domain="business_research",
    )

    assert seen["queue"]["not_ready"][0]["domain_slug"] == "business_research"
    assert summary["queue_counts"]["not_ready"] == 1


def test_next_candidate_summary_uses_pre_memo_diagnostic_queue_rows(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "_business_diagnostics"
    diagnostics.mkdir()
    diagnostic_path = diagnostics / "business_research-platform_strategy_network.json"
    diagnostic_path.write_text(json.dumps({
        "domain": "business_research",
        "topic": "platform_strategy_network",
        "raw_fact_count": 0,
        "normalized_fact_count": 0,
        "a_core_fact_count": 0,
        "retrieval_trace": {
            "fullraw": {
                "status": "incomplete_receipt",
                "async_status": "queued",
                "partial_shard_search": True,
            },
        },
    }), encoding="utf-8")
    (diagnostics / "latest_sweep.business_research.json").write_text(json.dumps({
        "results": [{
            "domain": "business_research",
            "topic": "platform_strategy_network",
            "status": "no_bundle",
            "diagnostics": str(diagnostic_path),
        }],
    }), encoding="utf-8")
    seen: dict[str, Any] = {}

    def select_candidate(queue: dict[str, Any], *_args: Any, **_kwargs: Any) -> tuple[None, list[dict[str, Any]]]:
        seen["queue"] = queue
        return None, [{"topic": "platform_strategy_network", "status": "no_ready_rows"}]

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: {
            "ready_to_publish": [],
            "agent_repair_needed": [],
            "curation_needed": [],
            "not_ready": [],
        },
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(
        tmp_path, cycle_module=fake_cycle, domain="business_research",
    )

    row = seen["queue"]["not_ready"][0]
    assert row["domain_slug"] == "business_research"
    assert row["topic"] == "platform_strategy_network"
    assert row["blockers"] == ["no_source_diverse_bundle", "fullraw_probe_busy"]
    assert summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 1,
    }


def test_next_candidate_summary_prefers_rebuilt_queue_over_stale_sidecar(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "_publish_queue.finance_research.json"
    sidecar.write_text(json.dumps({
        "ready_to_publish": [{"topic": "stale_duplicate"}],
        "agent_repair_needed": [],
        "curation_needed": [],
        "not_ready": [],
    }), encoding="utf-8")

    def select_candidate(
        queue: dict[str, list[dict[str, str]]],
        *_args: object,
        **_kwargs: object,
    ) -> tuple[None, list[dict[str, Any]]]:
        assert queue["ready_to_publish"] == []
        return None, [{"topic": "current_blocked", "status": "no_ready_rows"}]

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: {
            "ready_to_publish": [],
            "agent_repair_needed": [],
            "curation_needed": [{"topic": "current_blocked"}],
            "not_ready": [],
        },
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(
        tmp_path, cycle_module=fake_cycle, domain="finance_research",
    )

    assert summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 1,
        "not_ready": 0,
    }
    assert summary["supply_status"] == "no_ready_rows"


def test_no_daily_ledger_still_reports_domain_sidecar_queue(tmp_path: Path) -> None:
    sidecar = tmp_path / "_publish_queue.finance_research.json"
    sidecar.write_text(json.dumps({
        "ready_to_publish": [],
        "agent_repair_needed": [],
        "curation_needed": [],
        "not_ready": [{"topic": "asset_pricing_replication"}],
    }), encoding="utf-8")

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("domain sidecar should avoid rebuilding queue")
        ),
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=lambda *_args, **_kwargs: (
            None,
            [{"topic": "asset_pricing_replication", "status": "no_ready_rows"}],
        ),
    )

    summary = health.summarize_latest(
        tmp_path,
        domain="finance_research",
        show_next_candidate=True,
        cycle_module=fake_cycle,
    )

    assert summary["ok"] is False
    assert summary["status"] == "no_daily_ledger"
    assert summary["published"] == 0
    assert summary["reason"] == "no_daily_ledger"
    assert summary["top_blockers"] == {"no_daily_ledger": 1}
    assert summary["next_action"] == "run_domain_publish_cycle"
    assert summary["public_url_status"] is None
    assert summary["public_page_status"] is None
    assert summary["current_queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 1,
    }


def test_no_daily_ledger_reports_active_systemd_run(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            returncode=0,
            stdout="ActiveState=active\nSubState=running\nMainPID=5678\n",
        )

    monkeypatch.setattr(health.__dict__["subprocess"], "run", fake_run)

    summary = health.summarize_latest(
        tmp_path,
        domain="business_research",
        systemd_unit="researka-alpha-business-research.service",
    )

    assert summary["ok"] is False
    assert summary["status"] == "no_daily_ledger"
    assert summary["active_run"]["running"] is True
    assert summary["active_run"]["MainPID"] == "5678"


def test_health_summary_prefers_current_queue_counts_over_stale_ledger(
    tmp_path: Path,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z-ai.json", {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "domain_slug": "ai_research",
        "queue_counts": {"ready_to_publish": 2, "curation_needed": 9},
        "publish_summary": {
            "top_blockers": {"duplicate_submission_fingerprint": 2},
            "next_action": "refresh_or_expand_candidate_supply",
        },
    })
    sidecar = tmp_path / "_publish_queue.ai_research.json"
    sidecar.write_text(json.dumps({
        "ready_to_publish": [],
        "agent_repair_needed": [{"topic": "rag"}],
        "curation_needed": [{"topic": "open_source_models"}],
        "not_ready": [],
    }), encoding="utf-8")

    fake_cycle = SimpleNamespace(
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES=5,
        _DEFAULT_MIN_SUBMIT_SOURCES=5,
        _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS=30,
        _build_queue=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("current queue unavailable")
        ),
        _recently_published_topics=lambda *_args, **_kwargs: set(),
        _recent_submission_topics=lambda *_args, **_kwargs: set(),
        _recent_negative_topics=lambda *_args, **_kwargs: set(),
        select_candidate=lambda *_args, **_kwargs: (
            None,
            [{"topic": "rag", "status": "agent_repair_needed"}],
        ),
    )

    summary = health.summarize_latest(
        tmp_path,
        domain="ai_research",
        show_next_candidate=True,
        cycle_module=fake_cycle,
    )

    assert summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 1,
        "curation_needed": 1,
        "not_ready": 0,
    }
    assert summary["current_queue_counts"] == summary["queue_counts"]
    assert summary["ledger_queue_counts"] == {
        "ready_to_publish": 2,
        "curation_needed": 9,
    }
    assert summary["current_actionable_ready_to_publish"] == 0
    assert summary["next_candidate"]["supply_status"] == "no_ready_rows"


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


def test_sync_pending_decisions_does_not_greenlight_unpublished(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    _write_ledger(tmp_path, "2026-06-01T08-29-49Z.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "klotho",
        "submission_id": "sub-1",
    })

    fake_cycle = SimpleNamespace(
        sync_submission_decisions=lambda _runs_root: {
            "checked": 1, "updated": 0, "published": 0, "pending": 1,
        },
    )
    health_importlib = health.__dict__["importlib"]
    real_import = health_importlib.import_module

    def fake_import(name: str) -> Any:
        if name in {"scripts.daily_alpha_publish_cycle", "daily_alpha_publish_cycle"}:
            return fake_cycle
        return real_import(name)

    monkeypatch.setattr(health_importlib, "import_module", fake_import)

    assert health.main([
        "--runs-root", str(tmp_path),
        "--expect-published",
        "--sync-pending-decisions",
    ]) == 2


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
        "no_fresh_candidate": 1,
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
