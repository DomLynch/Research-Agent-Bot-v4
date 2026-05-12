"""Sprint 7.9 / 7.11.1 - freeze the primary-effect-extraction input set.

Reads an iter-N run dir, applies the universal evidence contract
retroactively, classifies surviving includes into lanes A/B/C/D/E, and
writes:

  primary_effect_input_set.json   { topic, run_id, frozen_at_utc,
                                    studies: [...] }

Sprint 7.11.1: manuals can only resolve sentinel STATUS or subtract
papers from the primary corpus (status='resolved_excluded'). They
cannot launder a paper into the primary set. The universal evidence
contract is the sole gate; the same rules apply to sentinels and
non-sentinels alike.

Universal: lane terms and contract rules come from agent.include_contract.
No biomedical literals in this script.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.include_contract import classify_lane, strict_a_core_check
from agent.manual_resolution import build_manual_status_overlay, load_manual_resolutions
from agent.screening import CandidateStudy
from agent.topic_pack import load_topic_pack


def _passes_contract(
    receipt: dict[str, Any], parsed: dict[str, Any], title: str, pack: Any,
) -> bool:
    """Mirror of agent.include_contract.validate_include on JSON dicts.

    Sprint 7.11.1: no manual bypass. Every receipt is contract-checked
    by the same universal rules regardless of reviewer."""
    from agent.include_contract import MIN_CHARS, MIN_EVIDENCE_QUOTES
    if not receipt.get("mandatory_fields", {}).get("parsed_text_adequate", False):
        return False
    if int(parsed.get("char_count", 0)) < MIN_CHARS:
        return False
    quotes = receipt.get("evidence_quotes") or []
    norm_t = "".join(c for c in (title or "").casefold() if c.isalnum())
    non_title = [
        q for q in quotes
        if not (norm_t and "".join(c for c in q.casefold() if c.isalnum()).startswith(norm_t[:60]))
    ]
    if len(non_title) < MIN_EVIDENCE_QUOTES:
        return False
    endpoint_terms = tuple(getattr(pack, "eligibility_endpoint_terms", ()))
    methods_terms = (
        tuple(getattr(pack, "primary_interventions", ()))
        + tuple(getattr(pack, "eligibility_control_terms", ()))
    )
    if endpoint_terms and not any(
        any(t.casefold() in q.casefold() for t in endpoint_terms if t) for q in quotes
    ):
        return False
    return not methods_terms or any(
        any(t.casefold() in q.casefold() for t in methods_terms if t) for q in quotes
    )


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument(
        "--include-lane-b", action="store_true",
        help="Also include disease-model survival (Lane B) as primary-pool input",
    )
    args = parser.parse_args()

    rd: Path = args.run_dir
    cands_raw = json.loads((rd / "candidates.json").read_text(encoding="utf-8"))
    elig = json.loads((rd / "eligibility_receipts.json").read_text(encoding="utf-8"))
    parsed = json.loads((rd / "parsed_receipts.json").read_text(encoding="utf-8"))
    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack {args.topic!r}", file=sys.stderr)
        return 2

    cand_by_id = {c["study_id"]: c for c in cands_raw}
    parsed_by_id = {p["study_id"]: p for p in parsed}

    # Sprint 7.11.1 manual overlay: maps study_id -> ManualResolutionReceipt.
    # Only resolved_excluded subtracts from the primary corpus; other
    # statuses are informational for the sentinel-recall gate.
    candidates = tuple(_candidate_from_dict(c) for c in cands_raw)
    manual_overlay = build_manual_status_overlay(
        load_manual_resolutions(args.topic), candidates,
    )
    excluded_by_manual: dict[str, str] = {
        sid: r.reason for sid, r in manual_overlay.items()
        if r.status == "resolved_excluded"
    }

    accept_lanes = {"A_direct_lifespan"}
    if args.include_lane_b:
        accept_lanes.add("B_disease_model_survival")

    studies: list[dict[str, Any]] = []
    counts = {"A_direct_lifespan": 0, "B_disease_model_survival": 0,
              "C_secondary_molecular": 0, "D_review_background": 0,
              "E_exclude": 0}
    # Sprint 7.11: strict-A bucket collects evidence-quote-audited primaries;
    # B keeps disease-model survival; C_secondary_contextual collects every
    # paper demoted out of A by the strict gate or by manual exclusion.
    strict_a: list[dict[str, Any]] = []
    strict_b: list[dict[str, Any]] = []
    strict_c: list[dict[str, Any]] = []
    strict_demote_reasons: dict[str, tuple[str, ...]] = {}
    for r in elig:
        if r["decision"] != "include":
            continue
        sid = r["study_id"]
        cand = cand_by_id.get(sid, {})
        parsed_rec = parsed_by_id.get(sid, {})
        contract_ok = _passes_contract(r, parsed_rec, cand.get("title", ""), pack)
        effective_decision = "include" if contract_ok else "unclear"

        # Manual exclusion subtracts from primary corpus regardless of
        # contract result. resolved_excluded is conservative and always
        # allowed.
        if sid in excluded_by_manual:
            lane = "C_secondary_molecular"
        else:
            lane = classify_lane(
                cand.get("title", ""), int(parsed_rec.get("char_count", 0)),
                effective_decision, pack,
            )
        counts[lane] = counts.get(lane, 0) + 1
        study_entry = {
            "study_id": sid,
            "title": cand.get("title"),
            "doi": cand.get("doi"),
            "pmid": cand.get("pmid"),
            "year": cand.get("year"),
            "venue": cand.get("venue"),
            "lane": lane,
            "char_count": parsed_rec.get("char_count", 0),
            "evidence_quotes": r.get("evidence_quotes", []),
            "contract_pass": contract_ok,
            "manually_excluded": sid in excluded_by_manual,
        }
        if lane in accept_lanes:
            studies.append(study_entry)

        # Strict 3-bucket assignment. NO manual bypass: every paper must
        # pass strict_a_core_check on its evidence quotes to land in
        # A-core. Manuals only subtract (resolved_excluded) — they
        # cannot promote.
        quotes = tuple(r.get("evidence_quotes", []))
        strict_ok, strict_reasons = strict_a_core_check(
            r["decision"], quotes, pack,
        )
        if sid in excluded_by_manual:
            # Manual exclusion overrides strict result and routes to C.
            strict_reasons = (f"manual:resolved_excluded: {excluded_by_manual[sid]}",)
            strict_ok = False
        if strict_reasons:
            strict_demote_reasons[sid] = strict_reasons
        if lane == "A_direct_lifespan" and strict_ok:
            strict_a.append({**study_entry, "strict_a_core": True})
        elif lane == "A_direct_lifespan" and not strict_ok:
            strict_c.append({
                **study_entry, "strict_a_core": False,
                "demoted_from": "A_direct_lifespan",
                "demote_reasons": list(strict_reasons),
            })
        elif lane == "B_disease_model_survival":
            strict_b.append(study_entry)
        elif lane == "C_secondary_molecular":
            strict_c.append({
                **study_entry, "demoted_from": None,
                "demote_reasons": list(strict_reasons),
            })

    out = {
        "topic": args.topic,
        "run_id": rd.name,
        "frozen_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "lane_counts": counts,
        "accepted_lanes": sorted(accept_lanes),
        "k_studies_frozen": len(studies),
        "manual_exclusions": list(excluded_by_manual),
        "studies": studies,
    }
    target = rd / "primary_effect_input_set.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[freeze] lane counts: {counts}")
    print(f"[freeze] frozen {len(studies)} studies in primary set "
          f"({'+ Lane B' if args.include_lane_b else 'Lane A only'})")
    print(f"[freeze] manual exclusions: {len(excluded_by_manual)}")
    print(f"[freeze] wrote {target}")

    strict_out = {
        "topic": args.topic,
        "run_id": rd.name,
        "frozen_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "bucket_counts": {
            "A_core_direct_lifespan": len(strict_a),
            "B_disease_model_survival": len(strict_b),
            "C_secondary_contextual": len(strict_c),
        },
        "demote_reasons": {sid: list(rs) for sid, rs in strict_demote_reasons.items()},
        "A_core_direct_lifespan": strict_a,
        "B_disease_model_survival": strict_b,
        "C_secondary_contextual": strict_c,
    }
    strict_target = rd / "primary_effect_input_set_strict.json"
    strict_target.write_text(json.dumps(strict_out, indent=2), encoding="utf-8")
    print(f"[freeze] strict buckets: A={len(strict_a)} B={len(strict_b)} "
          f"C={len(strict_c)} (demoted from A: "
          f"{sum(1 for s in strict_c if s.get('demoted_from') == 'A_direct_lifespan')})")
    print(f"[freeze] wrote {strict_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
