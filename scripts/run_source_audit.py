"""Sprint 52 — CLI for the source-audit layer.

Reads `runs/<topic>-evidence-<ts>/all_facts.json`, fetches each fact's
source-paper abstract from PubMed, asks Gemma to verify the DB claim,
emits `source_audit.json` + `source_audit.md` into the same run folder
plus a sha256-stamped entry in MANIFEST.json. Pure operator surface —
lives in scripts/ so it costs zero agent/ LOC.

Usage:
    python scripts/run_source_audit.py --run runs/rapamycin-evidence-<ts>
    python scripts/run_source_audit.py --run <dir> --no-update-manifest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.settings import load_settings
from agent.source_audit import SourceAuditReport, run_source_audit


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render_md(report: SourceAuditReport) -> str:
    head = (
        f"# Source-fact audit — {report.topic}\n\n"
        f"**Snapshot:** {report.snapshot_utc}\n"
        f"**Facts inspected:** {report.facts_inspected}\n"
        f"**Survives:** {report.survives}   "
        f"**Dies:** {report.dies}   "
        f"**Needs extraction:** {report.needs_extraction}\n\n"
        "Verdicts come from Gemma (judge model, temperature 0.0) "
        "comparing each fact's DB-stored value + subgroup attribution "
        "against the source paper's PubMed abstract. `dies` means the "
        "abstract contradicts the DB claim (wrong number, wrong "
        "subgroup, or wrong metric). `needs_extraction` means the "
        "abstract did not discuss the value directly.\n\n"
        "---\n\n"
    )
    blocks = []
    for v in report.verdicts:
        badge = {"survives": "OK", "dies": "FAIL",
                 "needs_extraction": "?"}.get(v.verdict, "?")
        blocks.append(
            f"## [{badge}] {v.fact_id}\n\n"
            f"- **Verdict:** `{v.verdict}`\n"
            f"- **DB value:** {v.db_value}\n"
            f"- **PMID:** {v.pmid or '(none)'}\n"
            f"- **Source quote:** {v.source_quote or '_none_'}\n"
            f"- **Reason:** {v.reason or '_none_'}\n",
        )
    return head + "\n---\n\n".join(blocks) + "\n"


def _update_manifest(run_dir: Path, audit_md: str, audit_json: str) -> None:
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
    files["source_audit_md"] = {"name": "source_audit.md",
                                "sha256": _sha256(audit_md)}
    files["source_audit_json"] = {"name": "source_audit.json",
                                  "sha256": _sha256(audit_json)}
    m["source_audit_model"] = "gemma-judge"
    manifest_path.write_text(json.dumps(m, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True,
                        help="Path to a runs/<topic>-evidence-<ts>/ folder")
    parser.add_argument("--no-update-manifest", action="store_true")
    args = parser.parse_args()
    run_dir: Path = args.run
    facts_path = run_dir / "all_facts.json"
    if not facts_path.exists():
        print(f"[source-audit] no all_facts.json under {run_dir}",
              file=sys.stderr)
        return 1
    manifest_path = run_dir / "MANIFEST.json"
    topic, snapshot_utc = "unknown", "unknown"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            topic = str(m.get("topic") or topic)
            snapshot_utc = str(m.get("snapshot_utc") or snapshot_utc)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[source-audit] could not read facts: {e}", file=sys.stderr)
        return 1
    if not isinstance(facts, list):
        print("[source-audit] all_facts.json is not a list", file=sys.stderr)
        return 1

    settings = load_settings()
    ncbi_key = os.environ.get("NCBI_API_KEY", "")
    with httpx.Client() as client:
        report = run_source_audit(
            topic=topic, snapshot_utc=snapshot_utc,
            facts=[f for f in facts if isinstance(f, dict)],
            settings=settings, client=client, ncbi_api_key=ncbi_key,
        )
    audit_json = json.dumps(report.as_dict(), indent=2, ensure_ascii=False)
    audit_md = _render_md(report)
    (run_dir / "source_audit.json").write_text(audit_json, encoding="utf-8")
    (run_dir / "source_audit.md").write_text(audit_md, encoding="utf-8")
    if not args.no_update_manifest:
        _update_manifest(run_dir, audit_md, audit_json)
    print(f"[source-audit] {run_dir.name}: "
          f"survives={report.survives} dies={report.dies} "
          f"needs_extraction={report.needs_extraction}")
    for v in report.verdicts:
        print(f"  [{v.verdict:18}]  {v.fact_id}  ({v.db_value})  "
              f"{v.reason[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
