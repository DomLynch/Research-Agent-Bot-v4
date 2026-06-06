"""Build a local evidence inventory for a specialist alpha domain."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.domain_profile import domain_choices, domain_slug, load_domain_profile
from agent.topic_discovery import load_seed_topics

Json = dict[str, Any]

_RUNS = Path(__file__).resolve().parent.parent / "runs"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dict(value: Any) -> Json:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _topic(run: Path) -> str:
    return run.name.split("-evidence-", 1)[0]


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _source_key(fact: Json) -> str:
    paper = _dict(fact.get("source_paper"))
    for key in ("doi", "pmid", "pmcid", "paper_id", "id", "title"):
        value = str(paper.get(key) or "").strip()
        if value:
            return value
    return ""


def _run_domain(run: Path) -> str:
    verdict = _dict(_read_json(run / "publish_verdict.json"))
    manifest = _dict(_read_json(run / "MANIFEST.json"))
    trace = _dict(_read_json(run / "search_trace.json"))
    return (
        domain_slug(verdict.get("domain"))
        or domain_slug(manifest.get("domain"))
        or domain_slug(trace.get("domain"))
    )


def _candidate_rows(payload: Json) -> list[Json]:
    raw = payload.get("all") or payload.get("top") or []
    return [row for row in _list(raw) if isinstance(row, dict) and row.get("topic")]


def _latest_discovery(runs_root: Path, domain: str) -> Json:
    out_dir = runs_root / "_topics_discovery"
    for path in sorted(out_dir.glob("*.json"), reverse=True):
        payload = _dict(_read_json(path))
        if domain_slug(payload.get("domain")) == domain:
            return payload | {"_path": _rel(path, runs_root)}
    return {}


def _evidence_runs(
    runs_root: Path, *, include_archive: bool, domain: str,
) -> dict[str, list[Path]]:
    patterns = ["*-evidence-*"]
    if include_archive:
        patterns.append("_archive/*/*-evidence-*")
    grouped: dict[str, list[Path]] = {}
    seen: set[Path] = set()
    for pattern in patterns:
        for run in sorted(runs_root.glob(pattern)):
            if run in seen or not run.is_dir() or _run_domain(run) != domain:
                continue
            seen.add(run)
            grouped.setdefault(_topic(run), []).append(run)
    for runs in grouped.values():
        runs.sort(key=lambda path: path.name)
    return grouped


def _run_summary(run: Path, runs_root: Path) -> Json:
    verdict = _dict(_read_json(run / "publish_verdict.json"))
    retrieval = _dict(_read_json(run / "retrieval_status.json"))
    facts = [fact for fact in _list(_read_json(run / "all_facts.json")) if isinstance(fact, dict)]
    lane_rows = _list(_dict(_read_json(run / "fact_lanes.json")).get("verdicts"))
    lane_counts = Counter(
        str(row.get("lane") or "")
        for row in lane_rows
        if isinstance(row, dict) and row.get("lane")
    )
    return {
        "run_dir": _rel(run, runs_root),
        "status": str(retrieval.get("status") or ("ok" if facts else "unknown")),
        "decision": str(verdict.get("decision") or ""),
        "publish_tier": str(verdict.get("publish_tier") or ""),
        "alpha_score": _int(verdict.get("alpha_score")),
        "confidence_label": str(verdict.get("confidence_label") or ""),
        "surface_type": str(verdict.get("surface_type") or ""),
        "headline": str(verdict.get("headline") or ""),
        "fact_count": len(facts),
        "source_count": len({key for fact in facts if (key := _source_key(fact))}),
        "lane_counts": dict(sorted(lane_counts.items())),
    }


def _discovery_summary(candidate: Json) -> Json:
    return {
        "paper_count": _int(candidate.get("paper_count")),
        "fact_source_count": _int(candidate.get("fact_source_count")),
        "velocity_score": _float(candidate.get("velocity_score")),
        "mean_fwci": _float(candidate.get("mean_fwci")),
        "mean_cited_by": _float(candidate.get("mean_cited_by")),
        "top_paper_doi": str(candidate.get("top_paper_doi") or ""),
        "top_paper_title": str(candidate.get("top_paper_title") or ""),
    }


def build_inventory(
    domain: str,
    *,
    runs_root: Path = _RUNS,
    include_archive: bool = True,
    snapshot_utc: str | None = None,
) -> Json:
    profile = load_domain_profile(domain)
    seeds = load_seed_topics(profile.seed_topics_path)
    discovery = _latest_discovery(runs_root, profile.slug)
    discovery_rows = {str(row["topic"]): row for row in _candidate_rows(discovery)}
    runs_by_topic = _evidence_runs(
        runs_root, include_archive=include_archive, domain=profile.slug,
    )
    topics = sorted(set(seeds) | set(discovery_rows) | set(runs_by_topic))
    rows: list[Json] = []
    for topic in topics:
        run_summaries = [_run_summary(run, runs_root) for run in runs_by_topic.get(topic, [])]
        latest_run = run_summaries[-1] if run_summaries else {}
        discovery_summary = (
            _discovery_summary(discovery_rows[topic]) if topic in discovery_rows else {}
        )
        rows.append({
            "topic": topic,
            "seeded": topic in seeds,
            "discovered": bool(discovery_summary),
            "discovery": discovery_summary,
            "evidence_run_count": len(run_summaries),
            "latest_evidence_run": latest_run,
        })
    rows.sort(key=lambda row: (
        not row["latest_evidence_run"],
        -int(row["discovery"].get("fact_source_count") or 0),
        -float(row["discovery"].get("velocity_score") or 0.0),
        str(row["topic"]),
    ))
    return {
        "domain": profile.as_metadata(),
        "snapshot_utc": snapshot_utc
        or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "runs_root": runs_root.as_posix(),
        "include_archive": include_archive,
        "seed_count": len(seeds),
        "discovery_snapshot": discovery.get("snapshot_utc", ""),
        "discovery_path": discovery.get("_path", ""),
        "discovery_candidate_count": len(discovery_rows),
        "evidence_run_count": sum(len(runs) for runs in runs_by_topic.values()),
        "evidence_topic_count": len(runs_by_topic),
        "topic_count": len(rows),
        "topics": rows,
    }


def write_inventory(inventory: Json, output: Path | None = None) -> Path:
    domain = domain_slug(inventory.get("domain"))
    snapshot = str(inventory.get("snapshot_utc") or "inventory")
    out = output or (
        Path(str(inventory["runs_root"]))
        / "_domain_inventory"
        / domain
        / f"{snapshot}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    if output is None:
        (out.parent / "_latest.json").write_text(
            json.dumps({
                "snapshot_file": out.name,
                "snapshot_utc": snapshot,
                "domain": inventory.get("domain"),
            }, indent=2),
            encoding="utf-8",
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=domain_choices(), default="longevity")
    parser.add_argument("--runs-root", type=Path, default=_RUNS)
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    inventory = build_inventory(
        args.domain,
        runs_root=args.runs_root,
        include_archive=not args.current_only,
    )
    out = write_inventory(inventory, args.output)
    print(
        "[domain-inventory] "
        f"domain={inventory['domain']['slug']} "
        f"topics={inventory['topic_count']} "
        f"runs={inventory['evidence_run_count']} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
