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
import os
import sys
from collections import Counter
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.eligibility_judge import (
    EligibilityProposal,
    curated_proposal,
    judge_eligibility,
    judge_eligibility_with_variance,
)
from agent.eligibility_merge import adjudicate
from agent.eligibility_rules import triage
from agent.evidence_state import EvidenceState
from agent.full_text_fetch import fetch_full_text_receipts
from agent.full_text_parse import ParsedFullText, parse_full_texts
from agent.include_contract import demote_failed_includes
from agent.manual_resolution import build_manual_status_overlay, load_manual_resolutions
from agent.results_compiler import compile_all
from agent.results_contract import validate_results_text
from agent.results_writer import write_results_section
from agent.retrieval.unified import search_all
from agent.screening import CandidateStudy, EligibilityReceipt, ParsedFullTextReceipt
from agent.screening_rules import build_candidate_studies, screen_hits
from agent.settings import load_settings
from agent.topic_pack import TopicPack, load_topic_pack

# Concurrency for the parallel judge loop. 5 keeps under OpenRouter's
# per-second cap while still cutting wall-clock ~5x.
JUDGE_CONCURRENCY = int(os.environ.get("JUDGE_CONCURRENCY", "5"))


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
    parser.add_argument(
        "--variance-check", action="store_true",
        help="Run the Gemma judge twice with different prompt phrasings; "
             "downgrade to 'unclear' on disagreement. Doubles LLM cost.",
    )
    args = parser.parse_args()
    judge_fn = (
        judge_eligibility_with_variance if args.variance_check
        else judge_eligibility
    )

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

    # Persist the study_id -> {title, year, venue, doi, pmid} map so the
    # downstream Corpus QA tool can audit sentinels without re-running search.
    (out_dir / "candidates.json").write_text(
        json.dumps(
            [
                {"study_id": c.study_id, "hit_key": c.hit_key, "title": c.title,
                 "year": c.year, "venue": c.venue, "doi": c.doi, "pmid": c.pmid}
                for c in candidates
            ], indent=2,
        ),
        encoding="utf-8",
    )

    ft_receipts = await fetch_full_text_receipts(candidates, settings=settings)
    print(
        f"[s7] OA availability: "
        f"{sum(1 for r in ft_receipts if r.retrieved)}/{len(ft_receipts)}"
    )

    by_id: dict[str, CandidateStudy] = {c.study_id: c for c in candidates}

    # Only parse the OA-located subset; the validator forbids parsed receipts
    # for candidates without a FullTextReceipt(retrieved=True). And only the
    # parsed-OK subset gets an eligibility decision - "decision pending" is
    # the honest state for everything else, recorded as missing receipts.
    located_receipts = tuple(r for r in ft_receipts if r.retrieved)
    parsed_docs = await parse_full_texts(located_receipts, settings=settings)

    # Sprint 9 corpus recovery: apply manual full-text overrides for any
    # candidate the operator has supplied bytes for under
    # `topic_packs/manual_full_text/<topic>/`. The hook is keyed by DOI
    # or PMID and recovers sentinel papers the auto pipeline cannot
    # reach (Nature paywall / OUP auth / abstract-only PMC strip).
    from agent.full_text_parse import (
        apply_manual_overrides,
        load_manual_full_text_overrides,
    )
    cand_doi_pmid: dict[str, tuple[str, str]] = {
        c.study_id: (c.doi or "", c.pmid or "") for c in candidates
    }
    overrides = load_manual_full_text_overrides(args.topic, cand_doi_pmid)
    if overrides:
        import hashlib as _hashlib
        parsed_docs = apply_manual_overrides(parsed_docs, overrides)
        print(f"[s7] applied {len(overrides)} manual full-text override(s): "
              f"{sorted(overrides)}")
        # ManualFullTextReceipt audit: this is source recovery, not
        # eligibility override. Record what bytes were injected, by
        # whom, when, with a SHA-256 so reviewers can verify the
        # operator-supplied text matches what the pipeline consumed.
        cand_by_id = {c.study_id: c for c in candidates}
        (out_dir / "manual_full_text_audit.json").write_text(
            json.dumps([
                {
                    "study_id": sid, "topic": args.topic,
                    "doi": (cand_by_id[sid].doi if sid in cand_by_id else None),
                    "pmid": (cand_by_id[sid].pmid if sid in cand_by_id else None),
                    "source_name": "manual_full_text",
                    "source_path": (
                        f"topic_packs/manual_full_text/{args.topic}/"
                        f"{(cand_by_id[sid].doi or '').casefold().replace('/', '-')}.txt"
                        if sid in cand_by_id and cand_by_id[sid].doi
                        else f"topic_packs/manual_full_text/{args.topic}/"
                             f"{cand_by_id[sid].pmid}.txt"
                        if sid in cand_by_id else ""
                    ),
                    "file_hash_sha256": _hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "byte_count": len(text.encode("utf-8")),
                    "retrieved_by": "human-operator",
                    "timestamp_utc": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
                    "reason": (
                        "auto retrieval (PMC/Unpaywall) failed or returned "
                        "junk for this sentinel; verbatim full-text supplied "
                        "by operator under manual_full_text/."
                    ),
                }
                for sid, text in overrides.items()
            ], indent=2),
            encoding="utf-8",
        )

    parsed_receipts: tuple[ParsedFullTextReceipt, ...] = tuple(d.to_receipt() for d in parsed_docs)
    parsed_by_id: dict[str, ParsedFullText] = {d.study_id: d for d in parsed_docs}
    print(f"[s7] parsed {sum(1 for r in parsed_receipts if r.parsed)}/{len(parsed_receipts)} full texts")

    # Sprint 7.11.2c / Sprint 8 prep: persist the parsed text bodies so
    # downstream extraction can read the exact bytes the judge saw
    # without re-fetching from NCBI/Unpaywall. text_hash in
    # parsed_receipts.json continues to provide tamper detection.
    parsed_text_dir = out_dir / "parsed_text"
    parsed_text_dir.mkdir(exist_ok=True)
    for d in parsed_docs:
        if d.text:
            (parsed_text_dir / f"{d.study_id}.txt").write_text(d.text, encoding="utf-8")

    # Parallel judge loop: asyncio.to_thread wraps the sync HTTP call so
    # up to JUDGE_CONCURRENCY runs go through OpenRouter concurrently.
    # Each receipt appends to eligibility_receipts.partial.jsonl under a
    # lock; a kill mid-loop preserves all completed work.
    checkpoint_path = out_dir / "eligibility_receipts.partial.jsonl"
    label_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    skipped_parse_failed = sum(
        1 for ft_r in located_receipts
        if not parsed_by_id[ft_r.study_id].text.strip()
    )
    parsed_subset = tuple(
        ft_r for ft_r in located_receipts
        if parsed_by_id[ft_r.study_id].text.strip()
    )
    print(f"[s7] judge loop: {len(parsed_subset)} parsed candidates, concurrency={JUDGE_CONCURRENCY}")
    sem = asyncio.Semaphore(JUDGE_CONCURRENCY)
    write_lock = asyncio.Lock()
    progress = {"done": 0}

    async def adjudicate_one(ft_r: object) -> EligibilityReceipt:
        candidate = by_id[ft_r.study_id]  # type: ignore[attr-defined]
        parsed_doc = parsed_by_id[ft_r.study_id]  # type: ignore[attr-defined]
        tri = triage(candidate, parsed_doc, pack)
        # Sprint 12.9 Researka-as-spine: short-circuit the LLM judge for
        # candidates retrieved via a curated index source (researka:*).
        # The Pass-1 rule triage + post-merge universal evidence contract
        # still gate final include; we only skip the costly OpenRouter
        # call. Set RESEARKA_SPINE_TRUST=false to revert to LLM-judging
        # every Researka hit.
        is_curated = (
            settings.researka_spine_trust
            and candidate.source.startswith("researka:")
        )
        async with sem:
            if args.dry_run:
                proposal = _dry_proposal(candidate.study_id)
            elif is_curated:
                proposal = curated_proposal(candidate, parsed_doc, tri, pack)
            else:
                proposal = await asyncio.to_thread(
                    judge_fn, candidate, parsed_doc, tri, pack, settings,
                )
        receipt = adjudicate(tri, proposal, parsed_doc)
        async with write_lock:
            label_counts[tri.label] += 1
            decision_counts[receipt.decision] += 1
            with checkpoint_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_receipt_dict(receipt)) + "\n")
                fh.flush()
            progress["done"] += 1
            if progress["done"] % 10 == 0:
                print(
                    f"[s7]   ... {progress['done']}/{len(parsed_subset)} done; "
                    f"decisions: {dict(decision_counts)}",
                    flush=True,
                )
        return receipt

    eligibility_receipts = list(
        await asyncio.gather(*(adjudicate_one(ft_r) for ft_r in parsed_subset))
    )
    if skipped_parse_failed:
        print(
            f"[s7] skipped {skipped_parse_failed} candidates with parse failures "
            f"(no eligibility decision possible)"
        )

    # Sprint 7.8 - include contract: post-merge "supreme court" that
    # demotes any include with insufficient parse, missing evidence, or
    # only-title quotes back to unclear. Fixes the iter-15 s237 bug where
    # a 54-char parse passed the merge because parsed_text_adequate is
    # not in MANDATORY_KEYS.
    titles_by_id = {c.study_id: c.title for c in candidates}
    parsed_by_receipt = {r.study_id: r for r in parsed_receipts}
    contracted_receipts, contract_results = demote_failed_includes(
        tuple(eligibility_receipts), parsed_by_receipt, titles_by_id, pack,
    )
    eligibility_receipts = list(contracted_receipts)
    demoted = sum(1 for v in contract_results.values() if v.violations)
    if demoted:
        print(f"[s7] include contract demoted {demoted} include(s) to unclear")

    # Sprint 7.11.1 - manual sentinel-status overlay. Loaded from
    # topic_packs/<topic>_manual_resolutions.toml. Manuals can only
    # resolve sentinel STATUS (resolved_available / resolved_unavailable
    # / resolved_excluded / needs_review). They do NOT mutate eligibility
    # receipts and cannot promote a paper into primary inclusion. The
    # universal evidence contract (already run above by demote_failed
    # _includes) is the sole gate of the primary-effect corpus.
    manual_resolutions = load_manual_resolutions(args.topic)
    manual_overlay = build_manual_status_overlay(manual_resolutions, candidates)
    if manual_resolutions:
        unmatched = len(manual_resolutions) - len(manual_overlay)
        print(
            f"[s7] manual status overlay: {len(manual_overlay)} matched, "
            f"{unmatched} declared-but-unmatched"
        )

    # Recount decisions after contract demotion. Manual overlay does not
    # change decision counts; it only resolves sentinel status downstream.
    decision_counts = Counter(r.decision for r in eligibility_receipts)

    # Sprint-7 strictness: assemble EvidenceState with parsed_receipts so the
    # eligibility validator can prove every include has a parsed=True receipt.
    state = EvidenceState.build(
        topic=args.topic,
        hits=tuple(hits),
        receipts=receipts,
        candidates=candidates,
        full_text_receipts=ft_receipts,
        parsed_receipts=parsed_receipts,
        eligibility_receipts=tuple(eligibility_receipts),
    )
    packets = compile_all(
        state, moderators=(), pack=pack, manual_overlay=manual_overlay,
    )
    results_text = write_results_section(packets)
    violations = validate_results_text(results_text, packets)

    (out_dir / "eligibility_receipts.json").write_text(
        json.dumps([_receipt_dict(r) for r in eligibility_receipts], indent=2),
        encoding="utf-8",
    )
    (out_dir / "parsed_receipts.json").write_text(
        json.dumps([
            {
                "study_id": r.study_id, "source_url": r.source_url,
                "parsed": r.parsed, "text_hash": r.text_hash,
                "char_count": r.char_count, "failure_reason": r.failure_reason,
            }
            for r in parsed_receipts
        ], indent=2),
        encoding="utf-8",
    )
    (out_dir / "main_draft.md").write_text(results_text, encoding="utf-8")
    if manual_overlay:
        (out_dir / "manual_status_overlay.json").write_text(
            json.dumps([
                {
                    "study_id": sid, "doi": r.doi, "pmid": r.pmid,
                    "status": r.status, "reason": r.reason,
                    "evidence_quote": r.evidence_quote, "reviewer": r.reviewer,
                    "action_required": r.action_required,
                }
                for sid, r in manual_overlay.items()
            ], indent=2),
            encoding="utf-8",
        )
    summary = {
        "topic": args.topic,
        "iter": args.iter,
        "timestamp_utc": ts,
        "k_hits": len(hits),
        "k_candidates": len(candidates),
        "k_full_text_located": sum(1 for r in ft_receipts if r.retrieved),
        "k_parsed_with_text": sum(1 for r in parsed_receipts if r.parsed),
        "triage_labels": dict(label_counts),
        "final_decisions": dict(decision_counts),
        "k_eligible": state.k_eligible,
        "contract_violations": len(violations),
        "dry_run": args.dry_run,
        "judge_model": settings.judge_model if not args.dry_run else "(dry-run)",
    }
    (out_dir / "eligibility_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8",
    )

    print(f"[s7] triage labels: {dict(label_counts)}")
    print(f"[s7] final decisions: {dict(decision_counts)}")
    print(f"[s7] eligible studies after merge: {state.k_eligible}")
    print(f"[s7] contract violations: {len(violations)}")
    print(f"[s7] saved -> {out_dir}/eligibility_receipts.json")
    print(f"[s7] saved -> {out_dir}/main_draft.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
