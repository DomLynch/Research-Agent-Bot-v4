"""Pass-2 LLM eligibility judge.

LLM proposes; deterministic merge (eligibility_merge.py) disposes. The
judge call returns strict JSON with decision, confidence in [0,1],
reasons, evidence_quotes, and a mandatory-fields checklist matching
agent.eligibility_rules.MANDATORY_KEYS.

Model: Gemma 4 31B via OpenRouter (settings.judge_model). The two-model
stack is non-negotiable (AGENTS.md): MiMo writer + Gemma judge. Do not
introduce a separate eligibility-judge model override without explicit
prior approval - per-call escalation to frontier models is a paid
external side effect and a deviation from the documented architecture.

Fail-soft: HTTP / JSON / refusal errors return a proposal with
decision='unclear', confidence=0.0, parse_error filled.
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
    "outside the JSON. Quote verbatim from the paper text only - never "
    "paraphrase a quote.\n\n"
    "READING DISCIPLINE - decide each mandatory field based on the ACTUAL "
    "STUDY SYSTEM (what was experimentally treated, measured, or reported), "
    "NOT framing words in the introduction. Papers routinely open with "
    "broad contextual phrases ('mammalian aging', 'vertebrate models', "
    "'cellular pathways in eukaryotes') before disclosing their actual "
    "experimental subject in later sentences or the title. Use the title "
    "and the Methods/Results passages, not just the first paragraph of the "
    "abstract. If the title or any concrete sentence names the criterion "
    "term (e.g. 'mice', 'rapamycin', 'lifespan'), set the corresponding "
    "field to true even if introduction sentences use broader category "
    "words. Only set decision='unclear' with low confidence when the "
    "ACTUAL study system is genuinely ambiguous in the parsed text."
)

# Variant B prompt: paragraph-first reasoning, then JSON.
# Used by judge_eligibility_with_variance() to cross-check Variant A.
_SYSTEM_PROMPT_REASONING_FIRST = (
    "You are a strict systematic-review eligibility judge. Write ONE "
    "concise paragraph (max 6 sentences) explaining whether the paper "
    "meets the criteria, anchored to the title and the Methods/Results "
    "passages. Then output a JSON object on the line after the paragraph, "
    "matching the schema the user provides. Use the title and concrete "
    "experimental sentences to determine each field - do not be misled "
    "by broad framing words ('mammalian', 'vertebrate', 'eukaryotic') "
    "that appear before the actual study system is named."
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
    """Find a JSON object inside the response. Robust to:
      - bare JSON ({"...": ...})
      - code-fenced JSON (```json ... ```)
      - paragraph-then-JSON (reasoning-first variant emits prose then {...})
    Scans for the first balanced { ... } pair after fence stripping.
    """
    stripped = _strip_fence(raw)
    try:
        obj = json.loads(stripped)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(stripped[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(stripped[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


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


def _call_with_prompt(
    candidate: CandidateStudy, parsed: ParsedFullText, triage: EligibilityTriage,
    pack: TopicPack, settings: Settings, *, system_prompt: str,
) -> EligibilityProposal:
    model = settings.judge_model
    if not parsed.text.strip():
        return _empty(candidate.study_id, model, "", "parsed text empty")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_prompt(candidate, parsed, triage, pack)},
    ]
    try:
        resp = call_judge(settings, messages, temperature=0.0)
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


def judge_eligibility(
    candidate: CandidateStudy, parsed: ParsedFullText,
    triage: EligibilityTriage, pack: TopicPack, settings: Settings,
) -> EligibilityProposal:
    """Single Gemma 4 31B call via OpenRouter; fail-soft to decision='unclear'.

    Model is fixed to settings.judge_model (Gemma) - the documented
    2-model stack from AGENTS.md. No per-call model override.
    """
    return _call_with_prompt(
        candidate, parsed, triage, pack, settings,
        system_prompt=_SYSTEM_PROMPT,
    )


def judge_eligibility_with_variance(
    candidate: CandidateStudy, parsed: ParsedFullText,
    triage: EligibilityTriage, pack: TopicPack, settings: Settings,
) -> EligibilityProposal:
    """Two Gemma calls with different prompt phrasings; consensus or
    'unclear' on disagreement. Catches prompt-phrasing sensitivity that
    a single roll can hide. Doubles LLM cost per candidate."""
    a = _call_with_prompt(
        candidate, parsed, triage, pack, settings,
        system_prompt=_SYSTEM_PROMPT,
    )
    b = _call_with_prompt(
        candidate, parsed, triage, pack, settings,
        system_prompt=_SYSTEM_PROMPT_REASONING_FIRST,
    )
    if a.decision == b.decision:
        # Agreement: return the higher-confidence proposal so the merge
        # step sees the strongest signal.
        return a if a.confidence >= b.confidence else b
    # Disagreement: downgrade to unclear with a reason that explains the split.
    reasons = (
        f"variance check: variant A said {a.decision} (conf {a.confidence:.2f}); "
        f"variant B said {b.decision} (conf {b.confidence:.2f})",
    )
    return EligibilityProposal(
        study_id=candidate.study_id, decision="unclear", confidence=0.0,
        reasons=reasons, evidence_quotes=a.evidence_quotes or b.evidence_quotes,
        eligibility_fields=MappingProxyType({}), model=a.model,
        raw_response=(a.raw_response + "\n---variant-B---\n" + b.raw_response),
        parse_error="variance disagreement",
    )
