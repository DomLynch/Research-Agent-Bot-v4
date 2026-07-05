"""Source-literature selected-bundle helpers for alpha publish cycles."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.domain_profile import load_domain_profile
from agent.researka_facts import tier2_domain
from agent.settings import load_settings

Json = dict[str, Any]
_FACT_SEARCH_TIMEOUT_ENV = "RESEARKA_SOURCE_LITERATURE_FACT_TIMEOUT_SECONDS"
_FULLRAW_TIMEOUT_ENV = "RESEARKA_SOURCE_LITERATURE_FULLRAW_TIMEOUT_SECONDS"
_FULLRAW_BUDGET_ENV = "RESEARKA_SOURCE_LITERATURE_FULLRAW_BUDGET_SECONDS"
_FULLRAW_SWEEP_WAIT_ENV = "RESEARKA_SOURCE_LITERATURE_FULLRAW_SWEEP_WAIT_SECONDS"
_FULLRAW_MAX_VARIANTS_ENV = "RESEARKA_SOURCE_LITERATURE_FULLRAW_MAX_VARIANTS"
_FULLRAW_MIN_SHARDS_ENV = "RESEARKA_SOURCE_LITERATURE_FULLRAW_MIN_SHARDS_SEARCHED"
_FULLRAW_MIN_SOURCES_ENV = "RESEARKA_SOURCE_LITERATURE_FULLRAW_MIN_SOURCES_SEARCHED"
_FULLRAW_MIN_SHARDS = 1525
_FULLRAW_MIN_SOURCES = 5
_FULLRAW_SOURCE_LIT_BUDGET_CAP_SECONDS = 300
_FULLRAW_SOURCE_LIT_SWEEP_CAP_SECONDS = 120
_GENERIC_TOPIC_TOKENS = frozenset({
    "association", "associations", "clinical", "effect", "effects", "evidence",
    "exposure", "intervention", "outcome", "outcomes", "review", "study",
    "trial", "treatment", "use", "using",
    "ageing", "aging", "agent", "agents", "agonist", "agonists", "antagonist",
    "antagonists", "blocker", "blockers", "drug", "drugs", "inhibitor",
    "inhibitors", "longevity", "therapies", "therapy", "anti",
})


def _int_env_floor(name: str, fallback: str | None, floor: int) -> str:
    try:
        return str(max(floor, int(os.environ.get(name, fallback or str(floor)))))
    except (TypeError, ValueError):
        return str(floor)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return None


def _seconds(raw: str | None, default: str, *, cap: int | None = None) -> str:
    try:
        value = max(1.0, float(raw if raw is not None else default))
    except (TypeError, ValueError):
        value = float(default)
    if cap is not None:
        value = min(value, float(cap))
    return str(int(value)) if value.is_integer() else str(value)


def _source_lit_budget_seconds() -> str:
    explicit = _first_env(
        _FULLRAW_BUDGET_ENV,
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS",
    )
    if explicit is not None:
        return _seconds(explicit, str(_FULLRAW_SOURCE_LIT_BUDGET_CAP_SECONDS))
    inherited = _first_env(
        "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS",
        "RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS",
    )
    return _seconds(
        inherited, str(_FULLRAW_SOURCE_LIT_BUDGET_CAP_SECONDS),
        cap=_FULLRAW_SOURCE_LIT_BUDGET_CAP_SECONDS,
    )


def _source_lit_sweep_wait_seconds() -> str:
    explicit = _first_env(
        _FULLRAW_SWEEP_WAIT_ENV,
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS",
    )
    if explicit is not None:
        return _seconds(explicit, str(_FULLRAW_SOURCE_LIT_SWEEP_CAP_SECONDS))
    inherited = _first_env(
        "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS",
        "V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS",
        "V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS",
        "RESEARKA_FULLRAW_FOREGROUND_SWEEP_WAIT_SECONDS",
        "RESEARKA_FULLRAW_SWEEP_WAIT_SECONDS",
    )
    return _seconds(
        inherited, str(_FULLRAW_SOURCE_LIT_SWEEP_CAP_SECONDS),
        cap=_FULLRAW_SOURCE_LIT_SWEEP_CAP_SECONDS,
    )


def _fullraw_max_variants() -> int:
    for name in (
        _FULLRAW_MAX_VARIANTS_ENV,
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_MAX_VARIANTS",
        "V5_MEMO_FULL_RAW_MAX_VARIANTS",
        "RESEARKA_FULLRAW_MAX_VARIANTS",
    ):
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            continue
    return 2


_LONGEVITY_CONTEXT_TOKENS = frozenset({
    "ageing", "aging", "longevity", "lifespan", "senescence", "geroscience",
    "mortality", "survival", "frailty", "biological", "epigenetic", "clock",
})
_NON_BIOMEDICAL_DOMAINS = frozenset({
    "business_research", "economics_research", "finance_research",
    "management_research", "marketing_research", "ai_research",
})
_CONTEXT_ONLY_ROLES = frozenset({
    "economic/context only", "antecedent/support", "descriptive/modeling",
    "non-clinical/predictive", "other/mixed",
})
_OUTCOME_QUERY_TOKENS = frozenset({
    "employment", "margin", "margins", "performance", "price", "pricing",
    "productivity", "profit", "profitability", "return", "returns", "revenue", "risk",
    "sales", "volatility",
})
_SOURCE_LABEL_GENERIC_TOKENS = _GENERIC_TOPIC_TOKENS | _OUTCOME_QUERY_TOKENS | frozenset({
    "business", "businesses", "chain", "companies", "company", "firm", "firms",
    "market", "markets", "metric", "metrics", "source", "sources", "supply",
})
_SOURCE_LABEL_EDGE_TOKENS = frozenset({
    "and", "as", "by", "for", "from", "in", "into", "of", "on", "or", "the",
    "to", "with",
})
_SOURCE_TITLE_UNSAFE_PUBLIC_TOKENS = frozenset({
    "boundary", "caveat", "construct", "cross",
})
_DIRECTIONAL_TOPUP_QUERY_TOKENS = (
    "profitability", "revenue", "sales", "productivity", "margin", "returns",
    "employment", "price", "risk", "volatility",
)


def title_key(title: Any) -> str:
    raw = str(title or "").casefold()
    raw = re.sub(r"\b(?:19|20)\d{2}(?:\s*[-/]\s*(?:19|20)\d{2})?\b", " ", raw)
    raw = re.sub(r"\d+", " ", raw)
    raw = re.sub(r"[^a-z]+", " ", raw)
    return " ".join(token for token in raw.split() if token)


def _topic_tokens(topic: str) -> set[str]:
    tokens: set[str] = set()
    for token in title_key(topic).split():
        if len(token) < 3 or token in _GENERIC_TOPIC_TOKENS:
            continue
        tokens.add(token)
        if len(token) > 3 and token.endswith("s"):
            tokens.add(token[:-1])
    return tokens


def _topic_token_sequence(topic: str) -> list[str]:
    return [
        token for token in title_key(topic).split()
        if len(token) >= 3 and token not in _GENERIC_TOPIC_TOKENS
    ]


def _topic_token_coverage(topic: str, paper: Json) -> int:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    text = title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
        fact.get("population"), fact.get("intervention"), fact.get("endpoint"),
    )))
    words = text.split()
    return sum(
        1 for token in set(_topic_token_sequence(topic))
        if any(_token_matches(word, token) for word in words)
    )


def _non_biomedical(profile_slug: str) -> bool:
    return profile_slug in _NON_BIOMEDICAL_DOMAINS


def _display_direction(direction: str, profile_slug: str) -> str:
    if not _non_biomedical(profile_slug):
        return direction
    return {
        "directionally favorable": "directional estimate",
        "comparator/not favorable": "reference/comparator contrast",
        "non-clinical/predictive": "descriptive/modeling",
        "null/non-convergent": "null/mixed",
    }.get(direction, direction)


def _token_matches(word: str, token: str) -> bool:
    return word == token or (len(word) > 3 and word.endswith("s") and word[:-1] == token)


def topic_relevant(topic: str, paper: Json) -> bool:
    tokens = _topic_tokens(topic)
    if not tokens:
        return not title_key(topic).split()
    fact = paper.get("source_fact")
    if not isinstance(fact, dict):
        return True
    if not _fact_complete(fact):
        return False
    fact_text = ""
    fact_text = " ".join(
        str(fact.get(key) or "")
        for key in ("canonical_phrase", "population", "intervention", "endpoint")
    )
    primary_text = title_key(" ".join((
        str(paper.get("title") or ""),
        str(paper.get("paper_title") or ""),
        str(fact.get("intervention") or ""),
    )))
    if (
        len(tokens) == 2
        and not _paper_has_active_topic_phrase(paper, topic)
        and all(
            any(_token_matches(word, token) for word in primary_text.split())
            for token in tokens
        )
    ):
        return False
    text = title_key(" ".join((
        str(paper.get("title") or ""),
        str(paper.get("paper_title") or ""),
        fact_text,
    )))
    text_tokens = set(text.split())
    topic_domain_tokens = set(title_key(topic).split()) & {"ageing", "aging", "longevity"}
    if topic_domain_tokens and not (text_tokens & _LONGEVITY_CONTEXT_TOKENS):
        return False
    return bool(tokens & set(primary_text.split())) and (
        len(tokens & text_tokens) >= min(2, len(tokens))
    )


def relevant_papers(topic: str, papers: list[Json]) -> list[Json]:
    return [paper for paper in papers if isinstance(paper, dict) and topic_relevant(topic, paper)]


def query_variants(topic: str) -> tuple[str, ...]:
    raw = " ".join(title_key(topic).split())
    contextual = " ".join(
        token for token in raw.split()
        if len(token) >= 3 and token not in {"longevity", "anti"}
    )
    focused = " ".join(
        token for token in raw.split()
        if len(token) >= 3 and token not in _GENERIC_TOPIC_TOKENS
    )
    windows = [" ".join(pair) for pair in zip(raw.split(), raw.split()[1:], strict=False)]
    tokens = set(raw.split())
    outcome_context = (
        f"{focused} performance"
        if (
            focused
            and not (tokens & _LONGEVITY_CONTEXT_TOKENS)
            and not (tokens & _OUTCOME_QUERY_TOKENS)
        ) else ""
    )
    return tuple(dict.fromkeys(
        q for q in (outcome_context, focused, contextual, raw, *windows) if q
    ))


def _directional_topup_queries(topic: str) -> tuple[str, ...]:
    base = " ".join(_topic_token_sequence(topic))
    if not base:
        return ()
    topic_tokens = set(base.split())
    existing = set(query_variants(topic))
    return tuple(dict.fromkeys(
        query
        for token in _DIRECTIONAL_TOPUP_QUERY_TOKENS
        if token not in topic_tokens
        for query in (f"{base} {token}",)
        if query not in existing
    ))


def _fullraw_topic_papers(topic: str, limit: int) -> list[Json]:
    try:
        import httpx

        from scripts.run_topic_discovery import _seed_fullraw_papers
    except Exception:
        return []
    timeout = os.environ.get(
        _FULLRAW_TIMEOUT_ENV,
        os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_TIMEOUT_SECONDS",
                       os.environ.get("V5_MEMO_FULL_RAW_QUERY_TIMEOUT",
                                      os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "35"))),
    )
    budget = _source_lit_budget_seconds()
    sweep_wait = _source_lit_sweep_wait_seconds()
    max_variants = os.environ.get(
        _FULLRAW_MAX_VARIANTS_ENV,
        os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_MAX_VARIANTS",
                       os.environ.get(
                           "V5_MEMO_FULL_RAW_MAX_VARIANTS",
                           os.environ.get("RESEARKA_FULLRAW_MAX_VARIANTS", "2"),
                       )),
    )
    bounds = {
        "TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS": timeout,
        "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS": timeout,
        "TOPIC_DISCOVERY_SEED_PAPER_TIMEOUT_SECONDS": timeout,
        "TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS": budget,
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS": budget,
        "TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS": sweep_wait,
        "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS": budget,
        "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS": sweep_wait,
        "TOPIC_DISCOVERY_V5_MAX_VARIANTS": max_variants,
        "TOPIC_DISCOVERY_V5_MIN_SHARDS_SEARCHED": _int_env_floor(
            _FULLRAW_MIN_SHARDS_ENV,
            os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_MIN_SHARDS_SEARCHED"),
            _FULLRAW_MIN_SHARDS,
        ),
        "TOPIC_DISCOVERY_V5_MIN_SOURCES_SEARCHED": _int_env_floor(
            _FULLRAW_MIN_SOURCES_ENV,
            os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_MIN_SOURCES_SEARCHED"),
            _FULLRAW_MIN_SOURCES,
        ),
        "TOPIC_DISCOVERY_V5_REQUIRE_COMPLETE_SEARCH": "1",
    }
    old = {key: os.environ.get(key) for key in bounds}
    try:
        os.environ.update(bounds)
        with httpx.Client() as client:
            return _seed_fullraw_papers(topic, client=client, limit=limit)
    except Exception:
        return []
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _fullraw_relevant_papers(topic: str, limit: int, seen: set[str]) -> list[Json]:
    out: list[Json] = []
    for query in query_variants(topic)[:_fullraw_max_variants()]:
        for paper in _fullraw_topic_papers(query, max(25, limit * 6)):
            if not isinstance(paper, dict):
                continue
            title = paper.get("title") or paper.get("paper_title")
            topic_tokens = _topic_token_sequence(topic)
            title_tokens = set(title_key(title).split())
            if (
                not _text_has_topic(title, topic)
                and (
                    len(topic_tokens) < 3
                    or len(set(topic_tokens) & title_tokens)
                    < min(len(topic_tokens), max(2, len(topic_tokens) - 1))
                )
            ):
                continue
            key = paper_key(paper, paper.get("paper_id"))
            if not key or not title or key in seen:
                continue
            raw_fact = paper.get("source_fact")
            candidate = paper | {
                "id": key,
                "title": title,
                "source_fact": (
                    raw_fact if isinstance(raw_fact, dict) and raw_fact.get("canonical_phrase")
                    else _metadata_source_fact(topic, paper | {"title": title})
                ),
            }
            if not topic_relevant(topic, candidate):
                continue
            seen.add(key)
            out.append(candidate)
            if len(out) >= limit:
                return out
    return out


def _paper_context_family(paper: Json) -> str:
    raw_fact = paper.get("source_fact")
    fact: Json = raw_fact if isinstance(raw_fact, dict) else {}
    return context_family(" ".join(str(value or "") for value in (
        paper.get("title"),
        fact.get("population"),
        fact.get("intervention"),
        fact.get("endpoint"),
    )))


def _paper_outcome_family_key(topic: str, paper: Json) -> str:
    raw_fact = paper.get("source_fact")
    fact: Json = raw_fact if isinstance(raw_fact, dict) else {}
    label = _source_fact_endpoint_label(fact, topic, paper) if fact else ""
    if not label:
        label = " ".join(str(value or "") for value in (
            fact.get("endpoint"),
            fact.get("metric"),
            paper.get("title"),
            paper.get("paper_title"),
        ))
    return title_key(label)


def _paper_pico_frame_key(topic: str, paper: Json) -> str:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    population = context_family(fact.get("population") or paper.get("title"))
    exposure = title_key(fact.get("intervention") or "")
    outcome = title_key(
        fact.get("endpoint") or fact.get("metric") or fact.get("canonical_phrase") or "",
    )
    if not exposure or not outcome:
        return ""
    if population == "other source context":
        population = ""
    return "|".join(part for part in (population, exposure, outcome) if part)


def _coherent_pico_cluster(
    topic: str, papers: list[Json], min_sources: int, profile_slug: str,
) -> list[Json]:
    if not profile_slug or _non_biomedical(profile_slug):
        return []
    buckets: dict[str, list[Json]] = {}
    for paper in papers:
        key = _paper_pico_frame_key(topic, paper)
        if key:
            buckets.setdefault(key, []).append(paper)
    clusters = [rows for rows in buckets.values() if len(rows) >= min_sources]
    return max(clusters, key=len) if clusters else []


def _pico_frame_count(topic: str, papers: list[Json]) -> int:
    return len({
        key for paper in papers
        if (key := _paper_pico_frame_key(topic, paper))
    })


def _source_diverse_order(topic: str, papers: list[Json]) -> list[Json]:
    picked: list[Json] = []
    duplicate_outcomes: list[Json] = []
    duplicate_sources: list[Json] = []
    used_sources: set[str] = set()
    used_outcomes: set[str] = set()
    for paper in papers:
        source_key = source_identity_key(paper)
        outcome_key = _paper_outcome_family_key(topic, paper)
        if source_key and source_key in used_sources:
            duplicate_sources.append(paper)
            continue
        if outcome_key and outcome_key in used_outcomes:
            duplicate_outcomes.append(paper)
            continue
        picked.append(paper)
        if source_key:
            used_sources.add(source_key)
        if outcome_key:
            used_outcomes.add(outcome_key)
    for paper in duplicate_outcomes:
        source_key = source_identity_key(paper)
        if source_key and source_key in used_sources:
            duplicate_sources.append(paper)
            continue
        picked.append(paper)
        if source_key:
            used_sources.add(source_key)
    picked.extend(duplicate_sources)
    return picked


_DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE = (
    "directional association with within-source caveat"
)
_DIRECTIONAL_SOURCE_LIT_ROLES = frozenset({
    "directional association", _DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE,
    "directional estimate", "directionally favorable",
})
_BOUNDARY_SOURCE_LIT_ROLES = frozenset({"null/mixed", "descriptive/modeling"})
_BIOMED_EFFECT_DIRECTIONS = frozenset({
    "comparator/not favorable", "directionally favorable", "null/non-convergent",
})


def _directional_receipt_count(papers: list[Json], topic: str, profile_slug: str) -> int:
    return sum(
        1 for paper in papers
        if _paper_evidence_role(paper, topic, profile_slug) in _DIRECTIONAL_SOURCE_LIT_ROLES
    )


def _boundary_receipt_count(papers: list[Json], topic: str, profile_slug: str) -> int:
    return sum(
        1 for paper in papers
        if _paper_evidence_role(paper, topic, profile_slug) in _BOUNDARY_SOURCE_LIT_ROLES
    )


def _null_mixed_receipt_count(papers: list[Json], topic: str, profile_slug: str) -> int:
    return sum(
        1 for paper in papers
        if _paper_evidence_role(paper, topic, profile_slug) == "null/mixed"
    )


def _directional_floor_met(
    papers: list[Json], topic: str, profile_slug: str, min_sources: int,
) -> bool:
    required_directional = min(3, min_sources)
    directional_count = _directional_receipt_count(papers, topic, profile_slug)
    if directional_count >= required_directional:
        return True
    return (
        _non_biomedical(profile_slug)
        and directional_count >= 2
        and _null_mixed_receipt_count(papers, topic, profile_slug) >= 1
        and _boundary_receipt_count(papers, topic, profile_slug) >= 2
    )


def _source_lit_selection(
    topic: str, papers: list[Json], min_sources: int, profile_slug: str,
) -> list[Json]:
    ordered = _source_diverse_order(topic, papers)
    selected = ordered[:min_sources]
    required_directional = min(3 if _non_biomedical(profile_slug) else 2, min_sources)
    if (
        _non_biomedical(profile_slug)
        and _directional_receipt_count(selected, topic, profile_slug) < required_directional
    ):
        for candidate in ordered[min_sources:]:
            if (
                _paper_evidence_role(candidate, topic, profile_slug)
                not in _DIRECTIONAL_SOURCE_LIT_ROLES
            ):
                continue
            candidate_key = source_identity_key(candidate)
            if candidate_key and candidate_key in {
                source_identity_key(paper) for paper in selected
            }:
                continue
            for idx in range(len(selected) - 1, -1, -1):
                if (
                    _paper_evidence_role(selected[idx], topic, profile_slug)
                    in _DIRECTIONAL_SOURCE_LIT_ROLES
                ):
                    continue
                trial = [*selected]
                trial[idx] = candidate
                if source_identity_count(trial, require_substantive=True) >= min_sources:
                    selected = trial
                    break
            if _directional_receipt_count(selected, topic, profile_slug) >= required_directional:
                break
    if source_outlet_count(selected) < min_sources:
        selected_ids = {source_identity_key(paper) for paper in selected}
        for candidate in ordered[min_sources:]:
            candidate_id = source_identity_key(candidate)
            candidate_outlet = source_outlet_key(candidate)
            if not candidate_id or candidate_id in selected_ids or not candidate_outlet:
                continue
            if candidate_outlet in {source_outlet_key(paper) for paper in selected}:
                continue
            current_outlet_count = source_outlet_count(selected)
            for idx in range(len(selected) - 1, -1, -1):
                trial = [*selected]
                trial[idx] = candidate
                if (
                    source_identity_count(trial, require_substantive=True) >= min_sources
                    and source_outlet_count(trial) > current_outlet_count
                    and _directional_floor_met(trial, topic, profile_slug, min_sources)
                ):
                    selected = trial
                    selected_ids = {source_identity_key(paper) for paper in selected}
                    break
            if source_outlet_count(selected) >= min_sources:
                break
    return selected


def select_boundary_papers(
    topic: str, papers: list[Json], min_sources: int, *, strict_topic_coverage: bool = False,
    profile_slug: str = "",
) -> list[Json]:
    usable = [
        paper for paper in papers
        if isinstance(paper, dict)
        and topic_relevant(topic, paper)
        and str(paper.get("title") or "").strip()
        and citable_source_ref(paper)
    ]
    if len(usable) < min_sources:
        return usable
    topic_tokens = set(_topic_token_sequence(topic))
    if strict_topic_coverage and len(topic_tokens) >= 3:
        precise = [
            paper for paper in usable
            if _topic_token_coverage(topic, paper) >= len(topic_tokens)
        ]
        if len(precise) < min_sources:
            return precise
        usable = precise
    usable = sorted(usable, key=lambda paper: not _paper_has_substantive_source_fact(paper))
    substantive = [
        paper for paper in usable if _paper_has_substantive_source_fact(paper)
    ]
    if len(substantive) >= min_sources:
        if pico_cluster := _coherent_pico_cluster(
            topic, substantive, min_sources, profile_slug,
        ):
            return _source_lit_selection(topic, pico_cluster, min_sources, profile_slug)
        substantive_buckets: dict[str, list[Json]] = {}
        for paper in substantive:
            substantive_buckets.setdefault(_paper_context_family(paper), []).append(paper)
        coherent_substantive = [
            rows for family, rows in substantive_buckets.items()
            if family != "other source context" and len(rows) >= min_sources
        ]
        if coherent_substantive:
            return _source_lit_selection(
                topic, max(coherent_substantive, key=len), min_sources, profile_slug,
            )
        return _source_lit_selection(topic, substantive, min_sources, profile_slug)
    buckets: dict[str, list[Json]] = {}
    if pico_cluster := _coherent_pico_cluster(topic, usable, min_sources, profile_slug):
        return _source_lit_selection(topic, pico_cluster, min_sources, profile_slug)
    for paper in usable:
        buckets.setdefault(_paper_context_family(paper), []).append(paper)
    coherent = [
        rows for family, rows in buckets.items()
        if family != "other source context" and len(rows) >= min_sources
    ]
    if coherent:
        return _source_lit_selection(topic, max(coherent, key=len), min_sources, profile_slug)
    return _source_lit_selection(topic, usable, min_sources, profile_slug)


def boundary_quality(
    topic: str, papers: list[Json], min_sources: int, *,
    strict_topic_coverage: bool = False,
    profile_slug: str = "",
) -> tuple[bool, str]:
    usable = select_boundary_papers(
        topic, papers, min_sources, strict_topic_coverage=strict_topic_coverage,
        profile_slug=profile_slug,
    )
    if len(usable) < min_sources:
        return False, "source_floor_below_min"
    if source_identity_count(usable) < min_sources:
        return False, "source_diverse_floor_below_min"
    keys = [title_key(paper.get("title")) for paper in usable]
    counts = {key: keys.count(key) for key in set(keys) if key}
    if any(count >= max(3, min_sources - 1) for count in counts.values()):
        return False, "repeated_title_series"
    topic_key = title_key(topic)
    if topic_key and len({key for key in keys if key and key != topic_key}) < min_sources:
        return False, "repeated_title_series"
    families = [_paper_context_family(paper) for paper in usable]
    specific = [family for family in families if family != "other source context"]
    if (
        len(set(specific)) >= 2
        and max(specific.count(family) for family in set(specific)) < min_sources
    ):
        return False, "mixed_source_context_family"
    directions = [_paper_effect_direction(paper, topic) for paper in usable]
    if (
        profile_slug
        and not _non_biomedical(profile_slug)
        and directions
        and all(direction == "non-clinical/predictive" for direction in directions)
    ):
        return False, "predictive_model_only_bundle"
    if (
        profile_slug
        and not _non_biomedical(profile_slug)
        and directions
        and not any(direction in _BIOMED_EFFECT_DIRECTIONS for direction in directions)
        and _pico_frame_count(topic, usable) >= min(3, min_sources)
    ):
        return False, "context_only_source_literature_bundle"
    if _uniform_favorable_cross_pico(usable, min_sources):
        return False, "directionally_uniform_cross_pico_bundle"
    if _non_biomedical(profile_slug) and not _directional_floor_met(
        usable, topic, profile_slug, min_sources,
    ):
        return False, "directional_receipt_floor_below_min"
    return True, "ok"


def paper_key(paper: Json, default: Any = "") -> str:
    return str(paper.get("doi") or paper.get("pmid") or paper.get("id") or default or "")


def source_identity_key(paper: Json) -> str:
    raw = (
        paper.get("doi")
        or paper.get("pmid")
        or paper.get("id")
        or paper.get("url")
        or paper.get("paper_id")
        or paper.get("openalex_id")
        or ""
    )
    return str(raw).strip().casefold()


def _openalex_ref(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("https://openalex.org/"):
        raw = raw.rsplit("/", 1)[-1]
    return raw if raw.startswith("W") and raw[1:].isdigit() else ""


def citable_source_ref(paper: Json) -> bool:
    if paper.get("doi") or paper.get("url") or paper.get("pmid"):
        return True
    return any(_openalex_ref(paper.get(key)) for key in ("id", "paper_id", "openalex_id"))


def source_identity_count(papers: list[Json], *, require_substantive: bool = False) -> int:
    keys: set[str] = set()
    for paper in papers:
        if require_substantive and not _paper_has_substantive_source_fact(paper):
            continue
        key = source_identity_key(paper)
        if key:
            keys.add(key)
    return len(keys)


_SOURCE_OUTLET_FIELDS = (
    "journal_name", "journal", "venue", "publisher", "source",
    "source_outlet", "source_name", "container_title", "publication_venue",
)


def _explicit_source_outlet_key(paper: Json) -> str:
    for key in _SOURCE_OUTLET_FIELDS:
        value = paper.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title")
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item)
        if cleaned := title_key(value):
            return cleaned
    return ""


def source_outlet_key(paper: Json) -> str:
    if cleaned := _explicit_source_outlet_key(paper):
        return cleaned
    doi_prefix = str(paper.get("doi") or "").strip().casefold().split("/", 1)[0]
    for key in ("url", "source_url", "landing_page_url"):
        value = str(paper.get(key) or "").strip()
        host = urllib.parse.urlparse(value).netloc.casefold().removeprefix("www.")
        if host == "doi.org" and doi_prefix:
            return "doi-prefix:" + doi_prefix
        if host:
            return host
    return ""


def source_outlet_count(papers: list[Json]) -> int:
    return len({key for paper in papers if (key := source_outlet_key(paper))})


def source_outlet_metadata_count(papers: list[Json]) -> int:
    return sum(1 for paper in papers if _explicit_source_outlet_key(paper))


def source_outlet_diversity_below_min(papers: list[Json], min_sources: int) -> bool:
    return (
        source_outlet_metadata_count(papers) >= min_sources
        and source_outlet_count(papers) < min_sources
    )


def source_fact(item: Json) -> Json:
    return {
        key: item.get(key)
        for key in (
            "id", "canonical_phrase", "population", "intervention", "comparator",
            "endpoint", "metric", "source_tier", "source_excerpt",
        )
        if item.get(key) not in (None, "")
    }


def _metadata_source_fact(topic: str, paper: Json) -> Json:
    title = str(paper.get("title") or paper.get("paper_title") or "").strip()
    return {
        "canonical_phrase": f"Title-level source match: {title}",
        "endpoint": "source-literature relevance",
        "source_tier": "paper_metadata",
    }


def with_metadata_source_facts(topic: str, papers: list[Json]) -> list[Json]:
    return [
        paper if isinstance(paper.get("source_fact"), dict)
        else paper | {"source_fact": _metadata_source_fact(topic, paper)}
        for paper in papers
    ]


def fact_count(papers: list[Json]) -> int:
    return sum(1 for paper in papers if isinstance(paper.get("source_fact"), dict))


def _substantive_source_fact(fact: Json) -> bool:
    phrase = str(fact.get("canonical_phrase") or "").strip()
    if not phrase or phrase.casefold().startswith("title-level source match:"):
        return False
    if str(fact.get("source_tier") or "").casefold() == "paper_metadata":
        return False
    return bool(
        str(fact.get("population") or "").strip()
        or str(fact.get("intervention") or "").strip()
        or str(fact.get("endpoint") or fact.get("metric") or "").strip()
    )


def _paper_has_substantive_source_fact(paper: Json) -> bool:
    fact = paper.get("source_fact")
    if not isinstance(fact, dict) or not _substantive_source_fact(fact):
        return False
    phrase_key = title_key(fact.get("canonical_phrase"))
    if not phrase_key:
        return False
    for key in (
        title_key(paper.get("title")),
        title_key(paper.get("paper_title")),
    ):
        if not key:
            continue
        if phrase_key == key:
            return False
    return True


def substantive_fact_count(papers: list[Json]) -> int:
    return sum(
        1 for paper in papers
        if _paper_has_substantive_source_fact(paper)
    )


def _short_finding(value: str, limit: int = 170) -> str:
    text = " ".join(str(value or "").split()).rstrip(".")
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(".,;") + "..."


def _text_has_topic(value: Any, topic: str) -> bool:
    topic_tokens = _topic_token_sequence(topic)
    words = title_key(value).split()
    if not topic_tokens:
        return False
    if len(topic_tokens) == 1:
        return any(_token_matches(word, topic_tokens[0]) for word in words)
    for idx, word in enumerate(words):
        if not _token_matches(word, topic_tokens[0]):
            continue
        cursor = idx
        for token in topic_tokens[1:]:
            match_idx = next(
                (pos for pos in range(cursor + 1, min(len(words), idx + len(topic_tokens) + 1))
                 if _token_matches(words[pos], token)),
                -1,
            )
            if match_idx < 0:
                break
            cursor = match_idx
        else:
            return True
    return False


def _text_has_topic_phrase(value: Any, topic: str) -> bool:
    topic_tokens = _topic_token_sequence(topic)
    words = title_key(value).split()
    if not topic_tokens:
        return False
    width = len(topic_tokens)
    return any(
        all(
            _token_matches(word, token)
            for word, token in zip(words[idx:idx + width], topic_tokens, strict=False)
        )
        for idx in range(0, len(words) - width + 1)
    )


def _paper_has_active_topic_phrase(paper: Json, topic: str) -> bool:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    return (
        _text_has_topic_phrase(paper.get("title") or paper.get("paper_title"), topic)
        or _text_has_topic_phrase(fact.get("intervention"), topic)
    )


def _topic_effect_ablated(finding: str, topic: str) -> bool:
    return bool(
        topic
        and _text_has_topic(finding, topic)
        and re.search(
            r"\b(?:abolish(?:ed|es)?|block(?:ed|s)?|blunt(?:ed|s)?|diminish(?:ed|es)?|"
            r"inhibit(?:ed|s|ion)?|knockdown|reduc(?:ed|es))\b[^.;]{0,120}"
            r"\b(?:anti|benefit|effect|function|protect|response|activity)",
            finding.casefold(),
        )
    )


def _effect_direction(finding: str, fact: Json | None = None, topic: str = "") -> str:
    text = finding.casefold()
    fact = fact or {}
    if _looks_method_or_aim_only(text):
        return "non-clinical/predictive"
    if any(term in text for term in (
        "cost-effect", "cost effectiveness", "qaly", "£", "$", "economic",
    )):
        return "economic/context only"
    if any(term in text for term in (
        "machine learning", "machine-learning", "deep learning", "predict",
        "prediction", "predictive", "chronological age", "age-prediction",
        "diagnosis", "diagnostic", "detection", "screening", "classification",
        "classifier", "accuracy", "auc", "fundus", "oct", "image", "images",
        "imaging", "neural network", "super-resolution", "segmentation",
    )):
        return "non-clinical/predictive"
    if _topic_effect_ablated(finding, topic):
        return "directionally favorable"
    if topic and _text_has_topic(fact.get("comparator"), topic) and not _text_has_topic(
        fact.get("intervention"), topic,
    ):
        return "comparator/not favorable"
    if any(term in text for term in (
        "no significant", "no effect", "null", "p = 0.83", "p=0.83",
        "not statistically different", "indistinguishable from zero",
        "not associated", "no association", "insignificant effect",
        "insignificant effects", "insignificant influence",
        "insignificant impact", "hypothesis rejected",
        "hypotheses rejected", "hypotheses have been rejected",
        "hypothesis has been rejected", "rejected", "not supported",
        "failed to support",
    )):
        return "null/non-convergent"
    if re.search(r"\b(?:hazard ratio|hr|risk ratio|relative risk)\b[^.;]{0,80}\b0\.\d+", text):
        return "directionally favorable"
    if any(term in text for term in (
        "lower", "lowered", "reduce", "reduces", "reduced", "reduction",
        "protective", "better", "improve", "improves", "improved",
        "benefit", "decrease", "decreases", "decreased", "extends lifespan",
        "increased lifespan", "longer lifespan", "attenuat", "restore",
        "restored", "dampen", "dampening", "odds ratio of 0.", "hr = 0.", "hr for",
        "ranked as the best", "ranked best", "best approach", "ranked first",
        "positive and significant", "significant positive", "significantly influences",
        "significantly influence", "positive effect", "positive impact",
        "positive influence", "promote", "promotes", "promoted",
    )):
        return "directionally favorable"
    return "other/mixed"


def _looks_method_or_aim_only(text: str) -> bool:
    return bool(
        re.search(r"\b(?:aim|purpose|objective)s? of (?:this|the) study\b", text)
        or (
            re.search(
                r"\b(?:method|approach|framework|model|criteria|sub-criteria|"
                r"relative weights?|analytic hierarchy process|ahp|vikor|"
                r"fuzzy|nominal group technique)\b",
                text,
            )
            and not re.search(
                r"\b(?:positive|negative|rejected|not supported|"
                r"no significant|improv(?:e|es|ed|ing|ement)?|"
                r"reduc(?:e|es|ed|ing|tion)?|"
                r"increas(?:e|es|ed|ing)?|decreas(?:e|es|ed|ing)?|effect|"
                r"rank(?:ed|ing)?|best)\b",
                text,
            )
        )
    )


def _display_finding(fact: Json, direction: str = "") -> str:
    finding = str(fact.get("canonical_phrase") or "").strip()
    if not finding:
        return ""
    if direction == "non-clinical/predictive" and _looks_method_or_aim_only(finding.casefold()):
        if re.search(
            r"\b(?:important|importance|ranking|ranked|criterion|criteria|ahp|vikor)\b",
            finding,
            flags=re.I,
        ) and not re.search(r"\b(?:aim|purpose|objective)s? of (?:this|the) study\b", finding, flags=re.I):
            return finding
        return "method or modelling receipt; no direct effect estimate extracted"
    return finding


def _paper_effect_direction(paper: Json, topic: str = "") -> str:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    text = " ".join(str(value or "") for value in (
        fact.get("canonical_phrase"),
        fact.get("endpoint"),
        fact.get("metric"),
    ))
    direction = _effect_direction(text, fact, topic)
    if direction != "other/mixed":
        return direction
    if _paper_has_active_topic_phrase(paper, topic) and re.search(
        r"\b(?:greater increases?|increas(?:e|ed|es|ing)|gains?|improv(?:e|ed|es|ing))\b",
        text.casefold(),
    ) and not re.search(
        r"\b(?:death|mortality|risk|adverse|harm)\b[^.;]{0,50}\bincreas"
        r"|\bonly observed in (?:the )?(?:cg|control|comparator|placebo)",
        text.casefold(),
    ):
        return "directionally favorable"
    title_direction = _effect_direction(str(paper.get("title") or ""), fact, topic)
    return "non-clinical/predictive" if title_direction == "non-clinical/predictive" else direction


def _non_bio_directional_performance_receipt(paper: Json) -> bool:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    text = title_key(" ".join(str(value or "") for value in (
        paper.get("title"),
        paper.get("paper_title"),
        fact.get("canonical_phrase"),
        fact.get("endpoint"),
        fact.get("metric"),
    )))
    return bool(set(text.split()) & {
        "performance", "profitability", "productivity", "returns", "return",
        "revenue", "value", "margin", "margins",
    })


def _non_bio_mixed_significant_performance_receipt(paper: Json) -> bool:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    text = " ".join(str(value or "") for value in (
        fact.get("canonical_phrase"),
        fact.get("endpoint"),
        fact.get("metric"),
    )).casefold()
    return (
        _non_bio_directional_performance_receipt(paper)
        and bool(re.search(
            r"\b(?:significant(?:ly)?\s+(?:effect|effects|influence|impact|"
            r"enhanc(?:e|es|ed|ing)|"
            r"increas(?:e|es|ed|ing)|improv(?:e|es|ed|ing)|"
            r"reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing))|"
            r"positive\s+significant|significant\s+positive)\b",
            text,
        ))
        and not re.search(r"\b(?:rejected|not supported|failed to support|no significant)\b", text)
    )


def _inferred_non_bio_endpoint(text: str) -> str:
    words = set(title_key(text).split())
    if "price" in words or "prices" in words:
        return "price pass-through"
    if "employment" in words:
        return "employment effects"
    if "poverty" in words and "elasticity" in words:
        return "poverty elasticity"
    if "earnings" in words and "inequality" in words:
        return "earnings inequality share"
    return ""


def _non_bio_numeric_direction_receipt(paper: Json) -> bool:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    text = " ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
        fact.get("endpoint"), fact.get("metric"),
    )).casefold()
    if re.search(r"\b(?:no significant|not statistically different|not supported)\b", text):
        return False
    return bool(
        re.search(r"\d|percent|percentage|point|elasticit(?:y|ies)", text)
        and re.search(
            r"\b(?:accounts? for|effect|effects|elasticit(?:y|ies)|estimat(?:e|es|ed)|fall|"
            r"increas(?:e|es|ed|ing)?|pass(?:ed)? through|pass-through|rang(?:e|es)|"
            r"reduc(?:e|es|ed|ing)?|rose|"
            r"translates? into)\b",
            text,
        )
    )


def _non_bio_directional_with_subdimension_caveat(paper: Json) -> bool:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    text = " ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
        fact.get("endpoint"), fact.get("metric"),
    )).casefold()
    return (
        _non_bio_directional_performance_receipt(paper)
        and bool(re.search(
            r"\b(?:positive\s+and\s+significant|significant(?:ly)?\s+"
            r"(?:effect|effects|influence|impact|influences|impacts))\b",
            text,
        ))
        and bool(re.search(r"\b(?:insignificant|non-significant)\s+effect\b", text))
        and not re.search(r"\b(?:rejected|not supported|failed to support)\b", text)
    )


def _fact_complete(fact: Json) -> bool:
    phrase = str(fact.get("canonical_phrase") or "").strip()
    if not phrase:
        return True
    if any(phrase.count(left) > phrase.count(right) for left, right in (("(", ")"), ("[", "]"))):
        return False
    return not re.search(r"(95%\s*ci|p\s*[=<])\s*[:;,]?\s*$", phrase, flags=re.I)


def _endpoint_key(fact: Json) -> str:
    return title_key(fact.get("endpoint") or fact.get("metric") or "")


def _uniform_favorable_cross_pico(papers: list[Json], min_sources: int) -> bool:
    facts = [
        fact for paper in papers
        if isinstance((fact := paper.get("source_fact")), dict)
        and str(fact.get("canonical_phrase") or "").strip()
    ]
    if len(facts) < min_sources:
        return False
    directions = [
        _effect_direction(str(fact.get("canonical_phrase") or ""), fact)
        for fact in facts[:min_sources]
    ]
    endpoints = {
        endpoint for fact in facts[:min_sources]
        if (endpoint := _endpoint_key(fact))
    }
    return (
        len(endpoints) >= 3
        and bool(directions)
        and all(direction == "directionally favorable" for direction in directions)
    )


def _paper_evidence_role(paper: Json, topic: str = "", profile_slug: str = "") -> str:
    direction = _paper_effect_direction(paper, topic)
    if (
        _non_biomedical(profile_slug)
        and direction == "null/non-convergent"
        and _non_bio_directional_with_subdimension_caveat(paper)
    ):
        return _DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE
    if _non_biomedical(profile_slug):
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        text = title_key(" ".join(str(value or "") for value in (
            paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
            fact.get("endpoint"), fact.get("metric"), fact.get("intervention"),
        )))
        exposure = title_key(_exposure_context_label(paper, non_bio=True))
        if direction == "null/non-convergent" and "firm performance" in text:
            return "null/mixed"
        if _non_bio_mixed_significant_performance_receipt(paper):
            return "directional association"
        if "antecedent" in exposure:
            return "antecedent/support"
        if "context" in exposure or "modeling" in exposure or "modelling" in exposure:
            return "descriptive/modeling"
    if _non_biomedical(profile_slug) and direction == "other/mixed":
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        text = title_key(" ".join(str(value or "") for value in (
            paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
            fact.get("endpoint"), fact.get("metric"), fact.get("intervention"),
        )))
        if "antecedent" in text or "mediat" in text:
            return "antecedent/support"
    if (
        _non_biomedical(profile_slug)
        and direction == "other/mixed"
        and _non_bio_mixed_significant_performance_receipt(paper)
    ):
        return "directional association"
    if (
        _non_biomedical(profile_slug)
        and direction in {"other/mixed", "economic/context only"}
        and _non_bio_numeric_direction_receipt(paper)
    ):
        return "directional association"
    label = _display_direction(direction, profile_slug)
    if label != "directional estimate" or not _non_biomedical(profile_slug):
        return label
    if _non_bio_directional_performance_receipt(paper):
        return "directional association"
    title = title_key(paper.get("title") or paper.get("paper_title") or "")
    exposure = title_key(_exposure_context_label(paper, non_bio=True))
    if "antecedent" in exposure or "factors affecting" in title:
        return "antecedent/support"
    return "directional association"


def _memo_role_label(label: str, profile_slug: str = "") -> str:
    if not _non_biomedical(profile_slug):
        return label
    return {
        "null/mixed": "null/mixed metric-scope caveat",
        "other/mixed": "context-only receipt",
        "null/non-convergent": "null/mixed metric-scope caveat",
    }.get(label, label)


def _table_cell(value: Any, limit: int = 90) -> str:
    text = str(value or "").replace("|", "/").strip()
    return _short_finding(text, limit) or "-"


def _heterogeneity_matrix_lines(
    papers: list[Json], topic: str = "", profile_slug: str = "",
) -> list[str]:
    header = [
        "| Outcome family | Receipt | Evidence role | Population/setting | Metric | Extracted finding |",
        "|---|---|---|---|---|---|",
    ]
    effect_rows: list[str] = []
    context_rows: list[str] = []
    non_bio = _non_biomedical(profile_slug)
    for paper in papers:
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        metric = _endpoint_context_label(paper, topic, non_bio=non_bio)
        direction = _paper_effect_direction(paper, topic)
        finding = _display_finding(fact, direction)
        role = _paper_evidence_role(paper, topic, profile_slug)
        family = "modeling-context" if role == "descriptive/modeling" else _outcome_family(metric)
        row = (
            "| "
            + " | ".join((
                _table_cell(family, 40),
                _table_cell(paper.get("title") or "Untitled source", 72),
                _table_cell(_memo_role_label(role, profile_slug), 52),
                _table_cell(_source_context_label(paper, non_bio=non_bio), 48),
                _table_cell(metric, 40),
                _table_cell(finding, 110),
            ))
            + " |"
        )
        if role in _DIRECTIONAL_SOURCE_LIT_ROLES | {"null/mixed", "null/non-convergent"}:
            effect_rows.append(row)
        else:
            context_rows.append(row)
    rows = []
    if non_bio:
        rows.extend([
            (
                "Matrix guard: effect-bearing rows below are metric-specific "
                "source facts, not a pooled comparison; context-only rows are "
                "excluded from effect support."
            ),
            "",
        ])
    rows.extend(["### Effect-bearing comparison", "", *header])
    rows.extend(effect_rows or ["| - | - | - | - | - | No effect-bearing receipts extracted. |"])
    if context_rows:
        rows.extend(["", "### Context-only receipts", "", *header, *context_rows])
    return rows


def _direction_rows(papers: list[Json], topic: str = "", profile_slug: str = "") -> list[str]:
    rows: list[str] = []
    for paper in papers:
        fact = paper.get("source_fact")
        finding = ""
        if isinstance(fact, dict):
            finding = str(fact.get("canonical_phrase") or "").strip()
        title = str(paper.get("title") or "Untitled source").strip()
        direction = _paper_effect_direction(paper, topic)
        label = _paper_evidence_role(paper, topic, profile_slug)
        if isinstance(fact, dict):
            finding = _display_finding(fact, direction)
        note = ""
        if direction == "comparator/not favorable":
            note = (
                " topic is the reference/comparator here; label is metric-specific,"
                " not a broad policy verdict"
                if _non_biomedical(profile_slug) else
                " topic is comparator here; label is endpoint-specific, not a broad efficacy verdict"
            )
        if direction == "directionally favorable" and _topic_effect_ablated(finding, topic):
            note = " mechanistic ablation supports the topic effect; not a comparator outcome"
        if direction == "directionally favorable" and re.search(r"\b(?:β|beta)\s*[=:-]\s*-", finding):
            note = " direction follows receipt wording; coefficient sign is source-specific"
        rows.append(
            f"- {label}: {title}"
            + (f" — {finding}" if finding else "")
            + (f" ({note})" if note else ""),
        )
    return rows


def _direction_category_lines(topic: str, profile_slug: str = "") -> list[str]:
    topic_text = topic or "the selected topic"
    if _non_biomedical(profile_slug):
        return [
            f"- directional association: source-level direction with design caveat; {topic_text} "
            "is the policy, exposure, method, or practice linked to the named metric, "
            "not a pooled effect-size estimate or efficacy verdict.",
            "- directional association with within-source caveat: source-level direction "
            "plus an explicit null/mixed subdimension inside the same receipt; do not "
            "read as uniformly directional support.",
            "- antecedent/support: the receipt explains inputs, enablers, or "
            "context for the topic rather than a clean topic-to-outcome effect.",
            f"- reference/comparator contrast: {topic_text} is the reference side "
            "of the extracted contrast; interpret only within that metric.",
            "- economic/context only: the receipt reports cost, market, prevalence, "
            "policy, or institutional context rather than a policy-effect estimate.",
            "- descriptive/modeling: the receipt reports modelling or prediction "
            "rather than a policy-effect estimate.",
            "- null/mixed metric-scope caveat: the receipt reports null, mixed, "
            "or rejected findings for the named metric/outcome and must not be "
            "softened into directional support.",
            "- context-only receipt: the extracted finding is retained as adjacent "
            "scope context, not direction-bearing support for the named metric.",
        ]
    return [
        f"- directionally favorable: {topic_text} is the intervention/exposure "
        "and the reported clinical endpoint favors that arm.",
        f"- comparator/not favorable: {topic_text} is the comparator arm; the "
        "label is limited to that head-to-head endpoint.",
        "- economic/context only: the receipt reports cost, QALY, or economic "
        "context rather than a clinical efficacy endpoint.",
        "- non-clinical/predictive: the receipt reports descriptive modelling, "
        "prediction, or age-clock performance rather than an intervention endpoint.",
        "- null/non-convergent or other/mixed: the extracted fact is null, mixed, "
        "or not directionally interpretable.",
    ]


def _used_direction_category_lines(
    papers: list[Json], topic: str = "", profile_slug: str = "",
) -> list[str]:
    used_roles = {
        _paper_evidence_role(paper, topic, profile_slug)
        for paper in papers
    }
    lines = _direction_category_lines(topic, profile_slug)
    out: list[str] = []
    for line in lines:
        label = line.removeprefix("- ").split(":", 1)[0]
        if (
            label in used_roles
            or (
                label == "null/mixed metric-scope caveat"
                and bool(used_roles & {"null/mixed", "null/non-convergent"})
            )
            or (
                label == "context-only receipt"
                and bool(used_roles & {"other/mixed"})
            )
        ):
            out.append(line)
    return out or lines


def _direction_summary(papers: list[Json], topic: str = "", profile_slug: str = "") -> str:
    groups: dict[str, list[str]] = {
        "directionally favorable": [],
        "null/non-convergent": [],
        "comparator/not favorable": [],
        "economic/context only": [],
        "non-clinical/predictive": [],
        "other/mixed": [],
    }
    for paper in papers:
        fact = paper.get("source_fact")
        if not isinstance(fact, dict):
            continue
        finding = _display_finding(fact, _paper_effect_direction(paper, topic))
        if not finding:
            continue
        label = _paper_evidence_role(paper, topic, profile_slug)
        groups.setdefault(label, []).append(_short_finding(finding, 120))
    parts = [
        f"{_memo_role_label(label, profile_slug)}: {len(values)} receipt(s)"
        for label, values in groups.items() if values
    ]
    return " | ".join(parts) if parts else "direction of effect is not extractable from the retrieved facts"


def _evidence_role_summary(papers: list[Json], topic: str = "", profile_slug: str = "") -> str:
    directional = nullish = context_only = 0
    for paper in papers:
        label = _paper_evidence_role(paper, topic, profile_slug)
        if label in _DIRECTIONAL_SOURCE_LIT_ROLES:
            directional += 1
        elif label in {"null/mixed", "null/non-convergent"}:
            nullish += 1
        elif label in {
            "antecedent/support", "descriptive/modeling", "non-clinical/predictive",
            "other/mixed",
        }:
            context_only += 1
    parts = [
        f"direction-bearing receipts: {directional}",
        f"null/mixed metric-scope caveat receipts: {nullish}",
    ]
    if context_only:
        parts.append(
            f"context/antecedent/model receipts: {context_only} excluded from effect support",
        )
    return "; ".join(parts)


def _direction_contrast_sentence(
    papers: list[Json], topic: str = "", profile_slug: str = "",
) -> str:
    groups: dict[str, list[str]] = {}
    for paper in papers:
        fact = paper.get("source_fact")
        if not isinstance(fact, dict):
            continue
        direction = _paper_effect_direction(paper, topic)
        finding = _display_finding(fact, direction)
        if not finding:
            continue
        label = _paper_evidence_role(paper, topic, profile_slug)
        title = str(paper.get("title") or "Untitled source").strip()
        groups.setdefault(label, []).append(
            f"{title}: {_short_finding(finding, 110)}",
        )
    if len(groups) < 2:
        return ""
    priority = (
        "directional association", _DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE,
        "directional estimate", "null/mixed", "reference/comparator contrast",
        "antecedent/support", "descriptive/modeling", "economic/context only", "other/mixed",
        "directionally favorable", "null/non-convergent", "comparator/not favorable",
        "non-clinical/predictive",
    )
    parts: list[str] = []
    for label in priority:
        values = groups.get(label)
        if values:
            parts.append(f"{_memo_role_label(label, profile_slug)}: {values[0]}")
    for label, values in groups.items():
        if label not in priority and values:
            parts.append(f"{_memo_role_label(label, profile_slug)}: {values[0]}")
    return "Concrete contrast: " + "; ".join(parts[:4]) + "."


def _cross_setting_contrast_sentence(
    papers: list[Json], topic: str = "", profile_slug: str = "",
) -> str:
    if not _non_biomedical(profile_slug):
        return ""
    clauses: list[str] = []
    for paper in papers:
        if _paper_evidence_role(paper, topic, profile_slug) not in _DIRECTIONAL_SOURCE_LIT_ROLES:
            continue
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        finding = _display_finding(fact, _paper_effect_direction(paper, topic))
        metric = _source_fact_endpoint_label(fact, topic, paper)
        setting = _source_context_label(paper, non_bio=True)
        if finding and metric and setting:
            clauses.append(f"{metric} in {setting}: {_short_finding(finding, 105)}")
    if len(clauses) < 2:
        return ""
    return (
        "Cross-setting contrast: "
        + "; ".join(clauses[:5])
        + " are separate setting-metric cells, not one pooled topic effect."
    )


def _pico_gap(facts: list[Json], profile_slug: str = "") -> str:
    for fact in facts:
        population = str(fact.get("population") or "").strip()
        intervention = str(fact.get("intervention") or "").strip()
        comparator = str(fact.get("comparator") or "").strip()
        outcome = str(fact.get("endpoint") or fact.get("metric") or "").strip()
        if population and intervention and comparator and outcome:
            return (
                "A stronger memo needs a matched design that reduces this "
                f"bundle's scope spread: hold metric={outcome} constant, "
                f"compare policy/exposure={intervention} against a clearly "
                f"matched reference group, and test it in a setting adjacent to "
                f"but not duplicating {population}."
            ) if _non_biomedical(profile_slug) else (
                "A stronger memo needs a new matched PICO that reduces this "
                f"bundle's heterogeneity: hold outcome={outcome} constant, "
                f"compare intervention/exposure={intervention} against a clearly "
                f"matched comparator, and test it in a population adjacent to "
                f"but not duplicating {population}."
            )
    return (
        "A stronger memo needs one matched design: one setting, one policy/exposure, "
        "one comparator/reference group, and one named metric."
        if _non_biomedical(profile_slug) else
        "A stronger memo needs one matched PICO: one population, one "
        "intervention/exposure, one comparator, and one named outcome."
    )


def _direction_signal_label(papers: list[Json], topic: str = "", profile_slug: str = "") -> str:
    directions = [_paper_effect_direction(paper, topic) for paper in papers]
    if _non_biomedical(profile_slug):
        if directions and all(direction == "directionally favorable" for direction in directions):
            return "directionally consistent estimates across separate contexts"
        if "directionally favorable" in directions and "non-clinical/predictive" in directions:
            return "policy/exposure estimates plus separate descriptive evidence"
        if "directionally favorable" in directions:
            return "directional estimates with context limits"
        if directions and all(direction == "non-clinical/predictive" for direction in directions):
            return "descriptive predictive signals, not policy-effect evidence"
        return "context-dependent, not uniformly convergent findings"
    if directions and all(direction == "directionally favorable" for direction in directions):
        return "directionally consistent signals across heterogeneous contexts"
    if "directionally favorable" in directions and "non-clinical/predictive" in directions:
        return "endpoint-specific intervention signals plus separate predictive evidence"
    if "directionally favorable" in directions:
        return "endpoint-specific favorable signals with context limits"
    if directions and all(direction == "non-clinical/predictive" for direction in directions):
        return "descriptive predictive signals, not intervention evidence"
    return "context-dependent, not uniformly convergent associations"


def _source_context_label(paper: Json, *, non_bio: bool) -> str:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    population = str(fact.get("population") or "").strip()
    if not non_bio:
        return population
    generic = {"", "firm", "firms", "companies", "businesses", "organizations"}
    if title_key(population) not in generic:
        return population
    text = title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
        fact.get("endpoint"), fact.get("metric"),
    )))
    labels: list[str] = []
    for token, label in (
        ("automotive", "automotive firms"),
        ("chemical", "chemical industrial companies"),
        ("manufacturing", "manufacturing firms"),
        ("retail", "retail firms"),
        ("bank", "banking/financial firms"),
        ("financial", "banking/financial firms"),
        ("market", "market setting"),
    ):
        if token in text.split() and label not in labels:
            labels.append(label)
    return join_contexts(labels[:2]) if labels else (population or "mixed firms/settings")


def _exposure_context_label(paper: Json, *, non_bio: bool) -> str:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    base = str(fact.get("intervention") or "").strip()
    if not non_bio:
        return base
    title = title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"),
    )))
    base_key = title_key(base)
    if (
        base and base_key and base_key in title
        and "factors affecting" not in title
        and f"effect of {base_key}" in title
    ):
        return base
    text = title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"), base,
    )))
    tokens = set(text.split())
    if {"fuzzy", "ahp"} <= tokens or "vikor" in text:
        return "Pythagorean fuzzy AHP-VIKOR modelling"
    if {"flexibility", "agility"} & tokens:
        return "flexibility, collaboration, and agility antecedents"
    if {"artificial", "intelligence"} <= tokens or "adaptive" in tokens or "collaboration" in text:
        return "AI, adaptive capability, and collaboration antecedents"
    if "visibility" in text:
        return "supply chain visibility and capability antecedents"
    if "disruption" in text:
        return "supply chain disruption context"
    return base


def _topic_performance_endpoint(topic: str, endpoint: str) -> str:
    topic_words = topic.replace("_", " ").split()
    endpoint_words = str(endpoint or "").replace("_", " ").split()
    if (
        len(topic_words) >= 3
        and topic_words[-1] == "performance"
        and endpoint_words == topic_words[:-1]
    ):
        return " ".join((*endpoint_words[:-1], "performance"))
    return ""


def _performance_endpoint_label(topic: str, text: str) -> str:
    topic_text = topic.replace("_", " ")
    if "performance" not in text or "performance" in topic_text:
        return ""
    words = topic_text.split()
    if len(words) >= 2:
        candidate = " ".join((*words[:-1], "performance"))
        if candidate in text or "and performance" in text:
            return candidate
    return f"{topic_text} performance"


def _endpoint_context_label(paper: Json, topic: str, *, non_bio: bool) -> str:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    endpoint = str(fact.get("endpoint") or fact.get("metric") or "").strip()
    if non_bio:
        inferred = _inferred_non_bio_endpoint(" ".join(str(value or "") for value in (
            endpoint, paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
        )))
        if inferred:
            return inferred
    if non_bio and title_key(endpoint) == "scp":
        return "supply chain performance"
    if not non_bio or not _endpoint_mirrors_topic(endpoint, topic):
        return _topic_performance_endpoint(topic, endpoint) or endpoint
    text = title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
    )))
    return _performance_endpoint_label(topic, text) or endpoint


def _outcome_family(endpoint: Any) -> str:
    text = title_key(endpoint)
    words = set(text.split())
    if "firm" in words or "firms" in words:
        return "firm-level"
    if "supply" in words and "chain" in words:
        return "chain-level"
    if "model" in words or "scoring" in words:
        return "business-outcome"
    if "business" in words:
        return "business-outcome"
    return " ".join(text.split()[:3]) or "outcome-specific"


def _outcome_families(facts: list[Json]) -> list[str]:
    seen = {
        _outcome_family(fact.get("endpoint") or fact.get("metric"))
        for fact in facts
        if str(fact.get("endpoint") or fact.get("metric") or "").strip()
    }
    priority = ("firm-level", "chain-level", "business-outcome")
    ordered = [family for family in priority if family in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered


def _endpoint_mirrors_topic(endpoint: str, topic: str) -> bool:
    endpoint_key = title_key(endpoint)
    topic_key = title_key(topic)
    return bool(endpoint_key and endpoint_key == topic_key)


def _source_fact_endpoint_label(fact: Json, topic: str, paper: Json | None = None) -> str:
    endpoint = str(fact.get("endpoint") or fact.get("metric") or "").strip()
    inferred = _inferred_non_bio_endpoint(" ".join(str(value or "") for value in (
        endpoint, (paper or {}).get("title"), (paper or {}).get("paper_title"),
        fact.get("canonical_phrase"),
    )))
    if inferred:
        return inferred
    if title_key(endpoint) == "scp":
        return "supply chain performance"
    topic_performance = _topic_performance_endpoint(topic, endpoint)
    if topic_performance:
        return topic_performance
    if _endpoint_mirrors_topic(endpoint, topic):
        return "the stated downstream outcome"
    return endpoint


def _title_endpoint_label(label: str, topic: str, papers: list[Json]) -> str:
    topic_performance = _topic_performance_endpoint(topic, label)
    if topic_performance:
        return topic_performance
    if label != "the stated downstream outcome":
        return label
    source_text = title_key(" ".join(str(paper.get("title") or "") for paper in papers))
    return _performance_endpoint_label(topic, source_text) or topic.replace("_", " ")


def _title_endpoint_labels(labels: list[str], topic: str, papers: list[Json]) -> list[str]:
    return list(dict.fromkeys(
        _title_endpoint_label(label, topic, papers)
        for label in labels
        if label
    ))


def _topic_title_label(topic: str) -> str:
    words = topic.replace("_", " ").split()
    if len(words) > 2 and words[-1] in {
        "effect", "effects", "outcome", "outcomes", "performance",
    }:
        words = words[:-1]
    return " ".join(words) or topic.replace("_", " ")


def _topic_signal_label(topic: str, *, non_bio: bool = False) -> str:
    words = _topic_title_label(topic).split()
    if non_bio and len(words) > 2 and words[-1] in {
        "firm", "firms", "company", "companies", "organization", "organizations",
    }:
        words = words[:-1]
    return " ".join(words) or _topic_title_label(topic)


def _source_label_text(paper: Json) -> str:
    fact = paper.get("source_fact")
    fact = fact if isinstance(fact, dict) else {}
    return title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"),
        fact.get("endpoint"), fact.get("metric"),
    )))


def _source_grounded_topic_label(topic: str, papers: list[Json], profile_slug: str) -> str:
    non_bio = _non_biomedical(profile_slug)
    label = _topic_signal_label(topic, non_bio=non_bio)
    if not non_bio or not papers:
        return label
    label_tokens = [
        token for token in title_key(label).split()
        if len(token) >= 3 and token not in _GENERIC_TOPIC_TOKENS
    ]
    corpus_words = " ".join(_source_label_text(paper) for paper in papers).split()
    trimmed_unsupported_suffix = False
    if (
        label_tokens
        and label_tokens[-1] in _OUTCOME_QUERY_TOKENS
        and not any(_token_matches(word, label_tokens[-1]) for word in corpus_words)
    ):
        trimmed = " ".join(label.split()[:-1]).strip()
        if trimmed:
            label = trimmed
            label_tokens = [
                token for token in title_key(label).split()
                if len(token) >= 3 and token not in _GENERIC_TOPIC_TOKENS
            ]
            trimmed_unsupported_suffix = True
    if label_tokens and all(
        any(_token_matches(word, token) for word in corpus_words)
        for token in label_tokens
    ) and not trimmed_unsupported_suffix:
        return label
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    label_token_set = set(label_tokens)
    for paper in papers:
        words = _source_label_text(paper).split()
        seen: set[str] = set()
        for size in (4, 3, 2):
            for idx in range(0, max(0, len(words) - size + 1)):
                tokens = words[idx:idx + size]
                if (
                    tokens[0] in _SOURCE_LABEL_EDGE_TOKENS
                    or tokens[-1] in _SOURCE_LABEL_EDGE_TOKENS
                    or not label_token_set.intersection(tokens)
                    or all(token in _SOURCE_LABEL_GENERIC_TOKENS for token in tokens)
                ):
                    continue
                phrase = " ".join(tokens)
                if phrase in seen:
                    continue
                seen.add(phrase)
                order.setdefault(phrase, len(order))
                counts[phrase] = counts.get(phrase, 0) + 1
    candidates = [
        phrase for phrase, count in counts.items()
        if count >= min(3, max(2, len(papers)))
    ]
    if not candidates:
        return label
    return sorted(candidates, key=lambda item: (-counts[item], -len(item.split()), order[item]))[0]


def _source_title_words(papers: list[Json]) -> set[str]:
    return {
        token
        for paper in papers
        for token in title_key(
            paper.get("title") or paper.get("paper_title") or "",
        ).split()
        if len(token) >= 3 and token not in _GENERIC_TOPIC_TOKENS
    }


def _source_title_supported_phrase(label: str, source_words: set[str]) -> str:
    tokens = [
        token for token in title_key(label).split()
        if (
            len(token) >= 3
            and token not in _GENERIC_TOPIC_TOKENS
            and token in source_words
        )
    ]
    return " ".join(dict.fromkeys(tokens))


def _source_title_aligned_submission_labels(
    topic_label: str, endpoint_labels: list[str], papers: list[Json],
) -> tuple[str, str]:
    source_words = _source_title_words(papers)
    if not source_words:
        return topic_label, topic_label
    public_topic = (
        _source_title_supported_phrase(topic_label, source_words) or topic_label
    )
    endpoint_phrases = [
        phrase for phrase in dict.fromkeys(
            _source_title_supported_phrase(label, source_words)
            for label in endpoint_labels
        )
        if phrase and phrase != public_topic and len(phrase.split()) >= 2
    ]
    if endpoint_phrases:
        return public_topic, f"{public_topic}: {', '.join(endpoint_phrases[:3])}"
    return public_topic, public_topic


def _source_title_alignment_needed(
    requested_topic: str, generated_title: str, topic_label: str, papers: list[Json],
) -> bool:
    source_words = _source_title_words(papers)
    if not source_words:
        return False
    title_tokens = set(title_key(generated_title).split())
    if title_tokens & _SOURCE_TITLE_UNSAFE_PUBLIC_TOKENS:
        return True
    label_tokens = set(title_key(topic_label).split())
    topic_tokens = [
        token for token in title_key(requested_topic).split()
        if len(token) >= 3 and token not in _GENERIC_TOPIC_TOKENS
    ]
    return any(
        token not in source_words and token not in label_tokens
        for token in topic_tokens
    )


def _bounded_signal_sentence(
    topic: str,
    endpoints_by_label: dict[str, list[str]],
    *,
    non_bio: bool,
    outcome_families: list[str] | None = None,
    display_label: str = "",
    nonpoolable_direction_scope: bool = False,
) -> str:
    topic_text = display_label or _topic_signal_label(topic, non_bio=non_bio)
    family_text = join_contexts((outcome_families or [])[:3])
    directional = list(dict.fromkeys(
        endpoints_by_label.get("directional association", [])
        + endpoints_by_label.get(_DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE, [])
        + endpoints_by_label.get("directional estimate", [])
        + endpoints_by_label.get("directionally favorable", []),
    ))
    nullish = list(dict.fromkeys(
        endpoints_by_label.get("null/mixed", [])
        + endpoints_by_label.get("null/non-convergent", []),
    ))
    descriptive = list(dict.fromkeys(
        endpoints_by_label.get("descriptive/modeling", [])
        + endpoints_by_label.get("non-clinical/predictive", []),
    ))
    context_only = list(dict.fromkeys(
        endpoint
        for label in _CONTEXT_ONLY_ROLES
        for endpoint in endpoints_by_label.get(label, [])
    ))
    if non_bio and directional and nullish:
        nullish_text = ", ".join(nullish[:2])
        nullish_verb = "are" if len(nullish) > 1 else "is"
        return (
            f"Bounded signal: {topic_text} has direction-bearing receipts for "
            f"{', '.join(directional[:2])}; {nullish_text} {nullish_verb} "
            "null/mixed in separate receipt(s), not softened scope caveats"
            f"{f' across {family_text}' if family_text else ''}. "
            "That supports only a narrow scoping contrast, not uniform support for the topic."
        )
    if non_bio and directional:
        directional_text = join_contexts(directional[:3])
        tail = (
            f", while descriptive/modeling receipts only contextualize "
            f"{', '.join(descriptive[:2])}"
            if descriptive else ""
        )
        if len(directional) > 1 and (context_only or nonpoolable_direction_scope):
            context_tail = (
                f"; context-only endpoints ({join_contexts(context_only[:2])}) "
                "remain adjacent scope context only"
                if context_only else ""
            )
            return (
                f"Bounded signal: {topic_text} maps separate direction-bearing cells for "
                f"{directional_text}{context_tail}. These are non-poolable metric "
                "cells, not support for the topic as a whole."
            )
        if len(directional) > 1:
            return (
                f"Bounded signal: {topic_text} has direction-bearing evidence across "
                f"{directional_text}{tail}; this is bounded to those metrics and settings."
            )
        return (
            f"Bounded signal: {topic_text} has direction-bearing evidence limited to "
            f"{directional_text}{tail}; this is bounded to those "
            "metrics and settings."
        )
    if directional and nullish:
        return (
            f"Bounded signal: {topic_text} has directionally favorable receipts for "
            f"{', '.join(directional[:2])}, but {', '.join(nullish[:2])} remains "
            "null/non-convergent; this is an endpoint-specific contrast, not an "
            "efficacy claim."
        )
    return (
        f"Bounded signal: {topic_text} is only a source-level context map; "
        "the selected receipts do not establish one pooled effect."
    )


def _has_context_term(text: str, terms: tuple[str, ...]) -> bool:
    tokens = set(title_key(text).split())
    return any(term in tokens or (" " in term and term in text) for term in terms)


def context_family(value: Any) -> str:
    text = str(value or "").casefold()
    if _has_context_term(text, ("patient", "patients", "participant", "adult", "human", "cohort")):
        return "human clinical/observational"
    if _has_context_term(text, ("mouse", "mice", "rat", "rats", "murine", "animal")):
        return "animal model"
    if _has_context_term(text, ("plant", "plants", "leaf", "leaves", "fruit")):
        return "plant model"
    if _has_context_term(text, ("cell", "cells", "huvec", "pc12", "pc3", "in vitro")):
        return "cell or in-vitro model"
    if _has_context_term(text, ("crystal", "cocrystal", "solubility", "compound")):
        return "chemistry/formulation"
    return "other source context"


def join_contexts(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else "the selected source contexts"
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def _source_design_labels(papers: list[Json]) -> list[str]:
    labels: list[str] = []
    patterns = (
        ("PLS-SEM", (r"\bpls[-\s]?sem\b", r"\bsmartpls\b")),
        (
            "NGT+AHP-VIKOR",
            (r"\bnominal group technique\b[^.]{0,120}\bahp\b",),
        ),
        ("AHP-VIKOR", (r"\bahp[-\s]?vikor\b", r"\banalytic hierarchy process\b")),
        ("factor analysis", (r"\bfactor analysis\b",)),
        ("regression/survey design", (r"\bregression\b", r"\bsurvey\b")),
    )
    for paper in papers:
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        text = " ".join(str(value or "") for value in (
            paper.get("title"), paper.get("paper_title"),
            fact.get("canonical_phrase"), fact.get("method"),
            fact.get("study_design"), fact.get("estimation_method"),
        ))
        for label, regexes in patterns:
            if label not in labels and any(re.search(pattern, text, re.I) for pattern in regexes):
                labels.append(label)
    return labels


def _specific_moderator_note(facts: list[Json], source_types: list[str]) -> str:
    endpoints = sorted({
        str(fact.get("endpoint") or fact.get("metric") or "").strip()
        for fact in facts if str(fact.get("endpoint") or fact.get("metric") or "").strip()
    })
    populations = sorted({
        str(fact.get("population") or "").strip()
        for fact in facts if str(fact.get("population") or "").strip()
    })
    parts = []
    if endpoints:
        parts.append("outcome type (" + "; ".join(endpoints[:5]) + ")")
    if populations:
        parts.append("population/indication (" + "; ".join(populations[:5]) + ")")
    if source_types:
        parts.append("study design/evidence type (" + "/".join(source_types) + ")")
    note = (
        "Specific moderators in this bundle are " + ", ".join(parts) + "."
        if parts else
        "Specific moderators are not extractable from the selected receipts."
    )
    if "primary" in source_types and "review" in source_types:
        note += (
            " Single primary-study estimates are separated from pooled review or "
            "meta-analytic estimates rather than treated as interchangeable."
        )
    return note


def fetch_papers(
    topic: str,
    limit: int,
    *,
    domain: str = "longevity_research",
    settings_loader: Callable[[], Any] = load_settings,
) -> list[Json]:
    settings = settings_loader()
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token:
        return _fullraw_relevant_papers(topic, limit, set())
    try:
        timeout = max(1.0, float(os.environ.get(_FACT_SEARCH_TIMEOUT_ENV, "12")))
    except ValueError:
        timeout = 12.0
    out: list[Json] = []
    seen: set[str] = set()
    min_ready_sources = min(5, max(1, limit))
    target_limit = (
        max(limit * 2, 30)
        if _non_biomedical(domain) and limit >= min_ready_sources else
        limit
    )

    def ready_to_stop() -> bool:
        if len(out) < limit:
            return False
        if not _non_biomedical(domain) or limit < min_ready_sources:
            return True
        ok, _reason = boundary_quality(
            topic, out, min_ready_sources,
            strict_topic_coverage=True, profile_slug=domain,
        )
        return ok or len(out) >= target_limit

    def fact_rows(query: str, *, row_timeout: float = timeout) -> list[Json]:
        req = urllib.request.Request(
            f"{base}/api/v1/tier2/facts/search",
            data=json.dumps({
                "domain": tier2_domain(domain),
                "query": query[:512],
                "top_k": max(30, limit * 6),
                "min_confidence": "medium",
                "numeric_only": True,
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Researka-Token": token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=row_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        return (
            [item for item in data if isinstance(item, dict)]
            if isinstance(data, list) else []
        )

    def add_fact_row(item: Json) -> bool:
        if not isinstance(item, dict):
            return False
        raw_paper = item.get("paper")
        paper: Json = raw_paper if isinstance(raw_paper, dict) else {}
        key = paper_key(paper, item.get("paper_id"))
        title = paper.get("title") or paper.get("paper_title")
        if not key or not title or key in seen:
            return False
        candidate = paper | {
            "id": key,
            "title": title,
            "source_fact": source_fact(item),
        }
        if not topic_relevant(topic, candidate):
            return False
        seen.add(key)
        out.append(candidate)
        return True

    for query in query_variants(topic):
        for item in fact_rows(query):
            add_fact_row(item)
            if ready_to_stop():
                break
        if ready_to_stop():
            break
    if _non_biomedical(domain) and len(out) >= min_ready_sources:
        ok, reason = boundary_quality(
            topic, out, min_ready_sources,
            strict_topic_coverage=True, profile_slug=domain,
        )
        if not ok and reason == "directional_receipt_floor_below_min":
            for query in _directional_topup_queries(topic):
                for item in fact_rows(query):
                    add_fact_row(item)
                    if ready_to_stop():
                        break
                if ready_to_stop():
                    break
    needs_fullraw = len(out) < limit
    if _non_biomedical(domain) and len(out) >= min_ready_sources:
        needs_fullraw = needs_fullraw or not boundary_quality(
            topic, out, min_ready_sources,
            strict_topic_coverage=True, profile_slug=domain,
        )[0]
    if needs_fullraw:
        fullraw_limit = (
            max(limit - len(out), limit)
            if _non_biomedical(domain) else
            limit - len(out)
        )
        out.extend(_fullraw_relevant_papers(topic, fullraw_limit, seen))
    for idx, paper in enumerate(list(out)):
        raw_fact = paper.get("source_fact")
        if isinstance(raw_fact, dict) and raw_fact.get("source_tier") != "paper_metadata":
            continue
        title = str(paper.get("title") or paper.get("paper_title") or "").strip()
        if not title:
            continue
        target_key = paper_key(paper, paper.get("paper_id"))
        target_title = title_key(title)
        target_updated = False
        for item in fact_rows(title, row_timeout=min(timeout, 8.0)):
            raw_paper = item.get("paper")
            matched: Json = raw_paper if isinstance(raw_paper, dict) else {}
            item_key = paper_key(matched, item.get("paper_id"))
            item_title_raw = matched.get("title") or matched.get("paper_title")
            item_title = title_key(item_title_raw)
            if not target_updated and (item_key == target_key or item_title == target_title):
                candidate = paper | {"source_fact": source_fact(item)}
                if topic_relevant(topic, candidate):
                    out[idx] = candidate
                    target_updated = True
                continue
            key = item_key or item_title
            if not key or key in seen or not item_title_raw:
                continue
            candidate = matched | {
                "id": key,
                "title": item_title_raw,
                "source_fact": source_fact(item),
            }
            if topic_relevant(topic, candidate):
                seen.add(key)
                out.append(candidate)
                if len(out) >= limit:
                    break
    if out:
        return out
    req = urllib.request.Request(
        f"{base}/api/v1/papers/topic",
        data=json.dumps({"topic": topic, "limit": limit}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Researka-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    papers = [paper for paper in data if isinstance(paper, dict)] if isinstance(data, list) else []
    return relevant_papers(topic, papers)[:limit]


def payload(
    *,
    profile_slug: str,
    topic: str,
    papers: list[Json],
    runs_root: Path,
    date: str,
    source_bundle: Callable[[list[Json]], list[Json]],
    evidence_type: Callable[[Json], str],
    year_value: Callable[[Any], int | None],
    write_json: Callable[[Path, Any], None],
    safe_excerpt: Callable[[str], str],
    submission_agent_id: Callable[[str], str],
    reviewer_notes: str = "",
    parent_submission_id: str = "",
    strict_topic_coverage: bool = False,
) -> tuple[Json, Json]:
    profile = load_domain_profile(profile_slug)
    non_bio = _non_biomedical(profile.slug)
    reviewer_notes = reviewer_notes.strip()
    parent_submission_id = parent_submission_id.strip()
    requested_topic = topic
    selected = select_boundary_papers(
        topic, papers, 5, strict_topic_coverage=strict_topic_coverage,
        profile_slug=profile.slug,
    )
    if non_bio and len(selected) < 5:
        grounded_label = _source_grounded_topic_label(topic, papers, profile.slug)
        grounded_topic = "_".join(title_key(grounded_label).split())
        if grounded_topic and grounded_topic != topic:
            grounded_selected = select_boundary_papers(
                grounded_topic, papers, 5,
                strict_topic_coverage=strict_topic_coverage,
                profile_slug=profile.slug,
            )
            if len(grounded_selected) > len(selected):
                selected = grounded_selected
                topic = grounded_topic
    run_dir = runs_root / f"{requested_topic}-source-literature-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    facts: list[Json] = []
    for paper in selected:
        raw_fact = paper.get("source_fact")
        if isinstance(raw_fact, dict):
            facts.append(raw_fact)
    topic_label = _source_grounded_topic_label(topic, selected, profile.slug)
    contexts = sorted({context_family(fact.get("population")) for fact in facts})
    context_text = join_contexts(contexts[:3])
    source_identity_total = source_identity_count(selected, require_substantive=True)
    question = (
        f"Does {topic_label} show a consistent direction-bearing association in "
        "the selected source bundle, and where do null/mixed or context-only "
        "receipts bound the claim?"
        if non_bio else
        f"Across retrieved source-level receipts for {topic_label}, which endpoints show "
        "directionally favorable versus null/non-convergent signals, and what "
        "matched PICO remains untested?"
    )
    lines = [
        "# Source literature boundary memo",
        "",
        "## Research question",
        "",
        question,
        "",
        "## Selection criteria",
        "",
        (
            f"The source-literature selector kept {topic_label} because the candidate "
            f"bundle met the public source rule: {len(selected)} citable papers, "
            f"{source_identity_total} distinct fact-backed source identities, "
            "topic-overlapping source facts, and enough shared scope to compare "
            "metric/context disagreement. It excludes duplicate reports, "
            "metadata-only title matches, off-topic papers, and sources without "
            "fact-level extraction before treating the bundle as a coherent "
            + (
                "scoping front rather than proof of a policy or market conclusion."
                if non_bio else
                "scoping front rather than proof of intervention efficacy."
            )
        ),
        "",
        "## Plain-language synthesis",
        "",
        "",
        "",
        "## Boundary map",
        "",
    ]
    bundle = source_bundle(selected)
    for idx, paper in enumerate(selected):
        bundled = bundle[idx] if idx < len(bundle) else {}
        title = str(paper.get("title") or "Untitled source").strip()
        doi = str(paper.get("doi") or "").strip()
        year = bundled.get("year") or paper.get("year") or paper.get("publication_year")
        source_type = evidence_type(paper)
        raw_fact = paper.get("source_fact")
        fact: Json = raw_fact if isinstance(raw_fact, dict) else {}
        annotation = "; ".join(str(x) for x in (source_type, year) if x)
        suffix = f" [{annotation}]" if annotation else ""
        lines.append(f"- {title}{suffix}" + (f" doi:{doi}" if doi else ""))
        role = _paper_evidence_role(paper, topic, profile.slug)
        phrase = _display_finding(fact, _paper_effect_direction(paper, topic))
        if phrase:
            lines.append(
                f"  - {'Bounded source claim' if non_bio else 'Finding'}: {phrase}",
            )
            if non_bio:
                bounds = [
                    ("setting", _source_context_label(paper, non_bio=True)),
                    ("exposure", _exposure_context_label(paper, non_bio=True)),
                    ("comparator/reference", str(fact.get("comparator") or "").strip()),
                    ("metric", _endpoint_context_label(paper, topic, non_bio=True)),
                ]
                bound_text = "; ".join(
                    f"{label}={value}" for label, value in bounds if value
                )
                if bound_text:
                    lines.append(f"  - Claim bounds: {bound_text}")
        if non_bio and role == "descriptive/modeling":
            lines.append(
                "  - Effect accounting: descriptive/modeling context only; "
                f"this receipt does not test an effect of {topic_label} "
                "on a performance endpoint.",
            )
        if non_bio and _non_bio_directional_with_subdimension_caveat(paper):
            lines.append(
                "  - Within-source caveat: significant dimensions drive the "
                "directional role, but the same receipt includes a null/mixed "
                f"subdimension ({_short_finding(phrase, 140)}).",
            )
        if non_bio and role in _CONTEXT_ONLY_ROLES:
            lines.append(
                "  - Topic-overlap rationale: retained as adjacent scope because "
                "the source fact overlaps the topic/exposure terms, but its metric "
                "is not direction-bearing support for the title claim.",
            )
        for label, key in (
            ("Population/setting" if non_bio else "Population", "population"),
            ("Policy/exposure/practice" if non_bio else "Intervention/exposure", "intervention"),
            ("Comparator/reference" if non_bio else "Comparator", "comparator"),
            ("Endpoint/metric", "endpoint"),
        ):
            value = (
                _source_context_label(paper, non_bio=non_bio)
                if key == "population" else
                _exposure_context_label(paper, non_bio=non_bio)
                if key == "intervention" else
                _endpoint_context_label(paper, topic, non_bio=non_bio)
                if key == "endpoint" else
                str(fact.get(key) or "").strip()
            )
            if value:
                lines.append(f"  - {label}: {value}")
    for item, paper in zip(bundle, selected, strict=False):
        raw_source_fact = paper.get("source_fact")
        bundle_fact: Json = raw_source_fact if isinstance(raw_source_fact, dict) else {}
        role = _paper_evidence_role(paper, topic, profile.slug)
        setting = _source_context_label(paper, non_bio=non_bio)
        if setting:
            item["population"] = setting
            item["setting"] = setting
        exposure = _exposure_context_label(paper, non_bio=non_bio)
        if exposure:
            item["intervention"] = exposure
            if isinstance(item.get("source_fact"), dict):
                item["source_fact"] = dict(item["source_fact"]) | {"intervention": exposure}
        endpoint = _endpoint_context_label(paper, topic, non_bio=non_bio)
        if endpoint:
            item["endpoint"] = endpoint
            if isinstance(item.get("source_fact"), dict):
                item["source_fact"] = dict(item["source_fact"]) | {"endpoint": endpoint}
        item["source_role"] = _memo_role_label(role, profile.slug)
        item["source_type"] = item.get("evidence_type") or evidence_type(paper)
        finding = _display_finding(bundle_fact, _paper_effect_direction(paper, topic))
        if finding:
            item["excerpt"] = safe_excerpt(finding) or " ".join(finding.split())
    bundle_identity_count = source_identity_count(bundle, require_substantive=True)
    bundle_fact_count = substantive_fact_count(bundle)
    bundle_outlet_metadata_count = source_outlet_metadata_count(bundle)
    source_setting_count = len({
        str(source.get("population") or source.get("setting") or "").strip().casefold()
        for source in bundle
        if str(source.get("population") or source.get("setting") or "").strip()
    })
    source_diversity = {
        "fact_backed_source_count": bundle_fact_count,
        "source_identity_count": bundle_identity_count,
        "source_outlet_metadata_count": bundle_outlet_metadata_count,
        "source_outlet_count": source_outlet_count(bundle),
        "source_setting_count": source_setting_count,
    }
    years = sorted(
        year for year in (year_value(source.get("year")) for source in bundle)
        if year is not None
    )
    year_text = (
        f"{years[0]}-{years[-1]}" if len(years) > 1
        else str(years[0]) if years else "undated"
    )
    type_text = "/".join(sorted({
        str(source.get("evidence_type") or "source") for source in bundle
    }))
    populations = sorted({
        value for paper in selected
        if (value := _source_context_label(paper, non_bio=non_bio))
    })
    outcome_families = _outcome_families(facts)
    interventions = sorted({
        str(fact.get("intervention") or "").strip() for fact in facts
        if str(fact.get("intervention") or "").strip()
    })
    endpoint_count = len({
        str(fact.get("endpoint") or fact.get("metric") or "").strip()
        for fact in facts if str(fact.get("endpoint") or fact.get("metric") or "").strip()
    })
    direction_text = _direction_summary(selected, topic, profile.slug)
    role_text = _evidence_role_summary(selected, topic, profile.slug)
    contrast_text = _direction_contrast_sentence(selected, topic, profile.slug)
    cross_setting_text = _cross_setting_contrast_sentence(selected, topic, profile.slug)
    signal_label = _direction_signal_label(selected, topic, profile.slug)
    endpoints_by_label: dict[str, list[str]] = {}
    for paper in selected:
        source_fact = paper.get("source_fact")
        if not isinstance(source_fact, dict):
            continue
        label = _paper_evidence_role(paper, topic, profile.slug)
        endpoint = _source_fact_endpoint_label(source_fact, topic, paper)
        if endpoint:
            endpoints_by_label.setdefault(label, []).append(endpoint)
    display_outcome_families = sorted({
        _outcome_family(endpoint)
        for endpoints in endpoints_by_label.values()
        for endpoint in endpoints
        if endpoint
    }) or outcome_families
    multi_display_outcome = non_bio and len(display_outcome_families) >= 2
    non_bio_scope_axis = "outcomes/metrics" if multi_display_outcome else "settings/designs"
    directional_endpoints = list(dict.fromkeys(
        endpoints_by_label.get("directional association", [])
        + endpoints_by_label.get(_DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE, [])
        + endpoints_by_label.get("directional estimate", [])
        + endpoints_by_label.get("directionally favorable", []),
    ))
    directional_endpoint_rows = (
        endpoints_by_label.get("directional association", [])
        + endpoints_by_label.get(_DIRECTIONAL_WITHIN_SOURCE_CAVEAT_ROLE, [])
        + endpoints_by_label.get("directional estimate", [])
        + endpoints_by_label.get("directionally favorable", [])
    )
    context_only_endpoints = list(dict.fromkeys(
        endpoint
        for label in _CONTEXT_ONLY_ROLES
        for endpoint in endpoints_by_label.get(label, [])
    ))
    context_only_settings = list(dict.fromkeys(
        setting for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug) in _CONTEXT_ONLY_ROLES
        and (setting := _source_context_label(paper, non_bio=non_bio))
    ))
    public_context_only_settings = [
        setting for setting in context_only_settings
        if title_key(setting) not in {"firm", "firms", "companies", "businesses", "organizations"}
    ]
    directional_endpoint_counts = {
        endpoint: directional_endpoint_rows.count(endpoint)
        for endpoint in dict.fromkeys(directional_endpoint_rows)
    }
    duplicated_directional_endpoints = [
        (endpoint, count)
        for endpoint, count in directional_endpoint_counts.items()
        if count > 1
    ]
    primary_duplicated_endpoint = (
        sorted(duplicated_directional_endpoints, key=lambda item: item[1], reverse=True)[0][0]
        if duplicated_directional_endpoints else ""
    )
    non_bio_nonpoolable_direction_scope = (
        non_bio
        and len(directional_endpoints) > 1
        and (bool(context_only_endpoints) or not primary_duplicated_endpoint)
    )
    nullish_endpoints = list(dict.fromkeys(
        endpoints_by_label.get("null/mixed", [])
        + endpoints_by_label.get("null/non-convergent", []),
    ))
    non_bio_signal_parts: list[str] = []
    if non_bio:
        if directional_endpoints:
            if non_bio_nonpoolable_direction_scope:
                non_bio_signal_parts.append(
                    "separate direction-bearing cells are limited to "
                    f"{join_contexts(directional_endpoints[:4])}",
                )
            else:
                direction_prefix = (
                    "direction-bearing evidence covers"
                    if len(directional_endpoints) > 1
                    else "direction-bearing evidence is limited to"
                )
                non_bio_signal_parts.append(
                    f"{direction_prefix} {join_contexts(directional_endpoints[:4])}",
                )
        for label, prefix in (
            ("null/mixed", "null/mixed metric-scope caveat receipts concern"),
            ("antecedent/support", "antecedent/support receipts contextualize"),
            ("descriptive/modeling", "descriptive/modeling receipts only contextualize"),
        ):
            endpoints = list(dict.fromkeys(endpoints_by_label.get(label, [])))
            if endpoints:
                non_bio_signal_parts.append(f"{prefix} {join_contexts(endpoints[:3])}")
    directional_count = sum(
        1 for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug) in _DIRECTIONAL_SOURCE_LIT_ROLES
    )
    nullish_count = sum(
        1 for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug)
        in {"null/mixed", "null/non-convergent"}
    )
    context_only_count = len(selected) - directional_count - nullish_count
    context_heavy_non_bio_scope = (
        non_bio
        and context_only_count >= 2
        and directional_count <= min(3, len(selected))
        and bool(directional_endpoints)
    )
    context_only_note = (
        "Context-only classification: "
        f"context-only endpoints ({join_contexts(context_only_endpoints[:3])}) remain adjacent source "
        f"context, not direction-bearing support, because it does not share the "
        f"directional metric set ({join_contexts(directional_endpoints[:4])})."
        if non_bio and context_only_endpoints and directional_endpoints else ""
    )
    antecedent_count = sum(
        1 for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug) == "antecedent/support"
    )
    antecedent_endpoints = list(dict.fromkeys(
        endpoints_by_label.get("antecedent/support", [])
    ))
    modeling_count = sum(
        1 for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug) == "descriptive/modeling"
    )
    thin_non_bio_scope = (
        non_bio and directional_count <= 1 and nullish_count >= 1
        and context_only_count >= 1 and bool(directional_endpoints)
    )
    if thin_non_bio_scope:
        contrast_text = ""
    directional_contexts = sorted({
        _source_context_label(paper, non_bio=non_bio)
        for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug) in _DIRECTIONAL_SOURCE_LIT_ROLES
        and _source_context_label(paper, non_bio=non_bio)
    })
    nullish_contexts = sorted({
        _source_context_label(paper, non_bio=non_bio)
        for paper in selected
        if _paper_evidence_role(paper, topic, profile.slug)
        in {"null/mixed", "null/non-convergent"}
        and _source_context_label(paper, non_bio=non_bio)
    })
    evidence_weight_note = ""
    scope_integration_note = ""
    single_caveat_endpoint = join_contexts(nullish_endpoints[:2]) or "the caveat outcome"
    if thin_non_bio_scope:
        context_tail = (
            f" in {join_contexts(directional_contexts[:2])}"
            if directional_contexts else ""
        )
        nullish_tail = (
            f" in {join_contexts(nullish_contexts[:2])}"
            if nullish_contexts else ""
        )
        evidence_weight_note = (
            f"Evidence weight: one effect-bearing receipt supports "
            f"{directional_endpoints[0]}{context_tail}; one caveat receipt reports "
            f"{join_contexts(nullish_endpoints[:2])}{nullish_tail} as null or "
            f"non-convergent; {antecedent_count + modeling_count} other receipt(s) "
            "provide antecedent or modeling context only. This is not an effect "
            "synthesis or a pooled comparison. "
            f"Falsifier/update: the directional-association {directional_endpoints[0]} receipt "
            "would weaken if a matched industry/setting, comparator/reference, "
            "and metric replication reports a weaker or opposite association."
        )
        scope_integration_note = (
            "Integrated reading: the directional and caveat receipts are not matched "
            "on setting, design, and metric, so the bundle supports only a narrow "
            "scope contrast between the named outcomes."
        )
    bounded_signal = _bounded_signal_sentence(
        topic, endpoints_by_label, non_bio=non_bio,
        outcome_families=display_outcome_families, display_label=topic_label,
        nonpoolable_direction_scope=non_bio_nonpoolable_direction_scope,
    )
    if context_heavy_non_bio_scope:
        bounded_signal = (
            f"Source-scope map: {directional_count} of {len(selected)} receipts are "
            f"direction-bearing for {join_contexts(directional_endpoints[:3])}; "
            f"{context_only_count} adjacent receipts remain context-only. This is "
            "not a comparator claim, pooled effect, or broad market signal."
        )
    directions = [_paper_effect_direction(paper, topic) for paper in selected]
    all_favorable = bool(directions) and all(
        direction == "directionally favorable" for direction in directions
    )
    source_types = sorted({evidence_type(paper) for paper in selected})
    design_labels = _source_design_labels(selected)
    design_heterogeneity_note = (
        "Design heterogeneity: selected receipts span "
        f"{join_contexts(design_labels[:4])}; treat this as a boundary map, "
        "not pooled evidence."
        if non_bio and len(design_labels) >= 2 else ""
    )
    missing_year_titles = [
        str(source.get("title") or "Untitled source").strip()
        for source in bundle
        if year_value(source.get("year")) is None
    ]
    split_front = (
        "directionally favorable" in direction_text
        and "non-clinical/predictive" in direction_text
    )
    lead = (
        f"This receipt-backed source-scope note maps a heterogeneous source set for {topic_label}: "
        if context_heavy_non_bio_scope else
        f"This memo makes a narrow source-grounded scope claim for {topic_label}, "
        "not a pooled effect synthesis: "
        if thin_non_bio_scope else
        f"This receipt-backed scoping note maps separate non-poolable metric cells for {topic_label}: "
        if non_bio_nonpoolable_direction_scope else
        f"This receipt-backed scoping note is a multi-outcome boundary map for {topic_label}: "
        if multi_display_outcome else
        f"This receipt-backed scoping note is a within-outcome heterogeneity map for {topic_label}: "
        if non_bio and display_outcome_families else
        f"This receipt-backed scoping note maps separated evidence fronts for {topic_label}: "
        if split_front else
        f"This receipt-backed scoping note has one bounded signal: {topic_label} shows "
    )
    group_label = (
        "Evidence role grouping; non-directional method receipts are context only"
        if split_front else
        "Evidence role grouping"
    )
    synthesis = (
        f"{lead}{signal_label} across this "
        f"{len(bundle)}-source {type_text} bundle ({year_text}). {group_label}: "
        f"{role_text}. The source facts cover "
        f"{len(populations) or 'multiple'} population/setting context(s) and "
        f"{len(interventions) or 'multiple'} "
        f"{'policy/exposure/practice' if non_bio else 'intervention/exposure'} context(s), "
            f"so this is a {'multi-outcome scoping map' if multi_display_outcome else 'scoping signal'} "
            f"about where {non_bio_scope_axis if non_bio else 'endpoints'} "
            "diverge, without "
        + (
            "establishing a causal, policy-prescriptive, market-generalized, "
            "or pooled econometric claim."
            if non_bio else
            "establishing a causal, clinical, species-translated, or mechanistically "
            "integrated claim."
        )
    )
    if non_bio and populations:
        synthesis += (
            " Population/setting counts are context descriptors only; they are "
            "not weighting, pooling, or aggregation evidence."
        )
    if all_favorable and (endpoint_count > 1 or len(populations) > 1 or len(interventions) > 1):
        synthesis += (
            " Direction is homogeneous: all selected receipts point in the same "
            "estimated direction. The boundary is setting, comparator/reference, "
            f"and {non_bio_scope_axis} diversity, not directional disagreement."
            if non_bio else
            " Direction is homogeneous: all selected receipts are directionally "
            "favorable. The boundary is population, comparator, and endpoint "
            "diversity, not directional disagreement."
        )
    if endpoint_count > 1 or len(populations) > 1:
        synthesis += (
            (
                " The listed estimates remain source-specific across metrics "
                "and settings; they are not pooled or averaged."
                if non_bio else
                " The listed effect sizes remain source-specific across endpoints "
                "and populations; they are not pooled or averaged."
            )
            + (
                " This is a separated policy/setting map, not a unified "
                "pooled economics claim."
                if non_bio else
                " This is a heterogeneous indication/context map, not a unified "
                "disease-specific or endpoint-family claim."
            )
        )
    if non_bio and populations:
        synthesis += f" Named setting scope includes {join_contexts(populations[:5])}."
    if non_bio and primary_duplicated_endpoint and not context_heavy_non_bio_scope:
        comparator_endpoints = [
            endpoint for endpoint in directional_endpoints
            if endpoint != primary_duplicated_endpoint
        ]
        if comparator_endpoints:
            synthesis += (
                f" Bounded research signal: {primary_duplicated_endpoint} is the repeated "
                f"anchor, while {join_contexts(comparator_endpoints[:3])} are comparator "
                f"outcome families under the shared {topic_label} exposure; "
                "the memo tests outcome-specific divergence, not one topic-level effect."
            )
    if non_bio_signal_parts:
        signal_heading = (
            "Source-scope map"
            if context_heavy_non_bio_scope else
            "Substantive map"
            if non_bio and len(directional_endpoints) > 1 else
            "Substantive signal"
        )
        synthesis += f" {signal_heading}: " + "; ".join(non_bio_signal_parts) + "."
    if non_bio and context_only_note:
        synthesis += f" {context_only_note}"
    if non_bio and duplicated_directional_endpoints and multi_display_outcome:
        duplicate_text = join_contexts(
            [
                f"{endpoint} ({count} of {directional_count} direction-bearing receipts)"
                for endpoint, count in duplicated_directional_endpoints[:3]
            ]
        )
        synthesis += (
            f" Coverage balance: {duplicate_text} is represented more than once; "
            "that is a scope imbalance to disclose, not stronger evidence for the topic."
        )
    if thin_non_bio_scope:
        synthesis += (
            " Integrated reading: the directional and caveat receipts are not matched "
            "on setting, design, and metric, so the bundle supports only a narrow "
            "scope contrast between the named outcomes."
        )
    if non_bio:
        metric_scope = join_contexts(directional_endpoints[:4]) or "their named metrics"
        synthesis += (
            " Within-vs-across outcome rule: direction-bearing rows are only "
            f"compared within {metric_scope}; unrelated receipt families are not "
            "treated as one outcome."
        )
        family_scope = directional_endpoints[:4] or outcome_families[:4]
        if family_scope:
            synthesis += (
                " Outcome families named here are "
                f"{join_contexts(family_scope)}; this is not one "
                "harmonized endpoint."
            )
    if contrast_text:
        synthesis += " " + contrast_text
    if cross_setting_text:
        synthesis += " " + cross_setting_text
    if non_bio:
        source_synthesis_note = (
            "Role definitions: direction-bearing rows carry metric-specific effect "
            "or association text; null/mixed rows carry rejected or non-convergent "
            "metric evidence; context/model rows rank, model, or contextualize "
            "adjacent constructs. Interpretation: keep these rows separate; do "
            "not pool them or treat antecedent/modeling rows as the same estimand."
        )
        if antecedent_count >= 2 and antecedent_endpoints:
            source_synthesis_note += (
                " Construct alignment: the antecedent/support rows are source-overlapping "
                f"for {join_contexts(antecedent_endpoints[:2])}, but they do not by "
                f"themselves test {topic_label} as a direct exposure."
            )
        if nullish_count == 1 and single_caveat_endpoint:
            source_synthesis_note += (
                f" The {single_caveat_endpoint} caveat is based on one heterogeneous "
                "receipt, and remains an explicit null/mixed boundary for that outcome family."
            )
    else:
        source_synthesis_note = ""
    body_synthesis = synthesis
    if nullish_count == 1 and single_caveat_endpoint:
        for noisy_note in (
            contrast_text,
            cross_setting_text,
            context_only_note,
            (
                "Population/setting counts are context descriptors only; they are "
                "not weighting, pooling, or aggregation evidence."
            ),
        ):
            if noisy_note:
                body_synthesis = body_synthesis.replace(f" {noisy_note}", "")
        body_synthesis = re.sub(
            r" Within-vs-across outcome rule: .*?not treated as one outcome\.",
            "",
            body_synthesis,
        )
        body_synthesis = re.sub(
            r" Outcome families named here are .*?not one harmonized endpoint\.",
            "",
            body_synthesis,
        )
    abstract_text = (
        f"{topic_label}: one receipt supports {join_contexts(directional_endpoints[:2])}; "
        f"one separate receipt is null or non-convergent for "
        f"{join_contexts(nullish_endpoints[:2])}; the remaining sources are context "
        "only, so this is a scoping contrast rather than a generalized effect."
        if thin_non_bio_scope else synthesis
    )
    if context_heavy_non_bio_scope:
        abstract_text = (
            f"{topic_label}: Source-scope map: {directional_count} of "
            f"{len(selected)} receipts are direction-bearing for "
            f"{join_contexts(directional_endpoints[:3])}; {context_only_count} "
            "adjacent receipts remain context-only. This is a source-bundle "
            "scoping map, not a comparator claim, pooled effect, or broad market "
            "signal."
        )
    elif non_bio and directional_endpoints and nullish_endpoints:
        abstract_text = (
            f"{topic_label}: direction-bearing receipts concern "
            f"{join_contexts(directional_endpoints[:3])}, while null/mixed "
            f"receipts concern {join_contexts(nullish_endpoints[:2])}; counts: "
            f"{directional_count} direction-bearing receipt(s), {nullish_count} "
            f"null/mixed receipt(s), and {context_only_count} context/model receipt(s). "
            "The context/model receipts do not test performance effects and stay "
            "outside effect accounting. This is an outcome-family boundary, not a "
            "pooled causal, policy-prescriptive, or market-generalized claim."
        )
    elif non_bio and not thin_non_bio_scope:
        no_pooling_clause = (
            "Context-only rows are adjacent scope, not effect support; no pooled "
            if context_only_count else "No pooled "
        )
        abstract_text = (
            f"{topic_label}: {bounded_signal} {no_pooling_clause}"
            "causal, policy-prescriptive, "
            "or market-generalized claim is made."
        )
    moderator_note = _specific_moderator_note(facts, source_types)
    gap_facts: list[Json] = []
    for paper in selected:
        if (
            _paper_evidence_role(paper, topic, profile.slug)
            not in (_DIRECTIONAL_SOURCE_LIT_ROLES | {"null/mixed", "null/non-convergent"})
        ):
            continue
        raw_gap_fact = paper.get("source_fact")
        if isinstance(raw_gap_fact, dict):
            gap_facts.append(raw_gap_fact)
    if not gap_facts:
        gap_facts = facts
    next_gaps = [
        _pico_gap(gap_facts, profile.slug),
        (
            f"If {topic_label} is promoted beyond a scoping note, the next run should "
            f"select sources sharing one context family rather than spanning {context_text}."
        ),
    ]
    if not non_bio and "human clinical/observational" not in contexts:
        next_gaps.insert(0, "No source in this selected bundle tests human clinical endpoints.")
    if non_bio and directional_endpoints and endpoints_by_label.get("null/mixed"):
        directional = ", ".join(directional_endpoints[:2])
        nullish = ", ".join(list(dict.fromkeys(endpoints_by_label["null/mixed"]))[:2])
        next_gaps.insert(
            0,
            "Resolve the null/mixed metric-scope caveat by retesting "
            f"{directional} and {nullish} inside one matched industry, comparator, "
            "and metric frame before generalizing the directional receipts.",
        )
    if non_bio and duplicated_directional_endpoints:
        next_gaps.insert(
            0,
            "Resolve the coverage imbalance by adding or swapping receipts so "
            f"{join_contexts([endpoint for endpoint, _count in duplicated_directional_endpoints[:3]])} "
            "is not over-represented relative to the other named metrics inside the same scoping map.",
        )
    if non_bio:
        next_gaps = list(dict.fromkeys(next_gaps))[:3]
    boundary_summary = (
        (
            f"Source-literature boundary for {topic_label}: the listed sources define "
            "separated intervention and predictive evidence fronts, not one pooled "
            "evidence front. "
        )
        if split_front else
        (
            f"Source-literature boundary for {topic_label}: the listed sources define "
            + (
                "separate outcome-specific signals across multiple metric families. "
                if multi_display_outcome else
                "a within-outcome heterogeneity map across separate source contexts. "
                if non_bio and display_outcome_families else
                "one bounded, context-dependent signal across separate source contexts. "
            )
        )
    ) + (
        "This memo does not claim causality, policy prescription, a pooled "
        "elasticity estimate, or a market-generalized effect across the sources."
        if non_bio else
        "This memo does not claim causality, clinical "
        "efficacy, species translation, or a demonstrated mechanistic chain "
        "across the sources."
    )
    writer_meta: Json = {
        "status": "skipped",
        "reason": "deterministic_boundary_only",
        "content_hash": hashlib.sha256(synthesis.encode("utf-8")).hexdigest(),
    }
    post_matrix_note = (
        "Audit note: effect-bearing rows stay metric-specific; "
        "antecedent/support and descriptive/modeling rows are excluded from effect "
        "support and no rows are pooled."
        if thin_non_bio_scope else
        "Audit note: effect-bearing rows stay metric-specific; context-only rows "
        "are excluded from effect support; role counts below keep direction-bearing, "
        "null/mixed metric-scope caveat, and context-only receipts separate."
        if non_bio else synthesis
    )
    extra_source_notes = [
        note for note in (
            cross_setting_text, context_only_note,
        )
        if note and not source_synthesis_note
    ]
    modeling_boundary_note = (
        f" Effect-support accounting: {context_only_count} of {len(selected)} "
        "receipt(s) is context/modeling-only and contributes no effect estimate; "
        f"{directional_count} receipt(s) are direction-bearing and {nullish_count} "
        "receipt(s) are null/mixed metric-scope caveats."
        if non_bio and context_only_count else ""
    )
    routing_boundary_note = (
        modeling_boundary_note
        if non_bio else
        (
            f" Routing domain `{profile.slug}` is publication-lane metadata only; "
            f"the source scope here is defined by the selected {topic} receipts."
        )
    )
    weakening_note = (
        (
            f"The antecedent-mediated map would weaken if matched {join_contexts(antecedent_endpoints[:2])} "
            "receipts show no link from the named antecedents to the outcome, or if "
            f"the {single_caveat_endpoint} null/mixed receipt replicates in a matched "
            "design and becomes the dominant result."
        )
        if non_bio and antecedent_count >= 2 and antecedent_endpoints and nullish_count else
        "This scoping signal would weaken if the null/mixed metric replicates in "
        "matched designs, if direction-bearing rows fail to reproduce within their "
        "named metric family, or if context/model rows become the only "
        "topic-overlapping receipts."
        if non_bio else
        "This scoping signal would weaken if a matched rerun finds five citable, "
        "fact-backed receipts in one population, intervention, and endpoint frame "
        "that remove the reported boundary, if the direction-bearing rows fail to "
        "reproduce within their named endpoint family, or if the context-only rows "
        "are the only topic-overlapping receipts."
    )
    lines.extend([
        "",
        "## Source synthesis",
        "",
        bounded_signal,
        "",
        *([body_synthesis, ""] if non_bio else []),
        *([source_synthesis_note, ""] if source_synthesis_note else []),
        *([design_heterogeneity_note, ""] if design_heterogeneity_note else []),
        *([*extra_source_notes, ""] if extra_source_notes else []),
        *([evidence_weight_note, ""] if evidence_weight_note else []),
        *([scope_integration_note, ""] if scope_integration_note else []),
        "",
        "## Evidence matrix",
        "",
        *_heterogeneity_matrix_lines(selected, topic, profile.slug),
        "",
        post_matrix_note,
        "",
        *(
            [
                "## Evidence role definitions",
                "",
                *_used_direction_category_lines(selected, topic, profile.slug),
                "",
            ]
            if non_bio else
            [
                "## Directional grouping",
                "",
                *(_direction_category_lines(topic, profile.slug)),
                "",
                *(_direction_rows(selected, topic, profile.slug) or [
                    "- Direction not extractable from the selected receipts.",
                ]),
                "",
            ]
        ),
        f"Evidence role summary: {role_text}.",
        f"Direction labels for audit: {direction_text}.",
        "",
        moderator_note,
        "",
        "## Context separation",
        "",
        (
            "Population/settings are separated as receipt context: "
            + (
                join_contexts(populations[:5])
                if populations else
                "specific population context is not extractable"
            )
            + ". "
            f"The selected receipts group because each carries a fact-level extraction "
            f"for {topic_label}; they separate by context ({context_text}) and "
            f"{'metric' if non_bio else 'endpoint'}, "
            "so they are not interchangeable evidence for one pooled claim."
            + (
                (
                    " Policy/exposure rows and predictive/model rows are separated as "
                    if non_bio else
                    " Intervention rows and predictive/model rows are separated as "
                )
                +
                "different evidence fronts within this source-literature boundary."
                if split_front else ""
            )
        ),
        "",
        "## Boundary limits",
        "",
        boundary_summary,
        (
            f" Material limitations: small {len(bundle)}-source bundle; no pooled "
            "estimate is possible; outlet/tier heterogeneity is scope, not weight; "
            "method/model receipts without direct effect "
            "estimates are context only; outcomes are not harmonized across studies."
            if non_bio else
            f" Material limitations: small {len(bundle)}-source bundle; no pooled "
            "estimate is possible; method/model receipts without direct effect "
            "estimates are context only; endpoints are not harmonized across studies."
        ),
        (
            " The signal is purely descriptive of source-level direction and scope; "
            + (
                "it cannot support a causal, policy-prescriptive, or pooled "
                "elasticity inference, and pooling across these designs would be inappropriate."
                if non_bio else
                "it cannot support even a weak causal or comparative-efficacy inference, "
                "and pooling across these PICOs would be inappropriate."
            )
        ),
        routing_boundary_note,
        "",
        "## What would weaken this",
        "",
        f"- {weakening_note}",
        "",
        "## Next gaps",
        "",
        *next_gaps,
        "",
    ])
    plain_language = (
        (
            f"Outcome-family boundary: direction-bearing receipts concern "
            f"{join_contexts(directional_endpoints[:3])}, while null/mixed receipts "
            f"concern {join_contexts(nullish_endpoints[:2])}; context/model receipts "
            "do not test performance effects."
            if directional_endpoints and nullish_endpoints else
            f"{directional_count} of {len(selected)} selected receipts are direction-bearing "
            f"for {join_contexts(directional_endpoints[:3]) or 'the named outcome'}; "
            f"{nullish_count} receipt(s) are null/mixed and {context_only_count} are "
            "context/model only. This is a bounded source-literature signal, not a pooled effect."
        )
        if non_bio else bounded_signal
    )
    if missing_year_titles:
        plain_language += (
            " Publication-year audit: missing year for "
            f"{join_contexts([_short_finding(title, 80) for title in missing_year_titles[:3]])}."
        )
    if "## Plain-language synthesis" in lines:
        idx = lines.index("## Plain-language synthesis") + 2
        lines[idx] = plain_language
    markdown = "\n".join(lines)
    (run_dir / "source_literature_memo.md").write_text(markdown, encoding="utf-8")
    write_json(run_dir / "source_literature_writer.json", writer_meta)
    candidate = {
        "topic": requested_topic,
        "run_dir": str(run_dir.relative_to(runs_root)),
        "memo_fingerprint": "",
        "domain": profile.as_metadata(),
    }
    agent_id = submission_agent_id(profile.slug)
    category = profile.slug.removesuffix("_research")
    revision_metadata: dict[str, Any] = {
        **({"reviewer_repair_notes": reviewer_notes} if reviewer_notes else {}),
        **({"revision_feedback": reviewer_notes} if reviewer_notes else {}),
        **({"revision_of": parent_submission_id} if parent_submission_id else {}),
        **({"revision_of_object_id": parent_submission_id} if parent_submission_id else {}),
    }
    title_directional_endpoints = _title_endpoint_labels(
        directional_endpoints[:4], topic, selected,
    )
    title_antecedent_endpoints = _title_endpoint_labels(
        antecedent_endpoints[:4], topic, selected,
    )
    comparator_title_endpoints = [
        endpoint for endpoint in title_directional_endpoints
        if endpoint != primary_duplicated_endpoint
    ]
    adjacent_context_title = join_contexts(public_context_only_settings[:2])
    adjacent_context_tail = (
        f" plus adjacent {adjacent_context_title} context"
        if adjacent_context_title else ""
    )
    antecedent_heavy_title = (
        non_bio and antecedent_count >= 2 and bool(title_antecedent_endpoints)
    )
    title_topic_label = f"{topic_label} antecedents" if antecedent_heavy_title else topic_label
    title_tail = (
        f"antecedent-mediated {join_contexts(title_antecedent_endpoints[:2])} map with "
        f"{join_contexts(nullish_endpoints[:2])} caveat"
        if antecedent_heavy_title and nullish_endpoints else
        f"antecedent-mediated {join_contexts(title_antecedent_endpoints[:2])} source map"
        if antecedent_heavy_title else
        f"cross-construct {join_contexts(title_directional_endpoints[:2])} boundary with "
        f"{join_contexts(nullish_endpoints[:2])} caveat"
        if (
            non_bio and multi_display_outcome and context_only_count
            and title_directional_endpoints and nullish_endpoints
        ) else
        f"source-scope map across {join_contexts(title_directional_endpoints[:3])} receipts"
        f"{adjacent_context_tail}"
        if context_heavy_non_bio_scope else
        f"source-scope map across {join_contexts(title_directional_endpoints[:3])} receipts"
        if non_bio_nonpoolable_direction_scope else
        (
            f"{len(bundle)}-source map: "
            f"{directional_endpoint_counts.get(primary_duplicated_endpoint, directional_count)} "
            f"direction-bearing {primary_duplicated_endpoint} receipt(s) plus "
            f"{nullish_count} null/mixed {single_caveat_endpoint} receipt(s)"
            + (
                f" plus {context_only_count} context/model receipt(s) excluded from effect support"
                if context_only_count else ""
            )
        )
        if (
            non_bio and multi_display_outcome and primary_duplicated_endpoint
            and nullish_count == 1 and not comparator_title_endpoints
        ) else
        f"{primary_duplicated_endpoint} with {join_contexts(comparator_title_endpoints[:3])} comparator outcomes"
        if non_bio and primary_duplicated_endpoint and comparator_title_endpoints else
        f"within-{display_outcome_families[0]} heterogeneity map across {len(bundle)} sources"
        if non_bio and len(display_outcome_families) == 1 else
        f"{len(bundle)}-source map: {directional_count} direction-bearing "
        f"{join_contexts(title_directional_endpoints)} receipt(s) plus "
        f"{nullish_count} null/mixed {join_contexts(nullish_endpoints[:2])} receipt(s)"
        if non_bio and title_directional_endpoints and nullish_endpoints else
        f"non-poolable direction-bearing cells for {join_contexts(title_directional_endpoints)}"
        if non_bio and len(title_directional_endpoints) > 1 and context_only_count else
        f"direction-bearing map across {join_contexts(title_directional_endpoints)} receipts"
        if non_bio and len(title_directional_endpoints) > 1 else
        f"boundary map across {join_contexts(display_outcome_families[:3])} receipts"
        if multi_display_outcome else
        "separated intervention and predictive evidence fronts"
        if split_front and not non_bio else
        "separated policy/exposure and predictive evidence fronts"
        if split_front else
        "evidence-base boundary map across receipts"
        if non_bio and non_bio_signal_parts else
        "one bounded, context-dependent signal across receipts"
    )
    generated_title = f"{title_topic_label}: {title_tail}"
    if non_bio and _source_title_alignment_needed(
        requested_topic, generated_title, topic_label, selected,
    ):
        submission_topic, submission_title = _source_title_aligned_submission_labels(
            topic_label,
            [
                *title_directional_endpoints,
                *comparator_title_endpoints,
            ],
            selected,
        )
    else:
        submission_topic, submission_title = requested_topic, generated_title
    payload_hash_material = f"{submission_topic}\n{submission_title}\n{markdown}"
    payload_hash = hashlib.sha256(payload_hash_material.encode("utf-8")).hexdigest()
    candidate["memo_fingerprint"] = payload_hash
    metadata: dict[str, Any] = {
        "article_type": "alpha_memo",
        "category": category,
        "domain_slug": profile.slug,
        "topic": submission_topic,
        "requested_topic": requested_topic,
        "topic_label": topic_label,
    }
    metadata.update(revision_metadata)
    evidence_bundle: dict[str, Any] = {
        "domain": profile.as_metadata(),
        "surface_type": "source_literature_boundary",
        "source_papers": selected,
        "direct_source_papers": selected,
        "source_bundle": bundle,
        "source_bundle_count": len(bundle),
        "bound_source_count": len(selected),
        "direct_source_count": len(bundle),
        "context_source_count": context_only_count if non_bio else 0,
        "context_sources_are_not_direct_support": bool(non_bio and context_only_count),
        "source_diversity": source_diversity,
        "source_literature_writer": writer_meta,
    }
    evidence_bundle.update(revision_metadata)
    out = {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": agent_id,
        "agent_id": agent_id,
        "domain": profile.as_metadata(),
        "domain_slug": profile.slug,
        "category": category,
        "title": submission_title,
        "human_title": submission_title,
        "abstract": safe_excerpt(abstract_text),
        "summary": safe_excerpt(abstract_text),
        "topic": submission_topic,
        "requested_topic": requested_topic,
        "metadata": metadata,
        "markdown": markdown,
        "citations": bundle,
        "source_bundle": bundle,
        "evidence_bundle": evidence_bundle,
        "content_hash": "sha256:" + payload_hash,
    }
    if parent_submission_id:
        out["object_type"] = "rebuttal"
        out["parent_submission_id"] = parent_submission_id
        out["parent_object_id"] = parent_submission_id
    write_json(run_dir / "source_literature_payload.json", out)
    return candidate, out
