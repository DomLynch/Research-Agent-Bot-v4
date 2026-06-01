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


def test_expect_published_exits_nonzero_for_failed_latest_ledger(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "2026-06-01T01-04-07Z.json", {
        "status": "no_publishable_candidate",
        "submitted": 0,
        "published": 0,
        "reason": "no eligible non-duplicate memo",
    })

    assert health.main(["--runs-root", str(tmp_path), "--expect-published"]) == 2


def test_next_candidate_summary_reports_retry_risk(tmp_path: Path) -> None:
    def select_candidate(*_args: object, **_kwargs: object) -> tuple[dict[str, str], list[dict[str, Any]]]:
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
        _build_queue=lambda *_args, **_kwargs: {"ready_to_publish": []},
        _recently_published_topics=lambda *_args, **_kwargs: {"old"},
        select_candidate=select_candidate,
    )

    summary = health.summarize_next_candidate(tmp_path, cycle_module=fake_cycle)

    assert summary["topic"] == "grid_storage"
    assert summary["retry_after_rejection"] is True
    assert summary["retry_attempt_count"] == 2
    assert summary["considered_counts"] == {"cycle_exhausted_topic": 1, "eligible": 1}
