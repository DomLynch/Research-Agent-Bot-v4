from __future__ import annotations

import json
from pathlib import Path

import scripts.build_domain_evidence_inventory as inventory
from agent.domain_profile import load_domain_profile


def _write_discovery(
    runs: Path, stamp: str, domain: str, candidates: list[dict[str, object]],
) -> None:
    out = runs / "_topics_discovery"
    out.mkdir(parents=True, exist_ok=True)
    out.joinpath(f"{stamp}.json").write_text(json.dumps({
        "domain": load_domain_profile(domain).as_metadata(),
        "snapshot_utc": stamp,
        "top": candidates[:1],
        "all": candidates,
    }), encoding="utf-8")


def _write_run(
    runs: Path,
    topic: str,
    *,
    domain: str | None,
    stamp: str = "2026-06-06T00-00-00Z",
    archive: str = "",
) -> None:
    base = runs / "_archive" / archive if archive else runs
    run = base / f"{topic}-evidence-{stamp}"
    run.mkdir(parents=True)
    if domain:
        run.joinpath("MANIFEST.json").write_text(json.dumps({
            "domain": load_domain_profile(domain).as_metadata(),
        }), encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps({
        "domain": load_domain_profile(domain).as_metadata() if domain else {},
        "topic": topic,
        "decision": "ready_to_publish",
        "publish_tier": "TIER_1",
        "alpha_score": 91,
        "confidence_label": "evidence_backed_signal",
        "surface_type": "publish_alpha_memo",
        "headline": "AI agents improve research workflow throughput",
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {"fact_id": "1", "source_paper": {"doi": "10.ai/1"}},
        {"fact_id": "2", "source_paper": {"doi": "10.ai/2"}},
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": "1", "lane": "A_core"},
            {"fact_id": "2", "lane": "B_context"},
        ],
    }), encoding="utf-8")


def test_inventory_is_domain_scoped_and_receipt_backed(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_discovery(runs, "2026-06-05T00-00-00Z", "longevity", [{
        "topic": "rapamycin",
        "paper_count": 99,
        "fact_source_count": 99,
        "velocity_score": 99.0,
    }])
    _write_discovery(runs, "2026-06-04T00-00-00Z", "ai_research", [{
        "topic": "ai_agents",
        "paper_count": 8,
        "fact_source_count": 6,
        "velocity_score": 12.5,
        "top_paper_doi": "10.ai/top",
        "top_paper_title": "AI agents benchmark",
    }])
    _write_run(runs, "ai_agents", domain="ai_research")
    _write_run(runs, "untagged_medical", domain=None)

    out = inventory.build_inventory(
        "ai_research",
        runs_root=runs,
        snapshot_utc="2026-06-06T00-00-00Z",
    )

    topics = {row["topic"]: row for row in out["topics"]}
    ai_agents = topics["ai_agents"]
    assert out["domain"]["slug"] == "ai_research"
    assert out["discovery_snapshot"] == "2026-06-04T00-00-00Z"
    assert ai_agents["seeded"] is True
    assert ai_agents["discovered"] is True
    assert ai_agents["discovery"]["fact_source_count"] == 6
    assert ai_agents["evidence_run_count"] == 1
    assert ai_agents["latest_evidence_run"]["source_count"] == 2
    assert ai_agents["latest_evidence_run"]["lane_counts"] == {
        "A_core": 1,
        "B_context": 1,
    }
    assert "untagged_medical" not in topics


def test_inventory_latest_run_ignores_archive_order(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(
        runs,
        "ai_agents",
        domain="ai_research",
        stamp="2026-06-01T00-00-00Z",
        archive="older",
    )
    _write_run(
        runs,
        "ai_agents",
        domain="ai_research",
        stamp="2026-06-06T00-00-00Z",
    )

    out = inventory.build_inventory(
        "ai_research",
        runs_root=runs,
        snapshot_utc="2026-06-06T00-00-00Z",
    )

    topics = {row["topic"]: row for row in out["topics"]}
    latest = topics["ai_agents"]["latest_evidence_run"]
    assert topics["ai_agents"]["evidence_run_count"] == 2
    assert latest["run_dir"] == "ai_agents-evidence-2026-06-06T00-00-00Z"


def test_write_inventory_updates_latest_pointer(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    out = inventory.build_inventory(
        "ai_research",
        runs_root=runs,
        snapshot_utc="2026-06-06T00-00-00Z",
    )

    path = inventory.write_inventory(out)

    latest = json.loads(path.with_name("_latest.json").read_text(encoding="utf-8"))
    assert path.name == "2026-06-06T00-00-00Z.json"
    assert latest["snapshot_file"] == path.name
    assert latest["domain"]["slug"] == "ai_research"
