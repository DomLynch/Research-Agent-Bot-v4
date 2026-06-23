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
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.domain_profile import domain_choices, load_domain_profile
from agent.settings import Settings, load_settings
from agent.topic_discovery import (
    TopicCandidate,
    _fetch_topic_papers,
    _score_topic,
    cached_source_rich_candidates,
    discover_topics,
    load_derived_topic_limit,
    load_seed_topics,
)
from agent.topic_synonyms import expand_topic_queries
from scripts import alpha_publish_io as publish_io

_FAST_DERIVED_TOPIC_LIMIT = 250
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENERIC_SCOPE_TOKENS = {
    "ai", "research", "study", "studies", "trial", "trials", "review",
    "meta", "analysis", "effect", "effects", "therapy", "treatment",
    "use", "uses", "intervention", "interventions", "outcome", "outcomes",
}


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


def _context_query_terms(value: str) -> str:
    seen: dict[str, None] = {}
    for token in _TOKEN_RE.findall(value.casefold()):
        if len(token) > 1 and token not in _GENERIC_SCOPE_TOKENS:
            seen.setdefault(token, None)
    return " ".join(seen)


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
    paper_backed = int(bool(candidate.paper_count and candidate.top_paper_title))
    return (
        -paper_backed,
        -min(candidate.paper_count, candidate.fact_source_count),
        -candidate.velocity_score,
        -candidate.paper_count,
        candidate.topic,
    )


def _hydrate_candidates(
    candidates: tuple[TopicCandidate, ...], *, settings: Settings,
    current_year: int, query_context: str = "",
) -> tuple[TopicCandidate, ...]:
    out = list(candidates)
    limit = min(_hydrate_limit(), len(out))
    if limit <= 0:
        return tuple(sorted(out, key=_rank_key))
    with httpx.Client() as client:
        for idx, candidate in enumerate(out[:limit]):
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
            out[idx] = TopicCandidate(
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
            )
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
        "--exclude-topic", action="append", default=[],
        help="Exclude a topic from the emitted queue; repeatable.",
    )
    args = parser.parse_args()
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
    ranked = (
        cached_source_rich_candidates(limit=scoped_cache_limit)
        if cache_supported
        and (args.cache_first or args.cache_only)
        and cache_limit > 0 else ()
    )
    ranked = _filter_cached_seed_scope(_filter_excluded(ranked, excluded), seeds)
    paper_backed_cached = sum(1 for c in ranked if c.paper_count and c.top_paper_title)
    if paper_backed_cached < args.top and not args.cache_only:
        with httpx.Client() as client:
            discovered = discover_topics(
                seeds=seeds, settings=settings, client=client,
                domain=profile.slug,
                derived_topic_limit=derived_limit,
                fact_probe_topics=fact_probe_topics,
                use_cached_source_rich=cache_supported,
                refresh_low_source_counts=args.warm_backlog,
            )
        # Scope discovered topics to this domain's own seeds + their children.
        # The token-overlap filter alone leaks cross-domain topics: with 100
        # seeds each expanded to dozens of queries, the token union is huge and
        # an AI topic like multi_agent_systems matches longevity on generic
        # tokens ("agent" from "senolytic agents", "systems" from "biological
        # systems"). The strict seed-scope (seed or seed_child) is what keeps a
        # longevity cycle from building and submitting AI topics tagged
        # longevity. Universal: each domain scopes to its own seed list.
        scoped_discovered = _filter_cached_seed_scope(
            _filter_domain_scope(
                _filter_excluded(discovered, excluded), seeds,
            ),
            seeds,
        )
        scoped_discovered = _hydrate_candidates(
            scoped_discovered, settings=settings, current_year=year,
            query_context=profile.display_name,
        )
        ranked = _merge_candidates(ranked, scoped_discovered)
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
        "cache_first": bool(args.cache_first and cache_supported),
        "cache_only": bool(args.cache_only and cache_supported),
        "cache_supported": cache_supported,
        "source_rich_floor": 5,
        "source_rich_count": sum(1 for c in ranked if c.fact_source_count >= 5),
        "top": [c.as_dict() for c in top],
        "all": [c.as_dict() for c in ranked],
    }
    publish_io.write_json(out_dir / f"{ts}.json", json_payload)
    (out_dir / f"{ts}.md").write_text(
        _render_md({"snapshot_utc": ts, "seed_count": str(len(seeds)),
                    "year": str(year)}, top),
        encoding="utf-8")
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
