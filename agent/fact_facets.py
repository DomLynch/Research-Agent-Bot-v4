"""Data-driven broad-theme grouping for operator-facing top cards."""
from __future__ import annotations

import tomllib
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

_FACETS_PATH = Path(__file__).resolve().parent.parent / "topic_packs" / "facets.toml"


def _text(fact: dict[str, Any]) -> str:
    paper = fact.get("source_paper") or {}
    parts = [
        fact.get("canonical_phrase"),
        fact.get("sub_topic"),
        fact.get("claim_type"),
        fact.get("population"),
        fact.get("intervention"),
        paper.get("title") if isinstance(paper, dict) else "",
    ]
    return " ".join(str(p or "") for p in parts).lower()


def _fallback_facet(config: tuple[dict[str, tuple[str, ...]], dict[str, int]]) -> str:
    markers_by_facet, priority_by_facet = config
    if not markers_by_facet:
        return "unclassified"
    return max(priority_by_facet, key=lambda facet: priority_by_facet[facet])


@lru_cache(maxsize=1)
def load_facet_config() -> tuple[dict[str, tuple[str, ...]], dict[str, int], dict[str, str]]:
    try:
        data = tomllib.loads(_FACETS_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}, {}, {}
    raw = data.get("facets")
    if not isinstance(raw, dict):
        return {}, {}, {}
    markers_by_facet: dict[str, tuple[str, ...]] = {}
    priority_by_facet: dict[str, int] = {}
    for priority, (key, value) in enumerate(raw.items()):
        if not isinstance(key, str) or not isinstance(value, list):
            continue
        markers = tuple(
            str(item).lower().strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )
        if markers:
            markers_by_facet[key] = markers
            priority_by_facet[key] = priority
    theme_by_facet = {facet: facet for facet in markers_by_facet}
    raw_themes = data.get("themes")
    if isinstance(raw_themes, dict):
        for theme, facets in raw_themes.items():
            if not isinstance(theme, str) or not isinstance(facets, list):
                continue
            for facet in facets:
                if isinstance(facet, str) and facet in markers_by_facet:
                    theme_by_facet[facet] = theme
    return markers_by_facet, priority_by_facet, theme_by_facet


def load_facet_markers() -> dict[str, tuple[str, ...]]:
    return load_facet_config()[0]


def classify_fact_theme(fact: dict[str, Any]) -> str:
    facet = classify_fact_facet(fact)
    _markers_by_facet, _priority_by_facet, theme_by_facet = load_facet_config()
    return theme_by_facet.get(facet, facet)


def classify_fact_facet(fact: dict[str, Any]) -> str:
    haystack = _text(fact)
    markers_by_facet, priority_by_facet, _theme_by_facet = load_facet_config()
    matches = {
        facet: sum(1 for marker in markers if marker in haystack)
        for facet, markers in markers_by_facet.items()
    }
    best_count = max(matches.values(), default=0)
    if best_count <= 0:
        return _fallback_facet((markers_by_facet, priority_by_facet))
    winners = [facet for facet, count in matches.items() if count == best_count]
    return min(winners, key=lambda facet: priority_by_facet[facet])


def facet_counts(facts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fact in facts:
        facet = classify_fact_facet(fact)
        counts[facet] = counts.get(facet, 0) + 1
    return counts


def select_coherent_theme(
    scored: list[tuple[int, dict[str, Any]]],
    top_n: int,
) -> tuple[str | None, list[tuple[int, dict[str, Any]]]]:
    """Choose one coherent broad theme for top-card rendering.

    Selection uses aggregate score within each facet, not a per-topic
    denylist. A singleton high-scoring fact from one surface will not displace
    a larger cluster from another surface, but if the singleton is genuinely
    the strongest available theme it can still win.
    """
    if not scored:
        return None, []
    buckets: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    _markers_by_facet, priority_by_facet, theme_by_facet = load_facet_config()
    for score, fact in scored:
        buckets[classify_fact_theme(fact)].append((score, fact))

    def _key(item: tuple[str, list[tuple[int, dict[str, Any]]]]) -> tuple[int, int, int]:
        theme, facts = item
        top_slice = facts[:top_n]
        total = sum(score for score, _fact in top_slice)
        peak = top_slice[0][0] if top_slice else 0
        theme_priority = min(
            priority_by_facet.get(facet, 999)
            for facet, mapped in theme_by_facet.items()
            if mapped == theme
        )
        return total, peak, -theme_priority

    theme, facts = max(buckets.items(), key=_key)
    return theme, facts[:top_n]
