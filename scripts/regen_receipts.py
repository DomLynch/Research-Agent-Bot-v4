"""Regenerate Sprint 16/17/23/24 sidecar receipts from a paper folder.

Reads whatever canonical receipts the folder already has
(eligibility_summary / primary_effect_input_set_strict /
effect_extractions / effect_pool) and produces:

  readiness_report.json       (Sprint 16)
  paper_type_decision.json    (Sprint 23)
  research_object.json        (Sprint 24 — typed bundle)

cite_audit.json is NOT regenerated here because it requires the
resolved paper.md body (which already exists on disk for stitched
papers but re-running resolve_citations needs the topic pack). For
forward stitches, stitch_paper.py already emits all of these.

Universal: no topic-specific logic; the regenerator reads receipt
shapes only.

Usage:
    python scripts/regen_receipts.py runs/rapamycin-paper-...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.maturity_router import select_paper_type
from agent.readiness import classify_readiness
from agent.reference_resolver import ResolvedReferences, audit_citations
from agent.research_object import bundle_research_object
from agent.topic_pack import load_topic_pack


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _regen_cite_audit(paper_dir: Path, topic: str) -> bool | None:
    """Recover a structural cite_audit.json for a paper folder stitched
    before Sprint 17 existed. Parses paper.md by splitting at the
    `## References` heading and runs audit_citations against the
    topic-pack bibliography. Returns clean=True/False, or None when
    paper.md or the topic pack is missing."""
    paper_md = paper_dir / "paper.md"
    if not paper_md.exists() or not topic:
        return None
    pack = load_topic_pack(topic)
    if pack is None:
        return None
    body = paper_md.read_text(encoding="utf-8")
    refs_idx = body.find("## References")
    if refs_idx < 0:
        return None
    pre_refs, refs_section = body[:refs_idx], body[refs_idx:]
    # citations_used can't be recovered post-stitch (anchor keys are
    # gone — only [N] remain), so dead-anchor reporting will list
    # everything; that's expected for retroactive regen. The in-text-
    # vs-reference-number cross-check is fully accurate.
    fake = ResolvedReferences(
        body=pre_refs, references_section=refs_section,
        citations_used=(), unresolved=(),
    )
    audit = audit_citations(fake, pack)
    # Drop dead_bibliography_anchors from clean signal because they're
    # always non-empty in retroactive regen (citations_used is unknown).
    structurally_clean = (
        not audit.in_text_without_entry
        and not audit.entry_without_in_text
        and not audit.unresolved_anchors
    )
    payload = audit.as_dict()
    payload["clean"] = structurally_clean
    payload["_regenerated"] = "retroactive structural audit only — citations_used unknown"
    (paper_dir / "cite_audit.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )
    return structurally_clean


def regen(paper_dir: Path, *, topic: str = "") -> dict[str, str]:
    """Materialise the four sidecar receipts in `paper_dir`. Returns a
    dict mapping receipt-name → produced level/label for stdout."""
    summary = _read_json(paper_dir / "eligibility_summary.json")
    strict = _read_json(paper_dir / "primary_effect_input_set_strict.json")
    extr = _read_json(paper_dir / "effect_extractions.json")
    pool = _read_json(paper_dir / "effect_pool.json")

    readiness = classify_readiness(
        summary=summary, strict=strict, extractions=extr, pool=pool,
    )
    (paper_dir / "readiness_report.json").write_text(
        json.dumps(readiness.as_dict(), indent=2), encoding="utf-8",
    )
    paper_type = select_paper_type(readiness)
    (paper_dir / "paper_type_decision.json").write_text(
        json.dumps(paper_type.as_dict(), indent=2), encoding="utf-8",
    )
    # cite_audit is produced FIRST so the research_object reader sees
    # the freshly-written file when it reads cite_audit.json.
    cite_clean = _regen_cite_audit(paper_dir, topic)
    research_object = bundle_research_object(paper_dir, topic=topic)
    (paper_dir / "research_object.json").write_text(
        json.dumps(research_object.as_dict(), indent=2), encoding="utf-8",
    )
    return {
        "readiness": f"L{readiness.level} {readiness.label}",
        "paper_type": paper_type.name,
        "cite_audit_clean": str(cite_clean),
        "research_object_studies": str(len(research_object.studies)),
        "research_object_claims": str(len(research_object.claims)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_dir", type=Path)
    parser.add_argument(
        "--topic", default="",
        help="Override topic name (else inferred from receipts).",
    )
    args = parser.parse_args()
    if not args.paper_dir.is_dir():
        print(f"ERROR: not a directory: {args.paper_dir}", file=sys.stderr)
        return 2
    summary = regen(args.paper_dir, topic=args.topic)
    print(f"[regen] wrote receipts → {args.paper_dir}")
    for k, v in summary.items():
        print(f"  - {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
