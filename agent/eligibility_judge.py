"""Pass-2 LLM eligibility judge.

LLM proposes; deterministic merge (eligibility_merge.py) disposes. The
judge call returns strict JSON with decision, confidence in [0,1],
reasons, evidence_quotes, and a mandatory-fields checklist matching
agent.eligibility_rules.MANDATORY_KEYS.

Model routing: settings.eligibility_judge_model (e.g. an Opus- or
GPT-class OpenRouter id) takes precedence; falls back to
settings.judge_model. Fail-soft: HTTP / JSON / refusal errors return a
proposal with decision='unclear', confidence=0.0, parse_error filled.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from agent.eligibility_rules import MANDATORY_KEYS, EligibilityTriage
from agent.full_text_parse import ParsedFullText
from agent.llm_client import call_judge
from agent.screening import CandidateStudy
from agent.settings import Settings
from agent.topic_pack import TopicPack

JudgeDecision = Literal["include", "exclude", "unclear"]
_EVIDENCE_CHARS = 12_000
_EXTRA_FIELDS: tuple[str, ...] = (
    "rapalog_only_intervention",
    "combination_only_no_isolated_arm",
)
_SYSTEM_PROMPT = (
    "You are a strict systematic-review eligibility judge. You ALWAYS return "
    "valid JSON matching the schema given by the user. You NEVER add prose "
    "outside the JSON. If evidence is missing or ambiguous, return "
    "decision='unclear' with low confidence. Quote verbatim from the paper "
    "text only - never paraphrase a quote."
)


@dataclass(frozen=True, slots=True)
class EligibilityProposal:
    study_id: str
    decision: JudgeDecision
    confidence: float
    reasons: tuple[str, ...]
    evidence_quotes: tuple[str, ...]
    eligibility_fields: Mapping[str, bool]
    model: str
    raw_response: str
    parse_error: str = ""


def _build_user_prompt(
    candidate: CandidateStudy, parsed: ParsedFullText,
    triage: EligibilityTriage, pack: TopicPack,
) -> str:
    schema = ",\n".join(
        f'    "{k}": <bool>' for k in tuple(MANDATORY_KEYS) + _EXTRA_FIELDS
    )
    return (
        f"Eligibility criteria for topic '{pack.display_name}':\n"
        f"  species: {', '.join(pack.preferred_terms)}\n"
        f"  primary intervention: {', '.join(pack.primary_interventions)}\n"
        f"  translational-only (NOT primary): {', '.join(pack.translational_only_interventions)}\n"
        f"  endpoint keywords: {', '.join(pack.eligibility_endpoint_terms)}\n"
        f"  comparator keywords: {', '.join(pack.eligibility_control_terms)}\n"
        f"  excluded designs: {', '.join(pack.eligibility_exclude_design_terms)}\n\n"
        f"Pass-1 triage: {triage.label}\n"
        f"Pass-1 fields: {json.dumps(dict(triage.mandatory_fields), sort_keys=True)}\n"
        f"Pass-1 reasons: {'; '.join(triage.reasons) or '(none)'}\n\n"
        f"Title: {candidate.title}\n"
        f"DOI: {candidate.doi or '(missing)'}  PMID: {candidate.pmid or '(missing)'}\n\n"
        f"Excerpt (first {_EVIDENCE_CHARS} chars):\n---\n{parsed.text[:_EVIDENCE_CHARS]}\n---\n\n"
        "Return JSON ONLY:\n{\n"
        '  "decision": "include" | "exclude" | "unclear",\n'
        '  "confidence": <float 0..1>,\n'
        '  "reasons": [<short strings>],\n'
        '  "evidence_quotes": [<verbatim quotes>],\n'
        f'  "eligibility_fields": {{\n{schema}\n  }}\n}}\n'
    )


def _empty(study_id: str, model: str, raw: str, err: str) -> EligibilityProposal:
    return EligibilityProposal(
        study_id=study_id, decision="unclear", confidence=0.0,
        reasons=("judge proposal unavailable",), evidence_quotes=(),
        eligibility_fields=MappingProxyType({}), model=model,
        raw_response=raw, parse_error=err,
    )


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = s.split("\n", 1)[1] if "\n" in s else s
    return s[:-3].strip() if s.endswith("```") else s.strip()


def _parse_json(raw: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(_strip_fence(raw))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _normalise(obj: dict[str, Any]) -> tuple[
    JudgeDecision, float, tuple[str, ...], tuple[str, ...], dict[str, bool]
]:
    d = str(obj.get("decision", "unclear")).lower()
    decision: JudgeDecision = (
        d if d in {"include", "exclude", "unclear"} else "unclear"  # type: ignore[assignment]
    )
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    reasons = tuple(
        str(r) for r in (obj.get("reasons") or [])
        if isinstance(r, (str, int, float))
    )
    quotes = tuple(
        str(q) for q in (obj.get("evidence_quotes") or []) if isinstance(q, str)
    )
    fr = obj.get("eligibility_fields") or {}
    fields = {str(k): bool(v) for k, v in fr.items()} if isinstance(fr, dict) else {}
    return decision, conf, reasons, quotes, fields


def judge_eligibility(
    candidate: CandidateStudy, parsed: ParsedFullText,
    triage: EligibilityTriage, pack: TopicPack, settings: Settings,
) -> EligibilityProposal:
    """Single LLM call; fail-soft to decision='unclear'."""
    model = settings.eligibility_judge_model or settings.judge_model
    if not parsed.text.strip():
        return _empty(candidate.study_id, model, "", "parsed text empty")
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(candidate, parsed, triage, pack)},
    ]
    try:
        resp = call_judge(
            settings, messages, temperature=0.0,
            model_override=settings.eligibility_judge_model,
        )
    except Exception as e:
        return _empty(candidate.study_id, model, "", f"llm call failed: {e.__class__.__name__}")
    obj = _parse_json(resp.content)
    if obj is None:
        return _empty(candidate.study_id, resp.model, resp.content, "json parse failed")
    decision, conf, reasons, quotes, fields = _normalise(obj)
    return EligibilityProposal(
        study_id=candidate.study_id, decision=decision, confidence=conf,
        reasons=reasons, evidence_quotes=quotes,
        eligibility_fields=MappingProxyType(fields), model=resp.model,
        raw_response=resp.content,
    )
