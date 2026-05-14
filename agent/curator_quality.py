"""Sprint 58 (Layer 8) — curator-quality feedback loop.

Walks every source_audit.json in the runs/ tree, joins each verdict to
its source-paper fact via the sibling all_facts.json to recover the
DB-stored validator (curator_id), aggregates per-curator stats. Output
is a top-level dashboard: which curators produce most errors, what
their dies-rate is over time, which topics they touch most.

End-game closure: Sprint 57 turned each dies verdict into a machine-
actionable correction; this sprint quantifies WHICH curator entered
those errors so the DB team can batch-revalidate or retrain.

Universal: validator field is just a string; no biomedical assumption.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CuratorStats:
    curator_id: str
    facts_audited: int
    survives: int
    dies: int
    needs_extraction: int
    disagreement: int
    topics_touched: tuple[str, ...]

    @property
    def error_rate(self) -> float:
        return round(self.dies / self.facts_audited, 3) \
            if self.facts_audited else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"curator_id": self.curator_id,
                "facts_audited": self.facts_audited,
                "survives": self.survives, "dies": self.dies,
                "needs_extraction": self.needs_extraction,
                "disagreement": self.disagreement,
                "error_rate": self.error_rate,
                "topics_touched": list(self.topics_touched)}


def _facts_by_id(facts: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in facts:
        if isinstance(f, dict):
            fid = str(f.get("fact_id") or "")
            if fid:
                out[fid] = f
    return out


def aggregate_from_runs(runs_root: Path) -> tuple[CuratorStats, ...]:
    """Walk runs/*-evidence-*/ folders; aggregate per-curator stats."""
    if not runs_root.exists():
        return ()
    audited: dict[str, dict[str, Any]] = {}
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir() or "-evidence-" not in run_dir.name:
            continue
        audit_path = run_dir / "source_audit.json"
        facts_path = run_dir / "all_facts.json"
        if not audit_path.exists() or not facts_path.exists():
            continue
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(audit, dict) or not isinstance(facts, list):
            continue
        topic = str(audit.get("topic") or "unknown")
        fbid = _facts_by_id(facts)
        for v in audit.get("verdicts", []):
            if not isinstance(v, dict):
                continue
            fid = str(v.get("fact_id") or "")
            fact = fbid.get(fid) or {}
            curator = str(fact.get("validator") or "unknown")
            verdict = str(v.get("verdict") or "")
            row = audited.setdefault(curator, {
                "facts_audited": 0, "survives": 0, "dies": 0,
                "needs_extraction": 0, "disagreement": 0,
                "topics": set(),
            })
            row["facts_audited"] += 1
            if verdict in ("survives", "dies", "needs_extraction",
                           "disagreement"):
                row[verdict] += 1
            row["topics"].add(topic)
    out: list[CuratorStats] = []
    for curator, row in audited.items():
        out.append(CuratorStats(
            curator_id=curator, facts_audited=int(row["facts_audited"]),
            survives=int(row["survives"]), dies=int(row["dies"]),
            needs_extraction=int(row["needs_extraction"]),
            disagreement=int(row["disagreement"]),
            topics_touched=tuple(sorted(row["topics"])),
        ))
    out.sort(key=lambda c: (c.error_rate, c.dies, c.facts_audited),
             reverse=True)
    return tuple(out)


def render_dashboard_md(stats: tuple[CuratorStats, ...]) -> str:
    """Human-readable per-curator dashboard, sorted by error_rate."""
    head = (
        "# Curator-quality dashboard\n\n"
        f"**Curators tracked:** {len(stats)}\n"
        f"**Total facts audited:** {sum(s.facts_audited for s in stats)}\n"
        f"**Total dies:** {sum(s.dies for s in stats)}\n\n"
        "Sorted by error_rate (= dies / facts_audited) desc.\n\n"
        "| Curator | Audited | Survives | Dies | NE | Disagree | "
        "Error rate | Topics |\n"
        "|---|---:|---:|---:|---:|---:|---:|---|\n"
    )
    if not stats:
        return head + "_No source_audit.json files found in runs/._\n"
    rows = []
    for s in stats:
        topics = ", ".join(s.topics_touched) if s.topics_touched else "—"
        rows.append(
            f"| `{s.curator_id}` | {s.facts_audited} | {s.survives} | "
            f"**{s.dies}** | {s.needs_extraction} | {s.disagreement} | "
            f"**{s.error_rate}** | {topics} |"
        )
    return head + "\n".join(rows) + "\n"
