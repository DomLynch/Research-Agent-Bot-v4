from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import scripts.build_business_alpha_candidate as business_cli
import scripts.build_publish_queue as queue
import scripts.run_business_alpha_sweep as sweep
from agent.business_research import build_candidate_bundle
from agent.domain_profile import DomainProfile, load_domain_profile
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


def test_business_bundle_infers_study_design_from_method_text() -> None:
    rows = _fixture_facts()
    for row in rows:
        row.pop("study_design")
        row.pop("identification_strategy")
        row.pop("estimation_method")
        row["canonical_phrase"] = (
            "The randomized controlled trial increased firm productivity "
            "relative to standard supervision."
        )

    bundle = build_candidate_bundle(
        rows,
        topic="management_practices_productivity",
        domain="management_research",
    )

    assert bundle is not None
    assert bundle.shape["study_design"] == "randomized controlled trial"


def test_business_bundle_ignores_generic_study_design_other() -> None:
    rows = _fixture_facts()
    for row in rows:
        row["claim_type"] = "returns_effect"
        row["canonical_phrase"] = "Factor premia earned abnormal returns."
        row["intervention"] = "factor premia"
        row["comparator"] = "market portfolio"
        row["outcome"] = "abnormal returns"
        row["metric"] = "returns"
        row["study_design"] = "other"
        row["identification_strategy"] = "asset pricing"

    bundle = build_candidate_bundle(
        rows,
        topic="factor_premia_returns",
        domain="finance_research",
    )

    assert bundle is not None
    assert bundle.shape["study_design"] == "asset pricing"


def test_business_bundle_rejects_off_topic_medical_management_fact() -> None:
    rows = _fixture_facts()
    for i, row in enumerate(rows, start=1):
        row.update({
            "id": f"medical-{i}",
            "topic": "mortality",
            "claim_type": "weight_loss_effect",
            "canonical_phrase": "Liraglutide achieved weight loss in specialist weight management services.",
            "population": "patients in specialist weight management services",
            "intervention": "liraglutide",
            "comparator": "standard care",
            "outcome": "weight loss",
            "metric": "weight loss",
            "study_design": "randomized controlled trial",
        })

    bundle = build_candidate_bundle(
        rows,
        topic="management_practices_productivity",
        domain="management_research",
    )

    assert bundle is None


def test_business_bundle_rejects_policy_only_medical_econ_fact() -> None:
    rows = _fixture_facts()
    for i, row in enumerate(rows, start=1):
        row.update({
            "id": f"bcg-{i}",
            "topic": "mortality",
            "claim_type": "mortality_effect",
            "canonical_phrase": "Early BCG reduced neonatal mortality.",
            "population": "low weight neonates",
            "intervention": "early BCG",
            "comparator": "control local policy",
            "outcome": "mortality",
            "metric": "mortality rate",
            "study_design": "randomized controlled trial",
        })

    bundle = build_candidate_bundle(
        rows,
        topic="monetary_policy_inflation",
        domain="economics_research",
    )

    assert bundle is None


def test_finance_return_facts_cluster_by_empirical_asset_pricing_shape() -> None:
    rows = [
        {
            "id": f"fin-{i}",
            "topic": "portfolio_returns" if i % 2 else "asset_pricing",
            "claim_type": "portfolio_returns",
            "numeric_value": value,
            "units": "%",
            "canonical_phrase": phrase,
            "population": population,
            "intervention": intervention,
            "comparator": comparator,
            "paper": {"doi": f"10.7777/finance-{i}", "title": "Portfolio returns"},
        }
        for i, (value, phrase, population, intervention, comparator) in enumerate([
            (11.0, "earns abnormal returns of roughly 11 percent per year", "portfolio", "past track record portfolio", ""),
            (8.6, "earns an average annual return of 8.6% in high-skill industries", "firms", "hiring-rate long-short portfolio", "low-skill industries"),
            (5.0, "firms in mobile industries earn returns over 5% higher", "firms", "labor mobility", "less mobile industries"),
            (2.4, "earn significant out-of-sample annual alphas of 2.4%", "mutual funds", "machine-learning fund characteristics", ""),
            (1.5, "one standard deviation in EPU is associated with a 1.5% increase in abnormal returns", "US market", "economic policy uncertainty exposure", ""),
        ], start=1)
    ]

    bundle = build_candidate_bundle(
        rows,
        topic="factor_premia_returns",
        domain="finance_research",
    )

    assert bundle is not None
    assert bundle.source_count == 5
    assert bundle.shape["study_design"] == "empirical asset pricing"
    assert bundle.shape["metric"] == "percentage return or alpha"
    assert bundle.receipts[0]["intervention"] == "return predictive signal portfolio"
    assert bundle.receipts[0]["intervention_detail"] == "past track record portfolio"


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


def test_business_sweep_submit_guard_blocks_dry_run_domain(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: ["management_practices_productivity"])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (_fixture_facts(), {"status": "ok"}))
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
    ])

    assert sweep.main() == 2
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        )
    )
    assert summary["results"][0]["status"] == "submit_blocked_domain_dry_run_only"


def test_business_sweep_submits_after_consistent_non_dry_run_passes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("management_research")
    live_profile = DomainProfile(
        slug=profile.slug,
        display_name=profile.display_name,
        seed_topics_path=profile.seed_topics_path,
        source_policy_path=profile.source_policy_path,
        claim_schema_path=profile.claim_schema_path,
        dry_run_only=False,
    )
    submissions: list[dict[str, Any]] = []
    fetch_calls = 0

    def fake_submitter(_url: str, _token: str) -> Any:
        def submit(payload: dict[str, Any]) -> dict[str, Any]:
            submissions.append(payload)
            return {
                "ok": True,
                "status": 202,
                "response": {"submission_id": "sub-business-1"},
            }
        return submit

    def fake_fetch(*_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
        nonlocal fetch_calls
        fetch_calls += 1
        facts = _fixture_facts()
        return (list(reversed(facts)) if fetch_calls == 2 else facts), {"status": "ok"}

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: live_profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: ["management_practices_productivity"])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "_submit_token", lambda: ("test-token", "TEST_TOKEN"))
    monkeypatch.setattr(sweep, "_http_submitter", fake_submitter)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "2",
        "--topics-per-domain", "1",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "2",
    ])

    assert sweep.main() == 0
    assert len(submissions) == 1
    assert submissions[0]["domain"]["slug"] == "management_research"
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        )
    )
    assert [row["status"] for row in summary["results"]] == [
        "ready_waiting_consistency",
        "submitted",
    ]


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
