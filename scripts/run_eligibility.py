"""Sprint 7 orchestrator: full-text parse -> triage -> judge -> merge.

Runs the eligibility-adjudication ladder for one topic and writes
`eligibility_receipts.json` + `eligibility_summary.json` to a fresh run
directory.

Usage:
    .venv/bin/python scripts/run_eligibility.py --topic rapamycin
    .venv/bin/python scripts/run_eligibility.py --topic rapamycin --dry-run

`--dry-run` skips the LLM judge call (no OpenRouter spend); receipts are
written with decision='unclear' and reason='dry-run' so the ladder can
be exercised offline.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.eligibility_judge import EligibilityProposal, judge_eligibility
from agent.eligibility_merge import adjudicate
from agent.eligibility_rules import triage
from agent.full_text_fetch import fetch_full_text_receipts
from agent.full_text_parse import parse_full_texts
from agent.retrieval.unified import search_all
from agent.screening import CandidateStudy, EligibilityReceipt
from agent.screening_rules import build_candidate_studies, screen_hits
from agent.settings import load_settings
from agent.topic_pack import TopicPack, load_topic_pack


def _query(pack: TopicPack) -> str:
    pref = " ".join(pack.preferred_terms[:1]) if pack.preferred_terms else ""
    primary = (
        " ".join(pack.primary_interventions[:1])
        if pack.primary_interventions else pack.topic
    )
    return " ".join(t for t in (primary, pack.endpoint, pref) if t)


def _dry_proposal(study_id: str) -> EligibilityProposal:
    return EligibilityProposal(
        study_id=study_id, decision="unclear", confidence=0.0,
        reasons=("dry-run; LLM judge skipped",), evidence_quotes=(),
        eligibility_fields=MappingProxyType({}), model="(dry-run)",
        raw_response="", parse_error="dry-run",
    )


def _receipt_dict(r: EligibilityReceipt) -> dict[str, object]:
    return {
        "study_id": r.study_id,
        "decision": r.decision,
        "reason": r.reason,
        "reviewer": r.reviewer,
        "confidence": r.confidence,
        "mandatory_fields": dict(r.mandatory_fields),
        "evidence_quotes": list(r.evidence_quotes),
        "judge_model": r.judge_model,
        "rule_decision": r.rule_decision,
        "source_text_hash": r.source_text_hash,
        "timestamp_utc": r.timestamp_utc,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument("--iter", type=int, default=1)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip LLM judge call (no OpenRouter spend)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Optional cap on number of candidates to adjudicate (0 = no cap)",
    )
    args = parser.parse_args()

    settings = load_settings()
    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack for {args.topic!r}", file=sys.stderr)
        return 2

    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_id = f"{args.topic}-s7-iter-{args.iter:02d}-{ts}"
    out_dir = Path(settings.runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    q = _query(pack)
    print(f"[s7] topic={args.topic} query={q!r}")

    hits = await search_all(q, settings=settings, pack=pack)
    receipts = screen_hits(tuple(hits), pack)
    candidates = build_candidate_studies(tuple(hits), receipts)
    print(f"[s7] {len(hits)} hits -> {len(candidates)} TA candidates")

    if args.limit and args.limit < len(candidates):
        candidates = candidates[: args.limit]
        print(f"[s7] limited to first {len(candidates)} for adjudication")

    ft_receipts = await fetch_full_text_receipts(candidates, settings=settings)
    print(
        f"[s7] OA availability: "
        f"{sum(1 for r in ft_receipts if r.retrieved)}/{len(ft_receipts)}"
    )

    by_id: dict[str, CandidateStudy] = {c.study_id: c for c in candidates}

    parsed = await parse_full_texts(ft_receipts, settings=settings)
    print(f"[s7] parsed {sum(1 for p in parsed if p.text)}/{len(parsed)} full texts")

    eligibility_receipts: list[EligibilityReceipt] = []
    label_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    for ft_r, parsed_doc in zip(ft_receipts, parsed, strict=True):
        candidate = by_id[ft_r.study_id]
        tri = triage(candidate, parsed_doc, pack)
        label_counts[tri.label] += 1
        proposal = (
            _dry_proposal(candidate.study_id) if args.dry_run
            else judge_eligibility(candidate, parsed_doc, tri, pack, settings)
        )
        receipt = adjudicate(tri, proposal, parsed_doc)
        decision_counts[receipt.decision] += 1
        eligibility_receipts.append(receipt)

    (out_dir / "eligibility_receipts.json").write_text(
        json.dumps([_receipt_dict(r) for r in eligibility_receipts], indent=2),
        encoding="utf-8",
    )
    summary = {
        "topic": args.topic,
        "iter": args.iter,
        "timestamp_utc": ts,
        "k_hits": len(hits),
        "k_candidates": len(candidates),
        "k_full_text_located": sum(1 for r in ft_receipts if r.retrieved),
        "k_parsed_with_text": sum(1 for p in parsed if p.text),
        "triage_labels": dict(label_counts),
        "final_decisions": dict(decision_counts),
        "dry_run": args.dry_run,
        "judge_model": (
            settings.eligibility_judge_model or settings.judge_model
            if not args.dry_run else "(dry-run)"
        ),
    }
    (out_dir / "eligibility_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8",
    )

    print(f"[s7] triage labels: {dict(label_counts)}")
    print(f"[s7] final decisions: {dict(decision_counts)}")
    print(f"[s7] saved -> {out_dir}/eligibility_receipts.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
