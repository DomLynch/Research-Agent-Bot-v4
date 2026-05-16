"""Sprint 64 — Researka alpha-signal post renderer.

Reads an existing run folder and emits `signal_post.md` in the
auditor's exact format:

  # Signal: <headline>
  # Why this is surprising
  # Evidence
  # Confidence: <alpha label>
  # Next question

Inputs (all read from disk, no new LLM call):
  frontier_review.json   — MiMo's lens + theses + next_extractions
  fact_lanes.json        — A_core/B_context/D_bad per fact (Sprint 59)
  opportunities_gate.json (optional) — thesis audit verdicts
  top_5.md               — Top-5 cards (already dedup + lane-rendered)

Confidence label (deterministic, from existing audit verdict):
  evidence_backed_signal  — gate.status == survives
  frontier_hypothesis     — gate.status == needs_source_audit
  speculative_alpha       — gate.status == rejected with low A_core
  discard                 — gate.status == rejected for metric_mix

Universal — operates only on existing JSON shapes, no domain literals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_LABEL_MAP = {
    "survives": "evidence_backed_signal",
    "needs_source_audit": "frontier_hypothesis",
    "rejected": "speculative_alpha",  # default for rejected
}

# Lanes that count as bound evidence. C_noise/D_bad are excluded —
# Sprint 66 source-binding lock prevents publishing a signal post
# whose only "evidence" is mis-bound or off-topic facts.
_BINDABLE_LANES = frozenset({"A_core", "B_context"})


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _alpha_label_for(
    audit: dict[str, Any],
    bound_a_or_b_count: int = -1,
    has_curation_hints: bool = False,
) -> str:
    """Map gate verdict + flags + binding state into a Researka alpha
    label. When bound_a_or_b_count is provided AND zero, override the
    label to surface the binding gap. Sprint 75: when MiMo provided
    actionable `next_extractions`, prefer the constructive
    `curation_needed` label (= 'thesis has merit, curate these N
    missing facts to unlock publish'); otherwise fall back to the
    legacy `evidence_binding_failed` notice."""
    status = str(audit.get("status") or "")
    flags = audit.get("blocking_flags") or []
    base = _LABEL_MAP.get(status, "frontier_hypothesis")
    if status == "rejected":
        base = ("discard" if any("metric_family_mix" in f for f in flags)
                else "speculative_alpha")
    # Source-binding lock: override when we have explicit binding info
    if bound_a_or_b_count == 0 and base != "discard":
        return "curation_needed" if has_curation_hints else \
            "evidence_binding_failed"
    return base


def _bound_fact_count(
    cited_ids: list[str], facts_by_id: dict[str, dict[str, Any]],
    lane_verdicts: dict[str, str],
) -> int:
    """How many cited facts land in A_core or B_context?"""
    n = 0
    for fid in cited_ids:
        if fid not in facts_by_id:
            continue
        if lane_verdicts.get(fid) in _BINDABLE_LANES:
            n += 1
    return n


def _read_lane_verdicts(run_dir: Path) -> dict[str, str]:
    """fact_id -> lane mapping from Sprint 59 fact_lanes.json."""
    p = run_dir / "fact_lanes.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for v in data.get("verdicts", []) or []:
        if isinstance(v, dict):
            out[str(v.get("fact_id") or "")] = str(v.get("lane") or "")
    return out


def _confidence_human(label: str) -> str:
    return {
        "evidence_backed_signal":
            "**High — evidence-backed signal.** Cited facts pass source-"
            "audit lane gates with A_core density and matched metric "
            "families.",
        "frontier_hypothesis":
            "**Medium — frontier hypothesis.** Idea is sharp but cited "
            "evidence needs source audit before publishing as fact.",
        "speculative_alpha":
            "**Speculative alpha.** Counter-narrative signal worth "
            "noting; underlying evidence is thin or single-study.",
        "curation_needed":
            "**Curation needed.** The thesis idea is sharp but its "
            "cited facts did not bind to the A_core/B_context lane. "
            "MiMo emitted actionable `next_extractions`; see "
            "`curation_brief.md` for the small set of facts to verify "
            "or harvest before this thesis can publish as evidence-"
            "backed.",
        "evidence_binding_failed":
            "**Evidence binding failed.** The thesis idea may be "
            "sharp, but its cited facts either could not be located "
            "or were classified as D_bad_extraction by the lane "
            "gate. **Do not publish as-is.** Treat as an alpha "
            "candidate; needs manual source binding.",
        "discard":
            "**Discard — metric mix.** Citations span incompatible "
            "metric families (effect_size + fold_change). Do not "
            "publish without restructuring.",
    }.get(label, "Unknown.")


def _pick_lead_thesis(
    audits: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pick the strongest thesis: prefer survives > needs_source_audit
    > rejected; within tier pick the highest capped_opportunity."""
    if not audits:
        return None
    rank = {"survives": 3, "needs_source_audit": 2, "rejected": 1}
    return max(
        audits,
        key=lambda a: (rank.get(str(a.get("status") or ""), 0),
                       int(a.get("capped_opportunity") or 0)),
    )


def _evidence_lines(
    audit: dict[str, Any], facts_by_id: dict[str, dict[str, Any]],
    lane_verdicts: dict[str, str] | None = None,
    max_lines: int = 4,
) -> list[str]:
    """Build evidence bullets from the cited facts of this thesis.
    Sprint 68: strict — when lane_verdicts provided, ONLY emit facts
    classified as A_core or B_context. D_bad/C_noise facts are
    excluded so we never publish unbound-but-cited evidence."""
    cited = audit.get("cited_fact_ids") or []
    out: list[str] = []
    for fid in cited:
        if (lane_verdicts is not None
                and lane_verdicts.get(str(fid)) not in _BINDABLE_LANES):
            continue  # D_bad / C_noise / unknown: skip
        f = facts_by_id.get(str(fid))
        if not f:
            continue
        nv = f.get("numeric_value")
        units = str(f.get("units") or "")
        phrase = str(f.get("canonical_phrase") or "")[:200]
        val = (f"{nv:g}{units}" if isinstance(nv, (int, float))
               and not isinstance(nv, bool) else "")
        paper = f.get("source_paper") or {}
        year = paper.get("year") or paper.get("canonical_year") or ""
        journal = str(paper.get("journal") or "")
        attribution = (f" ({journal} {year})".rstrip()
                       if journal or year else "")
        out.append(f"- {phrase}" + (f" **[{val}]**" if val else "")
                   + attribution)
        if len(out) >= max_lines:
            break
    return out or ["- _No cited facts could be mapped to this thesis._"]


def _render_signal_post(
    topic: str, snapshot: str, review: dict[str, Any],
    lead_audit: dict[str, Any] | None,
    facts_by_id: dict[str, dict[str, Any]],
    *,
    bound_count: int = -1,
    lane_verdicts: dict[str, str] | None = None,
) -> str:
    label = (_alpha_label_for(lead_audit, bound_count) if lead_audit
             else "frontier_hypothesis")
    lens = str(review.get("lens") or "").strip()
    known = review.get("known_to_ignore") or []
    next_extracts = review.get("next_extractions") or []
    tensions = review.get("tensions") or []
    theses_list = review.get("theses") or []
    has_thesis = (isinstance(theses_list, list) and theses_list
                  and isinstance(theses_list[0], dict)
                  and str(theses_list[0].get("title") or "").strip())
    # No-signal case: MiMo refused to opine (no theses) — emit an
    # honest 'no signal' marker rather than publishing the disclaimer.
    if not lead_audit and not has_thesis:
        return (
            f"# No signal — {topic}\n\n"
            f"_Snapshot:_ `{snapshot}`\n\n"
            f"**No publishable thesis.** MiMo declined to elevate a "
            f"finding from this evidence pool — typically because facts "
            f"are too noisy, too narrow, or off-target for the topic.\n\n"
            f"## MiMo's note\n\n{lens or '_no lens produced_'}\n\n"
            f"See `frontier_review.md` for the raw lens + tensions, "
            f"and `top_5.md` for the deterministic top-5.\n"
        )
    if lead_audit:
        headline = str(lead_audit.get("title") or "")
    elif has_thesis:
        headline = str(theses_list[0].get("title") or "")
    else:
        headline = f"Open research question — {topic}"
    surprise = (
        lens if lens else
        "No frontier lens produced — see top_5.md for raw findings."
    )
    if isinstance(known, list) and known:
        surprise += ("\n\nKnown / obvious (do not republish): "
                     + "; ".join(str(k)[:180] for k in known[:3]))
    if isinstance(tensions, list) and tensions:
        surprise += ("\n\nReal tension: "
                     + str(tensions[0])[:300])
    # Sprint 66 source-binding lock: if the thesis's cited fact_ids
    # cannot be bound to A_core or B_context lane facts, do NOT fall
    # back to MiMo's `tensions` array (which is unbound prose and
    # mis-attributes evidence to the thesis headline). Instead, emit
    # an explicit 'evidence_binding_failed' notice.
    # Sprint 68 strict: pass lane_verdicts so _evidence_lines filters
    # cited facts to A_core/B_context only (no D_bad evidence bullets).
    evidence_lines = (_evidence_lines(lead_audit, facts_by_id,
                                       lane_verdicts=lane_verdicts)
                      if lead_audit else [])
    bind_failed = (label == "evidence_binding_failed"
                   or not evidence_lines
                   or evidence_lines[0].startswith("- _No cited"))
    if bind_failed:
        evidence_lines = [
            "- **Evidence binding failed.** The thesis cites no facts "
            "that survived the A_core/B_context lane gate. Raw tensions "
            "are in `frontier_review.md`; do not copy them here as "
            "evidence — they are unbound prose, not facts attached to "
            "this headline.",
        ]
    next_q = (str(next_extracts[0]) if isinstance(next_extracts, list)
              and next_extracts else
              "What replicates this signal in independent cohorts?")
    return (
        f"# Signal — {topic}\n\n"
        f"_Snapshot:_ `{snapshot}`\n\n"
        f"## {headline}\n\n"
        f"## Why this is surprising\n\n"
        f"{surprise}\n\n"
        f"## Evidence\n\n"
        + "\n".join(evidence_lines) + "\n\n"
        f"## Confidence — `{label}`\n\n"
        f"{_confidence_human(label)}\n\n"
        f"## Next question\n\n"
        f"{next_q}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run_dir: Path = args.run
    if not (run_dir / "frontier_review.json").exists():
        print(f"[signal-post] no frontier_review.json under {run_dir}",
              file=sys.stderr)
        return 1
    try:
        review = json.loads(
            (run_dir / "frontier_review.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[signal-post] could not parse frontier_review.json: {e}",
              file=sys.stderr)
        return 1
    facts: list[Any] = []
    facts_path = run_dir / "all_facts.json"
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            facts = []
    facts_by_id = {str(f.get("fact_id") or ""): f
                   for f in facts if isinstance(f, dict)}
    audits: list[dict[str, Any]] = []
    gate_path = run_dir / "opportunities_gate.json"
    if gate_path.exists():
        try:
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            raw = gate.get("audits") or [] if isinstance(gate, dict) else []
            audits = [a for a in raw if isinstance(a, dict)]
        except (OSError, json.JSONDecodeError):
            audits = []
    lead = _pick_lead_thesis(audits)
    topic = str(review.get("topic") or run_dir.name.split("-evidence-")[0])
    snapshot = str(review.get("snapshot_utc") or run_dir.name)
    lane_verdicts = _read_lane_verdicts(run_dir)
    bound_count = (_bound_fact_count(
        list(lead.get("cited_fact_ids") or []), facts_by_id, lane_verdicts,
    ) if lead else 0)
    text = _render_signal_post(topic, snapshot, review, lead, facts_by_id,
                                bound_count=bound_count,
                                lane_verdicts=lane_verdicts)
    out_path = run_dir / "signal_post.md"
    out_path.write_text(text, encoding="utf-8")
    # Update MANIFEST if present
    manifest_path = run_dir / "MANIFEST.json"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(m, dict):
                files = m.setdefault("files", {})
                if isinstance(files, dict):
                    files["signal_post_md"] = {
                        "name": out_path.name, "sha256": _sha256(text),
                    }
                manifest_path.write_text(
                    json.dumps(m, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass
    label_used = (_alpha_label_for(lead) if lead else "frontier_hypothesis")
    print(f"[signal-post] {run_dir.name}: label={label_used} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
