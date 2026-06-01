"""Class -> instance synonym resolver (data: topic_packs/topic_synonyms.toml).

Class queries (senolytic) match instance facts (dasatinib). Matching is
word-boundary, so a short synonym (EPA) never matches inside a word
(heparin). Missing key -> topic-word-only behaviour. Universal: TOML is data.
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


def phrase_in_text(needle: str, haystack: str) -> bool:
    """Word-boundary match (normalised inputs): `epa` must not hit `heparin`."""
    return bool(needle) and re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


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
    """Exact topic + normalized forms + registry instances. Prefix-trimming
    (so `omega_3_longevity` reaches `omega 3`) applies ONLY to the topic slug,
    never to instances: trimming `low level laser therapy` to the generic
    fragment `low level` false-matched unrelated `low-level ...` text.
    """
    key = _norm(topic).replace(" ", "_")
    registered = key in load_synonyms()
    seen: dict[str, None] = {}
    for idx, kw in enumerate(expand_topic_keywords(topic)):
        normed = _norm(kw)
        raw = kw.strip()
        if raw:
            seen.setdefault(raw, None)
        if normed and (
            normed != raw.casefold()
            or (" " in raw and raw != raw.casefold())
        ):
            seen.setdefault(normed, None)
        if idx == 0 and not registered:
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
    return any(phrase_in_text(_norm(kw), haystack)
               for kw in expand_topic_keywords(topic))
