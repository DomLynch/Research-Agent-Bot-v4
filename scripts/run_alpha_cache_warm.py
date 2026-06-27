"""Warm source-rich discovery caches across v4 alpha domains."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.domain_profile import domain_choices, load_domain_profile


def _default_domains() -> tuple[str, ...]:
    by_seed: dict[str, str] = {}
    for slug in domain_choices():
        profile = load_domain_profile(slug)
        key = str(profile.seed_topics_path)
        previous = by_seed.get(key)
        if previous is None or (
            not previous.endswith("_research") and profile.slug.endswith("_research")
        ):
            by_seed[key] = profile.slug
    return tuple(sorted(by_seed.values()))


def _selected_domains(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return _default_domains()
    known = set(domain_choices())
    selected = tuple(item.strip() for item in raw.split(",") if item.strip())
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError(f"unknown domain(s): {', '.join(unknown)}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domains", default="")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--warm-backlog", dest="warm_backlog", action="store_true")
    parser.add_argument("--no-warm-backlog", dest="warm_backlog", action="store_false")
    parser.add_argument("--derived-topic-limit", type=int, default=1000)
    parser.add_argument("--fact-probe-topics", type=int, default=120)
    parser.set_defaults(warm_backlog=True)
    args = parser.parse_args()

    script = Path(__file__).with_name("run_topic_discovery.py")
    failures = 0
    for domain in _selected_domains(args.domains):
        cmd = [
            sys.executable,
            str(script),
            "--domain",
            domain,
            "--top",
            str(args.top),
            "--derived-topic-limit",
            str(args.derived_topic_limit),
            "--fact-probe-topics",
            str(args.fact_probe_topics),
        ]
        if args.warm_backlog:
            cmd.append("--warm-backlog")
        result = subprocess.run(cmd, check=False)
        print(f"[alpha-cache-warm] domain={domain} rc={result.returncode}", flush=True)
        if result.returncode != 0:
            failures += 1
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
