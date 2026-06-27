from __future__ import annotations

import fcntl
import json
import os
import signal as signal_mod
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx

import scripts.build_business_alpha_candidate as business_cli
import scripts.build_publish_queue as queue
import scripts.check_alpha_publish_health as health
import scripts.daily_alpha_publish_cycle as cycle
import scripts.run_business_alpha_sweep as sweep
from agent.business_research import (
    build_candidate_bundle,
    business_fact_diagnostics,
    cluster_business_facts,
    fetch_business_facts,
    normalize_business_fact,
    write_candidate_run,
)
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


def test_business_family_profiles_are_live_and_seeded() -> None:
    # All five business-family domains are ungated (audit #6): the econ_business
    # corpus now carries publishable facts, and the publish-tier gates
    # (homogeneity routing, stratification, payload-complete) are the quality
    # check — not the dry-run flag. economics/finance were already live; this
    # brings business/management/marketing in line.
    dry_run = {
        "business_research": False,
        "management_research": False,
        "economics_research": False,
        "finance_research": False,
        "marketing_research": False,
    }
    for domain in (
        "business_research",
        "management_research",
        "economics_research",
        "finance_research",
        "marketing_research",
    ):
        profile = load_domain_profile(domain)
        assert profile.dry_run_only is dry_run[domain]
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


def test_finance_return_bundle_rejects_mixed_signal_disagreement() -> None:
    rows: list[dict[str, Any]] = []
    signals = (
        "value factor long-short portfolio",
        "momentum factor long-short portfolio",
        "quality factor long-short portfolio",
        "liquidity factor long-short portfolio",
        "carbon disclosure factor portfolio",
    )
    for i, signal in enumerate(signals, start=1):
        rows.append({
            "id": f"finance-return-{i}",
            "topic": "portfolio_returns",
            "claim_type": "return_premium",
            "numeric_value": 13.0 if i == len(signals) else 1.0 + i,
            "units": "%",
            "canonical_phrase": f"{signal} earns abnormal return alpha.",
            "population": f"public equity portfolio segment {i}",
            "intervention": signal,
            "comparator": "benchmark portfolio",
            "outcome": "risk adjusted return",
            "metric": "annual alpha return",
            "study_design": "empirical asset pricing",
            "paper": {
                "doi": f"10.7777/finance-return-{i}",
                "title": "Predictive signals and portfolio returns",
            },
        })

    bundle = build_candidate_bundle(
        rows,
        topic="factor_premia_returns",
        domain="finance_research",
    )

    assert bundle is None
    diagnostics = business_fact_diagnostics(
        rows, topic="factor_premia_returns", domain="finance_research",
    )
    # Finance has no outlier_abs_threshold policy; this regression targets the
    # reviewer-rejected false comparison across different signal families.
    assert diagnostics["top_clusters"][0]["comparability_blockers"] == [
        "signal_family_heterogeneity_explains_spread",
    ]


def test_finance_return_bundle_splits_mixed_signal_when_subcluster_is_source_rich() -> None:
    rows: list[dict[str, Any]] = []
    for signal in ("value factor portfolio", "momentum factor portfolio"):
        for i in range(5):
            rows.append({
                "id": f"{signal}-{i}",
                "topic": "portfolio_returns",
                "claim_type": "return_premium",
                "numeric_value": 0.0 if i == 0 else 20.0 + i,
                "units": "%",
                "canonical_phrase": f"{signal} reports alpha return evidence.",
                "intervention": signal,
                "comparator": "benchmark portfolio",
                "outcome": "risk adjusted return",
                "metric": "annual alpha return",
                "study_design": "empirical asset pricing",
                "paper": {"doi": f"10.7777/{signal.replace(' ', '-')}-{i}"},
            })

    bundles = cluster_business_facts([
        normalize_business_fact(row, topic="portfolio_returns", domain="finance_research")
        for row in rows
    ])
    bundle = build_candidate_bundle(rows, topic="portfolio_returns", domain="finance_research")

    assert bundle is not None
    assert bundle.source_count == 5
    assert len({row["signal_family_detail"] for row in bundle.receipts}) == 1
    assert bundle.shape["signal_family"] in {
        "value factor portfolio",
        "momentum factor portfolio",
    }
    assert len({row.result_key for row in bundles}) == len(bundles)


def test_business_bundle_materializes_extractor_alias_fields() -> None:
    rows = _fixture_facts()
    for row in rows:
        row.pop("comparator")
        row.pop("outcome")
        row.pop("metric")
        row.pop("study_design")
        row["baseline_comparator"] = "matched control firms"
        row["outcome_metric"] = "operating productivity"
        row["design"] = "field experiment"

    bundle = build_candidate_bundle(
        rows,
        topic="management_practices_productivity",
        domain="management_research",
    )

    assert bundle is not None
    assert bundle.shape["comparator"] == "matched control firms"
    assert bundle.shape["outcome"] == "operating productivity"
    assert bundle.shape["metric"] == "operating productivity"
    assert bundle.shape["study_design"] == "field experiment"


def test_economics_schema_normalizer_clusters_minimum_wage_alias_rows() -> None:
    rows: list[dict[str, Any]] = []
    for i, phrase in enumerate([
        "minimum wage employment elasticity was not statistically different from zero",
        "minimum wage increases left low wage employment essentially unchanged",
        "teen employment elasticity near -0.15 after minimum wage increases",
        "minimum wage estimates imply small negative employment effects",
        "minimum wage effects on employment ranged from -0.1 to -0.3",
    ], start=1):
        rows.append({
            "id": f"mw-{i}",
            "topic": "labor_economics",
            "claim_type": "effect_size",
            "numeric_value": -0.05 * i,
            "canonical_phrase": phrase,
            "population": "teen workers",
            "intervention": "minimum wage",
            "metric": "employment elasticity",
            "design": "other",
            "identification_strategy": "local method wording",
            "paper": {
                "doi": f"10.6666/minwage-{i}",
                "title": "Minimum wage effects on employment",
            },
        })

    bundle = build_candidate_bundle(
        rows,
        topic="minimum_wage_employment",
        domain="economics_research",
    )

    assert bundle is not None
    assert bundle.source_count == 5
    assert bundle.shape["population"] == "low wage workers or jobs"
    assert bundle.shape["intervention"] == "minimum wage increase"
    assert bundle.shape["metric"] == "employment elasticity or employment change"
    assert bundle.shape["study_design"] == "empirical labor economics"
    assert bundle.shape["identification_strategy"] == "empirical labor economics"
    assert bundle.receipts[0]["population_detail"] == "teen workers"


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


def test_business_fetch_filters_global_fallback_when_live_schema_rejects_domain(
    monkeypatch: Any,
) -> None:
    calls: list[dict[str, Any]] = []
    timeouts: list[float] = []

    class _Settings:
        researka_database_url = "https://database.test"
        researka_database_token = "tok"

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        request = httpx.Request("POST", url)
        calls.append(json)
        timeouts.append(timeout)
        if len(calls) == 2:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "finance-1",
                        "topic": "portfolio_returns",
                        "claim_type": "rate",
                        "numeric_value": 1.2,
                        "metric": "factor premia returns",
                        "paper": {
                            "doi": "10.1000/finance",
                            "title": "Factor premia returns in asset pricing",
                        },
                    },
                    {
                        "id": "medical-1",
                        "topic": "other",
                        "claim_type": "rate",
                        "numeric_value": 60.0,
                        "population": "patients needing oxygen",
                        "intervention": "medical oxygen",
                        "paper": {"doi": "10.1000/oxygen", "title": "Medical oxygen access"},
                    },
                ],
                request=request,
            )
        return httpx.Response(
            422, json={"detail": "domain extra_forbidden"}, request=request,
        )

    monkeypatch.setattr("agent.business_research.httpx.post", fake_post)

    rows, trace = fetch_business_facts(
        "factor_premia_returns",
        domain="finance_research",
        settings=cast(Any, _Settings()),
    )

    assert [row["id"] for row in rows] == ["finance-1"]
    assert calls[0]["domain"] == "econ_business"
    assert "domain" not in calls[1]
    assert len(calls) == 2
    assert timeouts == [20.0, 20.0]
    assert trace["status"] == "fallback_filtered"
    assert trace["http_status"] == 200
    assert trace["domain_http_status"] == 422
    assert trace["fallback_unfiltered_facts"] == 2
    assert trace["facts"] == 1
    assert trace["domain_filter_used"] is False


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
            "paper": {
                "doi": f"10.5555/medical-{i}",
                "title": "Liraglutide weight loss in specialist weight management services",
            },
        })
        for key in (
            "organization_type",
            "industry",
            "geography",
            "time_period",
            "dataset",
            "estimation_method",
            "identification_strategy",
            "effect_size",
            "sample_size",
        ):
            row.pop(key, None)

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
            "paper": {"doi": f"10.7777/finance-{i}", "title": "Factor premia portfolio returns"},
        }
        for i, (value, phrase, population, intervention, comparator) in enumerate([
            (8.1, "hiring-rate long-short portfolios earn 8.1% annual returns", "firms", "hiring-rate long-short portfolio", "low hiring rate portfolio"),
            (8.2, "hiring-rate long-short portfolios earn 8.2% annual returns", "firms", "hiring-rate long-short portfolio", "low hiring rate portfolio"),
            (8.3, "hiring-rate long-short portfolios earn 8.3% annual returns", "firms", "hiring-rate long-short portfolio", "low hiring rate portfolio"),
            (8.4, "hiring-rate long-short portfolios earn 8.4% annual returns", "firms", "hiring-rate long-short portfolio", "low hiring rate portfolio"),
            (8.5, "hiring-rate long-short portfolios earn 8.5% annual returns", "firms", "hiring-rate long-short portfolio", "low hiring rate portfolio"),
        ], start=1)
    ]

    bundle = build_candidate_bundle(
        rows,
        topic="factor_premia_returns",
        domain="finance_research",
    )

    assert bundle is not None
    assert bundle.source_count == 5
    assert bundle.shape["signal_family"] == "return predictive signal"
    assert bundle.shape["study_design"] == "empirical asset pricing"
    assert bundle.shape["metric"] == "percentage return or alpha premium"
    assert bundle.receipts[0]["intervention"] == "return predictive signal portfolio"
    assert bundle.receipts[0]["intervention_detail"] == "hiring-rate long-short portfolio"


def test_finance_return_facts_reject_mixed_signal_disagreement() -> None:
    rows = [
        {
            "id": f"fin-mixed-{i}",
            "topic": "asset_pricing",
            "claim_type": "portfolio_returns",
            "numeric_value": value,
            "units": "%",
            "canonical_phrase": phrase,
            "population": "firms",
            "intervention": intervention,
            "comparator": "benchmark portfolio",
            "paper": {"doi": f"10.7777/finance-mixed-{i}", "title": "Portfolio returns"},
        }
        for i, (value, phrase, intervention) in enumerate([
            (11.0, "factor premia returns earn abnormal returns of roughly 11 percent per year", "past track record portfolio"),
            (8.6, "factor premia returns average 8.6% annually in high-skill industries", "hiring-rate long-short portfolio"),
            (5.0, "factor premia returns in mobile industries exceed 5%", "labor mobility"),
            (2.4, "factor premia returns earn out-of-sample annual alphas of 2.4%", "machine-learning fund characteristics"),
            (1.5, "factor premia returns rise 1.5% with economic policy uncertainty exposure", "economic policy uncertainty exposure"),
        ], start=1)
    ]

    bundle = build_candidate_bundle(
        rows,
        topic="factor_premia_returns",
        domain="finance_research",
    )

    assert bundle is None
    diagnostics = business_fact_diagnostics(
        rows, topic="factor_premia_returns", domain="finance_research",
    )
    assert diagnostics["top_clusters"][0]["comparability_blockers"] == [
        "signal_family_heterogeneity_explains_spread",
    ]


def test_business_candidate_cli_builds_ready_queue(
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
    matrix = json.loads((run_dir / "claim_receipt_matrix.json").read_text(encoding="utf-8"))
    audit = json.loads((run_dir / "memo_audit.json").read_text(encoding="utf-8"))
    assert manifest["dry_run_only"] is False  # ungated (audit #6)
    assert manifest["domain"]["slug"] == "management_research"
    assert facts[0]["result_shape"]["study_design"] == "quasi experimental panel"
    assert verdict["decision"] == "ready_to_publish"
    assert verdict["axes"]["direct_source_papers"] == 5
    assert matrix["direct_sources"] == 5
    assert audit["verdict"] == "supported"
    candidate, considered = cycle.select_candidate(
        out,
        runs_root=runs,
        submitted_path=runs / "_daily_ledger" / "_submitted_fingerprints.json",
        min_source_count=5,
        min_direct_source_count=5,
        domain="management_research",
    )
    assert candidate is None
    assert considered[0]["direct_source_count"] == 5


def test_business_candidate_memo_synthesizes_mixed_effects(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    rows: list[dict[str, Any]] = []
    for i, value in enumerate([0.0, -0.15, 0.0, -0.1, -0.2], start=1):
        rows.append({
            "id": f"mw-mixed-{i}",
            "topic": "labor_economics",
            "claim_type": "effect_size",
            "numeric_value": value,
            "canonical_phrase": f"minimum wage employment elasticity estimate {value}",
            "population": "low wage workers",
            "intervention": "minimum wage",
            "metric": "employment elasticity",
            "paper": {"doi": f"10.6666/mw-mixed-{i}", "title": "Minimum wage employment"},
        })
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(rows), encoding="utf-8")
    runs = tmp_path / "runs"
    monkeypatch.setattr(sys, "argv", [
        "build_business_alpha_candidate.py",
        "--domain", "economics_research",
        "--topic", "minimum_wage_employment",
        "--facts-json", str(facts_path),
        "--runs-root", str(runs),
        "--snapshot-utc", "2026-06-09T00-00-01Z",
    ])

    assert business_cli.main() == 0
    memo = (
        runs / "minimum_wage_employment-evidence-2026-06-09T00-00-01Z" / "alpha_memo.md"
    ).read_text(encoding="utf-8")
    assert "## Research question" in memo
    assert "The bounded signal is disagreement" in memo
    assert "same measured business effect" not in memo


def test_business_candidate_memo_treats_percent_spread_as_disagreement(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    rows: list[dict[str, Any]] = []
    for i, value in enumerate([2.0, 44.4, 45.3, 65.0, 87.2], start=1):
        rows.append({
            "id": f"finance-replication-{i}",
            "topic": "asset_pricing_replication",
            "claim_type": "replication_failure_rate",
            "numeric_value": value,
            "units": "%",
            "canonical_phrase": (
                f"For factor premia returns, replication failure rate of {value}% "
                "under asset pricing replication screens."
            ),
            "population": "published cross sectional equity return predictors and factor premia",
            "intervention": "replication or multiple testing robustness screen",
            "comparator": "original anomaly evidence at conventional thresholds",
            "outcome": "predictor survival after replication screen",
            "metric": "replication failure rate",
            "study_design": "empirical asset pricing replication",
            "dataset": "published stock return anomaly libraries",
            "estimation_method": "asset pricing replication robustness screen",
            "identification_strategy": "empirical asset pricing replication",
            "paper": {
                "doi": f"10.7777/finance-replication-{i}",
                "title": "Asset pricing replication",
            },
        })
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(rows), encoding="utf-8")
    runs = tmp_path / "runs"
    monkeypatch.setattr(sys, "argv", [
        "build_business_alpha_candidate.py",
        "--domain", "finance_research",
        "--topic", "factor_premia_returns",
        "--facts-json", str(facts_path),
        "--runs-root", str(runs),
        "--snapshot-utc", "2026-06-09T00-00-02Z",
    ])

    assert business_cli.main() == 0
    memo = (
        runs / "factor_premia_returns-evidence-2026-06-09T00-00-02Z" / "alpha_memo.md"
    ).read_text(encoding="utf-8")
    assert "The bounded signal is disagreement" in memo
    assert "replication failure rate estimates" in memo
    assert "method-sensitive heterogeneity" in memo
    assert "same measured business effect" not in memo


def test_finance_return_bundle_accepts_repeated_signal_family() -> None:
    rows: list[dict[str, Any]] = []
    for i, population in enumerate((
        "equity portfolios",
        "mutual funds",
        "hedge funds",
        "stock portfolios",
        "factor portfolios",
    ), start=1):
        rows.append({
            "id": f"finance-return-{i}",
            "topic": "portfolio returns",
            "claim_type": "alpha_return",
            "numeric_value": 5 + i,
            "units": "%",
            "canonical_phrase": f"value spread portfolio earns alpha returns of {5 + i}%",
            "population": population,
            "intervention": "value spread",
            "comparator": "benchmark portfolio",
            "outcome": "risk adjusted returns",
            "metric": "alpha return",
            "study_design": "empirical asset pricing",
            "paper": {
                "doi": f"10.7777/finance-return-{i}",
                "title": "value spread and portfolio returns",
            },
        })

    bundle = build_candidate_bundle(
        rows,
        topic="portfolio_returns",
        domain="finance_research",
    )

    assert bundle is not None
    assert bundle.source_count == 5
    assert bundle.shape["signal_family"] == "return predictive signal"
    assert bundle.receipts[0]["signal_family_detail"] == "value spread"


def test_business_candidate_blocks_population_heterogeneity_false_disagreement() -> None:
    rows: list[dict[str, Any]] = []
    for i, (value, population) in enumerate([
        (0.0, "low wage workers"),
        (0.0, "low wage jobs"),
        (-0.15, "teen workers"),
        (-0.2, "teen workers"),
        (-0.1, "young workers"),
    ], start=1):
        rows.append({
            "id": f"mw-pop-{i}",
            "topic": "labor_economics",
            "claim_type": "effect_size",
            "numeric_value": value,
            "canonical_phrase": f"minimum wage employment elasticity estimate {value}",
            "population": population,
            "intervention": "minimum wage",
            "metric": "employment elasticity",
            "paper": {"doi": f"10.6666/mw-pop-{i}", "title": "Minimum wage employment"},
        })

    bundle = build_candidate_bundle(
        rows,
        topic="minimum_wage_employment",
        domain="economics_research",
    )

    assert bundle is None
    diagnostics = business_fact_diagnostics(
        rows,
        topic="minimum_wage_employment",
        domain="economics_research",
    )
    assert diagnostics["top_clusters"][0]["comparability_blockers"] == [
        "population_heterogeneity_explains_spread",
    ]


def test_business_candidate_blocks_outlier_driven_false_disagreement() -> None:
    rows: list[dict[str, Any]] = []
    for i, value in enumerate([0.0, -0.7, 0.0, -0.15, -0.2], start=1):
        rows.append({
            "id": f"mw-outlier-{i}",
            "topic": "labor_economics",
            "claim_type": "effect_size",
            "numeric_value": value,
            "canonical_phrase": f"minimum wage employment elasticity estimate {value}",
            "population": "low wage workers",
            "intervention": "minimum wage",
            "metric": "employment elasticity",
            "paper": {"doi": f"10.6666/mw-outlier-{i}", "title": "Minimum wage employment"},
        })

    bundle = build_candidate_bundle(
        rows,
        topic="minimum_wage_employment",
        domain="economics_research",
    )

    assert bundle is None
    diagnostics = business_fact_diagnostics(
        rows,
        topic="minimum_wage_employment",
        domain="economics_research",
    )
    assert diagnostics["top_clusters"][0]["comparability_blockers"] == [
        "outlier_requires_verification",
    ]


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
    # The real business domains are now ungated (audit #6), so the dry-run
    # submit guard is exercised against a synthetic dry-run profile — the guard
    # logic is config-independent (mirrors the live-profile injection below).
    base = load_domain_profile("management_research")
    dry_run_profile = DomainProfile(
        slug=base.slug,
        display_name=base.display_name,
        seed_topics_path=base.seed_topics_path,
        source_policy_path=base.source_policy_path,
        claim_schema_path=base.claim_schema_path,
        dry_run_only=True,
    )
    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: dry_run_profile)
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


def test_business_sweep_writes_domain_scoped_latest_summaries(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research", "marketing_research"))
    monkeypatch.setattr(
        sweep,
        "_seed_topics",
        lambda _path, *, limit: ["business_model_performance"],
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "ok"}))
    monkeypatch.setattr(
        sweep, "_strict_fullraw_probe",
        lambda _topic, **_kwargs: {"status": "not_configured"},
    )
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research,marketing_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-date", "2026-06-26T01-00-00Z",
    ])

    assert sweep.main() == 2
    captured = capsys.readouterr()
    assert "[business-sweep] no_bundle business_research business_model_performance" in captured.out
    assert "[business-sweep] no_bundle marketing_research business_model_performance" in captured.out
    assert "[business-sweep] domain=business_research summary=" in captured.out
    assert (
        '"top_blockers": {"candidate_refresh_failed": 1, '
        '"fullraw_not_configured": 1, "no_bundle": 1, "no_source_diverse_bundle": 1}'
    ) in captured.out
    assert "[business-sweep] no_ready_candidate" in captured.err

    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    business = json.loads(
        (diagnostics / "latest_sweep.business_research.json").read_text(encoding="utf-8"),
    )
    marketing = json.loads(
        (diagnostics / "latest_sweep.marketing_research.json").read_text(encoding="utf-8"),
    )
    aggregate = json.loads((diagnostics / "latest_sweep.json").read_text(encoding="utf-8"))
    assert {row["domain"] for row in aggregate["results"]} == {
        "business_research",
        "marketing_research",
    }
    assert {row["status"] for row in aggregate["results"]} == {"no_bundle"}
    assert business["domain"] == "business_research"
    assert {row["domain"] for row in business["results"]} == {"business_research"}
    assert marketing["domain"] == "marketing_research"
    assert {row["domain"] for row in marketing["results"]} == {"marketing_research"}
    business_queue = json.loads(
        (tmp_path / "runs" / "_publish_queue.business_research.json").read_text(
            encoding="utf-8",
        ),
    )
    marketing_queue = json.loads(
        (tmp_path / "runs" / "_publish_queue.marketing_research.json").read_text(
            encoding="utf-8",
        ),
    )
    assert business_queue["not_ready"][0]["domain_slug"] == "business_research"
    assert marketing_queue["not_ready"][0]["domain_slug"] == "marketing_research"
    assert business_queue["not_ready"][0]["queue_status"] == "no_source_diverse_bundle"
    assert marketing_queue["not_ready"][0]["queue_status"] == "no_source_diverse_bundle"
    business_summary = health.summarize_latest(
        tmp_path / "runs", domain="business_research",
    )
    assert business_summary["status"] == "candidate_refresh_failed"
    assert business_summary["reason"] == "no_source_diverse_bundle"
    assert business_summary["queue_counts"]["not_ready"] == 1
    assert business_summary["top_blockers"] == {
        "candidate_refresh_failed": 1,
        "fullraw_not_configured": 1,
        "no_bundle": 1,
        "no_source_diverse_bundle": 1,
    }
    assert (
        tmp_path / "runs" / "_daily_ledger"
        / "2026-06-26T01-00-00Z-business_research.json"
    ).exists()


def test_business_sweep_seed_topics_prioritize_bounded_before_broad(
    tmp_path: Path,
) -> None:
    seeds = tmp_path / "seeds.toml"
    seeds.write_text(
        """
[seeds]
topics = [
    "business_model_performance",
    "platform_strategy_network_effects",
    "supply_chain_resilience_performance",
    "pricing_strategy_margin",
]
""",
        encoding="utf-8",
    )

    assert sweep._seed_topics(seeds, limit=3) == [
        "platform_strategy_network_effects",
        "supply_chain_resilience_performance",
        "pricing_strategy_margin",
    ]


def test_business_sweep_prioritizes_diagnostic_source_signal(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "finance_research-empty_seed.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "retrieval_trace": {"fullraw": {"status": "failed"}},
    }), encoding="utf-8")
    (diagnostics / "finance_research-source_rich_seed.json").write_text(json.dumps({
        "raw_fact_count": 11,
        "a_core_fact_count": 7,
        "retrieval_trace": {"fullraw": {"status": "failed"}},
        "top_clusters": [{"source_count": 7}],
    }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "finance_research",
        ["empty_seed", "unknown_seed", "source_rich_seed"],
    ) == ["source_rich_seed", "unknown_seed", "empty_seed"]


def test_business_sweep_latest_and_queue_writes_are_locked(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    lock_calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        lock_calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    rows = [{
        "domain": "business_research",
        "topic": "pricing_strategy_margin",
        "status": "no_bundle",
        "reason": "no_source_diverse_bundle",
        "decision": "not_ready",
        "publish_tier": "TIER_3",
    }]

    sweep._write_sweep_summary(tmp_path / "runs", rows)

    exclusive = {
        name for name, op in lock_calls
        if op == fcntl.LOCK_EX
    }
    assert {
        "latest_sweep.json.lock",
        "latest_sweep.business_research.json.lock",
        "_publish_queue.business_research.json.lock",
    } <= exclusive


def test_business_no_bundle_diagnostic_blockers_reach_queue_and_ledger(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    diagnostics = runs / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    diagnostic_payload = {
        "domain": "business_research",
        "topic": "pricing_strategy_margin",
        "raw_fact_count": 5,
        "normalized_fact_count": 5,
        "a_core_fact_count": 5,
        "top_clusters": [{
            "comparability_blockers": [
                "metric_concept_mismatch",
                "signal_family_heterogeneity_explains_spread",
            ],
        }],
    }
    diagnostic_path = diagnostics / "business_research-pricing_strategy_margin.json"
    diagnostic_path.write_text(json.dumps(diagnostic_payload), encoding="utf-8")
    blockers = business_cli.no_bundle_blockers_from_diagnostics(diagnostic_payload)
    rows = [{
        "domain": "business_research",
        "topic": "pricing_strategy_margin",
        "status": "no_bundle",
        "diagnostics": str(diagnostic_path),
        "blockers": blockers,
    }]

    sweep._write_sweep_summary(runs, rows)
    queue_payload = json.loads(
        (runs / "_publish_queue.business_research.json").read_text(encoding="utf-8"),
    )
    assert queue_payload["not_ready"][0]["blockers"] == blockers

    sweep._write_no_ready_ledgers(runs, rows, "2026-06-26T02-00-00Z")
    summary = health.summarize_latest(runs, domain="business_research")
    assert summary["next_action"] == "inspect_refresh_failure"
    assert summary["top_blockers"] == {
        "candidate_refresh_failed": 1,
        "metric_concept_mismatch": 1,
        "no_bundle": 1,
        "no_source_diverse_bundle": 1,
        "signal_family_heterogeneity_explains_spread": 1,
    }


def test_business_sweep_surfaces_incomplete_fullraw_receipt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: ["pricing_strategy_margin"])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "incomplete_receipt",
        "paper_count": 0,
        "shards_searched": 346,
        "partial_shard_search": True,
        "sweep_failed_shards": 0,
        "sources_searched": {"openalex": 300, "pubmed": 12, "crossref": 8, "core": 3, "semantic_scholar": 2},
    })
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-date", "2026-06-26T03-00-00Z",
    ])

    assert sweep.main() == 2
    diagnostic = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "business_research-pricing_strategy_margin.json").read_text(
            encoding="utf-8",
        ),
    )
    assert diagnostic["retrieval_trace"]["fullraw"]["partial_shard_search"] is True
    queue_payload = json.loads(
        (tmp_path / "runs" / "_publish_queue.business_research.json").read_text(
            encoding="utf-8",
        ),
    )
    assert "fullraw_probe_busy" in queue_payload["not_ready"][0]["blockers"]
    summary = health.summarize_latest(tmp_path / "runs", domain="business_research")
    assert summary["next_action"] == "wait_for_fullraw_completion"
    assert summary["top_blockers"]["fullraw_probe_busy"] == 1


def test_business_sweep_writes_no_ready_summary_before_next_probe_failure(
    tmp_path: Path, monkeypatch: Any, capsys: Any,
) -> None:
    calls = 0
    monkeypatch.setattr(
        sweep, "_DOMAINS", ("business_research", "management_research"),
    )
    monkeypatch.setattr(
        sweep, "_seed_topics", lambda _path, *, limit: ["platform_strategy_network_effects"],
    )
    monkeypatch.setattr(
        sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )

    def probe(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("later probe failed")
        return {"status": "failed", "error": "TimeoutError"}

    monkeypatch.setattr(sweep, "_strict_fullraw_probe", probe)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research,management_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-date", "2026-06-26T03-30-00Z",
    ])

    with suppress(RuntimeError):
        sweep.main()

    out = capsys.readouterr().out
    assert "[business-sweep] domain=business_research summary=" in out
    summary = health.summarize_latest(tmp_path / "runs", domain="business_research")
    assert summary["status"] == "candidate_refresh_failed"
    assert summary["considered_counts"] == {"no_bundle": 1}
    assert summary["published"] == 0


def test_business_sweep_fullraw_probe_does_not_inherit_storage_budget(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    captured: dict[str, str | None] = {}
    for key in (
        "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS",
        "TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS",
        "TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS",
        "TOPIC_DISCOVERY_FULLRAW_PRIORITY",
        "TOPIC_DISCOVERY_V5_MAX_VARIANTS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", "7200")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS", "999")
    discovery._FULLRAW_PROBE_EVENTS.clear()

    def fake_seed_fullraw(topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        client_timeout = _kwargs["client"].timeout
        captured.update({
            "client_timeout": str(client_timeout.read),
            "timeout": os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            "attempts": os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"),
            "priority": os.environ.get("TOPIC_DISCOVERY_FULLRAW_PRIORITY"),
            "poll_seconds": os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS"),
            "foreground_budget": os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
            "variants": os.environ.get("TOPIC_DISCOVERY_V5_MAX_VARIANTS"),
            "storage_budget": os.environ.get("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"),
        })
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 48,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "queued"}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": topic,
            "status": "incomplete_receipt",
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("portfolio_returns")

    assert result["status"] == "incomplete_receipt"
    assert captured == {
        "client_timeout": "30.0",
        "timeout": None,
        "attempts": "15",
        "priority": None,
        "poll_seconds": None,
        "foreground_budget": "30",
        "variants": None,
        "storage_budget": "7200",
    }
    assert os.environ["TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"] == "999"
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_PRIORITY") is None
    assert os.environ["TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"] == "7200"


def test_business_sweep_fullraw_probe_preserves_in_progress_cache_receipt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    discovery._FULLRAW_PROBE_EVENTS.clear()

    def fake_seed_fullraw(topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": topic,
            "status": "in_progress_cache_hit",
            "async_status": "queued",
            "partial_shard_search": True,
            "shards_searched": 192,
            "sweep_failed_shards": 0,
            "sources_searched": {"openalex": 59, "pubmed": 58},
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("platform_strategy_network")

    assert result["status"] == "in_progress_cache_hit"
    assert result["async_status"] == "queued"
    assert result["partial_shard_search"] is True
    assert result["shards_searched"] == 192
    assert result["sweep_failed_shards"] == 0
    assert result["sources_searched"] == {"openalex": 59, "pubmed": 58}
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": result},
    }) == ["no_source_diverse_bundle", "fullraw_probe_busy"]


def test_business_sweep_fullraw_probe_tries_compact_alpha_query(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[str] = []
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS", "replication")

    complete_receipt = {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "source_count_searched": 5,
    }

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = dict(complete_receipt)
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        if query.endswith("replication"):
            return [
                {"paper_id": f"paper-{idx}", "title": f"{query} source {idx}"}
                for idx in range(5)
            ]
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "platform_strategy_network_effects",
        include_papers=True,
    )

    assert calls == [
        "platform strategy network",
        "platform strategy network replication",
    ]
    assert result["status"] == "complete"
    assert result["paper_count"] == 5
    assert result["query"] == "platform strategy network replication"
    assert len(result["_papers"]) == 5


def test_business_fullraw_queries_are_compact_deduped_and_alpha_shaped(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS",
        "replication,primary endpoint",
    )

    queries = sweep._business_fullraw_queries("pricing_strategy_margin_effects")

    assert queries[:3] == (
        "pricing strategy margin",
        "pricing strategy margin replication",
        "pricing strategy margin primary endpoint",
    )
    assert all("effects" not in query for query in queries)
    assert all(len(query.split()) <= 5 for query in queries)
    assert len(queries) == len({
        " ".join(sorted(set(query.split())))
        for query in queries
    })


def test_business_sweep_fullraw_probe_does_not_dogpile_busy_worker(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    lock_path = tmp_path / "fullraw.lock"
    lock_path.touch()
    handle = lock_path.open("a", encoding="utf-8")
    fcntl.flock(handle, fcntl.LOCK_EX)
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH", str(lock_path))
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")

    try:
        result = sweep._strict_fullraw_probe("pricing_strategy_margin")
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()

    assert result == {"status": "busy"}
    assert os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS") is None


def test_business_sweep_fullraw_probe_has_hard_timeout(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import scripts.run_topic_discovery as discovery

    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_FOREGROUND_SECONDS", "5")

    def fake_seed_fullraw(_topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        signal_mod.raise_signal(signal_mod.SIGALRM)
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("pricing_strategy_margin")

    assert result == {"status": "failed", "error": "TimeoutError"}
    assert os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS") is None


def test_business_sweep_continues_after_busy_fullraw_probe(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("management_research")
    probed_topics: list[str] = []

    def fake_fetch(topic: str, *_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if topic == "management_practices_productivity":
            return _fixture_facts(), {"status": "ok"}
        return [], {"status": "ok"}

    def fake_probe(topic: str, **_kwargs: Any) -> dict[str, Any]:
        probed_topics.append(topic)
        return {"status": "busy"}

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "business_model_performance",
        "management_practices_productivity",
    ])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_probe)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "2",
        "--topics-per-domain", "2",
        "--domains", "management_research",
        "--runs-root", str(tmp_path / "runs"),
    ])

    assert sweep.main() == 0
    assert probed_topics == ["business_model_performance"]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    assert [row["status"] for row in summary["results"]] == ["no_bundle", "ready"]
    assert summary["results"][0]["blockers"] == [
        "no_source_diverse_bundle",
        "fullraw_probe_busy",
    ]


def test_business_sweep_continues_after_failed_fullraw_probe(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("management_research")
    probed_topics: list[str] = []

    def fake_fetch(topic: str, *_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if topic == "management_practices_productivity":
            return _fixture_facts(), {"status": "ok"}
        return [], {"status": "failed", "http_status": 503}

    def fake_probe(topic: str, **_kwargs: Any) -> dict[str, Any]:
        probed_topics.append(topic)
        return {"status": "failed", "error": "TimeoutError"}

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "platform_strategy_network_effects",
        "management_practices_productivity",
    ])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_probe)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--domains", "management_research",
        "--runs-root", str(tmp_path / "runs"),
    ])

    assert sweep.main() == 0
    assert probed_topics == ["platform_strategy_network_effects"]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    assert [row["status"] for row in summary["results"]] == ["no_bundle", "ready"]
    assert summary["results"][0]["blockers"] == [
        "no_source_diverse_bundle",
        "fullraw_complete_receipt_missing",
    ]


def test_business_sweep_uses_diagnostics_to_skip_known_empty_seed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("finance_research")
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "finance_research-empty_seed.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "retrieval_trace": {"fullraw": {"status": "failed"}},
    }), encoding="utf-8")
    (diagnostics / "finance_research-source_rich_seed.json").write_text(json.dumps({
        "raw_fact_count": 9,
        "a_core_fact_count": 7,
        "top_clusters": [{"source_count": 6}],
    }), encoding="utf-8")
    fetched_topics: list[str] = []

    def fake_bundle(_facts: list[dict[str, Any]], *, topic: str, domain: str) -> Any:
        return SimpleNamespace(
            domain=domain, topic=topic, result_key="ready",
            receipts=({"fact_id": topic},), source_count=5,
        )

    def fake_write_candidate_run(bundle: Any, **kwargs: Any) -> Path:
        run_dir = cast(Path, kwargs["runs_root"]) / f"{bundle.topic}-evidence-test"
        run_dir.mkdir(parents=True)
        return run_dir

    def fake_fetch(topic: str, *_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
        fetched_topics.append(topic)
        return _fixture_facts(), {"status": "ok"}

    monkeypatch.setattr(sweep, "_DOMAINS", ("finance_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "empty_seed",
        "unknown_seed",
        "source_rich_seed",
        "other_seed",
    ][:limit])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "build_candidate_bundle", fake_bundle)
    monkeypatch.setattr(sweep, "write_candidate_run", fake_write_candidate_run)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "finance_research",
        "--runs-root", str(tmp_path / "runs"),
    ])

    assert sweep.main() == 0
    assert fetched_topics == ["source_rich_seed"]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    assert summary["results"][0]["topic"] == "source_rich_seed"


def test_business_sweep_deprioritizes_no_receipt_fullraw_seeds(tmp_path: Path) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    for topic, status in (
        ("no_receipt_seed", "no_hits"),
        ("partial_receipt_seed", "incomplete_receipt"),
    ):
        (diagnostics / f"business_research-{topic}.json").write_text(json.dumps({
            "raw_fact_count": 0,
            "a_core_fact_count": 0,
            "retrieval_trace": {"fullraw": {"status": status}},
        }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "business_research",
        ["no_receipt_seed", "partial_receipt_seed", "untried_seed"],
    ) == ["untried_seed", "no_receipt_seed", "partial_receipt_seed"]


def test_business_sweep_retries_queued_fullraw_before_new_variants(tmp_path: Path) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "business_research-queued_seed.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "retrieval_trace": {
            "fullraw": {
                "status": "incomplete_receipt",
                "async_status": "queued",
            },
        },
    }), encoding="utf-8")
    (diagnostics / "business_research-dead_seed.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "retrieval_trace": {"fullraw": {"status": "no_hits"}},
    }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "business_research",
        ["dead_seed", "queued_seed", "untried_seed"],
    ) == ["queued_seed", "untried_seed", "dead_seed"]


def test_business_seed_topics_include_trimmed_variants_without_biomed_suffixes(
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "seeds.toml"
    seed_path.write_text(
        '[seeds]\ntopics = ["platform_strategy_network_effects"]\n',
        encoding="utf-8",
    )

    topics = sweep._seed_topics(seed_path, limit=8)

    assert topics[:3] == [
        "platform_strategy_network_effects",
        "platform_strategy_network",
        "platform_strategy",
    ]
    assert "platform_strategy_therapy" not in topics


def test_business_seed_pool_rotates_beyond_first_exhausted_window(tmp_path: Path) -> None:
    seed_path = tmp_path / "seeds.toml"
    seed_path.write_text(
        """
[seeds]
topics = [
    "platform_strategy_network_effects",
    "supply_chain_resilience_performance",
    "pricing_strategy_margin",
    "operations_process_improvement",
    "digital_transformation_firm_performance",
    "business_model_performance",
]
""",
        encoding="utf-8",
    )
    topics = sweep._seed_topics(seed_path, limit=16)
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    for topic in topics[:8]:
        (diagnostics / f"business_research-{topic}.json").write_text(json.dumps({
            "raw_fact_count": 0,
            "a_core_fact_count": 0,
            "retrieval_trace": {"fullraw": {"status": "no_hits"}},
        }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs", "business_research", topics,
    )[0] == topics[8]


def test_business_sweep_continues_after_running_fullraw_probe(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("management_research")
    probed_topics: list[str] = []

    def fake_probe(topic: str, **_kwargs: Any) -> dict[str, Any]:
        probed_topics.append(topic)
        return {
            "status": "incomplete_receipt",
            "async_status": "running",
            "shards_searched": 231,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "platform_strategy_network_effects",
        "management_practices_productivity",
    ])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [], {"status": "failed"},
    ))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_probe)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--domains", "management_research",
        "--runs-root", str(tmp_path / "runs"),
    ])

    assert sweep.main() == 2
    assert probed_topics == [
        "platform_strategy_network_effects",
        "management_practices_productivity",
    ]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    assert len(summary["results"]) == 2
    assert all(row["blockers"] == [
        "no_source_diverse_bundle",
        "fullraw_probe_busy",
    ] for row in summary["results"])


def test_business_no_bundle_complete_fullraw_requires_fact_synthesis() -> None:
    blockers = business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {
            "fullraw": {
                "status": "complete",
                "paper_count": 8,
                "shards_searched": 1525,
                "partial_shard_search": False,
                "sweep_failed_shards": 0,
            },
        },
        "top_clusters": [],
    })

    assert blockers == [
        "no_source_diverse_bundle",
        "requires_fact_level_source_synthesis",
    ]
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "complete", "paper_count": 3}},
    }) == ["no_source_diverse_bundle", "fullraw_insufficient_papers"]
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "complete_no_hits", "paper_count": 0}},
    }) == ["no_source_diverse_bundle", "fullraw_no_hits"]
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "busy"}},
    }) == ["no_source_diverse_bundle", "fullraw_probe_busy"]


def test_business_sweep_complete_fullraw_hands_off_to_source_literature(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    profile = load_domain_profile("economics_research")
    submissions: list[dict[str, Any]] = []
    papers = [
        {
            "title": f"Minimum wage employment evidence paper {i}",
            "doi": f"10.9999/fullraw-{i}",
            "abstract": "Minimum wage and employment evidence.",
        }
        for i in range(5)
    ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {
            "status": "published",
            "submitted": 1,
            "published": 1,
            "publish_summary": {
                "status": "published",
                "submitted": 1,
                "published": 1,
                "considered": 1,
                "queue_counts": {"ready_to_publish": 1},
                "top_blockers": {},
                "next_action": "public_page_verified",
                "public_url": "https://example.test/memo",
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("economics_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: ["minimum_wage_employment"])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "complete",
        "paper_count": 5,
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "sources_searched": {
            "openalex": 2,
            "pubmed": 1,
            "crossref": 1,
            "core": 1,
            "semantic_scholar": 1,
        },
        "_papers": papers,
    })
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "2",
        "--topics-per-domain", "1",
        "--domains", "economics_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "2",
        "--submit-date", "2026-06-27T01-00-00Z",
    ])

    assert sweep.main() == 0
    discovery = json.loads(
        (
            tmp_path / "runs" / "_topics_discovery"
            / "business_sweep_fullraw.economics_research.minimum_wage_employment.json"
        ).read_text(encoding="utf-8"),
    )
    assert discovery["source"] == "business_sweep_fullraw"
    assert discovery["all"][0]["paper_count"] == 5
    assert discovery["all"][0]["fact_source_count"] == 5
    assert len(discovery["all"][0]["source_papers"]) == 5
    assert submissions == [{
        "runs_root": tmp_path / "runs",
        "date": "2026-06-27T01-00-00Z",
        "domain": "economics_research",
        "submit": True,
        "refresh_candidates": True,
    }]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    assert [row["status"] for row in summary["results"]] == [
        "source_literature_waiting_consistency",
        "published",
    ]
    out = capsys.readouterr().out
    assert "source_literature_waiting_consistency" in out
    assert "via_fullraw_source_literature" in out
    assert '"public_url_status": 200' in out


def test_business_sweep_submits_after_consistent_non_dry_run_passes(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
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

    def fake_fetch(*_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
        nonlocal fetch_calls
        fetch_calls += 1
        facts = _fixture_facts()
        return (list(reversed(facts)) if fetch_calls == 2 else facts), {"status": "ok"}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "considered": 1,
                "queue_counts": {"ready_to_publish": 1},
                "top_blockers": {"submitted_to_researka": 1},
                "next_action": "watch_decision_or_public_page",
                "public_url": None,
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: live_profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: ["management_practices_productivity"])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "2",
        "--topics-per-domain", "1",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "2",
    ])

    assert sweep.main() == 0
    assert len(submissions) == 1
    assert submissions[0]["domain"] == "management_research"
    assert submissions[0]["submit"] is True
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        )
    )
    assert [row["status"] for row in summary["results"]] == [
        "ready_waiting_consistency",
        "submitted_to_researka",
    ]
    out = capsys.readouterr().out
    assert "[business-sweep] domain=management_research summary=" in out
    assert '"public_url_status": null' in out
    assert '"top_blockers": {"submitted_to_researka": 1}' in out


def test_business_sweep_consistency_persists_between_invocations(
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
    runs_root = tmp_path / "runs"

    def fake_fetch(*_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
        return _fixture_facts(), {"status": "ok"}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {"status": "submitted_to_researka", "submitted": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: live_profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: ["management_practices_productivity"])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    argv = [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "2",
    ]

    monkeypatch.setattr(sys, "argv", argv)
    assert sweep.main() == 2
    assert submissions == []

    monkeypatch.setattr(sys, "argv", argv)
    assert sweep.main() == 0
    assert len(submissions) == 1
    consistency = json.loads(
        (runs_root / "_business_diagnostics" / "ready_consistency.management_research.json").read_text(
            encoding="utf-8",
        )
    )
    assert consistency[0]["passes"] == 2


def test_business_sweep_continues_after_no_fresh_candidate(
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

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        if len(submissions) == 1:
            return {"status": "no_fresh_candidate", "published": 0}
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    def fake_bundle(
        _facts: list[dict[str, Any]], *, topic: str, domain: str,
    ) -> Any:
        return SimpleNamespace(
            domain=domain, topic=topic, result_key="ready",
            receipts=({"fact_id": topic},), source_count=5,
        )

    def fake_write_candidate_run(bundle: Any, **kwargs: Any) -> Path:
        runs_root = cast(Path, kwargs["runs_root"])
        run_dir = runs_root / f"{bundle.topic}-evidence-test"
        run_dir.mkdir(parents=True)
        return run_dir

    monkeypatch.setattr(sweep, "_DOMAINS", ("management_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: live_profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "management_practices_productivity",
        "employee_engagement_turnover",
    ])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_a, **_k: (_fixture_facts(), {"status": "ok"}))
    monkeypatch.setattr(sweep, "build_candidate_bundle", fake_bundle)
    monkeypatch.setattr(sweep, "write_candidate_run", fake_write_candidate_run)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
    ])

    assert sweep.main() == 0
    assert [call["domain"] for call in submissions] == [
        "management_research",
        "management_research",
    ]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        )
    )
    assert [row["status"] for row in summary["results"]] == [
        "no_fresh_candidate",
        "submitted_to_researka",
    ]


def test_daily_cycle_preserves_stored_business_candidate_verdict(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("management_research")
    bundle = build_candidate_bundle(
        _fixture_facts(),
        topic="management_practices_productivity",
        domain="management_research",
    )
    assert bundle is not None
    runs_root = tmp_path / "runs"
    write_candidate_run(bundle, profile=profile, runs_root=runs_root)

    def fail_recompute(_run_dir: Path) -> dict[str, Any]:
        return {
            "topic": "management_practices_productivity",
            "decision": "agent_repair_needed",
            "publish_tier": "TIER_2",
            "blockers": ["receipt_shape_mismatch"],
        }

    monkeypatch.setattr(cycle, "publish_verdict", fail_recompute)

    queue_payload = cycle._build_queue(
        runs_root, include_archive=False, domain="management_research",
    )

    assert [row["topic"] for row in queue_payload["ready_to_publish"]] == [
        "management_practices_productivity",
    ]
    assert queue_payload["agent_repair_needed"] == []


def test_business_systemd_timers_are_eight_hour_guarded() -> None:
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
        assert "scripts/run_business_alpha_sweep.py" in service
        assert "scripts/daily_alpha_publish_cycle.py" not in service
        assert f"--domains {domain}" in service
        assert "--submit-after-consistent-passes 2" in service
        assert "--cycles 1" in service
        assert "--topics-per-domain 2" in service
        assert "SuccessExitStatus=3" not in service
        assert "EnvironmentFile=/etc/researka-agent-v4.env" in service
        assert "EnvironmentFile=/root/Research-Agent-Bot-v4/.env" in service
        assert f"OnCalendar=*-*-* {schedule}" in timer
