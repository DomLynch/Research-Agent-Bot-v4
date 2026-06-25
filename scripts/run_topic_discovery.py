"""Sprint 63 CLI — autonomous topic-discovery loop.

Probes the DB for each seed topic in topic_packs/discovery_seeds.toml,
scores by paper-level velocity (fwci * log(1+cited) * recency *
quality_score) with Sprint 70 cross-topic anchor dampening, and emits
a ranked candidate queue:

  runs/_topics_discovery/<utc>.json   -- raw scores
  runs/_topics_discovery/<utc>.md     -- human-readable queue

The top-N topics become the v4 curator's "what to run next" list.
Lives in scripts/ so it costs zero agent/ LOC.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.domain_profile import domain_choices, load_domain_profile
from agent.settings import Settings, load_settings
from agent.topic_discovery import (
    TopicCandidate,
    _fetch_fullraw_topic_papers,
    _fetch_topic_papers,
    _score_topic,
    _title_topic_slugs,
    cached_source_rich_candidates,
    discover_topics,
    load_derived_topic_limit,
    load_seed_topics,
)
from agent.topic_synonyms import expand_topic_queries
from scripts import alpha_publish_io as publish_io

_FAST_DERIVED_TOPIC_LIMIT = 250
_SOURCE_RICH_FLOOR = 5
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_FULLRAW_PROBE_RECEIPTS: list[dict[str, object]] = []
_FULLRAW_PROBE_EVENTS: list[dict[str, object]] = []
_GENERIC_SCOPE_TOKENS = {
    "ai", "research", "study", "studies", "trial", "trials", "review",
    "meta", "analysis", "effect", "effects", "therapy", "treatment",
    "use", "uses", "intervention", "interventions", "outcome", "outcomes",
}


def _truthy_env(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _load_v5_env_defaults() -> None:
    if not _truthy_env("TOPIC_DISCOVERY_V5_ENV_LOAD"):
        return
    env_path = Path(os.environ.get("TOPIC_DISCOVERY_V5_ENV_FILE", "/etc/v5-memo/env"))
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _apply_v5_client_bounds() -> dict[str, str | None]:
    timeout = os.environ.get(
        "TOPIC_DISCOVERY_V5_TIMEOUT_SECONDS",
        os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", "30"),
    )
    values: dict[str, str] = {
        "V5_MEMO_FULL_RAW_CORPUS_TIMEOUT": timeout,
        "V5_MEMO_FULL_RAW_QUERY_TIMEOUT": timeout,
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS": os.environ.get(
            "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
            os.environ.get("TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS", "45"),
        ),
        "V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS": os.environ.get(
            "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS", "0",
        ),
        "V5_MEMO_FULL_RAW_MAX_VARIANTS": os.environ.get(
            "TOPIC_DISCOVERY_V5_MAX_VARIANTS", "2",
        ),
        "V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED": os.environ.get(
            "TOPIC_DISCOVERY_V5_MIN_SHARDS_SEARCHED", "1",
        ),
        "V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED": os.environ.get(
            "TOPIC_DISCOVERY_V5_MIN_SOURCES_SEARCHED", "1",
        ),
        "V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH": os.environ.get(
            "TOPIC_DISCOVERY_V5_REQUIRE_COMPLETE_SEARCH", "0",
        ),
    }
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    return old


def _restore_env(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _v5_client_papers(query: str, *, limit: int) -> list[dict[str, object]]:
    if not _truthy_env("TOPIC_DISCOVERY_V5_CLIENT_FALLBACK"):
        return []
    src = Path(os.environ.get("TOPIC_DISCOVERY_V5_SRC", "/opt/v5-memo/src"))
    if not src.exists():
        return []
    _load_v5_env_defaults()
    src_text = str(src)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    try:
        from v5_memo.client import FullRawCorpusSearchClient
    except Exception:
        return []
    old_env = _apply_v5_client_bounds()
    try:
        hits = FullRawCorpusSearchClient.from_env(strict=False).search(
            query, limit=limit,
        )
    except Exception:
        return []
    finally:
        _restore_env(old_env)
    out: list[dict[str, object]] = []
    for hit in hits:
        title = str(getattr(hit, "title", "") or "").strip()
        if not title:
            continue
        metadata = getattr(hit, "metadata", {}) or {}
        receipt = (
            metadata.get("shard_receipt")
            if isinstance(metadata, dict) else None
        )
        out.append({
            "doi": getattr(hit, "doi", None) or "",
            "pmid": metadata.get("pmid") if isinstance(metadata, dict) else None,
            "pmcid": metadata.get("pmcid") if isinstance(metadata, dict) else None,
            "paper_id": getattr(hit, "hit_id", None),
            "title": title,
            "journal": getattr(hit, "venue", None),
            "publication_year": getattr(hit, "year", None),
            "fwci": 1.0,
            "cited_by_count": (
                metadata.get("cited_by_count") if isinstance(metadata, dict) else 0
            ) or 0,
            "quality_score": 70.0,
            "url": getattr(hit, "url", "") or "",
            "fullraw_shard_receipt": dict(receipt) if isinstance(receipt, dict) else {},
        })
    return out


def _seed_fullraw_papers(
    query: str, *, client: httpx.Client, limit: int,
) -> list[dict[str, object]]:
    papers = _v5_client_papers(query, limit=limit) or _fetch_fullraw_topic_papers(
        query, client=client, limit=limit,
    )
    if not papers:
        _FULLRAW_PROBE_EVENTS.append({"query": query, "status": "no_hits"})
    return papers


def _hydrate_limit() -> int:
    try:
        return max(0, int(os.environ.get("TOPIC_DISCOVERY_HYDRATE_TOP", 20)))
    except (TypeError, ValueError):
        return 20


def _hydrate_query_limit() -> int:
    try:
        return max(1, int(os.environ.get("TOPIC_DISCOVERY_HYDRATE_QUERIES", 3)))
    except (TypeError, ValueError):
        return 3


def _seed_query_limit() -> int:
    try:
        return max(1, int(os.environ.get("TOPIC_DISCOVERY_SEED_QUERIES", 2)))
    except (TypeError, ValueError):
        return 2


def _seed_paper_probe_limit(top: int) -> int:
    raw = os.environ.get("TOPIC_DISCOVERY_SEED_PAPER_TOPICS")
    if raw is None or not raw.strip():
        return max(top, 6)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return max(top, 6)


def _seed_paper_budget_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get(
            "TOPIC_DISCOVERY_SEED_PAPER_BUDGET_SECONDS", "45",
        )))
    except (TypeError, ValueError):
        return 45.0


def _fullraw_supply_budget_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get(
            "TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS",
            "180",
        )))
    except (TypeError, ValueError):
        return 180.0


def _fullraw_supply_query_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get(
            "TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_TIMEOUT_SECONDS", "30",
        )))
    except (TypeError, ValueError):
        return 30.0


def _fullraw_supply_query_budget_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get(
            "TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS", "100",
        )))
    except (TypeError, ValueError):
        return 100.0


def _fullraw_configured() -> bool:
    return bool(os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "").strip())


def _context_query_terms(value: str) -> str:
    seen: dict[str, None] = {}
    for token in _TOKEN_RE.findall(value.casefold()):
        if len(token) > 1 and token not in _GENERIC_SCOPE_TOKENS:
            seen.setdefault(token, None)
    return " ".join(seen)


def _context_supported_papers(
    papers: list[dict[str, object]], context_terms: str,
) -> list[dict[str, object]]:
    context_tokens = set(_TOKEN_RE.findall(context_terms))
    if not context_tokens:
        return papers
    return [
        paper for paper in papers
        if context_tokens & set(_TOKEN_RE.findall(
            str(paper.get("title") or "").casefold()))
    ]


def _query_supported_papers(
    papers: list[dict[str, object]], query: str, context_terms: str,
) -> list[dict[str, object]]:
    scoped = _context_supported_papers(papers, context_terms)
    if len(scoped) >= _SOURCE_RICH_FLOOR:
        return scoped
    query_tokens = {
        token for token in _TOKEN_RE.findall(query.casefold())
        if len(token) > 1 and token not in _GENERIC_SCOPE_TOKENS
    }
    return [
        paper for paper in papers
        if query_tokens & set(_TOKEN_RE.findall(
            str(paper.get("title") or "").casefold()))
    ]


def _hydration_queries(candidate: TopicCandidate, *, context: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for query in expand_topic_queries(candidate.topic, max_queries=2):
        if query.strip():
            seen.setdefault(query.strip(), None)
    context_terms = _context_query_terms(context)
    if context_terms:
        for query in tuple(seen)[:2]:
            seen.setdefault(f"{query} {context_terms}", None)
    return tuple(seen)[:_hydrate_query_limit()]


def _context_variants(context: str) -> tuple[str, ...]:
    terms = _context_query_terms(context).split()
    seen: dict[str, None] = {}
    if terms:
        seen.setdefault(terms[0], None)
    if len(terms) > 1:
        seen.setdefault(" ".join(terms[1:]), None)
        seen.setdefault(" ".join(terms), None)
    return tuple(seen)


def _seed_paper_queries(seed: str, *, context: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for query in expand_topic_queries(seed, max_queries=4):
        if query.strip():
            seen.setdefault(query.strip(), None)
    for query in tuple(seen)[:2]:
        for variant in _context_variants(context):
            seen.setdefault(f"{query} {variant}", None)
    return tuple(seen)[:_seed_query_limit()]


def _resolve_limits(
    *, warm_backlog: bool, derived_topic_limit: int | None,
    fact_probe_topics: int | None, configured_limit: int,
) -> tuple[int, int | None]:
    derived = (
        max(0, derived_topic_limit)
        if derived_topic_limit is not None
        else configured_limit if warm_backlog
        else min(configured_limit, _FAST_DERIVED_TOPIC_LIMIT)
    )
    if warm_backlog:
        probes = (
            max(0, fact_probe_topics)
            if fact_probe_topics is not None
            else min(configured_limit, _FAST_DERIVED_TOPIC_LIMIT)
        )
        return derived, probes
    return derived, fact_probe_topics


def _render_md(stamps: dict[str, str],
               candidates: tuple[TopicCandidate, ...]) -> str:
    lines = [
        f"# Topic discovery queue — {stamps['snapshot_utc']}",
        "",
        f"**Seed topics probed:** {stamps['seed_count']}",
        f"**Year reference:** {stamps['year']}",
        "**Score formula:** mean(top-5 paper-velocity) where "
        "paper-velocity = fwci * log(1+cited_by_count) * recency_weight "
        "* quality_score/100, dampened when one paper anchors M >= 3 topics",
        "",
        "| Rank | Topic | Velocity | Papers | Fact sources | mean fwci | mean cited |"
        " Top paper |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for i, c in enumerate(candidates, start=1):
        lines.append(
            f"| {i} | `{c.topic}` | **{c.velocity_score:.2f}** | "
            f"{c.paper_count} | {c.fact_source_count} | {c.mean_fwci:.2f} | "
            f"{c.mean_cited_by:.0f} | "
            f"_{c.top_paper_title[:70]}_ |"
        )
    return "\n".join(lines) + "\n"


def _merge_candidates(
    first: tuple[TopicCandidate, ...],
    second: tuple[TopicCandidate, ...],
) -> tuple[TopicCandidate, ...]:
    merged: dict[str, TopicCandidate] = {}
    for candidate in (*first, *second):
        merged.setdefault(candidate.topic, candidate)
    return tuple(sorted(merged.values(), key=_rank_key))


def _rank_key(candidate: TopicCandidate) -> tuple[int, int, float, int, str]:
    paper_backed = int(_paper_backed(candidate))
    return (
        -paper_backed,
        -min(candidate.paper_count, candidate.fact_source_count),
        -candidate.velocity_score,
        -candidate.paper_count,
        candidate.topic,
    )


def _paper_backed(candidate: TopicCandidate) -> bool:
    return bool(candidate.paper_count and candidate.top_paper_title)


def _hydration_probeable(candidate: TopicCandidate) -> bool:
    tokens = _topic_tokens(candidate.topic)
    return len(tokens) > 1 or any(len(token) > 4 for token in tokens)


def _hydrate_candidates(
    candidates: tuple[TopicCandidate, ...], *, settings: Settings,
    current_year: int, query_context: str = "",
) -> tuple[TopicCandidate, ...]:
    out: list[TopicCandidate] = []
    limit = min(_hydrate_limit(), len(candidates))
    if limit <= 0:
        return tuple(sorted((c for c in candidates if _paper_backed(c)), key=_rank_key))
    with httpx.Client() as client:
        for idx, candidate in enumerate(candidates):
            if _paper_backed(candidate):
                out.append(candidate)
                continue
            if not _hydration_probeable(candidate):
                continue
            if idx >= limit:
                continue
            papers = []
            for query in _hydration_queries(candidate, context=query_context):
                try:
                    papers = _fetch_topic_papers(
                        query, client=client, settings=settings)
                except (OSError, TypeError, ValueError):
                    continue
                if papers:
                    break
            if not papers:
                continue
            scored = _score_topic(
                candidate.topic, papers, current_year,
                fact_source_count=candidate.fact_source_count,
            )
            if scored.top_paper_title:
                out.append(TopicCandidate(
                    topic=candidate.topic,
                    paper_count=max(candidate.paper_count, scored.paper_count),
                    fact_source_count=candidate.fact_source_count,
                    top_paper_doi=scored.top_paper_doi,
                    top_paper_title=scored.top_paper_title,
                    velocity_score=scored.velocity_score,
                    mean_fwci=scored.mean_fwci,
                    mean_cited_by=scored.mean_cited_by,
                    sub_topic=candidate.sub_topic,
                    claim_type=candidate.claim_type,
                ))
    return tuple(sorted(out, key=_rank_key))


def _seed_paper_candidates(
    seeds: tuple[str, ...], *, settings: Settings, current_year: int, top: int,
    query_context: str = "",
) -> tuple[TopicCandidate, ...]:
    out: list[TopicCandidate] = []
    old_timeout = os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS")
    seed_timeout = os.environ.get("TOPIC_DISCOVERY_SEED_PAPER_TIMEOUT_SECONDS", "6")
    try:
        old_timeout_value = float(old_timeout) if old_timeout else 0.0
        seed_timeout_value = float(seed_timeout)
    except (TypeError, ValueError):
        old_timeout_value = 0.0
        seed_timeout_value = 6.0
        seed_timeout = "6"
    if old_timeout is None or old_timeout_value > seed_timeout_value:
        os.environ["TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"] = seed_timeout
    try:
        deadline = time.monotonic() + _seed_paper_budget_seconds()
        with httpx.Client() as client:
            for seed in seeds[:_seed_paper_probe_limit(top)]:
                if time.monotonic() >= deadline:
                    break
                candidate = TopicCandidate(
                    topic=seed, paper_count=0, fact_source_count=0,
                    top_paper_doi="", top_paper_title="",
                    velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
                )
                if not _hydration_probeable(candidate):
                    continue
                papers_by_key: dict[str, dict[str, object]] = {}
                for query in _seed_paper_queries(seed, context=query_context):
                    if time.monotonic() >= deadline:
                        break
                    for paper in _seed_fullraw_papers(query, client=client, limit=5):
                        key = str(paper.get("doi") or paper.get("paper_id")
                                  or paper.get("title") or "").strip().casefold()
                        if not key or key in papers_by_key:
                            continue
                        receipt = paper.get("fullraw_shard_receipt")
                        if isinstance(receipt, dict):
                            _FULLRAW_PROBE_RECEIPTS.append({
                                "seed": seed,
                                "query": query,
                                "shards_searched": receipt.get("shards_searched"),
                                "partial_shard_search": receipt.get("partial_shard_search"),
                                "sources_searched": receipt.get("sources_searched"),
                            })
                        papers_by_key[key] = paper
                    if len(papers_by_key) >= 5:
                        break
                papers = list(papers_by_key.values())[:5]
                scored = _score_topic(
                    seed, papers, current_year, fact_source_count=len(papers),
                )
                if scored.top_paper_title:
                    out.append(scored)
                if len(out) >= top:
                    break
    finally:
        if old_timeout is None:
            os.environ.pop("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", None)
        else:
            os.environ["TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"] = old_timeout
    return tuple(sorted(out, key=_rank_key))


def _fullraw_supply_candidates(
    *, query_context: str, current_year: int, top: int,
    seeds: tuple[str, ...] = (),
) -> tuple[TopicCandidate, ...]:
    """Build fallback topics from fullraw only when each topic clears the floor."""
    query_labels: dict[str, str] = {}
    context_terms = _context_query_terms(query_context)
    context_variants = _context_variants(query_context)
    query_cap = max(_seed_paper_probe_limit(top), top * 6)
    seed_bases = [
        (seed, tuple(base.strip() for base in expand_topic_queries(seed, max_queries=2)
                     if base.strip()))
        for seed in seeds
    ]
    for variant in context_variants[:1] or ("",):
        for seed, bases in seed_bases:
            if not bases:
                continue
            query = f"{bases[0]} {variant}".strip()
            query_labels.setdefault(query, seed)
            if len(query_labels) >= query_cap:
                break
        if len(query_labels) >= query_cap:
            break
    if query := context_terms:
        query_labels.setdefault(query, "__domain_supply__")
    for seed, bases in seed_bases:
        for base in bases:
            for variant in context_variants[1:]:
                query_labels.setdefault(f"{base} {variant}", seed)
                if len(query_labels) >= query_cap:
                    break
            query_labels.setdefault(base, seed)
            if len(query_labels) >= query_cap:
                break
        if len(query_labels) >= query_cap:
            break
    if top <= 0 or not query_labels:
        return ()
    papers_by_key: dict[str, dict[str, object]] = {}
    papers_by_query: dict[str, list[dict[str, object]]] = {}
    out: list[TopicCandidate] = []
    seen_topics: set[str] = set()
    used_seed_labels: set[str] = set()
    deadline = time.monotonic() + _fullraw_supply_budget_seconds()
    with httpx.Client() as client:
        for query, label in query_labels.items():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if label != "__domain_supply__" and label in used_seed_labels:
                continue
            query_timeout = str(min(_fullraw_supply_query_timeout_seconds(), remaining))
            query_budget = str(min(_fullraw_supply_query_budget_seconds(), remaining))
            old_timeout = os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS")
            old_budget = os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS")
            old_sweep = os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS")
            os.environ["TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"] = query_timeout
            os.environ["TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"] = query_budget
            os.environ["TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"] = "0"
            receipt_recorded = False
            try:
                for paper in _seed_fullraw_papers(
                    query, client=client, limit=_SOURCE_RICH_FLOOR,
                ):
                    key = str(paper.get("doi") or paper.get("paper_id")
                              or paper.get("title") or "").strip().casefold()
                    if not key or key in papers_by_key:
                        continue
                    papers_by_key[key] = paper
                    papers_by_query.setdefault(query, []).append(paper)
                    receipt = paper.get("fullraw_shard_receipt")
                    if isinstance(receipt, dict) and not receipt_recorded:
                        _FULLRAW_PROBE_RECEIPTS.append({
                            "seed": label,
                            "query": query,
                            "shards_searched": receipt.get("shards_searched"),
                            "partial_shard_search": receipt.get("partial_shard_search"),
                            "sources_searched": receipt.get("sources_searched"),
                        })
                        receipt_recorded = True
            finally:
                for key, value in (
                    ("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", old_timeout),
                    ("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", old_budget),
                    ("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS", old_sweep),
                ):
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            if label != "__domain_supply__":
                scoped = _query_supported_papers(
                    papers_by_query.get(query, []), query, context_terms)
                if len(scoped) >= _SOURCE_RICH_FLOOR:
                    topic = "_".join(query.split())
                    seen_topics.add(topic)
                    used_seed_labels.add(label)
                    out.append(_score_topic(
                        topic, scoped[:25], current_year,
                        fact_source_count=len(scoped),
                    ))
                    if len(out) >= top:
                        return tuple(sorted(out, key=_rank_key))
    papers = list(papers_by_key.values())
    if len(papers) < _SOURCE_RICH_FLOOR:
        return ()

    for query, label in query_labels.items():
        if label == "__domain_supply__":
            continue
        scoped = _query_supported_papers(
            papers_by_query.get(query, []), query, context_terms)
        if len(scoped) < _SOURCE_RICH_FLOOR:
            continue
        topic = "_".join(query.split())
        seen_topics.add(topic)
        out.append(_score_topic(
            topic, scoped[:25], current_year, fact_source_count=len(scoped),
        ))
        if len(out) >= top:
            return tuple(sorted(out, key=_rank_key))
    for topic in _title_topic_slugs({"fullraw": papers}, current_year, limit=top * 12):
        if topic in seen_topics:
            continue
        topic_tokens = set(_TOKEN_RE.findall(topic.replace("_", " ").casefold()))
        scoped = _context_supported_papers([
            paper for paper in papers
            if topic_tokens <= set(_TOKEN_RE.findall(
                str(paper.get("title") or "").casefold()))
        ], context_terms)
        if len(scoped) < _SOURCE_RICH_FLOOR:
            continue
        out.append(_score_topic(
            topic, scoped[:25], current_year, fact_source_count=len(scoped),
        ))
        if len(out) >= top:
            break
    if not out:
        scoped = _context_supported_papers(papers, context_terms)
        if len(scoped) >= _SOURCE_RICH_FLOOR:
            out.append(_score_topic(
                "_".join(next(iter(query_labels)).split()), scoped[:25],
                current_year, fact_source_count=len(scoped),
            ))
    return tuple(sorted(out, key=_rank_key))


def _filter_excluded(
    candidates: tuple[TopicCandidate, ...], excluded: set[str],
) -> tuple[TopicCandidate, ...]:
    if not excluded:
        return candidates
    return tuple(c for c in candidates if not _topic_family_excluded(c.topic, excluded))


def _topic_key(value: str) -> str:
    return "_".join(_TOKEN_RE.findall(value.casefold()))


def _topic_tokens(value: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(value.casefold())
        if len(token) > 1 and token not in _GENERIC_SCOPE_TOKENS
    }


def _topic_family_excluded(topic: str, excluded: set[str]) -> bool:
    if topic in excluded:
        return True
    topic_key = _topic_key(topic)
    topic_tokens = _topic_tokens(topic)
    for blocked in excluded:
        if topic_key and topic_key == _topic_key(blocked):
            return True
        blocked_tokens = _topic_tokens(blocked)
        if not topic_tokens or not blocked_tokens:
            continue
        overlap = len(topic_tokens & blocked_tokens)
        if overlap >= 2 and overlap / min(len(topic_tokens), len(blocked_tokens)) >= 0.5:
            return True
        if overlap == 1 and min(len(topic_tokens), len(blocked_tokens)) == 1:
            return True
    return False


def _domain_scope(seeds: tuple[str, ...]) -> tuple[set[str], set[str]]:
    exact = {_topic_key(seed) for seed in seeds if _topic_key(seed)}
    tokens: set[str] = set()
    for seed in seeds:
        for query in expand_topic_queries(seed, max_queries=64):
            tokens.update(_topic_tokens(query))
    return exact, tokens


def _filter_domain_scope(
    candidates: tuple[TopicCandidate, ...], seeds: tuple[str, ...],
) -> tuple[TopicCandidate, ...]:
    exact, tokens = _domain_scope(seeds)
    if not exact or not tokens:
        return candidates
    return tuple(
        c for c in candidates
        if _topic_key(c.topic) in exact or bool(_topic_tokens(c.topic) & tokens)
    )


def _filter_cached_seed_scope(
    candidates: tuple[TopicCandidate, ...], seeds: tuple[str, ...],
) -> tuple[TopicCandidate, ...]:
    seed_keys = tuple(_topic_key(seed) for seed in seeds if _topic_key(seed))
    if not seed_keys:
        return candidates
    return tuple(
        c for c in candidates
        if any(
            (key := _topic_key(c.topic)) == seed
            or key.startswith(f"{seed}_")
            for seed in seed_keys
        )
    )


def _source_rich(candidate: TopicCandidate) -> bool:
    return (
        candidate.paper_count >= _SOURCE_RICH_FLOOR
        and candidate.fact_source_count >= _SOURCE_RICH_FLOOR
    )


def _scope_and_hydrate_candidates(
    candidates: tuple[TopicCandidate, ...], seeds: tuple[str, ...],
    excluded: set[str], *, settings: Settings, current_year: int,
    query_context: str, hydrate_source_rich: bool = True,
) -> tuple[TopicCandidate, ...]:
    domain_scoped = _filter_domain_scope(_filter_excluded(candidates, excluded), seeds)
    strict_scoped = _filter_cached_seed_scope(domain_scoped, seeds)
    strict_source_rich = tuple(
        c for c in strict_scoped if _source_rich(c)
    ) if not hydrate_source_rich else ()
    hydrated = _hydrate_candidates(
        tuple(c for c in strict_scoped if c not in strict_source_rich),
        settings=settings, current_year=current_year,
        query_context=query_context,
    )
    if strict_source_rich or hydrated:
        return _merge_candidates(strict_source_rich, hydrated)
    # If strict parent/child naming is exhausted by cooldowns or dedupe, allow
    # source-rich domain-scope rows through. This keeps the evidence floor while
    # avoiding infinite loops over already-used parent topics.
    relaxed = tuple(c for c in domain_scoped if _source_rich(c))
    if hydrate_source_rich:
        return _hydrate_candidates(
            relaxed, settings=settings, current_year=current_year,
            query_context=query_context,
        )
    return tuple(sorted(relaxed, key=_rank_key))


def _domain_seed_topics(domain: str) -> tuple[str, ...]:
    profile = load_domain_profile(domain)
    return (
        load_seed_topics()
        if profile.slug == "longevity" else
        load_seed_topics(profile.seed_topics_path)
    )


def _domain_derived_topic_limit(domain: str) -> int:
    profile = load_domain_profile(domain)
    return (
        load_derived_topic_limit()
        if profile.slug == "longevity" else
        load_derived_topic_limit(profile.seed_topics_path)
    )


def _cache_supported(domain: str) -> bool:
    """Whether ``domain`` may read the source-rich supply cache.

    The cache holds the default (longevity) seed space, and the candidate set
    is filtered by token-overlap, not strict seed membership — so a domain with
    its own seeds would pull default-space topics into its discovery. Only
    domains that share the default seed file (longevity, longevity_research)
    may read it; others fall through to live discovery.
    """
    return (
        load_domain_profile(domain).seed_topics_path
        == load_domain_profile(None).seed_topics_path
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=domain_choices(), default="longevity")
    parser.add_argument("--top", type=int, default=10,
                        help="Emit top-N candidates (default 10)")
    parser.add_argument(
        "--derived-topic-limit", type=int, default=None,
        help="Override configured derived-topic candidate cap.",
    )
    parser.add_argument(
        "--fact-probe-topics", type=int, default=None,
        help="Override extra derived topics probed for source breadth.",
    )
    parser.add_argument(
        "--warm-backlog", action="store_true",
        help="Probe source breadth for the full derived pool; slower, for backlog warming.",
    )
    parser.add_argument(
        "--cache-first", action="store_true",
        help="Use fresh cached source-rich topics when they fill the requested window.",
    )
    parser.add_argument(
        "--cache-only", action="store_true",
        help="Emit cached source-rich topics without slow DB expansion.",
    )
    parser.add_argument(
        "--seed-paper-only", action="store_true",
        help="After cache, use bounded seed-paper probes only; skip slow DB expansion.",
    )
    parser.add_argument(
        "--fullraw-supply-only", action="store_true",
        help="Use source-rich fullraw supply only; skip seed-paper and DB expansion.",
    )
    parser.add_argument(
        "--skip-seed-paper-probe", action="store_true",
        help="Skip fullraw seed-paper probes and go straight to domain discovery.",
    )
    parser.add_argument(
        "--exclude-topic", action="append", default=[],
        help="Exclude a topic from the emitted queue; repeatable.",
    )
    args = parser.parse_args()
    _FULLRAW_PROBE_RECEIPTS.clear()
    _FULLRAW_PROBE_EVENTS.clear()
    profile = load_domain_profile(args.domain)
    seeds = _domain_seed_topics(profile.slug)
    if not seeds:
        print(f"[topic-discovery] no seeds for domain={profile.slug}",
              file=sys.stderr)
        return 1
    settings = load_settings()
    year = dt.datetime.now(dt.UTC).year
    derived_limit, fact_probe_topics = _resolve_limits(
        warm_backlog=args.warm_backlog,
        derived_topic_limit=args.derived_topic_limit,
        fact_probe_topics=args.fact_probe_topics,
        configured_limit=_domain_derived_topic_limit(profile.slug),
    )
    cache_limit = max(args.top, fact_probe_topics or 0)
    excluded = {str(t).strip() for t in args.exclude_topic if str(t).strip()}
    cache_supported = _cache_supported(profile.slug)
    scoped_cache_limit = max(cache_limit * 20, 1000) if cache_supported else cache_limit
    read_source_rich_cache = args.cache_first or args.cache_only
    ranked = (
        cached_source_rich_candidates(limit=scoped_cache_limit)
        if cache_supported
        and read_source_rich_cache
        and cache_limit > 0 else ()
    )
    ranked = _filter_cached_seed_scope(_filter_excluded(ranked, excluded), seeds)
    paper_backed_cached = sum(1 for c in ranked if c.paper_count and c.top_paper_title)
    seed_paper_ranked: tuple[TopicCandidate, ...] = ()
    seed_probe_seeds = tuple(
        seed for seed in seeds
        if not _topic_family_excluded(seed, excluded)
    )
    fullraw_supply_checked = False
    if (
        paper_backed_cached < args.top
        and not args.cache_only
        and not args.seed_paper_only
        and not args.skip_seed_paper_probe
    ):
        fullraw_supply_checked = True
        ranked = _merge_candidates(
            ranked,
            _filter_excluded(
                _fullraw_supply_candidates(
                    query_context=profile.display_name,
                    current_year=year,
                    top=max(1, args.top - paper_backed_cached),
                    seeds=seed_probe_seeds,
                ),
                excluded,
            ),
        )
        paper_backed_cached = sum(1 for c in ranked if c.paper_count and c.top_paper_title)
    if (
        paper_backed_cached < args.top
        and not args.cache_only
        and not args.skip_seed_paper_probe
        and not args.fullraw_supply_only
    ):
        seed_paper_ranked = _filter_excluded(
            _seed_paper_candidates(
                seed_probe_seeds, settings=settings, current_year=year,
                query_context=profile.display_name,
                top=max(1, args.top - paper_backed_cached),
            ),
            excluded,
        )
        ranked = _merge_candidates(ranked, seed_paper_ranked)
        paper_backed_cached = sum(1 for c in ranked if c.paper_count and c.top_paper_title)
    if (
        paper_backed_cached < args.top
        and not args.cache_only
        and not args.seed_paper_only
        and not args.fullraw_supply_only
    ):
        with httpx.Client() as client:
            discovered = discover_topics(
                seeds=seeds, settings=settings, client=client,
                domain=profile.slug,
                derived_topic_limit=derived_limit,
                fact_probe_topics=fact_probe_topics,
                use_cached_source_rich=cache_supported,
                refresh_low_source_counts=args.warm_backlog,
            )
        scoped_discovered = _scope_and_hydrate_candidates(
            discovered, seeds, excluded, settings=settings, current_year=year,
            query_context=profile.display_name,
            hydrate_source_rich=not args.skip_seed_paper_probe,
        )
        if not scoped_discovered and os.environ.get("TOPIC_GROUPS_DISCOVERY") != "0":
            old = os.environ.get("TOPIC_GROUPS_DISCOVERY")
            os.environ["TOPIC_GROUPS_DISCOVERY"] = "0"
            try:
                fallback_derived_limit = min(derived_limit, max(args.top * 10, 10))
                fallback_fact_probe_topics = (
                    min(fact_probe_topics, max(args.top, 3))
                    if fact_probe_topics is not None else max(args.top, 3)
                )
                with httpx.Client() as client:
                    fallback = discover_topics(
                        seeds=seeds, settings=settings, client=client,
                        domain=profile.slug,
                        derived_topic_limit=fallback_derived_limit,
                        fact_probe_topics=fallback_fact_probe_topics,
                        use_cached_source_rich=cache_supported,
                        refresh_low_source_counts=args.warm_backlog,
                    )
            finally:
                if old is None:
                    os.environ.pop("TOPIC_GROUPS_DISCOVERY", None)
                else:
                    os.environ["TOPIC_GROUPS_DISCOVERY"] = old
            scoped_discovered = _merge_candidates(
                scoped_discovered,
                _scope_and_hydrate_candidates(
                    fallback, seeds, excluded, settings=settings, current_year=year,
                    query_context=profile.display_name,
                    hydrate_source_rich=not args.skip_seed_paper_probe,
                ),
            )
        ranked = _merge_candidates(ranked, scoped_discovered)
    paper_backed_ranked = sum(1 for c in ranked if _paper_backed(c))
    if (
        paper_backed_ranked < args.top
        and not args.cache_only
        and not args.seed_paper_only
        and not args.skip_seed_paper_probe
        and not fullraw_supply_checked
    ):
        ranked = _merge_candidates(
            ranked,
            _filter_excluded(
                _fullraw_supply_candidates(
                    query_context=profile.display_name,
                    current_year=year,
                    top=max(1, args.top - paper_backed_ranked),
                    seeds=seed_probe_seeds,
                ),
                excluded,
            ),
        )
    top = ranked[: args.top]
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = (Path(__file__).resolve().parent.parent
               / "runs" / "_topics_discovery")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_payload = {
        "domain": profile.as_metadata(),
        "snapshot_utc": ts, "year": year,
        "seed_count": len(seeds), "candidate_count": len(ranked),
        "derived_topic_limit": derived_limit,
        "fact_probe_topics": fact_probe_topics,
        "warm_backlog": bool(args.warm_backlog),
        "cache_first": bool(read_source_rich_cache and cache_supported),
        "cache_only": bool(args.cache_only and cache_supported),
        "seed_paper_only": bool(args.seed_paper_only),
        "fullraw_supply_only": bool(args.fullraw_supply_only),
        "fullraw_seed_probe": {
            "configured": _fullraw_configured(),
            "receipt_count": len(_FULLRAW_PROBE_RECEIPTS),
            "receipts": _FULLRAW_PROBE_RECEIPTS[:10],
            "event_count": len(_FULLRAW_PROBE_EVENTS),
            "events": _FULLRAW_PROBE_EVENTS[:10],
        },
        "cache_supported": cache_supported,
        "source_rich_floor": _SOURCE_RICH_FLOOR,
        "source_rich_count": sum(1 for c in ranked if _source_rich(c)),
        "top": [c.as_dict() for c in top],
        "all": [c.as_dict() for c in ranked],
    }
    publish_io.write_json(out_dir / f"{ts}.json", json_payload)
    publish_io.write_text(
        out_dir / f"{ts}.md",
        _render_md({"snapshot_utc": ts, "seed_count": str(len(seeds)),
                    "year": str(year)}, top),
    )
    print(f"[topic-discovery] seeds={len(seeds)} ranked={len(ranked)} "
          f"domain={profile.slug} "
          f"source_rich={json_payload['source_rich_count']} "
          f"-> runs/_topics_discovery/{ts}.json")
    for i, c in enumerate(top, start=1):
        print(f"  #{i}  velocity={c.velocity_score:6.2f}  "
              f"{c.topic:25}  papers={c.paper_count:3} "
              f"fact_sources={c.fact_source_count:2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
