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


def test_ai_research_profile_is_dry_run_only_with_own_seed_pack() -> None:
    profile = load_domain_profile("ai_research")

    assert profile.slug == "ai_research"
    assert profile.dry_run_only is True
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

    def fake_discover(**kwargs: Any) -> tuple[TopicCandidate, ...]:
        seen.append(kwargs["seeds"])
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

    def _fetch_empty(
        _topic: str, *, trace: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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


def test_ai_research_daily_submit_is_blocked_by_dry_run_fence(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"ok": True, "status": 200, "response": {}}

    ledger = daily.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-05T00-00-00Z",
        domain="ai_research",
        submit=True,
        submitter=submitter,
    )

    assert ledger["status"] == "domain_dry_run_only"
    assert ledger["dry_run"] is True
    assert ledger["submit_requested"] is True
    assert ledger["submitted"] == 0
    assert calls == []
