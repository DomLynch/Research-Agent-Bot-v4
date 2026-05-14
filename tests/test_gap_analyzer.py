"""Sprint 44 — gap-analyzer tests.

Locks the publish-opportunity trigger contract:
  - publication_opportunity=True in a snapshot → fires
  - |delta_points| >= 10 → fires as `strong_mover`
  - malformed JSON / missing fields → never raises
  - prioritization caps at MAX_TOPICS_PER_DIGEST
Universal: every fixture uses generic study IDs; no domain literals.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.gap_analyzer import (
    PublishOpportunity,
    _opportunities_for_topic,
    run_gap_analysis,
)


def _write(p: Path, obj: object) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def _make_topic_snapshot(
    topic_dir: Path, *, claims: list[dict[str, object]],
    movers: list[dict[str, object]] | None = None,
    snapshot_utc: str = "2026-05-14T10-00-00Z",
) -> None:
    topic_dir.mkdir(parents=True, exist_ok=True)
    snap_file = f"{snapshot_utc}.json"
    _write(topic_dir / snap_file, {
        "topic": topic_dir.name, "snapshot_utc": snapshot_utc,
        "paper_dir_name": "x", "claims": claims,
    })
    _write(topic_dir / f"{snapshot_utc}_movers.json", {
        "topic": topic_dir.name, "snapshot_utc": snapshot_utc,
        "movers": movers or [],
    })
    _write(topic_dir / "_latest_snapshot.json", {
        "snapshot_file": snap_file, "snapshot_utc": snapshot_utc,
    })


def test_publication_opportunity_claim_fires(tmp_path: Path) -> None:
    """Claim with publication_opportunity=True surfaces as a trigger."""
    out = _opportunities_for_topic(
        "rapamycin",
        snapshot={"snapshot_utc": "t", "claims": [{
            "claim_text": "rapamycin → lifespan",
            "confidence_0_100": 75,
            "publication_opportunity": True,
            "paper_type": "pilot-meta-analysis",
            "supporting_study_ids": ["s01", "s02"],
        }]},
        movers={"movers": []},
    )
    assert len(out) == 1
    op = out[0]
    assert isinstance(op, PublishOpportunity)
    assert op.reason == "publication_opportunity_fires"
    assert op.confidence_0_100 == 75
    assert op.supporting_study_count == 2


def test_strong_mover_fires_at_threshold(tmp_path: Path) -> None:
    """Claim with delta>=10 fires as strong_mover (even without pub-opp)."""
    out = _opportunities_for_topic(
        "rapamycin",
        snapshot={"snapshot_utc": "t", "claims": [{
            "claim_text": "rapamycin → lifespan",
            "confidence_0_100": 55,
            "publication_opportunity": False,
            "paper_type": "scoping-review",
            "supporting_study_ids": [],
        }]},
        movers={"movers": [{
            "claim_text": "rapamycin → lifespan",
            "delta_points": 12,
        }]},
    )
    assert len(out) == 1
    assert out[0].reason == "strong_mover"
    assert out[0].delta_points == 12


def test_weak_delta_below_threshold_does_not_fire(tmp_path: Path) -> None:
    """delta < 10 = noise. Doesn't trigger a paper write."""
    out = _opportunities_for_topic(
        "rapamycin",
        snapshot={"snapshot_utc": "t", "claims": [{
            "claim_text": "c", "confidence_0_100": 50,
            "publication_opportunity": False, "paper_type": "scoping-review",
            "supporting_study_ids": [],
        }]},
        movers={"movers": [{"claim_text": "c", "delta_points": 5}]},
    )
    assert out == []


def test_pub_opp_does_not_double_count_with_strong_mover(tmp_path: Path) -> None:
    """A claim that BOTH fires pub-opp AND has a >=10 delta should
    emit only ONE opportunity (the higher-signal pub-opp reason)."""
    out = _opportunities_for_topic(
        "rapamycin",
        snapshot={"snapshot_utc": "t", "claims": [{
            "claim_text": "c", "confidence_0_100": 80,
            "publication_opportunity": True, "paper_type": "x",
            "supporting_study_ids": ["s01", "s02"],
        }]},
        movers={"movers": [{"claim_text": "c", "delta_points": 20}]},
    )
    assert len(out) == 1
    assert out[0].reason == "publication_opportunity_fires"


def test_malformed_snapshot_does_not_raise(tmp_path: Path) -> None:
    """Missing/wrong-type fields coerce to defaults; no exception."""
    out = _opportunities_for_topic(
        "x",
        snapshot={"claims": [
            "not-a-dict",
            {"claim_text": 123, "confidence_0_100": "bad"},  # wrong types
            {"claim_text": "c", "publication_opportunity": True,
             "supporting_study_ids": "not-a-list"},
        ]},
        movers={"movers": "not-a-list"},
    )
    # Only one entry has pub_opp=True → only one opportunity.
    assert len(out) == 1
    assert out[0].reason == "publication_opportunity_fires"
    assert out[0].supporting_study_count == 0  # malformed list → 0


def test_run_gap_analysis_caps_at_top_n_by_priority(tmp_path: Path) -> None:
    """With more opportunities than MAX_TOPICS_PER_DIGEST, the result
    is capped and sorted by priority desc."""
    root = tmp_path / "_index"
    for i, conf in enumerate([95, 80, 70, 60, 90, 75, 88]):
        topic = f"topic{i:02d}"
        _make_topic_snapshot(root / topic, claims=[{
            "claim_text": f"{topic}-claim",
            "confidence_0_100": conf,
            "publication_opportunity": True,
            "paper_type": "x",
            "supporting_study_ids": ["s01", "s02"],
        }])
    digest = run_gap_analysis(root, snapshot_utc="t1")
    assert digest.topics_inspected == 7
    assert len(digest.opportunities) == 5  # capped
    # Verify desc-by-priority ordering — first item is the strongest.
    priorities = [o.priority for o in digest.opportunities]
    assert priorities == sorted(priorities, reverse=True)


def test_run_gap_analysis_skips_topics_without_snapshot(tmp_path: Path) -> None:
    """Empty topic dirs are ignored — no crash, just no opportunities."""
    root = tmp_path / "_index"
    (root / "empty_topic").mkdir(parents=True)
    _make_topic_snapshot(root / "real_topic", claims=[{
        "claim_text": "x", "confidence_0_100": 80,
        "publication_opportunity": True, "paper_type": "x",
        "supporting_study_ids": ["s01", "s02"],
    }])
    digest = run_gap_analysis(root, snapshot_utc="t")
    assert digest.topics_inspected == 1  # empty_topic ignored
    assert len(digest.opportunities) == 1
    assert digest.opportunities[0].topic == "real_topic"


def test_run_gap_analysis_handles_missing_index_dir(tmp_path: Path) -> None:
    digest = run_gap_analysis(tmp_path / "nonexistent", snapshot_utc="t")
    assert digest.topics_inspected == 0
    assert digest.opportunities == ()


def test_publish_opportunity_as_dict_round_trips(tmp_path: Path) -> None:
    op = PublishOpportunity(
        topic="rapamycin", reason="publication_opportunity_fires",
        confidence_0_100=80, delta_points=10,
        claim_text="rapamycin → lifespan", paper_type="pilot-meta-analysis",
        supporting_study_count=2, snapshot_utc="t", priority=90,
    )
    d = op.as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["reason"] == "publication_opportunity_fires"


def test_run_gap_analysis_universal_for_non_biomedical_topic(tmp_path: Path) -> None:
    """climate-vocab topic produces identical structure — proves no
    domain coupling in the analyzer."""
    root = tmp_path / "_index"
    _make_topic_snapshot(root / "carbon_tax", claims=[{
        "claim_text": "carbon tax → emissions reduction",
        "confidence_0_100": 75,
        "publication_opportunity": True,
        "paper_type": "pilot-meta-analysis",
        "supporting_study_ids": ["city-stockholm-2022", "country-norway-2019"],
    }])
    digest = run_gap_analysis(root, snapshot_utc="t")
    assert digest.opportunities[0].topic == "carbon_tax"
    assert digest.opportunities[0].supporting_study_count == 2
