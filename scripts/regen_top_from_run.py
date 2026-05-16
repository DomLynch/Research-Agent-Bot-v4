"""Sprint 70 — regenerate top_N.md for an existing run.

Offline tool: takes an existing runs/<topic>-evidence-<ts>/ folder,
re-runs filter_artifacts -> _interestingness -> _dedup_by_paper_subtopic
-> _render_md against `all_facts.json`, and overwrites top_N.md.

Use after a sanitizer/scoring change to refresh on-disk artifacts
without hitting the live Researka DB. Universal — works for any
topic-evidence run dir.

Usage:
    python scripts/regen_top_from_run.py <run-dir> [--top N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.numeric_sanitizer import filter_artifacts
from scripts.build_topic_evidence_run import (
    _dedup_by_paper_subtopic,
    _interestingness,
    _rankable_facts_for_top,
    _render_md,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    p.add_argument("--top", type=int, default=5)
    args = p.parse_args()

    run = args.run_dir
    facts_path = run / "all_facts.json"
    if not facts_path.exists():
        print(f"no all_facts.json under {run}", file=sys.stderr)
        return 2
    data = json.loads(facts_path.read_text(encoding="utf-8"))
    facts = data if isinstance(data, list) else data.get("facts", [])

    topic = run.name.split("-evidence-")[0]
    ts = run.name.split("-evidence-", 1)[1] if "-evidence-" in run.name else ""

    facts, _drop = filter_artifacts(facts)
    rankable_facts = _rankable_facts_for_top(facts, topic)
    scored = sorted(((_interestingness(f), f) for f in rankable_facts),
                    key=lambda pair: pair[0], reverse=True)
    deduped = _dedup_by_paper_subtopic(scored)
    top = deduped[: args.top]
    tier = str((facts[0].get("_tier") if facts else "") or "none")
    md = _render_md(topic, ts, top, len(facts), tier, mimo_editorial=None)

    out_path = run / f"top_{args.top}.md"
    out_path.write_text(md, encoding="utf-8")
    manifest_path = run / "MANIFEST.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if isinstance(manifest, dict):
            files = manifest.setdefault("files", {})
            if isinstance(files, dict):
                files["top_md"] = {
                    "name": out_path.name,
                    "sha256": _sha256(md),
                }
                manifest_path.write_text(
                    json.dumps(manifest, indent=2),
                    encoding="utf-8",
                )
    print(f"regenerated {out_path} ({len(top)} cards, "
          f"{len(_drop)} artifacts filtered)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
