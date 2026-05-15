"""Sprint 59 CLI — Evidence Opportunities Gate orchestration.

Given an existing runs/<topic>-evidence-<ts>/ folder, this CLI:
  1. Reads all_facts.json + frontier_review.json
  2. Classifies each fact into A_core / B_context / C_noise / D_bad
  3. Builds an input pack and reports A_core density
  4. Audits each frontier thesis through the 5 hard gates
  5. Emits:
       fact_lanes.json
       opportunities_gate.json
       paper_opportunities.md   -- only surviving theses, capped scores

Lives in scripts/ → zero agent/ LOC cost. Re-runnable on any run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.fact_lanes import LaneVerdict, classify_lanes, lane_counts
from agent.frontier_audit import ThesisAudit, audit_frontier_review
from agent.frontier_input_pack import build_input_pack


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render_md(
    topic: str, snapshot: str, audits: list[ThesisAudit],
    counts: dict[str, int], a_core_min: int, has_min: bool,
) -> str:
    head = (
        f"# Paper opportunities — {topic}\n\n"
        f"**Snapshot:** {snapshot}\n"
        f"**Lane counts:** A_core={counts['A_core']} "
        f"B_context={counts['B_context']} "
        f"C_noise={counts['C_noise']} "
        f"D_bad_extraction={counts['D_bad_extraction']}\n"
        f"**A_core min for paper opportunity:** {a_core_min} "
        f"(satisfied: {'yes' if has_min else 'NO'})\n\n"
        "Only theses with `status=survives` are real publish "
        "opportunities. `needs_source_audit` requires manual review "
        "of source metadata + A_core density before elevation. "
        "`rejected` cannot be elevated regardless of opportunity "
        "score — they cite D_bad_extraction or mix metric families.\n\n"
        "---\n\n"
    )
    if not audits:
        return head + "_No theses to audit._\n"
    blocks: list[str] = []
    for a in sorted(audits, key=lambda x: x.capped_opportunity, reverse=True):
        badge = {"survives": "PASS", "needs_source_audit": "AUDIT",
                 "rejected": "FAIL"}.get(a.status, "?")
        flags = ", ".join(a.blocking_flags) if a.blocking_flags else "_none_"
        cap_note = ("" if a.capped_opportunity == a.original_opportunity
                    else f" (capped from {a.original_opportunity})")
        blocks.append(
            f"## [{badge}] {a.title}\n\n"
            f"- **Status:** `{a.status}`\n"
            f"- **Opportunity:** {a.capped_opportunity}{cap_note}\n"
            f"- **Cited facts:** {len(a.cited_fact_ids)}\n"
            f"- **Blocking flags:** {flags}\n",
        )
    return head + "\n---\n\n".join(blocks) + "\n"


def _update_manifest(
    run_dir: Path, lanes_text: str, gate_text: str, opp_text: str,
) -> None:
    manifest_path = run_dir / "MANIFEST.json"
    if not manifest_path.exists():
        return
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(m, dict):
        return
    files = m.get("files")
    if not isinstance(files, dict):
        files = {}
        m["files"] = files
    files["fact_lanes"] = {"name": "fact_lanes.json",
                            "sha256": _sha256(lanes_text)}
    files["opportunities_gate"] = {"name": "opportunities_gate.json",
                                    "sha256": _sha256(gate_text)}
    files["paper_opportunities_md"] = {"name": "paper_opportunities.md",
                                        "sha256": _sha256(opp_text)}
    manifest_path.write_text(json.dumps(m, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--a-core-min", type=int, default=3)
    args = parser.parse_args()
    run_dir: Path = args.run
    facts_path = run_dir / "all_facts.json"
    review_path = run_dir / "frontier_review.json"
    if not facts_path.exists():
        print(f"[opps-gate] no all_facts.json under {run_dir}",
              file=sys.stderr)
        return 1
    topic, snapshot_utc = run_dir.name.split("-evidence-")[0], "unknown"
    manifest_path = run_dir / "MANIFEST.json"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            topic = str(m.get("topic") or topic)
            snapshot_utc = str(m.get("snapshot_utc") or snapshot_utc)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        facts_raw: Any = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[opps-gate] could not read facts: {e}", file=sys.stderr)
        return 1
    if not isinstance(facts_raw, list):
        print("[opps-gate] all_facts.json is not a list", file=sys.stderr)
        return 1
    facts: list[dict[str, Any]] = [f for f in facts_raw if isinstance(f, dict)]
    lanes: list[LaneVerdict] = classify_lanes(facts, topic)
    counts = lane_counts(lanes)
    pack = build_input_pack(facts, topic, a_core_min=args.a_core_min,
                            lane_verdicts=lanes)
    audits: list[ThesisAudit] = []
    if review_path.exists():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            review = {}
        if isinstance(review, dict):
            audits = audit_frontier_review(
                review, facts, lanes, a_core_min=args.a_core_min,
            )
    lanes_payload = {"topic": topic, "snapshot_utc": snapshot_utc,
                     "counts": counts,
                     "verdicts": [v.as_dict() for v in lanes]}
    gate_payload = {"topic": topic, "snapshot_utc": snapshot_utc,
                    "input_pack": pack.as_dict(),
                    "audits": [a.as_dict() for a in audits]}
    lanes_text = json.dumps(lanes_payload, indent=2, ensure_ascii=False)
    gate_text = json.dumps(gate_payload, indent=2, ensure_ascii=False)
    opp_text = _render_md(topic, snapshot_utc, audits, counts,
                          args.a_core_min, pack.has_minimum_a_core)
    (run_dir / "fact_lanes.json").write_text(lanes_text, encoding="utf-8")
    (run_dir / "opportunities_gate.json").write_text(gate_text, encoding="utf-8")
    (run_dir / "paper_opportunities.md").write_text(opp_text, encoding="utf-8")
    _update_manifest(run_dir, lanes_text, gate_text, opp_text)
    print(f"[opps-gate] {run_dir.name}: "
          f"A={counts['A_core']} B={counts['B_context']} "
          f"C={counts['C_noise']} D={counts['D_bad_extraction']}  "
          f"theses={len(audits)} has_min_a_core={pack.has_minimum_a_core}")
    for a in audits:
        cap = ("" if a.capped_opportunity == a.original_opportunity
               else f" (capped from {a.original_opportunity})")
        print(f"  [{a.status:18}]  opp={a.capped_opportunity}{cap}  "
              f"{a.title[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
