"""Sprint 7.6 Corpus QA tool.

Reads an iter-N run directory (candidates + parsed + eligibility receipts)
and emits two human-readable audit artefacts:

  - qa_report.md      per-include spot-check table + sentinel stage audit
                      + topline counts + unclear-queue summary
  - manual_review.md  the 30 unclear receipts laid out for human review

No LLM calls. No new dependencies. Pure read-only consumer of receipts.
Per V4 playbook rules 11 (small reversible diff) + 35 (stdlib first).

Usage:
    .venv/bin/python scripts/corpus_qa.py <run-dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.include_contract import classify_lane
from agent.manual_resolution import build_manual_status_overlay, load_manual_resolutions
from agent.retrieval.base import normalize_doi
from agent.screening import CandidateStudy
from agent.topic_pack import load_topic_pack


def _load(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _index_candidates(cands: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["study_id"]: c for c in cands}


def _sentinel_lookup(cands: list[dict[str, Any]], sentinel_ids: tuple[str, ...]) -> dict[str, dict[str, Any] | None]:
    """Map each sentinel id to its candidate row (or None if not promoted)."""
    by_doi: dict[str, dict[str, Any]] = {}
    by_pmid: dict[str, dict[str, Any]] = {}
    for c in cands:
        if c.get("doi"):
            n = normalize_doi(c["doi"])
            if n:
                by_doi[n] = c
        if c.get("pmid"):
            by_pmid[str(c["pmid"])] = c
    out: dict[str, dict[str, Any] | None] = {}
    for sid in sentinel_ids:
        norm = normalize_doi(sid) if "/" in sid else sid
        out[sid] = by_doi.get(norm or "") or by_pmid.get(sid)
    return out


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return head + "\n" + sep + "\n" + body


def _truncate(s: str, n: int = 90) -> str:
    s = (s or "").replace("\n", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "..."


def _passes_contract(
    receipt: dict[str, Any], parsed: dict[str, Any], title: str, pack: Any,
) -> bool:
    """Dict-based mirror of agent.include_contract.validate_include so
    corpus_qa can retro-apply the contract to legacy JSON receipts without
    reconstructing EligibilityReceipt objects. Hard rules:
      - parsed_text_adequate True
      - char_count >= 5000
      - >= 2 non-title-duplicate evidence quotes
      - >= 1 quote containing an endpoint term
      - >= 1 quote containing an intervention or control term

    Sprint 7.11.1: NO manual bypass. The universal evidence contract
    is the sole gate; manuals can only resolve sentinel status, never
    launder unresolved evidence into the corpus.
    """
    from agent.include_contract import MIN_CHARS, MIN_EVIDENCE_QUOTES
    if not receipt.get("mandatory_fields", {}).get("parsed_text_adequate", False):
        return False
    if int(parsed.get("char_count", 0)) < MIN_CHARS:
        return False
    quotes = receipt.get("evidence_quotes") or []
    norm_t = "".join(c for c in (title or "").casefold() if c.isalnum())
    non_title: list[str] = []
    for q in quotes:
        norm_q = "".join(c for c in q.casefold() if c.isalnum())
        if norm_t and (norm_q == norm_t or norm_q == norm_t[: len(norm_q)]):
            continue
        non_title.append(q)
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


def _per_include_rows(
    receipts: list[dict[str, Any]], parsed_by_id: dict[str, dict[str, Any]],
    cand_by_id: dict[str, dict[str, Any]], pack: Any,
    strict_lane_by_id: dict[str, str] | None = None,
) -> list[list[str]]:
    strict_lane_by_id = strict_lane_by_id or {}
    rows: list[list[str]] = []
    for r in receipts:
        if r["decision"] != "include":
            continue
        sid = r["study_id"]
        cand = cand_by_id.get(sid, {})
        parsed = parsed_by_id.get(sid, {})
        fields = r.get("mandatory_fields", {})
        evidence = r.get("evidence_quotes") or [""]
        # Sprint 7.11.2: pull the post-overlay lane from the strict
        # bucket file when available; fall back to the heuristic
        # classifier for legacy runs without a strict file. This is the
        # difference between showing s092 as "A" (legacy classifier) vs
        # "C" (after manual resolved_excluded subtraction).
        lane_letter = strict_lane_by_id.get(sid)
        if lane_letter is None:
            lane_letter = classify_lane(
                cand.get("title", ""), parsed.get("char_count", 0),
                r.get("decision"), pack,
            ).split("_", 1)[0]
        rows.append([
            sid,
            lane_letter,
            _truncate(cand.get("title", "?"), 60),
            str(cand.get("year") or "?"),
            "yes" if fields.get("species_match") else "no",
            "yes" if fields.get("intervention_match") else "no",
            "yes" if fields.get("endpoint_present") else "no",
            "yes" if fields.get("control_present") else "no",
            f"{r['confidence']:.2f}",
            f"{parsed.get('char_count', 0)}",
            _truncate(evidence[0], 90),
        ])
    return rows


def _sentinel_rows(
    pack_sentinels: dict[str, str],  # sid -> "primary" | "prior_meta"
    cands: list[dict[str, Any]],
    parsed_by_id: dict[str, dict[str, Any]],
    elig_by_id: dict[str, dict[str, Any]],
) -> list[list[str]]:
    sentinel_map = _sentinel_lookup(cands, tuple(pack_sentinels))
    rows: list[list[str]] = []
    for sid, role in pack_sentinels.items():
        cand = sentinel_map.get(sid)
        if cand is None:
            rows.append([sid, role, "missing", "-", "-", "-", "-"])
            continue
        study_id = cand["study_id"]
        parsed = parsed_by_id.get(study_id)
        elig = elig_by_id.get(study_id)
        rows.append([
            sid,
            role,
            "retrieved+candidate",
            "yes" if parsed and parsed.get("parsed") else "no",
            elig["decision"] if elig else ("no-decision" if parsed else "no-parse"),
            f"{elig['confidence']:.2f}" if elig else "-",
            _truncate(
                elig["reason"] if elig
                else (parsed.get("failure_reason", "-") if parsed else "no parsed receipt"),
                90,
            ),
        ])
    return rows


def _unclear_blocks(
    receipts: list[dict[str, Any]], cand_by_id: dict[str, dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for r in receipts:
        if r["decision"] != "unclear":
            continue
        cand = cand_by_id.get(r["study_id"], {})
        missing = [k for k, v in r.get("mandatory_fields", {}).items() if not v]
        quotes = "\n".join(f"    - {_truncate(q, 200)}" for q in r.get("evidence_quotes", [])[:3])
        blocks.append(
            f"### {r['study_id']} - {_truncate(cand.get('title', '?'), 100)}\n"
            f"- year: {cand.get('year') or '?'}  venue: {cand.get('venue') or '?'}\n"
            f"- doi: {cand.get('doi') or '-'}  pmid: {cand.get('pmid') or '-'}\n"
            f"- confidence: {r['confidence']:.2f}\n"
            f"- rule_decision: {r['rule_decision']}  reviewer: {r['reviewer']}\n"
            f"- missing mandatory: {', '.join(missing) or '(none)'}\n"
            f"- merge reason: {r['reason']}\n"
            f"- evidence quotes (first 3):\n{quotes or '    - (none)'}"
        )
    return "\n\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path, help="path to a runs/<topic>-s7-iter-NN-... directory")
    parser.add_argument("--topic", default="rapamycin")
    args = parser.parse_args()

    rd: Path = args.run_dir
    if not rd.is_dir():
        print(f"ERROR: not a directory: {rd}", file=sys.stderr)
        return 2
    cands_raw = _load(rd / "candidates.json")
    elig_raw = _load(rd / "eligibility_receipts.json")
    parsed_raw = _load(rd / "parsed_receipts.json")
    if cands_raw is None:
        print(
            f"ERROR: {rd}/candidates.json missing - regenerate via run_eligibility.py",
            file=sys.stderr,
        )
        return 3
    cands: list[dict[str, Any]] = cands_raw  # type: ignore[assignment]
    elig: list[dict[str, Any]] = elig_raw or []  # type: ignore[assignment]
    parsed: list[dict[str, Any]] = parsed_raw or []  # type: ignore[assignment]

    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack {args.topic!r}", file=sys.stderr)
        return 4

    cand_by_id = _index_candidates(cands)
    parsed_by_id = {p["study_id"]: p for p in parsed}
    elig_by_id = {r["study_id"]: r for r in elig}

    # Sprint 7.8: apply the include contract retroactively when reading
    # legacy runs (iter-15 was generated before the contract landed). Any
    # include that fails the contract is shown as 'unclear' in the audit
    # so the report reflects what the post-contract pipeline would emit.
    demoted_ids: set[str] = set()
    for r in elig:
        if r.get("decision") != "include":
            continue
        sid = r["study_id"]
        parsed_rec = parsed_by_id.get(sid, {})
        cand_rec = cand_by_id.get(sid, {})
        if not _passes_contract(r, parsed_rec, cand_rec.get("title", ""), pack):
            r["decision"] = "unclear"
            r["reason"] = "include_contract retro-demoted: " + r.get("reason", "")
            demoted_ids.add(sid)

    pack_sentinels: dict[str, str] = {
        **{s: "primary" for s in pack.sentinel_primary},
        **{s: "prior_meta" for s in pack.sentinel_prior_meta},
    }
    sentinel_rows = _sentinel_rows(pack_sentinels, cands, parsed_by_id, elig_by_id)

    # Sprint 7.11.2: read primary_effect_input_set_strict.json (if present)
    # so the per-include lane column reflects the post-overlay 3-bucket
    # split instead of the legacy lane classifier. Without this, s092 /
    # s244 / s263 (manually resolved_excluded) still display as Lane A.
    strict_path = rd / "primary_effect_input_set_strict.json"
    strict_lane_by_id: dict[str, str] = {}
    if strict_path.exists():
        strict = json.loads(strict_path.read_text(encoding="utf-8"))
        for s in strict.get("A_core_direct_lifespan", []):
            strict_lane_by_id[s["study_id"]] = "A"
        for s in strict.get("B_disease_model_survival", []):
            strict_lane_by_id[s["study_id"]] = "B"
        for s in strict.get("C_secondary_contextual", []):
            strict_lane_by_id[s["study_id"]] = "C"
    include_rows = _per_include_rows(
        elig, parsed_by_id, cand_by_id, pack, strict_lane_by_id,
    )
    decisions = Counter(r["decision"] for r in elig)

    # Sprint 7.11.2: surface the manual_status_overlay so the report
    # categorises each sentinel as resolved_available_pending_contract /
    # resolved_unavailable / resolved_excluded / needs_review instead of
    # blindly accepting "include with reviewer=human-dom".
    overlay_cands = tuple(
        CandidateStudy(
            study_id=c["study_id"], hit_key=c.get("hit_key", ""),
            title=c.get("title", ""), year=c.get("year"), venue=c.get("venue"),
            pmid=c.get("pmid"), doi=c.get("doi"),
        )
        for c in cands
    )
    overlay = build_manual_status_overlay(
        load_manual_resolutions(args.topic), overlay_cands,
    )
    overlay_rows: list[list[str]] = []
    pending_primaries: list[str] = []
    for sid, role in pack_sentinels.items():
        cand_row = next(
            (c for c in cands if (c.get("doi") and normalize_doi(c["doi"]) == (normalize_doi(sid) or ""))
             or (c.get("pmid") and str(c["pmid"]) == sid)),
            None,
        )
        cand_id = cand_row["study_id"] if cand_row else ""
        elig_row = elig_by_id.get(cand_id, {}) if cand_id else {}
        auto_decision = str(elig_row.get("decision", "no-receipt"))
        manual = overlay.get(cand_id) if cand_id else None
        if manual is None:
            status = "(no manual record)"
        elif manual.status == "resolved_available" and auto_decision != "include":
            status = "resolved_available_pending_contract"
        else:
            status = manual.status
        if role == "primary" and status == "resolved_available_pending_contract":
            pending_primaries.append(sid)
        overlay_rows.append([
            sid, role, cand_id or "-", auto_decision, status,
            _truncate(manual.action_required if manual else "", 60),
        ])

    qa = [
        f"# Corpus QA Report - {rd.name}\n",
        f"Topic: {args.topic}\n",
        "## Topline counts",
        f"- candidates: {len(cands)}",
        f"- parsed (parsed=True): {sum(1 for p in parsed if p['parsed'])}",
        f"- eligibility decisions: {len(elig)}",
        f"  - include: {decisions.get('include', 0)}",
        f"  - exclude: {decisions.get('exclude', 0)}",
        f"  - unclear: {decisions.get('unclear', 0)}",
        f"  - unavailable: {decisions.get('unavailable', 0)}",
        f"- declared sentinels: {len(pack_sentinels)} "
        f"({sum(1 for v in pack_sentinels.values() if v == 'primary')} primary + "
        f"{sum(1 for v in pack_sentinels.values() if v == 'prior_meta')} prior_meta)\n",
        "## Per-include audit\n",
        _md_table(
            ["study_id", "lane", "title", "yr", "spec", "interv", "endp", "ctrl",
             "conf", "chars", "first evidence quote"],
            include_rows,
        ) if include_rows else "_(no includes)_",
        "\n## Sentinel-stage audit\n",
        _md_table(
            ["sentinel_id", "role", "stage", "parsed?", "elig", "conf", "reason / failure"],
            sentinel_rows,
        ) if sentinel_rows else "_(no sentinels declared)_",
        "\n## Sentinel resolution status (manual overlay)\n",
        _md_table(
            ["sentinel_id", "role", "study_id", "auto_decision",
             "manual_status", "action_required"],
            overlay_rows,
        ) if overlay_rows else "_(no sentinels declared)_",
        "\n## Quality flags\n",
    ]
    flags: list[str] = []
    include_no_evidence = [r for r in elig if r["decision"] == "include" and not r.get("evidence_quotes")]
    if include_no_evidence:
        flags.append(f"- {len(include_no_evidence)} include(s) with NO evidence quotes - "
                     "demote to manual review.")
    high_conf_partial = [
        r for r in elig
        if r["decision"] == "include" and r["confidence"] >= 0.99
        and not all(r["mandatory_fields"].get(k, False) for k in
                    ("species_match", "intervention_match", "endpoint_present",
                     "control_present", "primary_research_design"))
    ]
    if high_conf_partial:
        flags.append(f"- {len(high_conf_partial)} include(s) with conf>=0.99 but "
                     "missing >=1 mandatory field - judge over-confidence smell.")
    # Sprint 7.11.2: pending-contract primary sentinels are a documented
    # SYSTEM-LEVEL GAP (retrieval/parser owes work). They are surfaced
    # here so the report can't quietly read "Quality flags: none" while
    # canonical sentinels are still unresolved.
    if pending_primaries:
        flags.append(
            f"- sentinel contract gaps remain: {len(pending_primaries)} "
            f"primary sentinel(s) resolved_available_pending_contract "
            f"({pending_primaries}); retrieval/parser must fix before "
            f"the universal contract can pass."
        )
    # Hard miss: primary sentinel where neither auto nor manual reaches
    # a final state. A sentinel counts as RESOLVED when:
    #   - auto_decision (row[3]) is in {include, exclude, unavailable}
    #     -> the auto pipeline already produced a terminal verdict; OR
    #   - manual_status (row[4]) is a documented terminal manual state
    #     (resolved_unavailable / resolved_excluded). resolved_available
    #     ALONE is not terminal — it's a status assertion that still
    #     needs a contract pass, surfaced separately via the "sentinel
    #     contract gaps remain" flag above.
    _RESOLVED_AUTO = {"include", "exclude", "unavailable"}
    _RESOLVED_MANUAL = {"resolved_unavailable", "resolved_excluded"}
    sentinel_misses: list[str] = []
    for s, role in pack_sentinels.items():
        if role != "primary":
            continue
        row = next((r for r in overlay_rows if r[0] == s), None)
        if row is None or (
            row[3] not in _RESOLVED_AUTO
            and row[4] not in _RESOLVED_MANUAL
            and row[4] != "resolved_available_pending_contract"
        ):
            sentinel_misses.append(s)
    if sentinel_misses:
        flags.append(f"- {len(sentinel_misses)} primary sentinel(s) UNRESOLVED "
                     f"(no auto verdict + no manual record): {sentinel_misses}")
    if not flags:
        flags.append("- (none)")
    qa.append("\n".join(flags))

    (rd / "qa_report.md").write_text("\n".join(qa) + "\n", encoding="utf-8")

    review = [
        f"# Manual Review Queue - {rd.name}\n",
        f"{decisions.get('unclear', 0)} receipts flagged 'unclear' by the "
        "rule -> judge -> deterministic merge. Sorted by study_id.\n",
        _unclear_blocks(elig, cand_by_id) or "_(none)_",
    ]
    (rd / "manual_review.md").write_text("\n".join(review) + "\n", encoding="utf-8")

    print(f"[qa] qa_report.md            -> {rd / 'qa_report.md'}")
    print(f"[qa] manual_review.md        -> {rd / 'manual_review.md'}")
    print(f"[qa] includes audited: {len(include_rows)} | "
          f"unclear queue: {decisions.get('unclear', 0)} | "
          f"sentinel rows: {len(sentinel_rows)} | flags: "
          f"{len(flags) if flags != ['- (none)'] else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
