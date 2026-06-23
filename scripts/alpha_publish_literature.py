"""Source-literature fallback helpers for alpha publish cycles."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.domain_profile import load_domain_profile
from agent.researka_facts import tier2_domain
from agent.settings import load_settings

Json = dict[str, Any]


def title_key(title: Any) -> str:
    raw = str(title or "").casefold()
    raw = re.sub(r"\b(?:19|20)\d{2}(?:\s*[-/]\s*(?:19|20)\d{2})?\b", " ", raw)
    raw = re.sub(r"\d+", " ", raw)
    raw = re.sub(r"[^a-z]+", " ", raw)
    return " ".join(token for token in raw.split() if token)


def boundary_quality(topic: str, papers: list[Json], min_sources: int) -> tuple[bool, str]:
    usable = [
        paper for paper in papers
        if isinstance(paper, dict)
        and str(paper.get("title") or "").strip()
        and (paper.get("doi") or paper.get("url") or paper.get("pmid") or paper.get("id"))
    ]
    if len(usable) < min_sources:
        return False, "source_floor_below_min"
    keys = [title_key(paper.get("title")) for paper in usable[:min_sources]]
    counts = {key: keys.count(key) for key in set(keys) if key}
    if any(count >= max(3, min_sources - 1) for count in counts.values()):
        return False, "repeated_title_series"
    topic_key = title_key(topic)
    if topic_key and len({key for key in keys if key and key != topic_key}) < min_sources:
        return False, "repeated_title_series"
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
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;") + "..."


def context_family(value: Any) -> str:
    text = str(value or "").casefold()
    if any(term in text for term in ("patient", "participant", "adult", "human", "cohort")):
        return "human clinical/observational"
    if any(term in text for term in ("mouse", "mice", "rat", "rats", "murine", "animal")):
        return "animal model"
    if any(term in text for term in ("cell", "cells", "huvec", "pc12", "pc3", "in vitro")):
        return "cell or in-vitro model"
    if any(term in text for term in ("crystal", "cocrystal", "solubility", "compound")):
        return "chemistry/formulation"
    return "other source context"


def join_contexts(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else "the selected source contexts"
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


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
        return []
    req = urllib.request.Request(
        f"{base}/api/v1/tier2/facts/search",
        data=json.dumps({
            "domain": tier2_domain(domain),
            "query": topic[:512],
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    out: list[Json] = []
    seen: set[str] = set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        raw_paper = item.get("paper")
        paper: Json = raw_paper if isinstance(raw_paper, dict) else {}
        key = paper_key(paper, item.get("paper_id"))
        title = paper.get("title") or paper.get("paper_title")
        if not key or not title or key in seen:
            continue
        seen.add(key)
        out.append(paper | {
            "id": key,
            "title": title,
            "source_fact": source_fact(item),
        })
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
    return [paper for paper in data if isinstance(paper, dict)] if isinstance(data, list) else []


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
) -> tuple[Json, Json]:
    profile = load_domain_profile(profile_slug)
    selected = papers[:5]
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
        f"What evidence fronts does {topic} occupy across {context_text}, "
        "and what remains untested?"
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
            f"The latest {profile.display_name} discovery pass ranked {topic} as "
            "source-rich. The fallback requires at least five verifiable source "
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
    synthesis = (
        f"This {len(bundle)}-source {type_text} bundle supports a receipt-backed "
        f"scoping note for {topic}, spanning {year_text}. The source facts cover "
        f"{len(populations) or 'multiple'} population context(s) and "
        f"{len(interventions) or 'multiple'} intervention/exposure context(s). "
        f"The bounded signal is mixed rather than convergent across {context_text}: "
        "the bundle identifies measured endpoints and where source-level findings "
        "separate, without establishing a causal, clinical, species-translated, "
        "or mechanistically integrated intervention claim."
    )
    if findings:
        examples = [_short_finding(finding) for finding in findings[:3]]
        synthesis += " Concrete source-level examples: " + "; ".join(examples) + "."
    next_gaps = [
        "A stronger memo needs one matched population/model, intervention or exposure, comparator, and endpoint.",
        (
            f"If {topic} is promoted beyond a scoping note, the next run should "
            f"select sources sharing one context family rather than mixing {context_text}."
        ),
    ]
    if "human clinical/observational" not in contexts:
        next_gaps.insert(0, "No source in this fallback bundle tests human clinical endpoints.")
    boundary_summary = (
        f"Source-literature boundary for {topic}: the listed sources define "
        "separate evidence fronts. This memo does not claim causality, clinical "
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
        "## Context separation",
        "",
        (
            f"The selected receipts group because each carries a fact-level extraction "
            f"for {topic}; they separate by context ({context_text}) and endpoint, "
            "so they are not interchangeable evidence for one pooled claim."
        ),
        "",
        "## Boundary limits",
        "",
        boundary_summary,
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
        "title": f"{topic}: receipt-backed evidence fronts",
        "abstract": safe_excerpt(synthesis),
        "summary": safe_excerpt(synthesis),
        "topic": topic,
        "metadata": {
            "article_type": "alpha_memo",
            "category": category,
            "domain_slug": profile.slug,
            "topic": topic,
        },
        "markdown": markdown,
        "citations": bundle,
        "source_bundle": bundle,
        "evidence_bundle": {
            "domain": profile.as_metadata(),
            "surface_type": "source_literature_boundary",
            "direct_source_count": len(bundle),
            "source_literature_writer": writer_meta,
        },
        "content_hash": "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    }
    write_json(run_dir / "source_literature_payload.json", out)
    return candidate, out
