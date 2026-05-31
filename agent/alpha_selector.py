"""Data-driven alpha scoring boosts for operator-facing fact ranking."""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "topic_packs" / "alpha_selection.toml"
)


def _text(fact: dict[str, Any]) -> str:
    paper = fact.get("source_paper") or {}
    supporting = fact.get("_supporting_facts")
    support_text = ""
    if isinstance(supporting, list):
        support_text = " ".join(
            str(item.get("canonical_phrase") or "")
            for item in supporting
            if isinstance(item, dict)
        )
    parts = [
        fact.get("canonical_phrase"),
        fact.get("population"),
        fact.get("intervention"),
        paper.get("title") if isinstance(paper, dict) else "",
        support_text,
    ]
    return " ".join(str(p or "") for p in parts).lower()


def _context_poor_numeric_phrase(fact: dict[str, Any]) -> bool:
    phrase = str(fact.get("canonical_phrase") or "").strip()
    if not phrase:
        return True
    starts_numeric = bool(phrase[:1].isdigit() or phrase[:1] in ".-")
    words = [
        token for token in phrase.replace("-", " ").split()
        if any(ch.isalpha() for ch in token)
    ]
    return starts_numeric and len(words) < 8


@lru_cache(maxsize=1)
def load_alpha_boosts() -> dict[str, tuple[int, tuple[str, ...]]]:
    try:
        data = tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    raw = data.get("boosts")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[int, tuple[str, ...]]] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str) or not isinstance(cfg, dict):
            continue
        weight = cfg.get("weight")
        markers = cfg.get("markers")
        if not isinstance(weight, int) or not isinstance(markers, list):
            continue
        cleaned = tuple(
            str(marker).lower().strip()
            for marker in markers
            if isinstance(marker, str) and marker.strip()
        )
        if cleaned:
            out[name] = (weight, cleaned)
    return out


def alpha_cues(fact: dict[str, Any]) -> tuple[str, ...]:
    haystack = _text(fact)
    cues = [
        name for name, (_weight, markers) in load_alpha_boosts().items()
        if any(marker in haystack for marker in markers)
    ]
    if _context_poor_numeric_phrase(fact):
        cues.append("context_fragment")
    return tuple(cues)


def alpha_score(base_score: int, fact: dict[str, Any]) -> int:
    boost = 0
    cues = set(alpha_cues(fact))
    for name, (weight, _markers) in load_alpha_boosts().items():
        if name in cues:
            boost += weight
    if "context_fragment" in cues:
        boost -= 45
    return max(0, min(100, base_score + boost))


def _intish(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _shape_source_count(verdict: dict[str, Any]) -> int:
    for key in ("source_count", "bound_source_count", "source_bundle_count"):
        count = _intish(verdict.get(key))
        if count:
            return count
    axes = verdict.get("axes")
    if isinstance(axes, dict):
        papers = axes.get("source_papers")
        if isinstance(papers, list):
            keys = {
                str(
                    (p or {}).get("doi") or (p or {}).get("pmid")
                    or (p or {}).get("pmcid") or (p or {}).get("paper_id")
                    or (p or {}).get("id") or (p or {}).get("title") or ""
                ).lower()
                for p in papers if isinstance(p, dict)
            }
            return len({k for k in keys if k})
        for key in ("source_count", "selected_count"):
            count = _intish(axes.get(key))
            if count:
                return count
    return 0


def accepted_shape_bonus(
    verdict: dict[str, Any],
    accepted_profiles: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> int:
    """Small deterministic bias toward shapes Researka has accepted before."""
    if not accepted_profiles:
        return 0
    candidate_sources = _shape_source_count(verdict)
    candidate_alpha = _intish(verdict.get("alpha_score"))
    best = 0
    for profile in accepted_profiles:
        score = 0
        profile_sources = _shape_source_count(profile)
        if candidate_sources and profile_sources:
            delta = abs(candidate_sources - profile_sources)
            if delta == 0:
                score += 4
            elif delta <= 2:
                score += 2
            elif candidate_sources >= profile_sources:
                score += 1
        profile_alpha = _intish(profile.get("alpha_score"))
        if candidate_alpha and profile_alpha:
            delta = abs(candidate_alpha - profile_alpha)
            if delta <= 10:
                score += 2
            elif delta <= 20:
                score += 1
        for key in ("publish_tier", "maturity_level", "surface_type", "confidence_label"):
            if verdict.get(key) and verdict.get(key) == profile.get(key):
                score += 1
        best = max(best, score)
    return min(best, 10)
