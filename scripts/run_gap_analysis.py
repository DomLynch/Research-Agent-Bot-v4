"""Sprint 44 — CLI for the v4 gap-analyser.

Walks `runs/_index/<topic>/` for every topic, emits the prioritized
publish-opportunity digest. v3 (paper writer) reads the JSON output
to decide when to write.

Usage:
    python scripts/run_gap_analysis.py
    python scripts/run_gap_analysis.py --out runs/_index/_digest_<ts>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.gap_analyzer import run_gap_analysis

_INDEX_ROOT = Path(__file__).resolve().parent.parent / "runs" / "_index"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None,
                        help="Override output path (default: "
                             "runs/_index/_digest_<utc-stamp>.json)")
    args = parser.parse_args()
    snapshot_utc = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    digest = run_gap_analysis(_INDEX_ROOT, snapshot_utc=snapshot_utc)
    out_path = args.out or (_INDEX_ROOT / f"_digest_{snapshot_utc}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(digest.as_dict(), indent=2), encoding="utf-8",
    )
    print(f"[gap] topics_inspected={digest.topics_inspected} "
          f"opportunities={len(digest.opportunities)} → {out_path}")
    for o in digest.opportunities:
        print(f"  [{o.priority:3}]  {o.topic:12}  {o.reason:32}  "
              f"conf={o.confidence_0_100} Δ={o.delta_points:+d}  "
              f"{o.claim_text[:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
