"""Sprint 59 — clean input pack for the frontier model.

Filters facts to A_core (thesis-eligible) + B_context (mechanism
support) before MiMo sees them. C and D excluded entirely. Carries
`has_minimum_a_core` flag for downstream gates that refuse to elevate
a thesis when A-core density is too thin (default >=3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.fact_lanes import LaneVerdict, classify_lanes


@dataclass(frozen=True, slots=True)
class FrontierInputPack:
    topic: str
    a_core: tuple[dict[str, Any], ...]
    b_context: tuple[dict[str, Any], ...]
    excluded_counts: dict[str, int]   # C_noise + D_bad_extraction counts
    has_minimum_a_core: bool
    a_core_min: int

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic,
                "a_core_count": len(self.a_core),
                "b_context_count": len(self.b_context),
                "excluded_counts": dict(self.excluded_counts),
                "has_minimum_a_core": self.has_minimum_a_core,
                "a_core_min": self.a_core_min}


def build_input_pack(
    facts: list[dict[str, Any]], topic: str, *, a_core_min: int = 3,
    lane_verdicts: list[LaneVerdict] | None = None,
) -> FrontierInputPack:
    """Filter facts by lane; return the cleaned input pack. Re-runs
    classify_lanes() unless caller passes pre-computed verdicts."""
    verdicts = lane_verdicts if lane_verdicts is not None \
        else classify_lanes(facts, topic)
    by_id = {v.fact_id: v for v in verdicts}
    a_core: list[dict[str, Any]] = []
    b_context: list[dict[str, Any]] = []
    excluded = {"C_noise": 0, "D_bad_extraction": 0}
    for f in facts:
        if not isinstance(f, dict):
            continue
        v = by_id.get(str(f.get("fact_id") or ""))
        if v is None:
            continue
        if v.lane == "A_core":
            a_core.append(f)
        elif v.lane == "B_context":
            b_context.append(f)
        elif v.lane in excluded:
            excluded[v.lane] += 1
    return FrontierInputPack(
        topic=topic, a_core=tuple(a_core), b_context=tuple(b_context),
        excluded_counts=excluded,
        has_minimum_a_core=len(a_core) >= a_core_min,
        a_core_min=a_core_min,
    )
