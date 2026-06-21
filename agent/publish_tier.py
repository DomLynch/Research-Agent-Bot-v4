from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from agent.domain_profile import domain_slug

_ROOT = Path(__file__).resolve().parent.parent
_CFG_PATH = _ROOT / "topic_packs" / "publish_tier.toml"
_PUBLICATION_PATH = _ROOT / "topic_packs" / "publication.toml"
_BINDABLE = frozenset({"A_core", "B_context"})
_DIRECT = frozenset({"A_core"})
_COUNTER_MIN_CLAIM_FIT = 0.2
_BLOCKED_LABELS = frozenset({
    "curation_needed", "evidence_binding_failed", "no_signal", "discard",
})
_LLM_CLUSTER_WAIVED_BLOCKERS = frozenset({
    "claim_alignment_partial", "source_dispersion", "receipt_shape_mismatch",
    "metric_type_mismatch", "weak_counter_consensus_tension", "low_alpha_score",
    "source_floor_below_min", "direct_source_floor_below_min",
})
_EVIDENCE_MAP_WAIVED_BLOCKERS = frozenset({
    "source_dispersion", "weak_counter_consensus_tension", "low_alpha_score",
    "claim_alignment_partial", "source_floor_below_min",
    "direct_source_floor_below_min", "receipt_shape_mismatch",
    "metric_type_mismatch",
})
_RECEIPT_SHAPE_DIMENSIONS = (
    ("population",),
    ("intervention",),
    ("comparator", "baseline_comparator"),
    ("endpoint", "outcome"),
    ("benchmark",),
    ("task", "dataset"),
    ("metric",),
    ("model_system",),
    ("evaluation_protocol",),
)
_STRICT_RECEIPT_SHAPE_DIMENSIONS = frozenset({
    ("comparator", "baseline_comparator"),
    ("benchmark",),
    ("task", "dataset"),
    ("metric",),
    ("model_system",),
    ("evaluation_protocol",),
})
_SHAPE_GENERIC_TOKENS = frozenset({
    "endpoint", "endpoints", "outcome", "outcomes", "intervention",
    "interventions", "comparator", "comparators", "population",
    "group", "groups", "primary", "secondary", "measure", "measures",
    "benchmark", "benchmarks", "metric", "metrics", "dataset",
    "datasets", "model", "models", "system", "systems", "protocol",
    "protocols", "baseline", "baselines", "study", "studies", "shot",
})
_FUNCTION_WORDS = frozenset({
    "was", "were", "been", "being", "are", "has", "had", "have", "having",
    "and", "the", "for", "with", "without", "within", "from", "into", "onto",
    "that", "this", "these", "those", "than", "then", "thus", "such",
    "when", "what", "which", "while", "where", "will", "would", "could",
    "should", "their", "there", "here", "about", "across", "among", "amongst",
    "between", "over", "under", "upon", "versus", "via", "per", "but", "not",
    "any", "all", "its", "his", "her", "our", "your", "they", "them", "may",
    "can", "also", "more", "most", "less", "least", "each", "both", "some",
    "due", "however", "whether",
})
_COUNTED_SOURCE_ARTIFACT_RE = re.compile(
    r"\b\d+\s+(?:of|/)\s+\d+\s+"
    r"(?:cited\s+|direct\s+|source\s+)?"
    r"(?:titles?|receipts?|sources?|reports?|papers?|studies?)\b"
    r".{0,100}\b(?:support(?:s|ed|ing)?|nam(?:e|es|ed|ing)|"
    r"mention(?:s|ed|ing)?|cluster(?:s|ed|ing)?|repeat(?:s|ed|ing)?|"
    r"shar(?:e|es|ed|ing)|overlap(?:s|ped|ping)?|point(?:s|ed|ing)?)\b"
)
_BUNDLE_ARTIFACT_RE = re.compile(
    r"\b(?:"
    r"retrieved\s+(?:bundle|sources?|papers?|receipts?)|"
    r"source\s+(?:bundle|titles?|receipts?|reports?|papers?)|"
    r"cited\s+(?:bundle|titles?|receipts?|reports?|papers?)|"
    r"evidence\s+(?:bundle|sources?|receipts?|papers?)|"
    r"receipt\s+bundle"
    r")\b"
    r".{0,120}\b(?:cluster(?:s|ed|ing)?|mention(?:s|ed|ing)?|"
    r"nam(?:e|es|ed|ing)|shar(?:e|es|ed|ing)|overlap(?:s|ped|ping)?|"
    r"repeat(?:s|ed|ing)?|dominat(?:e|es|ed|ing))\b"
)
_REPORT_TITLE_ARTIFACT_RE = re.compile(
    r"\b(?:report|source|paper|study)\s+titles?\b"
    r".{0,120}\b(?:repeat(?:s|ed|ing)?|cluster(?:s|ed|ing)?|"
    r"overlap(?:s|ped|ping)?|shar(?:e|es|ed|ing)|support(?:s|ed|ing)?)\b"
)
_BUNDLE_SUPPORT_ARTIFACT_RE = re.compile(
    r"\b(?:this|that|these|the)\s+"
    r"(?:retrieved\s+|source\s+|cited\s+|direct\s+|evidence\s+)?"
    r"(?:receipt\s+bundle|bundle|titles?|sources?|receipts?|reports?|papers?)\b"
    r".{0,80}\bsupport(?:s|ed|ing)?\b.{0,80}\b"
    r"(?:cluster|term|label|topic|source[- ]family|retrieval)\b"
)
_RECEIPT_BUNDLE_BOUNDARY_RE = re.compile(
    r"\b(?:sits inside|limited to|inside)\s+(?:the\s+)?"
    r"(?:direct\s+|cited\s+|direct\s+cited\s+)?"
    r"(?:receipt\s+bundle|direct\s+receipts?)\b"
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _domain_slug(run_dir: Path) -> str:
    for name in ("MANIFEST.json", "search_trace.json"):
        data = _json(run_dir / name, {})
        domain = data.get("domain") if isinstance(data, dict) else {}
        slug = domain_slug(domain)
        if slug:
            return slug
    return ""


def _feed_scope_markers(data: dict[str, Any], domain: str) -> tuple[str, ...]:
    feed = data.get("feed_scope") if isinstance(data, dict) else {}
    if not isinstance(feed, dict):
        return ()
    if domain:
        domains = feed.get("domains")
        domain_feed = domains.get(domain) if isinstance(domains, dict) else {}
        raw_values = domain_feed.get("off_scope_markers") if isinstance(domain_feed, dict) else []
    else:
        raw_values = feed.get("off_scope_markers", [])
    values = raw_values if isinstance(raw_values, list) else []
    return tuple(str(x).lower() for x in values)


def _cfg(domain: str = "") -> dict[str, Any]:
    try:
        data = tomllib.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    publish = data.get("publish_tier") if isinstance(data, dict) else {}
    thresholds = data.get("thresholds") if isinstance(data, dict) else {}
    return {
        "tension_markers": tuple(
            str(x).lower() for x in (publish or {}).get("tension_markers", [])
        ),
        "counter_markers": tuple(
            str(x).lower() for x in (publish or {}).get("counter_markers", [])
        ),
        "generic_tokens": frozenset(
            str(x).lower() for x in (publish or {}).get("generic_tokens", [])
        ),
        "cluster_stopwords": frozenset(
            str(x).lower() for x in (publish or {}).get("cluster_stopwords", [])
        ),
        "ready_min_bound_receipts": int(
            (thresholds or {}).get("ready_min_bound_receipts", 3)
        ),
        "ready_min_a_core_receipts": int(
            (thresholds or {}).get("ready_min_a_core_receipts", 2)
        ),
        "ready_min_alpha_score": int(
            (thresholds or {}).get("ready_min_alpha_score", 70)
        ),
        "review_min_alpha_score": int(
            (thresholds or {}).get("review_min_alpha_score", 30)
        ),
        "source_concentration_share": float(
            (thresholds or {}).get("source_concentration_share", 0.60)
        ),
        "domain_overlap_min": float(
            (thresholds or {}).get("domain_overlap_min", 0.06)
        ),
        "context_min_available_sources": int(
            (thresholds or {}).get("context_min_available_sources", 3)
        ),
        "broad_d_bad_share": float(
            (thresholds or {}).get("broad_d_bad_share", 0.60)
        ),
        "broad_min_sources": int((thresholds or {}).get("broad_min_sources", 3)),
        "off_scope_markers": _feed_scope_markers(data, domain),
    }


def _publication_int(key: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    if not isinstance(alpha, dict):
        return default
    try:
        return int(alpha.get(key, default))
    except (TypeError, ValueError):
        return default


def _field(md: str, name: str) -> str:
    m = re.search(rf"^\*\*{re.escape(name)}:\*\* (.+)$", md, flags=re.M)
    return m.group(1).strip() if m else ""


def _section(md: str, heading: str) -> str:
    m = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        md,
        flags=re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def _lead_audit(run_dir: Path) -> dict[str, Any]:
    gate = _json(run_dir / "opportunities_gate.json", {})
    audits = gate.get("audits", []) if isinstance(gate, dict) else []
    valid = [a for a in audits if isinstance(a, dict)]
    if not valid:
        return {}
    rank = {"survives": 3, "needs_source_audit": 2, "rejected": 1}
    return max(
        valid,
        key=lambda a: (
            rank.get(str(a.get("status") or ""), 0),
            int(a.get("capped_opportunity") or 0),
        ),
    )


def _memo_receipt_ids(
    text: str,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
) -> list[str]:
    names = "|".join(re.escape(name) for name in section_names)
    sections = re.findall(
        rf"^## (?:{names}) receipts\n\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.M | re.S,
    )
    seen: set[str] = set()
    out: list[str] = []
    for fid in re.findall(r"`fact_id=([^`\s]+)`", "\n".join(sections)):
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def _facts_by_id(run_dir: Path) -> dict[str, dict[str, Any]]:
    data = _json(run_dir / "all_facts.json", [])
    if not isinstance(data, list):
        return {}
    return {
        str(f.get("fact_id") or ""): f
        for f in data if isinstance(f, dict)
    }


def _lane_map(run_dir: Path) -> dict[str, str]:
    data = _json(run_dir / "fact_lanes.json", {})
    rows = data.get("verdicts", []) if isinstance(data, dict) else []
    return {
        str(v.get("fact_id") or ""): str(v.get("lane") or "")
        for v in rows if isinstance(v, dict)
    }


def _tokens(text: str, topic: str, generic: frozenset[str]) -> set[str]:
    topic_tokens = set(re.findall(r"[a-z0-9]{3,}", topic.lower()))
    out = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    return {
        t for t in out
        if t not in generic and t not in topic_tokens and t not in _FUNCTION_WORDS
    }


def _claim_fit_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    left_roots = {t[:6] for t in left if len(t) >= 6}
    right_roots = {t[:6] for t in right if len(t) >= 6}
    exact = len(left & right) * 2
    rooted = len(left_roots & right_roots)
    return (exact + rooted) / max(1, len(left) + len(right))


def _claim_tokens(cited_ids: list[str], facts: dict[str, dict[str, Any]]) -> set[str]:
    return set().union(*(
        set(re.findall(r"[a-z0-9]{3,}", str(facts.get(fid, {}).get("canonical_phrase") or "").lower()))
        for fid in cited_ids
    )) if cited_ids else set()


def _fact_axis_text(fact: dict[str, Any]) -> str:
    return " ".join(
        str(fact.get(key) or "")
        for key in (
            "canonical_phrase", "population", "intervention", "comparator",
            "endpoint", "outcome", "sub_topic", "claim_type", "metric",
            "benchmark", "task", "model_system", "baseline_comparator",
            "dataset", "evaluation_protocol", "source_topic",
        )
    )


def _shape_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_shape_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_shape_text(v) for v in value)
    return str(value or "")


def _shape_tokens(
    fact: dict[str, Any],
    fields: tuple[str, ...],
    generic: frozenset[str],
) -> set[str]:
    shape_raw = fact.get("result_shape")
    shape = shape_raw if isinstance(shape_raw, dict) else {}
    source = (
        shape
        if any(shape.get(field) not in (None, "", {}, []) for field in fields)
        else fact
    )
    text = " ".join(_shape_text(source.get(field)) for field in fields)
    min_len = 3 if fields in _STRICT_RECEIPT_SHAPE_DIMENSIONS else 4
    return {
        token for token in re.findall(r"[a-z][a-z0-9]*", text.lower())
        if len(token) >= min_len and token not in generic
    }


def _facts_share_shape(
    left: dict[str, Any],
    right: dict[str, Any],
    generic: frozenset[str],
) -> bool:
    shape_generic = generic | _SHAPE_GENERIC_TOKENS
    shared_dims = 0
    checked_dims = 0
    for fields in _RECEIPT_SHAPE_DIMENSIONS:
        left_shape = _shape_tokens(left, fields, shape_generic)
        right_shape = _shape_tokens(right, fields, shape_generic)
        if not left_shape or not right_shape:
            continue
        checked_dims += 1
        if left_shape & right_shape:
            shared_dims += 1
        elif fields in _STRICT_RECEIPT_SHAPE_DIMENSIONS:
            return False
    if not checked_dims:
        return True
    return shared_dims >= (2 if checked_dims >= 2 else 1)


def _receipt_ids_share_shape(
    ids: list[str],
    facts: dict[str, dict[str, Any]],
    generic: frozenset[str],
) -> bool:
    items = [facts[fid] for fid in ids if fid in facts]
    if len(items) < 2:
        return True
    shared_dims = 0
    checked_dims = 0
    shape_generic = generic | _SHAPE_GENERIC_TOKENS
    for fields in _RECEIPT_SHAPE_DIMENSIONS:
        shapes = [_shape_tokens(fact, fields, shape_generic) for fact in items]
        if not all(shapes):
            continue
        checked_dims += 1
        if set.intersection(*shapes):
            shared_dims += 1
        elif fields in _STRICT_RECEIPT_SHAPE_DIMENSIONS:
            return False
    if checked_dims:
        return shared_dims >= (2 if checked_dims >= 2 else 1)
    return True


def _evidence_map_stratified(
    ids: list[str],
    facts: dict[str, dict[str, Any]],
    generic: frozenset[str],
) -> bool:
    items = [facts[fid] for fid in ids if fid in facts]
    if len(items) < 2:
        return False
    shape_generic = generic | _SHAPE_GENERIC_TOKENS
    for fields in (("population",), ("endpoint", "outcome"),
                   ("comparator", "baseline_comparator")):
        values = {
            frozenset(_shape_tokens(fact, fields, shape_generic)) for fact in items
        }
        values.discard(frozenset())
        if len(values) >= 2:
            return True
    return False


def _numeric_value_patterns(value: Any) -> tuple[str, ...]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ()
    raw = str(value).strip()
    patterns = [re.escape(raw)] if raw else []
    if number.is_integer():
        patterns.append(re.escape(str(int(number))))
    else:
        compact = f"{number:g}"
        patterns.append(re.escape(compact))
    return tuple(dict.fromkeys(patterns))


def _numeric_anchor_window(fact: dict[str, Any], *, radius: int = 48) -> str:
    phrase = str(fact.get("canonical_phrase") or "")
    patterns = _numeric_value_patterns(fact.get("numeric_value"))
    if not phrase or not patterns:
        return ""
    for pattern in patterns:
        match = re.search(rf"(?<![0-9.]){pattern}(?![0-9.])", phrase)
        if match:
            lo = max(0, match.start() - radius)
            hi = min(len(phrase), match.end() + radius)
            return phrase[lo:hi]
    return ""


def _metric_type_coherent(
    ids: list[str],
    facts: dict[str, dict[str, Any]],
    generic: frozenset[str],
    *,
    min_sources: int,
) -> bool:
    items = [facts[fid] for fid in ids if fid in facts]
    if len(items) < 2:
        return True
    shape_generic = generic | _SHAPE_GENERIC_TOKENS
    metric_shapes = [
        _shape_tokens(fact, ("metric",), shape_generic) for fact in items
    ]
    metric_shapes = [tokens for tokens in metric_shapes if tokens]
    if not metric_shapes:
        return True
    common_metric = set.intersection(*metric_shapes) if len(metric_shapes) == len(items) else set()
    if not common_metric:
        return True
    aligned_sources: set[str] = set()
    quantified_sources: set[str] = set()
    for fid in ids:
        fact = facts.get(fid) or {}
        source = _source_key(fact)
        if not source or fact.get("numeric_value") in (None, ""):
            continue
        quantified_sources.add(source)
        window = _numeric_anchor_window(fact)
        unit_text = str(fact.get("units") or "")
        anchor_tokens = _tokens(
            f"{window} {unit_text}", "", shape_generic,
        )
        if common_metric & anchor_tokens:
            aligned_sources.add(source)
    if len(quantified_sources) < min_sources:
        return True
    return len(aligned_sources) >= min_sources


def _claim_axis(
    md: str,
    topic: str,
    generic: frozenset[str],
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
) -> tuple[str, set[str]]:
    text = "\n".join((
        _field(md, "Headline"),
        _section(md, "One-sentence thesis"),
        _section(md, "Why this is surprising"),
        _section(md, "Evidence Landscape"),
    ))
    tokens = _tokens(text, topic, generic)
    if tokens:
        return text, tokens
    return text, _claim_tokens(cited_ids, facts)


# An un-negated performance gain is same-direction as a "X improves Y" thesis —
# a SUPPORTING source, not counter-evidence. Recycling it is the reject reviewers
# flag; an incidental "improves ... without fine-tuning" must not flip to opposing,
# while a negated gain ("did not improve") still qualifies as counter-evidence.
_GAIN_TOKENS = (
    "improv", "outperform", "better", "higher", "superior", "boost",
    "enhanc", "exceed", "stronger", "gain", "advantage", "surpass",
)
_GAIN_NEGATORS = (
    "not", "no", "without", "fail", "lack", "lower", "less", "worse",
    "unchanged", "null", "reduc", "decreas", "drop", "declin", "nt",
)


def _asserts_unnegated_gain(phrase: str) -> bool:
    toks = re.findall(r"[a-z']+", phrase.lower())
    for i, tok in enumerate(toks):
        if any(tok.startswith(g) for g in _GAIN_TOKENS) and not any(
            w.startswith(n) for w in toks[max(0, i - 3):i] for n in _GAIN_NEGATORS
        ):
            return True
    return False


def _claim_fit(
    fid: str,
    fact: dict[str, Any],
    lane: str,
    claim_text: str,
    claim_tokens: set[str],
    topic: str,
    generic: frozenset[str],
    markers: tuple[str, ...],
) -> dict[str, Any]:
    fact_tokens = _tokens(_fact_axis_text(fact), topic, generic)
    score = _claim_fit_score(fact_tokens, claim_tokens)
    direct_overlap = len(fact_tokens & claim_tokens)
    phrase = str(fact.get("canonical_phrase") or "").lower()
    fact_opposes = bool(markers) and any(marker in phrase for marker in markers)
    core_claim_text = claim_text.splitlines()[0].lower() if claim_text.splitlines() else ""
    claim_opposes = bool(markers) and any(marker in core_claim_text for marker in markers)
    if (
        lane in _BINDABLE and fact_opposes and not claim_opposes
        and score >= _COUNTER_MIN_CLAIM_FIT
        and not _asserts_unnegated_gain(phrase)
    ):
        label = "opposing"
    elif lane in _DIRECT and (
        score >= _COUNTER_MIN_CLAIM_FIT or direct_overlap >= 4
    ):
        label = "direct_match"
    elif lane in _BINDABLE and (score > 0 or bool(_tokens(topic, "", frozenset()) & fact_tokens)):
        label = "boundary"
    else:
        label = "context"
    return {"fact_id": fid, "claim_fit": label, "score": round(score, 3)}


def _claim_fit_map(
    ids: list[str],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    claim_text: str,
    claim_tokens: set[str],
    topic: str,
    generic: frozenset[str],
    markers: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    return {
        fid: _claim_fit(
            fid, facts.get(fid) or {}, lanes.get(fid, ""), claim_text,
            claim_tokens, topic, generic, markers,
        )
        for fid in ids
    }


def _source_papers(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    papers: list[dict[str, Any]] = []
    for fid in cited_ids:
        paper = facts.get(fid, {}).get("source_paper") or {}
        if not isinstance(paper, dict):
            continue
        key = str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
                  or paper.get("paper_id") or paper.get("id") or paper.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            papers.append(paper)
    return papers


def _source_key(fact: dict[str, Any]) -> str:
    # P5 hardening: identity order DOI > PMID > PMCID > paper_id > id > title.
    paper = fact.get("source_paper") or {}
    if not isinstance(paper, dict):
        return ""
    return str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
               or paper.get("paper_id") or paper.get("id") or paper.get("title") or "")


def _result_key_direct_ids(
    ids: list[str],
    facts: dict[str, dict[str, Any]],
    generic: frozenset[str],
    min_sources: int,
) -> list[str]:
    clusters: dict[str, list[str]] = {}
    for fid in ids:
        fact = facts.get(fid) or {}
        key = str(fact.get("result_key") or "").strip()
        if key:
            clusters.setdefault(key, []).append(fid)
    for _key, cluster_ids in sorted(clusters.items(), key=lambda item: -len(item[1])):
        out: list[str] = []
        seen_sources: set[str] = set()
        for fid in cluster_ids:
            source = _source_key(facts.get(fid) or {})
            if source and source not in seen_sources:
                seen_sources.add(source)
                out.append(fid)
        if (
            len(seen_sources) >= min_sources
            and _receipt_ids_share_shape(out, facts, generic)
            and _metric_type_coherent(
                out, facts, generic, min_sources=min_sources,
            )
        ):
            return out
    return []


def _paper_summary(fact: dict[str, Any]) -> dict[str, Any]:
    paper = fact.get("source_paper") or {}
    return {
        "doi": str(paper.get("doi") or ""),
        "title": str(paper.get("title") or ""),
        "journal": str(paper.get("journal") or ""),
        "year": paper.get("year"),
    } if isinstance(paper, dict) else {
        "doi": "", "title": "", "journal": "", "year": None,
    }


def _fact_summary(
    fid: str,
    fact: dict[str, Any],
    lane: str,
) -> dict[str, Any]:
    return {
        "fact_id": fid,
        "lane": lane,
        "phrase": str(fact.get("canonical_phrase") or "")[:260],
        "sub_topic": str(fact.get("sub_topic") or ""),
        "population": str(fact.get("population") or "")[:160],
        "intervention": str(fact.get("intervention") or "")[:160],
        "source_paper": _paper_summary(fact),
    }


def _bound_ids_in_fact_order(
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
) -> list[str]:
    return [fid for fid in facts if lanes.get(fid) in _BINDABLE]


def _counter_evidence(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    claim_text: str,
    claim: set[str],
    topic: str,
    generic: frozenset[str],
    markers: tuple[str, ...],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fid in _bound_ids_in_fact_order(facts, lanes):
        fact = facts.get(fid) or {}
        fit = _claim_fit(
            fid, fact, lanes.get(fid, ""), claim_text, claim, topic,
            generic, markers,
        )
        if fit["claim_fit"] != "opposing":
            continue
        item = _fact_summary(fid, fact, lanes.get(fid, ""))
        item["claim_fit"] = fit["claim_fit"]
        item["claim_fit_score"] = fit["score"]
        item["_rank"] = float(fit["score"])
        out.append(item)
    out.sort(key=lambda item: (item["lane"] != "A_core", -float(item["_rank"]), item["fact_id"]))
    for item in out:
        item.pop("_rank", None)
    return out[:3]


def _expansion_candidates(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    cited = set(cited_ids)
    out: list[dict[str, Any]] = []
    claim = _claim_tokens(cited_ids, facts)
    cited_sources = {
        _source_key(facts[fid]) for fid in cited if fid in facts
    }
    for fid in _bound_ids_in_fact_order(facts, lanes):
        if fid in cited:
            continue
        fact = facts.get(fid) or {}
        item = _fact_summary(fid, fact, lanes.get(fid, ""))
        item["same_source_as_lead"] = _source_key(fact) in cited_sources
        item["_rank"] = _claim_fit_score(
            set(re.findall(r"[a-z0-9]{3,}", str(fact.get("canonical_phrase") or "").lower())),
            claim,
        )
        out.append(item)
    out.sort(key=lambda item: (
        item["same_source_as_lead"],
        item["lane"] != "A_core",
        -float(item["_rank"]),
        item["fact_id"],
    ))
    for item in out:
        item.pop("_rank", None)
    return out[:limit]


def _cluster_label(
    facts: list[dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    stopwords: frozenset[str],
) -> str:
    counts: Counter[str] = Counter()
    for fact in facts:
        primary_text = " ".join([
            str(fact.get("intervention") or ""),
            str(fact.get("comparator") or ""),
        ])
        tokens = _tokens(primary_text, topic, generic | stopwords)
        if not tokens:
            tokens = _tokens(str(fact.get("canonical_phrase") or ""), topic, generic | stopwords)
        if not tokens:
            tokens = _tokens(str(fact.get("population") or ""), topic, generic | stopwords)
        for token in sorted(tokens):
            counts[token] += 2
    return "_".join(token for token, _ in counts.most_common(3)) or "unlabeled"


def _source_diverse_fact_clusters(
    facts: list[dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    stopwords: frozenset[str],
    *,
    min_overlap: float,
    source_min: int,
) -> list[list[dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], str, set[str], set[str]]] = []
    for fact in facts:
        source = _source_key(fact)
        axis_text = _fact_axis_text(fact)
        tokens = _tokens(axis_text, topic, generic | stopwords)
        claim_tokens = tokens
        if source and tokens:
            rows.append((fact, source, tokens, claim_tokens))
    clusters: list[list[dict[str, Any]]] = []
    seen: set[tuple[str, ...]] = set()
    for seed, seed_source, seed_tokens, seed_claim_tokens in rows:
        sources = {seed_source}
        cluster = [seed]
        for fact, source, tokens, claim_tokens in rows:
            if source in sources:
                continue
            claim_overlap = seed_claim_tokens & claim_tokens
            if (
                len(claim_overlap) >= 2
                and len(seed_tokens & tokens) / max(1, len(seed_tokens | tokens)) >= min_overlap
                and _facts_share_shape(seed, fact, generic | stopwords)
            ):
                cluster.append(fact)
                sources.add(source)
        if len(sources) < source_min:
            continue
        sig = tuple(sorted(str(it.get("_fact_id") or "") for it in cluster))
        if sig not in seen:
            seen.add(sig)
            clusters.append(cluster)
    return sorted(
        clusters,
        key=lambda items: (
            -len({_source_key(it) for it in items}),
            -len(items),
            str(items[0].get("_fact_id") or ""),
        ),
    )


def _subtopic_recommendations(
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    topic: str,
    generic: frozenset[str],
    stopwords: frozenset[str],
    *,
    d_bad_share_min: float,
    min_overlap: float,
    source_min: int,
    enabled: bool,
) -> dict[str, Any]:
    total = max(1, len(lanes))
    d_bad = sum(1 for lane in lanes.values() if lane == "D_bad_extraction")
    by_source: dict[str, list[dict[str, Any]]] = {}
    a_core: list[dict[str, Any]] = []
    for fid, fact in facts.items():
        item = fact | {"_fact_id": fid}
        key = _source_key(fact)
        if key:
            by_source.setdefault(key, []).append(item)
        if lanes.get(fid) == "A_core":
            a_core.append(item)
    noisy_recommend = (
        enabled and d_bad / total >= d_bad_share_min
        and len(by_source) >= source_min
    )
    coherent_clusters = _source_diverse_fact_clusters(
        a_core, topic, generic, stopwords,
        min_overlap=min_overlap, source_min=source_min,
    )
    recommend = noisy_recommend or (enabled and bool(coherent_clusters))
    clusters: list[dict[str, Any]] = []
    if noisy_recommend:
        cluster_items = sorted(by_source.values(), key=len, reverse=True)
    else:
        cluster_items = sorted(coherent_clusters, key=len, reverse=True)
    if recommend:
        for items in cluster_items[:5]:
            first = items[0]
            clusters.append({
                "label": _cluster_label(items, topic, generic, stopwords),
                "member_fact_ids": [str(it.get("_fact_id") or "") for it in items[:8]],
                "source_paper": _paper_summary(first),
                "example_phrase": str(first.get("canonical_phrase") or "")[:220],
            })
    return {
        "recommended": recommend,
        "reason": (
            "high_d_bad_share_plus_semantic_dispersion" if noisy_recommend
            else "source_coherent_child_cluster" if recommend
            else "not_broad_or_not_noisy_enough"
        ),
        "d_bad_share": round(d_bad / total, 3),
        "source_count": len(by_source),
        "clusters": clusters,
    }


def _domain_forced(
    papers: list[dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    min_overlap: float,
) -> bool:
    if len(papers) < 2:
        return False
    token_sets = [
        _tokens(
            f"{p.get('title') or ''} {p.get('journal') or ''}",
            topic,
            generic,
        )
        for p in papers
    ]
    for i, left in enumerate(token_sets):
        for right in token_sets[i + 1:]:
            if not left or not right:
                continue
            overlap = len(left & right) / max(1, len(left | right))
            if overlap >= min_overlap:
                return False
    return True


def _source_concentrated(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    threshold: float,
) -> bool:
    dois = []
    for fid in cited_ids:
        paper = facts.get(fid, {}).get("source_paper") or {}
        doi = str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
                  or paper.get("paper_id") or paper.get("id") or paper.get("title") or "")
        if doi:
            dois.append(doi)
    if not dois:
        return False
    counts = Counter(dois)
    return max(counts.values()) / len(dois) >= threshold or len(counts) <= 2


def _claim_coherent_source_diversity(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    min_overlap: float,
    min_sources: int,
) -> bool:
    by_source: dict[str, set[str]] = {}
    for fid in cited_ids:
        fact = facts.get(fid) or {}
        source = _source_key(fact)
        if not source:
            continue
        tokens = _tokens(" ".join([
            str(fact.get("canonical_phrase") or ""),
            str(fact.get("population") or ""),
            str(fact.get("intervention") or ""),
        ]), topic, generic)
        if tokens:
            by_source.setdefault(source, set()).update(tokens)
    source_tokens = list(by_source.values())
    if len(source_tokens) < min_sources:
        return False
    for i, left in enumerate(source_tokens):
        cluster_size = 1
        for j, right in enumerate(source_tokens):
            if i == j:
                continue
            overlap = len(left & right) / max(1, len(left | right))
            if overlap >= min_overlap:
                cluster_size += 1
        if cluster_size >= min_sources:
            return True
    return False


def _has_tension(md: str, markers: tuple[str, ...]) -> bool:
    text = (
        _field(md, "Headline") + "\n" + _section(md, "Why this is surprising")
    ).lower()
    return "real tension:" in text or any(marker in text for marker in markers)


def _retrieval_artifact_claim(md: str, *, strong_direct_bundle: bool = False) -> bool:
    text = "\n".join((
        _field(md, "Headline"),
        _section(md, "One-sentence thesis"),
        _section(md, "Why this is surprising"),
        _section(md, "Evidence Landscape"),
        _section(md, "What this changes"),
    )).lower()
    if not text:
        return False
    return bool(
        _COUNTED_SOURCE_ARTIFACT_RE.search(text)
        or _BUNDLE_ARTIFACT_RE.search(text)
        or _REPORT_TITLE_ARTIFACT_RE.search(text)
        or _BUNDLE_SUPPORT_ARTIFACT_RE.search(text)
        or (
            not strong_direct_bundle
            and _RECEIPT_BUNDLE_BOUNDARY_RE.search(text)
        )
    )


def _marker_in_text(marker: str, text: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(marker).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _off_scope(
    papers: list[dict[str, Any]], topic: str, markers: tuple[str, ...],
) -> bool:
    if not markers:
        return False
    topic_text = topic.replace("_", " ").replace("-", " ").lower()
    text = "\n".join(
        f"{p.get('title') or ''} {p.get('journal') or ''}".lower()
        for p in papers
    )
    return any(
        not _marker_in_text(marker, topic_text) and _marker_in_text(marker, text)
        for marker in markers
    )


def publish_verdict(run_dir: Path) -> dict[str, Any]:
    md = _read(run_dir / "alpha_memo.md")
    cfg = _cfg(_domain_slug(run_dir))
    topic = run_dir.name.split("-evidence-", 1)[0]
    label = _field(md, "Confidence").strip("`") or "unknown"
    score_raw = _field(md, "Alpha score").split("/", 1)[0]
    try:
        alpha_score = int(score_raw)
    except ValueError:
        alpha_score = 0
    audit = _lead_audit(run_dir)
    cited_ids = _memo_receipt_ids(md) or [
        str(x) for x in audit.get("cited_fact_ids", [])
    ]
    evidence_ids = _memo_receipt_ids(md, ("Evidence",))
    facts = _facts_by_id(run_dir)
    lanes = _lane_map(run_dir)
    bound_ids = [fid for fid in cited_ids if lanes.get(fid) in _BINDABLE]
    direct_ids = [fid for fid in evidence_ids if lanes.get(fid) in _DIRECT]
    claim_text, claim_tokens = _claim_axis(
        md, topic, cfg["generic_tokens"] | cfg["cluster_stopwords"],
        direct_ids or bound_ids, facts,
    )
    fit_ids = list(dict.fromkeys(bound_ids + _bound_ids_in_fact_order(facts, lanes)))
    claim_fit = _claim_fit_map(
        fit_ids, facts, lanes, claim_text, claim_tokens, topic,
        cfg["generic_tokens"] | cfg["cluster_stopwords"],
        cfg["counter_markers"],
    )
    direct_match_ids = [
        fid for fid in direct_ids
        if claim_fit.get(fid, {}).get("claim_fit") == "direct_match"
    ]
    min_source_papers = _publication_int("min_source_papers", 5)
    min_direct_source_papers = _publication_int("min_direct_source_papers", 5)
    # A writer-validated homogeneous cluster publishes at its own lower floor:
    # 2-3 directly-comparable sources are a stronger claim than 5 dispersed ones.
    min_cluster_source_papers = _publication_int("min_cluster_source_papers", 3)
    result_direct_ids = _result_key_direct_ids(
        direct_ids, facts, cfg["generic_tokens"] | cfg["cluster_stopwords"],
        min_direct_source_papers,
    )
    if len(result_direct_ids) > len(direct_match_ids):
        direct_match_ids = result_direct_ids
    a_core = len(direct_match_ids)
    papers = _source_papers(bound_ids, facts)
    direct_papers = _source_papers(direct_match_ids, facts)
    all_bound_ids = _bound_ids_in_fact_order(facts, lanes)
    available_source_count = len({
        _source_key(facts[fid]) for fid in all_bound_ids if fid in facts
    } - {""})
    source_concentrated = _source_concentrated(
        direct_match_ids, facts, float(cfg["source_concentration_share"]),
    )
    source_coherent = len(direct_papers) >= min_source_papers and (
        source_concentrated or _claim_coherent_source_diversity(
            direct_match_ids, facts, topic,
            cfg["generic_tokens"] | cfg["cluster_stopwords"],
            float(cfg["domain_overlap_min"]), min_source_papers,
        )
    )
    forced = _domain_forced(
        papers, topic, cfg["generic_tokens"], float(cfg["domain_overlap_min"]),
    )
    off_scope = _off_scope(papers, topic, cfg["off_scope_markers"])
    counter_evidence = _counter_evidence(
        bound_ids, facts, lanes, claim_text,
        claim_tokens | _claim_tokens(direct_match_ids, facts), topic,
        cfg["generic_tokens"] | cfg["cluster_stopwords"], cfg["counter_markers"],
    )
    tension = _has_tension(md, cfg["tension_markers"]) or bool(counter_evidence)
    direct_shape_ids = direct_ids or direct_match_ids
    direct_receipt_shape_coherent = _receipt_ids_share_shape(
        direct_shape_ids, facts, cfg["generic_tokens"] | cfg["cluster_stopwords"],
    )
    direct_metric_type_coherent = _metric_type_coherent(
        direct_shape_ids, facts, cfg["generic_tokens"] | cfg["cluster_stopwords"],
        min_sources=min_direct_source_papers,
    )
    strong_direct_bundle = (
        len(direct_papers) >= min_direct_source_papers
        and len(direct_papers) >= min_source_papers
        and source_coherent
        and direct_receipt_shape_coherent
        and direct_metric_type_coherent
    )
    retrieval_artifact = _retrieval_artifact_claim(
        md, strong_direct_bundle=strong_direct_bundle,
    )
    expansion_candidates = _expansion_candidates(bound_ids, facts, lanes)
    blockers: list[str] = []
    if label in _BLOCKED_LABELS:
        blockers.append(f"blocked_label:{label}")
    if not bound_ids:
        blockers.append("no_bound_receipts")
    if forced:
        blockers.append("cross_domain_forced")
    if not source_coherent and direct_match_ids and len(direct_papers) >= min_source_papers:
        blockers.append("source_dispersion")
    if not tension and bound_ids and not strong_direct_bundle:
        blockers.append("weak_counter_consensus_tension")
    if bound_ids and alpha_score < int(cfg["review_min_alpha_score"]):
        blockers.append("low_alpha_score")
    if off_scope:
        blockers.append("feed_scope_mismatch")
    if len(direct_papers) < min_source_papers:
        blockers.append("source_floor_below_min")
    if len(direct_papers) < min_direct_source_papers:
        blockers.append("direct_source_floor_below_min")
    if bound_ids and len(direct_match_ids) < len(direct_ids):
        blockers.append("claim_alignment_partial")
    if direct_shape_ids and not direct_receipt_shape_coherent:
        blockers.append("receipt_shape_mismatch")
    if direct_shape_ids and not direct_metric_type_coherent:
        blockers.append("metric_type_mismatch")
    if retrieval_artifact:
        blockers.append("retrieval_artifact_claim")

    ready = (
        not blockers
        and label not in _BLOCKED_LABELS
        and len(bound_ids) >= int(cfg["ready_min_bound_receipts"])
        and a_core >= int(cfg["ready_min_a_core_receipts"])
        and alpha_score >= int(cfg["ready_min_alpha_score"])
    )
    # Evidence-map path: a source-rich multi-finding synthesis publishes when it
    # has >= the source floor of distinct A_core papers and clears every
    # integrity blocker; only single-claim coherence blockers are waived.
    a_core_source_papers = len(_source_papers(direct_ids, facts))
    # The full A_core landscape — every bound A_core source in the run, not just
    # the memo's narrow cluster. A heterogeneous topic's map cites that whole
    # breadth (multi-agent: 88 sources), so the map-route source floor must measure
    # it, not the handful the single-claim memo happened to cite.
    landscape_a_core_ids = [fid for fid in all_bound_ids if lanes.get(fid) in _DIRECT]
    landscape_a_core_sources = len(_source_papers(landscape_a_core_ids, facts))
    # Read the writer-validated cluster first: its homogeneity decides whether the
    # topic is a single claim or a landscape.
    llm_cluster = _json(run_dir / "claim_cluster.json", {})
    llm_cluster_ids = {
        str(x) for x in (llm_cluster.get("lead_fact_ids") or [])
    } if isinstance(llm_cluster, dict) else set()
    llm_cluster_sources = len(_source_papers(
        [fid for fid in bound_ids if fid in llm_cluster_ids and lanes.get(fid) in _DIRECT],
        facts,
    ))
    # Homogeneity is set by the clusterer's skeptical pass (absent on legacy runs
    # and on narrow topics -> default True, so behaviour is unchanged without the
    # signal). A heterogeneous cluster is a landscape masquerading as one claim.
    cluster_homogeneous = (
        bool(llm_cluster.get("homogeneous", True))
        if isinstance(llm_cluster, dict) else True
    )
    # Heterogeneous-but-source-rich -> evidence map: when M3 could not find a
    # coherent single claim (the cluster spans diseases/outcomes) but the topic has
    # the source breadth for a landscape, publish it as a map (the panel accepts
    # maps) instead of a single-claim memo (which it rejects for incoherence). The
    # map's own >=10-citation floor still applies at submit.
    cluster_map_route = (
        llm_cluster_sources >= min_cluster_source_papers
        and not cluster_homogeneous
        and landscape_a_core_sources >= min_direct_source_papers
    )
    # Evidence-map path: a source-rich multi-finding synthesis publishes when it
    # has >= the source floor of distinct A_core papers and clears every integrity
    # blocker; only single-claim coherence blockers are waived. A heterogeneous
    # cluster routes here even without the writer's evidence_map label.
    evidence_map_ready = (
        bool(bound_ids)
        and not (set(blockers) - _EVIDENCE_MAP_WAIVED_BLOCKERS)
        # Non-waived: a map must be a real landscape (>=2 distinct strata), or the
        # panel rejects it as a constant-population fake landscape — the reject that
        # a heterogeneous bundle routed here would otherwise hit again.
        and _evidence_map_stratified(
            landscape_a_core_ids, facts,
            cfg["generic_tokens"] | cfg["cluster_stopwords"],
        )
        and (
            (label == "evidence_map" and a_core_source_papers >= min_direct_source_papers)
            # The cluster-routed map cites the full landscape, so it clears the
            # floor on the landscape count even when the memo's cluster is narrow.
            or (cluster_map_route and landscape_a_core_sources >= min_direct_source_papers)
        )
    )
    # Trust an M3-validated HOMOGENEOUS cluster as a single claim: same population,
    # comparator, endpoint, and direction, clearing the lower cluster floor — only
    # token-coherence blockers stand in the way (waived). A heterogeneous cluster
    # is NOT a single claim and does not qualify here (it routes to the map above).
    llm_cluster_ready = (
        llm_cluster_sources >= min_cluster_source_papers
        and cluster_homogeneous
        and bool(bound_ids)
        and label not in _BLOCKED_LABELS
        and not off_scope
        and not (set(blockers) - _LLM_CLUSTER_WAIVED_BLOCKERS)
    )
    if ready or evidence_map_ready or llm_cluster_ready:
        tier, level = "TIER_1", "L5"
        decision = "ready_to_publish"
    elif (not bound_ids or label in _BLOCKED_LABELS or off_scope
          or alpha_score < int(cfg["review_min_alpha_score"])):
        tier, level = "TIER_3", "L2"
        decision = "curation_needed"
    else:
        tier, level = "TIER_2", "L4"
        decision = "agent_repair_needed"
    expansion_needed = (
        len(bound_ids) < int(cfg["ready_min_bound_receipts"])
        and len(all_bound_ids) > len(bound_ids)
    )
    context_dependence = (
        decision == "agent_repair_needed"
        and expansion_needed
        and tension
        and not forced
        and not off_scope
        and available_source_count >= int(cfg["context_min_available_sources"])
    )
    subtopics = _subtopic_recommendations(
        facts, lanes, topic, cfg["generic_tokens"], cfg["cluster_stopwords"],
        d_bad_share_min=float(cfg["broad_d_bad_share"]),
        min_overlap=float(cfg["domain_overlap_min"]),
        source_min=min_direct_source_papers,
        enabled=decision != "ready_to_publish",
    )
    if decision == "ready_to_publish":
        surface_type = (
            "evidence_map" if evidence_map_ready and not ready
            else "publish_alpha_memo"
        )
    elif context_dependence:
        surface_type = "context_dependence_memo"
    elif off_scope or forced:
        surface_type = "split_or_reject_memo"
    elif "source_dispersion" in blockers:
        surface_type = "heterogeneity_memo"
    elif "claim_alignment_partial" in blockers or "direct_source_floor_below_min" in blockers:
        surface_type = "receipt_map"
    elif "retrieval_artifact_claim" in blockers:
        surface_type = "retrieval_note"
    elif subtopics["recommended"]:
        surface_type = "subtopic_rerun_memo"
    elif decision == "curation_needed":
        surface_type = "curation_brief"
    else:
        surface_type = "frontier_hypothesis_memo"
    # A ready_to_publish verdict has no ACTIVE blockers: the listed ones were
    # WAIVED by the path that cleared it (llm_cluster_ready / evidence_map_ready).
    # Both a truthful reading of "blockers" and Researka intake's 2-4 source alpha
    # exception (which requires an empty blockers field on a TIER_1/L5 memo)
    # demand that a publishable verdict surface only active blockers; keep the
    # waived set separately for the diagnostic trail.
    publishable = decision == "ready_to_publish"
    active_blockers = [] if publishable else blockers
    waived_blockers = blockers if publishable else []
    try:
        run_ref = str(run_dir.resolve().relative_to(_ROOT))
    except ValueError:
        run_ref = str(run_dir)
    return {
        "run_dir": run_ref,
        "topic": topic,
        "decision": decision,
        "publish_tier": tier,
        "maturity_level": level,
        "headline": _field(md, "Headline"),
        "confidence_label": label,
        "alpha_score": alpha_score,
        "surface_type": surface_type,
        "axes": {
            "bound_receipts": len(bound_ids),
            "direct_match_receipts": len(direct_match_ids),
            "boundary_receipts": sum(
                1 for fid in bound_ids
                if claim_fit.get(fid, {}).get("claim_fit") == "boundary"
            ),
            "context_receipts": sum(
                1 for fid in bound_ids
                if claim_fit.get(fid, {}).get("claim_fit") == "context"
            ),
            "opposing_receipts": sum(
                1 for fid in bound_ids
                if claim_fit.get(fid, {}).get("claim_fit") == "opposing"
            ),
            "direct_source_papers": len(direct_papers),
            "available_bound_receipts": len(all_bound_ids),
            "available_source_contexts": available_source_count,
            "a_core_receipts": a_core,
            "source_concentrated": source_concentrated,
            "claim_coherent_source_diversity": source_coherent,
            "direct_receipt_shape_coherent": direct_receipt_shape_coherent,
            "direct_metric_type_coherent": direct_metric_type_coherent,
            "retrieval_artifact_claim": retrieval_artifact,
            "counter_consensus_tension": tension,
            "cross_domain_forced": forced,
            "feed_scope_mismatch": off_scope,
            "source_papers": [
                {
                    "doi": str(p.get("doi") or ""),
                    "title": str(p.get("title") or ""),
                    "journal": str(p.get("journal") or ""),
                    "year": p.get("year"),
                }
                for p in papers
            ],
        },
        "receipt_expansion": {
            "needed": expansion_needed,
            "why": (
                "lead_thesis_underuses_available_bound_receipts"
                if expansion_needed else "lead_thesis_uses_available_receipts"
            ),
            "cited_bound_fact_ids": bound_ids,
            # Scope the expansion pool to the claim: a writer-validated cluster's
            # population-aware membership is the coherent set (a house-cricket
            # receipt is split out of an "in mice" claim), so off-claim bound facts
            # never enter the pool that feeds receipt expansion. With no cluster
            # scoping the claim, every bound fact stays in scope.
            "available_bound_fact_ids": (
                [fid for fid in all_bound_ids if str(fid) in llm_cluster_ids]
                if llm_cluster_ids else all_bound_ids
            ),
            "candidate_receipts": [
                item | {
                    "claim_fit": claim_fit.get(
                        str(item.get("fact_id") or ""), {}
                    ).get("claim_fit", "context")
                }
                for item in expansion_candidates
            ],
        },
        "counter_evidence": {
            "status": "found" if counter_evidence else "none_found",
            "items": counter_evidence,
        },
        "subtopic_recommendations": subtopics,
        "blockers": active_blockers,
        "waived_blockers": waived_blockers,
    }


def write_publish_verdict(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    verdict = publish_verdict(run_dir)
    path = run_dir / "publish_verdict.json"
    path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    return path, verdict
