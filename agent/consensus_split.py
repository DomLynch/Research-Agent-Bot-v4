"""Evidence-map consensus split — partition a topic's findings into where the
studies AGREE, where they DISAGREE, and what's still OPEN.

The evidence-map lane is heterogeneous by construction (many populations /
endpoints / directions). Today it lists findings without summarising their
*agreement structure*. This module reads the bound facts and classifies each
finding's direction of effect (up / down / null) from its canonical phrase,
then reports:

  - **consensus**     — the dominant direction, when a clear majority agree
  - **disagreement**  — a genuine conflict (≥2 facts each pointing opposite ways)
  - **open_questions** — sparse / inconclusive / unclassifiable findings

Deterministic and universal: a direction LEXICON over phrase tokens, no domain
literals, no LLM. (Inspired by Companion-AI Feynman's consensus/disagreement/
open-question decomposition — reimplemented from the concept, not its code.)
Negation-aware and conservative: ambiguous findings fall to ``unclear`` rather
than being forced into a bucket.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

# Direction lexicons — closed-class effect verbs, domain-agnostic. Order matters
# only in that NULL markers and negation override a bare up/down token.
_UP = frozenset({
    "increase", "increased", "increases", "higher", "greater", "rise", "rose",
    "elevated", "elevate", "improve", "improved", "improves", "improvement",
    "gain", "gained", "prolong", "prolonged", "extend", "extended", "longer",
    "boost", "boosted", "enhanced", "enhance", "upregulated", "more",
})
_DOWN = frozenset({
    "decrease", "decreased", "decreases", "lower", "lowered", "reduce",
    "reduced", "reduces", "reduction", "decline", "declined", "fell", "drop",
    "dropped", "shorten", "shortened", "shorter", "worsen", "worsened", "loss",
    "impair", "impaired", "suppressed", "suppress", "downregulated", "fewer",
    "less",
})
# Explicit null / no-effect phrasing markers (substring match on normalised text).
_NULL_PHRASES = (
    "no significant", "not significant", "no difference", "no effect",
    "no change", "no association", "did not", "no statistically",
    "failed to", "unchanged", "without effect", "non-significant",
    "no measurable",
)
_NEGATORS = frozenset({"no", "not", "never", "without", "failed", "neither"})
_WORD = re.compile(r"[a-z]+")

# A direction is "consensus" only with a real majority AND minimum support.
_CONSENSUS_MIN_FRACTION = 0.60
_CONSENSUS_MIN_FACTS = 2
_DISAGREEMENT_MIN_PER_SIDE = 2


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    NULL = "null"
    UNCLEAR = "unclear"


def classify_direction(phrase: str) -> Direction:
    """Classify a finding's direction of effect from its phrase. Never raises."""
    text = phrase.lower()
    if any(p in text for p in _NULL_PHRASES):
        return Direction.NULL
    words = _WORD.findall(text)
    if not words:
        return Direction.UNCLEAR
    negated = bool(_NEGATORS & set(words))
    up = sum(1 for w in words if w in _UP)
    down = sum(1 for w in words if w in _DOWN)
    if up == down:
        return Direction.UNCLEAR
    direction = Direction.UP if up > down else Direction.DOWN
    if negated:
        # "did not increase" / "no reduction" — a negated effect reads as null.
        return Direction.NULL
    return direction


@dataclass(frozen=True, slots=True)
class ConsensusReport:
    total: int
    by_direction: dict[str, list[str]]  # direction -> [fact_id, ...]
    consensus_direction: str | None
    has_disagreement: bool
    summary: str
    open_question_ids: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "by_direction": self.by_direction,
            "consensus_direction": self.consensus_direction,
            "has_disagreement": self.has_disagreement,
            "open_question_ids": list(self.open_question_ids),
            "summary": self.summary,
        }


def _fact_phrase(fact: Mapping[str, object]) -> str:
    return str(fact.get("canonical_phrase") or fact.get("source_excerpt") or "").strip()


def partition(facts: Sequence[Mapping[str, object]]) -> ConsensusReport:
    """Partition findings into consensus / disagreement / open. Never raises."""
    buckets: dict[str, list[str]] = {d.value: [] for d in Direction}
    for i, fact in enumerate(facts):
        if not isinstance(fact, Mapping):
            continue
        phrase = _fact_phrase(fact)
        if not phrase:
            buckets[Direction.UNCLEAR.value].append(str(fact.get("fact_id") or i))
            continue
        d = classify_direction(phrase)
        buckets[d.value].append(str(fact.get("fact_id") or i))

    total = sum(len(v) for v in buckets.values())
    up, down = len(buckets[Direction.UP.value]), len(buckets[Direction.DOWN.value])
    null = len(buckets[Direction.NULL.value])
    directional = up + down  # NULL/UNCLEAR don't vote on a direction

    consensus_dir: str | None = None
    if directional >= _CONSENSUS_MIN_FACTS:
        lead, lead_n = (Direction.UP.value, up) if up >= down else (Direction.DOWN.value, down)
        if lead_n >= _CONSENSUS_MIN_FACTS and lead_n / directional >= _CONSENSUS_MIN_FRACTION:
            consensus_dir = lead

    has_disagreement = (
        up >= _DISAGREEMENT_MIN_PER_SIDE and down >= _DISAGREEMENT_MIN_PER_SIDE
    )
    open_ids = tuple(
        buckets[Direction.UNCLEAR.value]
        + ([] if directional else buckets[Direction.NULL.value]),
    )
    summary = _summarise(up, down, null, consensus_dir, has_disagreement)
    return ConsensusReport(
        total=total, by_direction=buckets, consensus_direction=consensus_dir,
        has_disagreement=has_disagreement, summary=summary, open_question_ids=open_ids,
    )


def _summarise(
    up: int, down: int, null: int, consensus: str | None, disagree: bool,
) -> str:
    parts = []
    if up:
        parts.append(f"{up} report an increase")
    if down:
        parts.append(f"{down} a decrease")
    if null:
        parts.append(f"{null} null/no-effect")
    body = "; ".join(parts) or "no directional findings"
    if disagree:
        return f"Conflicting evidence — {body}."
    if consensus:
        return f"Consensus ({consensus}) — {body}."
    return f"Inconclusive — {body}."


def render_markdown(report: ConsensusReport) -> str:
    """Compact 'agreement structure' section for an evidence-map memo."""
    if not report.total:
        return ""
    lines = ["### Evidence agreement", "", report.summary]
    if report.has_disagreement:
        lines.append(
            f"- Disagreement: {len(report.by_direction['up'])} increase vs "
            f"{len(report.by_direction['down'])} decrease.",
        )
    if report.open_question_ids:
        lines.append(f"- Open / inconclusive: {len(report.open_question_ids)} finding(s).")
    return "\n".join(lines)
