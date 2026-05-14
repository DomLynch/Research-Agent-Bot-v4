"""Sprint 46 — DB-backed claim feed for the v4 gap-analyser.

`GET /api/v1/topics/{topic}/facts` → aggregated gap-analyser claims.
Replaces writer-receipt-derived snapshots (bug-prone — see Sprints 14
/ 26 / 32 / 37) with canonical Researka-curated facts. Universal,
returns [] silently on any HTTP/JSON/config error.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.settings import Settings


def _score(items: list[dict[str, Any]], k_dois: int) -> int:
    has_ci = any(it.get("ci_lower") is not None
                 and it.get("ci_upper") is not None for it in items)
    validated = any(str(it.get("validator") or "") for it in items)
    superseded = any(it.get("superseded_by") for it in items)
    return min(100, 50 + (10 if k_dois >= 2 else 0) + (10 if has_ci else 0)
               + (10 if validated else 0) + (0 if superseded else 10))


def _aggregate(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_phrase: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        phrase = str(f.get("canonical_phrase") or "").strip()
        if phrase:
            by_phrase.setdefault(phrase, []).append(f)
    out: list[dict[str, Any]] = []
    for phrase, items in by_phrase.items():
        dois = sorted({str((it.get("source_paper") or {}).get("doi") or "")
                       for it in items} - {""})
        score = _score(items, len(dois))
        out.append({
            "claim_text": phrase, "confidence_0_100": score,
            "publication_opportunity": score >= 70 and len(dois) >= 2,
            "paper_type": str(items[0].get("claim_type") or ""),
            "supporting_study_ids": dois,
        })
    out.sort(key=lambda c: int(c.get("confidence_0_100") or 0), reverse=True)
    return out


def fetch_topic_claims(
    topic: str, *, client: httpx.Client, settings: Settings,
    sub_topic: str | None = None,
) -> list[dict[str, Any]]:
    """Pull canonical facts for `topic`; return gap-analyser claim dicts."""
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token or not topic.strip():
        return []
    params = {"sub_topic": sub_topic} if sub_topic else {}
    try:
        r = client.get(
            f"{base}/api/v1/topics/{topic}/facts",
            headers={"X-Researka-Token": token}, params=params, timeout=15.0,
        )
        r.raise_for_status()
        data: Any = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    facts = data if isinstance(data, list) else []
    return _aggregate([f for f in facts if isinstance(f, dict)])
