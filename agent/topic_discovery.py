"""Sprint 63 — Autonomous topic-discovery loop.

Closes the curator role: v4 stops needing hand-picked topics. For
each seed topic in topic_packs/discovery_seeds.toml the discovery
probes POST /api/v1/papers/topic, computes a per-paper velocity
score, aggregates per topic, and ranks. The top candidates feed the
operator queue that drives subsequent build_topic_evidence_run runs.

Velocity formula (universal, no domain literals):
    paper_score = fwci * log(1 + cited_by_count) * recency_weight
                  * (quality_score / 100)
    if a paper anchors M >= 3 topics' top-K, contribution /= sqrt(M)
    topic_score = mean(top-K paper_score for that topic)

recency_weight = max(0.2, 1 - (current_year - publication_year) / 10)

Tolerant: HTTP / JSON errors return empty list. Never raises.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from agent.fact_lanes import classify_lanes
from agent.settings import Settings
from agent.topic_synonyms import expand_topic_queries

_SEEDS_TOML = (Path(__file__).resolve().parent.parent
               / "topic_packs" / "discovery_seeds.toml")
# Per-topic A_core source-count cache. The probe is concurrent and
# network-bound; a timed-out query is indistinguishable from genuine
# scarcity (both yield 0), so under load a rich topic randomly drops
# to 0 and gets mis-ranked as worthless. The cache persists the last
# SUCCESSFUL count per topic so a transient failure never overwrites a
# known-good value, and only stale/missing topics are re-probed (which
# also slashes per-cycle DB load). Universal — no domain literals.
_SUPPLY_CACHE_PATH = (Path(__file__).resolve().parent.parent
                      / "runs" / "_topic_supply_cache.json")
_SUPPLY_CACHE_VERSION = 5
_PUBLISHABLE_SOURCE_FLOOR = 5
_PROBE_INCONCLUSIVE = -1  # all queries failed (timeout/error), not a real 0
_DERIVED_TOPIC_LIMIT = 5_000
# All configured seeds are probed; this caps extra velocity/derived topics on
# the latency-sensitive publish path. Full-pool probing is an explicit backlog
# warming mode, not something the 2-hour submit cycle should wait on.
_FACT_PROBE_TOPICS = 20
_FACT_PROBE_TIMEOUT_SECONDS = 8.0
_FACT_PROBE_BUDGET_SECONDS = 24.0
_PAPER_FETCH_WORKERS = 8
# Concurrent probe workers, capped to what the shared Researka DB sustains.
# Measured capacity: at <=4 concurrent the facts endpoint answers in <8s (the
# per-query timeout) and every probe succeeds; at 6-8 concurrent its latency
# climbs to 12s+ so queries exceed the timeout, return -1, and under sustained
# load it 504s — which starved discovery (all topics looked like 0 sources)
# and stopped the supply cache from ever warming. 4 keeps probes succeeding so
# the cache fills and steady-state load collapses to near zero.
_FACT_PROBE_WORKERS = 4
_TITLE_WORD = re.compile(r"[a-z][a-z0-9]+")
_TITLE_STOPWORDS = frozenset({
    "and", "the", "for", "with", "from", "into", "using", "among", "after",
    "before", "during", "across", "study", "trial", "review", "analysis",
    "effect", "effects", "association", "associated", "based", "between",
    "patients", "adults", "human", "mouse", "mice", "model", "models",
    "new", "novel",
})


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


_SUPPLY_CACHE_TTL_SECONDS = 86_400.0  # re-probe rich topics at most once/day
_LOW_SUPPLY_CACHE_TTL_SECONDS = _float_env(
    "RESEARCH_AGENT_LOW_TOPIC_SUPPLY_CACHE_TTL_SECONDS", 7200.0)


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    topic: str
    paper_count: int
    fact_source_count: int
    top_paper_doi: str
    top_paper_title: str
    velocity_score: float
    mean_fwci: float
    mean_cited_by: float

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "paper_count": self.paper_count,
                "fact_source_count": self.fact_source_count,
                "top_paper_doi": self.top_paper_doi,
                "top_paper_title": self.top_paper_title,
                "velocity_score": round(self.velocity_score, 3),
                "mean_fwci": round(self.mean_fwci, 3),
                "mean_cited_by": round(self.mean_cited_by, 1)}


@lru_cache(maxsize=1)
def load_seed_topics(path: Path | None = None) -> tuple[str, ...]:
    """Load seed topic list from TOML. Cached. Returns () on error."""
    target = path or _SEEDS_TOML
    if not target.exists():
        return ()
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    if not isinstance(data, dict):
        return ()
    seeds = data.get("seeds", {})
    topics = seeds.get("topics") if isinstance(seeds, dict) else None
    if not isinstance(topics, list):
        return ()
    return tuple(str(t).strip() for t in topics if str(t).strip())


def load_derived_topic_limit(path: Path | None = None) -> int:
    target = path or _SEEDS_TOML
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
        seeds = data.get("seeds", {}) if isinstance(data, dict) else {}
        raw = (
            seeds.get("derived_topic_limit", _DERIVED_TOPIC_LIMIT)
            if isinstance(seeds, dict) else _DERIVED_TOPIC_LIMIT
        )
        return max(0, int(raw))
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError):
        return _DERIVED_TOPIC_LIMIT


def _paper_score(paper: dict[str, Any], current_year: int) -> float:
    """Per-paper velocity. 0 when fields are missing — universal."""
    try:
        fwci = float(paper.get("fwci") or 0.0)
        cited = float(paper.get("cited_by_count") or 0.0)
        year = int(paper.get("publication_year") or 0)
        quality = float(paper.get("quality_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if year <= 0:
        return 0.0
    age = max(0, current_year - year)
    recency = max(0.2, 1.0 - age / 10.0)
    return fwci * math.log1p(cited) * recency * (quality / 100.0)


def _paper_key(paper: dict[str, Any]) -> str:
    """Stable cross-topic dedup key: DOI when present, else title."""
    doi = str(paper.get("doi") or "").strip().lower()
    if doi:
        return doi
    return str(paper.get("title") or "").strip().lower()[:200]


def _fact_source_key(item: dict[str, Any]) -> str:
    paper_raw = item.get("paper") or item.get("source_paper")
    paper = paper_raw if isinstance(paper_raw, dict) else {}
    return str(
        paper.get("doi")
        or paper.get("pmid")
        or paper.get("pmcid")
        or paper.get("paper_id")
        or item.get("paper_id")
        or paper.get("id")
        or paper.get("title")
        or "",
    ).strip().lower()[:200]


def _fact_for_lane(item: dict[str, Any], topic: str) -> dict[str, Any]:
    paper_raw = item.get("paper")
    paper = paper_raw if isinstance(paper_raw, dict) else {}
    return {
        "fact_id": item.get("id") or item.get("fact_id"),
        "topic": topic,
        "sub_topic": item.get("claim_type") or item.get("sub_topic") or "",
        "source_paper": {
            "doi": paper.get("doi"), "pmid": paper.get("pmid"),
            "pmcid": paper.get("pmcid"),
            "paper_id": paper.get("paper_id") or item.get("paper_id"),
            "id": paper.get("id"),
            "title": paper.get("title"),
        },
        "numeric_value": item.get("numeric_value"),
        "units": item.get("units"),
        "population": item.get("population") or "",
        "intervention": item.get("intervention") or "",
        "comparator": item.get("comparator") or "",
        "canonical_phrase": item.get("canonical_phrase") or "",
    }


def _topic_root(topic: str) -> str:
    base = list(expand_topic_queries(topic, max_queries=8))
    if not base:
        return ""
    normed = re.sub(r"[\W_]+", " ", base[0].lower()).strip()
    parts = normed.split()
    return " ".join(parts[:2]) if len(parts) > 1 else normed


def _paper_title_facets(
    topic: str, papers: list[dict[str, Any]], current_year: int, *,
    limit: int = 12,
) -> tuple[str, ...]:
    """Data-derived query facets from the topic's own retrieved papers.

    This replaces static domain slice terms. It is universal: a physics topic
    contributes physics title phrases, a policy topic contributes policy title
    phrases, and biomedical topics contribute biomedical title phrases.
    """
    root_words = set(_topic_root(topic).split())
    scores: dict[str, float] = {}
    ranked = sorted(papers, key=lambda p: _paper_score(p, current_year), reverse=True)
    for paper in ranked[:10]:
        words = [
            w for w in _TITLE_WORD.findall(str(paper.get("title") or "").lower())
            if len(w) > 2 and w not in _TITLE_STOPWORDS and w not in root_words
        ][:10]
        paper_score = _paper_score(paper, current_year) or 1.0
        for width in (2, 3):
            for i in range(0, max(0, len(words) - width + 1)):
                phrase = " ".join(words[i:i + width])
                scores[phrase] = scores.get(phrase, 0.0) + paper_score / width
    return tuple(k for k, _ in sorted(
        scores.items(), key=lambda item: item[1], reverse=True,
    )[:limit])


def _fact_probe_queries(
    topic: str, *, facets: tuple[str, ...] = (), max_queries: int = 16,
) -> tuple[str, ...]:
    base = list(expand_topic_queries(topic, max_queries=8))
    if not base:
        return ()
    stem = _topic_root(topic)
    seen: dict[str, None] = {}
    for query in base[:1]:
        seen.setdefault(query, None)
    if stem:
        seen.setdefault(stem, None)
    for query in base[1:]:
        seen.setdefault(query, None)
    for facet in facets:
        cleaned = re.sub(r"[\W_]+", " ", facet.lower()).strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen)[:max_queries]


def _fetch_topic_fact_source_count(
    topic: str, *, client: httpx.Client, settings: Settings,
    limit: int = 50, facets: tuple[str, ...] = (),
) -> int:
    """Count unique direct bindable fact-backed sources for ranking."""
    base = settings.researka_database_url.rstrip("/")
    tok = settings.researka_database_token.strip()
    if not base or not tok:
        return 0
    source_keys: set[str] = set()
    any_success = False
    deadline = time.monotonic() + _FACT_PROBE_BUDGET_SECONDS
    for query in _fact_probe_queries(topic, facets=facets):
        if time.monotonic() >= deadline:
            break
        try:
            r = client.post(
                f"{base}/api/v1/tier2/facts/search",
                headers={"X-Researka-Token": tok},
                json={
                    "query": query,
                    "top_k": limit,
                    "min_confidence": "medium",
                    "numeric_only": True,
                },
                timeout=_FACT_PROBE_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        facts = [_fact_for_lane(row, topic) for row in data if isinstance(row, dict)]
        lanes = {
            verdict.fact_id: verdict.lane
            for verdict in classify_lanes(facts, topic)
        }
        any_success = True
        source_keys.update(
            key for fact in facts
            if lanes.get(str(fact.get("fact_id") or "")) == "A_core"
            for key in (_fact_source_key(fact),) if key
        )
        if len(source_keys) >= 5:
            break
    # Distinguish "genuinely 0 A_core" (queries ran, found none) from
    # "probe failed" (every query timed out/errored). The latter must
    # NOT masquerade as a real 0 — that is what mis-ranked rich topics.
    if not any_success:
        return _PROBE_INCONCLUSIVE
    return len(source_keys)


def _load_supply_cache() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_SUPPLY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_supply_cache(cache: dict[str, dict[str, Any]]) -> None:
    try:
        _SUPPLY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SUPPLY_CACHE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        tmp.replace(_SUPPLY_CACHE_PATH)  # atomic
    except OSError:
        pass


def _supply_cache_ttl(count: int) -> float:
    if count < _PUBLISHABLE_SOURCE_FLOOR:
        return _LOW_SUPPLY_CACHE_TTL_SECONDS
    return _SUPPLY_CACHE_TTL_SECONDS


def _fresh_cached_supply_count(
    entry: Any, *, now: float, refresh_low_source_counts: bool,
) -> int | None:
    if not isinstance(entry, dict) or entry.get("version") != _SUPPLY_CACHE_VERSION:
        return None
    count = int(entry.get("count", 0))
    if (
        now - float(entry.get("ts", 0.0)) < _supply_cache_ttl(count)
        and not (refresh_low_source_counts and count < _PUBLISHABLE_SOURCE_FLOOR)
    ):
        return count
    return None


def _fetch_fact_source_counts(
    topics: list[str], *, client: httpx.Client, settings: Settings,
    refresh_low_source_counts: bool = False,
    facets_by_topic: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, int]:
    if not topics:
        return {}
    # Read cached counts first; only re-probe stale/missing topics. This
    # both slashes per-cycle DB load and means a transient probe failure
    # cannot overwrite a known-good count (see _SUPPLY_CACHE_PATH note).
    cache = _load_supply_cache()
    now = time.time()
    out: dict[str, int] = {}
    to_probe: list[str] = []
    for topic in topics:
        count = _fresh_cached_supply_count(
            cache.get(topic), now=now,
            refresh_low_source_counts=refresh_low_source_counts,
        )
        if count is not None:
            out[topic] = count
            continue
        to_probe.append(topic)
    if not to_probe:
        return out
    # Concurrency for the per-topic A_core source probe, capped to the
    # DB-sustainable level (see _FACT_PROBE_WORKERS). With the cache above
    # only stale/missing topics reach here, so steady-state pressure is low;
    # the cap protects the cold first-fill from overloading the endpoint.
    workers = min(_FACT_PROBE_WORKERS, len(to_probe))
    probed: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _fetch_topic_fact_source_count,
                topic,
                client=client,
                settings=settings,
                facets=(facets_by_topic or {}).get(topic, ()),
            ): topic
            for topic in to_probe
        }
        for fut in as_completed(futures):
            probed[futures[fut]] = fut.result()
    # Successful probe (>=0): refresh cache + use it. Inconclusive (-1):
    # keep the last cached count if any, else fall back to 0; never cache
    # a failure as a real count.
    for topic, count in probed.items():
        if count >= 0:
            cache[topic] = {
                "count": count, "ts": now, "version": _SUPPLY_CACHE_VERSION,
            }
            out[topic] = count
        else:
            prior = cache.get(topic)
            out[topic] = (int(prior.get("count", 0))
                          if isinstance(prior, dict) else 0)
    _save_supply_cache(cache)
    return out


def _title_topic_slugs(
    papers_by_topic: dict[str, list[dict[str, Any]]], current_year: int, *,
    limit: int,
) -> tuple[str, ...]:
    scores: dict[str, float] = {}
    for papers in papers_by_topic.values():
        ranked = sorted(papers, key=lambda p: _paper_score(p, current_year), reverse=True)
        for paper in ranked:
            paper_score = _paper_score(paper, current_year)
            words = [
                w for w in _TITLE_WORD.findall(str(paper.get("title") or "").lower())
                if len(w) > 2 and w not in _TITLE_STOPWORDS
            ][:12]
            for width in (2, 3, 4):
                for i in range(0, max(0, len(words) - width + 1)):
                    slug = "_".join(words[i:i + width])
                    scores[slug] = scores.get(slug, 0.0) + paper_score / width
    return tuple(k for k, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit])


def _next_uncached_topics(
    topics: list[str], *, limit: int, refresh_low_source_counts: bool,
) -> list[str]:
    """Pick the next derived topics whose supply counts need warming.

    The submit path stays bounded by `limit`, but each cycle advances through
    the derived pool instead of re-checking the same already-cached head.
    """
    if limit <= 0:
        return []
    cache = _load_supply_cache()
    now = time.time()
    due = [
        topic for topic in topics
        if _fresh_cached_supply_count(
            cache.get(topic), now=now,
            refresh_low_source_counts=refresh_low_source_counts,
        ) is None
    ]
    return (due or topics)[:limit]


def _anchorage_counts(
    papers_by_topic: dict[str, list[dict[str, Any]]],
    current_year: int, *, top_k: int = 5,
) -> dict[str, int]:
    """Sprint 70 — count how many topics include each paper in their
    top-K driver papers. Used to dampen cross-domain anchors: when one
    broad review/guideline (e.g. 2019 ACC/AHA cardiovascular paper)
    sits in the top-K of multiple unrelated topics, its contribution
    to each topic's velocity is downweighted by 1/sqrt(M) where M is
    the number of topics it anchors. Universal — structural signal
    only, no domain literals."""
    counts: dict[str, int] = {}
    for papers in papers_by_topic.values():
        if not papers:
            continue
        scored = sorted(
            ((_paper_score(p, current_year), p) for p in papers),
            key=lambda pair: pair[0], reverse=True,
        )
        for _, p in scored[:top_k]:
            k = _paper_key(p)
            if k:
                counts[k] = counts.get(k, 0) + 1
    return counts


def _score_topic(
    topic: str, papers: list[dict[str, Any]], current_year: int,
    *, top_k: int = 5,
    fact_source_count: int = 0,
    anchorage: dict[str, int] | None = None,
) -> TopicCandidate:
    """Aggregate per-paper scores; pick the strongest paper as anchor.

    When `anchorage` is supplied, dampen each paper's contribution by
    1/sqrt(M) when it anchors M ≥ 3 other topics' top-K. Keeps
    single-topic specificity intact (M < 3 = no dampening) while
    penalising cross-domain reviews / guidelines.
    """
    if not papers:
        return TopicCandidate(
            topic=topic, paper_count=0, fact_source_count=fact_source_count,
            top_paper_doi="",
            top_paper_title="", velocity_score=0.0,
            mean_fwci=0.0, mean_cited_by=0.0,
        )

    def _adjusted(p: dict[str, Any]) -> float:
        s = _paper_score(p, current_year)
        if anchorage:
            m = anchorage.get(_paper_key(p), 1)
            if m >= 3:
                s = s / math.sqrt(m)
        return s

    scored = sorted(
        ((_adjusted(p), p) for p in papers),
        key=lambda pair: pair[0], reverse=True,
    )
    top = scored[:top_k]
    velocity = sum(s for s, _ in top) / max(1, len(top))
    top_paper = top[0][1] if top else {}
    fwci_vals = [float(p.get("fwci") or 0.0) for p in papers]
    cited_vals = [float(p.get("cited_by_count") or 0.0) for p in papers]
    return TopicCandidate(
        topic=topic, paper_count=len(papers), fact_source_count=fact_source_count,
        top_paper_doi=str(top_paper.get("doi") or ""),
        top_paper_title=str(top_paper.get("title") or "")[:200],
        velocity_score=velocity,
        mean_fwci=sum(fwci_vals) / len(fwci_vals),
        mean_cited_by=sum(cited_vals) / len(cited_vals),
    )


def _fetch_topic_papers(
    topic: str, *, client: httpx.Client, settings: Settings,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """POST /api/v1/papers/topic; [] on any error."""
    base = settings.researka_database_url.rstrip("/")
    tok = settings.researka_database_token.strip()
    if not base or not tok:
        return []
    try:
        r = client.post(
            f"{base}/api/v1/papers/topic",
            headers={"X-Researka-Token": tok},
            json={"topic": topic, "limit": limit}, timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]


def _fetch_papers_by_topic(
    topics: list[str], *, client: httpx.Client, settings: Settings,
) -> dict[str, list[dict[str, Any]]]:
    if not topics:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    workers = min(_PAPER_FETCH_WORKERS, len(topics))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_topic_papers, topic, client=client, settings=settings): topic
            for topic in topics
        }
        for fut in as_completed(futures):
            topic = futures[fut]
            out[topic] = fut.result()
    return out


def discover_topics(
    seeds: tuple[str, ...] | None = None, *,
    settings: Settings, client: httpx.Client | None = None,
    current_year: int | None = None,
    derived_topic_limit: int = 0,
    fact_probe_topics: int | None = None,
    refresh_low_source_counts: bool = False,
) -> tuple[TopicCandidate, ...]:
    """Score every seed topic; return ranked tuple (highest velocity first).
    Never raises — degrades silently on HTTP/JSON errors per topic."""
    topics = seeds if seeds is not None else load_seed_topics()
    if not topics:
        return ()
    year_now = current_year or dt.datetime.now(dt.UTC).year
    own_client = client is None
    c = client or httpx.Client()
    try:
        papers_by_topic = _fetch_papers_by_topic(
            list(topics), client=c, settings=settings)
        known = set(papers_by_topic)
        if derived_topic_limit:
            derived = [
                topic for topic in _title_topic_slugs(
                    papers_by_topic, year_now, limit=derived_topic_limit)
                if topic not in known
            ]
            papers_by_topic.update(_fetch_papers_by_topic(
                derived, client=c, settings=settings))
        anchorage = _anchorage_counts(papers_by_topic, year_now)
        velocity_ranked = sorted(
            [
                _score_topic(topic, papers, year_now, anchorage=anchorage)
                for topic, papers in papers_by_topic.items()
            ],
            key=lambda c: c.velocity_score,
            reverse=True,
        )
        extra_probe_limit = (
            _FACT_PROBE_TOPICS if fact_probe_topics is None
            else max(0, fact_probe_topics)
        )
        seed_set = set(topics)
        extra_probe_topics = _next_uncached_topics(
            [cand.topic for cand in velocity_ranked if cand.topic not in seed_set],
            limit=extra_probe_limit,
            refresh_low_source_counts=refresh_low_source_counts,
        )
        probe_topics = list(dict.fromkeys([
            *(topic for topic in topics if topic in papers_by_topic),
            *extra_probe_topics,
        ]))
        fact_sources_by_topic = _fetch_fact_source_counts(
            probe_topics, client=c, settings=settings,
            refresh_low_source_counts=refresh_low_source_counts,
            facets_by_topic={
                topic: _paper_title_facets(topic, papers, year_now)
                for topic, papers in papers_by_topic.items()
            },
        )
        candidates = [
            _score_topic(
                topic, papers, year_now, anchorage=anchorage,
                fact_source_count=fact_sources_by_topic.get(topic, 0),
            )
            for topic, papers in papers_by_topic.items()
        ]
    finally:
        if own_client:
            c.close()
    seed_set = set(topics)
    candidates.sort(
        key=lambda c: (
            c.fact_source_count >= _PUBLISHABLE_SOURCE_FLOOR,
            c.fact_source_count,
            c.topic in seed_set,
            c.velocity_score,
        ),
        reverse=True,
    )
    return tuple(candidates)
