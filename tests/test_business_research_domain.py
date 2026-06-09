from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import scripts.build_business_alpha_candidate as business_cli
import scripts.build_publish_queue as queue
from agent.business_research import build_candidate_bundle
from agent.domain_profile import load_domain_profile
from agent.topic_discovery import load_seed_topics


def _fixture_facts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(1, 6):
        rows.append({
            "id": f"mgmt-{i}",
            "topic": "management_research",
            "claim_type": "productivity_effect",
            "numeric_value": 8 + i,
            "units": "%",
            "canonical_phrase": (
                "Management practices productivity increased relative to "
                "standard supervision in manufacturing firms."
            ),
            "population": "manufacturing firms",
            "organization_type": "firms",
            "industry": "manufacturing",
            "geography": "multi country",
            "time_period": "panel years",
            "intervention": "management practices",
            "comparator": "standard supervision",
            "outcome": "firm productivity",
            "metric": "productivity",
            "study_design": "quasi experimental panel",
            "dataset": "firm panel",
            "estimation_method": "difference in differences",
            "identification_strategy": "matched treatment timing",
            "effect_size": 8 + i,
            "sample_size": 1000 + i,
            "paper": {
                "doi": f"10.5555/mgmt-{i}",
                "title": "Management practices productivity in manufacturing firms",
                "journal_name": "Management Science",
                "publication_year": 2024,
            },
        })
    return rows


def test_business_family_profiles_are_dry_run_and_seeded() -> None:
    for domain in (
        "business_research",
        "management_research",
        "economics_research",
        "finance_research",
        "marketing_research",
    ):
        profile = load_domain_profile(domain)
        assert profile.dry_run_only is True
        assert profile.seed_topics_path.exists()
        assert profile.source_policy_path.exists()
        assert profile.claim_schema_path.exists()
        assert load_seed_topics(profile.seed_topics_path)


def test_business_bundle_clusters_shape_and_preserves_fields() -> None:
    bundle = build_candidate_bundle(
        _fixture_facts(),
        topic="management_practices_productivity",
        domain="management_research",
    )

    assert bundle is not None
    assert bundle.source_count == 5
    assert bundle.shape["intervention"] == "management practices"
    assert bundle.shape["metric"] == "productivity"
    assert bundle.receipts[0]["identification_strategy"] == "matched treatment timing"
    assert bundle.receipts[0]["sample_size"] == "1001"


def test_business_bundle_materializes_shape_fallbacks() -> None:
    rows = _fixture_facts()
    for row in rows:
        row.pop("outcome")
        row.pop("study_design")
        row["metric"] = "firm productivity"
        row["identification_strategy"] = "difference in differences"

    bundle = build_candidate_bundle(
        rows,
        topic="management_practices_productivity",
        domain="management_research",
    )

    assert bundle is not None
    assert bundle.shape["outcome"] == "firm productivity"
    assert bundle.shape["study_design"] == "difference in differences"


def test_business_candidate_cli_builds_ready_dry_run_queue(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_fixture_facts()), encoding="utf-8")
    runs = tmp_path / "runs"
    monkeypatch.setattr(queue, "_RUNS", runs)
    monkeypatch.setattr(sys, "argv", [
        "build_business_alpha_candidate.py",
        "--domain", "management_research",
        "--topic", "management_practices_productivity",
        "--facts-json", str(facts_path),
        "--runs-root", str(runs),
        "--snapshot-utc", "2026-06-09T00-00-00Z",
    ])

    assert business_cli.main() == 0
    out = queue.build_queue(include_archive=False, domain="management_research")

    assert [row["topic"] for row in out["ready_to_publish"]] == [
        "management_practices_productivity",
    ]
    run_dir = runs / "management_practices_productivity-evidence-2026-06-09T00-00-00Z"
    manifest = json.loads((run_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    facts = json.loads((run_dir / "all_facts.json").read_text(encoding="utf-8"))
    verdict = json.loads((run_dir / "publish_verdict.json").read_text(encoding="utf-8"))
    assert manifest["dry_run_only"] is True
    assert manifest["domain"]["slug"] == "management_research"
    assert facts[0]["result_shape"]["study_design"] == "quasi experimental panel"
    assert verdict["decision"] == "ready_to_publish"
    assert verdict["axes"]["direct_source_papers"] == 5


def test_business_candidate_cli_writes_no_bundle_diagnostics(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_fixture_facts()[:1]), encoding="utf-8")
    runs = tmp_path / "runs"
    monkeypatch.setattr(sys, "argv", [
        "build_business_alpha_candidate.py",
        "--domain", "management_research",
        "--topic", "management_practices_productivity",
        "--facts-json", str(facts_path),
        "--runs-root", str(runs),
    ])

    assert business_cli.main() == 3
    diagnostics = json.loads(
        (
            runs / "_business_diagnostics"
            / "management_research-management_practices_productivity.json"
        ).read_text(encoding="utf-8")
    )
    assert diagnostics["raw_fact_count"] == 1
    assert diagnostics["a_core_fact_count"] == 1
    assert diagnostics["top_clusters"][0]["source_count"] == 1


def test_business_systemd_timers_are_eight_hour_dry_run() -> None:
    expectations = {
        "business": ("business_research", "02/8:10:00"),
        "management": ("management_research", "03/8:10:00"),
        "economics": ("economics_research", "04/8:10:00"),
        "finance": ("finance_research", "05/8:10:00"),
        "marketing": ("marketing_research", "06/8:10:00"),
    }
    for name, (domain, schedule) in expectations.items():
        service = Path(f"deploy/systemd/researka-alpha-{name}-research.service").read_text(
            encoding="utf-8",
        )
        timer = Path(f"deploy/systemd/researka-alpha-{name}-research.timer").read_text(
            encoding="utf-8",
        )
        assert "scripts/build_business_alpha_candidate.py" in service
        assert f"--domain {domain}" in service
        assert "--submit" not in service
        assert "SuccessExitStatus=3" in service
        assert "EnvironmentFile=-/etc/researka-agent-v4.env" in service
        assert f"OnCalendar=*-*-* {schedule}" in timer
