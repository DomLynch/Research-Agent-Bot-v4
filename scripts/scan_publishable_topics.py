#!/usr/bin/env python3
"""Reproducible diagnostic: per-topic coherent-source count.

A topic is "publishable" when its largest cluster of distinct A_core source
papers sharing ONE claim reaches the source floor. Writes a timestamped JSON
artifact under runs/_diagnostics/ so the publishable-topic count is auditable.

Hits the live Researka DB (slow) — this is a diagnostic, not a unit test.

Usage:
    python scripts/scan_publishable_topics.py omega_3_longevity GLP_1_longevity ...
    python scripts/scan_publishable_topics.py --floor 5 <topic> [<topic> ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT))

import build_topic_evidence_run as evidence_run  # noqa: E402

from agent import signal_memo_writer as memo  # noqa: E402
from agent.fact_lanes import classify_lanes  # noqa: E402


def _source(fact: dict[str, Any]) -> str:
    paper = fact.get("source_paper") or {}
    return str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
               or paper.get("paper_id") or paper.get("id")
               or paper.get("title") or "").strip()


def scan_topic(topic: str) -> dict[str, Any]:
    facts = evidence_run._fetch_facts(topic)
    by_id = {str(f.get("fact_id")): f for f in facts}
    lanes = {str(v.fact_id): v.lane for v in classify_lanes(facts, topic)}
    a_core = [f for f in facts if lanes.get(str(f.get("fact_id"))) == "A_core"]
    best = 0
    for seed in a_core:
        claim = memo._claim_signal([str(seed.get("fact_id"))], by_id, topic)
        cluster = {_source(f) for f in a_core
                   if _source(f) and memo._fact_coheres(f, claim, topic)}
        best = max(best, len(cluster))
    return {
        "topic": topic,
        "papers": len({_source(f) for f in facts if _source(f)}),
        "a_core_papers": len({_source(f) for f in a_core if _source(f)}),
        "coherent_sources": best,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("topics", nargs="+")
    ap.add_argument("--floor", type=int, default=5)
    args = ap.parse_args()

    rows = [scan_topic(t) for t in args.topics]
    publishable = [r for r in rows if r["coherent_sources"] >= args.floor]
    artifact = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "floor": args.floor,
        "publishable": len(publishable),
        "total": len(rows),
        "rows": rows,
    }
    dst = _ROOT / "runs" / "_diagnostics" / "publishable_scan.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    for r in rows:
        flag = "PUBLISHABLE" if r["coherent_sources"] >= args.floor else ""
        print(f"  {r['topic']:<30} papers={r['papers']:3d} "
              f"a_core={r['a_core_papers']:2d} coherent={r['coherent_sources']:2d}  {flag}")
    print(f"PUBLISHABLE {len(publishable)}/{len(rows)} "
          f"(floor={args.floor}) -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
