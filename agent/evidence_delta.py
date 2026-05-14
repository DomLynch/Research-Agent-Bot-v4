"""Sprint 40 — Evidence Index delta detector.

Compares two `EvidenceIndex` snapshots (current vs prior) and emits
"monthly movers" classifications per claim: new / strengthened /
weakened / unchanged / lost. Universal — no domain literals; the
delta logic reads confidence_0_100 + supporting/contradicting counts.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.evidence_index import ClaimAtom, EvidenceIndex


@dataclass(frozen=True, slots=True)
class ClaimDelta:
    topic: str
    claim_text: str
    direction: str  # "new" / "strengthened" / "weakened" / "unchanged" / "lost"
    current_confidence: int | None
    previous_confidence: int | None
    delta_points: int           # current - previous (0 for new/lost)
    new_supporting_studies: tuple[str, ...]
    new_contradicting_studies: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic, "claim_text": self.claim_text,
            "direction": self.direction,
            "current_confidence": self.current_confidence,
            "previous_confidence": self.previous_confidence,
            "delta_points": self.delta_points,
            "new_supporting_studies": list(self.new_supporting_studies),
            "new_contradicting_studies": list(self.new_contradicting_studies),
        }


def _by_text(claims: tuple[ClaimAtom, ...]) -> dict[str, ClaimAtom]:
    return {c.claim_text: c for c in claims}


def compute_delta(
    current: EvidenceIndex, previous: EvidenceIndex | None,
) -> tuple[ClaimDelta, ...]:
    """Match claims by claim_text across snapshots and classify each."""
    cur_by = _by_text(current.claims)
    prev_by = _by_text(previous.claims) if previous else {}
    seen: set[str] = set()
    deltas: list[ClaimDelta] = []

    for text, cur in cur_by.items():
        seen.add(text)
        prev = prev_by.get(text)
        if prev is None:
            deltas.append(ClaimDelta(
                topic=cur.topic, claim_text=text, direction="new",
                current_confidence=cur.confidence_0_100,
                previous_confidence=None, delta_points=0,
                new_supporting_studies=cur.supporting_study_ids,
                new_contradicting_studies=cur.contradicting_study_ids,
            ))
            continue
        d = cur.confidence_0_100 - prev.confidence_0_100
        direction = "strengthened" if d > 0 else "weakened" if d < 0 else "unchanged"
        new_supp = tuple(s for s in cur.supporting_study_ids if s not in prev.supporting_study_ids)
        new_contra = tuple(s for s in cur.contradicting_study_ids if s not in prev.contradicting_study_ids)
        deltas.append(ClaimDelta(
            topic=cur.topic, claim_text=text, direction=direction,
            current_confidence=cur.confidence_0_100,
            previous_confidence=prev.confidence_0_100, delta_points=d,
            new_supporting_studies=new_supp,
            new_contradicting_studies=new_contra,
        ))

    # Claims that existed in `previous` but vanished in `current`.
    for text, prev in prev_by.items():
        if text not in seen:
            deltas.append(ClaimDelta(
                topic=prev.topic, claim_text=text, direction="lost",
                current_confidence=None,
                previous_confidence=prev.confidence_0_100, delta_points=0,
                new_supporting_studies=(), new_contradicting_studies=(),
            ))
    return tuple(deltas)


def deltas_as_dict(
    current: EvidenceIndex, deltas: tuple[ClaimDelta, ...],
) -> dict[str, object]:
    """Wrap deltas in a snapshot-aware payload for monthly-movers JSON."""
    return {
        "topic": current.topic,
        "snapshot_utc": current.snapshot_utc,
        "movers": [d.as_dict() for d in deltas],
    }
