"""Deterministic publish-tier gate for alpha memos.

The gate is structural: it reads the rendered alpha memo plus existing
run receipts and decides whether a memo is ready to publish, needs
operator review, or should go back to curation. No topic-specific
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
_BINDABLE = frozenset({"A_core", "B_context"})
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
        "generic_tokens": frozenset(
            str(x).lower() for x in (publish or {}).get("generic_tokens", [])
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
        "off_scope_markers": tuple(
            str(x).lower()
            for x in (data.get("feed_scope") or {}).get("off_scope_markers", [])
        ),
    }


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
        key = str(paper.get("doi") or paper.get("pmid") or paper.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            papers.append(paper)
    return papers


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
        doi = str(paper.get("doi") or paper.get("pmid") or paper.get("title") or "")
        if doi:
            dois.append(doi)
    if not dois:
        return False
    counts = Counter(dois)
    return max(counts.values()) / len(dois) >= threshold or len(counts) <= 2


def _has_tension(md: str, markers: tuple[str, ...]) -> bool:
    text = (
        _field(md, "Headline") + "\n" + _section(md, "Why this is surprising")
    ).lower()
    return "real tension:" in text or any(marker in text for marker in markers)


def _off_scope(papers: list[dict[str, Any]], markers: tuple[str, ...]) -> bool:
    if not markers:
        return False
    text = "\n".join(
        f"{p.get('title') or ''} {p.get('journal') or ''}".lower()
        for p in papers
    )
    return any(marker in text for marker in markers)


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
    cited_ids = [str(x) for x in audit.get("cited_fact_ids", [])]
    facts = _facts_by_id(run_dir)
    lanes = _lane_map(run_dir)
    bound_ids = [fid for fid in cited_ids if lanes.get(fid) in _BINDABLE]
    a_core = sum(1 for fid in bound_ids if lanes.get(fid) == "A_core")
    papers = _source_papers(bound_ids, facts)
    source_concentrated = _source_concentrated(
        bound_ids, facts, float(cfg["source_concentration_share"]),
    )
    forced = _domain_forced(
        papers, topic, cfg["generic_tokens"], float(cfg["domain_overlap_min"]),
    )
    tension = _has_tension(md, cfg["tension_markers"])
    off_scope = _off_scope(papers, cfg["off_scope_markers"])
    blockers: list[str] = []
    if label in _BLOCKED_LABELS:
        blockers.append(f"blocked_label:{label}")
    if not bound_ids:
        blockers.append("no_bound_receipts")
    if forced:
        blockers.append("cross_domain_forced")
    if not source_concentrated and bound_ids:
        blockers.append("source_dispersion")
    if not tension and bound_ids:
        blockers.append("weak_counter_consensus_tension")
    if bound_ids and alpha_score < int(cfg["review_min_alpha_score"]):
        blockers.append("low_alpha_score")
    if off_scope:
        blockers.append("feed_scope_mismatch")

    ready = (
        not blockers
        and label == "evidence_backed_signal"
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
        decision = "needs_operator_review"
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
        "axes": {
            "bound_receipts": len(bound_ids),
            "a_core_receipts": a_core,
            "source_concentrated": source_concentrated,
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
        "blockers": blockers,
    }


def write_publish_verdict(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    verdict = publish_verdict(run_dir)
    path = run_dir / "publish_verdict.json"
    path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    return path, verdict
