"""Online producer for the novelty gate — gathers I/O inputs, writes novelty.json.

Kept separate from ``agent/novelty_gate.py`` (which stays pure) so the scoring
core has no disk/network. Runs during the online evidence/signal build; the
publish gate later reads ``novelty.json`` offline via ``novelty_blockers``.

Graceful by contract: any read/network failure degrades to a conservative
report whose ``score`` does NOT block a real memo (corpus unreachable ->
``corpus_prior_art_count = None`` -> neutral scarcity), mirroring
``citation_verify``'s "never false-reject" stance.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from agent.citation_verify import verify_sources
from agent.novelty_gate import NoveltyConfig, compute_novelty
from agent.researka_facts import tier2_domain
from agent.settings import Settings

_AXIS_FIELDS = (
    "canonical_phrase", "population", "intervention", "comparator", "endpoint",
    "outcome", "sub_topic", "metric", "benchmark", "task", "dataset",
)
_GENERIC = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "study", "studies",
    "effect", "effects", "results", "result", "versus", "outcome", "outcomes",
})


def _read_json(path: Path, default: Any) -> Any:
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _shape(fact: dict[str, Any]) -> frozenset[str]:
    text = " ".join(str(fact.get(k) or "") for k in _AXIS_FIELDS).lower()
    return frozenset(t for t in re.findall(r"[a-z0-9]{3,}", text) if t not in _GENERIC)


def _year(fact: dict[str, Any]) -> int | None:
    paper = fact.get("source_paper")
    raw = (paper.get("year") if isinstance(paper, dict) else None) or fact.get("canonical_year")
    try:
        y = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return y if 1900 < y < 2100 else None


def _a_core_facts(run_dir: Path) -> list[dict[str, Any]]:
    facts = _read_json(run_dir / "all_facts.json", [])
    if not isinstance(facts, list):
        return []
    lanes_raw = _read_json(run_dir / "fact_lanes.json", {})
    rows = lanes_raw.get("verdicts", []) if isinstance(lanes_raw, dict) else []
    lane = {
        str(v.get("fact_id") or ""): str(v.get("lane") or "")
        for v in rows if isinstance(v, dict)
    }
    by_id = [f for f in facts if isinstance(f, dict)]
    core = [f for f in by_id if lane.get(str(f.get("fact_id") or "")) == "A_core"]
    return core or by_id  # fall back to all facts if lanes are absent


def _manifest_domain(run_dir: Path, lead: dict[str, Any]) -> str:
    manifest = _read_json(run_dir / "MANIFEST.json", {})
    if isinstance(manifest, dict):
        dom = str(manifest.get("domain") or "")
        if dom:
            return dom
    return str(lead.get("_domain") or "longevity")


def _corpus_prior_art_count(
    query: str, *, client: httpx.Client, settings: Settings, domain: str,
) -> int | None:
    """Distinct corpus source papers matching ``query`` — or None on any failure.

    Deliberately NOT ``researka_facts.tier2_source_count`` (which returns 0 on
    failure for the build-selection floor): the novelty gate must tell a genuine
    "no prior art" (0 -> novel) apart from a transient outage (None -> neutral
    scarcity), so a corpus error never reads as "maximally novel" and lets a
    non-novel claim false-pass in enforce mode.
    """
    base = settings.researka_database_url.rstrip("/")
    token = settings.researka_database_token.strip()
    if not base or not token:
        return None
    try:
        r = client.post(
            f"{base}/api/v1/tier2/facts/search",
            json={
                "domain": tier2_domain(domain), "query": query[:512], "top_k": 50,
                "min_confidence": "medium", "numeric_only": False,
            },
            headers={"X-Researka-Token": token, "Content-Type": "application/json"},
            timeout=20.0,
        )
        r.raise_for_status()
        data: Any = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    papers: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_paper = item.get("paper")
        paper = raw_paper if isinstance(raw_paper, dict) else {}
        key = str(paper.get("doi") or paper.get("pmid") or item.get("paper_id") or "")
        if key:
            papers.add(key)
    return len(papers)


def build_novelty_report(
    run_dir: Path,
    *,
    settings: Settings,
    now_year: int,
    cfg: NoveltyConfig,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Compute the novelty report for a run folder. Never raises."""
    core = _a_core_facts(run_dir)
    if not core:
        # No evidence to judge — neutral, non-blocking (avoid false rejects).
        return compute_novelty(
            corpus_prior_art_count=None, lead_shape=frozenset(), other_shapes=(),
            newest_source_year=None, now_year=now_year, citation_hallucinated=False,
            cfg=cfg,
        ).as_dict() | {"schema": "novelty-v1", "note": "no_a_core_facts"}

    lead, others = core[0], core[1:]
    lead_shape = _shape(lead)
    other_shapes = tuple(_shape(f) for f in others)
    years = [y for f in core if (y := _year(f)) is not None]
    newest = max(years) if years else None

    sources = [
        f["source_paper"] for f in core
        if isinstance(f.get("source_paper"), dict)
    ]

    # Corpus prior-art frequency. None when the corpus is not configured, so
    # scarcity stays neutral instead of falsely reading "0 == maximally novel".
    count: int | None = None
    if settings.researka_configured:
        query = str(lead.get("canonical_phrase") or lead.get("source_topic") or run_dir.name)
        domain = _manifest_domain(run_dir, lead)
        owns = client is None
        active = client or httpx.Client()
        try:
            count = _corpus_prior_art_count(query, client=active, settings=settings, domain=domain)
        finally:
            if owns:
                active.close()

    cite = verify_sources(sources) if sources else {"has_hallucinated": False, "checked": 0}

    report = compute_novelty(
        corpus_prior_art_count=count,
        lead_shape=lead_shape,
        other_shapes=other_shapes,
        newest_source_year=newest,
        now_year=now_year,
        citation_hallucinated=bool(cite.get("has_hallucinated")),
        cfg=cfg,
    )
    return report.as_dict() | {
        "schema": "novelty-v1",
        "lead_fact_id": str(lead.get("fact_id") or ""),
        "a_core_count": len(core),
        "citation_report": cite,
    }
