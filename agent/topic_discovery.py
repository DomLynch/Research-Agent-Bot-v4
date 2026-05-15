"""Sprint 63 — Autonomous topic-discovery loop.

Closes the curator role: v4 stops needing hand-picked topics. For
each seed topic in topic_packs/discovery_seeds.toml the discovery
probes POST /api/v1/papers/topic, computes a per-paper velocity
score, aggregates per topic, and ranks. The top candidates feed the
operator queue that drives subsequent build_topic_evidence_run runs.

Velocity formula (universal, no domain literals):
    paper_score = fwci * log(1 + cited_by_count) * recency_weight
                  * (quality_score / 100)
    topic_score = mean(top-K paper_score for that topic)

recency_weight = max(0.2, 1 - (current_year - publication_year) / 10)

Tolerant: HTTP / JSON errors return empty list. Never raises.
"""
from __future__ import annotations

import datetime as dt
import math
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from agent.settings import Settings

_SEEDS_TOML = (Path(__file__).resolve().parent.parent
               / "topic_packs" / "discovery_seeds.toml")


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    topic: str
    paper_count: int
    top_paper_doi: str
    top_paper_title: str
    velocity_score: float
    mean_fwci: float
    mean_cited_by: float

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "paper_count": self.paper_count,
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


def _score_topic(
    topic: str, papers: list[dict[str, Any]], current_year: int,
    *, top_k: int = 5,
) -> TopicCandidate:
    """Aggregate per-paper scores; pick the strongest paper as anchor."""
    if not papers:
        return TopicCandidate(
            topic=topic, paper_count=0, top_paper_doi="",
            top_paper_title="", velocity_score=0.0,
            mean_fwci=0.0, mean_cited_by=0.0,
        )
    scored = sorted(
        ((_paper_score(p, current_year), p) for p in papers),
        key=lambda pair: pair[0], reverse=True,
    )
    top = scored[:top_k]
    velocity = sum(s for s, _ in top) / max(1, len(top))
    top_paper = top[0][1] if top else {}
    fwci_vals = [float(p.get("fwci") or 0.0) for p in papers]
    cited_vals = [float(p.get("cited_by_count") or 0.0) for p in papers]
    return TopicCandidate(
        topic=topic, paper_count=len(papers),
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


def discover_topics(
    seeds: tuple[str, ...] | None = None, *,
    settings: Settings, client: httpx.Client | None = None,
    current_year: int | None = None,
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
        candidates: list[TopicCandidate] = []
        for topic in topics:
            papers = _fetch_topic_papers(topic, client=c, settings=settings)
            candidates.append(_score_topic(topic, papers, year_now))
    finally:
        if own_client:
            c.close()
    candidates.sort(key=lambda c: c.velocity_score, reverse=True)
    return tuple(candidates)
