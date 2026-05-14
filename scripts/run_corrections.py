"""Sprint 57 — CLI for the correction-proposal generator.

Reads runs/<topic>-evidence-<ts>/{source_audit.json, all_facts.json},
fetches each dies-verdict fact's source text (re-uses source_audit's
cache logic), emits corrections_proposed.json + corrections.md into
the same run folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.correction_proposer import (
    CorrectionProposal,
    propose_corrections_for_run,
)
from agent.source_audit import FactVerdict, fetch_pubmed_abstract
from agent.source_corpus import fetch_pmc_fulltext


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verdicts_from_json(data: list[dict[str, Any]]) -> list[FactVerdict]:
    out: list[FactVerdict] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        out.append(FactVerdict(
            fact_id=str(d.get("fact_id") or ""),
            verdict=str(d.get("verdict") or ""),
            db_value=str(d.get("db_value") or ""),
            pmid=str(d.get("pmid") or ""),
            source_quote=str(d.get("source_quote") or ""),
            reason=str(d.get("reason") or ""),
            judge=str(d.get("judge") or "gemma"),
            source_tier=str(d.get("source_tier") or "abstract"),
            anchor_hits=int(d.get("anchor_hits") or 0),
        ))
    return out


def _render_md(
    topic: str, snapshot: str, proposals: list[CorrectionProposal],
) -> str:
    head = (
        f"# Correction proposals — {topic}\n\n"
        f"**Snapshot:** {snapshot}\n"
        f"**Proposals:** {len(proposals)}\n\n"
        "Each proposal is built from a `dies` verdict in source_audit.json.\n"
        "It pairs the DB-stored value with the strongest source-text\n"
        "anchor that matches the DB's claimed subgroup. Ready for\n"
        "ingestion as canonical correction patches by the Researka DB\n"
        "team.\n\n---\n\n"
    )
    if not proposals:
        return head + "_No correction proposals (no dies verdicts with\n" \
                      "extractable alternatives)._\n"
    blocks: list[str] = []
    for p in proposals:
        blocks.append(
            f"## {p.fact_id}\n\n"
            f"- **Current (DB):** `{p.current_value}` for population "
            f"_{p.current_population}_\n"
            f"- **Proposed (source):** `{p.proposed_value}`\n"
            f"- **Confidence:** {p.confidence}\n"
            f"- **Evidence quote:** {p.evidence_quote}\n"
            f"- **Source span:** {p.proposed_population}\n"
            f"- **Rationale:** {p.rationale}\n",
        )
    return head + "\n---\n\n".join(blocks) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run_dir: Path = args.run
    audit_path = run_dir / "source_audit.json"
    facts_path = run_dir / "all_facts.json"
    manifest_path = run_dir / "MANIFEST.json"
    if not audit_path.exists() or not facts_path.exists():
        print(f"[corrections] need source_audit.json + all_facts.json under "
              f"{run_dir}", file=sys.stderr)
        return 1
    topic, snapshot_utc = "unknown", "unknown"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            topic = str(m.get("topic") or topic)
            snapshot_utc = str(m.get("snapshot_utc") or snapshot_utc)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        audit_raw = json.loads(audit_path.read_text(encoding="utf-8"))
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[corrections] could not read inputs: {e}", file=sys.stderr)
        return 1
    verdicts = _verdicts_from_json(
        audit_raw.get("verdicts", []) if isinstance(audit_raw, dict) else [],
    )
    if not isinstance(facts, list):
        print("[corrections] all_facts.json is not a list", file=sys.stderr)
        return 1
    ncbi_key = os.environ.get("NCBI_API_KEY", "")
    abstracts: dict[str, str] = {}
    fulltexts: dict[str, str] = {}
    dies_facts = {v.fact_id for v in verdicts if v.verdict == "dies"}
    with httpx.Client(timeout=30.0) as client:
        for f in facts:
            if not isinstance(f, dict):
                continue
            if str(f.get("fact_id") or "") not in dies_facts:
                continue
            paper = f.get("source_paper") or {}
            pmid = str(paper.get("pmid") or "")
            pmcid = str(paper.get("pmcid") or "")
            if pmid and pmid not in abstracts:
                abstracts[pmid] = fetch_pubmed_abstract(
                    pmid, client=client, ncbi_api_key=ncbi_key,
                )
            if pmcid and pmcid not in fulltexts:
                fulltexts[pmcid] = fetch_pmc_fulltext(
                    pmcid, client=client, ncbi_api_key=ncbi_key,
                )
    proposals = propose_corrections_for_run(
        verdicts, facts, abstracts=abstracts, fulltexts=fulltexts,
    )
    out_json = run_dir / "corrections_proposed.json"
    out_md = run_dir / "corrections.md"
    json_text = json.dumps(
        {"topic": topic, "snapshot_utc": snapshot_utc,
         "proposals": [p.as_dict() for p in proposals]},
        indent=2, ensure_ascii=False,
    )
    md_text = _render_md(topic, snapshot_utc, proposals)
    out_json.write_text(json_text, encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(m, dict):
                files = m.setdefault("files", {})
                if isinstance(files, dict):
                    files["corrections_json"] = {
                        "name": out_json.name, "sha256": _sha256(json_text),
                    }
                    files["corrections_md"] = {
                        "name": out_md.name, "sha256": _sha256(md_text),
                    }
                    manifest_path.write_text(
                        json.dumps(m, indent=2), encoding="utf-8",
                    )
        except (OSError, json.JSONDecodeError):
            pass
    print(f"[corrections] {run_dir.name}: proposals={len(proposals)}")
    for p in proposals:
        print(f"  {p.fact_id}  {p.current_value} -> {p.proposed_value}  "
              f"(conf={p.confidence})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
