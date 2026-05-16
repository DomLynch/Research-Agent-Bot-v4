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


def alpha_score(base_score: int, fact: dict[str, Any]) -> int:
    haystack = _text(fact)
    boost = 0
    for weight, markers in load_alpha_boosts().values():
        if any(marker in haystack for marker in markers):
            boost += weight
    return min(100, base_score + boost)
