"""Sprint 62 — Class -> instance synonym resolver.

Class queries (senolytic, mtor_inhibitor) match facts about specific
compound instances (dasatinib, rapamycin). Data lives in
topic_packs/topic_synonyms.toml — operator extends without code change.

Universal: TOML is data. Empty / missing key falls back to single-
keyword behavior (the topic word itself), preserving the pre-Sprint-62
contract for any topic not registered.
"""
from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from pathlib import Path

_TOML = (Path(__file__).resolve().parent.parent
         / "topic_packs" / "topic_synonyms.toml")
_NORM = re.compile(r"[\W_]+")


def _norm(s: str) -> str:
    """Lowercase + collapse non-word chars to single space."""
    return _NORM.sub(" ", s.lower()).strip()


@lru_cache(maxsize=1)
def load_synonyms(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Load class -> instances mapping. Cached. Returns {} on any error."""
    target = path or _TOML
    if not target.exists():
        return {}
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    if not isinstance(data, dict):
        return {}
    for class_name, body in data.items():
        if not isinstance(body, dict):
            continue
        instances = body.get("instances")
        if isinstance(instances, list):
            cleaned = tuple(str(s).strip() for s in instances
                            if str(s).strip())
            if cleaned:
                out[str(class_name).lower()] = cleaned
    return out


def expand_topic_keywords(topic: str) -> tuple[str, ...]:
    """Return all match strings for a topic. Always includes the topic
    word itself first; class registry instances follow if registered."""
    if not topic.strip():
        return ()
    key = _norm(topic).replace(" ", "_")
    instances = load_synonyms().get(key, ())
    # De-dupe while preserving order (topic first).
    seen: dict[str, None] = {topic: None}
    for inst in instances:
        seen.setdefault(inst, None)
    return tuple(seen)


def expand_topic_queries(topic: str, *, max_queries: int = 4) -> tuple[str, ...]:
    """Search queries for slug-style topics.

    Keeps the exact topic first, then adds normalized phrase forms and
    short prefixes so `omega_3_longevity` can still reach facts indexed
    under `omega 3`. Registry instances participate through
    expand_topic_keywords().
    """
    seen: dict[str, None] = {}
    for kw in expand_topic_keywords(topic):
        normed = _norm(kw)
        raw = kw.strip()
        if raw:
            seen.setdefault(raw, None)
        if normed and normed != raw.casefold():
            seen.setdefault(normed, None)
        parts = normed.split()
        while len(parts) > 2:
            parts = parts[:-1]
            seen.setdefault(" ".join(parts), None)
        if len(seen) >= max_queries:
            break
    return tuple(seen)[:max_queries]


def text_matches_topic(text: str, topic: str) -> bool:
    """Case-insensitive substring check across topic + all instances.
    Underscore-aware on the topic word (carbon_tax -> carbon tax)."""
    if not text or not topic.strip():
        return False
    haystack = _norm(text)
    return any(_norm(kw) in haystack
               for kw in expand_topic_keywords(topic))
