from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import signal as signal_mod
import sys
import urllib.request
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
from scripts import alpha_publish_literature as publish_literature


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


def test_business_fact_infers_study_design_from_source_topic() -> None:
    fact = normalize_business_fact(
        {
            "id": "field-exp-1",
            "topic": "field_experiment_rct",
            "claim_type": "effect_size",
            "numeric_value": 13.21,
            "units": "%",
            "canonical_phrase": (
                "Social nudges boosted video supply by 13.21% without changing quality."
            ),
            "population": "video content providers",
            "intervention": "social nudges",
            "comparator": "control providers",
            "metric": "video supply",
            "paper": {
                "doi": "10.1287/mnsc.2022.4622",
                "title": "The Impact of Social Nudges on User-Generated Content",
                "journal_name": "Management Science",
                "publication_year": 2022,
            },
        },
        topic="platform_strategy_network_effects",
        domain="business_research",
    )

    assert fact["study_design"] == "randomized controlled trial"


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
    assert calls[0]["numeric_only"] is True
    assert "domain" not in calls[1]
    assert calls[1]["numeric_only"] is True
    assert len(calls) == 2
    assert timeouts == [90.0, 90.0]
    assert trace["status"] == "fallback_filtered"
    assert trace["http_status"] == 200
    assert trace["domain_http_status"] == 422
    assert trace["fallback_unfiltered_facts"] == 2
    assert trace["facts"] == 1
    assert trace["domain_filter_used"] is False


def test_fetch_business_facts_can_include_directional_source_literature(
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
        calls.append(json)
        return httpx.Response(
            200,
            json=[{
                "id": "directional-1",
                "topic": "platform strategy network profitability",
                "claim_type": "directional_receipt",
                "canonical_phrase": (
                    "Platform strategy network effects improved firm profitability."
                ),
                "population": "firms",
                "intervention": "platform strategy network effects",
                "outcome": "firm profitability",
                "metric": "firm profitability",
                "paper": {
                    "doi": "10.6161/platform-directional",
                    "title": "Platform strategy network effects and firm profitability",
                    "journal_name": "Strategy Evidence Letters",
                },
            }],
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("agent.business_research.httpx.post", fake_post)

    rows, _trace = fetch_business_facts(
        "platform_strategy_network_profitability",
        domain="business_research",
        settings=cast(Any, _Settings()),
        numeric_only=False,
    )

    assert len(rows) == 1
    assert calls[0]["numeric_only"] is False


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
    assert "[business-sweep] end_summary=" in captured.out
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
    assert {row["domain_slug"] for row in aggregate["results"]} == {
        "business_research",
        "marketing_research",
    }
    assert business["domain"] == "business_research"
    assert {row["domain"] for row in business["results"]} == {"business_research"}
    assert {row["domain_slug"] for row in business["results"]} == {"business_research"}
    assert marketing["domain"] == "marketing_research"
    assert {row["domain"] for row in marketing["results"]} == {"marketing_research"}
    assert {row["domain_slug"] for row in marketing["results"]} == {"marketing_research"}
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
    artifact = tmp_path / "runs" / "_daily_ledger" / "business_alpha_sweep_summary.json"
    sweep_summary = json.loads(artifact.read_text(encoding="utf-8"))
    assert sweep_summary["summary_artifact"] == str(artifact)
    assert sweep_summary["candidates_considered"] == 2
    assert sweep_summary["queue_counts"] == {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 2,
    }
    assert sweep_summary["top_blockers"] == {
        "fullraw_not_configured": 2,
        "no_bundle": 2,
        "no_source_diverse_bundle": 2,
        "candidate_refresh_failed": 1,
    }
    assert sweep_summary["next_action"] == "inspect_refresh_failure"
    assert sweep_summary["public_url_status"] == {
        "business_research": None,
        "marketing_research": None,
    }
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


def test_business_sweep_fullraw_probe_inherits_fullraw_search_budget(
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
        "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_ENV_FILE", str(tmp_path / "missing-fullraw.env"))
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
            "limit": str(_kwargs.get("limit")),
            "timeout": os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            "attempts": os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"),
            "priority": os.environ.get("TOPIC_DISCOVERY_FULLRAW_PRIORITY"),
            "poll_seconds": os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS"),
            "foreground_budget": os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
            "sweep_wait": os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"),
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
        "client_timeout": "7200.0",
        "limit": "10",
        "timeout": "7200.0",
        "attempts": "4",
        "priority": "1",
        "poll_seconds": "15",
        "foreground_budget": "7200",
        "sweep_wait": "7200.0",
        "variants": None,
        "storage_budget": "7200",
    }
    assert os.environ["TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"] == "999"
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_PRIORITY") is None
    assert os.environ["TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"] == "7200"


def test_business_fullraw_result_limit_is_bounded_and_configurable(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("BUSINESS_SWEEP_FULLRAW_RESULT_LIMIT", raising=False)
    assert sweep._business_fullraw_result_limit() == 10

    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_RESULT_LIMIT", "3")
    assert sweep._business_fullraw_result_limit() == 5

    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_RESULT_LIMIT", "24")
    assert sweep._business_fullraw_result_limit() == 24

    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_RESULT_LIMIT", "bad")
    assert sweep._business_fullraw_result_limit() == 10


def test_business_sweep_fullraw_probe_priority_can_be_disabled(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    captured: dict[str, str | None] = {}
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_PRIORITY", "0")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(_topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        captured["priority"] = os.environ.get("TOPIC_DISCOVERY_FULLRAW_PRIORITY")
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 64,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "queued"}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": _topic,
            "status": "incomplete_receipt",
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("portfolio_returns")

    assert result["status"] == "incomplete_receipt"
    assert captured == {"priority": None}
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_PRIORITY") is None


def test_business_sweep_fullraw_probe_defaults_to_strict_sweep_budget(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    captured: dict[str, str | None] = {}
    for key in (
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_FOREGROUND_SECONDS",
        "TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS",
        "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS",
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS",
        "RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_ENV_FILE", str(tmp_path / "missing-fullraw.env"))
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(_topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        captured.update({
            "client_timeout": str(_kwargs["client"].timeout.read),
            "timeout": os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            "attempts": os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"),
            "foreground_budget": os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
        })
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 64,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "queued"}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": _topic,
            "status": "incomplete_receipt",
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("portfolio_returns")

    assert result["status"] == "incomplete_receipt"
    assert captured == {
        "client_timeout": "2400.0",
        "timeout": "2400.0",
        "attempts": "4",
        "foreground_budget": "2400",
    }
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS") is None
    assert os.environ.get("TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS") is None
    assert os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS") is None


def test_business_sweep_fullraw_probe_overrides_stale_short_timeout(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    captured: dict[str, str | None] = {}
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_ENV_FILE", str(tmp_path / "missing-fullraw.env"))
    monkeypatch.delenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_FOREGROUND_SWEEP_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_SWEEP_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS", "20")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(_topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        captured.update({
            "client_timeout": str(_kwargs["client"].timeout.read),
            "timeout": os.environ.get("TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"),
            "foreground_budget": os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"),
            "sweep_wait": os.environ.get("TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"),
        })
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 64,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "queued"}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": _topic,
            "status": "incomplete_receipt",
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("platform_strategy_network")

    assert result["status"] == "incomplete_receipt"
    assert captured == {
        "client_timeout": "2400.0",
        "timeout": "2400.0",
        "foreground_budget": "2400",
        "sweep_wait": "2400.0",
    }
    assert os.environ["TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"] == "20"
    assert os.environ["TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"] == "20"


def test_business_sweep_fullraw_probe_uses_strict_floor_over_generic_budget(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_FOREGROUND_SECONDS", raising=False)
    monkeypatch.delenv("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS", "900")

    assert sweep._business_fullraw_foreground_seconds() == "2400"


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
            "papers_searched": 313447963,
            "papers_total": 1456919317,
            "result_count_returned": 10,
            "result_count_unique": 17,
            "result_citation_diversity": 3,
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
    assert result["papers_searched"] == 313447963
    assert result["papers_total"] == 1456919317
    assert result["result_count_returned"] == 10
    assert result["result_count_unique"] == 17
    assert result["result_citation_diversity"] == 3
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": result},
    }) == ["no_source_diverse_bundle", "fullraw_probe_busy"]


def test_business_sweep_priority_probe_tries_next_query_after_quick_incomplete_fullraw(
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
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("business model performance", "firm performance empirical"),
    )
    discovery._FULLRAW_PROBE_EVENTS.clear()

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if len(calls) == 1:
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
                "shards_searched": 288,
                "partial_shard_search": True,
                "sweep_failed_shards": 0,
                "source_count_searched": 4,
            }
            topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "queued"}
            discovery._FULLRAW_PROBE_EVENTS.append({
                "query": query,
                "status": "incomplete_receipt",
                "async_status": "queued",
                "partial_shard_search": True,
                "shards_searched": 288,
            })
            return []
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "complete",
            "partial_shard_search": False,
            "shards_searched": 1525,
        })
        return [
            {
                "paper_id": f"paper-{idx}",
                "title": f"{query} source {idx}",
                "source_fact": {
                    "canonical_phrase": f"{query} changes firm performance {idx}.",
                    "population": "firms",
                    "intervention": query,
                    "endpoint": "firm performance",
                },
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "business_model_performance", runs_root=tmp_path / "runs",
    )

    assert result["status"] == "complete"
    assert result["query"] == "firm performance empirical"
    assert result["attempted_queries"] == [
        "business model performance",
        "firm performance empirical",
    ]
    assert result["paper_count"] == 5
    assert result["candidate_fact_source_count"] == 5
    assert calls == ["business model performance", "firm performance empirical"]


def test_business_sweep_fullraw_probe_preserves_in_progress_event_over_no_hits(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("business model performance",),
    )
    discovery._FULLRAW_PROBE_EVENTS.clear()

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "in_progress_poll_due",
            "async_status": "queued",
            "partial_shard_search": True,
            "shards_searched": 288,
            "paper_count": 0,
        })
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "no_hits",
            "paper_count": 0,
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "business_model_performance", runs_root=tmp_path / "runs",
    )

    assert result["status"] == "in_progress_poll_due"
    assert result["async_status"] == "queued"
    assert result["partial_shard_search"] is True
    assert result["shards_searched"] == 288


def test_business_sweep_fullraw_probe_backoff_is_topic_scoped(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[str] = []
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_PRIORITY", "0")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        if len(calls) == 1:
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
                "shards_searched": 231,
                "partial_shard_search": True,
                "sweep_failed_shards": 0,
            }
            topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "running"}
            status = "incomplete_receipt"
            async_status = "running"
            partial = True
            papers: list[dict[str, Any]] = []
        else:
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
                "shards_searched": 1525,
                "partial_shard_search": False,
                "sweep_failed_shards": 0,
                "source_count_searched": 5,
            }
            topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
            status = "complete"
            async_status = None
            partial = False
            # This test is about topic-scoped backoff, not source quality.
            # Under the live contract, title-only completions are source-poor
            # and correctly fall through to the next compact query.
            papers = [
                {
                    "paper_id": f"paper-{idx}",
                    "title": f"{query} source {idx}",
                    "source_fact": {
                        "canonical_phrase": f"{query} changes firm performance {idx}.",
                        "population": "firms",
                        "intervention": query,
                        "endpoint": "firm performance",
                    },
                }
                for idx in range(5)
            ]
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": status,
            "async_status": async_status,
            "partial_shard_search": partial,
            "shards_searched": topic_discovery_mod._FULLRAW_LAST_RECEIPT["shards_searched"],
        })
        return papers

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    first = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )
    same_topic = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )
    different_topic = sweep._strict_fullraw_probe(
        "pricing_strategy_margin", runs_root=tmp_path / "runs",
    )

    assert first["status"] == "incomplete_receipt"
    assert same_topic["status"] == "busy"
    assert same_topic["reason"] == "fullraw_backoff"
    assert same_topic["previous_status"] == "incomplete_receipt"
    assert different_topic["status"] == "complete"
    assert different_topic["paper_count"] == 5
    assert calls == ["platform strategy network performance", "pricing strategy margin"]


def test_business_sweep_priority_probe_honors_fresh_fullraw_backoff(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[str] = []
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_PRIORITY", "1")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 311,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {"status": "running"}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "incomplete_receipt",
            "async_status": "running",
            "partial_shard_search": True,
            "shards_searched": 311,
        })
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    first = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )
    same_topic = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )

    assert first["status"] == "incomplete_receipt"
    assert same_topic["status"] == "busy"
    assert same_topic["reason"] == "fullraw_backoff"
    assert same_topic["previous_status"] == "incomplete_receipt"
    assert calls == ["platform strategy network performance"]


def test_business_sweep_priority_probe_bypasses_stale_fullraw_backoff(
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

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "complete",
        })
        # This test isolates priority/backoff behaviour. Use source-fact
        # papers so the adaptive source-quality fallback is not the subject.
        return [
            {
                "paper_id": f"paper-{idx}",
                "title": f"{query} source {idx}",
                "source_fact": {
                    "canonical_phrase": f"{query} changes firm performance {idx}.",
                    "population": "firms",
                    "intervention": query,
                    "endpoint": "firm performance",
                },
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    first = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )
    same_topic = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )

    assert first["status"] == "complete"
    assert same_topic["status"] == "complete"
    assert calls == [
        "platform strategy network performance",
        "platform strategy network performance",
    ]


def test_business_sweep_priority_probe_checks_exact_key_when_queue_is_full(
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
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS", "0")
    topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
    topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
    discovery._FULLRAW_PROBE_EVENTS.clear()
    monkeypatch.setattr(discovery, "_cached_fullraw_in_progress", lambda _cache_key: None)

    monkeypatch.setattr(
        discovery,
        "_fullraw_queue_saturated",
        lambda **_kwargs: {
            "status": "inflight_saturated",
            "inflight_count": 2,
            "max_inflight": 2,
        },
    )

    def fake_fetch_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1453,
            "shards_total": 1525,
            "partial_shard_search": True,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {
            "status": "running",
            "key_running": True,
            "queued_count": 1,
            "inflight_count": 2,
        }
        return []

    monkeypatch.setattr(discovery, "_fetch_fullraw_topic_papers", fake_fetch_fullraw)

    result = sweep._strict_fullraw_probe(
        "digital_transformation_firm", runs_root=tmp_path / "runs",
    )

    assert calls == []
    assert result["query"] == "digital transformation firm performance"
    assert result["status"] == "inflight_saturated"
    assert result["inflight_count"] == 2
    assert result["max_inflight"] == 2
    assert result["queue_waiting"] is True
    assert result["queue_shed"] is True


def test_business_sweep_fullraw_probe_rejects_papers_without_complete_receipt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({"query": query, "status": "no_hits"})
        return [
            {"paper_id": f"paper-{idx}", "title": f"{query} source {idx}"}
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )

    assert result["status"] == "incomplete_receipt"
    assert result["paper_count"] == 5
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": result},
    }) == ["no_source_diverse_bundle", "fullraw_complete_receipt_missing"]


def test_business_sweep_fullraw_probe_uses_cached_paper_receipt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    receipt = {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "source_count_searched": 5,
    }
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "cache_hit",
            "paper_count": 5,
        })
        return [
            {
                "paper_id": f"paper-{idx}",
                "title": f"{query} source {idx}",
                "fullraw_shard_receipt": receipt,
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "platform_strategy_network", runs_root=tmp_path / "runs",
    )

    assert result["status"] == "complete"
    assert result["paper_count"] == 5
    assert result["shards_searched"] == 1525
    assert result["partial_shard_search"] is False


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
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "4")

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
                {
                    "paper_id": f"paper-{idx}",
                    "title": f"{query} source {idx}",
                    "source_fact": {
                        "canonical_phrase": (
                            "Platform strategy changed network-effect monetization "
                            f"in multi-sided markets {idx}."
                        ),
                        "population": "multi-sided markets",
                        "intervention": "platform strategy",
                        "endpoint": "network-effect monetization",
                    },
                }
                for idx in range(5)
            ]
        return []

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "platform_strategy_network_effects",
        include_papers=True,
    )

    assert calls == [
        "platform strategy network performance",
        "platform strategy network",
        "platform strategy network performance empirical",
        "platform strategy network performance replication",
    ]
    assert result["status"] == "complete"
    assert result["paper_count"] == 5
    assert result["query"] == "platform strategy network performance replication"
    assert len(result["_papers"]) == 5


def test_business_sweep_fullraw_probe_prefers_cached_complete_query_variant(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[str] = []
    complete_receipt = {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "source_count_searched": 5,
    }
    complete_results = [
        {
            "paper_id": f"paper-{idx}",
            "title": f"Supply chain resilience performance source {idx}",
            "source_fact": {
                "canonical_phrase": (
                    "Supply chain resilience changed firm performance "
                    f"in disruption setting {idx}."
                ),
                "population": "firms",
                "intervention": "supply chain resilience",
                "endpoint": "firm performance",
            },
        }
        for idx in range(5)
    ]

    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("supply chain resilience", "supply chain resilience performance"),
    )

    def fake_search_response(
        query: str, **_kwargs: Any,
    ) -> dict[str, Any]:
        if query != "supply chain resilience performance":
            return {
                "results": [
                    {
                        "paper_id": f"metadata-{idx}",
                        "title": f"Dataset for {query} {idx}",
                    }
                    for idx in range(10)
                ],
                "meta": {"shard_receipt": complete_receipt},
            }
        return {
            "results": complete_results,
            "meta": {"shard_receipt": complete_receipt},
        }

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = dict(complete_receipt)
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "complete",
            "partial_shard_search": False,
            "shards_searched": 1525,
        })
        return complete_results

    monkeypatch.setattr(sweep, "_fullraw_search_response", fake_search_response)
    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "supply_chain_resilience", include_papers=True,
    )

    assert calls == ["supply chain resilience performance"]
    assert result["status"] == "complete"
    assert result["query"] == "supply chain resilience performance"
    assert result["candidate_fact_source_count"] == 5


def test_business_fullraw_search_response_uses_canonical_payload(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results": []}'

    def fake_urlopen(req: Any, timeout: int = 0) -> FakeResponse:
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://fullraw/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("TOPIC_DISCOVERY_FULLRAW_PRIORITY", "1")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = sweep._fullraw_search_response("minimum wage", limit=10)

    assert result == {"results": []}
    assert captured["url"] == "http://fullraw/search"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["body"] == {
        "query": "minimum wage",
        "limit": 10,
        "rank_mode": "relevance",
        "cache_only": True,
        "queue_if_missing": True,
    }


def test_business_cached_fullraw_hit_probe_uses_short_bounded_timeout(
    monkeypatch: Any,
) -> None:
    captured: list[dict[str, Any]] = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results": []}'

    def fake_urlopen(req: Any, timeout: float = 0.0) -> FakeResponse:
        captured.append({
            "timeout": timeout,
            "body": json.loads(req.data.decode("utf-8")),
        })
        return FakeResponse()

    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://fullraw/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_CACHE_PROBE_TIMEOUT_SECONDS", "0.75")
    monkeypatch.setattr(sweep, "_business_fullraw_queries", lambda _topic: ("minimum wage",))
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    assert sweep._cached_fullraw_complete_hit_count("minimum_wage") == 0
    assert captured == [{
        "timeout": 0.75,
        "body": {
            "query": "minimum wage",
            "limit": 10,
            "rank_mode": "relevance",
            "cache_only": True,
            "queue_if_missing": False,
        },
    }]


def test_business_sweep_fullraw_probe_continues_after_complete_source_poor_query(
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
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "3")
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("platform strategy network", "platform strategy network performance"),
    )

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
        if query.endswith("performance"):
            return [
                {
                    "paper_id": f"article-{idx}",
                    "title": f"{query} article {idx}",
                    "abstract": (
                        "Findings show that platform strategy significantly "
                        f"improves firm performance in source {idx}."
                    ),
                }
                for idx in range(5)
            ]
        return [
            {"paper_id": f"dataset-{idx}", "title": f"Dataset for {query} {idx}"}
            for idx in range(10)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "platform_strategy_network_effects",
        include_papers=True,
    )

    assert calls == ["platform strategy network", "platform strategy network performance"]
    assert result["status"] == "complete"
    assert result["query"] == "platform strategy network performance"
    assert result["paper_count"] == 5
    assert result["candidate_fact_source_count"] == 5


def test_business_sweep_fullraw_probe_advances_after_bounded_incomplete_query(
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
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "2")
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("minimum wage", "minimum wage employment"),
    )

    complete_receipt = {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "source_count_searched": 5,
    }

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        if query == "minimum wage":
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
                "shards_searched": 730,
                "partial_shard_search": True,
                "sweep_failed_shards": 0,
                "source_count_searched": 5,
            }
            return [{"paper_id": "partial-1", "title": "Minimum wage partial receipt"}]
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = dict(complete_receipt)
        return [
            {
                "paper_id": f"employment-{idx}",
                "title": f"Minimum wage employment source {idx}",
                "abstract": (
                    "Results show minimum wage changes altered employment "
                    f"outcomes in labor market source {idx}."
                ),
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "minimum_wage_employment",
        include_papers=True,
    )

    assert calls == ["minimum wage", "minimum wage employment"]
    assert result["status"] == "complete"
    assert result["query"] == "minimum wage employment"
    assert result["candidate_fact_source_count"] == 5


def test_business_sweep_fullraw_probe_sheds_unadmitted_saturated_query(
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
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "2")
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS", "0")
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("minimum wage performance", "minimum wage employment"),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "queue_saturated",
            "async_status": "queued",
            "key_queued": False,
            "key_running": False,
            "queued_count": 4,
            "max_queue": 4,
            "paper_count": 0,
        })
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        if query == "minimum wage performance":
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
            return []
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        return [
            {
                "paper_id": f"employment-{idx}",
                "title": f"Minimum wage employment source {idx}",
                "abstract": (
                    "Results show minimum wage changes altered employment "
                    f"outcomes in labor market source {idx}."
                ),
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "minimum_wage_employment",
        include_papers=True,
    )

    assert calls == ["minimum wage performance"]
    assert result["status"] == "queue_saturated"
    assert result["query"] == "minimum wage performance"
    assert result["queue_shed"] is True


def test_business_sweep_fullraw_probe_retries_unadmitted_full_queue(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "2")
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS", "30")
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("minimum wage performance", "minimum wage employment"),
    )
    monkeypatch.setattr(
        "scripts.run_business_alpha_sweep.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        if len(calls) == 1:
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
            discovery._FULLRAW_PROBE_EVENTS.append({
                "query": query,
                "status": "queue_saturated",
                "async_status": "queued",
                "key_queued": False,
                "key_running": False,
                "queued_count": 4,
                "max_queue": 4,
                "paper_count": 0,
            })
            return []
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        return [
            {
                "paper_id": f"employment-{idx}",
                "title": f"Minimum wage employment source {idx}",
                "abstract": (
                    "Results show minimum wage changes altered employment "
                    f"outcomes in labor market source {idx}."
                ),
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "minimum_wage_employment",
        include_papers=True,
    )

    assert calls == ["minimum wage performance", "minimum wage performance"]
    assert sleeps == [15.0]
    assert result["status"] == "complete"
    assert result["candidate_fact_source_count"] == 5


def test_business_sweep_fullraw_probe_retries_admitted_pending_key(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "1")
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS", "30")
    monkeypatch.setattr(
        sweep,
        "_business_fullraw_queries",
        lambda _topic: ("minimum wage performance",),
    )
    monkeypatch.setattr(
        "scripts.run_business_alpha_sweep.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        if len(calls) == 1:
            topic_discovery_mod._FULLRAW_LAST_RECEIPT = {}
            discovery._FULLRAW_PROBE_EVENTS.append({
                "query": query,
                "status": "incomplete_receipt",
                "async_status": "queued",
                "key_queued": True,
                "key_running": False,
                "queued_count": 4,
                "max_queue": 4,
                "paper_count": 0,
            })
            return []
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        return [
            {
                "paper_id": f"employment-{idx}",
                "title": f"Minimum wage employment source {idx}",
                "abstract": (
                    "Results show minimum wage changes altered employment "
                    f"outcomes in labor market source {idx}."
                ),
            }
            for idx in range(5)
        ]

    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe(
        "minimum_wage_employment",
        include_papers=True,
    )

    assert calls == ["minimum wage performance", "minimum wage performance"]
    assert sleeps == [15.0]
    assert result["status"] == "complete"
    assert result["candidate_fact_source_count"] == 5


def test_business_fullraw_queries_are_compact_deduped_and_alpha_shaped(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS",
        "replication,primary endpoint",
    )
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "4")

    queries = sweep._business_fullraw_queries("pricing_strategy_margin_effects")

    assert queries[:3] == (
        "pricing strategy margin",
        "pricing strategy margin performance",
        "pricing strategy margin empirical",
    )
    assert all("effects" not in query for query in queries)
    assert all(len(query.split()) <= 5 for query in queries)
    assert len(queries) == len({
        " ".join(sorted(set(query.split())))
        for query in queries
    })


def test_business_fullraw_queries_priority_defaults_to_single_compact_sweep(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS",
        "replication,primary endpoint",
    )
    monkeypatch.delenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", raising=False)

    assert sweep._business_fullraw_queries("pricing_strategy_margin_effects") == (
        "pricing strategy margin",
    )


def test_business_fullraw_queries_nonpriority_default_keeps_source_rich_sweeps(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS",
        "replication,primary endpoint",
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_PRIORITY", "0")
    monkeypatch.delenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", raising=False)

    assert sweep._business_fullraw_queries("pricing_strategy_margin_effects") == (
        "pricing strategy margin",
        "pricing strategy margin performance",
        "pricing strategy margin empirical",
    )


def test_business_fullraw_queries_do_not_drop_all_specific_intent(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_FULLRAW_ALPHA_SHAPE_TERMS",
        "replication,primary endpoint",
    )
    monkeypatch.setenv("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", "4")

    queries = sweep._business_fullraw_queries("business_model_performance")

    assert queries == (
        "business model performance",
        "business model performance empirical",
        "business model performance replication",
        "business model performance primary endpoint",
    )
    assert "business model" not in queries


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


def test_business_sweep_fullraw_probe_waits_for_busy_worker(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    calls: list[int] = []
    sleeps: list[float] = []
    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setenv("TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_WAIT_SECONDS", "1")

    def fake_flock(_handle: Any, flags: int) -> None:
        if flags & fcntl.LOCK_UN:
            return
        calls.append(flags)
        if len(calls) == 1:
            raise BlockingIOError

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_seed_fullraw(_topic: str, **_kwargs: Any) -> list[dict[str, Any]]:
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = {
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "source_count_searched": 5,
        }
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        return [{"paper_id": f"paper-{idx}"} for idx in range(5)]

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    monkeypatch.setattr("scripts.run_business_alpha_sweep.time.sleep", fake_sleep)
    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)

    result = sweep._strict_fullraw_probe("pricing_strategy_margin")

    assert len(calls) == 2
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 1.0
    assert result["status"] == "complete"
    assert result["paper_count"] == 5


def test_business_sweep_maps_researka_fullraw_env_aliases(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    env_file = tmp_path / "fullraw.env"
    env_file.write_text(
        "\n".join((
            "RESEARKA_FULLRAW_SEARCH_URL=http://127.0.0.1:9903/search",
            "RESEARKA_FULLRAW_INDEX_TOKEN=tok-researka",
            "RESEARKA_FULLRAW_TOKEN=tok-researka",
            "RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED=1525",
            "RESEARKA_FULLRAW_MIN_SOURCES_SEARCHED=5",
            "RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH=1",
            "RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS=900",
        )),
        encoding="utf-8",
    )
    monkeypatch.setenv("V5_MEMO_FULL_RAW_ENV_FILE", str(env_file))
    for key in (
        "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL",
        "V5_MEMO_FULL_RAW_INDEX_TOKEN",
        "V5_MEMO_FULL_RAW_CORPUS_TOKEN",
        "V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED",
        "V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED",
        "V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH",
        "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS",
        "RESEARKA_FULLRAW_SEARCH_URL",
        "RESEARKA_FULLRAW_INDEX_TOKEN",
        "RESEARKA_FULLRAW_TOKEN",
        "RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED",
        "RESEARKA_FULLRAW_MIN_SOURCES_SEARCHED",
        "RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH",
        "RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)

    sweep._load_fullraw_env_defaults()

    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL"] == "http://127.0.0.1:9903/search"
    assert os.environ["V5_MEMO_FULL_RAW_INDEX_TOKEN"] == "tok-researka"
    assert os.environ["V5_MEMO_FULL_RAW_CORPUS_TOKEN"] == "tok-researka"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED"] == "1525"
    assert os.environ["V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED"] == "5"
    assert os.environ["V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH"] == "1"
    assert os.environ["V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS"] == "900"


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


def test_business_sweep_retries_complete_fact_bearing_fullraw_before_unknown(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "business_research-heterogeneous_seed.json").write_text(json.dumps({
        "raw_fact_count": 8,
        "a_core_fact_count": 2,
        "top_clusters": [{"source_count": 1}],
        "retrieval_trace": {
            "fullraw": {
                "status": "complete",
                "fact_source_count": 5,
                "shards_searched": 1525,
                "partial_shard_search": False,
                "sweep_failed_shards": 0,
            },
        },
    }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "business_research",
        ["heterogeneous_seed", "untried_seed"],
    ) == ["heterogeneous_seed", "untried_seed"]


def test_business_sweep_retries_complete_partial_source_fullraw_before_unknown(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "business_research-partial_source_seed.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "top_clusters": [],
        "retrieval_trace": {
            "fullraw": {
                "status": "complete",
                "paper_count": 10,
                "fact_source_count": 3,
                "shards_searched": 1525,
                "partial_shard_search": False,
                "sweep_failed_shards": 0,
            },
        },
    }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "business_research",
        ["partial_source_seed", "untried_seed"],
    ) == ["partial_source_seed", "untried_seed"]


def test_business_sweep_prioritizes_ready_source_literature_over_weak_db_cluster(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "business_research-ready_source_lit.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "top_clusters": [],
        "retrieval_trace": {
            "fullraw": {
                "status": "complete",
                "paper_count": 10,
                "fact_source_count": 6,
                "shards_searched": 1525,
                "partial_shard_search": False,
                "sweep_failed_shards": 0,
            },
        },
    }), encoding="utf-8")
    (diagnostics / "business_research-weak_db_cluster.json").write_text(json.dumps({
        "raw_fact_count": 8,
        "a_core_fact_count": 2,
        "top_clusters": [{"source_count": 1}],
        "retrieval_trace": {"fullraw": {"status": "complete", "paper_count": 10}},
    }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "business_research",
        ["weak_db_cluster", "ready_source_lit"],
    ) == ["ready_source_lit", "weak_db_cluster"]


def test_business_sweep_deprioritizes_complete_fullraw_without_raw_facts(
    tmp_path: Path,
) -> None:
    diagnostics = tmp_path / "runs" / "_business_diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "business_research-weak_seed.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "top_clusters": [],
        "retrieval_trace": {
            "fullraw": {
                "status": "complete",
                "paper_count": 10,
                "shards_searched": 1525,
                "partial_shard_search": False,
                "sweep_failed_shards": 0,
            },
        },
    }), encoding="utf-8")

    assert sweep._prioritized_seed_topics(
        tmp_path / "runs",
        "business_research",
        ["weak_seed", "untried_seed"],
    ) == ["untried_seed", "weak_seed"]


def test_business_seed_topics_keep_specific_intent_variants_only(
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "seeds.toml"
    seed_path.write_text(
        '[seeds]\ntopics = ["business_model_performance", '
        '"platform_strategy_network_effects", '
        '"digital_transformation_firm_performance"]\n',
        encoding="utf-8",
    )

    topics = sweep._seed_topics(seed_path, limit=8)

    assert topics[:3] == [
        "platform_strategy_network_effects",
        "digital_transformation_firm_performance",
        "business_model_performance",
    ]
    assert "platform_strategy_network" in topics
    assert "digital_transformation_firm" in topics
    assert "platform_strategy" not in topics
    assert "digital_transformation" not in topics
    assert "business_model" not in topics
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


def test_business_seed_topics_honor_derived_topic_limit_after_static_window(
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "seeds.toml"
    seed_path.write_text(
        """
[seeds]
derived_topic_limit = 64
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

    assert topics[:9] == [
        "platform_strategy_network_effects",
        "supply_chain_resilience_performance",
        "pricing_strategy_margin",
        "operations_process_improvement",
        "digital_transformation_firm_performance",
        "business_model_performance",
        "platform_strategy_network",
        "supply_chain_resilience",
        "digital_transformation_firm",
    ]
    assert len(topics) > 16
    assert "pricing_strategy_profitability" in topics
    assert "operations_process_productivity" in topics
    assert "digital_transformation_firm_value" in topics
    assert "platform_strategy" not in topics
    blocked = {sweep._topic_key(topic) for topic in topics[:9]}
    fresh = [
        topic for topic in sweep._prioritized_seed_topics(
            tmp_path / "runs", "business_research", topics,
        )
        if sweep._topic_key(topic) not in blocked
    ]
    assert fresh[0] == "platform_strategy_network_productivity"


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
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "health_unavailable"}},
    }) == ["no_source_diverse_bundle", "fullraw_probe_busy"]
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "queue_saturated"}},
    }) == ["no_source_diverse_bundle", "fullraw_probe_busy"]
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "inflight_saturated"}},
    }) == ["no_source_diverse_bundle", "fullraw_probe_busy"]
    assert business_cli.no_bundle_blockers_from_diagnostics({
        "retrieval_trace": {"fullraw": {"status": "async_queue_saturated"}},
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
            "source_fact": {
                "canonical_phrase": (
                    (
                        "Minimum wage policy significantly increases "
                        "employment outcomes in "
                    )
                    if i < 3
                    else "Minimum wage policy contextualizes employment outcomes in "
                )
                + (
                    f"state labor market receipt {i}."
                ),
                "population": "state labor markets",
                "intervention": "minimum wage policy",
                "endpoint": "employment outcomes",
                "source_tier": "fullraw_search",
            },
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
    source_papers = discovery["all"][0]["source_papers"]
    assert publish_literature.substantive_fact_count(source_papers) == 5
    assert publish_literature.source_identity_count(source_papers) == 5
    assert publish_literature.source_identity_count(
        source_papers, require_substantive=True,
    ) == 5
    assert submissions == [{
        "runs_root": tmp_path / "runs",
        "date": "2026-06-27T01-00-00Z",
        "domain": "economics_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {"minimum_wage_employment": papers},
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


def test_business_sweep_uses_cached_complete_fullraw_discovery_without_live_probe(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "business_model_performance"
    submissions: list[dict[str, Any]] = []
    papers = [
        {
            "title": f"Business model performance source paper {idx}",
            "doi": f"10.6161/business-model-{idx}",
            "abstract": "Business model evidence tied to firm performance.",
            "source_fact": {
                "canonical_phrase": (
                    (
                        "Business model changes significantly improve bounded "
                        "firm performance outcomes in "
                        if idx < 3
                        else "Business model changes contextualize bounded "
                        "firm performance outcomes in "
                    )
                    + f"source setting {idx}."
                ),
                "population": "firms",
                "intervention": "business model changes",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=papers,
    )

    def fail_live_probe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("cached complete fullraw discovery should avoid live probe")

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        return {
            "status": "published",
            "submitted": 1,
            "published": 1,
            "publish_summary": {
                "status": "published",
                "submitted": 1,
                "published": 1,
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fail_live_probe)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-10-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-10-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {topic: papers},
    }]


def test_business_sweep_enriches_cached_fullraw_discovery_before_fact_gate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    submissions: list[dict[str, Any]] = []
    papers = [
        {
            "title": f"Digital transformation firm performance paper {idx}",
            "doi": f"10.6161/digital-firm-{idx}",
            "abstract": "Digital transformation evidence tied to firm performance.",
            **({
                "source_fact": {
                    "canonical_phrase": (
                        (
                            "Digital transformation significantly improves "
                            "bounded firm performance outcomes in "
                            if idx < 3
                            else "Digital transformation contextualizes "
                            "bounded firm performance outcomes in "
                        )
                        + f"source setting {idx}."
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    enriched_papers = [
        paper if idx < 4 else paper | {
            "source_fact": {
                "canonical_phrase": (
                    "Digital transformation significantly improves firm performance in the "
                    "fifth independent source setting."
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_abstract",
            },
        }
        for idx, paper in enumerate(papers)
    ]
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=papers,
    )

    def fake_enrich(
        _topic: str, *, domain: str, papers: list[dict[str, Any]], settings: Any,
    ) -> list[dict[str, Any]]:
        assert domain == "business_research"
        assert len(papers) == 5
        return enriched_papers

    def fail_live_probe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("near-complete cached fullraw discovery should avoid live probe")

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        return {
            "status": "published",
            "submitted": 1,
            "published": 1,
            "publish_summary": {
                "status": "published",
                "submitted": 1,
                "published": 1,
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fail_live_probe)
    monkeypatch.setattr(sweep, "_enrich_fullraw_papers_with_db_facts", fake_enrich)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-20-00Z",
    ])

    assert sweep.main() == 0
    assert submissions[0]["source_literature_forced_papers"] == {
        topic: enriched_papers,
    }


def test_business_sweep_falls_back_to_live_probe_when_cached_discovery_stays_under_fact_gate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    submissions: list[dict[str, Any]] = []
    cached_papers = [
        {
            "title": f"Cached digital transformation paper {idx}",
            "doi": f"10.6161/cached-digital-{idx}",
            **({
                "source_fact": {
                    "canonical_phrase": (
                        f"Digital transformation significantly improves firm performance "
                        f"in cached enriched source {idx}."
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    live_papers = [
        {
            "title": f"Live digital transformation paper {idx}",
            "doi": f"10.6161/live-digital-{idx}",
            "source_fact": {
                    "canonical_phrase": (
                        f"Live digital transformation significantly improves "
                        f"firm performance in source {idx}."
                    ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=cached_papers,
    )

    def fake_fullraw(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": live_papers,
        }

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
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-25-00Z",
    ])

    assert sweep.main() == 0
    assert submissions[0]["source_literature_forced_papers"] == {
        topic: live_papers,
    }


def test_business_sweep_keeps_cached_facts_when_live_fullraw_is_busy(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    cached_papers = [
        {
            "title": f"Cached digital transformation paper {idx}",
            "doi": f"10.6161/cached-busy-digital-{idx}",
            **({
                "source_fact": {
                    "canonical_phrase": (
                        f"Digital transformation significantly improves firm performance "
                        f"in cached source {idx}."
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    submissions: list[dict[str, Any]] = []
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=cached_papers,
    )

    def fake_fullraw(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "queue_saturated",
            "async_status": "queued",
            "paper_count": 0,
            "_papers": [],
        }

    def fail_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {"status": "published", "submitted": 1, "published": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fail_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-35-00Z",
    ])

    assert sweep.main() == 2
    assert submissions == []

    summary = json.loads(
        (runs_root / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    row = summary["results"][0]
    assert row["status"] == "no_bundle"
    assert row["fullraw"]["status"] == "queue_saturated"
    assert row["fullraw"]["cached_fact_source_count"] == 4
    assert row["fullraw_fact_source_count"] == 4
    assert "fullraw_probe_busy" in row["blockers"]


def test_business_sweep_reuses_complete_cache_when_db_facts_fill_source_gate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    cached_papers = [
        {
            "title": f"Cached digital transformation paper {idx}",
            "doi": f"10.6161/cached-enriched-digital-{idx}",
            **({
                "source_fact": {
                    "canonical_phrase": f"Cached digital transformation fact {idx}.",
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    db_facts = [
        {
            "id": f"digital-db-{idx}",
            "topic": topic,
            "claim_type": "performance_estimate",
            "numeric_value": idx + 1,
            "units": "index points",
            "canonical_phrase": (
                "Digital transformation significantly improves firm performance in "
                f"bounded receipt {idx}."
            ),
            "population": "firms",
            "intervention": "digital transformation",
            "comparator": "lower digital transformation baseline",
            "outcome": f"firm performance signal {idx}",
            "metric": "firm performance",
            "study_design": f"quasi experimental design {idx}",
            "effect_size": idx + 1,
            "paper": {
                "doi": f"10.6161/digital-db-enriched-{idx}",
                "title": f"Digital transformation firm performance DB source {idx}",
                "journal_name": f"Digital DB outlet {idx}",
                "publication_year": 2024,
            },
        }
        for idx in range(3)
    ]
    submissions: list[dict[str, Any]] = []
    fullraw_calls: list[str] = []
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=cached_papers,
    )

    def fake_fullraw(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(_topic)
        raise AssertionError("cache plus DB facts should avoid live completion probe")

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        db_facts,
        {"status": "ok", "facts": len(db_facts)},
    ))
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-37-00Z",
    ])

    assert sweep.main() == 0
    assert submissions
    summary = json.loads(
        (runs_root / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    row = summary["results"][0]
    assert row["status"] == "submitted_to_researka"
    assert fullraw_calls == []
    assert row["fullraw"]["status"] == "complete"
    assert row["fullraw"]["selected_source_count"] == 5
    assert row["fullraw"]["selected_source_fact_count"] == 5
    assert row["fullraw"]["selected_source_identity_count"] == 5


def test_business_sweep_ranks_reusable_cached_receipt_before_pending_fullraw(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    diagnostics_dir = runs_root / "_business_diagnostics"
    diagnostics_dir.mkdir(parents=True)
    (diagnostics_dir / "business_research-minimum_wage.json").write_text(
        json.dumps({
            "retrieval_trace": {
                "fullraw": {
                    "status": "incomplete_receipt",
                    "async_status": "queued",
                    "fact_source_count": 14,
                },
            },
        }),
        encoding="utf-8",
    )
    (diagnostics_dir / "business_research-digital_transformation_firm.json").write_text(
        json.dumps({
            "retrieval_trace": {
                "fullraw": {
                    "status": "queue_saturated",
                    "fact_source_count": 6,
                },
            },
        }),
        encoding="utf-8",
    )
    topic = "digital_transformation_firm"
    cached_papers = [
        {
            "title": f"Cached digital transformation ranked paper {idx}",
            "doi": f"10.6161/cached-ranked-digital-{idx}",
            **({
                "source_fact": {
                    "canonical_phrase": (
                        f"Digital transformation significantly improves firm performance in cached ranked source {idx}."
                        if idx < 3
                        else f"Cached ranked digital fact {idx}."
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    db_facts = [
        {
            "id": f"digital-ranked-db-{idx}",
            "topic": topic,
            "claim_type": "performance_estimate",
            "numeric_value": idx + 1,
            "units": "index points",
            "canonical_phrase": (
                "Digital transformation significantly improves firm performance in "
                f"ranked receipt {idx}."
            ),
            "population": "firms",
            "intervention": "digital transformation",
            "comparator": "lower digital transformation baseline",
            "outcome": f"firm performance signal {idx}",
            "metric": "firm performance",
            "study_design": f"quasi experimental design {idx}",
            "effect_size": idx + 1,
            "paper": {
                "doi": f"10.6161/digital-ranked-db-{idx}",
                "title": f"Digital transformation ranked DB source {idx}",
                "journal_name": f"Digital ranked outlet {idx}",
                "publication_year": 2024,
            },
        }
        for idx in range(2)
    ]
    submissions: list[dict[str, Any]] = []
    probed_topics: list[str] = []
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=cached_papers,
    )

    def fake_fullraw(probed_topic: str, **_kwargs: Any) -> dict[str, Any]:
        probed_topics.append(probed_topic)
        return {
            "status": "queue_saturated",
            "async_status": "queued",
            "query": f"{probed_topic} completion",
            "paper_count": 0,
            "_papers": [],
        }

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: ["minimum_wage"],
    )
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "minimum_wage",
        topic,
    ])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda selected, **_kwargs: (
        db_facts if selected == topic else [],
        {"status": "ok"},
    ))
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-38-00Z",
    ])

    assert sweep.main() == 0
    assert probed_topics == []
    assert submissions


def test_business_sweep_merges_cached_and_live_fullraw_facts_to_reach_gate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    submissions: list[dict[str, Any]] = []
    cached_papers = [
        {
            "title": f"Cached digital transformation paper {idx}",
            "doi": f"10.6161/cached-merge-digital-{idx}",
            **({
                "source_fact": {
                    "canonical_phrase": (
                        f"Digital transformation significantly improves firm performance in cached source {idx}."
                        if idx < 3
                        else f"Cached digital transformation fact {idx}."
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    live_papers = [
        {
            "title": "Live digital transformation fifth source",
            "doi": "10.6161/live-merge-digital-5",
            "source_fact": {
                "canonical_phrase": "Live digital transformation significantly improves firm performance.",
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
    ]
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=cached_papers,
    )

    def fake_fullraw(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "complete",
            "paper_count": 1,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": live_papers,
        }

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-40-00Z",
    ])

    assert sweep.main() == 0
    forced = submissions[0]["source_literature_forced_papers"][topic]
    assert publish_literature.substantive_fact_count(forced) == 5
    assert publish_literature.source_identity_count(
        forced, require_substantive=True,
    ) == 5
    assert {paper["doi"] for paper in cached_papers[:4]} <= {
        paper["doi"] for paper in forced
    }
    assert "10.6161/live-merge-digital-5" in {paper["doi"] for paper in forced}


def test_business_sweep_rejects_complete_fullraw_without_five_citable_fact_sources(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    papers = [
        {
            "title": f"Digital transformation firm performance paper {idx}",
            "doi": f"10.6161/citable-digital-{idx}",
            "source_fact": {
                "canonical_phrase": f"Digital transformation fact {idx}.",
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(4)
    ] + [{
        "title": "Uncited digital transformation performance paper",
        "source_fact": {
            "canonical_phrase": "Digital transformation fact without a citable source id.",
            "population": "firms",
            "intervention": "digital transformation",
            "endpoint": "firm performance",
            "source_tier": "fullraw_search",
        },
    }]

    def fake_fullraw(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers,
        }

    def fail_run_cycle(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non-citable fifth fact source must not submit")

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fail_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T01-20-00Z",
    ])

    assert sweep.main() == 2
    summary = json.loads(
        (runs_root / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    row = summary["results"][0]
    assert row["status"] == "no_bundle"
    assert row["fullraw_fact_source_count"] == 5
    assert row["fullraw"]["source_fact_identity_count"] == 4
    assert "source_fact_diversity_below_min" in row["blockers"]


def test_business_sweep_uses_distinct_db_facts_to_complete_fullraw_bundle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("economics_research")
    runs_root = tmp_path / "runs"
    topic = "minimum_wage_employment"
    submissions: list[dict[str, Any]] = []
    labour_outlets = (
        "Alpha Labour Review",
        "Beta Employment Journal",
        "Gamma Policy Quarterly",
        "Delta Wage Studies",
        "Epsilon Labor Economics",
    )
    facts = [
        {
            "id": f"mw-{idx}",
            "topic": "minimum wage employment",
            "claim_type": "employment_estimate",
            "numeric_value": idx,
            "units": "percentage points",
            "canonical_phrase": (
                "Minimum wage policy significantly increases employment outcomes in "
                f"state labor market receipt {idx}."
            ),
            "population": "state labor markets",
            "intervention": "minimum wage policy",
            "comparator": "lower minimum wage baseline",
            "outcome": "employment outcomes",
            "metric": "employment",
            "study_design": f"quasi experimental design {idx}",
            "effect_size": idx,
            "paper": {
                "doi": f"10.6161/min-wage-{idx}",
                "title": f"Minimum wage employment source {idx}",
                "journal_name": labour_outlets[idx],
                "publication_year": 2024,
            },
        }
        for idx in range(5)
    ]
    metadata_papers = [
        {
            "title": f"Minimum wage employment source {idx}",
            "doi": f"10.6161/min-wage-{idx}",
        }
        for idx in range(5)
    ]

    assert build_candidate_bundle(facts, topic=topic, domain="economics_research") is None

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        assert publish_literature.source_outlet_count(forced) == 5
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("economics_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        facts,
        {"status": "ok", "facts": len(facts)},
    ))
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "complete",
        "paper_count": 5,
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "_papers": metadata_papers,
    })
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "economics_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T01-50-00Z",
    ])

    assert sweep.main() == 0
    forced = submissions[0]["source_literature_forced_papers"][topic]
    assert {paper["doi"] for paper in forced} == {
        f"10.6161/min-wage-{idx}" for idx in range(5)
    }


def test_business_sweep_refetches_directional_source_lit_facts_after_numeric_miss(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "platform_strategy_network_profitability"
    submissions: list[dict[str, Any]] = []
    outlets = (
        "Alpha Strategy Review",
        "Beta Platform Journal",
        "Gamma Network Letters",
        "Delta Business Quarterly",
        "Epsilon Profitability Studies",
    )
    directional_facts = [
        {
            "id": f"platform-{idx}",
            "topic": "platform strategy network profitability",
            "claim_type": "directional_receipt",
            "canonical_phrase": (
                "Platform strategy network effects improved firm profitability "
                f"in bounded receipt {idx}."
            ),
            "population": "firms",
            "intervention": "platform strategy network effects",
            "comparator": "non-platform strategy baseline",
            "outcome": "firm profitability",
            "metric": "firm profitability",
            "study_design": f"empirical strategy design {idx}",
            "paper": {
                "doi": f"10.6161/platform-directional-{idx}",
                "title": f"Platform strategy networks and profitability source {idx}",
                "journal_name": outlets[idx],
                "publication_year": 2024,
            },
        }
        for idx in range(5)
    ]

    def fake_fetch(
        *_args: Any,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if kwargs.get("numeric_only") is False:
            return directional_facts, {
                "status": "ok",
                "facts": len(directional_facts),
                "numeric_only": False,
            }
        return [], {"status": "ok", "facts": 0, "numeric_only": True}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced,
            require_substantive=True,
        ) == 5
        assert publish_literature.source_outlet_count(forced) == 5
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "complete",
        "paper_count": 5,
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "_papers": [
            {
                "title": f"Platform strategy networks and profitability source {idx}",
                "doi": f"10.6161/platform-directional-{idx}",
            }
            for idx in range(5)
        ],
    })
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-07-01T03-30-00Z",
    ])

    assert sweep.main() == 0
    assert submissions


def test_business_sweep_hands_off_selected_five_fact_backed_sources(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    submissions: list[dict[str, Any]] = []
    outlets = (
        "Alpha Business Review",
        "Beta Operations Journal",
        "Gamma Strategy Letters",
        "Delta Management Quarterly",
        "Epsilon Firm Studies",
    )
    good_papers = [
        {
            "title": f"Digital transformation firm performance source {idx}",
            "doi": f"10.6161/digital-selected-{idx}",
            "journal_name": outlets[idx],
            "source_fact": {
                "canonical_phrase": (
                    f"Digital transformation significantly improves firm performance {idx}."
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": f"firm performance signal {idx}",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]
    noisy_papers = [
        {
            "title": "Digital transformation metadata appendix",
            "doi": "10.6161/digital-metadata",
            "source_fact": {
                "canonical_phrase": "Title-level source match: digital transformation",
                "endpoint": "source-literature relevance",
                "source_tier": "paper_metadata",
            },
        },
        {
            "title": "Digital transformation firm performance duplicate",
            "doi": "10.6161/digital-duplicate-claim",
            "journal_name": "Digital outlet duplicate",
            "source_fact": good_papers[0]["source_fact"],
        },
    ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert len(forced) == 5
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        assert sweep._source_outlet_count(forced) == 5
        claim_keys = [sweep._source_fact_claim_key(paper) for paper in forced]
        assert len(set(claim_keys)) == 5
        assert "10.6161/digital-metadata" not in {paper["doi"] for paper in forced}
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [], {"status": "failed"},
    ))
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "complete",
        "paper_count": 7,
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "_papers": [*noisy_papers, *good_papers],
    })
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T03-05-00Z",
    ])

    assert sweep.main() == 0
    assert submissions
    discovery = json.loads(
        (
            runs_root / "_topics_discovery"
            / "business_sweep_fullraw.business_research.digital_transformation_firm.json"
        ).read_text(encoding="utf-8"),
    )
    papers = discovery["all"][0]["source_papers"]
    assert len(papers) == 5
    assert publish_literature.substantive_fact_count(papers) == 5


def test_business_sweep_counts_doi_prefixes_as_outlet_diversity() -> None:
    rows = [
        {
            "doi": "10.3390/systems11080396",
            "url": "https://doi.org/10.3390/systems11080396",
        },
        {
            "doi": "10.3390/admsci13100225",
            "url": "https://doi.org/10.3390/admsci13100225",
        },
        {
            "doi": "10.57044/sajol.2022.1.2.2212",
            "url": "https://doi.org/10.57044/sajol.2022.1.2.2212",
        },
        {
            "doi": "10.5267/j.uscm.2022.8.001",
            "url": "https://doi.org/10.5267/j.uscm.2022.8.001",
        },
        {
            "doi": "10.1108/jmtm-08-2022-0307",
            "url": "https://doi.org/10.1108/jmtm-08-2022-0307",
        },
    ]

    assert sweep._source_outlet_count(rows) == 4


def test_business_sweep_requires_five_fact_backed_outlets() -> None:
    outlets = ("Alpha Journal", "Beta Journal", "Gamma Journal", "Delta Journal")
    papers = [
        {
            "title": f"Digital transformation firm performance source {idx}",
            "doi": f"10.6161/digital-outlet-floor-{idx}",
            "journal_name": outlets[min(idx, 3)],
            "source_fact": {
                "canonical_phrase": (
                    f"digital transformation changed firm outcome {idx}"
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": f"firm outcome {idx}",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]

    selected, reason = sweep._source_literature_ready_papers(
        "digital_transformation_firm",
        "business_research",
        papers,
    )

    assert len(selected) == 5
    assert publish_literature.substantive_fact_count(selected) == 5
    assert publish_literature.source_identity_count(
        selected, require_substantive=True,
    ) == 5
    assert publish_literature.source_outlet_count(selected) == 4
    assert reason == "source_outlet_diversity_below_min"


def test_business_sweep_blocks_complete_metadata_with_thin_outlet_diversity(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    papers = [
        {
            "title": f"Digital transformation firm performance source {idx}",
            "doi": f"10.6161/digital-thin-outlet-{idx}",
            "journal_name": f"Outlet {idx % 2}",
            "source_fact": {
                "canonical_phrase": f"Digital transformation changed firm outcome {idx}.",
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": f"firm outcome {idx}",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]
    run_cycle_calls = 0

    def fail_run_cycle(**_kwargs: Any) -> dict[str, Any]:
        nonlocal run_cycle_calls
        run_cycle_calls += 1
        return {"status": "published", "submitted": 1, "published": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [], {"status": "failed"},
    ))
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "complete",
        "paper_count": 5,
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "_papers": papers,
    })
    monkeypatch.setattr(sweep, "run_cycle", fail_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T03-30-00Z",
    ])

    assert sweep.main() == 2
    row = json.loads(
        (runs_root / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )["results"][0]
    assert row["fullraw"]["selected_source_outlet_metadata_count"] == 5
    assert row["fullraw"]["selected_source_outlet_count"] == 2
    assert "source_outlet_diversity_below_min" in row["blockers"]
    assert run_cycle_calls == 0


def test_business_sweep_targets_near_ready_sources_to_complete_fact_gate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import agent.topic_discovery as topic_discovery_mod
    import scripts.run_topic_discovery as discovery

    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    calls: list[str] = []
    submissions: list[dict[str, Any]] = []
    cached_papers = [
        {
            "title": f"Cached digital transformation paper {idx}",
            "doi": f"10.6161/cached-target-digital-{idx}",
            "source_fact": {
                "canonical_phrase": (
                    f"Digital transformation significantly improves firm performance "
                    f"in cached target source {idx}."
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(4)
    ] + [{
        "title": "The Impact of Digital Transformation on Firm Profitability",
        "doi": "10.6161/unfactored-digital-profitability",
    }]
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic=topic,
        profile=profile,
        papers=cached_papers,
    )
    receipt = {
        "shards_searched": 1525,
        "partial_shard_search": False,
        "sweep_failed_shards": 0,
        "source_count_searched": 5,
    }

    def fake_seed_fullraw(query: str, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(query)
        topic_discovery_mod._FULLRAW_LAST_RECEIPT = dict(receipt)
        topic_discovery_mod._FULLRAW_LAST_ASYNC_SWEEP = {}
        discovery._FULLRAW_PROBE_EVENTS.append({
            "query": query,
            "status": "complete",
            "shards_searched": 1525,
            "partial_shard_search": False,
        })
        return [{
            "title": "Live digital transformation profitability source",
            "doi": "10.6161/live-digital-profitability",
            "source_fact": {
                "canonical_phrase": (
                    "Digital transformation improved firm profitability "
                    "in listed firms."
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "firm profitability",
                "source_tier": "fullraw_search",
            },
        }]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "publish_summary": {
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "top_blockers": {},
                "next_action": "watch_decision_or_public_page",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": None,
            },
        }

    monkeypatch.setenv("V5_MEMO_FULL_RAW_INDEX_TOKEN", "tok")
    monkeypatch.setenv(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
        str(tmp_path / "fullraw.lock"),
    )
    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(discovery, "_seed_fullraw_papers", fake_seed_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-45-00Z",
    ])

    assert sweep.main() == 0
    assert calls == ["digital transformation firm profitability"]
    assert submissions


def test_business_sweep_prioritizes_cached_fullraw_facts_over_busy_probe(
    tmp_path: Path,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    diagnostic_dir = runs_root / "_business_diagnostics"
    diagnostic_dir.mkdir(parents=True)
    (diagnostic_dir / "business_research-platform_strategy_network.json").write_text(
        json.dumps({
            "raw_fact_count": 2,
            "a_core_fact_count": 2,
            "top_clusters": [{"source_count": 1, "fact_count": 2}],
            "retrieval_trace": {
                "fullraw": {
                    "status": "queue_saturated",
                    "async_status": "queued",
                    "fact_source_count": 0,
                },
            },
        }),
        encoding="utf-8",
    )
    papers = [
        {
            "title": f"Digital transformation firm performance paper {idx}",
            "doi": f"10.6161/digital-rank-{idx}",
            **({
                "source_fact": {
                    "canonical_phrase": (
                        "Digital transformation changed firm performance in "
                        f"source setting {idx}."
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            } if idx < 4 else {}),
        }
        for idx in range(5)
    ]
    sweep._write_fullraw_discovery(
        runs_root,
        domain="business_research",
        topic="digital_transformation_firm",
        profile=profile,
        papers=papers,
    )

    assert sweep._prioritized_seed_topics(
        runs_root,
        "business_research",
        ["platform_strategy_network", "digital_transformation_firm"],
    ) == ["digital_transformation_firm", "platform_strategy_network"]


def test_business_sweep_skips_recent_source_literature_topics_before_fullraw(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    profile = load_domain_profile("business_research")
    topics = ["supply_chain_resilience_performance", "business_model_performance"]
    fullraw_calls: list[str] = []
    submissions: list[dict[str, Any]] = []

    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    recent_date = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    (ledger_dir / "_submitted_fingerprints.json").write_text(
        json.dumps([{
            "date": recent_date,
            "domain": "business_research",
            "topic": "supply_chain_resilience_performance",
        }]),
        encoding="utf-8",
    )

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.4242/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} significantly improves business performance in source {idx}"
                        if idx < 3
                        else f"{topic} bounded source fact {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(topic)
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(topic),
        }

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
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: topics)
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-00-00Z",
    ])

    assert sweep.main() == 0
    assert fullraw_calls == ["business_model_performance"]
    assert submissions[0]["source_literature_forced_papers"] == {
        "business_model_performance": papers_for("business_model_performance"),
    }
    out = capsys.readouterr().out
    assert "skipped_recent_source_literature_topics" in out
    assert "supply_chain_resilience_performance" in out


def test_business_sweep_retries_repairable_recent_source_literature_topic(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    repaired_topic = "supply_chain_resilience_performance"
    topics = [repaired_topic, "business_model_performance"]
    fullraw_calls: list[str] = []
    submissions: list[dict[str, Any]] = []

    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    run_dir = runs_root / f"{repaired_topic}-source-literature-2026-06-29T03-00-00Z"
    run_dir.mkdir(parents=True)
    (run_dir / "source_literature_memo.md").write_text(
        "Repairable source literature memo.",
        encoding="utf-8",
    )
    (ledger_dir / "_submitted_fingerprints.json").write_text(
        json.dumps([{
            "date": "2026-06-29T03-00-00Z",
            "domain": "business_research",
            "topic": repaired_topic,
            "run_dir": str(run_dir),
            "fingerprint": "fp-repairable-source-lit",
        }]),
        encoding="utf-8",
    )
    (ledger_dir / "2026-06-29T03-00-00Z-business_research.json").write_text(
        json.dumps({
            "date": "2026-06-29T03-00-00Z",
            "domain": "business_research",
            "submitted": 1,
            "published": 0,
            "candidate": {
                "topic": repaired_topic,
                "run_dir": str(run_dir),
                "fingerprint": "fp-repairable-source-lit",
            },
            "researka_decision": {
                "decision": "revise",
                "claim_support_verdict": "supported",
                "resubmission": {"allowed": True},
                "required_revisions": ["surface the source bundle evidence"],
            },
        }),
        encoding="utf-8",
    )

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5253/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} significantly improves business performance in source {idx}"
                        if idx < 3
                        else f"{topic} bounded source fact {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(topic)
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(topic),
        }

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
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: topics)
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-00-00Z",
    ])

    assert sweep.main() == 0
    assert fullraw_calls == [repaired_topic]
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-00-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {repaired_topic: papers_for(repaired_topic)},
    }]


def test_business_sweep_promotes_repairable_source_lit_outside_seed_window(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    repaired_topic = "supply_chain_resilience_performance"
    seed_topic = "business_model_performance"
    fullraw_calls: list[str] = []
    submissions: list[dict[str, Any]] = []

    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    diagnostics_dir = runs_root / "_business_diagnostics"
    ledger_dir.mkdir(parents=True)
    diagnostics_dir.mkdir(parents=True)
    (diagnostics_dir / f"business_research-{seed_topic}.json").write_text(json.dumps({
        "raw_fact_count": 0,
        "a_core_fact_count": 0,
        "retrieval_trace": {
            "fullraw": {
                "status": "failed",
                "fact_source_count": 0,
            },
        },
    }), encoding="utf-8")
    run_dir = runs_root / f"{repaired_topic}-source-literature-2026-06-29T03-00-00Z"
    run_dir.mkdir(parents=True)
    (run_dir / "source_literature_memo.md").write_text(
        "Repairable source literature memo.",
        encoding="utf-8",
    )
    (ledger_dir / "2026-06-29T03-00-00Z-business_research.json").write_text(json.dumps({
        "date": "2026-06-29T03-00-00Z",
        "domain": "business_research",
        "submitted": 1,
        "published": 0,
        "submission_id": "sub-clean-revise",
        "candidate": {
            "topic": repaired_topic,
            "run_dir": run_dir.name,
            "fingerprint": "fp-clean-revise",
        },
        "researka_decision": {
            "decision": "revise",
            "claim_support_verdict": "supported",
            "notes": ["editorial decision is terminal; external author must resubmit"],
            "required_revisions": [],
            "major_issues": [],
            "minor_issues": [],
            "failed_checks": [],
            "gate_failures": [],
            "rubric_scores": {
                "claim_evidence_alignment": 5,
                "source_grounding": 5,
                "synthesis_quality": 5,
            },
            "resubmission": {
                "allowed": True,
                "parent_submission_id": "sub-clean-revise",
            },
        },
    }), encoding="utf-8")

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5353/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} significantly improves business performance in source {idx}"
                        if idx < 3
                        else f"{topic} bounded source fact {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(topic)
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(topic),
        }

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
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [seed_topic])
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(
        sweep, "_cached_fullraw_complete_hit_count",
        lambda _topic: 0,
    )
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-00-00Z",
    ])

    assert sweep.main() == 0
    assert fullraw_calls == [repaired_topic]
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-00-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {repaired_topic: papers_for(repaired_topic)},
    }]


def test_business_sweep_keeps_repairable_source_lit_ahead_of_cached_rank(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    submissions: list[dict[str, Any]] = []
    repair_topic = "minimum_wage"

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5354/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": f"{topic} bounded source fact {idx}",
                    "population": "market setting",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def cached_papers(
        _runs_root: Path, _domain: str, topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if topic != repair_topic:
            raise AssertionError(f"non-repair topic should not outrank {repair_topic}")
        return papers_for(topic), {"status": "complete"}

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
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "platform_strategy_network",
        "digital_transformation_firm",
        repair_topic,
    ])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, _topics: [
            "digital_transformation_firm",
            "platform_strategy_network",
            repair_topic,
        ],
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {repair_topic: {}},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [repair_topic, "digital_transformation_firm"],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 10)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("repair path should run before DB facts")),
        {},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-10-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-10-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {repair_topic: papers_for(repair_topic)},
    }]


def test_business_sweep_repair_rows_do_not_starve_fresh_source_lit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    repair_topics = ["repair_duplicate_a", "repair_duplicate_b"]
    fresh_topic = "platform_strategy_network_productivity"
    submissions: list[str] = []
    fullraw_calls: list[str] = []

    def papers_for(topic: str) -> list[dict[str, Any]]:
        outlets = (
            "Journal of Platform Strategy",
            "Strategic Management Review",
            "Management Science Letters",
            "Operations Productivity Quarterly",
            "Firm Performance Studies",
        )
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5656/{topic}-{idx}",
                "journal_name": outlets[idx - 1],
                "abstract": (
                    f"{topic.replace('_', ' ')} reports bounded firm productivity "
                    f"evidence for source {idx}."
                ),
                "source_fact": {
                    "canonical_phrase": (
                        (
                            f"{topic.replace('_', ' ')} significantly improves "
                            "bounded firm productivity "
                            if idx <= 3
                            else f"{topic.replace('_', ' ')} contextualizes "
                            "bounded firm productivity "
                        )
                        + f"outcome {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": f"firm productivity outcome {idx}",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(1, 6)
        ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        forced = kwargs.get("source_literature_forced_papers") or {}
        priority = kwargs.get("source_literature_priority_topics") or []
        topic = next(iter(forced), "") or next(iter(priority), "")
        submissions.append(str(topic))
        if topic in repair_topics:
            return {
                "status": "no_fresh_candidate",
                "submitted": 0,
                "published": 0,
                "publish_summary": {
                    "status": "no_fresh_candidate",
                    "submitted": 0,
                    "published": 0,
                    "top_blockers": {"no_fresh_candidate": 1},
                    "next_action": "refresh_or_expand_candidate_supply",
                    "queue_counts": {"ready_to_publish": 0},
                    "public_url_status": None,
                },
            }
        return {
            "status": "published",
            "submitted": 1,
            "published": 1,
            "publish_summary": {
                "status": "published",
                "submitted": 1,
                "published": 1,
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(topic)
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(topic),
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [fresh_topic])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, topics: list(topics),
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {topic: {} for topic in repair_topics},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: repair_topics,
    )
    monkeypatch.setattr(
        cycle,
        "_pending_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        sweep,
        "_recent_source_literature_repair_attempt_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        sweep,
        "_cached_ready_source_literature_papers",
        lambda _root, _domain, topic, _settings: (
            papers_for(topic) if topic in repair_topics else []
        ),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-07-01T05-00-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [*repair_topics, fresh_topic]
    assert fullraw_calls == [fresh_topic]


def test_business_sweep_duplicate_fallback_suppresses_older_repair_attempt(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "digital_transformation_firm"
    older = ledger_dir / "2026-07-01T00-00-00Z-business_research.json"
    newer = ledger_dir / "2026-07-01T01-00-00Z-business_research.json"
    cycle._write_json(older, {
        "domain": {"slug": "business_research"},
        "source_literature_fallback_attempts": [{
            "topic": topic,
            "status": "blocked",
            "reason": "directional_receipt_floor_below_min",
            "repair_submission": True,
            "selected_source_count": 5,
            "selected_source_fact_count": 5,
            "selected_source_identity_count": 5,
        }],
    })
    cycle._write_json(newer, {
        "domain": {"slug": "business_research"},
        "source_literature_fallback": {
            "topic": topic,
            "status": "blocked",
            "reason": "duplicate_submission_fingerprint",
            "selected_source_count": 5,
            "selected_source_fact_count": 5,
            "selected_source_identity_count": 5,
        },
    })
    os.utime(older, (older.stat().st_atime - 20, older.stat().st_mtime - 20))

    assert sweep._recent_source_literature_repair_attempt_topics(
        runs_root, "business_research",
    ) == []


def test_business_sweep_retries_repair_submission_fallback_attempt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    repair_topic = "digital_transformation_firm"
    submissions: list[dict[str, Any]] = []

    cycle._write_json(ledger_dir / "2026-06-29T08-03-00Z.json", {
        "domain": {"slug": "business_research"},
        "source_literature_fallback_attempts": [{
            "topic": repair_topic,
            "status": "blocked",
            "reason": "directional_receipt_floor_below_min",
            "repair_submission": True,
            "selected_source_count": 5,
            "selected_source_fact_count": 5,
            "selected_source_identity_count": 5,
        }],
    })

    def papers_for(topic: str) -> list[dict[str, Any]]:
        endpoints = [
            "firm performance", "firm profitability", "firm productivity",
            "operating margin", "environmental performance",
        ]
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5555/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic.replace('_', ' ')} significantly improves {endpoint}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": endpoint,
                    "source_tier": "fullraw_search",
                },
            }
            for idx, endpoint in enumerate(endpoints, 1)
        ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(
        sweep,
        "_seed_topics",
        lambda _path, *, limit: ["operations_process_improvement"],
    )
    monkeypatch.setattr(sweep, "_prioritized_seed_topics", lambda _root, _domain, topics: topics)
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {repair_topic: {}},
    )
    monkeypatch.setattr(cycle, "_repairable_source_literature_topics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(
        sweep,
        "_cached_fullraw_discovery_papers",
        lambda _root, _domain, topic: (papers_for(topic), {"status": "complete"}),
    )
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-12-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-12-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {repair_topic: papers_for(repair_topic)},
    }]


def test_business_sweep_retries_cached_ready_recent_submission(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "supply_chain_resilience_performance"
    submissions: list[dict[str, Any]] = []

    cycle._write_json(ledger_dir / "_submitted_fingerprints.json", [{
        "date": "2026-06-30T08-00-00Z",
        "domain": "business_research",
        "topic": topic,
        "fingerprint": "old-source-lit-payload",
    }])

    def papers_for(value: str) -> list[dict[str, Any]]:
        outlets = (
            "Alpha Operations Review",
            "Beta Process Journal",
            "Gamma Management Letters",
            "Delta Productivity Quarterly",
            "Epsilon Firm Systems",
        )
        return [
            {
                "title": f"{value.replace('_', ' ')} source {idx}",
                "doi": f"10.6262/{value}-{idx}",
                "journal_name": outlets[idx],
                "source_fact": {
                    "canonical_phrase": (
                        (
                            f"{value.replace('_', ' ')} significantly improves "
                            "bounded firm "
                            if idx < 3
                            else f"{value.replace('_', ' ')} contextualizes bounded firm "
                        )
                        + f"outcome {idx}"
                    ),
                    "population": "firms",
                    "intervention": value.replace("_", " "),
                    "endpoint": f"firm outcome {idx}",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def cached_papers(
        _runs_root: Path, _domain: str, value: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if value == topic:
            return papers_for(value), {"status": "complete", "paper_count": 5}
        return [], {}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert len(forced) == 5
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        assert sweep._source_outlet_count(forced) == 5
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        topic,
        "platform_strategy_network_effects",
    ])
    monkeypatch.setattr(sweep, "_prioritized_seed_topics", lambda _root, _domain, topics: topics)
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {topic: {}},
    )
    monkeypatch.setattr(cycle, "_repairable_source_literature_topics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("cached-ready topic should run first")),
        {},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T08-30-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-30T08-30-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {topic: papers_for(topic)},
    }]


def test_business_sweep_forces_cached_ready_repair_even_when_unblocked(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    topic = "digital_transformation_firm"
    submissions: list[dict[str, Any]] = []

    def papers_for(value: str) -> list[dict[str, Any]]:
        outlets = (
            "Alpha Strategy Journal",
            "Beta Firm Review",
            "Gamma Management Quarterly",
            "Delta Operations Letters",
            "Epsilon Business Studies",
        )
        return [
            {
                "title": f"{value.replace('_', ' ')} source {idx}",
                "doi": f"10.7272/{value}-{idx}",
                "journal_name": outlets[idx],
                "source_fact": {
                    "canonical_phrase": (
                        f"{value.replace('_', ' ')} changed bounded firm outcome {idx}"
                    ),
                    "population": "firms",
                    "intervention": value.replace("_", " "),
                    "endpoint": f"firm outcome {idx}",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def cached_papers(
        _runs_root: Path, _domain: str, value: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if value == topic:
            return papers_for(value), {"status": "complete", "paper_count": 5}
        return [], {}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert len(forced) == 5
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        assert sweep._source_outlet_count(forced) == 5
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "_prioritized_seed_topics", lambda _root, _domain, topics: topics)
    monkeypatch.setattr(sweep, "_recent_source_literature_blocked_topics", lambda *_args: set())
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {topic: {}},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [topic],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("cached repair should run before DB facts")),
        {},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-07-01T06-30-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-07-01T06-30-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {topic: papers_for(topic)},
    }]


def test_business_sweep_skips_cached_recent_submission_without_priority_repair(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    stale_topic = "supply_chain_resilience_performance"
    fresh_topic = "platform_strategy_network_productivity"
    submissions: list[str] = []
    fullraw_calls: list[str] = []

    cycle._write_json(ledger_dir / "_submitted_fingerprints.json", [{
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "domain": "business_research",
        "topic": stale_topic,
        "fingerprint": "old-source-lit-payload",
    }])

    def papers_for(topic: str) -> list[dict[str, Any]]:
        outlets = (
            "Journal of Platform Strategy",
            "Strategic Management Review",
            "Management Science Letters",
            "Operations Productivity Quarterly",
            "Firm Performance Studies",
        )
        return [
            {
                "title": f"{topic.replace('_', ' ')} source {idx}",
                "doi": f"10.6363/{topic}-{idx}",
                "journal_name": outlets[idx - 1],
                "abstract": (
                    f"{topic.replace('_', ' ')} significantly improves bounded "
                    f"firm productivity outcome {idx}."
                ),
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic.replace('_', ' ')} significantly improves "
                        f"bounded firm productivity outcome {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": f"firm productivity outcome {idx}",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(1, 6)
        ]

    def cached_papers(
        _runs_root: Path, _domain: str, topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if topic == stale_topic:
            return papers_for(topic), {"status": "complete", "paper_count": 5}
        return [], {}

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(topic)
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(topic),
        }

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        forced = kwargs.get("source_literature_forced_papers") or {}
        submissions.append(next(iter(forced), ""))
        return {"status": "published", "submitted": 1, "published": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        stale_topic,
        fresh_topic,
    ])
    monkeypatch.setattr(sweep, "_prioritized_seed_topics", lambda _root, _domain, topics: topics)
    monkeypatch.setattr(cycle, "_priority_source_literature_repair_decisions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cycle, "_repairable_source_literature_topics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-07-01T05-30-00Z",
    ])

    assert sweep.main() == 0
    assert fullraw_calls == [fresh_topic]
    assert submissions == [fresh_topic]


def test_business_sweep_retries_cached_ready_source_floor_without_priority_repair(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "operations_process_improvement"
    submissions: list[dict[str, Any]] = []

    cycle._write_json(ledger_dir / "2026-06-30T08-00-00Z.json", {
        "domain": {"slug": "business_research"},
        "source_literature_fallback": {
            "topic": topic,
            "status": "blocked",
            "reason": "source_floor_below_min",
        },
    })

    def papers_for(value: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{value.replace('_', ' ')} source {idx}",
                "doi": f"10.6464/{value}-{idx}",
                "journal_name": f"Outlet {idx}",
                "abstract": (
                    f"{value.replace('_', ' ')} changes bounded operating "
                    f"outcome {idx}."
                ),
                "source_fact": {
                    "canonical_phrase": (
                        f"{value.replace('_', ' ')} changes bounded operating "
                        f"outcome {idx}"
                    ),
                    "population": "firms",
                    "intervention": value.replace("_", " "),
                    "endpoint": f"operating outcome {idx}",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(1, 6)
        ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        forced = kwargs["source_literature_forced_papers"][topic]
        assert len(forced) == 5
        assert publish_literature.substantive_fact_count(forced) == 5
        assert publish_literature.source_identity_count(
            forced, require_substantive=True,
        ) == 5
        assert sweep._source_outlet_count(forced) == 5
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, topics: topics,
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        cycle,
        "_pending_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(
        sweep,
        "_cached_ready_source_literature_papers",
        lambda _root, _domain, value, _settings: papers_for(value),
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("cached-ready topic should run first")),
        {},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-07-01T05-45-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-07-01T05-45-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {topic: papers_for(topic)},
    }]


def test_business_sweep_retries_source_floor_with_pending_fullraw_completion(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "platform_strategy_network"
    fullraw_calls: list[str] = []
    submissions: list[str] = []

    cycle._write_json(ledger_dir / "2026-06-30T08-05-00Z.json", {
        "domain": {"slug": "business_research"},
        "source_literature_fallback": {
            "topic": topic,
            "status": "blocked",
            "reason": "source_floor_below_min",
        },
    })

    def papers_for(value: str) -> list[dict[str, Any]]:
        outlets = (
            "Platform Strategy Review",
            "Network Economics Journal",
            "Digital Market Quarterly",
            "Management Systems Letters",
            "Firm Performance Studies",
        )
        return [
            {
                "title": f"{value.replace('_', ' ')} source {idx}",
                "doi": f"10.6565/{value}-{idx}",
                "journal_name": outlets[idx - 1],
                "abstract": (
                    f"{value.replace('_', ' ')} changes bounded firm "
                    f"performance outcome {idx}."
                ),
                "source_fact": {
                    "canonical_phrase": (
                        (
                            f"{value.replace('_', ' ')} significantly improves "
                            "bounded firm performance "
                            if idx <= 3
                            else f"{value.replace('_', ' ')} contextualizes "
                            "bounded firm performance "
                        )
                        + f"outcome {idx}"
                    ),
                    "population": "firms",
                    "intervention": value.replace("_", " "),
                    "endpoint": f"firm performance outcome {idx}",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(1, 6)
        ]

    def fake_fullraw(value: str, **kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(value)
        result = {
            "status": "complete",
            "paper_count": 5,
            "candidate_fact_source_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(value),
        }
        if kwargs.get("include_papers"):
            return result
        return {key: item for key, item in result.items() if key != "_papers"}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        forced = kwargs["source_literature_forced_papers"]
        submissions.append(next(iter(forced)))
        return {"status": "published", "submitted": 1, "published": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, topics: topics,
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        cycle,
        "_pending_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(
        sweep,
        "_cached_ready_source_literature_papers",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        sweep,
        "_cached_pending_fullraw_completion",
        lambda value: value == topic,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [],
        {"status": "empty"},
    ))
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-07-01T06-05-00Z",
    ])

    assert sweep.main() == 0
    assert fullraw_calls == [topic]
    assert submissions == [topic]


def test_business_sweep_skips_pending_source_literature_topic(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    pending_topic = "supply_chain_resilience_performance"
    next_topic = "digital_transformation_firm"
    fetched_topics: list[str] = []

    def fake_fetch(topic: str, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        fetched_topics.append(topic)
        return [], {"status": "failed"}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        pending_topic,
        next_topic,
    ])
    monkeypatch.setattr(sweep, "_prioritized_seed_topics", lambda _root, _domain, topics: topics)
    monkeypatch.setattr(cycle, "_priority_source_literature_repair_decisions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cycle, "_repairable_source_literature_topics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cycle, "_pending_source_literature_topics", lambda *_args, **_kwargs: {
        pending_topic,
    })
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "fetch_business_facts", fake_fetch)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "not_configured",
    })
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T08-45-00Z",
    ])

    assert sweep.main() == 2
    assert fetched_topics == [next_topic]


def test_business_sweep_delegates_uncached_priority_repair_to_daily_cycle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    repair_topic = "minimum_wage"
    submissions: list[dict[str, Any]] = []

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        "platform_strategy_network",
        repair_topic,
    ])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, _topics: ["platform_strategy_network", repair_topic],
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {repair_topic: {}},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [repair_topic],
    )
    monkeypatch.setattr(
        sweep,
        "_cached_fullraw_discovery_papers",
        lambda *_args, **_kwargs: ([], {}),
    )
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("daily repair selector should run first")),
            {},
        ),
    )

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
        }

    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-12-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-12-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_priority_topics": [repair_topic],
    }]


def test_business_sweep_demotes_cached_priority_repair_below_fact_floor(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    bad_topic = "digital_transformation_firm"
    good_topic = "pricing_strategy_margin"
    submissions: list[dict[str, Any]] = []

    def papers_for(topic: str, *, bad: bool = False) -> list[dict[str, Any]]:
        papers = [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5354/{topic}-{idx}",
                "abstract": f"{topic} performance evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} improves business performance in bounded firm samples {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]
        if bad:
            papers[-1]["source_fact"] = {
                "canonical_phrase": papers[-1]["title"],
                "source_tier": "fullraw_search",
            }
        return papers

    bad_papers = papers_for(bad_topic, bad=True)
    assert publish_literature.substantive_fact_count(bad_papers) == 4
    assert publish_literature.source_identity_count(
        bad_papers, require_substantive=True,
    ) == 4

    def cached_papers(
        _runs_root: Path, _domain: str, topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if topic == bad_topic:
            return bad_papers, {"status": "complete", "paper_count": 5}
        if topic == good_topic:
            return papers_for(topic), {"status": "complete", "paper_count": 5}
        return [], {}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        if kwargs.get("source_literature_priority_topics") == [bad_topic]:
            raise AssertionError("below-floor cached repair should not re-enter priority")
        submissions.append(kwargs)
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        bad_topic,
        good_topic,
    ])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, _topics: [bad_topic, good_topic],
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {bad_topic: {}, good_topic: {}},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [bad_topic, good_topic],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [],
        {"status": "empty"},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-14-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-14-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {good_topic: papers_for(good_topic)},
    }]


def test_business_sweep_retries_cached_ready_source_lit_despite_recent_submission(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "supply_chain_resilience"
    submissions: list[dict[str, Any]] = []
    cycle._write_json(ledger_dir / "_submitted_fingerprints.json", [{
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "domain": "business_research",
        "status": "reviewer_revise",
        "topic": topic,
    }])
    papers = [
        {
            "title": f"Supply chain resilience performance source paper {idx}",
            "doi": f"10.5354/supply-chain-{idx}",
            "journal_name": journal,
            "source_fact": {
                "canonical_phrase": (
                    "Supply chain resilience significantly improves firm performance in "
                    f"bounded source setting {idx}."
                ),
                "population": "firms",
                "intervention": "supply chain resilience",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx, journal in enumerate((
            "Supply Chain Review",
            "Operations Evidence Journal",
            "Resilience Management Letters",
            "Logistics Performance Studies",
            "Firm Operations Quarterly",
        ))
    ]

    def cached_papers(
        _runs_root: Path, _domain: str, seed_topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if seed_topic == topic:
            return papers, {"status": "complete", "paper_count": 5}
        return [], {}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [topic])
    monkeypatch.setattr(sweep, "_prioritized_seed_topics", lambda _root, _domain, topics: topics)
    monkeypatch.setattr(sweep, "_recent_source_literature_blocked_topics", lambda *_args: {
        sweep._topic_key(topic),
    })
    monkeypatch.setattr(sweep, "_hard_source_literature_blocked_topic_keys", lambda *_args: set())
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(cycle, "_repairable_source_literature_topics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cycle, "_pending_source_literature_topics", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(cycle, "_recent_submission_topics", lambda *_args, **_kwargs: {topic})
    monkeypatch.setattr(cycle, "_recent_source_floor_topics", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(
        cycle,
        "_recent_source_literature_structural_blocked_topics",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [],
        {"status": "empty"},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-16-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-16-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {topic: papers},
    }]


def test_business_sweep_cached_ready_requires_ok_readiness_reason(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    topic = "supply_chain_resilience"
    papers = [
        {
            "title": f"Supply chain resilience source paper {idx}",
            "doi": f"10.5354/supply-chain-duplicate-outlet-{idx}",
            "journal_name": "Same Outlet Journal",
            "source_fact": {
                "canonical_phrase": (
                    "Supply chain resilience changed firm performance in "
                    f"bounded source setting {idx}."
                ),
                "population": "firms",
                "intervention": "supply chain resilience",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]

    monkeypatch.setattr(
        sweep,
        "_cached_fullraw_discovery_papers",
        lambda *_args, **_kwargs: (papers, {"status": "complete", "paper_count": 5}),
    )
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )

    assert sweep._cached_ready_source_literature_papers(
        tmp_path / "runs",
        "business_research",
        topic,
        object(),
    ) == []


def test_business_sweep_reuses_parent_cache_only_with_child_topic_coverage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    topic = "digital_transformation_firm_performance"
    parent_topic = "digital_transformation_firm"
    journals = (
        "Digital Strategy Journal",
        "Firm Performance Review",
        "Transformation Management Letters",
        "Business Technology Quarterly",
        "Enterprise Performance Studies",
    )
    papers = [
        {
            "title": f"Digital transformation firm performance source {idx}",
            "doi": f"10.5454/digital-performance-{idx}",
            "journal_name": journals[idx],
            "source_fact": {
                "canonical_phrase": (
                    "Digital transformation significantly improves firm performance in "
                    f"bounded business setting {idx}."
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]

    def cached_papers(
        _runs_root: Path, _domain: str, cache_topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if cache_topic == parent_topic:
            return papers, {"status": "complete", "paper_count": 5}
        return [], {}

    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )

    ready, cache_topic = sweep._cached_ready_source_literature_papers_with_topic(
        tmp_path / "runs",
        "business_research",
        topic,
        object(),
    )

    assert len(ready) == 5
    assert cache_topic == parent_topic


def test_business_sweep_reuses_sibling_outcome_cache_with_active_topic_coverage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    topic = "platform_strategy_network_profitability"
    sibling_topic = "platform_strategy_network_performance"
    journals = (
        "Alpha Strategy Review",
        "Beta Platform Journal",
        "Gamma Network Letters",
        "Delta Business Quarterly",
        "Epsilon Profitability Studies",
    )
    papers = [
        {
            "title": f"Platform strategy network profitability source {idx}",
            "doi": f"10.5454/platform-profitability-{idx}",
            "journal_name": journals[idx],
            "source_fact": {
                "canonical_phrase": (
                    "Platform strategy network effects improved firm profitability in "
                    f"bounded business setting {idx}."
                ),
                "population": "firms",
                "intervention": "platform strategy network effects",
                "endpoint": "firm profitability",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]

    def cached_papers(
        _runs_root: Path, _domain: str, cache_topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if cache_topic == sibling_topic:
            return papers, {"status": "complete", "paper_count": 5}
        return [], {}

    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )

    ready, cache_topic = sweep._cached_ready_source_literature_papers_with_topic(
        tmp_path / "runs",
        "business_research",
        topic,
        object(),
    )

    assert len(ready) == 5
    assert cache_topic == sibling_topic
    assert publish_literature.source_identity_count(
        ready, require_substantive=True,
    ) == 5
    assert publish_literature.source_outlet_count(ready) == 5


def test_business_sweep_rejects_parent_cache_without_child_topic_coverage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    topic = "minimum_wage_employment"
    parent_topic = "minimum_wage"
    journals = (
        "Wage Policy Journal",
        "Labor Cost Review",
        "Firm Regulation Letters",
        "Business Cost Quarterly",
        "Policy Operations Studies",
    )
    papers = [
        {
            "title": f"Minimum wage policy source {idx}",
            "doi": f"10.5454/minimum-wage-{idx}",
            "journal_name": journals[idx],
            "source_fact": {
                "canonical_phrase": (
                    "Minimum wage policy changed operating costs in "
                    f"bounded business setting {idx}."
                ),
                "population": "firms",
                "intervention": "minimum wage",
                "endpoint": "operating costs",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(5)
    ]

    def cached_papers(
        _runs_root: Path, _domain: str, cache_topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if cache_topic == parent_topic:
            return papers, {"status": "complete", "paper_count": 5}
        return [], {}

    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )

    assert sweep._cached_ready_source_literature_papers_with_topic(
        tmp_path / "runs",
        "business_research",
        topic,
        object(),
    ) == ([], "")


def test_business_sweep_underfilled_repair_does_not_exhaust_scan_window(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    bad_topic = "digital_transformation_firm"
    good_topic = "pricing_strategy_margin"
    submissions: list[dict[str, Any]] = []
    cycle._write_json(ledger_dir / "2026-06-29T08-03-00Z.json", {
        "domain": {"slug": "business_research"},
        "source_literature_fallback_attempts": [{
            "topic": bad_topic,
            "status": "blocked",
            "reason": "directional_receipt_floor_below_min",
            "repair_submission": True,
            "selected_source_count": 5,
            "selected_source_fact_count": 5,
            "selected_source_identity_count": 5,
        }],
    })

    def papers_for(topic: str, *, bad: bool = False) -> list[dict[str, Any]]:
        papers = [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5355/{topic}-{idx}",
                "abstract": f"{topic} performance evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} improves business performance in bounded firm samples {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]
        if bad:
            papers[-1]["source_fact"] = {
                "canonical_phrase": papers[-1]["title"],
                "source_tier": "fullraw_search",
            }
        return papers

    def cached_papers(
        _runs_root: Path, _domain: str, topic: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if topic == bad_topic:
            return papers_for(topic, bad=True), {"status": "complete", "paper_count": 5}
        if topic == good_topic:
            return papers_for(topic), {"status": "complete", "paper_count": 5}
        return [], {}

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        if kwargs.get("source_literature_priority_topics") == [bad_topic]:
            raise AssertionError("below-floor cached repair should not re-enter priority")
        submissions.append(kwargs)
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        bad_topic,
        good_topic,
    ])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, _topics: [bad_topic, good_topic],
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(sweep, "_cached_fullraw_discovery_papers", cached_papers)
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: (
        [],
        {"status": "empty"},
    ))
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-14-00Z",
    ])

    assert sweep.main() == 0
    assert submissions == [{
        "runs_root": runs_root,
        "date": "2026-06-29T04-14-00Z",
        "domain": "business_research",
        "submit": True,
        "refresh_candidates": False,
        "source_literature_forced_papers": {good_topic: papers_for(good_topic)},
    }]


def test_business_sweep_blocks_recent_source_floor_topic_without_cached_ready(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "operations_process_improvement"
    cycle._write_json(ledger_dir / "2026-06-29T09-00-00Z.json", {
        "domain": {"slug": "business_research"},
        "source_literature_fallback": {
            "topic": topic,
            "status": "blocked",
            "reason": "source_floor_below_min",
        },
    })
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )

    assert topic in sweep._recent_source_literature_blocked_topics(
        runs_root, "business_research",
    )


def test_business_sweep_allows_repairable_directional_underfill_topic(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / "_daily_ledger"
    ledger_dir.mkdir(parents=True)
    topic = "digital_transformation_firm"
    cycle._write_json(ledger_dir / "2026-06-29T08-03-00Z.json", {
        "domain": {"slug": "business_research"},
        "source_literature_fallback_attempts": [{
            "topic": topic,
            "status": "blocked",
            "reason": "directional_receipt_floor_below_min",
            "selected_source_count": 5,
            "selected_source_fact_count": 5,
            "selected_source_identity_count": 5,
            "selected_directional_receipt_count": 1,
        }],
    })
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [topic],
    )

    assert sweep._recent_source_literature_blocked_topics(
        runs_root, "business_research",
    ) == set()

    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [],
    )

    assert sweep._recent_source_literature_blocked_topics(
        runs_root, "business_research",
    ) == {sweep._topic_key(topic)}


def test_business_sweep_promotes_cached_complete_fullraw_topic(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    topics = [
        "pricing_strategy_margin",
        "operations_process_improvement",
        "platform_strategy_network",
    ]
    fullraw_calls: list[str] = []
    submissions: list[dict[str, Any]] = []

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.5252/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} significantly improves business performance in source {idx}"
                        if idx < 3
                        else f"{topic} bounded fact {idx}"
                    ),
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "business performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        fullraw_calls.append(topic)
        return {
            "status": "complete",
            "paper_count": 5,
            "shards_searched": 1525,
            "partial_shard_search": False,
            "sweep_failed_shards": 0,
            "_papers": papers_for(topic),
        }

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
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: topics)
    monkeypatch.setattr(sweep, "fetch_business_facts", lambda *_args, **_kwargs: ([], {"status": "failed"}))
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda topic: 10 if topic == "platform_strategy_network" else 0)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T04-30-00Z",
    ])

    assert sweep.main() == 0
    assert fullraw_calls == ["platform_strategy_network"]
    assert submissions[0]["source_literature_forced_papers"] == {
        "platform_strategy_network": papers_for("platform_strategy_network"),
    }


def test_business_sweep_bounds_cached_fullraw_ranking_before_selection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    topics = [f"candidate_{idx}_performance" for idx in range(8)]
    cache_calls: list[str] = []

    def fake_cached_hit_count(topic: str) -> int:
        cache_calls.append(topic)
        return 0

    def fake_fullraw(_topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "queue_saturated",
            "async_status": "queued",
            "paper_count": 0,
            "_papers": [],
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: topics[:limit])
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", fake_cached_hit_count)
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T02-05-00Z",
    ])

    assert sweep.main() == 2
    assert cache_calls == topics[:3]


def test_business_sweep_fullraw_continues_after_reviewer_revise(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("economics_research")
    topics = ["minimum_wage_employment", "asset_pricing_replication"]
    submissions: list[dict[str, Any]] = []

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.7777/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": (
                        f"{topic} significantly improves research outcome in source {idx}"
                        if idx < 3
                        else f"{topic} bounded evidence fact {idx}"
                    ),
                    "population": "market setting",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "research outcome",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        if len(submissions) == 1:
            return {
                "status": "reviewer_revise",
                "submitted": 1,
                "published": 0,
                "publish_summary": {
                    "status": "reviewer_revise",
                    "submitted": 1,
                    "published": 0,
                    "top_blockers": {"reviewer_revise": 1},
                    "next_action": "repair_researka_review_feedback",
                    "queue_counts": {"ready_to_publish": 0},
                    "public_url_status": None,
                },
            }
        return {
            "status": "published",
            "submitted": 1,
            "published": 1,
            "publish_summary": {
                "status": "published",
                "submitted": 1,
                "published": 1,
                "top_blockers": {},
                "next_action": "public_page_verified",
                "queue_counts": {"ready_to_publish": 1},
                "public_url_status": 200,
            },
        }

    def fake_fullraw(topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {
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
            "_papers": papers_for(topic),
        }

    monkeypatch.setattr(sweep, "_DOMAINS", ("economics_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: topics)
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed"}),
    )
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", fake_fullraw)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--domains", "economics_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-27T02-00-00Z",
    ])

    assert sweep.main() == 0
    assert [call["source_literature_forced_papers"] for call in submissions] == [
        {"minimum_wage_employment": papers_for("minimum_wage_employment")},
        {"asset_pricing_replication": papers_for("asset_pricing_replication")},
    ]
    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json").read_text(
            encoding="utf-8",
        ),
    )
    assert [row["status"] for row in summary["results"]] == [
        "reviewer_revise",
        "published",
    ]


def test_business_sweep_skips_topics_attempted_by_source_lit_cycle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    runs_root = tmp_path / "runs"
    repair_topic = "digital_transformation_firm"
    thin_topic = "operations_process_improvement"
    submissions: list[dict[str, Any]] = []
    fact_fetches: list[str] = []

    def papers_for(topic: str) -> list[dict[str, Any]]:
        return [
            {
                "title": f"{topic.replace('_', ' ')} evidence paper {idx}",
                "doi": f"10.8181/{topic}-{idx}",
                "abstract": f"{topic} evidence.",
                "source_fact": {
                    "canonical_phrase": f"{topic} bounded source fact {idx}",
                    "population": "firms",
                    "intervention": topic.replace("_", " "),
                    "endpoint": "firm performance",
                    "source_tier": "fullraw_search",
                },
            }
            for idx in range(5)
        ]

    def fake_run_cycle(**kwargs: Any) -> dict[str, Any]:
        submissions.append(kwargs)
        return {
            "status": "no_fresh_candidate",
            "submitted": 0,
            "published": 0,
            "source_literature_fallback_attempts": [
                {
                    "topic": repair_topic,
                    "status": "blocked",
                    "reason": "rejected_duplicate",
                },
                {
                    "topic": thin_topic,
                    "status": "blocked",
                    "reason": "source_floor_below_min",
                },
            ],
        }

    def fail_if_reprobed(topic: str, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        fact_fetches.append(topic)
        if topic == thin_topic:
            raise AssertionError("source-lit attempted topic should not be probed again")
        return [], {"status": "empty"}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(sweep, "_seed_topics", lambda _path, *, limit: [
        repair_topic, thin_topic,
    ])
    monkeypatch.setattr(
        sweep,
        "_prioritized_seed_topics",
        lambda _root, _domain, _topics: [repair_topic, thin_topic],
    )
    monkeypatch.setattr(
        cycle,
        "_priority_source_literature_repair_decisions",
        lambda *_args, **_kwargs: {repair_topic: {}},
    )
    monkeypatch.setattr(
        cycle,
        "_repairable_source_literature_topics",
        lambda *_args, **_kwargs: [repair_topic],
    )
    monkeypatch.setattr(sweep, "_cached_fullraw_complete_hit_count", lambda _topic: 0)
    monkeypatch.setattr(
        sweep,
        "_cached_fullraw_discovery_papers",
        lambda _root, _domain, topic: (
            (papers_for(topic), {"status": "complete"})
            if topic == repair_topic else
            ([], {})
        ),
    )
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda _topic, *, domain, papers, settings: papers,
    )
    monkeypatch.setattr(sweep, "fetch_business_facts", fail_if_reprobed)
    monkeypatch.setattr(sweep, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "2",
        "--domains", "business_research",
        "--runs-root", str(runs_root),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-30T02-20-00Z",
    ])

    assert sweep.main() == 2
    assert len(submissions) == 1
    assert submissions[0]["source_literature_forced_papers"] == {
        repair_topic: papers_for(repair_topic),
    }
    assert fact_fetches == []


def test_business_sweep_fullraw_discovery_does_not_count_metadata_as_facts(
    tmp_path: Path,
) -> None:
    profile = load_domain_profile("business_research")
    papers = [
        {
            "paper_id": f"metadata-{idx}",
            "title": f"Platform strategy network effects title match {idx}",
            "source_fact": {
                "canonical_phrase": (
                    "Title-level source match: Platform strategy network effects"
                ),
                "endpoint": "source-literature relevance",
                "source_tier": "paper_metadata",
            },
        }
        for idx in range(5)
    ]
    papers.append({
        "paper_id": "fullraw-fact-1",
        "title": "Platform strategy changed network monetization",
        "source_fact": {
            "canonical_phrase": (
                "Platform strategy changed network-effect monetization in "
                "multi-sided markets."
            ),
            "population": "multi-sided markets",
            "intervention": "platform strategy",
            "endpoint": "network-effect monetization",
            "source_tier": "fullraw_search",
        },
    })

    path = sweep._write_fullraw_discovery(
        tmp_path,
        domain="business_research",
        topic="platform_strategy_network_effects",
        profile=profile,
        papers=papers,
    )

    row = json.loads(path.read_text(encoding="utf-8"))["all"][0]
    assert row["paper_count"] == 6
    assert row["fact_source_count"] == 1


def test_business_sweep_metadata_only_fullraw_does_not_handoff_to_submit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    papers = [
        {
            "paper_id": f"metadata-{idx}",
            "title": f"Platform strategy network effects title match {idx}",
            "source_fact": {
                "canonical_phrase": (
                    "Title-level source match: Platform strategy network effects"
                ),
                "endpoint": "source-literature relevance",
                "source_tier": "paper_metadata",
            },
        }
        for idx in range(5)
    ]
    run_cycle_calls = 0

    def fail_run_cycle(**_kwargs: Any) -> dict[str, Any]:
        nonlocal run_cycle_calls
        run_cycle_calls += 1
        return {"status": "published", "submitted": 1, "published": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(
        sweep,
        "_seed_topics",
        lambda _path, *, limit: ["platform_strategy_network_effects"],
    )
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed", "http_status": 503}),
    )
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
    monkeypatch.setattr(sweep, "run_cycle", fail_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-28T13-41-06Z",
    ])

    assert sweep.main() == 2

    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json")
        .read_text(encoding="utf-8"),
    )
    row = summary["results"][0]
    assert row["status"] == "no_bundle"
    assert "requires_fact_level_source_synthesis" in row["blockers"]
    assert run_cycle_calls == 0


def test_business_sweep_thin_fact_fullraw_does_not_handoff_to_submit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    papers = [
        {
            "paper_id": f"fullraw-fact-{idx}",
            "title": f"Platform strategy network effects evidence {idx}",
            "source_fact": {
                "canonical_phrase": (
                    "Platform strategy changed network-effect monetization in "
                    f"multi-sided markets {idx}."
                ),
                "population": "multi-sided markets",
                "intervention": "platform strategy",
                "endpoint": "network-effect monetization",
                "source_tier": "fullraw_search",
            },
        }
        for idx in range(2)
    ]
    papers.extend({
        "paper_id": f"fullraw-title-{idx}",
        "title": f"Platform strategy network effects title match {idx}",
    } for idx in range(3))
    run_cycle_calls = 0

    def fail_run_cycle(**_kwargs: Any) -> dict[str, Any]:
        nonlocal run_cycle_calls
        run_cycle_calls += 1
        return {"status": "published", "submitted": 1, "published": 1}

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(
        sweep,
        "_seed_topics",
        lambda _path, *, limit: ["platform_strategy_network_effects"],
    )
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed", "http_status": 503}),
    )
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
    monkeypatch.setattr(sweep, "run_cycle", fail_run_cycle)
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-28T14-11-00Z",
    ])

    assert sweep.main() == 2

    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json")
        .read_text(encoding="utf-8"),
    )
    row = summary["results"][0]
    assert row["status"] == "no_bundle"
    assert row["fullraw_fact_source_count"] == 2
    assert row["fullraw"]["fact_source_count"] == 2
    assert "requires_fact_level_source_synthesis" in row["blockers"]
    assert run_cycle_calls == 0


def test_business_sweep_reports_enriched_fullraw_candidate_fact_source_count(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile = load_domain_profile("business_research")
    raw_papers = [
        {
            "doi": f"10.1000/source-{idx}",
            "title": f"Supply chain resilience performance source {idx}",
        }
        for idx in range(5)
    ]
    enriched_papers = [
        paper | {
            "source_fact": {
                "canonical_phrase": (
                    f"Supply chain resilience changed firm performance in setting {idx}."
                ),
                "population": "firms",
                "intervention": "supply chain resilience",
                "endpoint": "firm performance",
                "source_tier": "fullraw_search",
            },
        }
        for idx, paper in enumerate(raw_papers)
    ]

    monkeypatch.setattr(sweep, "_DOMAINS", ("business_research",))
    monkeypatch.setattr(sweep, "load_domain_profile", lambda _domain: profile)
    monkeypatch.setattr(
        sweep,
        "_seed_topics",
        lambda _path, *, limit: ["supply_chain_resilience_performance"],
    )
    monkeypatch.setattr(
        sweep,
        "fetch_business_facts",
        lambda *_args, **_kwargs: ([], {"status": "failed", "http_status": 503}),
    )
    monkeypatch.setattr(sweep, "_fullraw_search_hits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        sweep,
        "_enrich_fullraw_papers_with_db_facts",
        lambda *_args, **_kwargs: enriched_papers,
    )
    monkeypatch.setattr(sweep, "_strict_fullraw_probe", lambda _topic, **_kwargs: {
        "status": "complete",
        "paper_count": 5,
        "candidate_fact_source_count": 1,
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
        "_papers": raw_papers,
    })
    monkeypatch.setattr(sweep, "run_cycle", lambda **_kwargs: {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
    })
    monkeypatch.setattr(sys, "argv", [
        "run_business_alpha_sweep.py",
        "--cycles", "1",
        "--topics-per-domain", "1",
        "--domains", "business_research",
        "--runs-root", str(tmp_path / "runs"),
        "--submit-after-consistent-passes", "1",
        "--submit-date", "2026-06-29T03-20-00Z",
    ])

    assert sweep.main() == 2

    summary = json.loads(
        (tmp_path / "runs" / "_business_diagnostics" / "latest_sweep.json")
        .read_text(encoding="utf-8"),
    )
    row = summary["results"][0]
    assert row["fullraw_fact_source_count"] == 5
    assert row["fullraw"]["fact_source_count"] == 5
    assert row["fullraw"]["candidate_fact_source_count"] == 5


def test_business_sweep_enriches_fullraw_papers_with_exact_db_facts(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_facts_for_paper(
        *,
        base: str,
        token: str,
        paper_id: str,
        domain: str,
        timeout: float,
        numeric_only: bool = True,
    ) -> list[dict[str, Any]]:
        calls.append((paper_id, numeric_only))
        if paper_id != "W123":
            return []
        return [{
            "id": "fact-1",
            "canonical_phrase": (
                "Platform strategy changed network-effect monetization in "
                "multi-sided markets."
            ),
            "population": "multi-sided markets",
            "intervention": "platform strategy",
            "endpoint": "network-effect monetization",
            "source_tier": "tier2",
        }]

    monkeypatch.setattr(sweep, "_tier2_facts_for_paper", fake_facts_for_paper)
    settings = SimpleNamespace(
        researka_database_url="https://db.test",
        researka_database_token="tok-test",
    )
    papers = [{
        "openalex_id": "https://openalex.org/W123",
        "title": "Platform strategy and network effects in multi-sided markets",
    }]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "platform_strategy_network_effects",
        domain="business_research",
        papers=papers,
        settings=settings,
    )

    assert calls == [("https://openalex.org/W123", True), ("W123", True)]
    assert publish_literature.substantive_fact_count(enriched) == 1
    assert enriched[0]["id"] == "W123"
    assert enriched[0]["source_fact"]["canonical_phrase"].startswith(
        "Platform strategy changed network-effect monetization",
    )


def test_business_sweep_enriches_non_numeric_directional_by_paper_facts(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_facts_for_paper(
        *,
        base: str,
        token: str,
        paper_id: str,
        domain: str,
        timeout: float,
        numeric_only: bool = True,
    ) -> list[dict[str, Any]]:
        calls.append((paper_id, numeric_only))
        if numeric_only:
            return []
        suffix = paper_id.rsplit("/", 1)[-1]
        return [{
            "id": f"fact-{suffix}",
            "canonical_phrase": (
                "Platform strategy network effects improved firm profitability "
                f"in firm sample {suffix}."
            ),
            "population": f"firm sample {suffix}",
            "intervention": "platform strategy network effects",
            "endpoint": "firm profitability",
            "source_tier": "tier2_directional",
        }]

    monkeypatch.setattr(sweep, "_tier2_facts_for_paper", fake_facts_for_paper)
    settings = SimpleNamespace(
        researka_database_url="https://db.test",
        researka_database_token="tok-test",
    )
    papers = [
        {
            "openalex_id": f"https://openalex.org/W{i}",
            "title": (
                "Platform strategy network profitability evidence "
                f"from firms {i}"
            ),
            "journal_name": journal,
        }
        for i, journal in enumerate((
            "Alpha Strategy Review",
            "Beta Management Journal",
            "Gamma Platform Studies",
            "Delta Business Research",
            "Epsilon Market Evidence",
        ), start=1)
    ]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "platform_strategy_network_profitability",
        domain="business_research",
        papers=papers,
        settings=settings,
    )
    ready, reason = sweep._source_literature_ready_papers(
        "platform_strategy_network_profitability",
        "business_research",
        enriched,
    )

    assert reason == "ok"
    assert publish_literature.substantive_fact_count(ready) == 5
    assert publish_literature.source_identity_count(ready, require_substantive=True) == 5
    assert publish_literature.source_outlet_count(ready) == 5
    assert {numeric_only for _paper_id, numeric_only in calls} == {True, False}


def test_business_sweep_enriches_fullraw_article_abstracts_without_metadata_only(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sweep, "_tier2_facts_for_paper", lambda **_kwargs: [])
    settings = SimpleNamespace(
        researka_database_url="https://db.test",
        researka_database_token="tok-test",
    )
    papers = [
        {
            "doi": "10.1000/article",
            "title": (
                "Digital Transformation and Firm Environmental Performance: "
                "Does Managerial Overseas Experience Matter?"
            ),
            "abstract": (
                "Digital transformation and firm environmental performance have "
                "emerged as central topics in corporate sustainability. This paper "
                "examines the impact of digital transformation on firm environmental "
                "performance using a sample of listed firms. Findings show that "
                "digital transformation significantly improves firm environmental "
                "performance."
            ),
        },
        {
            "doi": "10.1000/dataset",
            "title": "Dataset on the Impact of Digital Transformation on Firm Value",
            "abstract": (
                "This dataset contains data from a study examining digital "
                "transformation and firm value."
            ),
        },
    ]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "digital_transformation_firm",
        domain="business_research",
        papers=papers,
        settings=settings,
    )

    assert publish_literature.substantive_fact_count(enriched) == 1
    assert enriched[0]["source_fact"]["source_tier"] == "fullraw_abstract"
    assert enriched[0]["source_fact"]["endpoint"] == "environmental performance"
    assert enriched[0]["source_fact"]["canonical_phrase"].startswith("Findings show")
    assert "source_fact" not in enriched[1]


def test_business_sweep_prefers_result_sentence_for_abstract_source_fact(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sweep, "_tier2_facts_for_paper", lambda **_kwargs: [])
    settings = SimpleNamespace(
        researka_database_url="",
        researka_database_token="",
    )

    def source(
        suffix: str, title: str, outlet: str, phrase: str, endpoint: str,
        *, abstract: str = "",
    ) -> dict[str, Any]:
        return {
            "title": title,
            "doi": f"10.6161/dt-result-{suffix}",
            "journal_name": outlet,
            **({"abstract": abstract} if abstract else {}),
            "source_fact": {
                "canonical_phrase": phrase,
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": endpoint,
                "source_tier": "fullraw_search",
            },
        }

    title_echo = (
        "Effects of digital transformation on firm performance: "
        "The role of IT capabilities and digital orientation"
    )
    papers = [
        source(
            "a", "Digital transformation and firm environmental performance",
            "Alpha Strategy Journal",
            "digital transformation significantly enhances firm environmental performance",
            "environmental performance",
        ),
        source(
            "b", title_echo, "Beta Management Journal", title_echo,
            "firm performance",
            abstract=(
                "However, although IT capabilities play a critical role, the "
                "mechanism driving IT capabilities towards enhanced firm "
                "performance is not fully understood. Results confirm a "
                "positive effect of IT capabilities on firm performance through "
                "the development of a digital orientation and the digital "
                "transformation of the organisation."
            ),
        ),
        source(
            "c", "Digital transformation and return on assets",
            "Gamma Finance Review",
            "digital transformation significantly increases return on assets",
            "return on assets",
        ),
        source(
            "d", "Digital transformation context source one",
            "Delta Operations Review",
            "digital transformation context marker one was documented across firms",
            "context marker one",
        ),
        source(
            "e", "Digital transformation context source two",
            "Epsilon Digital Business",
            "digital transformation context marker two was documented across firms",
            "context marker two",
        ),
    ]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "digital_transformation_firm",
        domain="business_research",
        papers=papers,
        settings=settings,
    )
    ready, reason = sweep._source_literature_ready_papers(
        "digital_transformation_firm",
        "business_research",
        enriched,
    )

    assert reason == "ok"
    assert publish_literature.substantive_fact_count(ready) == 5
    assert publish_literature.source_identity_count(ready, require_substantive=True) == 5
    assert publish_literature.source_outlet_count(ready) == 5
    assert publish_literature._directional_receipt_count(
        ready, "digital_transformation_firm", "business_research",
    ) == 3
    assert any(
        str((paper.get("source_fact") or {}).get("canonical_phrase") or "").startswith(
            "Results confirm a positive effect",
        )
        for paper in ready
    )


def test_business_sweep_resynthesizes_stale_parent_facts_for_child_topic(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sweep, "_tier2_facts_for_paper", lambda **_kwargs: [])
    settings = SimpleNamespace(
        researka_database_url="",
        researka_database_token="",
    )
    papers = [
        {
            "doi": f"10.1000/dt-child-{idx}",
            "title": (
                f"Digital transformation in firm operating systems sample {idx}"
            ),
            "journal_name": journal,
            "abstract": (
                "This study examines digital transformation in firms and tests "
                "whether the transformation changes operating outcomes. Our "
                "findings show that digital transformation improves firm "
                f"performance in operating sample {idx}."
            ),
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation adoption was documented across firms"
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "adoption",
                "source_tier": "parent_topic_fact",
            },
        }
        for idx, journal in enumerate((
            "Alpha Strategy Review",
            "Beta Management Journal",
            "Gamma Platform Studies",
            "Delta Business Research",
            "Epsilon Market Evidence",
        ), start=1)
    ]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "digital_transformation_firm_performance",
        domain="business_research",
        papers=papers,
        settings=settings,
    )
    ready, reason = sweep._source_literature_ready_papers(
        "digital_transformation_firm_performance",
        "business_research",
        enriched,
    )

    assert reason == "ok"
    assert publish_literature.substantive_fact_count(ready) == 5
    assert publish_literature.source_identity_count(ready, require_substantive=True) == 5
    assert publish_literature.source_outlet_count(ready) == 5
    assert {
        paper["source_fact"]["source_tier"] for paper in ready
    } == {"fullraw_abstract"}
    assert all(
        publish_literature._topic_token_coverage(
            "digital_transformation_firm_performance",
            paper,
        ) == 4
        for paper in ready
    )


def test_business_sweep_backfills_crossref_abstracts_and_strips_markup(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("BUSINESS_SWEEP_PUBMED_ABSTRACT_BACKFILL_LIMIT", raising=False)
    monkeypatch.delenv("RESEARKA_FULLRAW_DOI_ABSTRACT_BACKFILL_LIMIT", raising=False)
    monkeypatch.setattr(sweep, "_tier2_facts_for_paper", lambda **_kwargs: [])
    monkeypatch.setattr(sweep, "_fetch_pubmed_abstract", lambda *_args: "")
    monkeypatch.setattr(
        sweep,
        "_fetch_crossref_abstract",
        lambda *_args: (
            "<jats:p>The research findings reveal that visibility significantly "
            "influences supply chain resilience and firm performance.</jats:p>"
        ),
    )
    settings = SimpleNamespace(
        researka_database_url="https://db.test",
        researka_database_token="tok-test",
    )
    papers = [{
        "doi": "10.1000/article",
        "title": (
            "The Impacts of Supply Chain Capabilities, Visibility, Resilience "
            "on Supply Chain Performance and Firm Performance"
        ),
    }]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "supply_chain_resilience_performance",
        domain="business_research",
        papers=papers,
        settings=settings,
    )

    fact = enriched[0]["source_fact"]
    assert publish_literature.substantive_fact_count(enriched) == 1
    assert fact["canonical_phrase"].startswith("The research findings reveal")
    assert "<jats" not in fact["canonical_phrase"]


def test_business_sweep_backfills_pubmed_abstract_for_title_only_fullraw(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def fake_fetch(pmid: str, _settings: Any) -> str:
        calls.append(pmid)
        return (
            "Results show that digital transformation significantly improves "
            "firm performance among small and medium enterprises."
        )

    monkeypatch.setenv("BUSINESS_SWEEP_PUBMED_ABSTRACT_BACKFILL_LIMIT", "1")
    monkeypatch.setattr(sweep, "_fetch_pubmed_abstract", fake_fetch)
    settings = SimpleNamespace(
        researka_database_url="",
        researka_database_token="",
        ncbi_api_key="",
    )
    papers = [{
        "pmid": "38509885",
        "title": (
            "Effects of digital transformation on firm performance: "
            "The role of IT capabilities and digital orientation"
        ),
    }]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "digital_transformation_firm",
        domain="business_research",
        papers=papers,
        settings=settings,
    )

    assert calls == ["38509885"]
    assert publish_literature.substantive_fact_count(enriched) == 1
    assert enriched[0]["abstract"].startswith("Results show")
    assert enriched[0]["source_fact"]["source_tier"] == "fullraw_abstract"
    assert enriched[0]["source_fact"]["endpoint"] == "firm performance"


def test_business_sweep_backfills_crossref_abstract_for_doi_only_fullraw(
    monkeypatch: Any,
) -> None:
    crossref_calls: list[str] = []

    def fake_crossref(doi: str, _settings: Any) -> str:
        crossref_calls.append(doi)
        return (
            "Empirical results indicate that digital transformation improves "
            "firm profitability in listed firms."
        )

    monkeypatch.setenv("BUSINESS_SWEEP_PUBMED_ABSTRACT_BACKFILL_LIMIT", "1")
    monkeypatch.setattr(sweep, "_fetch_pubmed_abstract", lambda *_args: "")
    monkeypatch.setattr(sweep, "_fetch_crossref_abstract", fake_crossref)
    settings = SimpleNamespace(
        researka_database_url="",
        researka_database_token="",
        crossref_polite_email="",
    )
    papers = [{
        "doi": "10.64753/jcasc.v10i4.3152",
        "title": "The Impact of Digital Transformation on Firm Profitability",
    }]

    enriched = sweep._enrich_fullraw_papers_with_db_facts(
        "digital_transformation_firm",
        domain="business_research",
        papers=papers,
        settings=settings,
    )

    assert crossref_calls == ["10.64753/jcasc.v10i4.3152"]
    assert publish_literature.substantive_fact_count(enriched) == 1
    assert enriched[0]["abstract"].startswith("Empirical results indicate")
    assert enriched[0]["source_fact"]["endpoint"] == "firm profitability"


def test_business_sweep_abstract_fact_prefers_results_over_methods() -> None:
    paper = {
        "doi": "10.1000/digital-result",
        "title": (
            "Digital Transformation and Firm Environmental Performance: "
            "Does Managerial Overseas Experience Matter?"
        ),
        "abstract": (
            "This paper aims to address this gap by examining the impact of "
            "digital transformation on firm environmental performance. "
            "Using a sample of Chinese listed companies from 2011 to 2021, "
            "we employ robust econometric models to analyse the effects and "
            "variations across firms. Our findings reveal that digital "
            "transformation significantly enhances firm environmental performance."
        ),
    }

    fact = sweep._abstract_source_fact("digital_transformation_firm", paper)

    assert fact is not None
    assert fact["canonical_phrase"].startswith("Our findings reveal")
    assert "Using a sample" not in fact["canonical_phrase"]


def test_business_sweep_abstract_fact_uses_downstream_effect_endpoint() -> None:
    paper = {
        "doi": "10.5267/j.uscm.2022.8.001",
        "title": (
            "The effect of supply chain resilience on supply chain performance "
            "of chemical industrial companies"
        ),
        "abstract": (
            "The aim of this study is to identify the effect of supply chain "
            "resilience as measured by supply chain flexibility, supply chain "
            "collaboration, and supply chain agility on supply chain performance. "
            "The findings show that supply chain resilience positively affects "
            "supply chain performance."
        ),
    }

    fact = sweep._abstract_source_fact("supply_chain_resilience_performance", paper)

    assert fact is not None
    assert fact["endpoint"] == "supply chain performance"
    assert fact["endpoint"] != "supply chain resilience"
    assert fact["canonical_phrase"].startswith("The findings show")
    assert "aim of this study" not in fact["canonical_phrase"].lower()


def test_source_literature_selection_keeps_substantive_facts_ahead_of_metadata() -> None:
    papers = [
        {
            "doi": f"10.1000/meta-{idx}",
            "title": title,
            "source_fact": {
                "canonical_phrase": f"Title-level source match: {title}",
                "endpoint": "source-literature relevance",
                "source_tier": "paper_metadata",
            },
        }
        for idx, title in enumerate([
            "Dataset on the Impact of Digital Transformation on Firm Value",
            "Digital transformation firm source material",
            "Digital transformation and firm performance metadata",
            "Digital transformation and firm profitability metadata",
        ], 1)
    ]
    papers.extend([
        {
            "doi": "10.1000/article-1",
            "title": (
                "Digital Transformation and Firm Environmental Performance: "
                "Does Managerial Overseas Experience Matter?"
            ),
            "source_fact": {
                "canonical_phrase": (
                    "Digital transformation changed firm environmental performance "
                    "conditional on managerial overseas experience."
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "environmental performance",
                "source_tier": "fullraw_abstract",
            },
        },
        {
            "doi": "10.1000/article-2",
            "title": (
                "Assessing the mediating role of human capital in the relationship "
                "between digital transformation and firm performance"
            ),
            "source_fact": {
                "canonical_phrase": (
                    "Digital transformation related to firm performance through "
                    "human capital mediation."
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
                "source_tier": "fullraw_abstract",
            },
        },
    ])

    selected = publish_literature.select_boundary_papers(
        "digital_transformation_firm",
        papers,
        5,
        strict_topic_coverage=True,
    )

    assert publish_literature.substantive_fact_count(selected) == 2
    assert [paper["doi"] for paper in selected[:2]] == [
        "10.1000/article-1",
        "10.1000/article-2",
    ]


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
    assert "[business-sweep] end_summary=" in out
    assert '"public_url_status": null' in out
    assert '"top_blockers": {"submitted_to_researka": 1}' in out
    artifact = tmp_path / "runs" / "_daily_ledger" / "business_alpha_sweep_summary.json"
    sweep_summary = json.loads(artifact.read_text(encoding="utf-8"))
    assert sweep_summary["submitted"] == 1
    assert sweep_summary["published"] == 0
    assert sweep_summary["public_url_status"] == {"management_research": None}
    assert sweep_summary["next_action"] == "watch_decision_or_public_page"


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


def test_business_source_literature_blocks_title_echo_fact_bundle() -> None:
    papers = [
        {
            "title": "Digital Transformation and Firm Environmental Performance",
            "doi": "10.17323/example-env",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly enhances firm environmental "
                    "performance"
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "environmental performance",
            },
        },
        {
            "title": "Effects of digital transformation on firm performance",
            "doi": "10.1016/example-title",
            "source_fact": {
                "canonical_phrase": "Effects of digital transformation on firm performance",
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
            },
        },
        {
            "title": "Digital transformation and next generation services",
            "doi": "10.1108/example-services",
            "source_fact": {
                "canonical_phrase": (
                    "71 percent of banking firms report that big data provides "
                    "competitive advantage"
                ),
                "population": "banking firms",
                "intervention": "big data use",
                "endpoint": "competitive advantage",
            },
        },
        {
            "title": "Human capital in digital transformation",
            "doi": "10.1108/example-human-capital",
            "source_fact": {
                "canonical_phrase": (
                    "digital capabilities and management support substantially affect "
                    "digital transformation"
                ),
                "population": "firms",
                "intervention": "digital transformation",
                "endpoint": "firm performance",
            },
        },
        {
            "title": "The impact of digital transformation on firm profitability",
            "doi": "10.64753/example-profit",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases return on assets"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "firm profitability",
            },
        },
    ]

    selected = publish_literature.select_boundary_papers(
        "digital_transformation_firm",
        papers,
        5,
        strict_topic_coverage=True,
    )
    assert len(selected) == 5
    assert publish_literature.substantive_fact_count(selected) == 4

    ready, reason = sweep._source_literature_ready_papers(
        "digital_transformation_firm", "business_research", papers,
    )

    assert ready == []
    assert reason == "requires_fact_level_source_synthesis"


def test_business_source_literature_blocks_two_directional_fact_backed_map() -> None:
    papers = [
        {
            "title": "Digital transformation and firm profitability",
            "doi": "10.5555/dt-profit",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases firm profitability"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "firm profitability",
            },
        },
        {
            "title": "Digital transformation and return on assets",
            "doi": "10.5555/dt-roa",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases return on assets"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "return on assets",
            },
        },
        *[
            {
                "title": [
                    "Digital transformation in firm operating models",
                    "Firm digital transformation governance map",
                    "Enterprise digital transformation adoption context",
                ][idx - 1],
                "doi": f"10.5555/dt-context-{idx}",
                "source_fact": {
                    "canonical_phrase": (
                        f"implementation scope marker {idx} was documented across firms"
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": f"context marker {idx}",
                },
            }
            for idx in range(1, 4)
        ],
    ]

    ok, reason = publish_literature.boundary_quality(
        "digital_transformation_firm",
        papers,
        5,
        strict_topic_coverage=True,
        profile_slug="business_research",
    )

    assert not ok
    assert reason == "directional_receipt_floor_below_min"
    ready, ready_reason = sweep._source_literature_ready_papers(
        "digital_transformation_firm", "business_research", papers,
    )
    assert len(ready) == 5
    assert ready_reason == "directional_receipt_floor_below_min"


def test_business_source_literature_allows_three_directional_fact_backed_map() -> None:
    papers = [
        {
            "title": "Digital transformation and firm profitability",
            "doi": "10.5555/dt-profit",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases firm profitability"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "firm profitability",
            },
        },
        {
            "title": "Digital transformation and return on assets",
            "doi": "10.5555/dt-roa",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases return on assets"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "return on assets",
            },
        },
        {
            "title": "Digital transformation and operating margin",
            "doi": "10.5555/dt-margin",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases operating margin"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "operating margin",
            },
        },
        *[
            {
                "title": [
                    "Digital transformation in firm operating models",
                    "Firm digital transformation governance map",
                ][idx - 1],
                "doi": f"10.5555/dt-context-{idx}",
                "source_fact": {
                    "canonical_phrase": (
                        f"implementation scope marker {idx} was documented across firms"
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": f"context marker {idx}",
                },
            }
            for idx in range(1, 3)
        ],
    ]

    ok, reason = publish_literature.boundary_quality(
        "digital_transformation_firm",
        papers,
        5,
        strict_topic_coverage=True,
        profile_slug="business_research",
    )

    assert ok
    assert reason == "ok"


def test_business_source_literature_blocks_one_directional_receipt() -> None:
    papers = [
        {
            "title": "Digital transformation and firm profitability",
            "doi": "10.5555/dt-profit",
            "source_fact": {
                "canonical_phrase": (
                    "digital transformation significantly increases firm profitability"
                ),
                "population": "listed firms",
                "intervention": "digital transformation",
                "endpoint": "firm profitability",
            },
        },
        *[
            {
                "title": [
                    "Digital transformation in firm operating models",
                    "Firm digital transformation governance map",
                    "Enterprise digital transformation adoption context",
                    "Digital transformation adoption scope in firms",
                ][idx - 1],
                "doi": f"10.5555/dt-context-{idx}",
                "source_fact": {
                    "canonical_phrase": (
                        f"implementation scope marker {idx} was documented across firms"
                    ),
                    "population": "firms",
                    "intervention": "digital transformation",
                    "endpoint": f"context marker {idx}",
                },
            }
            for idx in range(1, 5)
        ],
    ]

    ok, reason = publish_literature.boundary_quality(
        "digital_transformation_firm",
        papers,
        5,
        strict_topic_coverage=True,
        profile_slug="business_research",
    )

    assert not ok
    assert reason == "directional_receipt_floor_below_min"


def test_business_source_literature_counts_significant_metric_change_directional() -> None:
    paper = {
        "title": "Digital transformation and firm profitability",
        "doi": "10.5555/dt-profit",
        "source_fact": {
            "canonical_phrase": "digital transformation significantly increases firm profitability",
            "population": "listed firms",
            "intervention": "digital transformation",
            "endpoint": "firm profitability",
        },
    }

    assert publish_literature._paper_evidence_role(
        paper,
        "digital_transformation_firm",
        "business_research",
    ) == "directional association"


def test_business_source_literature_counts_significant_enhancement_directional() -> None:
    paper = {
        "title": "Digital Transformation and Firm Environmental Performance",
        "doi": "10.5555/dt-environment",
        "source_fact": {
            "canonical_phrase": (
                "digital transformation significantly enhances firm environmental performance"
            ),
            "population": "firms",
            "intervention": "digital transformation",
            "endpoint": "firm environmental performance",
        },
    }

    assert publish_literature._paper_effect_direction(
        paper,
        "digital_transformation_firm",
    ) == "other/mixed"
    assert publish_literature._paper_evidence_role(
        paper,
        "digital_transformation_firm",
        "business_research",
    ) == "directional association"


def test_business_source_literature_does_not_treat_improves_as_method_only() -> None:
    paper = {
        "title": "Business model performance source paper",
        "doi": "10.5555/business-model-performance",
        "source_fact": {
            "canonical_phrase": (
                "Business model changes significantly improve bounded firm "
                "performance outcomes in source setting 1."
            ),
            "population": "firms",
            "intervention": "business model changes",
            "endpoint": "firm performance",
        },
    }

    assert publish_literature._paper_evidence_role(
        paper,
        "business_model_performance",
        "business_research",
    ) == "directional association"


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
        assert "EnvironmentFile=/etc/researka-fullraw.env" in service
        assert "researka-fullraw-search.service" in service
        assert "Environment=TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_WAIT_SECONDS=" not in service
        assert "Environment=TOPIC_DISCOVERY_BUSINESS_FULLRAW_FOREGROUND_SECONDS=" not in service
        assert "Environment=TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS=" not in service
        assert "Environment=V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS=" not in service
        assert "Environment=V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS=" not in service
        assert "TimeoutStartSec=7200" in service
        assert f"OnCalendar=*-*-* {schedule}" in timer
