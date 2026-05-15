"""Sprint 59 (Evidence Opportunities Gate) — A/B/C/D lane classifier.

Demotes facts where the numeric role isn't a real finding (regimen,
timepoint, dose) or the PICO is incomplete; promotes facts where
intervention, population, and effect-shaped numeric all align with
the topic. Universal: rules use fact structural fields + topic-word
co-occurrence + numeric role; no biomedical domain literals.

Lanes:
  A_core           — topic in intervention + clean PICO + real effect
  B_context        — topic in phrase but not intervention; still useful
                     as mechanism / translational support
  C_noise          — topic word absent from every structural field
  D_bad_extraction — missing population/intervention OR numeric is not
                     an effect (regimen, timepoint, dose, p-value, etc.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.numeric_role_classifier import (
    classify_numeric_role,
    is_real_finding,
)

LANES = ("A_core", "B_context", "C_noise", "D_bad_extraction")


@dataclass(frozen=True, slots=True)
class LaneVerdict:
    fact_id: str
    lane: str
    numeric_role: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, "lane": self.lane,
                "numeric_role": self.numeric_role, "reason": self.reason}


def _has_field(fact: dict[str, Any], key: str) -> bool:
    return bool(str(fact.get(key) or "").strip())


def _topic_haystack(fact: dict[str, Any]) -> str:
    return " ".join([
        str(fact.get("canonical_phrase") or ""),
        str(fact.get("population") or ""),
        str(fact.get("intervention") or ""),
        str(fact.get("comparator") or ""),
        str(fact.get("sub_topic") or ""),
    ]).lower()


def classify_lane(fact: dict[str, Any], topic: str) -> LaneVerdict:
    """Single-fact lane classification."""
    fact_id = str(fact.get("fact_id") or "")
    phrase = str(fact.get("canonical_phrase") or "")
    nv = fact.get("numeric_value")
    nv_f: float | None = float(nv) if isinstance(nv, (int, float)) else None
    units = str(fact.get("units") or "")
    role = classify_numeric_role(nv_f, units, phrase)

    if not _has_field(fact, "population") or not _has_field(fact, "intervention"):
        return LaneVerdict(
            fact_id=fact_id, lane="D_bad_extraction",
            numeric_role=role, reason="missing_population_or_intervention",
        )
    if not is_real_finding(role):
        return LaneVerdict(
            fact_id=fact_id, lane="D_bad_extraction",
            numeric_role=role,
            reason=f"numeric_role={role}_not_effect_finding",
        )

    tw = topic.replace("_", " ").lower()
    if tw not in _topic_haystack(fact):
        return LaneVerdict(
            fact_id=fact_id, lane="C_noise",
            numeric_role=role,
            reason="topic_word_absent_from_pico_fields",
        )

    if tw in str(fact.get("intervention") or "").lower():
        return LaneVerdict(
            fact_id=fact_id, lane="A_core",
            numeric_role=role,
            reason="topic_in_intervention_pico_complete",
        )
    return LaneVerdict(
        fact_id=fact_id, lane="B_context",
        numeric_role=role,
        reason="topic_in_phrase_but_not_intervention",
    )


def classify_lanes(
    facts: list[dict[str, Any]], topic: str,
) -> list[LaneVerdict]:
    """Batch classification. Ignores non-dict entries silently."""
    return [classify_lane(f, topic) for f in facts if isinstance(f, dict)]


def lane_counts(verdicts: list[LaneVerdict]) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(LANES, 0)
    for v in verdicts:
        if v.lane in counts:
            counts[v.lane] += 1
    return counts
