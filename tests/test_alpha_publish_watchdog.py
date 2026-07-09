from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import scripts.alpha_publish_watchdog as watchdog


def _args(root: Path, **overrides: Any) -> argparse.Namespace:
    values = {
        "runs_root": root,
        "state_path": None,
        "summary_path": None,
        "warn_gap_hours": 24.0,
        "max_publish_gap_hours": 48.0,
        "fullraw_health_url": "",
        "fullraw_stuck_minutes": 45.0,
        "restart_fullraw_service": "",
        "timeout": 1.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_watchdog_fails_when_latest_publication_exceeds_sla(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    ledger_dir = tmp_path / "_daily_ledger"
    ledger_dir.mkdir()
    (ledger_dir / "_submitted_fingerprints.json").write_text(json.dumps([
        {
            "status": "published",
            "date": "2026-07-05T01-30-02Z",
            "topic": "retrieval_augmented_generation",
            "public_url": "https://researka.org/alpha/live",
        },
    ]), encoding="utf-8")
    monkeypatch.setattr(watchdog, "_public_status", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(watchdog, "fullraw_sample", lambda *_a, **_k: {"ok": True, "busy": False})

    summary = watchdog.evaluate(
        _args(tmp_path),
        now=dt.datetime(2026, 7, 9, 12, 0, tzinfo=dt.UTC),
    )

    assert summary["ok"] is False
    assert summary["publish_gap_breach"] is True
    assert summary["latest_published"]["topic"] == "retrieval_augmented_generation"


def test_watchdog_restarts_stuck_fullraw_queue(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    ledger_dir = tmp_path / "_daily_ledger"
    ledger_dir.mkdir()
    state_path = ledger_dir / "alpha_publish_watchdog_state.json"
    state_path.write_text(json.dumps({
        "fullraw": {
            "signature": "2|4|4|2|4",
            "first_seen": "2026-07-09T10:00:00+00:00",
        },
    }), encoding="utf-8")
    (ledger_dir / "_submitted_fingerprints.json").write_text(json.dumps([
        {
            "status": "published",
            "date": "2026-07-09T09-30-00Z",
            "topic": "fresh",
            "public_url": "https://researka.org/alpha/fresh",
        },
    ]), encoding="utf-8")
    monkeypatch.setattr(watchdog, "_public_status", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(watchdog, "fullraw_sample", lambda *_a, **_k: {
        "ok": True,
        "busy": True,
        "signature": "2|4|4|2|4",
        "inflight": 2,
        "queued": 4,
        "priority_queued": 4,
        "workers": 2,
        "max_queue": 4,
    })
    calls: list[str] = []

    def restart(service: str) -> dict[str, Any]:
        calls.append(service)
        return {"attempted": True, "service": service, "returncode": 0}

    monkeypatch.setattr(watchdog, "_restart_service", restart)

    summary = watchdog.evaluate(
        _args(tmp_path, restart_fullraw_service="researka-v4-fullraw-search.service"),
        now=dt.datetime(2026, 7, 9, 11, 0, tzinfo=dt.UTC),
    )

    assert summary["ok"] is False
    assert summary["fullraw"]["stuck"] is True
    assert calls == ["researka-v4-fullraw-search.service"]


def test_publish_health_unit_runs_watchdog_before_health_check() -> None:
    service = Path("deploy/systemd/researka-alpha-publish-health.service").read_text(
        encoding="utf-8",
    )

    assert "scripts/alpha_publish_watchdog.py" in service
    assert "--max-publish-gap-hours 48" in service
    assert "--fullraw-stuck-minutes 45" in service
    assert "--restart-fullraw-service researka-v4-fullraw-search.service" in service
    assert service.index("scripts/alpha_publish_watchdog.py") < service.index(
        "scripts/check_alpha_publish_health.py",
    )
