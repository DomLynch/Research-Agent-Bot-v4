"""Source-literature selected-bundle helpers for alpha publish cycles."""
from __future__ import annotations

import hashlib
import json
import os
import re
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
_LONGEVITY_CONTEXT_TOKENS = frozenset({
    "ageing", "aging", "longevity", "lifespan", "senescence", "geroscience",
    "mortality", "survival", "frailty", "biological", "epigenetic", "clock",
})
_NON_BIOMEDICAL_DOMAINS = frozenset({
    "business_research", "economics_research", "finance_research",
    "management_research", "marketing_research", "ai_research",
})


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
    return tuple(dict.fromkeys(q for q in (focused, contextual, raw, *windows) if q))


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
    budget = os.environ.get(
        _FULLRAW_BUDGET_ENV,
        os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS",
                       os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
                                      os.environ.get("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "45"))),
    )
    sweep_wait = os.environ.get(
        _FULLRAW_SWEEP_WAIT_ENV,
        os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS",
                       os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS",
                                      os.environ.get("V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS",
                                                     os.environ.get("V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS", "15")))),
    )
    max_variants = os.environ.get(
        _FULLRAW_MAX_VARIANTS_ENV,
        os.environ.get("TOPIC_DISCOVERY_FULLRAW_SUPPLY_MAX_VARIANTS",
                       os.environ.get("V5_MEMO_FULL_RAW_MAX_VARIANTS", "2")),
    )
    bounds = {
        "TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS": timeout,
        "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS": timeout,
        "TOPIC_DISCOVERY_SEED_PAPER_TIMEOUT_SECONDS": timeout,
        "TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS": budget,
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
    for query in query_variants(topic):
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


def select_boundary_papers(
    topic: str, papers: list[Json], min_sources: int, *, strict_topic_coverage: bool = False,
) -> list[Json]:
    usable = [
        paper for paper in papers
        if isinstance(paper, dict)
        and topic_relevant(topic, paper)
        and str(paper.get("title") or "").strip()
        and (paper.get("doi") or paper.get("url") or paper.get("pmid") or paper.get("id"))
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
    buckets: dict[str, list[Json]] = {}
    for paper in usable:
        buckets.setdefault(_paper_context_family(paper), []).append(paper)
    coherent = [
        rows for family, rows in buckets.items()
        if family != "other source context" and len(rows) >= min_sources
    ]
    if coherent:
        return max(coherent, key=len)[:min_sources]
    return usable[:min_sources]


def boundary_quality(
    topic: str, papers: list[Json], min_sources: int, *,
    strict_topic_coverage: bool = False,
    profile_slug: str = "",
) -> tuple[bool, str]:
    usable = select_boundary_papers(
        topic, papers, min_sources, strict_topic_coverage=strict_topic_coverage,
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
    if _uniform_favorable_cross_pico(usable, min_sources):
        return False, "directionally_uniform_cross_pico_bundle"
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
        or ""
    )
    return str(raw).strip().casefold()


def source_identity_count(papers: list[Json], *, require_substantive: bool = False) -> int:
    keys: set[str] = set()
    for paper in papers:
        if require_substantive and not _paper_has_substantive_source_fact(paper):
            continue
        key = source_identity_key(paper)
        if key:
            keys.add(key)
    return len(keys)


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
    return isinstance(fact, dict) and _substantive_source_fact(fact)


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
        "not associated", "no association", "hypothesis rejected",
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
        "positive influence",
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
                r"no significant|improv|reduc|increas|decreas|effect|"
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
    label = _display_direction(direction, profile_slug)
    if label != "directional estimate" or not _non_biomedical(profile_slug):
        return label
    title = title_key(paper.get("title") or paper.get("paper_title") or "")
    exposure = title_key(_exposure_context_label(paper, non_bio=True))
    if "antecedent" in exposure or "factors affecting" in title:
        return "antecedent/support"
    return label


def _table_cell(value: Any, limit: int = 90) -> str:
    text = str(value or "").replace("|", "/").strip()
    return _short_finding(text, limit) or "-"


def _heterogeneity_matrix_lines(
    papers: list[Json], topic: str = "", profile_slug: str = "",
) -> list[str]:
    rows = [
        "| Outcome family | Receipt | Evidence role | Population/setting | Metric | Extracted finding |",
        "|---|---|---|---|---|---|",
    ]
    non_bio = _non_biomedical(profile_slug)
    for paper in papers:
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        metric = str(fact.get("endpoint") or fact.get("metric") or "").strip()
        direction = _paper_effect_direction(paper, topic)
        finding = _display_finding(fact, direction)
        rows.append(
            "| "
            + " | ".join((
                _table_cell(_outcome_family(metric), 40),
                _table_cell(paper.get("title") or "Untitled source", 72),
                _table_cell(_paper_evidence_role(paper, topic, profile_slug), 36),
                _table_cell(_source_context_label(paper, non_bio=non_bio), 48),
                _table_cell(metric, 40),
                _table_cell(finding, 110),
            ))
            + " |",
        )
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
            f"- directional estimate: {topic_text} is the policy, exposure, "
            "method, or practice being measured; the label is not an efficacy verdict.",
            "- antecedent/support: the receipt explains inputs, enablers, or "
            "context for the topic rather than a clean topic-to-outcome effect.",
            f"- reference/comparator contrast: {topic_text} is the reference side "
            "of the extracted contrast; interpret only within that metric.",
            "- economic/context only: the receipt reports cost, market, prevalence, "
            "policy, or institutional context rather than a policy-effect estimate.",
            "- descriptive/modeling: the receipt reports modelling or prediction "
            "rather than a policy-effect estimate.",
            "- null/mixed or other/mixed: the extracted finding is null, mixed, "
            "or not directionally interpretable.",
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
        f"{label}: {len(values)} receipt(s)"
        for label, values in groups.items() if values
    ]
    return " | ".join(parts) if parts else "direction of effect is not extractable from the retrieved facts"


def _evidence_role_summary(papers: list[Json], topic: str = "", profile_slug: str = "") -> str:
    directional = nullish = context_only = 0
    for paper in papers:
        label = _paper_evidence_role(paper, topic, profile_slug)
        if label in {"directional estimate", "directionally favorable"}:
            directional += 1
        elif label in {"null/mixed", "null/non-convergent"}:
            nullish += 1
        elif label in {
            "antecedent/support", "descriptive/modeling", "non-clinical/predictive",
        }:
            context_only += 1
    parts = [
        f"direction-bearing evidence base k={directional}",
        f"null/mixed outcome receipts k={nullish}",
    ]
    if context_only:
        parts.append(
            f"context/antecedent/model receipts k={context_only} excluded from effect support",
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
        "directional estimate", "null/mixed", "reference/comparator contrast",
        "antecedent/support", "descriptive/modeling", "economic/context only", "other/mixed",
        "directionally favorable", "null/non-convergent", "comparator/not favorable",
        "non-clinical/predictive",
    )
    parts: list[str] = []
    for label in priority:
        values = groups.get(label)
        if values:
            parts.append(f"{label}: {values[0]}")
    for label, values in groups.items():
        if label not in priority and values:
            parts.append(f"{label}: {values[0]}")
    return "Concrete contrast: " + "; ".join(parts[:4]) + "."


def _pico_gap(facts: list[Json], profile_slug: str = "") -> str:
    endpoints = [
        str(fact.get("endpoint") or fact.get("metric") or "").strip()
        for fact in facts
        if str(fact.get("endpoint") or fact.get("metric") or "").strip()
    ]
    for fact in facts:
        population = str(fact.get("population") or "").strip()
        intervention = str(fact.get("intervention") or "").strip()
        comparator = str(fact.get("comparator") or "").strip()
        if population and intervention and comparator and endpoints:
            outcome = endpoints[0]
            return (
                "A stronger memo needs a matched design that reduces this "
                f"bundle's heterogeneity: hold metric={outcome} constant, "
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
            return "directionally consistent estimates across heterogeneous contexts"
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
    text = title_key(" ".join(str(value or "") for value in (
        paper.get("title"), paper.get("paper_title"), fact.get("canonical_phrase"), base,
    )))
    if {"artificial", "intelligence"} <= set(text.split()) or "collaboration" in text:
        return "AI, adaptive capability, and collaboration antecedents"
    if "visibility" in text:
        return "supply chain visibility and capability antecedents"
    if "disruption" in text:
        return "supply chain disruption context"
    if {"fuzzy", "ahp"} <= set(text.split()) or "vikor" in text:
        return "Pythagorean fuzzy AHP-VIKOR modelling"
    if {"flexibility", "collaboration", "agility"} & set(text.split()):
        return "flexibility, collaboration, and agility antecedents"
    return base


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


def _bounded_signal_sentence(
    topic: str,
    endpoints_by_label: dict[str, list[str]],
    *,
    non_bio: bool,
    outcome_families: list[str] | None = None,
) -> str:
    topic_text = topic.replace("_", " ")
    family_text = join_contexts((outcome_families or [])[:3])
    directional = list(dict.fromkeys(
        endpoints_by_label.get("directional estimate", [])
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
    if non_bio and directional and nullish:
        return (
            f"Bounded signal: {topic_text} is a multi-outcome heterogeneity map"
            f"{f' across {family_text} receipts' if family_text else ''}: "
            "direction-bearing receipts cover "
            f"{', '.join(directional[:2])}, but {', '.join(nullish[:2])} remains "
            "null/mixed; the contrast is between outcome families, not within one "
            "harmonized performance outcome."
        )
    if non_bio and directional:
        tail = (
            f", while descriptive/modeling receipts only contextualize "
            f"{', '.join(descriptive[:2])}"
            if descriptive else ""
        )
        return (
            f"Bounded signal: {topic_text} has direction-bearing receipts for "
            f"{', '.join(directional[:2])}{tail}; this is bounded to those "
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

    for query in query_variants(topic):
        for item in fact_rows(query):
            if not isinstance(item, dict):
                continue
            raw_paper = item.get("paper")
            paper: Json = raw_paper if isinstance(raw_paper, dict) else {}
            key = paper_key(paper, item.get("paper_id"))
            title = paper.get("title") or paper.get("paper_title")
            if not key or not title or key in seen:
                continue
            candidate = paper | {
                "id": key,
                "title": title,
                "source_fact": source_fact(item),
            }
            if not topic_relevant(topic, candidate):
                continue
            seen.add(key)
            out.append(candidate)
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    if len(out) < limit:
        out.extend(_fullraw_relevant_papers(topic, limit - len(out), seen))
    for idx, paper in enumerate(out):
        raw_fact = paper.get("source_fact")
        if isinstance(raw_fact, dict) and raw_fact.get("source_tier") != "paper_metadata":
            continue
        title = str(paper.get("title") or paper.get("paper_title") or "").strip()
        if not title:
            continue
        target_key = paper_key(paper, paper.get("paper_id"))
        target_title = title_key(title)
        for item in fact_rows(title, row_timeout=min(timeout, 3.0)):
            raw_paper = item.get("paper")
            matched: Json = raw_paper if isinstance(raw_paper, dict) else {}
            item_key = paper_key(matched, item.get("paper_id"))
            item_title = title_key(matched.get("title") or matched.get("paper_title"))
            if item_key != target_key and item_title != target_title:
                continue
            candidate = paper | {"source_fact": source_fact(item)}
            if topic_relevant(topic, candidate):
                out[idx] = candidate
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
    strict_topic_coverage: bool = False,
) -> tuple[Json, Json]:
    profile = load_domain_profile(profile_slug)
    non_bio = _non_biomedical(profile.slug)
    selected = select_boundary_papers(
        topic, papers, 5, strict_topic_coverage=strict_topic_coverage,
    )
    run_dir = runs_root / f"{topic}-source-literature-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    facts: list[Json] = []
    for paper in selected:
        raw_fact = paper.get("source_fact")
        if isinstance(raw_fact, dict):
            facts.append(raw_fact)
    contexts = sorted({context_family(fact.get("population")) for fact in facts})
    context_text = join_contexts(contexts[:3])
    source_identity_total = source_identity_count(selected, require_substantive=True)
    question = (
        f"Across retrieved source-level receipts for {topic}, which metrics, "
        "settings, or contrasts differ versus remain null/mixed, and what "
        "matched design remains untested?"
        if non_bio else
        f"Across retrieved source-level receipts for {topic}, which endpoints show "
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
            f"The source-literature selector kept {topic} because the candidate "
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
        "## Boundary map",
        "",
    ]
    for paper in selected:
        title = str(paper.get("title") or "Untitled source").strip()
        doi = str(paper.get("doi") or "").strip()
        year = paper.get("year") or paper.get("publication_year")
        source_type = evidence_type(paper)
        raw_fact = paper.get("source_fact")
        fact: Json = raw_fact if isinstance(raw_fact, dict) else {}
        annotation = "; ".join(str(x) for x in (source_type, year) if x)
        suffix = f" [{annotation}]" if annotation else ""
        lines.append(f"- {title}{suffix}" + (f" doi:{doi}" if doi else ""))
        phrase = _display_finding(fact, _paper_effect_direction(paper, topic))
        if phrase:
            lines.append(f"  - Finding: {phrase}")
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
                str(fact.get(key) or "").strip()
            )
            if value:
                lines.append(f"  - {label}: {value}")
    bundle = source_bundle(selected)
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
    signal_label = _direction_signal_label(selected, topic, profile.slug)
    non_bio_signal_parts: list[str] = []
    endpoints_by_label: dict[str, list[str]] = {}
    for paper in selected:
        source_fact = paper.get("source_fact")
        if not isinstance(source_fact, dict):
            continue
        label = _paper_evidence_role(paper, topic, profile.slug)
        endpoint = str(source_fact.get("endpoint") or source_fact.get("metric") or "").strip()
        if endpoint:
            endpoints_by_label.setdefault(label, []).append(endpoint)
    if non_bio:
        for label, prefix in (
            ("directional estimate", "direction-bearing receipts support"),
            ("null/mixed", "null/mixed receipts limit"),
            ("antecedent/support", "antecedent/support receipts contextualize"),
            ("descriptive/modeling", "descriptive/modeling receipts only contextualize"),
        ):
            endpoints = list(dict.fromkeys(endpoints_by_label.get(label, [])))
            if endpoints:
                non_bio_signal_parts.append(f"{prefix} {', '.join(endpoints[:3])}")
    bounded_signal = _bounded_signal_sentence(
        topic, endpoints_by_label, non_bio=non_bio,
        outcome_families=outcome_families,
    )
    directions = [_paper_effect_direction(paper, topic) for paper in selected]
    all_favorable = bool(directions) and all(
        direction == "directionally favorable" for direction in directions
    )
    source_types = sorted({evidence_type(paper) for paper in selected})
    split_front = (
        "directionally favorable" in direction_text
        and "non-clinical/predictive" in direction_text
    )
    lead = (
        f"This receipt-backed scoping note is a multi-outcome heterogeneity map for {topic}: "
        if non_bio and len(outcome_families) >= 2 else
        f"This receipt-backed scoping note maps separated evidence fronts for {topic}: "
        if split_front else
        f"This receipt-backed scoping note has one bounded signal: {topic} shows "
    )
    group_label = (
        "Evidence role grouping; non-directional method receipts are context only"
        if split_front else
        "Evidence role grouping"
    )
    synthesis = (
        f"{lead}{signal_label} across this "
        f"{len(bundle)}-source {type_text} bundle ({year_text}). {group_label}: "
        f"{role_text}. Direction labels for audit: {direction_text}. The source facts cover "
        f"{len(populations) or 'multiple'} population/setting context(s) and "
        f"{len(interventions) or 'multiple'} "
        f"{'policy/exposure/practice' if non_bio else 'intervention/exposure'} context(s), "
        f"so this is a scoping signal about where {'metrics' if non_bio else 'endpoints'} "
        "diverge, without "
        + (
            "establishing a causal, policy-prescriptive, market-generalized, "
            "or pooled econometric claim."
            if non_bio else
            "establishing a causal, clinical, species-translated, or mechanistically "
            "integrated claim."
        )
    )
    if all_favorable and (endpoint_count > 1 or len(populations) > 1 or len(interventions) > 1):
        synthesis += (
            " Direction is homogeneous: all selected receipts point in the same "
            "estimated direction. The boundary is setting, comparator/reference, "
            "and metric diversity, not directional disagreement."
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
                " This is a heterogeneous policy/setting map, not a unified "
                "pooled economics claim."
                if non_bio else
                " This is a heterogeneous indication/context map, not a unified "
                "disease-specific or endpoint-family claim."
            )
        )
    if non_bio_signal_parts:
        synthesis += " Substantive signal: " + "; ".join(non_bio_signal_parts) + "."
    if non_bio:
        synthesis += " Within-vs-across outcome rule: direction-bearing rows are "
        synthesis += (
            "only compared within their named metric; firm-performance, supply-chain "
            "performance, and modelling receipts are not treated as one outcome."
        )
        if outcome_families:
            synthesis += (
                " Outcome families named here are "
                f"{join_contexts(outcome_families[:4])}; this is not one "
                "harmonized SCR-to-performance endpoint."
            )
    if contrast_text:
        synthesis += " " + contrast_text
    abstract_text = synthesis
    moderator_note = _specific_moderator_note(facts, source_types)
    next_gaps = [
        _pico_gap(facts, profile.slug),
        (
            f"If {topic} is promoted beyond a scoping note, the next run should "
            f"select sources sharing one context family rather than mixing {context_text}."
        ),
    ]
    if not non_bio and "human clinical/observational" not in contexts:
        next_gaps.insert(0, "No source in this selected bundle tests human clinical endpoints.")
    if non_bio and endpoints_by_label.get("directional estimate") and endpoints_by_label.get("null/mixed"):
        directional = ", ".join(list(dict.fromkeys(endpoints_by_label["directional estimate"]))[:2])
        nullish = ", ".join(list(dict.fromkeys(endpoints_by_label["null/mixed"]))[:2])
        next_gaps.insert(
            0,
            "Resolve the directional/null conflict by retesting "
            f"{directional} and {nullish} inside one matched industry, comparator, "
            "and metric frame before generalizing the directional receipts.",
        )
    boundary_summary = (
        (
            f"Source-literature boundary for {topic}: the listed sources define "
            "separated intervention and predictive evidence fronts, not one pooled "
            "evidence front. "
        )
        if split_front else
        (
            f"Source-literature boundary for {topic}: the listed sources define "
            "one bounded, context-dependent signal across separate source contexts. "
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
    lines.extend([
        "",
        "## Source synthesis",
        "",
        bounded_signal,
        "",
        "## Heterogeneity matrix",
        "",
        *_heterogeneity_matrix_lines(selected, topic, profile.slug),
        "",
        synthesis,
        "",
        "## Directional grouping",
        "",
        *(_direction_category_lines(topic, profile.slug)),
        "",
        f"Evidence role summary: {role_text}.",
        "",
        *(_direction_rows(selected, topic, profile.slug) or [
            "- Direction not extractable from the selected receipts.",
        ]),
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
            f"for {topic}; they separate by context ({context_text}) and "
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
            f" Material limitations: small k={len(bundle)} source bundle; no pooled "
            "estimate is possible; method/model receipts without direct effect "
            "estimates are context only; outcomes are not harmonized across studies."
            if non_bio else
            f" Material limitations: small k={len(bundle)} source bundle; no pooled "
            "estimate is possible; method/model receipts without direct effect "
            "estimates are context only; endpoints are not harmonized across studies."
        ),
        (
            " The signal is purely descriptive of effect-direction heterogeneity; "
            + (
                "it cannot support a causal, policy-prescriptive, or pooled "
                "elasticity inference, and pooling across these designs would be inappropriate."
                if non_bio else
                "it cannot support even a weak causal or comparative-efficacy inference, "
                "and pooling across these PICOs would be inappropriate."
            )
        ),
        (
            f" Routing domain `{profile.slug}` is publication-lane metadata only; "
            f"the source scope here is defined by the selected {topic} receipts."
        ),
        "",
        "## Next gaps",
        "",
        *next_gaps,
        "",
    ])
    markdown = "\n".join(lines)
    (run_dir / "source_literature_memo.md").write_text(markdown, encoding="utf-8")
    write_json(run_dir / "source_literature_writer.json", writer_meta)
    candidate = {
        "topic": topic,
        "run_dir": str(run_dir.relative_to(runs_root)),
        "memo_fingerprint": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "domain": profile.as_metadata(),
    }
    agent_id = submission_agent_id(profile.slug)
    category = profile.slug.removesuffix("_research")
    out = {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": agent_id,
        "agent_id": agent_id,
        "domain": profile.as_metadata(),
        "domain_slug": profile.slug,
        "category": category,
        "title": (
            f"{topic.replace('_', ' ')}: "
            + (
                f"heterogeneity map across {join_contexts(outcome_families[:3])} receipts"
                if non_bio and len(outcome_families) >= 2 else
                "separated intervention and predictive evidence fronts"
                if split_front and not non_bio else
                "separated policy/exposure and predictive evidence fronts"
                if split_front else
                "evidence-base heterogeneity map across receipts"
                if non_bio and non_bio_signal_parts else
                "one bounded, context-dependent signal across receipts"
            )
        ),
        "abstract": safe_excerpt(abstract_text),
        "summary": safe_excerpt(abstract_text),
        "topic": topic,
        "metadata": {
            "article_type": "alpha_memo",
            "category": category,
            "domain_slug": profile.slug,
            "topic": topic,
            **({"reviewer_repair_notes": reviewer_notes.strip()} if reviewer_notes.strip() else {}),
        },
        "markdown": markdown,
        "citations": bundle,
        "source_bundle": bundle,
        "evidence_bundle": {
            "domain": profile.as_metadata(),
            "surface_type": "source_literature_boundary",
            "source_papers": selected,
            "direct_source_papers": selected,
            "source_bundle": bundle,
            "source_bundle_count": len(bundle),
            "bound_source_count": len(selected),
            "direct_source_count": len(bundle),
            "context_source_count": 0,
            "context_sources_are_not_direct_support": False,
            "source_literature_writer": writer_meta,
            **({"reviewer_repair_notes": reviewer_notes.strip()} if reviewer_notes.strip() else {}),
        },
        "content_hash": "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    }
    write_json(run_dir / "source_literature_payload.json", out)
    return candidate, out
