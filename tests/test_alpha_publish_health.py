from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

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
    stale.touch()
    latest.touch()

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
