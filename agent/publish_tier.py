"""Deterministic publish-tier gate for alpha memos.

The gate is structural: it reads the rendered alpha memo plus existing
run receipts and decides whether a memo is ready to publish, needs
agent repair, or should go back to curation. No topic-specific
rules live here.
"""
from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CFG_PATH = _ROOT / "topic_packs" / "publish_tier.toml"
_PUBLICATION_PATH = _ROOT / "topic_packs" / "publication.toml"
_BINDABLE = frozenset({"A_core", "B_context"})
_DIRECT = frozenset({"A_core"})
_COUNTER_MIN_CLAIM_FIT = 0.2
_BLOCKED_LABELS = frozenset({
    "curation_needed", "evidence_binding_failed", "no_signal", "discard",
})


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _cfg() -> dict[str, Any]:
    try:
        data = tomllib.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    publish = data.get("publish_tier") if isinstance(data, dict) else {}
    thresholds = data.get("thresholds") if isinstance(data, dict) else {}
    return {
        "tension_markers": tuple(
            str(x).lower() for x in (publish or {}).get("tension_markers", [])
        ),
        "counter_markers": tuple(
            str(x).lower() for x in (publish or {}).get("counter_markers", [])
        ),
        "generic_tokens": frozenset(
            str(x).lower() for x in (publish or {}).get("generic_tokens", [])
        ),
        "cluster_stopwords": frozenset(
            str(x).lower() for x in (publish or {}).get("cluster_stopwords", [])
        ),
        "ready_min_bound_receipts": int(
            (thresholds or {}).get("ready_min_bound_receipts", 3)
        ),
        "ready_min_a_core_receipts": int(
            (thresholds or {}).get("ready_min_a_core_receipts", 2)
        ),
        "ready_min_alpha_score": int(
            (thresholds or {}).get("ready_min_alpha_score", 70)
        ),
        "review_min_alpha_score": int(
            (thresholds or {}).get("review_min_alpha_score", 30)
        ),
        "source_concentration_share": float(
            (thresholds or {}).get("source_concentration_share", 0.60)
        ),
        "domain_overlap_min": float(
            (thresholds or {}).get("domain_overlap_min", 0.06)
        ),
        "context_min_available_sources": int(
            (thresholds or {}).get("context_min_available_sources", 3)
        ),
        "broad_d_bad_share": float(
            (thresholds or {}).get("broad_d_bad_share", 0.60)
        ),
        "broad_min_sources": int((thresholds or {}).get("broad_min_sources", 3)),
        "off_scope_markers": tuple(
            str(x).lower()
            for x in (data.get("feed_scope") or {}).get("off_scope_markers", [])
        ),
    }


def _publication_int(key: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    if not isinstance(alpha, dict):
        return default
    try:
        return int(alpha.get(key, default))
    except (TypeError, ValueError):
        return default


def _field(md: str, name: str) -> str:
    m = re.search(rf"^\*\*{re.escape(name)}:\*\* (.+)$", md, flags=re.M)
    return m.group(1).strip() if m else ""


def _section(md: str, heading: str) -> str:
    m = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        md,
        flags=re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def _lead_audit(run_dir: Path) -> dict[str, Any]:
    gate = _json(run_dir / "opportunities_gate.json", {})
    audits = gate.get("audits", []) if isinstance(gate, dict) else []
    valid = [a for a in audits if isinstance(a, dict)]
    if not valid:
        return {}
    rank = {"survives": 3, "needs_source_audit": 2, "rejected": 1}
    return max(
        valid,
        key=lambda a: (
            rank.get(str(a.get("status") or ""), 0),
            int(a.get("capped_opportunity") or 0),
        ),
    )


def _memo_receipt_ids(
    text: str,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
) -> list[str]:
    names = "|".join(re.escape(name) for name in section_names)
    sections = re.findall(
        rf"^## (?:{names}) receipts\n\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.M | re.S,
    )
    seen: set[str] = set()
    out: list[str] = []
    for fid in re.findall(r"`fact_id=([^`\s]+)`", "\n".join(sections)):
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def _facts_by_id(run_dir: Path) -> dict[str, dict[str, Any]]:
    data = _json(run_dir / "all_facts.json", [])
    if not isinstance(data, list):
        return {}
    return {
        str(f.get("fact_id") or ""): f
        for f in data if isinstance(f, dict)
    }


def _lane_map(run_dir: Path) -> dict[str, str]:
    data = _json(run_dir / "fact_lanes.json", {})
    rows = data.get("verdicts", []) if isinstance(data, dict) else []
    return {
        str(v.get("fact_id") or ""): str(v.get("lane") or "")
        for v in rows if isinstance(v, dict)
    }


def _tokens(text: str, topic: str, generic: frozenset[str]) -> set[str]:
    topic_tokens = set(re.findall(r"[a-z0-9]{3,}", topic.lower()))
    out = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    return {t for t in out if t not in generic and t not in topic_tokens}


def _claim_fit_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    left_roots = {t[:6] for t in left if len(t) >= 6}
    right_roots = {t[:6] for t in right if len(t) >= 6}
    exact = len(left & right) * 2
    rooted = len(left_roots & right_roots)
    return (exact + rooted) / max(1, len(left) + len(right))


def _claim_tokens(cited_ids: list[str], facts: dict[str, dict[str, Any]]) -> set[str]:
    return set().union(*(
        set(re.findall(r"[a-z0-9]{3,}", str(facts.get(fid, {}).get("canonical_phrase") or "").lower()))
        for fid in cited_ids
    )) if cited_ids else set()


def _source_papers(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    papers: list[dict[str, Any]] = []
    for fid in cited_ids:
        paper = facts.get(fid, {}).get("source_paper") or {}
        if not isinstance(paper, dict):
            continue
        key = str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
                  or paper.get("paper_id") or paper.get("id") or paper.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            papers.append(paper)
    return papers


def _source_key(fact: dict[str, Any]) -> str:
    # P5 hardening: identity order DOI > PMID > PMCID > paper_id > id > title.
    paper = fact.get("source_paper") or {}
    if not isinstance(paper, dict):
        return ""
    return str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
               or paper.get("paper_id") or paper.get("id") or paper.get("title") or "")


def _paper_summary(fact: dict[str, Any]) -> dict[str, Any]:
    paper = fact.get("source_paper") or {}
    return {
        "doi": str(paper.get("doi") or ""),
        "title": str(paper.get("title") or ""),
        "journal": str(paper.get("journal") or ""),
        "year": paper.get("year"),
    } if isinstance(paper, dict) else {
        "doi": "", "title": "", "journal": "", "year": None,
    }


def _fact_summary(
    fid: str,
    fact: dict[str, Any],
    lane: str,
) -> dict[str, Any]:
    return {
        "fact_id": fid,
        "lane": lane,
        "phrase": str(fact.get("canonical_phrase") or "")[:260],
        "sub_topic": str(fact.get("sub_topic") or ""),
        "population": str(fact.get("population") or "")[:160],
        "intervention": str(fact.get("intervention") or "")[:160],
        "source_paper": _paper_summary(fact),
    }


def _bound_ids_in_fact_order(
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
) -> list[str]:
    return [fid for fid in facts if lanes.get(fid) in _BINDABLE]


def _counter_evidence(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    markers: tuple[str, ...],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    claim = _claim_tokens(cited_ids, facts)
    for fid in _bound_ids_in_fact_order(facts, lanes):
        fact = facts.get(fid) or {}
        # Counter markers must live in the asserted finding itself. Comparator
        # text often says "without X" for ordinary controls; treating that as
        # opposition creates false counter-evidence.
        haystack = str(fact.get("canonical_phrase") or "").lower()
        if markers and not any(marker in haystack for marker in markers):
            continue
        rank = _claim_fit_score(
            set(re.findall(r"[a-z0-9]{3,}", str(fact.get("canonical_phrase") or "").lower())),
            claim,
        )
        if rank < _COUNTER_MIN_CLAIM_FIT:
            continue
        item = _fact_summary(fid, fact, lanes.get(fid, ""))
        item["_rank"] = rank
        out.append(item)
    out.sort(key=lambda item: (item["lane"] != "A_core", -float(item["_rank"]), item["fact_id"]))
    for item in out:
        item.pop("_rank", None)
    return out[:3]


def _expansion_candidates(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    cited = set(cited_ids)
    out: list[dict[str, Any]] = []
    claim = _claim_tokens(cited_ids, facts)
    cited_sources = {
        _source_key(facts[fid]) for fid in cited if fid in facts
    }
    for fid in _bound_ids_in_fact_order(facts, lanes):
        if fid in cited:
            continue
        fact = facts.get(fid) or {}
        item = _fact_summary(fid, fact, lanes.get(fid, ""))
        item["same_source_as_lead"] = _source_key(fact) in cited_sources
        item["_rank"] = _claim_fit_score(
            set(re.findall(r"[a-z0-9]{3,}", str(fact.get("canonical_phrase") or "").lower())),
            claim,
        )
        out.append(item)
    out.sort(key=lambda item: (
        item["same_source_as_lead"],
        item["lane"] != "A_core",
        -float(item["_rank"]),
        item["fact_id"],
    ))
    for item in out:
        item.pop("_rank", None)
    return out[:limit]


def _cluster_label(
    facts: list[dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    stopwords: frozenset[str],
) -> str:
    counts: Counter[str] = Counter()
    for fact in facts:
        paper = fact.get("source_paper") or {}
        text = " ".join([
            str(fact.get("sub_topic") or ""),
            str(fact.get("population") or ""),
            str(fact.get("intervention") or ""),
            str(fact.get("comparator") or ""),
            str(fact.get("canonical_phrase") or ""),
            str(paper.get("title") or "") if isinstance(paper, dict) else "",
            str(paper.get("journal") or "") if isinstance(paper, dict) else "",
        ])
        for token in _tokens(text, topic, generic | stopwords):
            counts[token] += 1
    return "_".join(token for token, _ in counts.most_common(3)) or "unlabeled"


def _source_diverse_fact_clusters(
    facts: list[dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    stopwords: frozenset[str],
    *,
    min_overlap: float,
    source_min: int,
) -> list[list[dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], str, set[str]]] = []
    for fact in facts:
        source = _source_key(fact)
        tokens = _tokens(" ".join([
            str(fact.get("sub_topic") or ""),
            str(fact.get("population") or ""),
            str(fact.get("intervention") or ""),
            str(fact.get("canonical_phrase") or ""),
        ]), topic, generic | stopwords)
        if source and tokens:
            rows.append((fact, source, tokens))
    clusters: list[list[dict[str, Any]]] = []
    seen: set[tuple[str, ...]] = set()
    for seed, seed_source, seed_tokens in rows:
        sources = {seed_source}
        cluster = [seed]
        for fact, source, tokens in rows:
            if source in sources:
                continue
            if len(seed_tokens & tokens) / max(1, len(seed_tokens | tokens)) >= min_overlap:
                cluster.append(fact)
                sources.add(source)
        if len(sources) < source_min:
            continue
        sig = tuple(sorted(str(it.get("_fact_id") or "") for it in cluster))
        if sig not in seen:
            seen.add(sig)
            clusters.append(cluster)
    return sorted(
        clusters,
        key=lambda items: (
            -len({_source_key(it) for it in items}),
            -len(items),
            str(items[0].get("_fact_id") or ""),
        ),
    )


def _subtopic_recommendations(
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    topic: str,
    generic: frozenset[str],
    stopwords: frozenset[str],
    *,
    d_bad_share_min: float,
    min_overlap: float,
    source_min: int,
    enabled: bool,
) -> dict[str, Any]:
    total = max(1, len(lanes))
    d_bad = sum(1 for lane in lanes.values() if lane == "D_bad_extraction")
    by_source: dict[str, list[dict[str, Any]]] = {}
    a_core: list[dict[str, Any]] = []
    for fid, fact in facts.items():
        item = fact | {"_fact_id": fid}
        key = _source_key(fact)
        if key:
            by_source.setdefault(key, []).append(item)
        if lanes.get(fid) == "A_core":
            a_core.append(item)
    noisy_recommend = (
        enabled and d_bad / total >= d_bad_share_min
        and len(by_source) >= source_min
    )
    coherent_clusters = _source_diverse_fact_clusters(
        a_core, topic, generic, stopwords,
        min_overlap=min_overlap, source_min=source_min,
    )
    recommend = noisy_recommend or (enabled and bool(coherent_clusters))
    clusters: list[dict[str, Any]] = []
    if noisy_recommend:
        cluster_items = sorted(by_source.values(), key=len, reverse=True)
    else:
        cluster_items = sorted(coherent_clusters, key=len, reverse=True)
    if recommend:
        for items in cluster_items[:5]:
            first = items[0]
            clusters.append({
                "label": _cluster_label(items, topic, generic, stopwords),
                "member_fact_ids": [str(it.get("_fact_id") or "") for it in items[:8]],
                "source_paper": _paper_summary(first),
                "example_phrase": str(first.get("canonical_phrase") or "")[:220],
            })
    return {
        "recommended": recommend,
        "reason": (
            "high_d_bad_share_plus_semantic_dispersion" if noisy_recommend
            else "source_coherent_child_cluster" if recommend
            else "not_broad_or_not_noisy_enough"
        ),
        "d_bad_share": round(d_bad / total, 3),
        "source_count": len(by_source),
        "clusters": clusters,
    }


def _domain_forced(
    papers: list[dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    min_overlap: float,
) -> bool:
    if len(papers) < 2:
        return False
    token_sets = [
        _tokens(
            f"{p.get('title') or ''} {p.get('journal') or ''}",
            topic,
            generic,
        )
        for p in papers
    ]
    for i, left in enumerate(token_sets):
        for right in token_sets[i + 1:]:
            if not left or not right:
                continue
            overlap = len(left & right) / max(1, len(left | right))
            if overlap >= min_overlap:
                return False
    return True


def _source_concentrated(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    threshold: float,
) -> bool:
    dois = []
    for fid in cited_ids:
        paper = facts.get(fid, {}).get("source_paper") or {}
        doi = str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
                  or paper.get("paper_id") or paper.get("id") or paper.get("title") or "")
        if doi:
            dois.append(doi)
    if not dois:
        return False
    counts = Counter(dois)
    return max(counts.values()) / len(dois) >= threshold or len(counts) <= 2


def _claim_coherent_source_diversity(
    cited_ids: list[str],
    facts: dict[str, dict[str, Any]],
    topic: str,
    generic: frozenset[str],
    min_overlap: float,
    min_sources: int,
) -> bool:
    by_source: dict[str, set[str]] = {}
    for fid in cited_ids:
        fact = facts.get(fid) or {}
        source = _source_key(fact)
        if not source:
            continue
        tokens = _tokens(" ".join([
            str(fact.get("canonical_phrase") or ""),
            str(fact.get("population") or ""),
            str(fact.get("intervention") or ""),
        ]), topic, generic)
        if tokens:
            by_source.setdefault(source, set()).update(tokens)
    source_tokens = list(by_source.values())
    if len(source_tokens) < min_sources:
        return False
    for i, left in enumerate(source_tokens):
        cluster_size = 1
        for j, right in enumerate(source_tokens):
            if i == j:
                continue
            overlap = len(left & right) / max(1, len(left | right))
            if overlap >= min_overlap:
                cluster_size += 1
        if cluster_size >= min_sources:
            return True
    return False


def _has_tension(md: str, markers: tuple[str, ...]) -> bool:
    text = (
        _field(md, "Headline") + "\n" + _section(md, "Why this is surprising")
    ).lower()
    return "real tension:" in text or any(marker in text for marker in markers)


def _marker_in_text(marker: str, text: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(marker).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _off_scope(
    papers: list[dict[str, Any]], topic: str, markers: tuple[str, ...],
) -> bool:
    if not markers:
        return False
    topic_text = topic.replace("_", " ").replace("-", " ").lower()
    text = "\n".join(
        f"{p.get('title') or ''} {p.get('journal') or ''}".lower()
        for p in papers
    )
    return any(
        not _marker_in_text(marker, topic_text) and _marker_in_text(marker, text)
        for marker in markers
    )


def publish_verdict(run_dir: Path) -> dict[str, Any]:
    md = _read(run_dir / "alpha_memo.md")
    cfg = _cfg()
    topic = run_dir.name.split("-evidence-", 1)[0]
    label = _field(md, "Confidence").strip("`") or "unknown"
    score_raw = _field(md, "Alpha score").split("/", 1)[0]
    try:
        alpha_score = int(score_raw)
    except ValueError:
        alpha_score = 0
    audit = _lead_audit(run_dir)
    cited_ids = _memo_receipt_ids(md) or [
        str(x) for x in audit.get("cited_fact_ids", [])
    ]
    evidence_ids = _memo_receipt_ids(md, ("Evidence",))
    facts = _facts_by_id(run_dir)
    lanes = _lane_map(run_dir)
    bound_ids = [fid for fid in cited_ids if lanes.get(fid) in _BINDABLE]
    direct_ids = [fid for fid in evidence_ids if lanes.get(fid) in _DIRECT]
    a_core = sum(1 for fid in bound_ids if lanes.get(fid) == "A_core")
    papers = _source_papers(bound_ids, facts)
    direct_papers = _source_papers(direct_ids, facts)
    min_source_papers = _publication_int("min_source_papers", 5)
    min_direct_source_papers = _publication_int("min_direct_source_papers", 5)
    all_bound_ids = _bound_ids_in_fact_order(facts, lanes)
    available_source_count = len({
        _source_key(facts[fid]) for fid in all_bound_ids if fid in facts
    } - {""})
    source_concentrated = _source_concentrated(
        bound_ids, facts, float(cfg["source_concentration_share"]),
    )
    source_coherent = source_concentrated or _claim_coherent_source_diversity(
        bound_ids, facts, topic, cfg["generic_tokens"] | cfg["cluster_stopwords"],
        float(cfg["domain_overlap_min"]), min_source_papers,
    )
    forced = _domain_forced(
        papers, topic, cfg["generic_tokens"], float(cfg["domain_overlap_min"]),
    )
    off_scope = _off_scope(papers, topic, cfg["off_scope_markers"])
    counter_evidence = _counter_evidence(
        bound_ids, facts, lanes, cfg["counter_markers"],
    )
    tension = _has_tension(md, cfg["tension_markers"]) or bool(counter_evidence)
    expansion_candidates = _expansion_candidates(bound_ids, facts, lanes)
    blockers: list[str] = []
    if label in _BLOCKED_LABELS:
        blockers.append(f"blocked_label:{label}")
    if not bound_ids:
        blockers.append("no_bound_receipts")
    if forced:
        blockers.append("cross_domain_forced")
    if not source_coherent and bound_ids and len(papers) >= min_source_papers:
        blockers.append("source_dispersion")
    if not tension and bound_ids:
        blockers.append("weak_counter_consensus_tension")
    if bound_ids and alpha_score < int(cfg["review_min_alpha_score"]):
        blockers.append("low_alpha_score")
    if off_scope:
        blockers.append("feed_scope_mismatch")
    if len(papers) < min_source_papers:
        blockers.append("source_floor_below_min")
    if len(direct_papers) < min_direct_source_papers:
        blockers.append("direct_source_floor_below_min")

    ready = (
        not blockers
        and label not in _BLOCKED_LABELS
        and len(bound_ids) >= int(cfg["ready_min_bound_receipts"])
        and a_core >= int(cfg["ready_min_a_core_receipts"])
        and alpha_score >= int(cfg["ready_min_alpha_score"])
    )
    if ready:
        tier, level = "TIER_1", "L5"
        decision = "ready_to_publish"
    elif (not bound_ids or label in _BLOCKED_LABELS or off_scope
          or alpha_score < int(cfg["review_min_alpha_score"])):
        tier, level = "TIER_3", "L2"
        decision = "curation_needed"
    else:
        tier, level = "TIER_2", "L4"
        decision = "agent_repair_needed"
    expansion_needed = (
        len(bound_ids) < int(cfg["ready_min_bound_receipts"])
        and len(all_bound_ids) > len(bound_ids)
    )
    context_dependence = (
        decision == "agent_repair_needed"
        and expansion_needed
        and tension
        and not forced
        and not off_scope
        and available_source_count >= int(cfg["context_min_available_sources"])
    )
    subtopics = _subtopic_recommendations(
        facts, lanes, topic, cfg["generic_tokens"], cfg["cluster_stopwords"],
        d_bad_share_min=float(cfg["broad_d_bad_share"]),
        min_overlap=float(cfg["domain_overlap_min"]),
        source_min=int(cfg["broad_min_sources"]),
        enabled=decision != "ready_to_publish",
    )
    if decision == "ready_to_publish":
        surface_type = "publish_alpha_memo"
    elif context_dependence:
        surface_type = "context_dependence_memo"
    elif off_scope or forced:
        surface_type = "split_or_reject_memo"
    elif subtopics["recommended"]:
        surface_type = "subtopic_rerun_memo"
    elif decision == "curation_needed":
        surface_type = "curation_brief"
    else:
        surface_type = "frontier_hypothesis_memo"
    try:
        run_ref = str(run_dir.resolve().relative_to(_ROOT))
    except ValueError:
        run_ref = str(run_dir)
    return {
        "run_dir": run_ref,
        "topic": topic,
        "decision": decision,
        "publish_tier": tier,
        "maturity_level": level,
        "headline": _field(md, "Headline"),
        "confidence_label": label,
        "alpha_score": alpha_score,
        "surface_type": surface_type,
        "axes": {
            "bound_receipts": len(bound_ids),
            "direct_source_papers": len(direct_papers),
            "available_bound_receipts": len(all_bound_ids),
            "available_source_contexts": available_source_count,
            "a_core_receipts": a_core,
            "source_concentrated": source_concentrated,
            "claim_coherent_source_diversity": source_coherent,
            "counter_consensus_tension": tension,
            "cross_domain_forced": forced,
            "feed_scope_mismatch": off_scope,
            "source_papers": [
                {
                    "doi": str(p.get("doi") or ""),
                    "title": str(p.get("title") or ""),
                    "journal": str(p.get("journal") or ""),
                    "year": p.get("year"),
                }
                for p in papers
            ],
        },
        "receipt_expansion": {
            "needed": expansion_needed,
            "why": (
                "lead_thesis_underuses_available_bound_receipts"
                if expansion_needed else "lead_thesis_uses_available_receipts"
            ),
            "cited_bound_fact_ids": bound_ids,
            "available_bound_fact_ids": all_bound_ids,
            "candidate_receipts": expansion_candidates,
        },
        "counter_evidence": {
            "status": "found" if counter_evidence else "none_found",
            "items": counter_evidence,
        },
        "subtopic_recommendations": subtopics,
        "blockers": blockers,
    }


def write_publish_verdict(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    verdict = publish_verdict(run_dir)
    path = run_dir / "publish_verdict.json"
    path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    return path, verdict
