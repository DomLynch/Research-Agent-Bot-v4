from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import scripts.build_topic_evidence_run as evidence_run
import scripts.daily_alpha_publish_cycle as daily
import scripts.run_topic_discovery as run_topic_discovery
from agent.domain_profile import load_domain_profile
from agent.topic_discovery import TopicCandidate, load_seed_topics


def _ai_queue_run(runs: Path, topic: str) -> None:
    run = runs / f"{topic}-evidence-ts"
    run.mkdir(parents=True)
    run.joinpath("alpha_memo.md").write_text("# Alpha memo\n", encoding="utf-8")
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")
    run.joinpath("publish_verdict.json").write_text(json.dumps(
        _ai_verdict() | {"topic": topic, "run_dir": f"runs/{run.name}"},
    ), encoding="utf-8")


def test_ai_research_profile_is_live_with_own_seed_pack() -> None:
    profile = load_domain_profile("ai_research")

    assert profile.slug == "ai_research"
    assert profile.dry_run_only is False
    assert profile.seed_topics_path.name == "ai_research_discovery_seeds.toml"
    seeds = load_seed_topics(profile.seed_topics_path)
    assert "ai_agents" in seeds
    assert "research_automation" in seeds


def test_default_domain_remains_longevity() -> None:
    profile = load_domain_profile(None)

    assert profile.slug == "longevity"
    assert profile.dry_run_only is False
    assert profile.seed_topics_path.name == "discovery_seeds.toml"


def test_ai_research_discovery_uses_ai_seed_pack(
    tmp_path: Path, monkeypatch: Any,
    ) -> None:
    seen: list[tuple[str, ...]] = []
    seen_domains: list[str] = []

    def fake_discover(**kwargs: Any) -> tuple[TopicCandidate, ...]:
        seen.append(kwargs["seeds"])
        seen_domains.append(kwargs["domain"])
        return (
            TopicCandidate(
                topic="ai_agents", paper_count=1, fact_source_count=5,
                top_paper_doi="10.1/ai", top_paper_title="AI agents",
                velocity_score=1.0, mean_fwci=1.0, mean_cited_by=1.0,
            ),
        )

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(run_topic_discovery, "load_settings", MagicMock())
    monkeypatch.setattr(run_topic_discovery, "discover_topics", fake_discover)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py", "--domain", "ai_research", "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    assert seen and "ai_agents" in seen[0]
    assert seen_domains == ["ai_research"]
    assert "rapamycin" not in seen[0]
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["domain"]["slug"] == "ai_research"


def test_ai_research_cache_only_does_not_leak_longevity_cache(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    def cached_source_rich_candidates(*, limit: int) -> tuple[TopicCandidate, ...]:
        raise AssertionError("non-longevity domains must not use global cache")

    def discover_topics(**_kwargs: Any) -> tuple[TopicCandidate, ...]:
        raise AssertionError("cache-only must not fetch")

    fake_script = tmp_path / "scripts" / "run_topic_discovery.py"
    fake_script.parent.mkdir(parents=True)
    monkeypatch.setattr(run_topic_discovery, "__file__", str(fake_script))
    monkeypatch.setattr(
        run_topic_discovery,
        "cached_source_rich_candidates",
        cached_source_rich_candidates,
    )
    monkeypatch.setattr(run_topic_discovery, "discover_topics", discover_topics)
    monkeypatch.setattr(sys, "argv", [
        "run_topic_discovery.py",
        "--domain", "ai_research",
        "--cache-only",
        "--top", "1",
    ])

    assert run_topic_discovery.main() == 0
    out = sorted((tmp_path / "runs" / "_topics_discovery").glob("*.json"))
    payload = json.loads(out[-1].read_text(encoding="utf-8"))
    assert payload["domain"]["slug"] == "ai_research"
    assert payload["cache_supported"] is False
    assert payload["candidate_count"] == 0
    assert payload["top"] == []


def test_ai_research_evidence_run_records_domain(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    class _S:
        writer_configured = False

    seen_domains: list[str] = []

    def _fetch_empty(
        _topic: str, *, trace: list[dict[str, Any]], domain: str = "longevity",
    ) -> list[dict[str, Any]]:
        seen_domains.append(domain)
        trace.append({
            "kind": "tier1", "query": "ai_agents", "facts": 0,
            "status": "ok", "errors": [],
        })
        return []

    monkeypatch.setattr(evidence_run, "_RUNS", tmp_path / "runs")
    monkeypatch.setattr(evidence_run, "_fetch_facts", _fetch_empty)
    monkeypatch.setattr(evidence_run, "load_settings", lambda: _S())
    monkeypatch.setattr(sys, "argv", [
        "build_topic_evidence_run.py",
        "--domain", "ai_research",
        "--topic", "ai_agents",
        "--top", "5",
        "--no-frontier",
    ])

    assert evidence_run.main() == 0
    run_dir = next((tmp_path / "runs").glob("ai_agents-evidence-*"))
    manifest = json.loads((run_dir / "MANIFEST.json").read_text())
    trace = json.loads((run_dir / "search_trace.json").read_text())
    assert manifest["domain"]["slug"] == "ai_research"
    assert trace["domain"]["slug"] == "ai_research"
    assert seen_domains == ["ai_research"]


def _ai_verdict() -> dict[str, Any]:
    source_papers = [
        {"doi": f"10.2000/ai-{i}", "title": f"AI benchmark paper {i}"}
        for i in range(5)
    ]
    return {
        "run_dir": "runs/ai_agents-evidence-ts",
        "domain": load_domain_profile("ai_research").as_metadata(),
        "topic": "ai_agents",
        "decision": "ready_to_publish",
        "publish_tier": "TIER_1",
        "maturity_level": "L5",
        "headline": "AI agents improve benchmarked research workflow throughput",
        "confidence_label": "evidence_backed_signal",
        "alpha_score": 90,
        "surface_type": "publish_alpha_memo",
        "axes": {"available_source_contexts": 5, "source_papers": source_papers},
        "receipt_expansion": {"cited_bound_fact_ids": ["1", "2", "3", "4", "5"]},
    }


def _write_ai_memo(root: Path, verdict: dict[str, Any]) -> None:
    run = root / str(verdict["run_dir"])
    run.mkdir(parents=True)
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": verdict["domain"],
    }), encoding="utf-8")
    ids = ["1", "2", "3", "4", "5"]
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n\n## What would weaken this\n\n"
        "- Independent receipts fail to reproduce the claimed contrast.\n",
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": (
                "AI agents improved benchmarked research workflow throughput."
            ),
            "source_paper": {
                "doi": f"10.2000/ai-{fid}",
                "title": f"AI benchmark paper {fid}",
            },
        }
        for fid in ids
    ]), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in ids],
    }), encoding="utf-8")
    for name, payload in {
        "claim_receipt_matrix.json": {"direct_sources": 5},
        "typed_counter_evidence.json": {"items": []},
        "novelty_delta.json": {"novelty_delta": {"label": "contradictory"}},
        "memo_audit.json": {"verdict": "supported"},
    }.items():
        run.joinpath(name).write_text(json.dumps(payload), encoding="utf-8")


def test_ai_research_daily_submit_is_live_when_explicitly_selected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    verdict = _ai_verdict()
    _write_ai_memo(root, verdict)
    calls: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=root / "runs",
        date="2026-06-05T00-00-00Z",
        domain="ai_research",
        queue={"ready_to_publish": [verdict], "needs_operator_review": [], "curation_needed": []},
        submit=True,
        retraction_mode="metadata",
        submitter=submitter,
        fetcher=lambda _doi: {},
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["dry_run"] is False
    assert ledger["submit_requested"] is True
    assert ledger["submitted"] == 1
    assert calls and calls[0]["topic"] == "ai_agents"


def test_ai_research_queue_excludes_seed_mismatched_domain_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for topic in (
        "sglt2_inhibitors_events",
        "ai_agents",
        "llm_judge_reliability",
        "research_automation",
    ):
        _ai_queue_run(runs, topic)

    out = daily._build_queue(runs, include_archive=False, domain="ai_research")

    topics = [r["topic"] for r in out["ready_to_publish"]]
    assert "sglt2_inhibitors_events" not in topics
    assert set(topics) == {"ai_agents", "llm_judge_reliability", "research_automation"}
    assert out["_meta"]["seed_scope_dropped_count"] == 1
    assert out["_meta"]["seed_scope_fallback_used"] is False


def test_ai_research_queue_keeps_seed_scope_when_thin(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for topic in ("sglt2_inhibitors_events", "llm_judge_reliability"):
        _ai_queue_run(runs, topic)

    out = daily._build_queue(runs, include_archive=False, domain="ai_research")

    assert [r["topic"] for r in out["ready_to_publish"]] == ["llm_judge_reliability"]
    assert out["_meta"]["seed_scope_dropped_count"] == 1
    assert out["_meta"]["seed_scope_fallback_count"] == 0
    assert out["_meta"]["seed_scope_fallback_used"] is False
