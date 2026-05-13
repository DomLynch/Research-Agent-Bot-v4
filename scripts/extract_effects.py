"""Sprint 8 - effect-size extraction CLI.

Reads `primary_effect_input_set_strict.json` from a frozen run directory,
loads the persisted parsed text for each strict A-core record, calls the
writer LLM with a topic-pack-driven extraction prompt, and saves:

  effect_extractions.json   one ExtractionReceipt per strict A-core paper
  effect_extractions.partial.jsonl
                            per-paper checkpoint; the run is resumable
                            on a kill mid-loop.

Universal: no biomedical literals; metric vocabulary comes from the topic
pack. The strict_a_core file is the canonical input — legacy
primary_effect_input_set.json is never consulted.

Usage:
    python scripts/extract_effects.py runs/latest --topic rapamycin
    python scripts/extract_effects.py runs/latest --topic rapamycin --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.effect_extraction import (
    ExtractionReceipt,
    build_adjudicator_prompt,
    build_extraction_prompt,
    build_extraction_prompt_strict_verify,
    compare_receipts,
    merge_agreed_receipts,
    parse_extraction_response,
    receipt_from_response,
    validate_extraction,
)
from agent.effect_pooling import compile_pool
from agent.llm_client import call_writer
from agent.settings import load_settings
from agent.topic_pack import load_topic_pack


def _now_utc() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _receipt_to_dict(r: ExtractionReceipt) -> dict[str, Any]:
    return {
        "study_id": r.study_id, "status": r.status, "metric": r.metric,
        "treated_value": r.treated_value, "control_value": r.control_value,
        "treated_n": r.treated_n, "control_n": r.control_n,
        "hazard_ratio": r.hazard_ratio,
        "hazard_ratio_ci_low": r.hazard_ratio_ci_low,
        "hazard_ratio_ci_high": r.hazard_ratio_ci_high,
        "percent_change": r.percent_change,
        "moderators": dict(r.moderators),
        "evidence_quotes": list(r.evidence_quotes),
        "failure_reason": r.failure_reason, "reviewer": r.reviewer,
        "text_hash": r.text_hash, "timestamp_utc": r.timestamp_utc,
    }


def _placeholder_receipt(study_id: str, reason: str) -> ExtractionReceipt:
    return ExtractionReceipt(
        study_id=study_id, status="parse_failed", metric="",
        treated_value=None, control_value=None,
        treated_n=None, control_n=None,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=None,
        moderators=MappingProxyType({}),
        evidence_quotes=(), failure_reason=reason,
        reviewer="extract-cli", text_hash="", timestamp_utc=_now_utc(),
    )


def _dry_run_receipt(study_id: str) -> ExtractionReceipt:
    return ExtractionReceipt(
        study_id=study_id, status="no_numerics", metric="",
        treated_value=None, control_value=None,
        treated_n=None, control_n=None,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=None,
        moderators=MappingProxyType({}),
        evidence_quotes=(), failure_reason="dry-run; LLM call skipped",
        reviewer="dry-run", text_hash="", timestamp_utc=_now_utc(),
    )


def _run_dual_pass(
    *, primary: ExtractionReceipt, pack: Any, study_id: str, title: str,
    parsed_text: str, settings: Any, text_hash: str, temperature: float,
) -> ExtractionReceipt:
    """Sprint 12.9 Task C orchestrator: run strict-verify Pass-B + adjudicate.

    Inputs:
      `primary`  — the Pass-A receipt (status='extracted').
      Returns the dual-pass result with reviewer field tagged
      'mimo-dual-pass-agreed' / 'mimo-dual-pass-adjudicated' / 'mimo-dual-pass-pass-b-failed'
      depending on the outcome.

    Bounded: at most two extra LLM calls (Pass-B + adjudicator). On any
    Pass-B failure the function returns the primary receipt unchanged
    (with the reviewer noting the dual-pass attempt) — never sinks the
    extraction step.
    """
    # Pass-B: strict-verify variant of the same extraction prompt.
    try:
        b_msg = build_extraction_prompt_strict_verify(
            pack, study_id, title, parsed_text,
        )
        b_resp = call_writer(settings, b_msg, temperature=temperature)
        b_parsed = parse_extraction_response(b_resp.content)
        pass_b = receipt_from_response(
            b_parsed, study_id=study_id, text_hash=text_hash,
            reviewer=f"mimo-strict:{b_resp.model}", timestamp_utc=_now_utc(),
        )
    except (ValueError, OSError, RuntimeError):
        return _retag(primary, reviewer="mimo-dual-pass-pass-b-failed")
    disagreements = compare_receipts(primary, pass_b)
    if not disagreements:
        return merge_agreed_receipts(
            primary, pass_b, reviewer="mimo-dual-pass-agreed",
        )
    # Adjudicator call. Bounded to ONE attempt: if the adjudicator
    # itself fails to return parseable JSON, we keep Pass-A as the
    # default (it ran first and feeds the existing pool path).
    try:
        adj_msg = build_adjudicator_prompt(
            primary, pass_b, disagreements, parsed_text,
        )
        adj_resp = call_writer(settings, adj_msg, temperature=temperature)
        adj_parsed = parse_extraction_response(adj_resp.content)
        return receipt_from_response(
            adj_parsed, study_id=study_id, text_hash=text_hash,
            reviewer=(
                f"mimo-dual-pass-adjudicated:{adj_resp.model};"
                f"disagreements={','.join(disagreements)}"
            ),
            timestamp_utc=_now_utc(),
        )
    except (ValueError, OSError, RuntimeError):
        return _retag(
            primary, reviewer=(
                f"mimo-dual-pass-adjudicator-failed;"
                f"disagreements={','.join(disagreements)}"
            ),
        )


def _retag(receipt: ExtractionReceipt, *, reviewer: str) -> ExtractionReceipt:
    """Return a copy of `receipt` with a new `reviewer` provenance
    string. Used to record dual-pass attempts on the primary receipt
    when Pass-B / adjudicator paths failed."""
    return ExtractionReceipt(
        study_id=receipt.study_id, status=receipt.status,
        metric=receipt.metric,
        treated_value=receipt.treated_value, control_value=receipt.control_value,
        treated_n=receipt.treated_n, control_n=receipt.control_n,
        hazard_ratio=receipt.hazard_ratio,
        hazard_ratio_ci_low=receipt.hazard_ratio_ci_low,
        hazard_ratio_ci_high=receipt.hazard_ratio_ci_high,
        percent_change=receipt.percent_change,
        moderators=receipt.moderators,
        evidence_quotes=receipt.evidence_quotes,
        failure_reason=receipt.failure_reason,
        reviewer=reviewer,
        text_hash=receipt.text_hash, timestamp_utc=receipt.timestamp_utc,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="skip LLM call; emit placeholder no_numerics receipts so the "
             "pipeline can be exercised end-to-end without spend",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="writer LLM sampling temperature (0 = greedy; numeric tasks)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="only run extraction on the first N A-core records (0 = all)",
    )
    args = parser.parse_args()

    rd: Path = args.run_dir
    strict_path = rd / "primary_effect_input_set_strict.json"
    if not strict_path.exists():
        print(
            f"ERROR: {strict_path} missing — run freeze_primary_set.py first",
            file=sys.stderr,
        )
        return 2
    strict = json.loads(strict_path.read_text(encoding="utf-8"))
    if not strict.get("canonical_for_sprint_8", False):
        print(
            "ERROR: strict file is not flagged canonical_for_sprint_8; "
            "refresh via freeze_primary_set.py", file=sys.stderr,
        )
        return 3

    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack {args.topic!r}", file=sys.stderr)
        return 4

    a_core: list[dict[str, Any]] = list(strict.get("A_core_direct_lifespan", []))
    if args.limit > 0:
        a_core = a_core[: args.limit]
    if not a_core:
        print("[extract] no A-core records to process; exiting clean")
        return 0

    parsed_text_dir = rd / "parsed_text"
    parsed_receipts = {
        p["study_id"]: p for p in json.loads(
            (rd / "parsed_receipts.json").read_text(encoding="utf-8")
        )
    }

    checkpoint = rd / "effect_extractions.partial.jsonl"
    done_ids: set[str] = set()
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                done_ids.add(json.loads(line)["study_id"])
        print(f"[extract] resuming; {len(done_ids)} record(s) already processed")

    settings = None
    if not args.dry_run:
        settings = load_settings()
        if not settings.writer_configured:
            print(
                "ERROR: writer not configured (MIMO_API_KEY missing). "
                "Use --dry-run to scaffold without LLM.", file=sys.stderr,
            )
            return 5

    receipts: list[ExtractionReceipt] = []
    t0 = time.time()
    for entry in a_core:
        sid = entry["study_id"]
        if sid in done_ids:
            continue
        title = entry.get("title") or ""
        text_path = parsed_text_dir / f"{sid}.txt"
        parsed_text = _read_text(text_path)
        if not parsed_text:
            r = _placeholder_receipt(
                sid, f"no persisted parsed text at {text_path}; "
                f"re-run run_eligibility.py to repopulate parsed_text/",
            )
        elif args.dry_run:
            r = _dry_run_receipt(sid)
        else:
            assert settings is not None
            messages = build_extraction_prompt(pack, sid, title, parsed_text)
            # One transient retry at slightly higher temperature when the
            # first attempt fails to return parseable JSON (observed on
            # large excerpts where MIMO occasionally returns a non-JSON
            # refusal or empty content at temp=0). Determinism break costs
            # one extra call only when the first fails.
            r = _placeholder_receipt(sid, "extraction not yet attempted")
            for attempt, temp in ((1, args.temperature), (2, max(args.temperature, 0.2))):
                try:
                    resp = call_writer(settings, messages, temperature=temp)
                    parsed = parse_extraction_response(resp.content)
                    text_hash = parsed_receipts.get(sid, {}).get("text_hash", "")
                    r = receipt_from_response(
                        parsed, study_id=sid, text_hash=text_hash,
                        reviewer=f"mimo:{resp.model}", timestamp_utc=_now_utc(),
                    )
                    break
                except (ValueError, OSError, RuntimeError) as e:
                    if attempt == 2:
                        r = _placeholder_receipt(
                            sid, f"extraction error after 2 attempts: {e}",
                        )
            # Sprint 12.9 Task C: dual-pass extraction. After the primary
            # pass (above) lands an extracted receipt, run an independent
            # strict-verify pass and adjudicate any pool-critical
            # disagreement. Skip when Pass-A already failed (no benefit)
            # or when the operator opted out via EXTRACTION_DUAL_PASS=false.
            if (settings.extraction_dual_pass and r.status == "extracted"):
                r = _run_dual_pass(
                    primary=r, pack=pack, study_id=sid, title=title,
                    parsed_text=parsed_text, settings=settings,
                    text_hash=parsed_receipts.get(sid, {}).get("text_hash", ""),
                    temperature=args.temperature,
                )
        receipts.append(r)
        with checkpoint.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_receipt_to_dict(r)) + "\n")
            fh.flush()
        contract = validate_extraction(r, pack)
        flag = "PASS" if contract.passes else f"FAIL({len(contract.violations)})"
        print(f"[extract] {sid:>6}  status={r.status:<13} contract={flag}")

    # Merge with prior checkpoint receipts (resume case).
    all_receipts: list[dict[str, Any]] = []
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                all_receipts.append(json.loads(line))

    out_path = rd / "effect_extractions.json"
    receipts_rehydrated = tuple(
        receipt_from_response(
            r, study_id=r["study_id"],
            text_hash=r.get("text_hash", ""),
            reviewer=r.get("reviewer", ""),
            timestamp_utc=r.get("timestamp_utc", ""),
        )
        for r in all_receipts
    )
    k_contract_passing = sum(
        1 for r in receipts_rehydrated if validate_extraction(r, pack).passes
    )
    out_path.write_text(
        json.dumps({
            "_doc": (
                "Sprint 8 effect-extraction receipts. Each strict A-core "
                "record gets one receipt. Pooling reads only receipts that "
                "pass validate_extraction(); the rest are documented "
                "extraction failures."
            ),
            "topic": args.topic,
            "run_id": rd.name,
            "frozen_at_utc": _now_utc(),
            "k_records": len(all_receipts),
            "k_contract_passing": k_contract_passing,
            "receipts": all_receipts,
        }, indent=2),
        encoding="utf-8",
    )

    # Sprint 19: per-study extraction confidence + needs_human_audit
    # flag, derived from the dual-pass reviewer provenance. Sidecar
    # receipt so downstream human-audit + readiness layers can read it
    # without touching ExtractionReceipt shape.
    from agent.extraction_confidence import score_extractions
    confidence_report = score_extractions(receipts_rehydrated)
    (rd / "extraction_confidence.json").write_text(
        json.dumps(confidence_report.as_dict(), indent=2), encoding="utf-8",
    )
    print(
        f"[extract] confidence: k_total={confidence_report.k_total} "
        f"k_needs_audit={confidence_report.k_needs_audit} "
        f"mean={confidence_report.mean_confidence:.3f}"
    )

    # Sprint 27: dual-agent extraction audit. Parses the dual-pass
    # reviewer-provenance tag into a per-study record showing per-field
    # agreement state. Reframes "needs human audit" as "agent-review
    # status" — the platform thesis is agent-to-agent adjudication, not
    # human duplicate review.
    from agent.dual_agent_audit import audit_extractions
    dual_agent = audit_extractions(receipts_rehydrated)
    (rd / "dual_agent_extraction_audit.json").write_text(
        json.dumps(dual_agent.as_dict(), indent=2), encoding="utf-8",
    )
    print(
        f"[extract] dual-agent: k_total={dual_agent.k_total} "
        f"agreed={dual_agent.k_agent_agreed} "
        f"adjudicated={dual_agent.k_agent_adjudicated} "
        f"single_pass={dual_agent.k_single_pass} "
        f"blocking={dual_agent.k_blocking}"
    )

    # Sprint 8 pooling: convert contract-passing receipts to
    # (ExtractedOutcome, EffectSizeRecord) pairs and write to disk so
    # regen_section3 can render the primary-effect prose. Receipts that
    # lack pooling numerics are recorded as skipped with reason.
    outcomes, effects, skipped_ids = compile_pool(receipts_rehydrated, pack)
    pool_path = rd / "effect_pool.json"
    pool_path.write_text(
        json.dumps({
            "_doc": (
                "Sprint 8 pooled effect-size records. Inverse-variance "
                "pooling consumes this file; main_draft.md Primary Pooled "
                "Effect renders from the resulting packet."
            ),
            "topic": args.topic,
            "run_id": rd.name,
            "frozen_at_utc": _now_utc(),
            "k_outcomes": len(outcomes),
            "k_effects": len(effects),
            "skipped_study_ids": list(skipped_ids),
            "outcomes": [
                {
                    "study_id": o.study_id, "outcome_id": o.outcome_id,
                    "metric_name": o.metric_name,
                    "moderators": dict(o.moderators),
                    "treated_value": o.treated_value,
                    "control_value": o.control_value,
                    "treated_n": o.treated_n, "control_n": o.control_n,
                    "raw_unit": o.raw_unit,
                }
                for o in outcomes
            ],
            "effects": [
                {
                    "study_id": e.study_id, "outcome_id": e.outcome_id,
                    "metric": e.metric, "estimate": e.estimate,
                    "se": e.se, "ci_low": e.ci_low, "ci_high": e.ci_high,
                    "moderators": dict(e.moderators),
                }
                for e in effects
            ],
        }, indent=2),
        encoding="utf-8",
    )

    dt_secs = time.time() - t0
    print(
        f"[extract] wrote {out_path} "
        f"({len(all_receipts)} records, {k_contract_passing} contract-pass, "
        f"{dt_secs:.1f}s)"
    )
    print(
        f"[extract] wrote {pool_path} "
        f"({len(effects)} pooling-ready effects, {len(skipped_ids)} skipped)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
