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


def _default_output_path() -> Path:
    return _RUNS / "_publish_queue.json"


def _domain_output_path(domain: str | None) -> Path | None:
    if domain:
        return _RUNS / f"_publish_queue.{domain}.json"
    return None


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


def _display_path(path: Path) -> str:
    return str(path.relative_to(_ROOT)) if path.is_relative_to(_ROOT) else str(path)


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


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


def _diagnostic_rows(
    *, domain: str | None, existing: set[tuple[str, str]], seed_keys: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    diag_dir = _RUNS / "_business_diagnostics"
    for path in sorted(diag_dir.glob("*.json")):
        if path.name.startswith("latest_sweep"):
            continue
        data = _read_json(path)
        row_domain = domain_slug(data.get("domain"))
        topic = str(data.get("topic") or "").strip()
        if not row_domain or not topic:
            continue
        if domain and row_domain != domain:
            continue
        if seed_keys and not (_scope_keys(topic) & seed_keys):
            continue
        key = (row_domain, topic)
        if key in existing:
            continue
        rows.append({
            "topic": topic,
            "domain": load_domain_profile(row_domain).as_metadata(),
            "domain_slug": row_domain,
            "decision": "not_ready",
            "publish_tier": "UNBUILT",
            "stage": "no_source_diverse_bundle",
            "queue_status": "no_source_diverse_bundle",
            "blockers": ["no_source_diverse_bundle"],
            "diagnostics_path": _display_path(path),
            "raw_fact_count": _int(data.get("raw_fact_count")),
            "normalized_fact_count": _int(data.get("normalized_fact_count")),
            "a_core_fact_count": _int(data.get("a_core_fact_count")),
        })
        existing.add(key)
    return rows


def build_queue(
    include_archive: bool = True, domain: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    rows = []
    seed_keys = _domain_seed_keys(domain)
    default_domain = load_domain_profile(None).slug
    existing: set[tuple[str, str]] = set()
    submitted_path = _RUNS / "_daily_ledger" / "_submitted_fingerprints.json"
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
        row = cycle._queue_ready_row(row, _RUNS)
        row = cycle._queue_submitted_duplicate_row(
            row, _RUNS, submitted_path, run_domain or domain,
        )
        rows.append(row)
        existing.add((run_domain, str(row.get("topic") or _topic(run))))
    rows.extend(_diagnostic_rows(domain=domain, existing=existing, seed_keys=seed_keys))
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
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or _default_output_path()
    queue = build_queue(include_archive=not args.current_only, domain=args.domain)
    _write_json(output, queue)
    domain_output = _domain_output_path(args.domain)
    if domain_output and domain_output != output:
        _write_json(domain_output, queue)
    print(
        "[publish-queue] "
        f"ready={len(queue['ready_to_publish'])} "
        f"repair={len(queue['agent_repair_needed'])} "
        f"curation={len(queue['curation_needed'])} "
        f"not_ready={len(queue['not_ready'])} -> {output}"
        + (f" domain_output={domain_output}" if domain_output else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
