"""Run repeated dry-run sweeps across business-family alpha lanes."""
from __future__ import annotations

import argparse
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
from scripts.build_business_alpha_candidate import write_no_bundle_diagnostics

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


def _write_sweep_summary(runs_root: Path, rows: list[dict[str, Any]]) -> Path:
    out_dir = runs_root / "_business_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest_sweep.json"
    out_path.write_text(json.dumps({"results": rows}, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--topics-per-domain", type=int, default=2)
    parser.add_argument("--runs-root", type=Path, default=_RUNS)
    args = parser.parse_args()
    settings = load_settings()
    rows: list[dict[str, Any]] = []
    for cycle in range(max(1, args.cycles)):
        for domain in _DOMAINS:
            profile = load_domain_profile(domain)
            if profile.slug not in BUSINESS_DOMAINS or not profile.dry_run_only:
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
                run_dir = write_candidate_run(bundle, profile=profile, runs_root=args.runs_root)
                row["run_dir"] = str(run_dir)
                row["source_count"] = bundle.source_count
                rows.append(row)
                summary_path = _write_sweep_summary(args.runs_root, rows)
                print(f"[business-sweep] ready {domain} {topic} -> {run_dir}")
                print(f"[business-sweep] summary={summary_path}")
                return 0
        if cycle + 1 < args.cycles and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    summary_path = _write_sweep_summary(args.runs_root, rows)
    print(f"[business-sweep] no_ready_candidate summary={summary_path}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
