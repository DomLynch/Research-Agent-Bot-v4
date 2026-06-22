"""A/B/C/D fact-lane classifier for alpha memo evidence binding."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from agent.numeric_role_classifier import (
    classify_numeric_role,
    is_real_finding,
)
from agent.topic_synonyms import expand_topic_queries, phrase_in_text

LANES = ("A_core", "B_context", "C_noise", "D_bad_extraction")
_NORM_PUNCT = re.compile(r"[\W_]+")
_MIN_SPECIFIC_HEAD_CHARS = 8
_BACKGROUND_CUES = ("added to", "add on to", "add-on to", "background", "receiving", "on")
TopicType = Literal["intervention", "exposure", "disease_or_condition", "biomarker", "broad_risk_factor"]
_POPULATION_CONTEXT_ONLY: frozenset[TopicType] = frozenset({
    "disease_or_condition", "broad_risk_factor",
})


def _norm(s: str) -> str:
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
        str(fact.get("metric") or ""),
        str(fact.get("benchmark") or ""),
        str(fact.get("task") or ""),
        str(fact.get("model_system") or ""),
        str(fact.get("baseline_comparator") or ""),
        str(fact.get("source_topic") or ""),
    ]).lower()


def _topic_keywords(topic: str) -> list[str]:
    seen: dict[str, None] = {}
    for kw in expand_topic_queries(topic, max_queries=64):
        normed = _norm(kw)
        if normed:
            seen.setdefault(normed, None)
    head = _norm(topic).split()[:1]
    if head and len(head[0]) >= _MIN_SPECIFIC_HEAD_CHARS:
        seen.setdefault(head[0], None)
    return list(seen)


def _background_topic_match(text: str, keywords: list[str]) -> bool:
    norm = _norm(text)
    if not norm:
        return False
    for kw in keywords:
        if not kw or not phrase_in_text(kw, norm):
            continue
        pattern = re.escape(kw).replace(r"\ ", r"\s+")
        if re.search(rf"\b(?:non|without|no)\s+{pattern}\b", norm):
            return True
        for cue in _BACKGROUND_CUES:
            cue_pattern = re.escape(cue).replace(r"\ ", r"\s+")
            if re.search(rf"\b{cue_pattern}\s+{pattern}\b", norm):
                return True
    return False


def _topic_type(topic: str) -> TopicType:
    tokens = set(_norm(topic).split())
    if {"risk", "factor"} <= tokens or {"risk", "factors"} <= tokens:
        return "broad_risk_factor"
    if tokens & {"disease", "condition", "disorder", "syndrome"}:
        return "disease_or_condition"
    if tokens & {"biomarker", "marker"}:
        return "biomarker"
    if "exposure" in tokens:
        return "exposure"
    return "intervention"


def classify_lane(fact: dict[str, Any], topic: str) -> LaneVerdict:
    """Single-fact lane classification."""
    fact_id = str(fact.get("fact_id") or "")
    phrase = str(fact.get("canonical_phrase") or "")
    nv = fact.get("numeric_value")
    nv_f: float | None = float(nv) if isinstance(nv, (int, float)) else None
    units = str(fact.get("units") or "")
    role = classify_numeric_role(nv_f, units, phrase)

    if not _has_field(fact, "population") and not _has_field(fact, "intervention"):
        return LaneVerdict(
            fact_id=fact_id, lane="D_bad_extraction",
            numeric_role=role, reason="missing_population_and_intervention",
        )

    keywords = _topic_keywords(topic)
    haystack = _norm(_topic_haystack(fact))
    if not any(phrase_in_text(kw, haystack) for kw in keywords if kw):
        return LaneVerdict(
            fact_id=fact_id, lane="C_noise",
            numeric_role=role,
            reason="topic_word_absent_from_pico_fields",
        )

    real = is_real_finding(role)
    intervention_norm = _norm(str(fact.get("intervention") or ""))
    population_norm = _norm(str(fact.get("population") or ""))
    topic_in_intervention = any(phrase_in_text(kw, intervention_norm) for kw in keywords if kw)
    topic_in_population = any(phrase_in_text(kw, population_norm) for kw in keywords if kw)
    background_intervention = _background_topic_match(intervention_norm, keywords)
    background_population = (
        not topic_in_intervention and _background_topic_match(population_norm, keywords)
    )
    if real and (background_intervention or background_population):
        return LaneVerdict(
            fact_id=fact_id, lane="B_context",
            numeric_role=role, reason="topic_in_background_context",
        )
    if real and (topic_in_intervention or (
        topic_in_population and _topic_type(topic) not in _POPULATION_CONTEXT_ONLY
    )):
        return LaneVerdict(
            fact_id=fact_id, lane="A_core",
            numeric_role=role,
            reason=("topic_in_intervention_pico_complete"
                    if topic_in_intervention
                    else "topic_in_population_pico_complete"),
        )
    if real and topic_in_population:
        return LaneVerdict(
            fact_id=fact_id, lane="B_context",
            numeric_role=role, reason="topic_in_population_context_only",
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
