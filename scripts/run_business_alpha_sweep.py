"""Run repeated dry-run sweeps across business-family alpha lanes."""
from __future__ import annotations

import argparse
import datetime as dt
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
from scripts.alpha_publish_io import write_json
from scripts.build_business_alpha_candidate import write_no_bundle_diagnostics
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
    return out_path


def _bundle_fingerprint(bundle: Any) -> str:
    return "|".join((
        str(bundle.domain),
        str(bundle.topic),
        str(bundle.result_key),
        ",".join(sorted(str(fact.get("fact_id") or "") for fact in bundle.receipts)),
    ))


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
    consistent: dict[str, int] = {}
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
                    row["diagnostics"] = str(write_no_bundle_diagnostics(
                        runs_root=args.runs_root,
                        domain=domain,
                        topic=topic,
                        facts=facts,
                        trace=trace,
                    ))
                    rows.append(row)
                    print(f"[business-sweep] no_bundle {domain} {topic} facts={len(facts)}")
                    continue
                fingerprint = _bundle_fingerprint(bundle)
                consistent[fingerprint] = consistent.get(fingerprint, 0) + 1
                run_dir = write_candidate_run(bundle, profile=profile, runs_root=args.runs_root)
                row["run_dir"] = str(run_dir)
                row["source_count"] = bundle.source_count
                row["candidate_fingerprint"] = fingerprint
                row["consistent_passes"] = consistent[fingerprint]
                rows.append(row)
                summary_path = _write_sweep_summary(args.runs_root, rows)
                submit_after = max(0, args.submit_after_consistent_passes)
                if submit_after:
                    if consistent[fingerprint] < submit_after:
                        row["status"] = "ready_waiting_consistency"
                        _write_sweep_summary(args.runs_root, rows)
                        print(
                            "[business-sweep] ready_waiting_consistency "
                            f"{domain} {topic} passes={consistent[fingerprint]}/{submit_after}"
                        )
                        continue
                    if profile.dry_run_only:
                        row["status"] = "submit_blocked_domain_dry_run_only"
                        _write_sweep_summary(args.runs_root, rows)
                        print(
                            "[business-sweep] submit_blocked_domain_dry_run_only "
                            f"{domain} {topic} passes={consistent[fingerprint]}/{submit_after}",
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
                    print(f"[business-sweep] {row['status']} {domain} {topic} -> {run_dir}")
                    return 0 if row["status"] in {"submitted_to_researka", "published"} else 2
                print(f"[business-sweep] ready {domain} {topic} -> {run_dir}")
                print(f"[business-sweep] summary={summary_path}")
                return 0
        if cycle + 1 < args.cycles and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    summary_path = _write_sweep_summary(args.runs_root, rows)
    print(f"[business-sweep] no_ready_candidate summary={summary_path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
