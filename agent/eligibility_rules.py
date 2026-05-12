"""Pass-1 deterministic eligibility triage.

Scans candidate title + parsed full-text for topic-pack keyword lists and
emits an `EligibilityTriage` label:

  - eligible_likely : every mandatory field present, no hard excluder fires
  - exclude_likely  : hard excluder fires (rapalog-only, non-primary design)
  - unclear         : evidence missing but no excluder; pass to LLM judge

Checklist shape matches what the LLM judge returns, so Pass-3 merge can
compare apples to apples. Universal: keyword lists come from the topic pack.
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


def _build(
    study_id: str, label: TriageLabel, checklist: dict[str, bool],
    reasons: list[str],
) -> EligibilityTriage:
    return EligibilityTriage(
        study_id=study_id, label=label,
        mandatory_fields=MappingProxyType(checklist), reasons=tuple(reasons),
    )


def triage(
    candidate: CandidateStudy, parsed: ParsedFullText, pack: TopicPack,
) -> EligibilityTriage:
    title = (candidate.title or "").lower()
    haystack = (parsed.text or "").lower() + " " + title
    intervention_ok = _any_term(haystack, pack.primary_interventions)
    rapalog_only = (
        _any_term(haystack, pack.translational_only_interventions)
        and not intervention_ok
    )
    # Exclude-design check is TITLE-only. Bodies of primary studies routinely
    # cite reviews / meta-analyses in references and prior-work sections;
    # scanning the full body false-rejects every primary study that mentions
    # a related synthesis. A paper's actual design is named in its title.
    excluded_design = _any_term(title, pack.eligibility_exclude_design_terms)
    text_long_enough = len(parsed.text) >= pack.eligibility_min_text_chars
    checklist: dict[str, bool] = {
        "species_match": _any_term(haystack, pack.preferred_terms),
        "intervention_match": intervention_ok,
        "endpoint_present": _any_term(haystack, pack.eligibility_endpoint_terms),
        "control_present": _any_term(haystack, pack.eligibility_control_terms),
        "primary_research_design": not excluded_design,
        "rapalog_only_intervention": rapalog_only,
        "parsed_text_adequate": text_long_enough,
    }
    reasons: list[str] = []
    if parsed.error:
        reasons.append(f"parse error: {parsed.error}")
    if rapalog_only:
        reasons.append("translational-only intervention without primary intervention")
        return _build(candidate.study_id, "exclude_likely", checklist, reasons)
    if excluded_design:
        reasons.append("text matches review / non-primary design markers")
        return _build(candidate.study_id, "exclude_likely", checklist, reasons)
    if all(checklist[k] for k in MANDATORY_KEYS) and text_long_enough:
        reasons.append("all mandatory fields present in parsed text")
        return _build(candidate.study_id, "eligible_likely", checklist, reasons)
    if not text_long_enough:
        reasons.append("parsed text below minimum length for confident triage")
    missing = [k for k in MANDATORY_KEYS if not checklist[k]]
    if missing:
        reasons.append("mandatory fields missing: " + ", ".join(missing))
    return _build(candidate.study_id, "unclear", checklist, reasons)
