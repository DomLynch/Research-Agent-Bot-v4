"""Pass-1 deterministic eligibility triage.

Reads a `CandidateStudy` + `ParsedFullText` + topic-pack keyword lists
and emits an `EligibilityTriage` with one of three labels:

  - eligible_likely : every mandatory field is present, no hard excluder fires
  - exclude_likely  : a hard excluder fires (rapalog-only intervention,
                      non-primary design, etc.)
  - unclear         : mandatory evidence is missing but no hard excluder
                      fires; pass to LLM judge for adjudication

The mandatory-fields checklist is the same dict shape the LLM judge will
return in Pass 2, so the merge step in Pass 3 can compare apples to apples.

Universal: every keyword list comes from the topic pack. No biomedical
literal in this file.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from agent.full_text_parse import ParsedFullText
from agent.screening import CandidateStudy
from agent.topic_pack import TopicPack

TriageLabel = Literal["eligible_likely", "exclude_likely", "unclear"]

MANDATORY_KEYS: tuple[str, ...] = (
    "species_match",
    "intervention_match",
    "endpoint_present",
    "control_present",
    "primary_research_design",
)


@dataclass(frozen=True, slots=True)
class EligibilityTriage:
    study_id: str
    label: TriageLabel
    mandatory_fields: Mapping[str, bool]
    reasons: tuple[str, ...]


def _any_term(haystack: str, terms: tuple[str, ...]) -> bool:
    if not terms or not haystack:
        return False
    return any(term.lower() in haystack for term in terms if term)


def triage(
    candidate: CandidateStudy, parsed: ParsedFullText, pack: TopicPack,
) -> EligibilityTriage:
    body = (parsed.text or "").lower()
    title = (candidate.title or "").lower()
    haystack = body + " " + title

    species_ok = _any_term(haystack, pack.preferred_terms)
    intervention_ok = _any_term(haystack, pack.primary_interventions)
    rapalog_only = (
        _any_term(haystack, pack.translational_only_interventions) and not intervention_ok
    )
    endpoint_ok = _any_term(haystack, pack.eligibility_endpoint_terms)
    control_ok = _any_term(haystack, pack.eligibility_control_terms)
    excluded_design = _any_term(haystack, pack.eligibility_exclude_design_terms)
    text_long_enough = len(parsed.text) >= pack.eligibility_min_text_chars

    checklist: dict[str, bool] = {
        "species_match": species_ok,
        "intervention_match": intervention_ok,
        "endpoint_present": endpoint_ok,
        "control_present": control_ok,
        "primary_research_design": not excluded_design,
        "rapalog_only_intervention": rapalog_only,
        "parsed_text_adequate": text_long_enough,
    }
    reasons: list[str] = []

    if parsed.error:
        reasons.append(f"parse error: {parsed.error}")

    if rapalog_only:
        reasons.append(
            "translational-only intervention detected without primary "
            "intervention present"
        )
        return EligibilityTriage(
            study_id=candidate.study_id, label="exclude_likely",
            mandatory_fields=MappingProxyType(checklist), reasons=tuple(reasons),
        )

    if excluded_design:
        reasons.append("text matches review / non-primary design markers")
        return EligibilityTriage(
            study_id=candidate.study_id, label="exclude_likely",
            mandatory_fields=MappingProxyType(checklist), reasons=tuple(reasons),
        )

    all_mandatory = all(checklist[k] for k in MANDATORY_KEYS)
    if all_mandatory and text_long_enough:
        reasons.append("all mandatory fields present in parsed text")
        return EligibilityTriage(
            study_id=candidate.study_id, label="eligible_likely",
            mandatory_fields=MappingProxyType(checklist), reasons=tuple(reasons),
        )

    if not text_long_enough:
        reasons.append("parsed text below minimum length for confident triage")
    missing = [k for k in MANDATORY_KEYS if not checklist[k]]
    if missing:
        reasons.append("mandatory fields missing in parsed text: " + ", ".join(missing))
    return EligibilityTriage(
        study_id=candidate.study_id, label="unclear",
        mandatory_fields=MappingProxyType(checklist), reasons=tuple(reasons),
    )
