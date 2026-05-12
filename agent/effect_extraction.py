"""Sprint 8 - effect-size extraction contract + LLM prompt scaffolding.

Consumes the strict A-core records (primary_effect_input_set_strict.json)
plus parsed full-text bytes, asks the writer LLM to extract pre-specified
numeric fields, and emits ExtractionReceipt records that downstream
effect-size pooling can validate.

Universal: every required field is named by the topic pack, not by this
module. Biomedical packs ask for {n_treatment, n_control, median_lifespan,
hazard_ratio}; climate packs would ask for {delta_temp, scenario_run_n,
baseline_period}; etc. Same dataclass, same parser.

Contract (Sprint 8 extraction gate):
    can_pool_effect = (
        receipt.status == "extracted"
        AND receipt.metric is one of pack.extraction_metrics
        AND receipt.treated_value is not None
        AND receipt.control_value is not None
        AND at least one current-study evidence quote
    )
The contract REFUSES rather than fabricates: a paper whose numeric data
is not extractable lands as status="no_numerics" with a documented
failure reason; pooling skips it.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from agent.topic_pack import TopicPack

ExtractionStatus = Literal[
    "extracted",        # numeric fields present, contract passes
    "no_numerics",      # text parsed but no extractable numerics for this metric
    "parse_failed",     # could not read paper bytes
    "llm_refused",      # writer LLM emitted a refusal marker
]


@dataclass(frozen=True, slots=True)
class ExtractionReceipt:
    """One paper's extraction result. Topic-agnostic shape."""

    study_id: str
    status: ExtractionStatus
    metric: str                       # e.g. "median_lifespan_days"
    treated_value: float | None
    control_value: float | None
    treated_n: int | None
    control_n: int | None
    hazard_ratio: float | None
    hazard_ratio_ci_low: float | None
    hazard_ratio_ci_high: float | None
    percent_change: float | None
    moderators: Mapping[str, str]
    evidence_quotes: tuple[str, ...]
    failure_reason: str
    reviewer: str
    text_hash: str
    timestamp_utc: str

    @staticmethod
    def freeze_moderators(m: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(m))


def build_extraction_prompt(
    pack: TopicPack, study_id: str, title: str, parsed_text: str, *,
    excerpt_chars: int = 12000,
) -> list[dict[str, str]]:
    """Compose a writer-LLM prompt that pre-specifies the topic-pack's
    extraction fields. Returns OpenAI-style {role, content} messages.

    The pack drives the metric list, the moderator vocabulary, and the
    intervention/control terms used in the evidence-quote requirement.
    No biomedical literals here.
    """
    endpoint = pack.endpoint or "primary endpoint"
    metrics = ", ".join(pack.eligibility_endpoint_terms) or endpoint
    interventions = ", ".join(pack.primary_interventions) or "the intervention"
    controls = ", ".join(pack.eligibility_control_terms) or "the comparator"
    excerpt = parsed_text[:excerpt_chars]
    system = (
        "You extract effect-size data from one research paper. Output ONLY "
        "JSON matching the schema below. Never invent numbers. If a field "
        "is not stated in the excerpt, emit null for that field. If no "
        "numeric effect for the primary metric is available, set status="
        '"no_numerics" with a one-sentence failure_reason.'
    )
    user = (
        f"Paper: {study_id} - {title}\n\n"
        f"Topic: {pack.display_name}. Primary metric vocabulary: {metrics}. "
        f"Primary interventions of interest: {interventions}. "
        f"Control / comparator vocabulary: {controls}.\n\n"
        f"Excerpt (first {excerpt_chars} chars):\n---\n{excerpt}\n---\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "status": "extracted" | "no_numerics" | "llm_refused",\n'
        '  "metric": "<one metric name from the vocabulary>",\n'
        '  "treated_value": number | null,\n'
        '  "control_value": number | null,\n'
        '  "treated_n": integer | null,\n'
        '  "control_n": integer | null,\n'
        '  "hazard_ratio": number | null,\n'
        '  "hazard_ratio_ci_low": number | null,\n'
        '  "hazard_ratio_ci_high": number | null,\n'
        '  "percent_change": number | null,\n'
        '  "moderators": {"sex"|"strain"|"dose": "<value>"} | {},\n'
        '  "evidence_quotes": [\n'
        '     "<verbatim sentence from the excerpt that states the '
        'treatment + control + metric>", ...\n'
        "  ],\n"
        '  "failure_reason": "<one sentence if status != extracted, else empty>"\n'
        "}\n\n"
        "Rules:\n"
        "- Treated group must use one of the primary interventions; control "
        "  must match the control vocabulary. If unclear, status=no_numerics.\n"
        "- Evidence quotes must be VERBATIM from the excerpt, not paraphrased.\n"
        "- Do not output any prose outside the JSON object."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_extraction_response(raw: str) -> dict[str, object]:
    """Find the first balanced JSON object in raw text and parse it.
    Returns the parsed dict or raises ValueError on unparseable output."""
    if not raw or not raw.strip():
        raise ValueError("empty response")
    text = raw.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    match = _JSON_OBJECT_RE.search(text)
    if match is None:
        raise ValueError("no JSON object found in response")
    return json.loads(match.group(0))  # type: ignore[no-any-return]


def receipt_from_response(
    parsed: dict[str, object], *, study_id: str, text_hash: str,
    reviewer: str, timestamp_utc: str,
) -> ExtractionReceipt:
    """Construct an ExtractionReceipt from a parsed-JSON response dict."""
    moderators_raw = parsed.get("moderators") or {}
    if not isinstance(moderators_raw, dict):
        moderators_raw = {}
    quotes = parsed.get("evidence_quotes") or ()
    if not isinstance(quotes, list | tuple):
        quotes = ()
    status_raw = str(parsed.get("status", "no_numerics"))
    if status_raw not in {"extracted", "no_numerics", "llm_refused"}:
        status_raw = "no_numerics"
    return ExtractionReceipt(
        study_id=study_id,
        status=status_raw,  # type: ignore[arg-type]
        metric=str(parsed.get("metric") or ""),
        treated_value=_as_float(parsed.get("treated_value")),
        control_value=_as_float(parsed.get("control_value")),
        treated_n=_as_int(parsed.get("treated_n")),
        control_n=_as_int(parsed.get("control_n")),
        hazard_ratio=_as_float(parsed.get("hazard_ratio")),
        hazard_ratio_ci_low=_as_float(parsed.get("hazard_ratio_ci_low")),
        hazard_ratio_ci_high=_as_float(parsed.get("hazard_ratio_ci_high")),
        percent_change=_as_float(parsed.get("percent_change")),
        moderators=ExtractionReceipt.freeze_moderators(
            {str(k): str(v) for k, v in moderators_raw.items() if v is not None}
        ),
        evidence_quotes=tuple(str(q) for q in quotes if q),
        failure_reason=str(parsed.get("failure_reason") or ""),
        reviewer=reviewer,
        text_hash=text_hash,
        timestamp_utc=timestamp_utc,
    )


def _as_float(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _as_int(v: object) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return None
    return None


@dataclass(frozen=True, slots=True)
class ExtractionContractResult:
    passes: bool
    violations: tuple[str, ...]


def validate_extraction(
    receipt: ExtractionReceipt, pack: TopicPack,
) -> ExtractionContractResult:
    """The Sprint 8 extraction gate. Returns ExtractionContractResult
    (passes=True, violations=()) only when the receipt has enough data
    to feed effect-size pooling.

    Universal: relies on pack.eligibility_endpoint_terms for the metric
    vocabulary. Caller treats failure as "exclude from pool" not "retry".
    """
    if receipt.status != "extracted":
        return ExtractionContractResult(
            passes=False, violations=(f"status={receipt.status}",),
        )
    violations: list[str] = []
    metric_vocab = tuple(pack.eligibility_endpoint_terms)
    if metric_vocab and not any(
        m.casefold() in receipt.metric.casefold() for m in metric_vocab if m
    ):
        violations.append(
            f"metric {receipt.metric!r} is not in topic-pack endpoint vocabulary"
        )
    if receipt.treated_value is None:
        violations.append("treated_value is null")
    if receipt.control_value is None and receipt.hazard_ratio is None:
        violations.append("no control_value and no hazard_ratio (need at least one)")
    if not receipt.evidence_quotes:
        violations.append("no evidence quote tying numerics to the paper")
    return ExtractionContractResult(
        passes=not violations, violations=tuple(violations),
    )
