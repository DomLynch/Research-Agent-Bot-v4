"""Sprint 7.11 - regenerate Section 3 from a frozen run dir.

Rebuilds `main_draft.md` against the POST-override state of an existing
run, so the prose reflects:
  - manual_resolutions.toml as it stands today (sentinel gate may have
    moved from WARN to PASS since the run was originally written)
  - the strict A-core split (3-bucket strict primary set)
  - the same PRISMA flow counts the run was frozen with

No retrieval, no LLM. Pure deterministic re-render of packets from
frozen JSON. Universal: topic-pack-driven; no biomedical literals here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.evidence_state import EvidenceState
from agent.include_contract import demote_failed_includes
from agent.manual_resolution import build_manual_status_overlay, load_manual_resolutions
from agent.results_compiler import InformationalPacket, compile_all
from agent.results_writer import write_results_section
from agent.retrieval.base import PaperHit
from agent.screening import (
    CandidateStudy,
    EligibilityReceipt,
    FullTextReceipt,
    ParsedFullTextReceipt,
    ScreeningReceipt,
)
from agent.topic_pack import load_topic_pack


def _candidate_from_dict(d: dict[str, Any]) -> CandidateStudy:
    return CandidateStudy(
        study_id=str(d["study_id"]),
        hit_key=str(d.get("hit_key", "")),
        title=str(d.get("title", "")),
        year=d.get("year"),
        venue=d.get("venue"),
        pmid=d.get("pmid"),
        doi=d.get("doi"),
    )


def _parsed_from_dict(d: dict[str, Any]) -> ParsedFullTextReceipt:
    return ParsedFullTextReceipt(
        study_id=str(d["study_id"]),
        source_url=str(d.get("source_url", "")),
        parsed=bool(d.get("parsed", False)),
        text_hash=str(d.get("text_hash", "")),
        char_count=int(d.get("char_count", 0)),
        failure_reason=str(d.get("failure_reason", "")),
    )


def _eligibility_from_dict(d: dict[str, Any]) -> EligibilityReceipt:
    mf = d.get("mandatory_fields") or {}
    return EligibilityReceipt(
        study_id=str(d["study_id"]),
        decision=d["decision"],
        reason=str(d.get("reason", "")),
        reviewer=str(d.get("reviewer", "")),
        confidence=float(d.get("confidence", 0.0)),
        mandatory_fields=MappingProxyType({k: bool(v) for k, v in mf.items()}),
        evidence_quotes=tuple(d.get("evidence_quotes", [])),
        judge_model=str(d.get("judge_model", "")),
        rule_decision=str(d.get("rule_decision", "")),
        source_text_hash=str(d.get("source_text_hash", "")),
        timestamp_utc=str(d.get("timestamp_utc", "")),
    )


def _hit_stub(c: CandidateStudy) -> PaperHit:
    """Reconstruct a minimal PaperHit so sentinel recall + study selection
    counts work. The candidate already carries the identifiers we need
    (doi/pmid) plus title/year/venue; retrieval source is opaque here."""
    return PaperHit(
        source="reconstructed", title=c.title, abstract="",
        year=c.year, url="",
        doi=c.doi, pmid=c.pmid, venue=c.venue,
    )


def _render_primary_pool_block(strict: dict[str, Any]) -> str:
    """Render the 3-bucket strict primary-pool composition as Markdown."""
    bc = strict.get("bucket_counts", {})
    a = bc.get("A_core_direct_lifespan", 0)
    b = bc.get("B_disease_model_survival", 0)
    c = bc.get("C_secondary_contextual", 0)
    demoted_a = sum(
        1 for s in strict.get("C_secondary_contextual", [])
        if s.get("demoted_from") == "A_direct_lifespan"
    )
    lines = [
        "### Primary Pool Composition",
        "",
        (
            f"After applying the strict A-core evidence-quote audit, "
            f"{a} studies form the primary direct-lifespan corpus, "
            f"{b} studies populate the disease-model survival sensitivity "
            f"lane, and {c} studies are retained as secondary/contextual "
            f"(of which {demoted_a} were demoted from the auto-judge "
            f"direct-lifespan lane because their evidence quotes failed "
            f"the per-quote mouse/intervention/control/endpoint audit) "
            f"[PACKET:primary_pool_composition]."
        ),
        "",
    ]
    a_ids = [s["study_id"] for s in strict.get("A_core_direct_lifespan", [])]
    if a_ids:
        lines.append(
            "Strict A-core study IDs: " + ", ".join(sorted(a_ids))
            + " [PACKET:primary_pool_composition]."
        )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output path (defaults to <run_dir>/main_draft.md)",
    )
    args = parser.parse_args()

    rd: Path = args.run_dir
    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack {args.topic!r}", file=sys.stderr)
        return 2

    cands_raw = json.loads((rd / "candidates.json").read_text(encoding="utf-8"))
    parsed_raw = json.loads((rd / "parsed_receipts.json").read_text(encoding="utf-8"))
    elig_raw = json.loads((rd / "eligibility_receipts.json").read_text(encoding="utf-8"))
    strict = json.loads(
        (rd / "primary_effect_input_set_strict.json").read_text(encoding="utf-8")
    )

    candidates = tuple(_candidate_from_dict(c) for c in cands_raw)
    parsed_receipts = tuple(_parsed_from_dict(p) for p in parsed_raw)
    eligibility = tuple(_eligibility_from_dict(r) for r in elig_raw)

    # Sprint 7.11.1: re-apply the universal evidence contract to the
    # frozen receipts. Iter-17 was written with the old "manual override
    # bypasses contract" path, so Harrison/Bitto receipts ship with
    # decision=include despite carrying only 1 evidence quote. The new
    # contract rejects that and demotes them to unclear; without this
    # re-apply step the sentinel gate would falsely report PASS.
    parsed_by_id = {p.study_id: p for p in parsed_receipts}
    titles_by_id = {c.study_id: c.title for c in candidates}
    eligibility, contract_results = demote_failed_includes(
        eligibility, parsed_by_id, titles_by_id, pack,
    )
    demoted = sum(1 for v in contract_results.values() if v.violations)
    if demoted:
        print(f"[regen] universal contract demoted {demoted} include(s) to unclear")

    # Manual_resolutions are a status-only overlay. They do NOT mutate
    # eligibility receipts and cannot promote a paper into primary
    # inclusion; that is the universal contract's job. The overlay
    # informs the sentinel-recall packet so the prose can say
    # "WARN: sentinel located but retrieval/parser failed" instead of
    # silently treating manual entries as auto-includes.
    resolutions = load_manual_resolutions(args.topic)
    manual_overlay = build_manual_status_overlay(resolutions, candidates)
    if manual_overlay:
        print(f"[regen] loaded {len(manual_overlay)} manual status overlay records")

    # Stub hits + TA screening receipts + full-text receipts to satisfy
    # EvidenceState chain validation. Each candidate by definition has an
    # include TA receipt; full-text receipts mirror parsed receipts where
    # parsed=True implies retrieval succeeded.
    hits = tuple(_hit_stub(c) for c in candidates)
    receipts = tuple(
        ScreeningReceipt(
            hit_key=c.hit_key, decision="include",
            stage="title-abstract", reason="reconstructed",
        )
        for c in candidates
    )
    # Every parsed receipt implies retrieval succeeded (bytes were located
    # before being handed to the parser), even when the parse itself
    # failed. Keep retrieved=True so validate_parsed_receipts accepts the
    # chain. Manual-override receipts without a parsed receipt are
    # allowed by validate_eligibility_receipts as of Sprint 7.10b — the
    # human is the evidence — so we do not fabricate parsed stubs here.
    full_text = tuple(
        FullTextReceipt(
            study_id=p.study_id, retrieved=True,
            source="reconstructed", reason="",
        )
        for p in parsed_receipts
    )

    state = EvidenceState.build(
        topic=args.topic,
        hits=hits,
        receipts=receipts,
        candidates=candidates,
        full_text_receipts=full_text,
        parsed_receipts=parsed_receipts,
        eligibility_receipts=eligibility,
    )

    packets = compile_all(state, pack=pack, manual_overlay=manual_overlay)

    # Replace study_selection counts with frozen-run summary values where
    # the reconstruction can't fully recover the real retrieval-stage
    # counts (k_hits=502 vs. reconstructed=298, full_text_located=257 vs.
    # reconstructed from parsed receipts).
    summary_path = rd / "eligibility_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for i, p in enumerate(packets):
            if isinstance(p, InformationalPacket) and p.packet_id == "study_selection":
                c = dict(p.counts)
                c["identified"] = int(summary.get("k_hits", c.get("identified", 0)))
                c["screened_title_abstract"] = c["identified"]
                c["candidates_after_title_abstract"] = int(
                    summary.get("k_candidates", c.get("candidates_after_title_abstract", 0))
                )
                c["full_text_availability_located"] = int(
                    summary.get("k_full_text_located", c.get("full_text_availability_located", 0))
                )
                c["full_text_parsed"] = int(
                    summary.get("k_parsed_with_text", c.get("full_text_parsed", 0))
                )
                packets[i] = InformationalPacket(
                    packet_id=p.packet_id,
                    description=p.description,
                    counts=MappingProxyType(c),
                    notes=p.notes,
                    source_study_ids=p.source_study_ids,
                )
                break

    body = write_results_section(packets)
    body = body.rstrip() + "\n\n" + _render_primary_pool_block(strict)

    out = args.out or (rd / "main_draft.md")
    out.write_text(body, encoding="utf-8")
    timestamp = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    print(
        f"[regen] {state.k_eligibility_included} include / "
        f"{state.k_eligibility_unclear} unclear / "
        f"{state.k_eligibility_excluded} exclude"
    )
    print(f"[regen] wrote {out} at {timestamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
