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
from scripts import alpha_publish_io as publish_io

_FAST_DERIVED_TOPIC_LIMIT = 250


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


def _paper_backed(candidate: TopicCandidate) -> bool:
    return bool(candidate.paper_count and candidate.top_paper_title)


def _rank_key(candidate: TopicCandidate) -> tuple[int, int, float, int, str]:
    return (
        -int(_paper_backed(candidate)),
        -min(candidate.paper_count, candidate.fact_source_count),
        -candidate.velocity_score,
        -candidate.paper_count,
        candidate.topic,
    )


def _hydrate_candidates(
    candidates: tuple[TopicCandidate, ...], *, client: httpx.Client,
    settings: Settings, current_year: int,
) -> tuple[TopicCandidate, ...]:
    out: list[TopicCandidate] = []
    for candidate in candidates:
        if _paper_backed(candidate):
            out.append(candidate)
            continue
        scored = _score_topic(
            candidate.topic,
            _fetch_topic_papers(candidate.topic, client=client, settings=settings),
            current_year,
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
            ))
    return tuple(sorted(out, key=_rank_key))


def _filter_excluded(
    candidates: tuple[TopicCandidate, ...], excluded: set[str],
) -> tuple[TopicCandidate, ...]:
    if not excluded:
        return candidates
    return tuple(c for c in candidates if c.topic not in excluded)


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


def _cache_supported_domain(domain: str) -> bool:
    profile = load_domain_profile(domain)
    default_profile = load_domain_profile(None)
    return profile.seed_topics_path == default_profile.seed_topics_path


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
    derived_limit, fact_probe_topics = _resolve_limits(
        warm_backlog=args.warm_backlog,
        derived_topic_limit=args.derived_topic_limit,
        fact_probe_topics=args.fact_probe_topics,
        configured_limit=_domain_derived_topic_limit(profile.slug),
    )
    cache_limit = max(args.top, fact_probe_topics or 0)
    excluded = {str(t).strip() for t in args.exclude_topic if str(t).strip()}
    cache_supported = _cache_supported_domain(profile.slug)
    ranked = (
        cached_source_rich_candidates(limit=cache_limit)
        if cache_supported
        and (args.cache_first or args.cache_only)
        and cache_limit > 0 else ()
    )
    ranked = _filter_excluded(ranked, excluded)
    paper_backed_cached = sum(1 for c in ranked if _paper_backed(c))
    if paper_backed_cached < args.top and not args.cache_only:
        with httpx.Client() as client:
            discovered = discover_topics(
                seeds=seeds, settings=settings, client=client,
                derived_topic_limit=derived_limit,
                fact_probe_topics=fact_probe_topics,
                refresh_low_source_counts=args.warm_backlog,
            )
            discovered = _hydrate_candidates(
                _filter_excluded(discovered, excluded),
                client=client, settings=settings, current_year=dt.datetime.now(dt.UTC).year,
            )
            if len(discovered) < args.top:
                old = os.environ.get("TOPIC_GROUPS_DISCOVERY")
                os.environ["TOPIC_GROUPS_DISCOVERY"] = "0"
                try:
                    fallback = discover_topics(
                        seeds=seeds, settings=settings, client=client,
                        derived_topic_limit=derived_limit,
                        fact_probe_topics=fact_probe_topics,
                        refresh_low_source_counts=args.warm_backlog,
                    )
                finally:
                    if old is None:
                        os.environ.pop("TOPIC_GROUPS_DISCOVERY", None)
                    else:
                        os.environ["TOPIC_GROUPS_DISCOVERY"] = old
                discovered = _merge_candidates(
                    discovered,
                    _hydrate_candidates(
                        _filter_excluded(fallback, excluded),
                        client=client, settings=settings,
                        current_year=dt.datetime.now(dt.UTC).year,
                    ),
                )
        ranked = _merge_candidates(ranked, discovered)
    top = ranked[: args.top]
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    year = dt.datetime.now(dt.UTC).year
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
