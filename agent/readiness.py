"""Sprint 16 — universal readiness classifier (L1..L6).

Classifies evidence maturity from the four canonical receipts:
  L1 scaffold / L2 no-eligible-studies / L3 no-primary-set /
  L4 no-pooled-effects / L5 pilot-pool / L6 meta-analytic-pool.
Universal: thresholds read count fields, no domain literals.
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
            "reasons": list(self.reasons), "next_steps": list(self.next_steps),
            "counts": dict(self.counts),
        }


def _count(d: dict[str, object] | None, key: str) -> int:
    if not d:
        return 0
    v = d.get(key)
    return len(v) if isinstance(v, list) else 0


def _int(d: dict[str, object] | None, key: str) -> int:
    if not d:
        return 0
    raw = d.get(key, 0)
    try:
        return int(raw) if isinstance(raw, (int, float, str)) else 0
    except (TypeError, ValueError):
        return 0


def classify_readiness(
    *,
    summary: dict[str, object] | None,
    strict: dict[str, object] | None,
    extractions: dict[str, object] | None,
    pool: dict[str, object] | None,
) -> ReadinessReport:
    """Return the readiness level. Empty / None inputs never raise."""
    # `effect_extractions.json` carries the list under the key "receipts"
    # (matches extract_effects.py writer); legacy fixtures occasionally
    # used "extractions" — accept both, prefer the canonical key.
    counts = {
        "k_eligible": _int(summary, "k_eligible"),
        "k_a_core": _count(strict, "A_core_direct_lifespan"),
        "k_b_lane": _count(strict, "B_disease_model_survival"),
        "k_extractions": _count(extractions, "receipts") or _count(extractions, "extractions"),
        "k_pool": _count(pool, "effects"),
    }
    k_e, k_a, k_p = counts["k_eligible"], counts["k_a_core"], counts["k_pool"]
    if not summary and not strict and not pool:
        lvl, why, nxt = 1, "no receipts present — pipeline has not run", \
            "run scripts/build_topic_paper.py --topic <T>"
    elif k_e == 0:
        lvl, why, nxt = 2, "eligibility_summary.k_eligible = 0", \
            "review topic-pack inclusion_terms + sentinels; rerun eligibility"
    elif k_a == 0:
        lvl, why, nxt = 3, (
            f"primary_effect_input_set_strict.A_core empty ({k_e} eligible "
            f"but none survived the A-core evidence-quote audit)"
        ), "inspect strict-set demote_reasons; loosen evidence criteria via pack"
    elif k_p == 0:
        lvl, why, nxt = 4, (
            f"effect_pool.effects empty ({k_a} A-core records but no "
            f"parseable numeric effects)"
        ), "rerun extract_effects.py; inspect skipped_study_ids parse failures"
    elif k_p < 3:
        lvl, why, nxt = 5, (
            f"effect_pool.effects = {k_p} — pilot pool, below the k>=3 "
            f"threshold for meta-analytic claims"
        ), "expand corpus; rerun eligibility + extraction with broader inclusion"
    else:
        lvl, why, nxt = 6, (
            f"effect_pool.effects = {k_p} >= 3 — supports an inverse-variance "
            f"pool with heterogeneity + sensitivity"
        ), "ship; consider RoB adapter + pub-bias tests for journal uplift"
    _labels = {1: "scaffold", 2: "no-eligible-studies", 3: "no-primary-set",
               4: "no-pooled-effects", 5: "pilot-pool", 6: "meta-analytic-pool"}
    return ReadinessReport(
        level=lvl, label=_labels[lvl],
        reasons=(why,), next_steps=(nxt,), counts=counts,
    )
