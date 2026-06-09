"""Build the ReseaRka alpha publish queue from run folders."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.domain_profile import domain_choices, domain_slug, load_domain_profile
from agent.publish_tier import publish_verdict

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"
_LEGACY_AGENT_REPAIR_DECISIONS = {
    "agent_repair_needed", "needs_operator_review", "needs_operator_approval",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def _alpha_runs(include_archive: bool) -> list[Path]:
    patterns = ["*-evidence-*/alpha_memo.md"]
    if include_archive:
        patterns.append("_archive/*/*-evidence-*/alpha_memo.md")
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in patterns:
        for path in sorted(_RUNS.glob(pattern)):
            run = path.parent
            if run not in seen:
                seen.add(run)
                out.append(run)
    return out


def _topic(run: Path) -> str:
    return run.name.split("-evidence-", 1)[0]


def _latest_per_topic(runs: list[Path]) -> list[Path]:
    latest: dict[str, Path] = {}
    for run in runs:
        topic = _topic(run)
        prev = latest.get(topic)
        if prev is None or run.name > prev.name:
            latest[topic] = run
    return sorted(latest.values(), key=lambda p: p.name)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_domain(run: Path, verdict: dict[str, Any]) -> str:
    return (
        domain_slug(verdict.get("domain"))
        or domain_slug(_read_json(run / "MANIFEST.json").get("domain"))
        or domain_slug(_read_json(run / "search_trace.json").get("domain"))
    )


def _scope_keys(value: object) -> set[str]:
    text = str(value or "").lower()
    tokens = [token for token in _WORD_RE.findall(text) if len(token) >= 5]
    exact = "_".join(_WORD_RE.findall(text))
    keys = {"topic:" + exact} if exact else set()
    keys.update("token:" + token for token in tokens)
    return keys


def _domain_seed_keys(domain: str | None) -> set[str]:
    if not domain or domain == load_domain_profile(None).slug:
        return set()
    try:
        data = tomllib.loads(load_domain_profile(domain).seed_topics_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return set()
    seeds = data.get("seeds")
    topics = seeds.get("topics") if isinstance(seeds, dict) else None
    if not isinstance(topics, list):
        return set()
    out: set[str] = set()
    for topic in topics:
        out.update(_scope_keys(topic))
    return out


def _run_scope_keys(run: Path, verdict: dict[str, Any]) -> set[str]:
    values = (
        _topic(run),
        verdict.get("topic"),
        verdict.get("topic_family"),
        verdict.get("parent_topic") or verdict.get("_parent_topic"),
    )
    out: set[str] = set()
    for value in values:
        out.update(_scope_keys(value))
    return out


def _can_recompute_verdict(run: Path) -> bool:
    return all(
        run.joinpath(name).exists()
        for name in ("alpha_memo.md", "opportunities_gate.json", "fact_lanes.json", "all_facts.json")
    )


def _verdict_for_run(run: Path) -> dict[str, Any]:
    if _can_recompute_verdict(run):
        return publish_verdict(run)
    return _read_json(run / "publish_verdict.json")


def _normalised_decision(row: dict[str, Any]) -> str:
    decision = str(row.get("decision") or "")
    return "agent_repair_needed" if decision in _LEGACY_AGENT_REPAIR_DECISIONS else decision


def build_queue(
    include_archive: bool = True, domain: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    rows = []
    seed_keys = _domain_seed_keys(domain)
    default_domain = load_domain_profile(None).slug
    for run in _latest_per_topic(_alpha_runs(include_archive)):
        row = _verdict_for_run(run)
        run_domain = _run_domain(run, row) or (
            default_domain if domain == default_domain else ""
        )
        if domain and run_domain != domain:
            continue
        if seed_keys and not (_run_scope_keys(run, row) & seed_keys):
            continue
        rows.append(row)
    rank = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2}
    rows.sort(key=lambda r: (
        rank.get(str(r.get("publish_tier")), 9),
        -int(r.get("alpha_score") or 0),
        str(r.get("topic") or ""),
    ))
    return {
        "ready_to_publish": [
            r for r in rows if _normalised_decision(r) == "ready_to_publish"
        ],
        "agent_repair_needed": [
            r for r in rows if _normalised_decision(r) == "agent_repair_needed"
        ],
        "curation_needed": [
            r for r in rows if _normalised_decision(r) == "curation_needed"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--domain", choices=domain_choices(), default=None)
    parser.add_argument("--output", type=Path, default=_RUNS / "_publish_queue.json")
    args = parser.parse_args()
    queue = build_queue(include_archive=not args.current_only, domain=args.domain)
    args.output.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    print(
        "[publish-queue] "
        f"ready={len(queue['ready_to_publish'])} "
        f"repair={len(queue['agent_repair_needed'])} "
        f"curation={len(queue['curation_needed'])} -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
