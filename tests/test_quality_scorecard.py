"""Tests for agent.quality_scorecard — deterministic, reads run artifacts only."""
from __future__ import annotations

import json
from pathlib import Path

from agent.quality_scorecard import scorecard


def _write(run: Path, name: str, payload: object) -> None:
    (run / name).write_text(json.dumps(payload), encoding="utf-8")


def _facts(n_sources: int, journals: int) -> list[dict[str, object]]:
    return [
        {
            "fact_id": str(i),
            "source_paper": {"doi": f"10.1/{i}", "journal": f"J{i % journals}"},
        }
        for i in range(n_sources)
    ]


def _lanes(fact_ids: list[str]) -> dict[str, object]:
    return {"verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in fact_ids]}


def test_full_scorecard_composes_all_dimensions(tmp_path: Path) -> None:
    facts = _facts(8, 5)
    _write(tmp_path, "all_facts.json", facts)
    _write(tmp_path, "fact_lanes.json", _lanes([str(i) for i in range(8)]))
    _write(tmp_path, "claim_cluster.json", {"conformance_fraction": 0.9})
    _write(tmp_path, "citation_verify.json", {"counts": {"verified": 8, "suspicious": 0, "hallucinated": 0}})
    _write(tmp_path, "frontier_review.json", {"theses": [{"novelty": 70}]})

    r = scorecard(tmp_path)
    dims = r["dimensions"]
    assert isinstance(dims, dict)
    assert dims["evidence_strength"] == 100  # 8 distinct A_core sources == _STRONG_SOURCES
    assert dims["coherence"] == 90
    assert dims["citation_integrity"] == 100
    assert dims["source_diversity"] == 100
    assert dims["novelty"] == 70
    assert r["band"] in ("A", "B")
    assert (tmp_path / "quality_scorecard.json").exists()


def test_hallucinated_citations_tank_integrity(tmp_path: Path) -> None:
    _write(tmp_path, "all_facts.json", _facts(4, 2))
    _write(tmp_path, "fact_lanes.json", _lanes([str(i) for i in range(4)]))
    _write(tmp_path, "citation_verify.json",
           {"counts": {"verified": 1, "suspicious": 1, "hallucinated": 2}})
    r = scorecard(tmp_path)
    dims = r["dimensions"]
    assert isinstance(dims, dict)
    # (1 + 0.5*1) / 4 = 37.5 -> 38, below the floor
    assert dims["citation_integrity"] == 38
    breaches = r["floor_breaches"]
    assert isinstance(breaches, list)
    assert "citation_integrity" in breaches


def test_missing_artifacts_degrade_to_none_not_crash(tmp_path: Path) -> None:
    # empty run dir — only the always-derivable dims should be present
    r = scorecard(tmp_path)
    dims = r["dimensions"]
    assert isinstance(dims, dict)
    assert dims["coherence"] is None
    assert dims["citation_integrity"] is None
    assert dims["novelty"] is None
    # no fact_lanes.json -> A_core membership is unknown -> not assessable (not 0)
    assert dims["evidence_strength"] is None
    assert isinstance(r["overall"], int)


def test_all_skipped_citations_is_not_assessable(tmp_path: Path) -> None:
    _write(tmp_path, "all_facts.json", _facts(3, 3))
    _write(tmp_path, "fact_lanes.json", _lanes(["0", "1", "2"]))
    _write(tmp_path, "citation_verify.json", {"counts": {"skipped": 3}})
    r = scorecard(tmp_path)
    dims = r["dimensions"]
    assert isinstance(dims, dict)
    assert dims["citation_integrity"] is None  # all SKIPPED -> not scored
