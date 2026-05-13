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
    excerpt_chars: int = 60000,
) -> list[dict[str, str]]:
    """Compose a writer-LLM prompt that pre-specifies the topic-pack's
    extraction fields. Returns OpenAI-style {role, content} messages.

    The pack drives the metric list, the moderator vocabulary, and the
    intervention/control terms used in the evidence-quote requirement.
    The excerpt window is large by default (60k chars) because raw
    numerics live in Results / Tables which typically sit deep in the
    document. No biomedical literals.
    """
    endpoint = pack.endpoint or "primary endpoint"
    metrics = ", ".join(pack.eligibility_endpoint_terms) or endpoint
    interventions = ", ".join(pack.primary_interventions) or "the intervention"
    controls = ", ".join(pack.eligibility_control_terms) or "the comparator"
    preferred_families = ", ".join(pack.preferred_metric_families)
    preference_clause = (
        f" When multiple metric families are reported in the same paper "
        f"(e.g. median lifespan AND 90th-percentile lifespan), PREFER one of "
        f"the families [{preferred_families}] over alternatives so the result "
        f"can be inverse-variance-pooled with other studies in the same "
        f"family. Record the preferred-family metric in the metric field; "
        f"if the preferred family is genuinely not in the paper, fall back "
        f"to whatever the paper reports."
        if preferred_families else ""
    )
    excerpt = parsed_text[:excerpt_chars]
    system = (
        "You extract effect-size data from one research paper. Output ONLY "
        "JSON matching the schema below. Never invent numbers. If a field "
        "is not stated in the excerpt, emit null for that field. If no "
        "numeric effect for the primary metric is available, set status="
        '"no_numerics" with a one-sentence failure_reason. Look hard at '
        "Results, Methods, and Tables sections; raw values usually live "
        "there, not in the abstract."
        + preference_clause
        + " Sample-size recovery is critical for inverse-variance pooling: "
        "scan the Methods, Table 1 (cohort table), figure legends, and "
        "survival-analysis sections for treated_n and control_n. Only "
        "leave these null when the paper genuinely does not report them; "
        "do not skip a manual scan."
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
        "- treated_value and control_value must be in the SAME unit (e.g. "
        "  both in days, or both in months). Convert to days if the paper "
        "  reports months/weeks; record the original unit's name in the "
        "  metric field (e.g. metric=\"median_lifespan_days\"). When you "
        "  report a numeric effect, also fill treated_n and control_n if "
        "  the excerpt states them (Methods, Table 1, figure captions); "
        "  otherwise leave null without padding the prompt.\n"
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


# --- Sprint 12.9 Task C: dual-pass extraction with LLM-adjudicated --------
# disagreements. Two independent extraction passes (a primary + a strict-
# verify variant) run on the same parsed text. A receipt comparator then
# checks the pool-critical fields; if they disagree, an adjudicator LLM
# call picks the right answer with explicit evidence-quote justification.
# Net effect: rescues parse_failed / no_numerics cases (one pass misses,
# the other catches), and lets Methods honestly claim "dual independent
# extraction" — the audit panel asked for this in 12.8 review.
#
# Universal: every helper below reads only pack vocabulary + receipt
# fields; no biomedical literals.

# Fields that affect pooling. Disagreement on any of these fires the
# adjudicator call. Non-pool fields (failure_reason, moderators) are
# allowed to diverge between passes without invoking adjudication.
_POOL_FIELDS: tuple[str, ...] = (
    "status", "metric",
    "treated_value", "control_value",
    "treated_n", "control_n",
    "hazard_ratio", "hazard_ratio_ci_low", "hazard_ratio_ci_high",
    "percent_change",
)
# Numeric-field disagreement tolerance: receipts that differ by <2%
# count as agreement (rounding / unit-conversion noise).
_NUMERIC_TOLERANCE_PCT: float = 2.0


def build_extraction_prompt_strict_verify(
    pack: TopicPack, study_id: str, title: str, parsed_text: str, *,
    excerpt_chars: int = 60000,
) -> list[dict[str, str]]:
    """Pass-B prompt: strict-verify variant. Same schema as Pass-A; the
    system message tightens discipline so the model rejects any numeric
    it can't tie to a verbatim sentence. Genuine numerics survive both
    passes; LLM-imagined ones surface as disagreement for the
    adjudicator. Universal — reads only pack vocabulary."""
    base = build_extraction_prompt(
        pack, study_id, title, parsed_text, excerpt_chars=excerpt_chars,
    )
    suffix = (
        "\n\nSTRICT-VERIFY MODE (second independent extraction cross-"
        "checking the first). Every numeric you emit MUST be tied to "
        "one verbatim sentence in the excerpt. If the paper forces an "
        "estimate, average, unit conversion, or graph inference, emit "
        "null. Sample-size (treated_n, control_n) must be read off the "
        "page, not derived. evidence_quotes MUST include one verbatim "
        "sentence per non-null numeric."
    )
    return [
        {"role": "system", "content": base[0]["content"] + suffix},
        base[1],
    ]


def _close_enough(
    a: float | int | None, b: float | int | None,
) -> bool:
    """Numeric agreement within `_NUMERIC_TOLERANCE_PCT`; two nulls
    agree, null vs number disagree."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    a_f, b_f = float(a), float(b)
    avg = (abs(a_f) + abs(b_f)) / 2.0
    return a_f == b_f if avg == 0.0 else abs(a_f - b_f) / avg * 100.0 <= _NUMERIC_TOLERANCE_PCT


def compare_receipts(
    r1: ExtractionReceipt, r2: ExtractionReceipt,
) -> tuple[str, ...]:
    """Pool-critical fields that disagree between two passes. Empty
    tuple == agreement. Numerics use `_NUMERIC_TOLERANCE_PCT` noise."""
    out: list[str] = []
    for f in _POOL_FIELDS:
        v1, v2 = getattr(r1, f, None), getattr(r2, f, None)
        if f in {"status", "metric"}:
            if str(v1 or "").strip().casefold() != str(v2 or "").strip().casefold():
                out.append(f)
        elif not _close_enough(v1, v2):
            out.append(f)
    return tuple(out)


def _avg2(a: float | int | None, b: float | int | None) -> float | None:
    """Average two optional numerics; coalesce when one side is None."""
    if a is None and b is None:
        return None
    if a is None:
        return float(b) if b is not None else None
    if b is None:
        return float(a)
    return (float(a) + float(b)) / 2.0


def merge_agreed_receipts(
    r1: ExtractionReceipt, r2: ExtractionReceipt, *, reviewer: str,
) -> ExtractionReceipt:
    """Merge two extraction passes that agree on pool-critical fields.
    Numerics averaged when both non-null; evidence quotes unioned
    (dedup by casefold)."""
    seen: set[str] = set()
    quotes_union: list[str] = []
    for q in (*r1.evidence_quotes, *r2.evidence_quotes):
        key = q.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            quotes_union.append(q)
    n_t = _avg2(r1.treated_n, r2.treated_n)
    n_c = _avg2(r1.control_n, r2.control_n)
    return ExtractionReceipt(
        study_id=r1.study_id, status=r1.status,
        metric=r1.metric or r2.metric,
        treated_value=_avg2(r1.treated_value, r2.treated_value),
        control_value=_avg2(r1.control_value, r2.control_value),
        treated_n=round(n_t) if n_t is not None else None,
        control_n=round(n_c) if n_c is not None else None,
        hazard_ratio=_avg2(r1.hazard_ratio, r2.hazard_ratio),
        hazard_ratio_ci_low=_avg2(r1.hazard_ratio_ci_low, r2.hazard_ratio_ci_low),
        hazard_ratio_ci_high=_avg2(r1.hazard_ratio_ci_high, r2.hazard_ratio_ci_high),
        percent_change=_avg2(r1.percent_change, r2.percent_change),
        moderators=r1.moderators or r2.moderators,
        evidence_quotes=tuple(quotes_union),
        failure_reason=r1.failure_reason or r2.failure_reason,
        reviewer=reviewer,
        text_hash=r1.text_hash, timestamp_utc=r1.timestamp_utc,
    )


def build_adjudicator_prompt(
    r1: ExtractionReceipt, r2: ExtractionReceipt,
    disagreements: tuple[str, ...], parsed_text: str, *,
    excerpt_chars: int = 60000,
) -> list[dict[str, str]]:
    """Adjudicator prompt for pool-critical disagreements between two
    extraction passes. May pick A's value, B's value, or null — may NOT
    invent a number not in either pass. Universal: reads only field
    names + parsed text; no biomedical literals."""
    excerpt = parsed_text[:excerpt_chars]
    pool_a = {f: getattr(r1, f, None) for f in _POOL_FIELDS}
    pool_b = {f: getattr(r2, f, None) for f in _POOL_FIELDS}
    disagree_lines = "\n".join(
        f"  - {f}: pass-A={pool_a[f]!r} vs pass-B={pool_b[f]!r}"
        for f in disagreements
    )
    system = (
        "You are an extraction adjudicator. Two prior LLM extractions of "
        "the same paper disagreed on one or more pool-critical fields. "
        "Resolve each disagreement by pointing at the verbatim sentence "
        "in the excerpt that supports the correct value. You MAY pick "
        "pass-A's value, pass-B's value, or null (if neither is supported "
        "by an explicit statement). You MAY NOT invent a number that is "
        "not in either pass. Output ONLY the merged JSON receipt — same "
        "schema as the primary extraction."
    )
    user = (
        f"Paper: {r1.study_id}\n\n"
        f"Pass-A receipt (permissive):\n{json.dumps(pool_a)}\n\n"
        f"Pass-B receipt (strict-verify):\n{json.dumps(pool_b)}\n\n"
        f"Disagreements on pool-critical fields:\n{disagree_lines}\n\n"
        f"Excerpt (first {excerpt_chars} chars):\n---\n{excerpt}\n---\n\n"
        "Emit a single merged JSON receipt (same schema as the primary "
        "extraction). For each disagreed field, pick the value supported "
        "by a verbatim sentence in the excerpt (or null) and include "
        "that sentence in evidence_quotes."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


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
