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

from agent.frontier_review import FrontierReview, run_frontier_review
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
    by topic. Network/JSON errors return [] silently so a flaky DB
    blip never crashes the whole run."""
    settings = load_settings()
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    hdr = {"X-Researka-Token": token}
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.get(f"{base}/api/v1/topics/{topic}/facts", headers=hdr)
            r.raise_for_status()
            tier1 = r.json()
            if isinstance(tier1, list) and tier1:
                for f in tier1:
                    if isinstance(f, dict):
                        f["_tier"] = "tier1_canonical"
                return [f for f in tier1 if isinstance(f, dict)]
            r2 = c.post(f"{base}/api/v1/tier2/facts/search", headers=hdr,
                        json={"query": topic, "top_k": 50,
                              "min_confidence": "medium", "numeric_only": True})
            r2.raise_for_status()
            items = r2.json() if isinstance(r2.json(), list) else []
    except (httpx.HTTPError, ValueError):
        return []
    # DB curators now bucket much of Tier-2 under topic='other'. Accept
    # exact topic match OR content-match (topic word appears in the
    # canonical_phrase / claim / paper title). Universal substring check.
    tw = topic.replace("_", " ").lower()
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        tag = str(it.get("topic") or "").lower()
        haystack = " ".join([
            str(it.get("canonical_phrase") or ""),
            str(it.get("claim_type") or ""),
            str((it.get("paper") or {}).get("title") or ""),
        ]).lower()
        if tag == topic.lower() or tw in haystack:
            out.append(_normalize_tier2(it, topic))
    return out


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


def _fetch_papers(topic: str, limit: int = 25) -> list[dict[str, Any]]:
    """Pull paper metadata for cross-context (citations, fwci, quality)."""
    settings = load_settings()
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token:
        return []
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(f"{base}/api/v1/papers/topic",
                       headers={"X-Researka-Token": token},
                       json={"topic": topic, "limit": limit})
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def _render_frontier_md(review: FrontierReview, topic: str) -> str:
    """Markdown view of the MiMo-driven research-strategist output."""
    if review.model.startswith("error:"):
        return (
            f"# Frontier review — {topic}\n\n"
            f"**Snapshot:** {review.snapshot_utc}\n\n"
            f"_No frontier review available ({review.model})._\n"
        )

    def _bullets(items: tuple[str, ...]) -> str:
        return "\n".join(f"- {x}" for x in items) if items else "_none_"

    theses_md = "_none_"
    if review.theses:
        blocks = []
        sorted_theses = sorted(review.theses,
                               key=lambda t: t.opportunity_score, reverse=True)
        for i, t in enumerate(sorted_theses, start=1):
            blocks.append(
                f"### #{i} — opportunity {t.opportunity_score} · "
                f"`{t.paper_type or 'unspecified'}`\n\n"
                f"**Thesis:** {t.title}\n\n"
                f"- novelty {t.novelty} / evidence_strength "
                f"{t.evidence_strength} / reviewer_risk {t.reviewer_risk}\n"
                f"- **Why publishable:** {t.rationale}\n"
            )
        theses_md = "\n---\n\n".join(blocks)

    return (
        f"# Frontier review — {topic}\n\n"
        f"**Snapshot:** {review.snapshot_utc}\n"
        f"**Strategist model:** {review.model}\n\n"
        f"## The lens\n\n{review.lens or '_no lens produced_'}\n\n"
        f"## Already known — do not publish\n\n"
        f"{_bullets(review.known_to_ignore)}\n\n"
        f"## Tensions / contradictions\n\n{_bullets(review.tensions)}\n\n"
        f"## Evidence gaps\n\n{_bullets(review.gaps)}\n\n"
        f"## Paper theses\n\n{theses_md}\n\n"
        f"## Reviewer objections to anticipate\n\n"
        f"{_bullets(review.reviewer_objections)}\n\n"
        f"## Suggested next extractions\n\n"
        f"{_bullets(review.next_extractions)}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--no-frontier", action="store_true",
                        help="Skip the MiMo frontier-review LLM call")
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

    files_manifest = {
        "top_md": {"name": md_path.name, "sha256": _sha256(md_text)},
        "all_facts": {"name": raw_path.name, "sha256": _sha256(raw_text)},
        "claims_index": {"name": claims_path.name, "sha256": _sha256(claims_text)},
    }

    review_model = "skipped"
    if not args.no_frontier and facts:
        papers = _fetch_papers(args.topic)
        review = run_frontier_review(
            topic=args.topic, snapshot_utc=ts, facts=facts,
            papers=papers or None, settings=load_settings(),
        )
        review_model = review.model
        fr_md_path = out_dir / "frontier_review.md"
        fr_md_text = _render_frontier_md(review, args.topic)
        fr_md_path.write_text(fr_md_text, encoding="utf-8")
        fr_json_path = out_dir / "frontier_review.json"
        fr_json_text = json.dumps(review.as_dict(), indent=2, ensure_ascii=False)
        fr_json_path.write_text(fr_json_text, encoding="utf-8")
        files_manifest["frontier_md"] = {
            "name": fr_md_path.name, "sha256": _sha256(fr_md_text),
        }
        files_manifest["frontier_json"] = {
            "name": fr_json_path.name, "sha256": _sha256(fr_json_text),
        }
        if papers:
            papers_path = out_dir / "papers_metadata.json"
            papers_text = json.dumps(papers, indent=2, ensure_ascii=False)
            papers_path.write_text(papers_text, encoding="utf-8")
            files_manifest["papers_metadata"] = {
                "name": papers_path.name, "sha256": _sha256(papers_text),
            }

    manifest = {
        "topic": args.topic, "snapshot_utc": ts, "top_n": args.top,
        "facts_inspected": len(facts), "aggregated_claims": len(aggregated),
        "data_tier": tier,
        "source": ("researka_db GET /api/v1/topics/{topic}/facts"
                   if tier == "tier1_canonical"
                   else "researka_db POST /api/v1/tier2/facts/search "
                   "(Tier-2 fallback; topic filter on response)"),
        "frontier_model": review_model,
        "ranking": "deterministic: validation*magnitude*precision*recency",
        "files": files_manifest,
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )

    print(f"[evidence-run] topic={args.topic} facts={len(facts)} "
          f"top={len(top)} frontier={review_model} → {out_dir}")
    for i, (score, f) in enumerate(top, start=1):
        phrase = str(f.get("canonical_phrase") or "")[:80]
        print(f"  #{i}  score={score:3}  {phrase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
