"""Sprint 59 — frontier-thesis survival gate.

Five hard checks per thesis:
  1. Citations cannot rest on D_bad_extraction facts.
  2. Citations cannot mix metric families (effect_size + fold_change
     + correlation in same thesis) unless flagged.
  3. Citations cannot reference facts with missing source metadata
     (no DOI and no PMID).
  4. A_core density must be >= a_core_min (default 3) for a thesis
     to claim 'paper opportunity' status.
  5. opportunity_score is capped at 80 unless status == 'survives'.

Outputs per-thesis verdict: survives | needs_source_audit | rejected,
with explicit blocking_flags for downstream operators.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.fact_lanes import LaneVerdict

AUDIT_STATUSES = ("survives", "needs_source_audit", "rejected")


@dataclass(frozen=True, slots=True)
class ThesisAudit:
    thesis_idx: int
    title: str
    status: str
    blocking_flags: tuple[str, ...]
    original_opportunity: int
    capped_opportunity: int
    cited_fact_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"thesis_idx": self.thesis_idx,
                "title": self.title, "status": self.status,
                "blocking_flags": list(self.blocking_flags),
                "original_opportunity": self.original_opportunity,
                "capped_opportunity": self.capped_opportunity,
                "cited_fact_ids": list(self.cited_fact_ids)}


def _cited_fact_ids(
    thesis: dict[str, Any], facts: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Sprint 67: prefer MiMo's explicit cited_fact_ids when present
    in the thesis. Fall back to the substring heuristic only when
    MiMo did not provide an explicit list (older runs / weak models)."""
    explicit = thesis.get("cited_fact_ids")
    if isinstance(explicit, list) and explicit:
        valid_ids = {str(f.get("fact_id") or "")
                     for f in facts if isinstance(f, dict)}
        out = tuple(str(fid) for fid in explicit
                    if isinstance(fid, (str, int))
                    and str(fid) in valid_ids)
        if out:
            return out
        # explicit list given but none match facts -> fall through to heuristic
    text = (str(thesis.get("title") or "")
            + " " + str(thesis.get("rationale") or "")).lower()
    cited: list[str] = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        nv = f.get("numeric_value")
        units = str(f.get("units") or "")
        nv_variants: list[str] = []
        if isinstance(nv, (int, float)):
            nv_variants = [f"{nv:g}{units}".lower(),
                           f"{nv:g} {units}".lower(),
                           f"{nv:g}".lower()] if units else [f"{nv:g}".lower()]
        phrase_lead = str(f.get("canonical_phrase") or "")[:40].lower()
        if (any(v and v in text for v in nv_variants)) or \
           (phrase_lead and phrase_lead in text):
            cited.append(str(f.get("fact_id") or ""))
    return tuple(cited)


def audit_thesis(
    thesis: dict[str, Any], thesis_idx: int,
    facts: list[dict[str, Any]],
    lane_verdicts: list[LaneVerdict],
    *, a_core_min: int = 3,
) -> ThesisAudit:
    """Single-thesis audit. Universal — operates only on dataclass
    fields and structural counts."""
    title = str(thesis.get("title") or "")
    opp = int(thesis.get("opportunity_score") or 0)
    flags: list[str] = []

    cited = _cited_fact_ids(thesis, facts)
    by_id = {v.fact_id: v for v in lane_verdicts}
    fact_by_id = {str(f.get("fact_id") or ""): f
                  for f in facts if isinstance(f, dict)}

    # Gate 1 — D_bad_extraction citations
    d_bad = [fid for fid in cited
             if by_id.get(fid) and by_id[fid].lane == "D_bad_extraction"]
    if d_bad:
        flags.append(f"cites_d_bad_extraction:{len(d_bad)}")

    # Gate 2 — metric family mix
    cited_roles = {by_id[fid].numeric_role for fid in cited if fid in by_id}
    real_roles = cited_roles & {"effect_size", "fold_change", "correlation"}
    if len(real_roles) > 1:
        flags.append(f"metric_family_mix:{sorted(real_roles)}")

    # Gate 3 — missing source metadata
    for fid in cited:
        paper = (fact_by_id.get(fid, {}).get("source_paper") or {})
        if not paper.get("doi") and not paper.get("pmid"):
            flags.append(f"missing_source_metadata:{fid}")

    # Gate 4 — A_core density
    a_core_cited = [fid for fid in cited
                    if by_id.get(fid) and by_id[fid].lane == "A_core"]
    if len(a_core_cited) < a_core_min:
        flags.append(
            f"a_core_density_too_low:{len(a_core_cited)}<{a_core_min}",
        )

    # Status + Gate 5 (opportunity cap)
    if not flags:
        status, capped = "survives", opp
    elif any(f.startswith("cites_d_bad_extraction") for f in flags) \
            or any(f.startswith("metric_family_mix") for f in flags):
        status, capped = "rejected", min(opp, 40)
    else:
        status, capped = "needs_source_audit", min(opp, 80)

    return ThesisAudit(
        thesis_idx=thesis_idx, title=title, status=status,
        blocking_flags=tuple(flags),
        original_opportunity=opp, capped_opportunity=capped,
        cited_fact_ids=cited,
    )


def audit_frontier_review(
    review: dict[str, Any], facts: list[dict[str, Any]],
    lane_verdicts: list[LaneVerdict], *, a_core_min: int = 3,
) -> list[ThesisAudit]:
    """Audit every thesis in a frontier_review.json payload."""
    theses_raw = review.get("theses", [])
    if not isinstance(theses_raw, list):
        return []
    return [
        audit_thesis(t, i, facts, lane_verdicts, a_core_min=a_core_min)
        for i, t in enumerate(theses_raw) if isinstance(t, dict)
    ]
