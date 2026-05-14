"""Sprint 58 — CLI for the curator-quality dashboard.

Walks runs/*-evidence-*/ folders, aggregates per-curator stats from
each source_audit.json, writes:
  runs/_curator_quality/<utc>.json   -- raw stats
  runs/_curator_quality/<utc>.md     -- human dashboard

Re-runnable; latest run supersedes prior dashboards.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.curator_quality import aggregate_from_runs, render_dashboard_md

_RUNS = Path(__file__).resolve().parent.parent / "runs"


def main() -> int:
    stats = aggregate_from_runs(_RUNS)
    out_dir = _RUNS / "_curator_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    payload = {"snapshot_utc": ts, "curators": [s.as_dict() for s in stats]}
    json_path = out_dir / f"{ts}.json"
    md_path = out_dir / f"{ts}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    md_path.write_text(render_dashboard_md(stats), encoding="utf-8")
    total_dies = sum(s.dies for s in stats)
    total_audited = sum(s.facts_audited for s in stats)
    print(f"[curator-quality] curators={len(stats)} "
          f"facts_audited={total_audited} total_dies={total_dies} "
          f"-> {json_path}")
    for s in stats[:5]:
        print(f"  {s.curator_id:55}  audited={s.facts_audited:3}  "
              f"dies={s.dies:2}  error_rate={s.error_rate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
