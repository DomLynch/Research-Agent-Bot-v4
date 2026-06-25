"""Source-literature fallback helpers for alpha publish cycles."""
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
_GENERIC_TOPIC_TOKENS = frozenset({
    "association", "associations", "clinical", "effect", "effects", "evidence",
    "exposure", "intervention", "outcome", "outcomes", "review", "study",
    "trial", "treatment", "use", "using",
    "ageing", "aging", "agent", "agents", "agonist", "agonists", "antagonist",
    "antagonists", "blocker", "blockers", "drug", "drugs", "inhibitor",
    "inhibitors", "longevity", "therapies", "therapy", "anti",
})
_LONGEVITY_CONTEXT_TOKENS = frozenset({
    "ageing", "aging", "longevity", "lifespan", "senescence", "geroscience",
    "mortality", "survival", "frailty", "biological", "epigenetic", "clock",
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
    return tuple(dict.fromkeys(q for q in (focused, contextual, raw) if q))


def _fullraw_topic_papers(topic: str, limit: int) -> list[Json]:
    try:
        import httpx

        from scripts.run_topic_discovery import _seed_fullraw_papers
    except Exception:
        return []
    try:
        with httpx.Client() as client:
            return _seed_fullraw_papers(topic, client=client, limit=limit)
    except Exception:
        return []


def _fullraw_relevant_papers(topic: str, limit: int, seen: set[str]) -> list[Json]:
    out: list[Json] = []
    for query in query_variants(topic):
        for paper in _fullraw_topic_papers(query, max(25, limit * 6)):
            if not isinstance(paper, dict) or not _text_has_topic(paper.get("title"), topic):
                continue
            key = paper_key(paper, paper.get("paper_id"))
            title = paper.get("title") or paper.get("paper_title")
            if not key or not title or key in seen:
                continue
            seen.add(key)
            out.append(paper | {"id": key, "title": title})
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


def select_boundary_papers(topic: str, papers: list[Json], min_sources: int) -> list[Json]:
    usable = [
        paper for paper in papers
        if isinstance(paper, dict)
        and topic_relevant(topic, paper)
        and str(paper.get("title") or "").strip()
        and (paper.get("doi") or paper.get("url") or paper.get("pmid") or paper.get("id"))
    ]
    if len(usable) < min_sources:
        return usable
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


def boundary_quality(topic: str, papers: list[Json], min_sources: int) -> tuple[bool, str]:
    usable = select_boundary_papers(topic, papers, min_sources)
    if len(usable) < min_sources:
        return False, "source_floor_below_min"
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
    if _uniform_favorable_cross_pico(usable, min_sources):
        return False, "directionally_uniform_cross_pico_bundle"
    return True, "ok"


def paper_key(paper: Json, fallback: Any = "") -> str:
    return str(paper.get("doi") or paper.get("pmid") or paper.get("id") or fallback or "")


def source_fact(item: Json) -> Json:
    return {
        key: item.get(key)
        for key in (
            "id", "canonical_phrase", "population", "intervention", "comparator",
            "endpoint", "metric", "source_tier", "source_excerpt",
        )
        if item.get(key) not in (None, "")
    }


def fact_count(papers: list[Json]) -> int:
    return sum(1 for paper in papers if isinstance(paper.get("source_fact"), dict))


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
    if any(term in text for term in (
        "cost-effect", "cost effectiveness", "qaly", "£", "$", "economic",
    )):
        return "economic/context only"
    if any(term in text for term in (
        "machine learning", "machine-learning", "predict", "prediction",
        "predictive", "chronological age", "age-prediction",
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
        "not associated", "no association",
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
    )):
        return "directionally favorable"
    return "other/mixed"


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


def _direction_rows(papers: list[Json], topic: str = "") -> list[str]:
    rows: list[str] = []
    for paper in papers:
        fact = paper.get("source_fact")
        finding = ""
        if isinstance(fact, dict):
            finding = str(fact.get("canonical_phrase") or "").strip()
        title = str(paper.get("title") or "Untitled source").strip()
        direction = _paper_effect_direction(paper, topic)
        note = (
            " topic is comparator here; label is endpoint-specific, not a broad efficacy verdict"
            if direction == "comparator/not favorable" else ""
        )
        if direction == "directionally favorable" and _topic_effect_ablated(finding, topic):
            note = " mechanistic ablation supports the topic effect; not a comparator outcome"
        if direction == "directionally favorable" and re.search(r"\b(?:β|beta)\s*[=:-]\s*-", finding):
            note = " direction follows receipt wording; coefficient sign is source-specific"
        rows.append(
            f"- {direction}: {title}"
            + (f" — {finding}" if finding else "")
            + (f" ({note})" if note else ""),
        )
    return rows


def _direction_category_lines(topic: str) -> list[str]:
    topic_text = topic or "the selected topic"
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


def _direction_summary(papers: list[Json], topic: str = "") -> str:
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
        finding = str(fact.get("canonical_phrase") or "").strip()
        if not finding:
            continue
        groups[_paper_effect_direction(paper, topic)].append(_short_finding(finding, 120))
    parts = [f"{label}: {len(values)} receipt(s)" for label, values in groups.items() if values]
    return " | ".join(parts) if parts else "direction of effect is not extractable from the retrieved facts"


def _pico_gap(facts: list[Json]) -> str:
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
                "A stronger memo needs a new matched PICO that reduces this "
                f"bundle's heterogeneity: hold outcome={outcome} constant, "
                f"compare intervention/exposure={intervention} against a clearly "
                f"matched comparator, and test it in a population adjacent to "
                f"but not duplicating {population}."
            )
    return (
        "A stronger memo needs one matched PICO: one population, one "
        "intervention/exposure, one comparator, and one named outcome."
    )


def _direction_signal_label(papers: list[Json], topic: str = "") -> str:
    directions = [_paper_effect_direction(paper, topic) for paper in papers]
    if directions and all(direction == "directionally favorable" for direction in directions):
        return "directionally consistent signals across heterogeneous contexts"
    if "directionally favorable" in directions and "non-clinical/predictive" in directions:
        return "endpoint-specific intervention signals plus separate predictive evidence"
    if "directionally favorable" in directions:
        return "endpoint-specific favorable signals with context limits"
    if directions and all(direction == "non-clinical/predictive" for direction in directions):
        return "descriptive predictive signals, not intervention evidence"
    return "context-dependent, not uniformly convergent associations"


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

    def fact_rows(query: str) -> list[Json]:
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
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        if isinstance(paper.get("source_fact"), dict):
            continue
        title = str(paper.get("title") or paper.get("paper_title") or "").strip()
        if not title:
            continue
        target_key = paper_key(paper, paper.get("paper_id"))
        target_title = title_key(title)
        for item in fact_rows(title):
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
) -> tuple[Json, Json]:
    profile = load_domain_profile(profile_slug)
    selected = select_boundary_papers(topic, papers, 5)
    run_dir = runs_root / f"{topic}-source-literature-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    facts: list[Json] = []
    for paper in selected:
        raw_fact = paper.get("source_fact")
        if isinstance(raw_fact, dict):
            facts.append(raw_fact)
    contexts = sorted({context_family(fact.get("population")) for fact in facts})
    context_text = join_contexts(contexts[:3])
    question = (
        f"Across retrieved fact-level receipts for {topic}, which endpoints show "
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
            f"The source-literature fallback selected {topic} because the domain "
            "snapshot exposed enough fact-backed, topic-overlapping papers. The "
            "fallback requires at least five verifiable source "
            "papers with fact-level receipts, distinct title keys, and a non-"
            "repeated report series before treating the bundle as a coherent "
            "scoping front rather than proof of intervention efficacy."
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
        phrase = str(fact.get("canonical_phrase") or "").strip()
        if phrase:
            lines.append(f"  - Finding: {phrase}")
        for label, key in (
            ("Population", "population"),
            ("Intervention/exposure", "intervention"),
            ("Comparator", "comparator"),
            ("Endpoint/metric", "endpoint"),
        ):
            value = str(fact.get(key) or "").strip()
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
        str(fact.get("population") or "").strip() for fact in facts
        if str(fact.get("population") or "").strip()
    })
    interventions = sorted({
        str(fact.get("intervention") or "").strip() for fact in facts
        if str(fact.get("intervention") or "").strip()
    })
    findings = [
        str(fact.get("canonical_phrase") or "").strip() for fact in facts
        if str(fact.get("canonical_phrase") or "").strip()
    ]
    endpoint_count = len({
        str(fact.get("endpoint") or fact.get("metric") or "").strip()
        for fact in facts if str(fact.get("endpoint") or fact.get("metric") or "").strip()
    })
    direction_text = _direction_summary(selected, topic)
    signal_label = _direction_signal_label(selected, topic)
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
        f"This receipt-backed scoping note maps separated evidence fronts for {topic}: "
        if split_front else
        f"This receipt-backed scoping note has one bounded signal: {topic} shows "
    )
    group_label = (
        "Descriptive receipt labels, not pooled effect counts"
        if split_front else
        "Grouped by direction"
    )
    synthesis = (
        f"{lead}{signal_label} across this "
        f"{len(bundle)}-source {type_text} bundle ({year_text}). {group_label}: "
        f"{direction_text}. The source facts cover "
        f"{len(populations) or 'multiple'} population context(s) and "
        f"{len(interventions) or 'multiple'} intervention/exposure context(s), "
        "so this is a scoping signal about where endpoints diverge, without "
        "establishing a causal, clinical, species-translated, or mechanistically "
        "integrated claim."
    )
    if all_favorable and (endpoint_count > 1 or len(populations) > 1 or len(interventions) > 1):
        synthesis += (
            " Direction is homogeneous: all selected receipts are directionally "
            "favorable. The boundary is population, comparator, and endpoint "
            "diversity, not directional disagreement."
        )
    if endpoint_count > 1 or len(populations) > 1:
        synthesis += (
            " The listed effect sizes remain source-specific across endpoints "
            "and populations; they are not pooled or averaged."
            " This is a heterogeneous indication/context map, not a unified "
            "disease-specific or endpoint-family claim."
        )
    abstract_text = synthesis
    if findings:
        examples = [_short_finding(finding) for finding in findings[:3]]
        synthesis += " Concrete source-level examples: " + "; ".join(examples) + "."
    moderator_note = _specific_moderator_note(facts, source_types)
    next_gaps = [
        _pico_gap(facts),
        (
            f"If {topic} is promoted beyond a scoping note, the next run should "
            f"select sources sharing one context family rather than mixing {context_text}."
        ),
    ]
    if "human clinical/observational" not in contexts:
        next_gaps.insert(0, "No source in this fallback bundle tests human clinical endpoints.")
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
        synthesis,
        "",
        "## Directional grouping",
        "",
        *(_direction_category_lines(topic)),
        "",
        *(_direction_rows(selected, topic) or [
            "- Direction not extractable from the selected receipts.",
        ]),
        "",
        moderator_note,
        "",
        "## Context separation",
        "",
        (
            f"The selected receipts group because each carries a fact-level extraction "
            f"for {topic}; they separate by context ({context_text}) and endpoint, "
            "so they are not interchangeable evidence for one pooled claim."
            + (
                " Intervention rows and predictive/model rows are separated as "
                "different evidence fronts within this source-literature boundary."
                if split_front else ""
            )
        ),
        "",
        "## Boundary limits",
        "",
        boundary_summary,
        (
            " The signal is purely descriptive of effect-direction heterogeneity; "
            "it cannot support even a weak causal or comparative-efficacy inference, "
            "and pooling across these PICOs would be inappropriate."
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
                "separated intervention and predictive evidence fronts"
                if split_front else
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
            "direct_source_count": len(bundle),
            "source_literature_writer": writer_meta,
            **({"reviewer_repair_notes": reviewer_notes.strip()} if reviewer_notes.strip() else {}),
        },
        "content_hash": "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    }
    write_json(run_dir / "source_literature_payload.json", out)
    return candidate, out
