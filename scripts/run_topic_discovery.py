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
    _fetch_fullraw_topic_papers,
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


def _seed_query_limit() -> int:
    try:
        return max(1, int(os.environ.get("TOPIC_DISCOVERY_SEED_QUERIES", 6)))
    except (TypeError, ValueError):
        return 6


def _seed_paper_probe_limit(top: int) -> int:
    try:
        return max(0, int(os.environ.get("TOPIC_DISCOVERY_SEED_PAPER_TOPICS", 6)))
    except (TypeError, ValueError):
        return max(top, 6)


def _fullraw_configured() -> bool:
    return bool(os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "").strip())


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
        with httpx.Client() as client:
            for seed in seeds[:_seed_paper_probe_limit(top)]:
                candidate = TopicCandidate(
                    topic=seed, paper_count=0, fact_source_count=0,
                    top_paper_doi="", top_paper_title="",
                    velocity_score=0.0, mean_fwci=0.0, mean_cited_by=0.0,
                )
                if not _hydration_probeable(candidate):
                    continue
                papers_by_key: dict[str, dict[str, object]] = {}
                for query in _seed_paper_queries(seed, context=query_context):
                    for paper in _fetch_fullraw_topic_papers(query, client=client, limit=5):
                        key = str(paper.get("doi") or paper.get("paper_id")
                                  or paper.get("title") or "").strip().casefold()
                        if key:
                            papers_by_key.setdefault(key, paper)
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
        "--seed-paper-only", action="store_true",
        help="After cache, use bounded seed-paper probes only; skip slow DB expansion.",
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
    read_source_rich_cache = args.cache_first or args.cache_only or args.warm_backlog
    ranked = (
        cached_source_rich_candidates(limit=scoped_cache_limit)
        if cache_supported
        and read_source_rich_cache
        and cache_limit > 0 else ()
    )
    ranked = _filter_cached_seed_scope(_filter_excluded(ranked, excluded), seeds)
    paper_backed_cached = sum(1 for c in ranked if c.paper_count and c.top_paper_title)
    seed_paper_ranked: tuple[TopicCandidate, ...] = ()
    if paper_backed_cached < args.top and not args.cache_only:
        seed_paper_ranked = _filter_excluded(
            _seed_paper_candidates(
                seeds, settings=settings, current_year=year,
                query_context=profile.display_name,
                top=max(1, args.top - paper_backed_cached),
            ),
            excluded,
        )
        ranked = _merge_candidates(ranked, seed_paper_ranked)
        paper_backed_cached = sum(1 for c in ranked if c.paper_count and c.top_paper_title)
    if paper_backed_cached < args.top and not args.cache_only and not args.seed_paper_only:
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
                _hydrate_candidates(
                    _filter_cached_seed_scope(
                        _filter_domain_scope(
                            _filter_excluded(fallback, excluded), seeds,
                        ),
                        seeds,
                    ),
                    settings=settings,
                    current_year=year,
                    query_context=profile.display_name,
                ),
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
        "cache_first": bool(read_source_rich_cache and cache_supported),
        "cache_only": bool(args.cache_only and cache_supported),
        "seed_paper_only": bool(args.seed_paper_only),
        "cache_supported": cache_supported,
        "source_rich_floor": 5,
        "source_rich_count": sum(1 for c in ranked if c.fact_source_count >= 5),
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
