"""Warm source-rich discovery caches across v4 alpha domains."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.domain_profile import domain_choices, load_domain_profile

_FULLRAW_CACHE_FILES = (
    Path("runs/_fullraw_completed_sweeps.json"),
    Path("runs/_fullraw_in_progress_sweeps.json"),
)


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


def _fullraw_cache_state() -> dict[Path, tuple[int, int]]:
    out: dict[Path, tuple[int, int]] = {}
    for path in _FULLRAW_CACHE_FILES:
        try:
            stat = path.stat()
        except OSError:
            continue
        out[path] = (stat.st_mtime_ns, stat.st_size)
    return out


def _fullraw_cache_progress(before: dict[Path, tuple[int, int]]) -> bool:
    after = _fullraw_cache_state()
    return any(after.get(path) != before.get(path) for path in _FULLRAW_CACHE_FILES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domains", default="")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--warm-backlog", dest="warm_backlog", action="store_true")
    parser.add_argument("--no-warm-backlog", dest="warm_backlog", action="store_false")
    parser.add_argument("--derived-topic-limit", type=int, default=1000)
    parser.add_argument("--fact-probe-topics", type=int, default=120)
    parser.add_argument("--per-domain-timeout-seconds", type=float, default=900.0)
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
        timeout = args.per_domain_timeout_seconds if args.per_domain_timeout_seconds > 0 else None
        print(f"[alpha-cache-warm] domain={domain} start", flush=True)
        cache_before = _fullraw_cache_state()
        timed_out_with_progress = False
        try:
            result = subprocess.run(cmd, check=False, timeout=timeout)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            timed_out_with_progress = _fullraw_cache_progress(cache_before)
            returncode = 0 if timed_out_with_progress else 124
        progress_note = " fullraw_cache_progress=1" if timed_out_with_progress else ""
        print(f"[alpha-cache-warm] domain={domain} rc={returncode}{progress_note}", flush=True)
        if returncode != 0:
            failures += 1
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
