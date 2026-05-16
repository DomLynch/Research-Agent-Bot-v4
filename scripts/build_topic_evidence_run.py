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
    python scripts/build_topic_evidence_run.py --topic <topic> --top 5
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

from agent.alpha_selector import alpha_cues, alpha_score
from agent.fact_facets import (
    facet_counts,
    select_coherent_theme,
)
from agent.fact_lanes import LaneVerdict, classify_lanes
from agent.frontier_review import (
    FrontierReview,
    run_frontier_review,
)
from agent.frontier_review import (
    _parse as _frontier_parse,
)
from agent.llm_client import call_writer_with_fallback
from agent.numeric_sanitizer import filter_artifacts
from agent.pico_enrichment import enrich_facts_pico
from agent.researka_claims import _aggregate
from agent.settings import load_settings

_RUNS = Path(__file__).resolve().parent.parent / "runs"
_TOP_BINDABLE_LANES = frozenset({"A_core", "B_context"})


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
        mag = min(20, int(abs(nv) / 3))  # 60% -> +20, 9% -> +3
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
        # DB upgrade (2026-05-15) ships PICO on Tier-2; preserve if present.
        "population": str(item.get("population") or ""),
        "intervention": str(item.get("intervention") or ""),
        "comparator": str(item.get("comparator") or ""),
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
    # DB curators bucket much of Tier-2 under topic='other'. Accept
    # exact topic match OR content-match (topic word appears in the
    # canonical_phrase / claim / paper title). Universal substring
    # check.  Fallback: when class-name queries (e.g. "senolytic")
    # return semantic results that don't literally contain the word,
    # trust the semantic search — it already did the relevance work.
    tw = topic.replace("_", " ").lower()
    matched: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        all_items.append(it)
        tag = str(it.get("topic") or "").lower()
        haystack = " ".join([
            str(it.get("canonical_phrase") or ""),
            str(it.get("claim_type") or ""),
            str((it.get("paper") or {}).get("title") or ""),
        ]).lower()
        if tag == topic.lower() or tw in haystack:
            matched.append(it)
    chosen = matched if matched else all_items
    return [_normalize_tier2(it, topic) for it in chosen]


def _rankable_facts_for_top(
    facts: list[dict[str, Any]],
    topic: str,
    lane_verdicts: list[LaneVerdict] | None = None,
) -> list[dict[str, Any]]:
    """Facts allowed to appear as top_N cards.

    Top cards are operator-facing "interesting findings", so they must
    not include lane-rejected facts. Signal posts already fail closed via
    fact_lanes; this applies the same A_core/B_context discipline to the
    deterministic top_N renderer.
    """
    verdicts = lane_verdicts if lane_verdicts is not None else classify_lanes(
        facts, topic)
    lane_by_id = {v.fact_id: v.lane for v in verdicts}
    return [
        f for f in facts
        if lane_by_id.get(str(f.get("fact_id") or "")) in _TOP_BINDABLE_LANES
        and "context_fragment" not in alpha_cues(f)
    ]


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


def _dedup_by_paper_subtopic(
    scored: list[tuple[int, dict[str, Any]]],
) -> list[tuple[int, dict[str, Any]]]:
    """Collapse same-paper same-subtopic facts into one top-card.

    A single trial that reports FBS + 2HPP + fructosamine should not
    monopolise the Top 5. After scoring, group by (doi, sub_topic):
    keep the highest-scoring fact as headline; attach the rest as
    `_supporting_facts` (list of dicts with `value` + `units` +
    `canonical_phrase`). Order of headlines preserves the input
    ranking. Universal — keys come from fact structure, not domain.
    """
    seen: dict[tuple[str, str], int] = {}
    out: list[tuple[int, dict[str, Any]]] = []
    for score, f in scored:
        paper = f.get("source_paper") or {}
        doi = str(paper.get("doi") or "").lower().strip()
        sub = str(f.get("sub_topic") or "").lower().strip()
        # Fallback key when doi missing: paper title (still groups same-paper)
        key_a = doi or str(paper.get("title") or "").lower().strip()[:80]
        key = (key_a, sub)
        if not key_a:  # cannot bucket — treat as unique
            out.append((score, f))
            continue
        if key not in seen:
            seen[key] = len(out)
            f_copy = dict(f)
            f_copy["_supporting_facts"] = []
            out.append((score, f_copy))
        else:
            head_idx = seen[key]
            _, head = out[head_idx]
            supp = head.setdefault("_supporting_facts", [])
            if isinstance(supp, list):
                supp.append({
                    "value": f.get("numeric_value"),
                    "units": str(f.get("units") or ""),
                    "canonical_phrase": str(f.get("canonical_phrase") or ""),
                })
    return out


def _editorial_block(
    fact: dict[str, Any], sub_topic: str, supp_count: int,
    mimo_enrichment: dict[str, str] | None = None,
) -> str:
    """Deterministic 3-line editorial. MiMo enrichment (when provided)
    swaps in richer per-fact context for any of: why_it_matters,
    caution, next_question. Universal — sub_topic + structural counts
    only."""
    enrich = mimo_enrichment or {}
    why = enrich.get("why_it_matters") or (
        f"Direct evidence in the `{sub_topic}` sub-topic; "
        f"informs whether the finding generalises beyond a single study."
    )
    caution = enrich.get("caution") or (
        f"Single trial / single subgroup (k={1 + supp_count} biomarker"
        f"{'s' if supp_count else ''} from one paper); replication "
        "across independent cohorts required."
    )
    nxt = enrich.get("next_question") or (
        "What sub-populations, doses, or timepoints remain "
        "underexplored for this finding?"
    )
    return (
        f"- **Why it matters:** {why}\n"
        f"- **Caution:** {caution}\n"
        f"- **Next question:** {nxt}"
    )


def _call_mimo_editorial(
    topic: str, top: list[tuple[int, dict[str, Any]]],
) -> dict[int, dict[str, str]]:
    """Opt-in MiMo enrichment of editorial fields. One batched call
    returns {fact_idx: {why_it_matters, caution, next_question}}.
    Returns {} on any error so the deterministic block stands in.
    Universal — prompt asks only for context interpretation, no
    domain-specific reasoning is hardcoded."""
    settings = load_settings()
    if not settings.writer_configured or not top:
        return {}
    fact_block = "\n".join(
        f"[{i}] {str(f.get('canonical_phrase') or '')[:200]} "
        f"(sub_topic={f.get('sub_topic')}, "
        f"population={str(f.get('population') or '')[:80]})"
        for i, (_score, f) in enumerate(top)
    )
    msgs = [
        {"role": "system",
         "content": "You produce editorial context for research "
                    "findings. Reply with JSON only."},
        {"role": "user", "content":
            f"TOPIC: {topic}\nFINDINGS:\n{fact_block}\n\n"
            "For each finding, write three short sentences:\n"
            "  why_it_matters: 1 sentence on real-world significance\n"
            "  caution: 1 sentence on study-design limits (k=1, model, dose)\n"
            "  next_question: 1 sentence on the next unanswered question\n"
            "Be specific. Avoid generic prose. Respond as JSON: "
            '{"0": {"why_it_matters":..., "caution":..., "next_question":...}, '
            '"1": {...}, ...}'},
    ]
    try:
        resp = call_writer_with_fallback(
            settings, msgs, temperature=0.2, max_tokens=2000,
        )
    except (RuntimeError, OSError, httpx.HTTPError):
        return {}
    # Reuse the frontier-review tolerant JSON parser: strips ```json
    # code fences and repairs truncated-mid-stream MiMo output.
    loaded = _frontier_parse(resp.content)
    if not loaded:
        return {}
    out: dict[int, dict[str, str]] = {}
    for k, v in loaded.items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            out[idx] = {
                "why_it_matters": str(v.get("why_it_matters") or "")[:400],
                "caution": str(v.get("caution") or "")[:400],
                "next_question": str(v.get("next_question") or "")[:400],
            }
    return out


def _render_md(topic: str, ts: str, top: list[tuple[int, dict[str, Any]]],
               total_facts: int, tier: str,
               mimo_editorial: dict[int, dict[str, str]] | None = None,
               selected_theme: str | None = None,
               all_facet_counts: dict[str, int] | None = None) -> str:
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
    # Lane mode: if top spans 2+ distinct sub_topics, render labeled lanes.
    sub_topics = [str(f.get("sub_topic") or "").strip() or "—"
                  for _s, f in top]
    use_lanes = len({s for s in sub_topics if s != "—"}) >= 2
    ranking_note = (
        "**Ranking:** validation * magnitude * precision * recency "
        "(deterministic, no LLM), then one coherent broad theme is selected "
        "by aggregate score. Same-paper + same-sub_topic findings are "
        "collapsed; extra biomarkers from the same trial appear as "
        "supporting numerics under the headline.\n"
    )
    lines = [
        f"# Top {len(top)} interesting findings — {topic}",
        "",
        f"**Snapshot:** {ts}",
        f"**Source:** {source}",
        f"**Facts inspected:** {total_facts}",
        ranking_note,
    ]
    if selected_theme:
        counts = all_facet_counts or {}
        counts_txt = ", ".join(
            f"{k}={v}" for k, v in sorted(counts.items())
        ) or "unavailable"
        lines.append(
            f"**Selected theme:** `{selected_theme}` "
            f"(facet counts: {counts_txt})\n",
        )
    if use_lanes:
        lines.append(
            "**Sub-topic lanes detected:** facts grouped by `sub_topic` "
            "below — read each lane independently.\n",
        )
    lines.append("---")

    def _emit_card(
        rank: int, score: int, f: dict[str, Any], editorial_idx: int,
    ) -> list[str]:
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
        supp_raw = f.get("_supporting_facts")
        supp = supp_raw if isinstance(supp_raw, list) else []
        editorial = _editorial_block(
            f, sub_topic, len(supp),
            (mimo_editorial or {}).get(editorial_idx),
        )
        block: list[str] = [
            "",
            f"## #{rank} — score {score} · {sub_topic}",
            "",
            f"**Finding:** {f.get('canonical_phrase') or '(no canonical phrase)'}",
            "",
            f"- **Value:** {_fmt_value(f)}",
            f"- **Population:** {population}",
            f"- **Intervention:** {intervention}",
            f"- **Alpha cues:** {', '.join(alpha_cues(f)) or 'baseline'}",
            f"- **Source:** *{title}* — {journal} ({year})",
            f"  · DOI: `{doi}`" if doi else "",
            f"- **Validator:** {validator}"
            + (" · **SUPERSEDED**" if superseded else ""),
        ]
        if supp:
            block.append("- **Same-trial supporting numerics:** "
                          + "; ".join(
                              f"{s.get('value')}{s.get('units', '')} "
                              f"({str(s.get('canonical_phrase') or '')[:60]})"
                              for s in supp if isinstance(s, dict)))
        block += ["", editorial, "", "---"]
        return block

    if use_lanes:
        # Stable lane order = order of first appearance in `top`
        seen_lanes: list[str] = []
        for s in sub_topics:
            if s not in seen_lanes:
                seen_lanes.append(s)
        rank = 0
        for lane in seen_lanes:
            lane_label = lane if lane != "—" else "(no sub_topic)"
            lines.append(f"\n### Lane — `{lane_label}`\n")
            for original_idx, (sc, f) in enumerate(top):
                if (str(f.get("sub_topic") or "").strip() or "—") != lane:
                    continue
                rank += 1
                lines += _emit_card(rank, sc, f, original_idx)
    else:
        for i, (sc, f) in enumerate(top, start=1):
            lines += _emit_card(i, sc, f, i - 1)
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
    parser.add_argument("--with-editorial", action="store_true",
                        help="Enrich top-5 editorial fields (why_it_matters / "
                             "caution / next_question) via one MiMo call. "
                             "Default is deterministic templates.")
    parser.add_argument("--no-pico-enrich", action="store_true",
                        help="Skip the MiMo PICO-enrichment pass over Tier-2 "
                             "facts with empty population / intervention. "
                             "Default is to enrich; flag for debugging.")
    parser.add_argument("--mode", choices=("alpha", "paper"), default="alpha",
                        help="alpha (default): surprise-weighted Researka "
                             "signal posts, labels risk; paper: strict "
                             "evidence-gated journal mode.")
    args = parser.parse_args()
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = _RUNS / f"{args.topic}-evidence-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    facts = _fetch_facts(args.topic)
    pico_result = None
    if not args.no_pico_enrich and facts:
        facts, pico_result = enrich_facts_pico(facts, settings=load_settings())
    # Sprint 64: drop identifier-embed numerics (14,15-EET, Ser555,
    # ABT-263) before scoring so a parse artifact can never lead the
    # Top 5. Universal — syntactic shape only, no domain literals.
    facts, _artifact_facts = filter_artifacts(facts)
    rankable_facts = _rankable_facts_for_top(facts, args.topic)
    scored = sorted(((alpha_score(_interestingness(f), f), f) for f in rankable_facts),
                    key=lambda p: p[0], reverse=True)
    # Collapse same-paper + same-sub_topic duplicates so a single trial
    # can't monopolise the Top N (Sprint 60a).
    deduped = _dedup_by_paper_subtopic(scored)
    selected_theme, top = select_coherent_theme(deduped, args.top)
    all_facet_counts = facet_counts([f for _score, f in deduped])
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
    mimo_editorial = (_call_mimo_editorial(args.topic, top)
                      if args.with_editorial else {})
    md_path = out_dir / f"top_{args.top}.md"
    md_text = _render_md(args.topic, ts, top, len(facts), tier,
                         mimo_editorial=mimo_editorial,
                         selected_theme=selected_theme,
                         all_facet_counts=all_facet_counts)
    md_path.write_text(md_text, encoding="utf-8")

    files_manifest = {
        "top_md": {"name": md_path.name, "sha256": _sha256(md_text)},
        "all_facts": {"name": raw_path.name, "sha256": _sha256(raw_text)},
        "claims_index": {"name": claims_path.name, "sha256": _sha256(claims_text)},
    }

    review_model = "skipped"
    if not args.no_frontier and facts:
        papers = _fetch_papers(args.topic)
        # Sprint 75 — split facts by lane before handing to the
        # frontier reviewer. EVIDENCE (A_core/B_context) is citable;
        # ALPHA HINTS (C_noise/D_bad_extraction) are inspiration only.
        # Stops MiMo from picking provocative D_bad facts and forming
        # theses the binding gate must reject downstream.
        _bindable = {"A_core", "B_context"}
        lane_by_id: dict[str, str] = {
            v.fact_id: v.lane for v in classify_lanes(facts, args.topic)
        }
        evidence_facts, alpha_hints = [], []
        for f in facts:
            lane = lane_by_id.get(str(f.get("fact_id") or ""))
            if lane in _bindable:
                evidence_facts.append(f)
            elif lane is not None:
                alpha_hints.append(f)
        review = run_frontier_review(
            topic=args.topic, snapshot_utc=ts,
            evidence_facts=evidence_facts, alpha_hints=alpha_hints,
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
        "mode": args.mode,
        "selected_theme": selected_theme,
        "facet_counts": all_facet_counts,
        "numeric_artifacts_filtered": len(_artifact_facts),
        "pico_enrichment": (pico_result.as_dict() if pico_result
                            else {"model": "skipped_by_flag"}),
        "ranking": ("alpha: deterministic validation*magnitude*precision*recency "
                    "+ data-driven contrast/subgroup boosts + theme coherence"),
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
