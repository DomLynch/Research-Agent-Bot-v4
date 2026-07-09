#!/usr/bin/env python3
"""Watch alpha publishing SLA and the V4 FullRaw queue."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.alpha_publish_io import read_json, write_json

Json = dict[str, Any]
_STATE_NAME = "alpha_publish_watchdog_state.json"
_SUMMARY_NAME = "alpha_publish_watchdog_summary.json"


def _parse_stamp(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H-%M-%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(text[:20], fmt).replace(tzinfo=dt.UTC)
        except ValueError:
            pass
    with_utc = text.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(with_utc)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _ledger_dir(runs_root: Path) -> Path:
    return runs_root / "_daily_ledger"


def latest_published(runs_root: Path) -> Json | None:
    rows: list[Json] = []
    submitted = read_json(_ledger_dir(runs_root) / "_submitted_fingerprints.json", [])
    if isinstance(submitted, dict):
        submitted_rows = list(submitted.values())
    else:
        submitted_rows = submitted if isinstance(submitted, list) else []
    for row in submitted_rows:
        if isinstance(row, dict) and str(row.get("status") or "") == "published":
            stamp = _parse_stamp(row.get("published_at") or row.get("date") or row.get("submitted_at"))
            if stamp:
                rows.append({**row, "_published_dt": stamp})
    for path in _ledger_dir(runs_root).glob("*.json"):
        ledger = read_json(path, {})
        if not isinstance(ledger, dict) or int(ledger.get("published") or 0) != 1:
            continue
        stamp = _parse_stamp(ledger.get("published_at") or ledger.get("date") or path.stem)
        if stamp:
            rows.append({**ledger, "_published_dt": stamp})
    if not rows:
        return None
    latest = max(rows, key=lambda row: row["_published_dt"])
    published_at: dt.datetime = latest["_published_dt"]
    return {
        "published_at": published_at.isoformat(),
        "topic": latest.get("published_topic") or latest.get("topic") or latest.get("submitted_topic"),
        "public_url": latest.get("public_url") or latest.get("url"),
    }


def _public_status(url: str, *, timeout: float) -> Json:
    if not url:
        return {"ok": False, "http_status": None, "reason": "missing_public_url"}
    request = urllib.request.Request(
        url, headers={"User-Agent": "researka-v4-watchdog/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"ok": 200 <= response.status < 300, "http_status": response.status}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http_status": exc.code}
    except OSError as exc:
        return {"ok": False, "http_status": None, "error": type(exc).__name__}


def _fullraw_health_url(explicit: str) -> str:
    if explicit:
        return explicit
    url = os.environ.get("RESEARKA_FULLRAW_SEARCH_URL") or os.environ.get(
        "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "",
    )
    return url.rsplit("/", 1)[0] + "/health" if url else ""


def fullraw_sample(url: str, *, timeout: float) -> Json:
    if not url:
        return {"configured": False, "ok": True}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        return {"configured": True, "ok": False, "error": type(exc).__name__}
    async_sweep = data.get("async_sweep") if isinstance(data, dict) else {}
    if not isinstance(async_sweep, dict):
        async_sweep = {}
    sample: Json = {
        "configured": True,
        "ok": bool(data.get("ok", True)) if isinstance(data, dict) else False,
        "inflight": int(async_sweep.get("inflight_count") or 0),
        "queued": int(async_sweep.get("queued_count") or 0),
        "priority_queued": int(async_sweep.get("priority_queued_count") or 0),
        "workers": int(async_sweep.get("workers") or 0),
        "max_queue": int(async_sweep.get("max_queue") or 0),
    }
    sample["signature"] = "|".join(str(sample[key]) for key in (
        "inflight", "queued", "priority_queued", "workers", "max_queue",
    ))
    sample["busy"] = any(int(sample[key]) > 0 for key in ("inflight", "queued", "priority_queued"))
    return sample


def _evaluate_fullraw(
    state: Json,
    sample: Json,
    *,
    now: dt.datetime,
    stuck_minutes: float,
) -> Json:
    raw_previous = state.get("fullraw")
    previous: Json = raw_previous if isinstance(raw_previous, dict) else {}
    signature = str(sample.get("signature") or "")
    first_seen = now
    if sample.get("busy") and previous.get("signature") == signature:
        first_seen = _parse_stamp(previous.get("first_seen")) or now
    elapsed = max(0.0, (now - first_seen).total_seconds() / 60.0)
    stuck = bool(sample.get("busy")) and elapsed >= stuck_minutes
    return {
        **sample,
        "first_seen": first_seen.isoformat(),
        "busy_minutes": round(elapsed, 1),
        "stuck": stuck,
    }


def _restart_service(service: str) -> Json:
    if not service:
        return {"attempted": False}
    result = subprocess.run(
        ["systemctl", "restart", service],
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
    )
    return {
        "attempted": True,
        "service": service,
        "returncode": result.returncode,
        "stdout": result.stdout[-500:],
        "stderr": result.stderr[-500:],
    }


def evaluate(args: argparse.Namespace, *, now: dt.datetime | None = None) -> Json:
    current = now or dt.datetime.now(dt.UTC)
    runs_root: Path = args.runs_root
    state_path = args.state_path or (_ledger_dir(runs_root) / _STATE_NAME)
    summary_path = args.summary_path or (_ledger_dir(runs_root) / _SUMMARY_NAME)
    state = read_json(state_path, {})
    state = state if isinstance(state, dict) else {}

    latest = latest_published(runs_root)
    gap_hours: float | None = None
    if latest:
        published_at = _parse_stamp(latest.get("published_at"))
        if published_at:
            gap_hours = max(0.0, (current - published_at).total_seconds() / 3600.0)
    public = _public_status(str((latest or {}).get("public_url") or ""), timeout=args.timeout)
    fullraw = _evaluate_fullraw(
        state,
        fullraw_sample(_fullraw_health_url(args.fullraw_health_url), timeout=args.timeout),
        now=current,
        stuck_minutes=args.fullraw_stuck_minutes,
    )
    remediation: Json = {"fullraw_restart": {"attempted": False}}
    if fullraw.get("stuck") and args.restart_fullraw_service:
        remediation["fullraw_restart"] = _restart_service(args.restart_fullraw_service)

    warn = gap_hours is None or gap_hours >= args.warn_gap_hours
    fail = gap_hours is None or gap_hours >= args.max_publish_gap_hours
    summary: Json = {
        "ok": not fail and not fullraw.get("stuck") and bool(public.get("ok")),
        "checked_at": current.isoformat(),
        "latest_published": latest,
        "publish_gap_hours": None if gap_hours is None else round(gap_hours, 2),
        "warn_gap_hours": args.warn_gap_hours,
        "max_publish_gap_hours": args.max_publish_gap_hours,
        "publish_gap_warning": warn,
        "publish_gap_breach": fail,
        "public_status": public,
        "fullraw": fullraw,
        "remediation": remediation,
    }
    write_json(summary_path, summary)
    write_json(state_path, {"fullraw": fullraw, "last_summary": str(summary_path)})
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--state-path", type=Path)
    parser.add_argument("--summary-path", type=Path)
    parser.add_argument("--warn-gap-hours", type=float, default=24.0)
    parser.add_argument("--max-publish-gap-hours", type=float, default=48.0)
    parser.add_argument("--fullraw-health-url", default="")
    parser.add_argument("--fullraw-stuck-minutes", type=float, default=45.0)
    parser.add_argument("--restart-fullraw-service", default="")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    summary = evaluate(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
