"""Sprint 47 — operator-facing topic-evidence run.

Pulls canonical facts for a topic from the live Researka DB, scores
each fact by an "interestingness" rubric (validation * magnitude *
precision * recency), picks the top-N, and writes a run folder
parallel to the existing `runs/<topic>-paper-<ts>/` convention:

    runs/<topic>-evidence-<ts>/
        top_n.md          — human-readable curated list
        all_facts.json    — raw DB facts (provenance)
        claims_index.json — aggregated claim view + scores
        MANIFEST.json     — run metadata + bundle integrity hashes

No LLM calls. Pure data → ranked view from canonical Researka curation.

Usage:
    python scripts/build_topic_evidence_run.py --topic rapamycin --top 5
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.researka_claims import _aggregate
from agent.settings import load_settings

_RUNS = Path(__file__).resolve().parent.parent / "runs"


def _safe_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _interestingness(fact: dict[str, Any]) -> int:
    """0..100 score: validation, numeric magnitude, CI, recency, k_aliases."""
    score = 0
    if fact.get("validator"):
        score += 30
    if not fact.get("superseded_by"):
        score += 10
    nv = _safe_float(fact.get("numeric_value"))
    if nv is not None:
        score += 10
        mag = min(20, int(abs(nv) / 3))  # 60% lifespan ext -> +20, 9% -> +3
        score += mag
    if fact.get("ci_lower") is not None and fact.get("ci_upper") is not None:
        score += 15
    yr = _safe_float(fact.get("canonical_year"))
    if yr is not None:
        if yr >= 2020:
            score += 10
        elif yr >= 2015:
            score += 5
    aliases = fact.get("aliases")
    if isinstance(aliases, list) and aliases:
        score += min(5, len(aliases))
    return min(100, score)


def _normalize_tier2(item: dict[str, Any], topic: str) -> dict[str, Any]:
    """Coerce a tier2/facts/search row into the Tier-1-shaped dict the
    renderer / scorer expects. Keeps the same interestingness signals
    (numeric_value, validation, recency) but flags `tier=tier2`."""
    paper = item.get("paper") or {}
    return {
        "fact_id": item.get("id"), "topic": topic,
        "sub_topic": item.get("claim_type") or "",
        "source_paper": {
            "pmid": paper.get("pmid"), "doi": paper.get("doi"),
            "pmcid": paper.get("pmcid"), "title": paper.get("title"),
            "journal": paper.get("journal_name"),
            "year": paper.get("publication_year"),
        },
        "claim_type": item.get("claim_type"),
        "numeric_value": item.get("numeric_value"),
        "units": item.get("units"), "ci_lower": None, "ci_upper": None,
        "population": "", "intervention": "", "comparator": "",
        "canonical_phrase": item.get("canonical_phrase") or (
            f"{item.get('claim_type','fact')}: "
            f"{item.get('numeric_value','')}{item.get('units','')} "
            f"({paper.get('title','')})".strip()
        ),
        "canonical_year": paper.get("publication_year"),
        "validator": ("researka-tier2"
                      if str(item.get("extraction_confidence") or "")
                      in {"canonical", "high"} else ""),
        "superseded_by": None,
        "_tier": "tier2",
    }


def _fetch_facts(topic: str) -> list[dict[str, Any]]:
    """Try Tier-1 canonical first; fall back to Tier-2 search filtered
    by topic so non-rapamycin topics still surface real DB evidence."""
    settings = load_settings()
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    hdr = {"X-Researka-Token": token}
    with httpx.Client(timeout=20.0) as c:
        r = c.get(f"{base}/api/v1/topics/{topic}/facts", headers=hdr)
        r.raise_for_status()
        tier1 = r.json()
        if isinstance(tier1, list) and tier1:
            for f in tier1:
                if isinstance(f, dict):
                    f["_tier"] = "tier1_canonical"
            return [f for f in tier1 if isinstance(f, dict)]
        # Tier-2 fallback: semantic search filtered to the topic.
        r2 = c.post(f"{base}/api/v1/tier2/facts/search", headers=hdr, json={
            "query": topic, "top_k": 50,
            "min_confidence": "medium", "numeric_only": True,
        })
        r2.raise_for_status()
        items = r2.json() if isinstance(r2.json(), list) else []
    return [_normalize_tier2(it, topic) for it in items
            if isinstance(it, dict) and str(it.get("topic") or "") == topic]


def _fmt_value(fact: dict[str, Any]) -> str:
    nv = fact.get("numeric_value")
    units = str(fact.get("units") or "").strip()
    if nv is None:
        return "—"
    ci_lo = fact.get("ci_lower")
    ci_hi = fact.get("ci_upper")
    if ci_lo is not None and ci_hi is not None:
        return f"{nv}{units} (95% CI {ci_lo}-{ci_hi})"
    return f"{nv}{units}"


def _render_md(topic: str, ts: str, top: list[tuple[int, dict[str, Any]]],
               total_facts: int, tier: str) -> str:
    if tier == "tier1_canonical":
        source = (f"Researka DB Tier-1 canonical "
                  f"(`GET /api/v1/topics/{topic}/facts`) — "
                  "hand-curated, validated.")
    else:
        source = (f"Researka DB Tier-2 search "
                  f"(`POST /api/v1/tier2/facts/search`, filter topic={topic}) "
                  "— LLM-extracted, no Tier-1 canonical facts loaded for "
                  "this topic yet; findings may be off-target (e.g. chemistry "
                  "papers using the molecule name) until canonical curation.")
    lines = [
        f"# Top {len(top)} interesting findings — {topic}",
        "",
        f"**Snapshot:** {ts}",
        f"**Source:** {source}",
        f"**Facts inspected:** {total_facts}",
        "**Ranking:** validation * magnitude * precision * recency "
        "(deterministic, no LLM).",
        "",
        "---",
    ]
    for i, (score, f) in enumerate(top, start=1):
        paper = f.get("source_paper") or {}
        doi = str(paper.get("doi") or "")
        title = str(paper.get("title") or "(no title)")
        journal = str(paper.get("journal") or "")
        year = paper.get("year") or f.get("canonical_year") or "?"
        validator = str(f.get("validator") or "—")
        superseded = bool(f.get("superseded_by"))
        population = str(f.get("population") or "—")
        intervention = str(f.get("intervention") or "—")
        sub_topic = str(f.get("sub_topic") or "—")
        lines += [
            "",
            f"## #{i} — score {score} · {sub_topic}",
            "",
            f"**Finding:** {f.get('canonical_phrase') or '(no canonical phrase)'}",
            "",
            f"- **Value:** {_fmt_value(f)}",
            f"- **Population:** {population}",
            f"- **Intervention:** {intervention}",
            f"- **Source:** *{title}* — {journal} ({year})",
            f"  · DOI: `{doi}`" if doi else "",
            f"- **Validator:** {validator}"
            + (" · **SUPERSEDED**" if superseded else ""),
            "",
            "---",
        ]
    return "\n".join(line for line in lines if line is not None) + "\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = _RUNS / f"{args.topic}-evidence-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    facts = _fetch_facts(args.topic)
    scored = sorted(((_interestingness(f), f) for f in facts),
                    key=lambda p: p[0], reverse=True)
    top = scored[: args.top]
    aggregated = _aggregate(facts)

    raw_path = out_dir / "all_facts.json"
    raw_text = json.dumps(facts, indent=2, ensure_ascii=False)
    raw_path.write_text(raw_text, encoding="utf-8")

    claims_path = out_dir / "claims_index.json"
    claims_text = json.dumps({
        "topic": args.topic, "snapshot_utc": ts,
        "claim_count": len(aggregated), "claims": aggregated,
    }, indent=2, ensure_ascii=False)
    claims_path.write_text(claims_text, encoding="utf-8")

    tier = str((facts[0].get("_tier") if facts else "") or "none")
    md_path = out_dir / f"top_{args.top}.md"
    md_text = _render_md(args.topic, ts, top, len(facts), tier)
    md_path.write_text(md_text, encoding="utf-8")

    manifest = {
        "topic": args.topic, "snapshot_utc": ts, "top_n": args.top,
        "facts_inspected": len(facts), "aggregated_claims": len(aggregated),
        "data_tier": tier,
        "source": ("researka_db GET /api/v1/topics/{topic}/facts"
                   if tier == "tier1_canonical"
                   else "researka_db POST /api/v1/tier2/facts/search "
                   "(Tier-2 fallback; topic filter on response)"),
        "files": {
            "top_md": {"name": md_path.name, "sha256": _sha256(md_text)},
            "all_facts": {"name": raw_path.name, "sha256": _sha256(raw_text)},
            "claims_index": {"name": claims_path.name, "sha256": _sha256(claims_text)},
        },
        "ranking": "deterministic: validation*magnitude*precision*recency",
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )

    print(f"[evidence-run] topic={args.topic} facts={len(facts)} "
          f"top={len(top)} → {out_dir}")
    for i, (score, f) in enumerate(top, start=1):
        phrase = str(f.get("canonical_phrase") or "")[:80]
        print(f"  #{i}  score={score:3}  {phrase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
