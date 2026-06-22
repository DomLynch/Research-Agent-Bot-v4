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
from scripts import alpha_publish_io as publish_io
from scripts import daily_alpha_publish_cycle as cycle

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"
_LEGACY_AGENT_REPAIR_DECISIONS = {
    "agent_repair_needed", "needs_operator_review", "needs_operator_approval",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def _alpha_runs(include_archive: bool) -> list[Path]:
    patterns = ["*-evidence-*"]
    if include_archive:
        patterns.append("_archive/*/*-evidence-*")
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in patterns:
        for path in sorted(_RUNS.glob(pattern)):
            run = path if path.is_dir() else path.parent
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


def _write_json(path: Path, payload: Any) -> None:
    publish_io.write_json(path, payload)


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


def _stage_blockers(run: Path) -> list[str]:
    required = (
        "alpha_memo.md",
        "opportunities_gate.json",
        "fact_lanes.json",
        "all_facts.json",
        "claim_receipt_matrix.json",
        "typed_counter_evidence.json",
        "novelty_delta.json",
        "memo_audit.json",
    )
    return [f"missing_{name.rsplit('.', 1)[0]}" for name in required if not run.joinpath(name).exists()]


def _verdict_for_run(run: Path) -> dict[str, Any]:
    if (run / "business_candidate_bundle.json").exists():
        stored = _read_json(run / "publish_verdict.json")
        if stored:
            return stored
    if _can_recompute_verdict(run):
        return publish_verdict(run)
    stored = _read_json(run / "publish_verdict.json")
    if stored:
        return stored
    blockers = _stage_blockers(run)
    return {
        "topic": _topic(run),
        "run_dir": str(run.relative_to(_ROOT)) if run.is_relative_to(_ROOT) else str(run),
        "decision": "not_ready",
        "publish_tier": "UNBUILT",
        "blockers": blockers,
        "stage": blockers[0] if blockers else "not_ready",
    }


def _normalised_decision(row: dict[str, Any]) -> str:
    decision = str(row.get("decision") or "")
    return "agent_repair_needed" if decision in _LEGACY_AGENT_REPAIR_DECISIONS else decision


def _queue_ready_row(row: dict[str, Any]) -> dict[str, Any]:
    if (
        _normalised_decision(row) != "ready_to_publish"
        or row.get("surface_type") != "evidence_map"
    ):
        return row
    min_citations = cycle._alpha_memo_int("evidence_map_min_citations", 10)
    if cycle._direct_source_count(row, _RUNS) < min_citations:
        status = "evidence_map_below_citation_floor"
    elif not cycle._map_scope_coherent(row, _RUNS, min_citations):
        status = "evidence_map_scope_mismatch"
    else:
        return row
    blockers = row.get("blockers")
    blocker_list = blockers if isinstance(blockers, list) else []
    return row | {
        "decision": "curation_needed",
        "queue_status": status,
        "blockers": sorted({*(str(b) for b in blocker_list), status}),
    }


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
        if run_domain:
            row = row | {
                "domain": load_domain_profile(run_domain).as_metadata(),
                "domain_slug": run_domain,
            }
        row = _queue_ready_row(row)
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
        "not_ready": [
            r for r in rows if _normalised_decision(r) == "not_ready"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--domain", choices=domain_choices(), default=None)
    parser.add_argument("--output", type=Path, default=_RUNS / "_publish_queue.json")
    args = parser.parse_args()
    queue = build_queue(include_archive=not args.current_only, domain=args.domain)
    _write_json(args.output, queue)
    print(
        "[publish-queue] "
        f"ready={len(queue['ready_to_publish'])} "
        f"repair={len(queue['agent_repair_needed'])} "
        f"curation={len(queue['curation_needed'])} "
        f"not_ready={len(queue['not_ready'])} -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
