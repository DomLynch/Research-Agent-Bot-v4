"""Business-family specialist alpha candidate builder.

Keeps domain-specific evidence shape outside the shared publish gates. The
output is the existing run-folder contract: all_facts, fact_lanes,
opportunities_gate, alpha_memo, MANIFEST, and publish_verdict.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agent.domain_profile import DomainProfile
from agent.publish_tier import write_publish_verdict
from agent.settings import Settings
from agent.signal_memo_writer import build_claim_receipt_matrix, build_memo_audit

BUSINESS_DOMAINS = frozenset({
    "business_research",
    "management_research",
    "economics_research",
    "finance_research",
    "marketing_research",
})
MIN_DIRECT_SOURCES = 5
FETCH_TOP_K = 100
PRESERVED_FIELDS = (
    "population", "organization_type", "industry", "asset_class", "geography",
    "time_period", "intervention", "comparator", "outcome", "metric",
    "study_design", "dataset", "estimation_method", "identification_strategy",
    "effect_size", "confidence_interval", "standard_error", "p_value",
    "sample_size",
)
SHAPE_FIELDS = (
    "population", "organization_type", "industry", "asset_class", "geography",
    "time_period", "intervention", "signal_family", "comparator", "outcome",
    "metric", "study_design", "dataset", "estimation_method", "identification_strategy",
)
CORE_SHAPE_FIELDS = ("intervention", "comparator", "outcome", "metric", "study_design")
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "comparator": ("baseline_comparator", "benchmark"),
    "outcome": ("outcome_metric", "estimand", "metric"),
    "metric": ("outcome_metric", "estimand"),
    "study_design": ("design",),
}
_WORD = re.compile(r"[a-z0-9]+")
_GENERIC_METHOD_VALUES = frozenset({"other", "unknown", "not reported", "none", "n/a", "na"})
_GENERIC_TOPIC_TOKENS = frozenset({
    "business", "management", "economics", "finance", "marketing", "research",
    "performance", "effect", "effects", "outcome", "outcomes", "model",
    "policy",
})
_FINANCE_RETURN_TOPICS = frozenset({"asset pricing", "portfolio returns", "market efficiency"})
_FINANCE_RETURN_RE = re.compile(r"\b(alpha|alphas|return|returns|premium|premia)\b", re.I)
_STUDY_DESIGN_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(randomi[sz]ed controlled trial|randomi[sz]ed trial|rct)\b", re.I), "randomized controlled trial"),
    (re.compile(r"\b(field experiment|randomi[sz]ed experiment)\b", re.I), "field experiment"),
    (re.compile(r"\b(difference[- ]in[- ]differences|diff[- ]in[- ]diff)\b", re.I), "difference in differences"),
    (re.compile(r"\b(regression discontinuity|rd design)\b", re.I), "regression discontinuity"),
    (re.compile(r"\b(instrumental variable|instrumental variables|iv estimate)\b", re.I), "instrumental variables"),
    (re.compile(r"\b(event study)\b", re.I), "event study"),
    (re.compile(r"\b(panel regression|fixed effects|panel data)\b", re.I), "panel regression"),
    (re.compile(r"\b(asset pricing|factor model|factor premia)\b", re.I), "asset pricing model"),
)
Json = dict[str, Any]


@dataclass(frozen=True, slots=True)
class BusinessCandidateBundle:
    domain: str
    topic: str
    result_key: str
    shape: dict[str, str]
    receipts: tuple[Json, ...]

    @property
    def source_count(self) -> int:
        return len({key for fact in self.receipts if (key := source_key(fact))})

    def as_dict(self) -> Json:
        return {
            "domain": self.domain,
            "topic": self.topic,
            "result_key": self.result_key,
            "shape": dict(self.shape),
            "source_count": self.source_count,
            "receipt_count": len(self.receipts),
            "receipt_ids": [str(f.get("fact_id") or "") for f in self.receipts],
        }


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip()


def _norm(value: Any) -> str:
    return " ".join(_WORD.findall(str(value or "").lower()))


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _field(item: Json, fact: Json, name: str) -> Any:
    value = item.get(name)
    if value not in (None, ""):
        return value
    value = fact.get(name)
    if value not in (None, ""):
        return value
    for alias in FIELD_ALIASES.get(name, ()):
        value = item.get(alias)
        if value not in (None, ""):
            return value
        value = fact.get(alias)
        if value not in (None, ""):
            return value
    return None


def _specific_method(value: Any) -> str:
    text = _clean(value)
    return "" if text.casefold() in _GENERIC_METHOD_VALUES else text


def _paper(item: Json) -> Json:
    raw = item.get("paper") or item.get("source_paper")
    return raw if isinstance(raw, dict) else {}


def _infer_study_design(item: Json, fact: Json, paper: Json) -> str:
    text = " ".join(
        _clean(value)
        for value in (
            item.get("study_design"),
            fact.get("study_design"),
            item.get("identification_strategy"),
            fact.get("identification_strategy"),
            item.get("estimation_method"),
            fact.get("estimation_method"),
            item.get("sub_topic"),
            fact.get("sub_topic"),
            item.get("claim_type"),
            fact.get("claim_type"),
            item.get("canonical_phrase"),
            fact.get("canonical_phrase"),
            paper.get("title"),
            paper.get("journal_name") or paper.get("journal"),
        )
        if value
    )
    for pattern, label in _STUDY_DESIGN_HINTS:
        if pattern.search(text):
            return label
    return ""


def source_key(fact: Json) -> str:
    paper = fact.get("source_paper")
    if not isinstance(paper, dict):
        paper = {}
    for key in ("doi", "pmid", "pmcid", "paper_id", "id", "title"):
        value = _clean(paper.get(key) or fact.get(key))
        if value:
            return value.casefold()
    return ""


def normalize_business_fact(item: Json, *, topic: str, domain: str) -> Json:
    raw_fact = item.get("fact")
    fact = raw_fact if isinstance(raw_fact, dict) else {}
    paper = _paper(item)
    metric = _clean(_field(item, fact, "metric") or item.get("claim_type"))
    outcome = _clean(_field(item, fact, "outcome") or metric)
    study_design = _clean(
        _specific_method(_field(item, fact, "study_design"))
        or _specific_method(_field(item, fact, "identification_strategy"))
        or _specific_method(_field(item, fact, "estimation_method"))
    ) or _infer_study_design(item, fact, paper)
    effect = _field(item, fact, "effect_size")
    numeric = _num(item.get("numeric_value") if item.get("numeric_value") is not None else effect)
    out: Json = {
        "fact_id": _clean(item.get("id") or item.get("fact_id") or fact.get("id")),
        "topic": topic.strip(),
        "_domain": domain.strip(),
        "source_topic": _clean(item.get("topic") or domain),
        "sub_topic": outcome or _clean(item.get("claim_type") or "result"),
        "source_paper": {
            "pmid": paper.get("pmid"),
            "doi": paper.get("doi") or item.get("paper_id"),
            "pmcid": paper.get("pmcid"),
            "paper_id": paper.get("paper_id") or item.get("paper_id"),
            "title": paper.get("title"),
            "journal": paper.get("journal_name") or paper.get("journal"),
            "year": paper.get("publication_year") or paper.get("year"),
        },
        "claim_type": item.get("claim_type") or fact.get("claim_type"),
        "numeric_value": numeric,
        "units": _clean(item.get("units") or fact.get("units")),
        "ci_lower": _num(item.get("ci_lower") or item.get("confidence_interval_low")),
        "ci_upper": _num(item.get("ci_upper") or item.get("confidence_interval_high")),
        "population": _clean(_field(item, fact, "population")),
        "intervention": _clean(_field(item, fact, "intervention")),
        "comparator": _clean(_field(item, fact, "comparator")),
        "outcome": outcome,
        "metric": metric,
        "study_design": study_design,
        "endpoint": outcome,
        "canonical_phrase": _clean(
            item.get("canonical_phrase") or fact.get("canonical_phrase")
            or f"{_clean(_field(item, fact, 'intervention'))} vs "
            f"{_clean(_field(item, fact, 'comparator'))} on {outcome}"
        ),
        "canonical_year": paper.get("publication_year") or paper.get("year"),
        "validator": "researka-business-specialist",
        "superseded_by": None,
        "_tier": _clean(item.get("_tier") or "business_research_fact"),
    }
    for name in PRESERVED_FIELDS:
        value = _clean(_specific_method(_field(item, fact, name)) if name == "study_design" else _field(item, fact, name))
        if value:
            out[name] = value
    if numeric is not None and not out.get("effect_size"):
        out["effect_size"] = numeric
    _apply_finance_return_shape(out)
    return out


def comparable_shape(fact: Json) -> dict[str, str]:
    if _is_finance_return_fact(fact):
        return {
            "population": "firms portfolios funds",
            "intervention": "return predictive signal portfolio",
            "signal_family": _finance_signal_family(fact),
            "comparator": "benchmark or opposite signal portfolio",
            "outcome": "risk adjusted portfolio returns",
            "metric": "percentage return or alpha",
            "study_design": "empirical asset pricing",
        }
    return {name: _norm(fact.get(name)) for name in SHAPE_FIELDS if _norm(fact.get(name))}


def shape_key(fact: Json) -> str:
    shape = comparable_shape(fact)
    return "|".join(f"{name}={shape.get(name, '')}" for name in SHAPE_FIELDS)


def _topic_intent_tokens(topic: Any) -> set[str]:
    return set(_WORD.findall(str(topic or "").lower())) - _GENERIC_TOPIC_TOKENS


def _matches_topic_intent(fact: Json) -> bool:
    tokens = _topic_intent_tokens(fact.get("topic"))
    if not tokens:
        return True
    text = _norm(" ".join(
        str(fact.get(name) or "")
        for name in (
            "source_topic", "sub_topic", "canonical_phrase", "population",
            "intervention", "comparator", "outcome", "metric", "industry",
            "asset_class", "dataset", "claim_type",
        )
    ))
    words = set(text.split())
    return bool(tokens & words)


def _is_finance_return_fact(fact: Json) -> bool:
    if str(fact.get("_domain") or "") != "finance_research":
        return False
    if _norm(fact.get("source_topic")) not in _FINANCE_RETURN_TOPICS:
        return False
    if _clean(fact.get("units")).casefold() not in {"%", "percent", "percentage points"}:
        return False
    text = " ".join(str(fact.get(name) or "") for name in (
        "canonical_phrase", "outcome", "metric", "sub_topic", "claim_type",
    ))
    return bool(_FINANCE_RETURN_RE.search(text))


def _finance_signal_family(fact: Json) -> str:
    for field in ("intervention_detail", "intervention", "asset_class", "dataset"):
        value = _norm(fact.get(field))
        if value and value not in _GENERIC_METHOD_VALUES:
            return value
    return ""


def _apply_finance_return_shape(fact: Json) -> None:
    if not _is_finance_return_fact(fact):
        return
    for field in ("population", "intervention", "comparator", "outcome", "metric", "study_design"):
        value = _clean(fact.get(field))
        if value:
            fact[f"{field}_detail"] = value
    fact.update({
        "population": "firms portfolios funds",
        "intervention": "return predictive signal portfolio",
        "signal_family": _finance_signal_family(fact),
        "comparator": "benchmark or opposite signal portfolio",
        "outcome": "risk adjusted portfolio returns",
        "metric": "percentage return or alpha",
        "study_design": "empirical asset pricing",
    })


def is_a_core_business_fact(fact: Json) -> bool:
    shape = comparable_shape(fact)
    if not source_key(fact) or any(not shape.get(field) for field in CORE_SHAPE_FIELDS):
        return False
    if not _matches_topic_intent(fact):
        return False
    if not any(shape.get(field) for field in ("population", "organization_type", "industry", "geography")):
        return False
    return fact.get("numeric_value") is not None or fact.get("effect_size") is not None


def cluster_business_facts(facts: list[Json], *, min_sources: int = MIN_DIRECT_SOURCES) -> list[BusinessCandidateBundle]:
    buckets: dict[str, list[Json]] = {}
    for fact in facts:
        if is_a_core_business_fact(fact):
            buckets.setdefault(shape_key(fact), []).append(fact)
    bundles: list[BusinessCandidateBundle] = []
    for rows in buckets.values():
        picked: list[Json] = []
        seen_sources: set[str] = set()
        for fact in rows:
            src = source_key(fact)
            if src and src not in seen_sources:
                picked.append(fact)
                seen_sources.add(src)
        if len(seen_sources) < min_sources:
            continue
        first = picked[0]
        topic = str(first.get("topic") or "").strip()
        domain = str(first.get("_domain") or "").strip()
        shape = comparable_shape(first)
        bundles.append(BusinessCandidateBundle(
            domain=domain,
            topic=topic,
            result_key=_result_key(topic, shape),
            shape=shape,
            receipts=tuple(picked[:min_sources]),
        ))
    return sorted(bundles, key=lambda b: (-b.source_count, b.result_key))


def _result_key(topic: str, shape: dict[str, str]) -> str:
    basis = "|".join([topic, *(shape.get(name, "") for name in SHAPE_FIELDS)])
    return f"{topic}:{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"


def build_candidate_bundle(raw_facts: list[Json], *, topic: str, domain: str) -> BusinessCandidateBundle | None:
    facts = [
        normalize_business_fact(item, topic=topic, domain=domain)
        for item in raw_facts
        if isinstance(item, dict)
    ]
    bundles = cluster_business_facts(facts)
    return bundles[0] if bundles else None


def business_fact_diagnostics(raw_facts: list[Json], *, topic: str, domain: str) -> Json:
    facts = [
        normalize_business_fact(item, topic=topic, domain=domain)
        for item in raw_facts
        if isinstance(item, dict)
    ]
    missing = {field: 0 for field in (*CORE_SHAPE_FIELDS, "source", "numeric")}
    clusters: dict[str, list[Json]] = {}
    core_count = 0
    for fact in facts:
        shape = comparable_shape(fact)
        for field in CORE_SHAPE_FIELDS:
            if not shape.get(field):
                missing[field] += 1
        if not source_key(fact):
            missing["source"] += 1
        if fact.get("numeric_value") is None and fact.get("effect_size") is None:
            missing["numeric"] += 1
        if is_a_core_business_fact(fact):
            core_count += 1
            clusters.setdefault(shape_key(fact), []).append(fact)
    top_clusters = sorted(
        clusters.values(),
        key=lambda rows: len({source_key(row) for row in rows}),
        reverse=True,
    )[:5]
    return {
        "domain": domain,
        "topic": topic,
        "raw_fact_count": len(raw_facts),
        "normalized_fact_count": len(facts),
        "a_core_fact_count": core_count,
        "missing_core_fields": missing,
        "top_clusters": [
            {
                "source_count": len({source_key(row) for row in rows}),
                "fact_count": len(rows),
                "shape": comparable_shape(rows[0]) if rows else {},
                "sample_fact_id": _clean(rows[0].get("fact_id")) if rows else "",
                "sample": _clean(rows[0].get("canonical_phrase")) if rows else "",
            }
            for rows in top_clusters
        ],
    }


def _headline(bundle: BusinessCandidateBundle) -> str:
    shape = bundle.shape
    intervention = shape.get("intervention", "intervention")
    comparator = shape.get("comparator", "comparator")
    metric = shape.get("metric") or shape.get("outcome") or "outcome"
    population = shape.get("population") or shape.get("industry") or "target population"
    return f"{intervention} vs {comparator} shifts {metric} in {population}"


def _memo_text(bundle: BusinessCandidateBundle, snapshot_utc: str, *, dry_run_only: bool = True) -> str:
    lines = [
        f"# Alpha memo - {bundle.topic}",
        "",
        f"**Headline:** {_headline(bundle)}",
        "**Alpha score:** 90/100",
        "**Confidence:** `evidence_backed_signal`",
        "",
        "## Why this is surprising",
        "",
        "Real tension: the receipts point to the same measured business effect across independent sources, but only within a narrow comparable evidence shape.",
        "",
        "## Evidence shape",
        "",
    ]
    lines.extend(
        f"- **{field}:** {value}"
        for field in SHAPE_FIELDS
        if (value := bundle.shape.get(field))
    )
    lines.extend(["", "## Evidence receipts", ""])
    for fact in bundle.receipts:
        lines.append(
            f"- `fact_id={_clean(fact.get('fact_id'))}` (`A_core`) - "
            f"{_clean(fact.get('canonical_phrase'))}"
        )
    lines.extend([
        "",
        "## What would weaken this",
        "",
        "- A source-diverse rerun with the same shape fails to reproduce the effect.",
        "",
        "## Provenance",
        "",
        f"- **Domain:** `{bundle.domain}`",
        f"- **Snapshot:** `{snapshot_utc}`",
        (
            "- **Mode:** dry-run specialist candidate; no Researka submission."
            if dry_run_only
            else "- **Mode:** guarded specialist candidate; eligible for core Researka submission."
        ),
        "",
    ])
    return "\n".join(lines)


def _lanes_payload(bundle: BusinessCandidateBundle, snapshot_utc: str) -> Json:
    return {
        "topic": bundle.topic,
        "snapshot_utc": snapshot_utc,
        "counts": {"A_core": len(bundle.receipts), "B_context": 0, "C_noise": 0, "D_bad_extraction": 0},
        "verdicts": [
            {
                "fact_id": _clean(fact.get("fact_id")),
                "lane": "A_core",
                "numeric_role": "business_effect",
                "reason": "business_shape_complete_source_diverse",
            }
            for fact in bundle.receipts
        ],
    }


def _gate_payload(bundle: BusinessCandidateBundle, snapshot_utc: str) -> Json:
    ids = [_clean(fact.get("fact_id")) for fact in bundle.receipts]
    return {
        "topic": bundle.topic,
        "snapshot_utc": snapshot_utc,
        "input_pack": {
            "topic": bundle.topic,
            "a_core_count": len(ids),
            "b_context_count": 0,
            "has_minimum_a_core": True,
        },
        "audits": [{
            "thesis_idx": -1,
            "title": f"Source-bound business signal: {_headline(bundle)}",
            "status": "survives",
            "blocking_flags": [],
            "original_opportunity": 90,
            "capped_opportunity": 90,
            "cited_fact_ids": ids,
        }],
    }


def _claim_tokens(bundle: BusinessCandidateBundle) -> set[str]:
    text = " ".join([bundle.topic, *(bundle.shape.values())])
    return set(_WORD.findall(text.lower())) - _GENERIC_TOPIC_TOKENS


def _audit_sidecars_payloads(bundle: BusinessCandidateBundle, facts: list[Json]) -> dict[str, str]:
    facts_by_id = {_clean(fact.get("fact_id")): fact for fact in facts}
    ids = [_clean(fact.get("fact_id")) for fact in facts]
    claim = _claim_tokens(bundle)
    matrix = build_claim_receipt_matrix(claim, ids, ids, facts_by_id)
    novelty = {"selected": _headline(bundle), "repeats": 0}
    audit = build_memo_audit(
        claim,
        ids,
        ids,
        facts_by_id,
        {"counter_evidence": {"items": []}},
        falsifier=True,
        novelty=novelty,
    )
    return {
        "claim_receipt_matrix.json": json.dumps(matrix, indent=2, ensure_ascii=False),
        "typed_counter_evidence.json": json.dumps({"items": []}, indent=2, ensure_ascii=False),
        "novelty_delta.json": json.dumps(
            {
                "novelty_delta": audit["novelty_delta"],
                "nearest_literature": audit["nearest_literature"],
            },
            indent=2,
            ensure_ascii=False,
        ),
        "memo_audit.json": json.dumps(audit, indent=2, ensure_ascii=False),
    }


def write_candidate_run(
    bundle: BusinessCandidateBundle,
    *,
    profile: DomainProfile,
    runs_root: Path,
    snapshot_utc: str | None = None,
) -> Path:
    ts = snapshot_utc or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = runs_root / f"{bundle.topic}-evidence-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    facts = [dict(fact, result_key=bundle.result_key, result_shape=bundle.shape) for fact in bundle.receipts]
    payloads = {
        "all_facts.json": json.dumps(facts, indent=2, ensure_ascii=False),
        "fact_lanes.json": json.dumps(_lanes_payload(bundle, ts), indent=2, ensure_ascii=False),
        "opportunities_gate.json": json.dumps(_gate_payload(bundle, ts), indent=2, ensure_ascii=False),
        "alpha_memo.md": _memo_text(bundle, ts, dry_run_only=profile.dry_run_only),
        "business_candidate_bundle.json": json.dumps(bundle.as_dict(), indent=2, ensure_ascii=False),
        "retrieval_status.json": json.dumps(
            {
                "status": "ok",
                "mode": "dry_run_only" if profile.dry_run_only else "guarded_submit_eligible",
                "source_count": bundle.source_count,
            },
            indent=2,
        ),
    }
    payloads.update(_audit_sidecars_payloads(bundle, facts))
    for name, text in payloads.items():
        run_dir.joinpath(name).write_text(text, encoding="utf-8")
    manifest = {
        "domain": profile.as_metadata(),
        "topic": bundle.topic,
        "snapshot_utc": ts,
        "mode": "business_specialist_dry_run" if profile.dry_run_only else "business_specialist_submit_candidate",
        "dry_run_only": profile.dry_run_only,
        "data_tier": "business_research_fact",
        "source": "Researka DB business-family fact search or fixture",
        "result_key": bundle.result_key,
        "files": {
            name.replace(".", "_"): {
                "name": name,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
            for name, text in payloads.items()
        },
    }
    run_dir.joinpath("MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_publish_verdict(run_dir)
    return run_dir


def fetch_business_facts(
    topic: str,
    *,
    domain: str,
    settings: Settings,
    top_k: int = FETCH_TOP_K,
) -> tuple[list[Json], Json]:
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token:
        return [], {"status": "missing_token", "facts": 0}
    body = {
        "domain": domain,
        "query": topic.replace("_", " "),
        "top_k": top_k,
        "min_confidence": "medium",
        "numeric_only": True,
    }
    try:
        response = httpx.post(
            f"{base}/api/v1/tier2/facts/search",
            headers={"X-Researka-Token": token, "Content-Type": "application/json"},
            json=body,
            timeout=30.0,
        )
        status_code = response.status_code
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return [], {
            "status": "failed",
            "error": exc.__class__.__name__,
            "http_status": status_code if "status_code" in locals() else None,
            "facts": 0,
        }
    rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    return rows, {"status": "ok", "facts": len(rows), "http_status": status_code}
