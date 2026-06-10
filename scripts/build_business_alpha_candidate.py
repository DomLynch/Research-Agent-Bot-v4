"""Build one dry-run business-family alpha memo candidate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.business_research import (
    BUSINESS_DOMAINS,
    build_candidate_bundle,
    business_fact_diagnostics,
    fetch_business_facts,
    write_candidate_run,
)
from agent.domain_profile import domain_choices, load_domain_profile
from agent.settings import load_settings

_RUNS = Path(__file__).resolve().parent.parent / "runs"


def _read_facts(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def write_no_bundle_diagnostics(
    *,
    runs_root: Path,
    domain: str,
    topic: str,
    facts: list[dict[str, Any]],
    trace: dict[str, Any],
) -> Path:
    out_dir = runs_root / "_business_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = business_fact_diagnostics(facts, topic=topic, domain=domain)
    payload["retrieval_trace"] = trace
    out_path = out_dir / f"{domain}-{topic}.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=domain_choices())
    parser.add_argument("--topic", required=True)
    parser.add_argument("--facts-json", type=Path, default=None)
    parser.add_argument("--runs-root", type=Path, default=_RUNS)
    parser.add_argument("--snapshot-utc", default=None)
    args = parser.parse_args()
    profile = load_domain_profile(args.domain)
    if profile.slug not in BUSINESS_DOMAINS:
        print(f"[business-candidate] unsupported business domain: {profile.slug}", file=sys.stderr)
        return 2
    trace: dict[str, Any] = {"status": "local_fixture", "facts": 0}
    facts = _read_facts(args.facts_json)
    if not facts:
        facts, trace = fetch_business_facts(args.topic, domain=profile.slug, settings=load_settings())
    bundle = build_candidate_bundle(facts, topic=args.topic, domain=profile.slug)
    if bundle is None:
        diagnostics_path = write_no_bundle_diagnostics(
            runs_root=args.runs_root,
            domain=profile.slug,
            topic=args.topic,
            facts=facts,
            trace=trace,
        )
        print(
            "[business-candidate] no source-diverse comparable A-core bundle "
            f"domain={profile.slug} topic={args.topic} trace={trace} "
            f"diagnostics={diagnostics_path}",
            file=sys.stderr,
        )
        return 3
    run_dir = write_candidate_run(
        bundle, profile=profile, runs_root=args.runs_root, snapshot_utc=args.snapshot_utc,
    )
    print(
        "[business-candidate] "
        f"domain={profile.slug} topic={args.topic} sources={bundle.source_count} -> {run_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
