"""Sprint 59 (Evidence Opportunities Gate) — A/B/C/D lane classifier.

Demotes facts where the numeric role isn't a real finding (regimen,
timepoint, dose) or the PICO is incomplete; promotes facts where
intervention, population, and effect-shaped numeric all align with
the topic. Universal: rules use fact structural fields + topic-word
co-occurrence + numeric role; no biomedical domain literals.

Lanes:
  A_core           — topic in intervention + clean PICO + real numeric effect
  B_context        — topic matched + clean PICO, but either topic only in the
                     phrase OR no clean numeric effect (qualitative finding /
                     methodological number); usable as mechanism / context
                     support, never the lead
  C_noise          — topic word absent from every structural field
  D_bad_extraction — missing population/intervention (incomplete PICO)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.numeric_role_classifier import (
    classify_numeric_role,
    is_real_finding,
)
from agent.topic_synonyms import expand_topic_queries, phrase_in_text

LANES = ("A_core", "B_context", "C_noise", "D_bad_extraction")
_NORM_PUNCT = re.compile(r"[\W_]+")


def _norm(s: str) -> str:
    """Universal text normalisation: collapse underscores + punctuation
    to single spaces, lowercase. Makes 'carbon_tax' match 'carbon tax'
    in both directions."""
    return _NORM_PUNCT.sub(" ", s.lower()).strip()


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

    # Sprint 62: class queries (senolytic) match instance words
    # (dasatinib, quercetin). expand_topic_keywords always includes
    # the topic itself first, so behavior is unchanged for unregistered
    # topics.
    keywords = [_norm(kw) for kw in expand_topic_queries(topic, max_queries=64)]
    haystack = _norm(_topic_haystack(fact))
    if not any(phrase_in_text(kw, haystack) for kw in keywords if kw):
        return LaneVerdict(
            fact_id=fact_id, lane="C_noise",
            numeric_role=role,
            reason="topic_word_absent_from_pico_fields",
        )

    # A_core is the quantitative LEAD: topic in intervention + clean PICO +
    # a real numeric effect. Anything else that is PICO-complete and topic-
    # matched binds as B_context (mechanism / qualitative / context support),
    # rather than being discarded — a numeric_role that is not an effect
    # (or absent) only blocks the lead, it does not make the fact unusable.
    real = is_real_finding(role)
    intervention_norm = _norm(str(fact.get("intervention") or ""))
    if real and any(phrase_in_text(kw, intervention_norm) for kw in keywords if kw):
        return LaneVerdict(
            fact_id=fact_id, lane="A_core",
            numeric_role=role,
            reason="topic_in_intervention_pico_complete",
        )
    return LaneVerdict(
        fact_id=fact_id, lane="B_context",
        numeric_role=role,
        reason=("topic_in_phrase_but_not_intervention" if real
                else "topic_matched_no_clean_numeric_effect"),
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
