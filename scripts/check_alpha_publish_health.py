"""Summarize the latest alpha publish ledger for monitoring.

Default mode is observe-only and exits 0. Pass --expect-published when a
scheduled/forced cycle should have produced a public alpha memo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

Json = dict[str, Any]


def _ledger_paths(runs_root: Path) -> list[Path]:
    ledger_dir = runs_root / "_daily_ledger"
    return sorted(
        (
            path
            for path in ledger_dir.glob("*.json")
            if not path.name.startswith("_") and "decision" not in path.name
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _load_json(path: Path) -> Json:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _considered_counts(ledger: Json) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in ledger.get("considered") or []:
        if isinstance(row, dict):
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    return counts


def _attempts(ledger: Json) -> list[Json]:
    rows: list[Json] = []
    for row in ledger.get("cycle_attempts") or []:
        if isinstance(row, dict):
            rows.append({
                "batch": row.get("batch"),
                "topic": row.get("topic"),
                "status": row.get("status"),
            })
    return rows


def _public_url_status(url: str, *, timeout: float) -> int | None:
    if not url:
        return None
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except OSError:
        return None


def summarize_latest(
    runs_root: Path,
    *,
    check_url: bool = False,
    timeout: float = 15.0,
    now: dt.datetime | None = None,
) -> Json:
    paths = _ledger_paths(runs_root)
    if not paths:
        return {"ok": False, "reason": "no_daily_ledger", "runs_root": str(runs_root)}
    path = paths[0]
    ledger = _load_json(path)
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    current = now or dt.datetime.now(dt.UTC)
    url = str(ledger.get("public_url") or "")
    url_status = _public_url_status(url, timeout=timeout) if check_url else None
    published = int(ledger.get("published") or 0) == 1
    return {
        "ok": published and (not check_url or bool(url_status and 200 <= url_status < 400)),
        "ledger": path.name,
        "ledger_mtime": mtime.isoformat(),
        "ledger_age_minutes": round((current - mtime).total_seconds() / 60, 1),
        "status": ledger.get("status"),
        "submitted": int(ledger.get("submitted") or 0),
        "published": int(ledger.get("published") or 0),
        "topic": ledger.get("published_topic") or ledger.get("submitted_topic"),
        "public_url": url or None,
        "public_url_status": url_status,
        "decision_poll": ledger.get("decision_poll"),
        "attempts": _attempts(ledger),
        "considered_counts": _considered_counts(ledger),
        "reason": ledger.get("reason"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--expect-published", action="store_true")
    parser.add_argument("--check-url", action="store_true")
    parser.add_argument("--max-age-minutes", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    summary = summarize_latest(
        args.runs_root,
        check_url=args.check_url,
        timeout=args.timeout,
    )
    if args.max_age_minutes > 0 and float(summary.get("ledger_age_minutes") or 0) > args.max_age_minutes:
        summary["ok"] = False
        summary["reason"] = "latest_ledger_stale"
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.expect_published and not summary.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
