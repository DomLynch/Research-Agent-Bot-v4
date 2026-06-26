from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path
from typing import Any

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
        settings=_Settings(),  # type: ignore[arg-type]
    )

    assert [row["id"] for row in rows] == ["finance-1"]
    assert calls[0]["domain"] == "econ_business"
    assert "domain" not in calls[1]
    assert len(calls) == 2
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
        '"no_bundle": 1, "no_source_diverse_bundle": 1}'
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
        "no_bundle": 1,
        "no_source_diverse_bundle": 1,
    }
    assert (
        tmp_path / "runs" / "_daily_ledger"
        / "2026-06-26T01-00-00Z-business_research.json"
    ).exists()


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

    def fake_fetch(*_args: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
        nonlocal fetch_calls
        fetch_calls += 1
        facts = _fixture_facts()
        return (list(reversed(facts)) if fetch_calls == 2 else facts), {"status": "ok"}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {"status": "submitted_to_researka", "submitted": 1}

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
        if name in {"business", "management", "finance", "marketing"}:
            assert "--topics-per-domain 6" in service
        assert "SuccessExitStatus=3" not in service
        assert "EnvironmentFile=/etc/researka-agent-v4.env" in service
        assert "EnvironmentFile=/root/Research-Agent-Bot-v4/.env" in service
        assert f"OnCalendar=*-*-* {schedule}" in timer
