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

# Consensus and disagreement are mutually exclusive: a clear majority (no
# substantial dissent) is consensus; a substantial minority is disagreement.
_CONSENSUS_MIN_FRACTION = 0.60
_CONSENSUS_MIN_FACTS = 2
_DISAGREEMENT_MIN_PER_SIDE = 2
_DISAGREEMENT_MIN_FRACTION = 0.34  # a minority below this is "minor dissent", not a conflict
_NEG_WINDOW = 2  # a negator this many tokens before the effect word negates it


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    NULL = "null"
    UNCLEAR = "unclear"


def _negated_near(words: list[str], direction_set: frozenset[str]) -> bool:
    """True if a negator sits within ``_NEG_WINDOW`` tokens before an effect word.

    Scoped (not whole-phrase) so a distant negator in a different clause —
    'increased mortality; effect not dose-dependent' — does not wrongly null the
    primary finding.
    """
    for i, word in enumerate(words):
        if word in direction_set and _NEGATORS & set(words[max(0, i - _NEG_WINDOW):i]):
            return True
    return False


def classify_direction(phrase: str) -> Direction:
    """Classify a finding's direction of effect from its phrase. Never raises."""
    text = str(phrase).lower()
    if any(p in text for p in _NULL_PHRASES):
        return Direction.NULL
    words = _WORD.findall(text)
    if not words:
        return Direction.UNCLEAR
    up = sum(1 for w in words if w in _UP)
    down = sum(1 for w in words if w in _DOWN)
    if up == down:
        return Direction.UNCLEAR
    winner = _UP if up > down else _DOWN
    if _negated_near(words, winner):
        # "no reduction" / a negated effect verb reads as null.
        return Direction.NULL
    return Direction.UP if up > down else Direction.DOWN


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
    minority = min(up, down)

    # Disagreement first; consensus is then "clear majority with no real dissent",
    # so the two are mutually exclusive and the structured fields never contradict.
    has_disagreement = (
        minority >= _DISAGREEMENT_MIN_PER_SIDE
        and bool(directional)
        and minority / directional >= _DISAGREEMENT_MIN_FRACTION
    )
    consensus_dir: str | None = None
    if not has_disagreement and directional >= _CONSENSUS_MIN_FACTS:
        lead, lead_n = (Direction.UP.value, up) if up >= down else (Direction.DOWN.value, down)
        if lead_n >= _CONSENSUS_MIN_FACTS and lead_n / directional >= _CONSENSUS_MIN_FRACTION:
            consensus_dir = lead
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
