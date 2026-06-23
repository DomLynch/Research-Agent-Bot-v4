"""Summarize the latest alpha publish ledger for monitoring.

Default mode is observe-only and exits 0. Pass --expect-published when a
scheduled/forced cycle should have produced a public alpha memo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

Json = dict[str, Any]
_CYCLE_LEDGER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}t\d{2}-\d{2}-\d{2}z\.json$", re.I)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ledger_paths(runs_root: Path) -> list[Path]:
    ledger_dir = runs_root / "_daily_ledger"
    return sorted(
        (
            path
            for path in ledger_dir.glob("*.json")
            if _CYCLE_LEDGER_RE.match(path.name)
        ),
        key=lambda path: path.name.lower(),
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


def _no_candidate_reason(considered: list[Json]) -> str:
    try:
        status_module = importlib.import_module("scripts.alpha_publish_status")
    except ModuleNotFoundError:
        status_module = importlib.import_module("alpha_publish_status")
    return str(status_module.no_candidate_reason(considered))


def _ledger_domain_slug(ledger: Json) -> str | None:
    domain = ledger.get("domain")
    if isinstance(domain, dict):
        slug = str(domain.get("slug") or "").strip()
        if slug:
            return slug
    slug = str(ledger.get("domain_slug") or "").strip()
    return slug or None


def summarize_next_candidate(
    runs_root: Path,
    *,
    cycle_module: Any | None = None,
    domain: str | None = None,
) -> Json:
    cycle: Any = cycle_module
    if cycle is None:
        try:
            cycle = importlib.import_module("scripts.daily_alpha_publish_cycle")
        except ModuleNotFoundError:
            cycle = importlib.import_module("daily_alpha_publish_cycle")

    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    queue = cycle._build_queue(runs_root, include_archive=False, domain=domain)
    blocked = cycle._recently_published_topics(
        runs_root / "_daily_ledger",
        days=cycle._DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS,
        domain=domain,
    ) | cycle._recent_submission_topics(
        submitted_path,
        days=cycle._DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS,
        domain=domain,
    ) | cycle._recent_negative_topics(
        runs_root / "_daily_ledger",
        days=cycle._DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS,
        domain=domain,
    )
    candidate, considered = cycle.select_candidate(
        queue,
        runs_root=runs_root,
        submitted_path=submitted_path,
        min_source_count=cycle._DEFAULT_MIN_SUBMIT_SOURCES,
        min_direct_source_count=cycle._DEFAULT_MIN_DIRECT_SUBMIT_SOURCES,
        blocked_topics=blocked,
        memo_refresher=None,
        domain=domain,
    )
    eligible_row = next(
        (row for row in considered if isinstance(row, dict) and row.get("status") == "eligible"),
        {},
    )
    return {
        "topic": (candidate or {}).get("topic"),
        "decision": (candidate or {}).get("decision"),
        "run_dir": (candidate or {}).get("run_dir"),
        "considered_counts": _considered_counts({"considered": considered}),
        "retry_after_rejection": bool(eligible_row.get("retry_after_rejection")),
        "retry_attempt_count": eligible_row.get("retry_attempt_count"),
    }


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
    show_next_candidate: bool = False,
    sync_pending_decisions: bool = False,
    cycle_module: Any | None = None,
    timeout: float = 15.0,
    now: dt.datetime | None = None,
) -> Json:
    decision_sync: Json | None = None
    if sync_pending_decisions:
        cycle: Any = cycle_module
        if cycle is None:
            try:
                cycle = importlib.import_module("scripts.daily_alpha_publish_cycle")
            except ModuleNotFoundError:
                cycle = importlib.import_module("daily_alpha_publish_cycle")
        decision_sync = cycle.sync_submission_decisions(runs_root)
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
    publish_summary = ledger.get("publish_summary")
    if not isinstance(publish_summary, dict):
        publish_summary = {}
    considered_counts = _considered_counts(ledger)
    reason = ledger.get("reason")
    if reason in {None, "", "no eligible non-duplicate memo"}:
        derived_reason = _no_candidate_reason([
            row for row in ledger.get("considered") or [] if isinstance(row, dict)
        ])
        reason = derived_reason or reason
    summary = {
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
        "considered_counts": considered_counts,
        "queue_counts": ledger.get("queue_counts") or publish_summary.get("queue_counts") or {},
        "top_blockers": publish_summary.get("top_blockers") or considered_counts,
        "next_action": publish_summary.get("next_action"),
        "reason": reason,
    }
    if decision_sync is not None:
        summary["decision_sync"] = decision_sync
    if show_next_candidate:
        try:
            summary["next_candidate"] = summarize_next_candidate(
                runs_root, domain=_ledger_domain_slug(ledger),
            )
        except Exception as exc:  # pragma: no cover - monitor should report, not crash.
            summary["next_candidate_error"] = f"{type(exc).__name__}: {exc}"
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--expect-published", action="store_true")
    parser.add_argument("--check-url", action="store_true")
    parser.add_argument("--show-next-candidate", action="store_true")
    parser.add_argument("--sync-pending-decisions", action="store_true")
    parser.add_argument("--max-age-minutes", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    summary = summarize_latest(
        args.runs_root,
        check_url=args.check_url,
        show_next_candidate=args.show_next_candidate,
        sync_pending_decisions=args.sync_pending_decisions,
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
