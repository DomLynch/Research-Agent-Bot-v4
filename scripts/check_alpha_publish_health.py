#!/usr/bin/env python3
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
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

Json = dict[str, Any]
_QUEUE_BUCKETS = ("ready_to_publish", "agent_repair_needed", "curation_needed", "not_ready")
_CYCLE_LEDGER_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}t(?!.*-decision-)[a-z0-9_.:-]+z(?:-[a-z0-9_.-]+)?\.json$",
    re.I,
)
_NUMERIC_LEDGER_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})t(\d{2})-(\d{2})-(\d{2})z",
    re.I,
)
_DRY_RUN_LEDGER_RE = re.compile(r"(^|[-_t])dry[-_]?run", re.I)
_DEFAULT_ACTIVE_RUN_STALE_MINUTES = 120.0
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from scripts import alpha_publish_io as publish_io
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback.
    import alpha_publish_io as publish_io  # type: ignore[no-redef]


def _ledger_paths(runs_root: Path, *, domain: str | None = None) -> list[Path]:
    ledger_dir = runs_root / "_daily_ledger"
    return sorted(
        (
            path
            for path in ledger_dir.glob("*.json")
            if _CYCLE_LEDGER_RE.match(path.name)
            and not _DRY_RUN_LEDGER_RE.search(path.stem)
            and (domain is None or _ledger_domain_slug(_load_json(path)) == domain)
        ),
        key=_ledger_sort_key,
        reverse=True,
    )


def _ledger_sort_key(path: Path) -> tuple[float, str]:
    match = _NUMERIC_LEDGER_TS_RE.match(path.name)
    if match:
        year, month, day, hour, minute, second = (int(value) for value in match.groups())
        stamp = dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC)
        if stamp > dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5):
            return (path.stat().st_mtime, path.name.lower())
        return (stamp.timestamp(), path.name.lower())
    return (path.stat().st_mtime, path.name.lower())


def _load_json(path: Path) -> Json:
    data = publish_io.read_json(path, {})
    return data if isinstance(data, dict) else {}


def _considered_counts(ledger: Json) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in ledger.get("considered") or []:
        if isinstance(row, dict):
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    return counts


def _blocker_counts(ledger: Json) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in ledger.get("considered") or []:
        if not isinstance(row, dict):
            continue
        for blocker in row.get("blockers") or []:
            key = str(blocker or "").strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
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


def _next_action_for_status(status: Any) -> str:
    try:
        status_module = importlib.import_module("scripts.alpha_publish_status")
    except ModuleNotFoundError:
        status_module = importlib.import_module("alpha_publish_status")
    return str(status_module.next_action_for_status(str(status or "")))


def _publish_summary(ledger: Json) -> Json:
    try:
        status_module = importlib.import_module("scripts.alpha_publish_status")
    except ModuleNotFoundError:
        status_module = importlib.import_module("alpha_publish_status")
    computed = status_module.publish_summary(ledger)
    computed = computed if isinstance(computed, dict) else {}
    stored = ledger.get("publish_summary")
    if not isinstance(stored, dict):
        return computed
    summary = dict(stored)
    for key in ("considered", "queue_counts", "public_url_status", "public_page_status"):
        if key not in summary and key in computed:
            summary[key] = computed[key]
    if computed.get("next_action"):
        summary["next_action"] = computed["next_action"]
    blockers = summary.get("top_blockers")
    if not isinstance(blockers, dict) or not blockers:
        summary["top_blockers"] = computed.get("top_blockers") or {}
        return summary
    status = str(ledger.get("status") or "")
    if status and status not in (
        status_module.SUBMIT_SUCCESS_STATUSES | {status_module.CycleStatus.STARTED.value}
    ):
        merged: dict[str, int] = {
            str(key): int(value)
            for key, value in blockers.items()
            if str(key) and isinstance(value, int)
        }
        merged[status] = max(1, merged.get(status, 0))
        summary["top_blockers"] = dict(
            sorted(merged.items(), key=lambda item: (-item[1], item[0]))[:5]
        )
    return summary


def _ledger_domain_slug(ledger: Json) -> str | None:
    domain = ledger.get("domain")
    if isinstance(domain, dict):
        slug = str(domain.get("slug") or "").strip()
        if slug:
            return slug
    slug = str(ledger.get("domain_slug") or "").strip()
    return slug or None


def _domain_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _queue_sidecar(runs_root: Path, domain: str | None) -> Json | None:
    path = runs_root / (f"_publish_queue.{domain}.json" if domain else "_publish_queue.json")
    if not path.exists():
        return None
    data = _load_json(path)
    return data if any(isinstance(data.get(key), list) for key in _QUEUE_BUCKETS) else None


def _current_queue(runs_root: Path, cycle: Any, domain: str | None, submitted_path: Path) -> Json:
    sidecar = _queue_sidecar(runs_root, domain)
    if (
        isinstance(sidecar, dict)
        and not sidecar.get("ready_to_publish")
        and any(sidecar.get(key) for key in ("agent_repair_needed", "curation_needed", "not_ready"))
    ):
        return sidecar
    try:
        queue_module = importlib.import_module("scripts.build_publish_queue")
    except ModuleNotFoundError:
        queue_module = None
    if queue_module is not None:
        old_runs = getattr(queue_module, "_RUNS", None)
        try:
            queue_module._RUNS = runs_root  # type: ignore[attr-defined]
            queue = queue_module.build_queue(include_archive=False, domain=domain)
        finally:
            if old_runs is not None:
                queue_module._RUNS = old_runs  # type: ignore[attr-defined]
        if isinstance(queue, dict) and any(queue.get(key) for key in _QUEUE_BUCKETS):
            return queue
    try:
        queue = cycle._build_queue(
            runs_root,
            include_archive=False,
            domain=domain,
            submitted_path=submitted_path,
        )
        return queue if isinstance(queue, dict) else {}
    except Exception:
        return sidecar or {}


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
    queue = _current_queue(runs_root, cycle, domain, submitted_path)
    raw_ready = len(queue.get("ready_to_publish") or [])
    queue_counts = {
        key: raw_ready if key == "ready_to_publish" else len(queue.get(key) or [])
        for key in _QUEUE_BUCKETS
    }
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
    has_actionable = candidate is not None
    considered_ledger = {"considered": considered}
    considered_counts = _considered_counts(considered_ledger)
    blocker_counts = _blocker_counts(considered_ledger)
    return {
        "topic": (candidate or {}).get("topic"),
        "decision": (candidate or {}).get("decision"),
        "run_dir": (candidate or {}).get("run_dir"),
        "queue_counts": queue_counts,
        "actionable_ready_to_publish": 1 if has_actionable else 0,
        "non_actionable_ready_to_publish": (
            max(0, raw_ready - 1) if has_actionable else raw_ready
        ),
        "supply_status": (
            "actionable_candidate_available" if has_actionable else
            "ready_queue_blocked" if raw_ready else "no_ready_rows"
        ),
        "considered_counts": considered_counts,
        "blocked_ready_reasons": considered_counts if raw_ready and not has_actionable else {},
        "blocked_ready_blockers": blocker_counts if raw_ready and not has_actionable else {},
        "retry_after_rejection": bool(eligible_row.get("retry_after_rejection")),
        "retry_attempt_count": eligible_row.get("retry_attempt_count"),
    }


def _attach_current_queue_summary(summary: Json, next_candidate: Json) -> None:
    current_counts = next_candidate.get("queue_counts")
    if isinstance(current_counts, dict):
        ledger_counts = summary.get("queue_counts")
        if (
            isinstance(ledger_counts, dict)
            and ledger_counts
            and ledger_counts != current_counts
        ):
            summary["ledger_queue_counts"] = ledger_counts
        summary["queue_counts"] = current_counts
        summary["current_queue_counts"] = current_counts
    summary["current_actionable_ready_to_publish"] = (
        next_candidate.get("actionable_ready_to_publish")
    )
    summary["current_non_actionable_ready_to_publish"] = (
        next_candidate.get("non_actionable_ready_to_publish")
    )


def _write_summary_artifact(runs_root: Path, summary: Json) -> Path:
    path = runs_root / "_daily_ledger" / "alpha_publish_health_summary.json"
    summary["summary_artifact"] = str(path)
    publish_io.write_json(path, summary)
    return path


def _count_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _aggregate_domain_summaries(domain_summaries: dict[str, Json]) -> Json:
    queue_counts = {key: 0 for key in _QUEUE_BUCKETS}
    blocker_counts: dict[str, int] = {}
    public_status: dict[str, Any] = {}
    candidates_considered = 0
    actionable_ready = 0
    non_actionable_ready = 0
    next_action: str | None = None
    for domain, summary in domain_summaries.items():
        counts = summary.get("current_queue_counts") or summary.get("queue_counts") or {}
        if isinstance(counts, dict):
            for key in _QUEUE_BUCKETS:
                queue_counts[key] += _count_int(counts.get(key))
        actionable_ready += _count_int(summary.get("current_actionable_ready_to_publish"))
        non_actionable_ready += _count_int(
            summary.get("current_non_actionable_ready_to_publish"),
        )
        blockers = summary.get("top_blockers") or {}
        if isinstance(blockers, dict):
            for key, value in blockers.items():
                name = str(key or "").strip()
                if name:
                    blocker_counts[name] = blocker_counts.get(name, 0) + _count_int(value)
        considered = summary.get("considered_counts") or {}
        if isinstance(considered, dict):
            candidates_considered += sum(_count_int(value) for value in considered.values())
        public_status[domain] = summary.get("public_url_status")
        if not summary.get("ok") and not next_action and summary.get("next_action"):
            next_action = str(summary.get("next_action"))
    return {
        "submitted": sum(_count_int(row.get("submitted")) for row in domain_summaries.values()),
        "published": sum(_count_int(row.get("published")) for row in domain_summaries.values()),
        "queue_counts": queue_counts,
        "top_blockers": dict(
            sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ),
        "candidates_considered": candidates_considered,
        "current_actionable_ready_to_publish": actionable_ready,
        "current_non_actionable_ready_to_publish": non_actionable_ready,
        "next_action": next_action,
        "public_url_status": public_status,
    }


def _public_url_status(url: str, *, timeout: float) -> Json:
    if not url:
        return {"http_status": None, "rendered": False, "status": None}
    request = urllib.request.Request(
        url, headers={"User-Agent": "researka-v4-health/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            result: Json = {"ok": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        result = {
            "ok": False,
            "status": exc.code,
            "body": exc.read(512).decode("utf-8", errors="replace"),
        }
    except OSError as exc:
        return {
            "http_status": None,
            "rendered": False,
            "status": "error",
            "error": type(exc).__name__,
        }
    try:
        public = importlib.import_module("scripts.alpha_publish_public")
    except ModuleNotFoundError:
        public = importlib.import_module("alpha_publish_public")
    rendered = bool(public.page_rendered(result))
    return {
        "http_status": int(result.get("status") or 0),
        "rendered": rendered,
        "status": "rendered" if rendered else "not_rendered",
    }


def _systemd_unit_status(unit: str) -> Json:
    if not unit:
        return {}
    try:
        result = subprocess.run(
            [
                "systemctl", "show", unit,
                "-p", "ActiveState",
                "-p", "SubState",
                "-p", "Result",
                "-p", "ExecMainStatus",
                "-p", "MainPID",
                "-p", "ExecMainStartTimestamp",
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"unit": unit, "error": type(exc).__name__}
    fields: Json = {"unit": unit, "returncode": result.returncode}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key] = value
    state = str(fields.get("ActiveState") or "")
    pid = str(fields.get("MainPID") or "0")
    fields["running"] = state in {"active", "activating"} and pid not in {"", "0"}
    return fields


def _parse_systemd_timestamp(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.search(r" [+-]\d{2}$", raw):
        raw = f"{raw}00"
    for fmt in ("%a %Y-%m-%d %H:%M:%S %z", "%a %Y-%m-%d %H:%M:%S %Z"):
        try:
            parsed = dt.datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    return None


def _mark_active_run_if_newer(
    summary: Json,
    *,
    ledger_mtime: dt.datetime,
    now: dt.datetime,
    stale_after_minutes: float,
) -> None:
    active_run = summary.get("active_run")
    if not isinstance(active_run, dict) or not active_run.get("running"):
        return
    started_at = _parse_systemd_timestamp(active_run.get("ExecMainStartTimestamp"))
    if (
        started_at is None
        or (
            started_at <= ledger_mtime
            and str(summary.get("status") or "") != "started"
        )
    ):
        return
    summary["active_run_supersedes_ledger"] = True
    summary["active_run_started_at"] = started_at.isoformat()
    active_age_minutes = max(0.0, (now - started_at).total_seconds() / 60)
    summary["active_run_age_minutes"] = round(active_age_minutes, 1)
    summary["active_run_stale_after_minutes"] = stale_after_minutes
    summary["stale_ledger"] = {
        "current": False,
        "ledger": summary.get("ledger"),
        "status": summary.get("status"),
        "reason": summary.get("reason"),
        "top_blockers": summary.get("top_blockers") or {},
        "queue_counts": summary.get("queue_counts") or {},
    }
    summary["current_blocker_scope"] = "active_run"
    if stale_after_minutes > 0 and active_age_minutes > stale_after_minutes:
        summary["status"] = "active_run_stale"
        summary["reason"] = "active_run_stale"
        summary["top_blockers"] = {"active_run_stale": 1}
        summary["current_top_blockers"] = summary["top_blockers"]
        summary["next_action"] = "inspect_or_restart_active_run"
        return
    summary["status"] = "active_run_in_progress"
    summary["reason"] = "active_run_in_progress"
    summary["top_blockers"] = {"active_run_in_progress": 1}
    summary["current_top_blockers"] = summary["top_blockers"]
    summary["next_action"] = "wait_for_active_run_completion"


def _default_systemd_unit(domain: str | None) -> str | None:
    slug = str(domain or "").strip()
    if not slug:
        return None
    return f"researka-alpha-{slug.replace('_', '-')}.service"


def summarize_latest(
    runs_root: Path,
    *,
    domain: str | None = None,
    check_url: bool = False,
    show_next_candidate: bool = False,
    sync_pending_decisions: bool = False,
    systemd_unit: str | None = None,
    cycle_module: Any | None = None,
    timeout: float = 15.0,
    now: dt.datetime | None = None,
    active_run_stale_minutes: float = _DEFAULT_ACTIVE_RUN_STALE_MINUTES,
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
    paths = _ledger_paths(runs_root, domain=domain)
    if not paths:
        summary: Json = {
            "ok": False,
            "reason": "no_daily_ledger",
            "status": "no_daily_ledger",
            "submitted": 0,
            "published": 0,
            "runs_root": str(runs_root),
            "domain": domain,
            "queue_counts": {},
            "top_blockers": {"no_daily_ledger": 1},
            "next_action": "run_domain_publish_cycle",
            "public_url": None,
            "public_url_status": None,
            "public_page_status": None,
        }
        if show_next_candidate:
            try:
                next_candidate = summarize_next_candidate(
                    runs_root, cycle_module=cycle_module, domain=domain,
                )
                summary["next_candidate"] = next_candidate
                _attach_current_queue_summary(summary, next_candidate)
            except Exception as exc:  # pragma: no cover - monitor should report, not crash.
                summary["next_candidate_error"] = f"{type(exc).__name__}: {exc}"
        if systemd_unit:
            summary["active_run"] = _systemd_unit_status(systemd_unit)
        return summary
    path = paths[0]
    ledger = _load_json(path)
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    current = now or dt.datetime.now(dt.UTC)
    url = str(ledger.get("public_url") or "")
    url_check = (
        _public_url_status(url, timeout=timeout)
        if check_url else {"http_status": None, "rendered": False, "status": None}
    )
    url_status = url_check.get("http_status")
    published = int(ledger.get("published") or 0) == 1
    publish_summary = _publish_summary(ledger)
    considered_counts = _considered_counts(ledger)
    started_without_terminal = (
        str(ledger.get("status") or "") == "started"
        and not _attempts(ledger)
        and int(ledger.get("submitted") or 0) == 0
        and int(ledger.get("published") or 0) == 0
    )
    reason = ledger.get("reason")
    if reason in {None, "", "no eligible non-duplicate memo"}:
        derived_reason = _no_candidate_reason([
            row for row in ledger.get("considered") or [] if isinstance(row, dict)
        ])
        reason = derived_reason or reason
    if (
        started_without_terminal
        and reason in {None, "", "no eligible non-duplicate memo"}
    ):
        reason = "cycle_started_no_terminal_status"
    top_blockers = publish_summary.get("top_blockers") or considered_counts
    if started_without_terminal and not top_blockers:
        top_blockers = {"cycle_started_no_terminal_status": 1}
    summary = {
        "ok": published and (not check_url or bool(url_check.get("rendered"))),
        "ledger": path.name,
        "domain": _ledger_domain_slug(ledger),
        "ledger_mtime": mtime.isoformat(),
        "ledger_age_minutes": round((current - mtime).total_seconds() / 60, 1),
        "status": ledger.get("status"),
        "submitted": int(ledger.get("submitted") or 0),
        "published": int(ledger.get("published") or 0),
        "topic": ledger.get("published_topic") or ledger.get("submitted_topic"),
        "public_url": url or None,
        "public_url_status": url_status,
        "public_page_status": url_check.get("status"),
        "decision_poll": ledger.get("decision_poll"),
        "attempts": _attempts(ledger),
        "considered_counts": considered_counts,
        "queue_counts": ledger.get("queue_counts") or publish_summary.get("queue_counts") or {},
        "top_blockers": top_blockers,
        "next_action": publish_summary.get("next_action") or _next_action_for_status(
            ledger.get("status"),
        ),
        "reason": reason,
    }
    if decision_sync is not None:
        summary["decision_sync"] = decision_sync
    if show_next_candidate:
        try:
            next_candidate = summarize_next_candidate(
                runs_root,
                cycle_module=cycle_module,
                domain=domain or _ledger_domain_slug(ledger),
            )
            summary["next_candidate"] = next_candidate
            _attach_current_queue_summary(summary, next_candidate)
        except Exception as exc:  # pragma: no cover - monitor should report, not crash.
            summary["next_candidate_error"] = f"{type(exc).__name__}: {exc}"
    if systemd_unit:
        summary["active_run"] = _systemd_unit_status(systemd_unit)
        _mark_active_run_if_newer(
            summary,
            ledger_mtime=mtime,
            now=current,
            stale_after_minutes=active_run_stale_minutes,
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--expect-published", action="store_true")
    parser.add_argument("--check-url", action="store_true")
    parser.add_argument("--domain")
    parser.add_argument("--domains")
    parser.add_argument("--show-next-candidate", action="store_true")
    parser.add_argument("--sync-pending-decisions", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--systemd-unit")
    parser.add_argument("--max-age-minutes", type=float, default=0.0)
    parser.add_argument("--active-run-stale-minutes", type=float, default=_DEFAULT_ACTIVE_RUN_STALE_MINUTES)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    domains = _domain_list(args.domains)
    if args.domain and domains:
        parser.error("--domain and --domains are mutually exclusive")
    if domains:
        domain_summaries = {
            domain: summarize_latest(
                args.runs_root,
                domain=domain,
                check_url=args.check_url,
                show_next_candidate=args.show_next_candidate,
                sync_pending_decisions=args.sync_pending_decisions,
                systemd_unit=_default_systemd_unit(domain),
                timeout=args.timeout,
                active_run_stale_minutes=args.active_run_stale_minutes,
            )
            for domain in domains
        }
        for summary in domain_summaries.values():
            if (
                args.max_age_minutes > 0
                and float(summary.get("ledger_age_minutes") or 0) > args.max_age_minutes
            ):
                summary["ok"] = False
                summary["reason"] = "latest_ledger_stale"
        failed = [domain for domain, summary in domain_summaries.items() if not summary.get("ok")]
        summary = {
            "ok": not failed,
            "domains": domain_summaries,
            "failed_domains": failed,
            **_aggregate_domain_summaries(domain_summaries),
        }
        if args.write_summary:
            summary["summary_artifact"] = str(_write_summary_artifact(args.runs_root, summary))
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.expect_published and failed:
            return 2
        return 0

    summary = summarize_latest(
        args.runs_root,
        domain=args.domain,
        check_url=args.check_url,
        show_next_candidate=args.show_next_candidate,
        sync_pending_decisions=args.sync_pending_decisions,
        systemd_unit=args.systemd_unit or _default_systemd_unit(args.domain),
        timeout=args.timeout,
        active_run_stale_minutes=args.active_run_stale_minutes,
    )
    if args.max_age_minutes > 0 and float(summary.get("ledger_age_minutes") or 0) > args.max_age_minutes:
        summary["ok"] = False
        summary["reason"] = "latest_ledger_stale"
    if args.write_summary:
        summary["summary_artifact"] = str(_write_summary_artifact(args.runs_root, summary))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.expect_published and not summary.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
