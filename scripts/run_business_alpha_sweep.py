"""Run repeated dry-run sweeps across business-family alpha lanes."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.business_research import (
    BUSINESS_DOMAINS,
    build_candidate_bundle,
    fetch_business_facts,
    write_candidate_run,
)
from agent.domain_profile import load_domain_profile
from agent.settings import load_settings
from scripts import alpha_publish_status as publish_status
from scripts import build_publish_queue as publish_queue
from scripts.alpha_publish_io import read_json, update_json_list, write_json, write_ledger
from scripts.build_business_alpha_candidate import (
    no_bundle_blockers_from_diagnostics,
    write_no_bundle_diagnostics,
)
from scripts.daily_alpha_publish_cycle import run_cycle

_RUNS = Path(__file__).resolve().parent.parent / "runs"
_DOMAINS = (
    "management_research",
    "economics_research",
    "finance_research",
    "business_research",
    "marketing_research",
)


def _seed_topics(seed_path: Path, *, limit: int) -> list[str]:
    data = tomllib.loads(seed_path.read_text(encoding="utf-8"))
    topics = data.get("seeds", {}).get("topics", [])
    if not isinstance(topics, list):
        return []
    return [str(topic) for topic in topics[:limit] if str(topic).strip()]


def _selected_domains(value: str) -> tuple[str, ...]:
    if not value.strip():
        return _DOMAINS
    wanted = tuple(item.strip() for item in value.split(",") if item.strip())
    unknown = sorted(set(wanted) - set(_DOMAINS))
    if unknown:
        raise ValueError(f"unknown business sweep domain(s): {', '.join(unknown)}")
    return wanted


def _write_sweep_summary(runs_root: Path, rows: list[dict[str, Any]]) -> Path:
    out_dir = runs_root / "_business_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"results": rows}
    out_path = out_dir / "latest_sweep.json"
    write_json(out_path, payload)
    domains = sorted({
        str(row.get("domain") or "").strip()
        for row in rows
        if str(row.get("domain") or "").strip()
    })
    for domain in domains:
        write_json(
            out_dir / f"latest_sweep.{domain}.json",
            {
                "domain": domain,
                "results": [
                    row for row in rows
                    if str(row.get("domain") or "").strip() == domain
                ],
            },
        )
        _refresh_domain_queue(runs_root, domain)
    return out_path


def _refresh_domain_queue(runs_root: Path, domain: str) -> None:
    previous = publish_queue._RUNS
    publish_queue._RUNS = runs_root
    try:
        queue = publish_queue.build_queue(include_archive=False, domain=domain)
    finally:
        publish_queue._RUNS = previous
    write_json(runs_root / f"_publish_queue.{domain}.json", queue)


def _write_no_ready_ledgers(runs_root: Path, rows: list[dict[str, Any]], date: str) -> None:
    for domain in sorted({str(row.get("domain") or "") for row in rows if row.get("domain")}):
        domain_rows = [row for row in rows if row.get("domain") == domain]
        queue = read_json(runs_root / f"_publish_queue.{domain}.json", {})
        queue_counts = publish_status.queue_counts(queue if isinstance(queue, dict) else {})
        considered = [
            {
                "topic": row.get("topic"),
                "status": row.get("status") or "not_ready",
                "domain_slug": domain,
                "blockers": row.get("blockers") or (
                    ["no_source_diverse_bundle"] if row.get("status") == "no_bundle" else []
                ),
            }
            for row in domain_rows
        ]
        reason = (
            "no_source_diverse_bundle"
            if considered and all(row.get("status") == "no_bundle" for row in domain_rows)
            else "no_ready_business_candidate"
        )
        ledger = {
            "date": date,
            "domain": load_domain_profile(domain).as_metadata(),
            "domain_slug": domain,
            "status": publish_status.CycleStatus.CANDIDATE_REFRESH_FAILED.value,
            "reason": reason,
            "submitted": 0,
            "published": 0,
            "considered": considered,
            "queue_counts": queue_counts,
            "next_action": "inspect_refresh_failure",
        }
        path = runs_root / "_daily_ledger" / f"{date}-{domain}.json"
        write_ledger(path, ledger)
        print(
            f"[business-sweep] domain={domain} "
            f"summary={json.dumps(ledger['publish_summary'], sort_keys=True)}"
        )


def _bundle_fingerprint(bundle: Any) -> str:
    return "|".join((
        str(bundle.domain),
        str(bundle.topic),
        str(bundle.result_key),
        ",".join(sorted(str(fact.get("fact_id") or "") for fact in bundle.receipts)),
    ))


def _record_consistent_pass(
    runs_root: Path, *, domain: str, topic: str, fingerprint: str,
) -> int:
    path = runs_root / "_business_diagnostics" / f"ready_consistency.{domain}.json"
    passes = 1
    stamp = dt.datetime.now(dt.UTC).isoformat()

    def mutate(rows: list[Any]) -> bool:
        nonlocal passes
        rows[:] = [row for row in rows if isinstance(row, dict)]
        for row in rows:
            if str(row.get("fingerprint") or "") != fingerprint:
                continue
            try:
                passes = int(row.get("passes") or 0) + 1
            except (TypeError, ValueError):
                passes = 1
            row.update({
                "domain": domain,
                "topic": topic,
                "fingerprint": fingerprint,
                "passes": passes,
                "updated_utc": stamp,
            })
            return True
        rows.append({
            "domain": domain,
            "topic": topic,
            "fingerprint": fingerprint,
            "passes": passes,
            "updated_utc": stamp,
        })
        return True

    update_json_list(path, mutate)
    return passes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--topics-per-domain", type=int, default=2)
    parser.add_argument("--domains", default="")
    parser.add_argument("--runs-root", type=Path, default=_RUNS)
    parser.add_argument(
        "--submit-after-consistent-passes",
        type=int,
        default=0,
        help="Opt-in submit guard: require the same ready bundle this many times before submit.",
    )
    parser.add_argument("--submit-date", default="")
    args = parser.parse_args()
    settings = load_settings()
    rows: list[dict[str, Any]] = []
    domains = _selected_domains(args.domains)
    for cycle in range(max(1, args.cycles)):
        for domain in domains:
            profile = load_domain_profile(domain)
            if profile.slug not in BUSINESS_DOMAINS:
                continue
            for topic in _seed_topics(profile.seed_topics_path, limit=args.topics_per_domain):
                facts, trace = fetch_business_facts(topic, domain=domain, settings=settings)
                bundle = build_candidate_bundle(facts, topic=topic, domain=domain)
                row: dict[str, Any] = {
                    "cycle": cycle + 1,
                    "domain": domain,
                    "topic": topic,
                    "facts": len(facts),
                    "trace": trace,
                    "ready": bundle is not None,
                }
                if bundle is None:
                    row["status"] = "no_bundle"
                    diagnostics_path = write_no_bundle_diagnostics(
                        runs_root=args.runs_root,
                        domain=domain,
                        topic=topic,
                        facts=facts,
                        trace=trace,
                    )
                    row["diagnostics"] = str(diagnostics_path)
                    diagnostics = read_json(diagnostics_path, {})
                    if isinstance(diagnostics, dict):
                        row["blockers"] = no_bundle_blockers_from_diagnostics(diagnostics)
                    rows.append(row)
                    print(f"[business-sweep] no_bundle {domain} {topic} facts={len(facts)}")
                    continue
                fingerprint = _bundle_fingerprint(bundle)
                run_dir = write_candidate_run(bundle, profile=profile, runs_root=args.runs_root)
                submit_after = max(0, args.submit_after_consistent_passes)
                consistent_passes = (
                    _record_consistent_pass(
                        args.runs_root, domain=domain, topic=topic, fingerprint=fingerprint,
                    )
                    if submit_after else 1
                )
                row["run_dir"] = str(run_dir)
                row["source_count"] = bundle.source_count
                row["candidate_fingerprint"] = fingerprint
                row["consistent_passes"] = consistent_passes
                rows.append(row)
                summary_path = _write_sweep_summary(args.runs_root, rows)
                if submit_after:
                    if consistent_passes < submit_after:
                        row["status"] = "ready_waiting_consistency"
                        _write_sweep_summary(args.runs_root, rows)
                        print(
                            "[business-sweep] ready_waiting_consistency "
                            f"{domain} {topic} passes={consistent_passes}/{submit_after}"
                        )
                        continue
                    if profile.dry_run_only:
                        row["status"] = "submit_blocked_domain_dry_run_only"
                        _write_sweep_summary(args.runs_root, rows)
                        print(
                            "[business-sweep] submit_blocked_domain_dry_run_only "
                            f"{domain} {topic} passes={consistent_passes}/{submit_after}",
                            file=sys.stderr,
                        )
                        return 2
                    ledger = run_cycle(
                        runs_root=args.runs_root,
                        date=args.submit_date
                        or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                        domain=domain,
                        submit=True,
                    )
                    row["status"] = str(ledger.get("status") or "submit_failed")
                    row["submission_ledger"] = ledger
                    _write_sweep_summary(args.runs_root, rows)
                    if isinstance(ledger.get("publish_summary"), dict):
                        print(
                            f"[business-sweep] domain={domain} "
                            f"summary={json.dumps(ledger['publish_summary'], sort_keys=True)}"
                        )
                    print(f"[business-sweep] {row['status']} {domain} {topic} -> {run_dir}")
                    return 0 if row["status"] in {"submitted_to_researka", "published"} else 2
                print(f"[business-sweep] ready {domain} {topic} -> {run_dir}")
                print(f"[business-sweep] summary={summary_path}")
                return 0
        if cycle + 1 < args.cycles and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    summary_path = _write_sweep_summary(args.runs_root, rows)
    ledger_date = args.submit_date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    _write_no_ready_ledgers(args.runs_root, rows, ledger_date)
    print(f"[business-sweep] no_ready_candidate summary={summary_path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
