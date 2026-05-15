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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _alpha_label_for(audit: dict[str, Any]) -> str:
    """Map gate verdict + flags into a Researka alpha label."""
    status = str(audit.get("status") or "")
    flags = audit.get("blocking_flags") or []
    if status == "rejected":
        if any("metric_family_mix" in f for f in flags):
            return "discard"
        return "speculative_alpha"
    return _LABEL_MAP.get(status, "frontier_hypothesis")


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
    max_lines: int = 4,
) -> list[str]:
    """Build evidence bullets from the cited facts of this thesis."""
    cited = audit.get("cited_fact_ids") or []
    out: list[str] = []
    for fid in cited[:max_lines]:
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
    return out or ["- _No cited facts could be mapped to this thesis._"]


def _render_signal_post(
    topic: str, snapshot: str, review: dict[str, Any],
    lead_audit: dict[str, Any] | None,
    facts_by_id: dict[str, dict[str, Any]],
) -> str:
    label = _alpha_label_for(lead_audit) if lead_audit else "frontier_hypothesis"
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
    evidence_lines: list[str] = []
    if lead_audit:
        evidence_lines = _evidence_lines(lead_audit, facts_by_id)
    if (not evidence_lines or evidence_lines[0].startswith("- _No cited")):
        # Fall back to the frontier tensions list — already contains
        # concrete numeric claims and is what the strategist cited.
        if isinstance(tensions, list) and tensions:
            evidence_lines = [f"- {str(t)[:400]}" for t in tensions[:3]]
        else:
            evidence_lines = ["- _See frontier_review.md for evidence._"]
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
    text = _render_signal_post(topic, snapshot, review, lead, facts_by_id)
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
