"""Memo quality scorecard — one legible multi-dimension score, composed (not
re-judged) from signals the pipeline already produces.

The publish path is gate-based (pass/fail per gate); there is no single
multi-dimension *quality* view of a finished memo. This module composes the
existing per-run artifacts into one scorecard:

  - **evidence_strength** — distinct A_core source papers bound
  - **coherence**         — claim-cluster conformance (how tightly facts agree)
  - **citation_integrity**— external citation-existence check (citation_verify)
  - **source_diversity**  — spread of distinct journals
  - **novelty**           — frontier research-strategist novelty score

Deterministic and universal — it reads JSON the run already wrote and applies
boring quality scaling; **no LLM, no network, no re-judging**. Each dimension is
``None`` when its source artifact is absent, so the scorecard degrades cleanly.
(Inspired by APE's multi-dimension rubric — the dimensions, not its tournament,
which doesn't fit a one-memo-per-topic pipeline.)
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path

# Quality scaling constants (not domain literals — they tune the 0..100 curve).
_STRONG_SOURCES = 8       # distinct A_core sources that reads as "strong" evidence
_FULL_DIVERSITY_JOURNALS = 5  # distinct journals that reads as "well spread"
_FLOOR = 40               # a dimension below this is a quality-floor breach
_BANDS = ((80, "A"), (60, "B"), (40, "C"), (0, "D"))


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _load(run_dir: Path, name: str) -> object | None:
    try:
        data: object = json.loads((run_dir / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def _a_core_sources(facts: Sequence[object], lanes: Mapping[str, str]) -> int:
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        fid = str(fact.get("fact_id") or "")
        if lanes and lanes.get(fid) != "A_core":
            continue
        paper = fact.get("source_paper")
        if isinstance(paper, Mapping):
            key = str(paper.get("doi") or paper.get("pmid") or paper.get("title") or "")
            if key:
                seen.add(key)
    return len(seen)


def _lane_map(fact_lanes: object) -> dict[str, str]:
    if isinstance(fact_lanes, Mapping):
        verdicts = fact_lanes.get("verdicts")
        if isinstance(verdicts, list):
            return {
                str(v.get("fact_id")): str(v.get("lane"))
                for v in verdicts if isinstance(v, Mapping)
            }
    return {}


def _score_evidence(facts: Sequence[object], lanes: Mapping[str, str]) -> int | None:
    # Without lane data we cannot tell which facts are A_core, so the dimension
    # is not assessable — return None rather than counting every lane and
    # inflating the score.
    if not lanes:
        return None
    return _clamp(100 * _a_core_sources(facts, lanes) / _STRONG_SOURCES)


def _score_coherence(claim_cluster: object) -> int | None:
    if not isinstance(claim_cluster, Mapping):
        return None
    conf = claim_cluster.get("conformance_fraction")
    if isinstance(conf, (int, float)):
        return _clamp(100 * float(conf))
    return None


def _score_citation(citation_verify: object) -> int | None:
    if not isinstance(citation_verify, Mapping):
        return None
    counts = citation_verify.get("counts")
    if not isinstance(counts, Mapping):
        return None
    verified = int(counts.get("verified", 0) or 0)
    suspicious = int(counts.get("suspicious", 0) or 0)
    hallucinated = int(counts.get("hallucinated", 0) or 0)
    judged = verified + suspicious + hallucinated
    if judged == 0:
        return None  # all SKIPPED (APIs unreachable) — not assessable
    # Suspicious counts half; hallucinated is a hard penalty.
    return _clamp(100 * (verified + 0.5 * suspicious) / judged)


def _score_diversity(facts: Sequence[object]) -> int:
    journals: set[str] = set()
    for fact in facts:
        if isinstance(fact, Mapping):
            paper = fact.get("source_paper")
            if isinstance(paper, Mapping):
                j = str(paper.get("journal") or "").strip().lower()
                if j:
                    journals.add(j)
    return _clamp(100 * min(len(journals), _FULL_DIVERSITY_JOURNALS) / _FULL_DIVERSITY_JOURNALS)


def _score_novelty(frontier_review: object) -> int | None:
    if not isinstance(frontier_review, Mapping):
        return None
    theses = frontier_review.get("theses")
    if isinstance(theses, list):
        for thesis in theses:
            if isinstance(thesis, Mapping) and isinstance(thesis.get("novelty"), (int, float)):
                return _clamp(float(thesis["novelty"]))
    return None


def _band(overall: int) -> str:
    for floor, label in _BANDS:
        if overall >= floor:
            return label
    return "D"


def scorecard(run_dir: Path) -> dict[str, object]:
    """Compose a multi-dimension quality scorecard for a run. Never raises."""
    facts_raw = _load(run_dir, "all_facts.json")
    facts: Sequence[object] = facts_raw if isinstance(facts_raw, list) else []
    lanes = _lane_map(_load(run_dir, "fact_lanes.json"))

    dims: dict[str, int | None] = {
        "evidence_strength": _score_evidence(facts, lanes),
        "coherence": _score_coherence(_load(run_dir, "claim_cluster.json")),
        "citation_integrity": _score_citation(_load(run_dir, "citation_verify.json")),
        "source_diversity": _score_diversity(facts),
        "novelty": _score_novelty(_load(run_dir, "frontier_review.json")),
    }
    present = {k: v for k, v in dims.items() if v is not None}
    overall = _clamp(sum(present.values()) / len(present)) if present else 0
    breaches = sorted(k for k, v in present.items() if v < _FLOOR)
    report: dict[str, object] = {
        "dimensions": dims,
        "overall": overall,
        "band": _band(overall),
        "floor_breaches": breaches,
    }
    with suppress(OSError):
        (run_dir / "quality_scorecard.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8",
        )
    return report
