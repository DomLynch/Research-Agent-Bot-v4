"""Sprint 16 — universal readiness classifier (L1..L6).

Reads the four canonical receipt JSONs (eligibility_summary,
primary_effect_input_set_strict, effect_extractions, effect_pool) and
classifies the paper's evidence maturity on a 1..6 ladder:

  L1 scaffold              — no pipeline run yet (no receipts present)
  L2 no-eligible-studies   — pipeline ran but k_eligible = 0
  L3 no-primary-set        — eligible studies exist but A-core empty
  L4 no-pooled-effects     — A-core records exist but pool.effects empty
  L5 pilot-pool            — pool.effects 1..2 (single-study / pilot)
  L6 meta-analytic-pool    — pool.effects >= 3 (real synthesis ground)

The output drives a one-glance reviewer signal: a journal-grade paper
needs L6; an L3 paper means "writer prose without numeric backing —
not shippable as evidence". Universal: every threshold reads a count
field from the canonical receipts, no domain literals required.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessReport:
    level: int
    label: str
    reasons: tuple[str, ...]
    next_steps: tuple[str, ...]
    counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level, "label": self.label,
            "reasons": list(self.reasons),
            "next_steps": list(self.next_steps),
            "counts": dict(self.counts),
        }


_LABELS: dict[int, str] = {
    1: "scaffold",
    2: "no-eligible-studies",
    3: "no-primary-set",
    4: "no-pooled-effects",
    5: "pilot-pool",
    6: "meta-analytic-pool",
}


def _count_list(d: dict[str, object] | None, key: str) -> int:
    """Defensive list-length read; missing key / non-list -> 0."""
    if not d:
        return 0
    v = d.get(key)
    return len(v) if isinstance(v, list) else 0


def classify_readiness(
    *,
    summary: dict[str, object] | None,
    strict: dict[str, object] | None,
    extractions: dict[str, object] | None,
    pool: dict[str, object] | None,
) -> ReadinessReport:
    """Return the readiness level for the four receipts. Empty / None
    inputs are treated as 0-count, never raise."""
    raw_k = (summary or {}).get("k_eligible", 0)
    k_eligible = int(raw_k) if isinstance(raw_k, (int, float, str)) else 0
    k_a_core = _count_list(strict, "A_core_direct_lifespan")
    k_b_lane = _count_list(strict, "B_disease_model_survival")
    k_extractions = _count_list(extractions, "extractions")
    k_pool = _count_list(pool, "effects")
    counts = {
        "k_eligible": k_eligible, "k_a_core": k_a_core, "k_b_lane": k_b_lane,
        "k_extractions": k_extractions, "k_pool": k_pool,
    }

    if not summary and not strict and not pool:
        return ReadinessReport(
            level=1, label=_LABELS[1],
            reasons=("no receipts present — pipeline has not run",),
            next_steps=("run scripts/build_topic_paper.py --topic <T>",),
            counts=counts,
        )
    if k_eligible == 0:
        return ReadinessReport(
            level=2, label=_LABELS[2],
            reasons=("eligibility_summary.k_eligible = 0 — no study "
                     "passed eligibility",),
            next_steps=("review topic-pack inclusion_terms + sentinels; "
                        "rerun eligibility with broader query",),
            counts=counts,
        )
    if k_a_core == 0:
        return ReadinessReport(
            level=3, label=_LABELS[3],
            reasons=(f"primary_effect_input_set_strict.A_core empty "
                     f"({k_eligible} eligible but none survived the "
                     f"A-core evidence-quote audit)",),
            next_steps=("inspect strict-set demote_reasons; loosen evidence "
                        "criteria via topic-pack if appropriate",),
            counts=counts,
        )
    if k_pool == 0:
        return ReadinessReport(
            level=4, label=_LABELS[4],
            reasons=(f"effect_pool.effects empty ({k_a_core} A-core records "
                     f"but no parseable numeric effects)",),
            next_steps=("rerun scripts/extract_effects.py; inspect "
                        "skipped_study_ids for parse_failed reasons",),
            counts=counts,
        )
    if k_pool < 3:
        return ReadinessReport(
            level=5, label=_LABELS[5],
            reasons=(f"effect_pool.effects = {k_pool} — pilot pool, below "
                     f"the k>=3 threshold for meta-analytic claims",),
            next_steps=("expand corpus; rerun eligibility + extraction with "
                        "broader inclusion or additional sources",),
            counts=counts,
        )
    return ReadinessReport(
        level=6, label=_LABELS[6],
        reasons=(f"effect_pool.effects = {k_pool} >= 3 — supports an "
                 f"inverse-variance pool with heterogeneity + sensitivity",),
        next_steps=("ship; consider risk-of-bias adapter + publication-bias "
                    "tests for journal-readiness uplift",),
        counts=counts,
    )
