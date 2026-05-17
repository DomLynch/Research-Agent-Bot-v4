"""Publish-tier gate tests.

Fixtures are non-biomedical. The gate should classify by structure:
binding, source concentration, tension, and cross-domain coherence.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.publish_tier import publish_verdict, write_publish_verdict


def _run(
    root: Path,
    *,
    label: str = "evidence_backed_signal",
    score: int = 80,
    lanes: tuple[str, ...] = ("A_core", "A_core", "A_core"),
    dois: tuple[str, ...] = ("10.same/a", "10.same/a", "10.same/a"),
    titles: tuple[str, ...] = (
        "Grid storage threshold improves reserve reliability",
        "Grid storage threshold improves reserve reliability",
        "Grid storage threshold improves reserve reliability",
    ),
    journals: tuple[str, ...] = ("Energy Systems", "Energy Systems", "Energy Systems"),
    tension: bool = True,
) -> Path:
    run = root / "grid_storage-evidence-ts"
    run.mkdir()
    ids = [str(i + 1) for i in range(len(lanes))]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - grid_storage\n\n"
        "**Headline:** Storage threshold paradox in reserve markets\n"
        f"**Alpha score:** {score}/100\n"
        f"**Confidence:** `{label}`\n\n"
        "## Why this is surprising\n\n"
        + ("Real tension: reserve reliability rises while costs fall.\n\n"
           if tension else "Expected result without a clear contrast.\n\n")
        + "## Evidence receipts\n\n"
        + "\n".join(
            f"- `fact_id={fid}` (`{lane}`) - receipt"
            for fid, lane in zip(ids, lanes, strict=True)
        )
        + "\n",
        encoding="utf-8",
    )
    run.joinpath("opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "status": "survives",
            "capped_opportunity": score,
            "cited_fact_ids": ids,
        }],
    }), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": fid, "lane": lane}
            for fid, lane in zip(ids, lanes, strict=True)
        ],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "source_paper": {
                "doi": doi, "title": title, "journal": journal, "year": 2026,
            },
        }
        for fid, doi, title, journal in zip(ids, dois, titles, journals, strict=True)
    ]), encoding="utf-8")
    return run


def test_ready_to_publish_requires_bound_concentrated_tension(tmp_path: Path) -> None:
    verdict = publish_verdict(_run(tmp_path))

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["publish_tier"] == "TIER_1"
    assert verdict["maturity_level"] == "L5"
    assert verdict["blockers"] == []


def test_no_bound_receipts_routes_to_curation(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        label="curation_needed",
        lanes=("D_bad_extraction", "D_bad_extraction", "D_bad_extraction"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "curation_needed"
    assert "no_bound_receipts" in verdict["blockers"]


def test_cross_domain_forced_routes_to_operator_review(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        dois=("10.a", "10.b", "10.b"),
        titles=(
            "Tariff auctions shift grid reserve reliability",
            "Ceramic kiln glazing changes pigment adhesion",
            "Ceramic kiln firing changes pigment durability",
        ),
        journals=("Energy Markets", "Materials Craft", "Materials Craft"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "needs_operator_review"
    assert verdict["publish_tier"] == "TIER_2"
    assert "cross_domain_forced" in verdict["blockers"]


def test_source_dispersion_routes_to_operator_review(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Reserve auctions threshold changes grid storage reliability",
            "Reserve dispatch threshold changes grid storage reliability",
            "Reserve pricing threshold changes grid storage reliability",
        ),
        journals=("Grid Review", "Grid Letters", "Grid Reports", "Grid Notes"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "needs_operator_review"
    assert "source_dispersion" in verdict["blockers"]
    assert "cross_domain_forced" not in verdict["blockers"]


def test_low_alpha_score_routes_to_curation(tmp_path: Path) -> None:
    verdict = publish_verdict(_run(tmp_path, score=0))

    assert verdict["decision"] == "curation_needed"
    assert "low_alpha_score" in verdict["blockers"]


def test_feed_scope_mismatch_routes_to_curation(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        titles=(
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
        ),
        journals=("Crop Systems", "Crop Systems", "Crop Systems"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "curation_needed"
    assert "feed_scope_mismatch" in verdict["blockers"]


def test_write_publish_verdict_writes_file(tmp_path: Path) -> None:
    run = _run(tmp_path)

    path, verdict = write_publish_verdict(run)

    assert path == run / "publish_verdict.json"
    assert json.loads(path.read_text(encoding="utf-8")) == verdict
