"""Sprint 7.9 - freeze the primary-effect-extraction input set.

Reads an iter-N run dir, applies the include contract retroactively,
classifies surviving includes into lanes A/B/C/D/E, and writes:

  primary_effect_input_set.json   { topic, run_id, frozen_at_utc,
                                    studies: [ {study_id, title, doi,
                                    pmid, year, venue, lane,
                                    char_count, evidence_quotes,
                                    contract_pass} ] }

Only Lane A (direct lifespan) papers are stamped as primary-effect
candidates. Lane B (disease-model survival) is included with a flag
for later pre-specified inclusion. Lanes C/D/E are excluded.

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

from agent.include_contract import classify_lane
from agent.manual_resolution import load_manual_resolutions
from agent.retrieval.base import normalize_doi
from agent.topic_pack import load_topic_pack

_LANE_LETTERS = {
    "direct_lifespan": "A",
    "disease_model_survival": "B",
    "secondary_molecular": "C",
    "healthspan_only": "C",
    "exclude": "E",
}


def _lane_letter(manual_lane: str) -> str:
    """Map the manual TOML lane name to the lane-letter prefix used by
    agent.include_contract.Lane (A/B/C/D/E)."""
    return _LANE_LETTERS.get(manual_lane, "E")


def _passes_contract(
    receipt: dict[str, Any], parsed: dict[str, Any], title: str, pack: Any,
) -> bool:
    """Mirror of agent.include_contract.validate_include on JSON dicts."""
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
    cands = json.loads((rd / "candidates.json").read_text(encoding="utf-8"))
    elig = json.loads((rd / "eligibility_receipts.json").read_text(encoding="utf-8"))
    parsed = json.loads((rd / "parsed_receipts.json").read_text(encoding="utf-8"))
    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack {args.topic!r}", file=sys.stderr)
        return 2

    cand_by_id = {c["study_id"]: c for c in cands}
    parsed_by_id = {p["study_id"]: p for p in parsed}

    accept_lanes = {"A_direct_lifespan"}
    if args.include_lane_b:
        accept_lanes.add("B_disease_model_survival")

    # Sprint 7.10b: manual overrides may carry a `lane` declaration that
    # short-circuits the heuristic classifier. Index by DOI + PMID for
    # fast lookup against candidate identifiers.
    manual_by_key: dict[str, str] = {}
    for mr in load_manual_resolutions(args.topic):
        if mr.lane:
            if mr.doi:
                norm = normalize_doi(mr.doi)
                if norm:
                    manual_by_key[norm] = f"{_lane_letter(mr.lane)}_{mr.lane}"
            if mr.pmid:
                manual_by_key[mr.pmid] = f"{_lane_letter(mr.lane)}_{mr.lane}"

    def _resolve_lane(cand: dict[str, Any], parsed_rec: dict[str, Any],
                      decision: str) -> str:
        doi_norm = normalize_doi(cand.get("doi") or "") if cand.get("doi") else None
        if doi_norm and doi_norm in manual_by_key:
            return manual_by_key[doi_norm]
        if cand.get("pmid") and cand["pmid"] in manual_by_key:
            return manual_by_key[cand["pmid"]]
        return classify_lane(
            cand.get("title", ""), int(parsed_rec.get("char_count", 0)),
            decision, pack,
        )

    studies: list[dict[str, Any]] = []
    counts = {"A_direct_lifespan": 0, "B_disease_model_survival": 0,
              "C_secondary_molecular": 0, "D_review_background": 0,
              "E_exclude": 0}
    for r in elig:
        if r["decision"] != "include":
            continue
        sid = r["study_id"]
        cand = cand_by_id.get(sid, {})
        parsed_rec = parsed_by_id.get(sid, {})
        contract_ok = _passes_contract(r, parsed_rec, cand.get("title", ""), pack)
        # Manual overrides bypass the contract (handled by include_contract
        # already, but check defensively here too for retro QA on legacy runs).
        is_manual = (
            r.get("reviewer", "").startswith("human-")
            or r.get("rule_decision") == "manual-override"
        )
        if is_manual:
            contract_ok = True
        effective_decision = "include" if contract_ok else "unclear"
        lane = _resolve_lane(cand, parsed_rec, effective_decision)
        counts[lane] = counts.get(lane, 0) + 1
        if lane in accept_lanes:
            studies.append({
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
                "manual_override": is_manual,
            })

    out = {
        "topic": args.topic,
        "run_id": rd.name,
        "frozen_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "lane_counts": counts,
        "accepted_lanes": sorted(accept_lanes),
        "k_studies_frozen": len(studies),
        "studies": studies,
    }
    target = rd / "primary_effect_input_set.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[freeze] lane counts: {counts}")
    print(f"[freeze] frozen {len(studies)} studies in primary set "
          f"({'+ Lane B' if args.include_lane_b else 'Lane A only'})")
    print(f"[freeze] wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
