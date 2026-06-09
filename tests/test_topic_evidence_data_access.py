"""Locks the alpha evidence run's Researka DB access order.

Universal: tests endpoint contracts and fallback behavior only.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from agent.settings import load_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_topic_evidence_run as evidence_run
import daily_alpha_publish_cycle as daily


def _settings() -> Any:
    return replace(
        load_settings(),
        researka_database_url="https://database.researka.org",
        researka_database_token="token",
    )


def _fact(fid: str, doi: str, *, bindable: bool = True) -> dict[str, Any]:
    out = {
        "id": fid,
        "paper": {
            "doi": doi,
            "title": f"Paper {fid}",
            "publication_year": 2026,
            "journal_name": "Journal",
        },
        "claim_type": "effect_size",
        "numeric_value": 10,
        "units": "%",
        "extraction_confidence": "high",
        "canonical_phrase": f"topicA signal {fid}",
    }
    if bindable:
        out["population"] = "adults"
        out["intervention"] = "topicA"
    return out


def _tier1_fact(fid: str, doi: str) -> dict[str, Any]:
    return {
        "fact_id": fid,
        "source_paper": {"doi": doi, "title": f"Paper {fid}"},
        "numeric_value": 10,
        "units": "%",
        "canonical_phrase": f"MK-7 signal {fid}",
        "population": "adults",
        "intervention": "MK-7",
    }


def _ai_result_bundle() -> dict[str, Any]:
    receipts = []
    for i in range(5):
        receipts.append({
            "id": 100 + i,
            "paper_id": f"paper-{i}",
            "paper": {
                "doi": f"10.5555/ai-{i}",
                "title": f"AI benchmark paper {i}",
                "publication_year": 2026,
                "journal_name": "ArXiv",
            },
            "claim_type": "effect_size",
            "numeric_value": 70 + i,
            "units": "%",
            "canonical_phrase": (
                f"Model {i} achieves {70 + i}% accuracy on GSM8K."
            ),
            "topic": "llm_evaluation",
            "benchmark": "GSM8K",
            "task": "math reasoning",
            "dataset": "GSM8K",
            "metric": "accuracy",
            "model_system": f"Model {i}",
            "baseline_comparator": f"baseline {i}",
            "evaluation_protocol": "matched-budget evaluation",
            "source_identifiers": {"doi": f"10.5555/ai-{i}"},
            "validation": {"status": "exact"},
        })
    return {
        "result_key": "llm_evaluation::gsm8k::accuracy",
        "topic": "llm_evaluation",
        "shape": {
            "benchmark": "GSM8K",
            "task": "math reasoning",
            "dataset": "GSM8K",
            "metric": "accuracy",
            "evaluation_protocol": "matched-budget evaluation",
        },
        "papers": 5,
        "complete_papers": 5,
        "ready_for_queue": True,
        "receipts": receipts,
    }


def _mock_client(monkeypatch: Any, handler: Any) -> None:
    real_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "Client", factory)
    monkeypatch.setattr(evidence_run, "load_settings", _settings)


def test_fetch_facts_strict_first_then_normal_until_source_floor(
    monkeypatch: Any,
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/api/v1/topics/topicA/facts"
            assert request.url.params.get("validated_only") == "true"
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("strict_audit_required"):
            return httpx.Response(200, json=[_fact("strict", "10.1/strict")])
        return httpx.Response(
            200,
            json=[_fact(f"normal-{i}", f"10.1/normal-{i}") for i in range(5)],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    assert bodies[0]["strict_audit_required"] is True
    assert bodies[0]["numeric_only"] is True
    # Strict probes run first; the diverse outcome queries then widen into
    # normal (non-strict) queries to gather a broader base than the floor.
    assert any(b.get("strict_audit_required") is None for b in bodies)
    assert evidence_run._source_count(facts) == 6
    assert evidence_run._a_core_source_count(facts, "topicA") == 6


def test_ai_research_fetch_uses_result_bundles_before_tier2_search(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/v1/ai/results/search":
            return httpx.Response(200, json=[_ai_result_bundle()])
        raise AssertionError("tier2 fallback should not run when bundle is ready")

    _mock_client(monkeypatch, handler)
    trace: list[dict[str, Any]] = []

    facts = evidence_run._fetch_facts(
        "llm_evaluation", trace=trace, domain="ai_research",
    )

    assert [path for path, _body in calls] == ["/api/v1/ai/results/search"]
    assert calls[0][1] == {
        "query": "llm_evaluation",
        "limit": 20,
        "min_sources": 5,
        "receipts_per_bundle": 5,
        "require_complete_axes": True,
    }
    assert len(facts) == 5
    assert evidence_run._source_count(facts) == 5
    assert facts[0]["_tier"] == "ai_results_index"
    assert facts[0]["result_key"] == "llm_evaluation::gsm8k::accuracy"
    assert facts[0]["population"] == "llm_evaluation GSM8K math reasoning GSM8K"
    assert facts[0]["intervention"] == "Model 0"
    assert facts[0]["comparator"] == "baseline 0"
    assert facts[0]["endpoint"] == "accuracy"
    assert facts[0]["reported_model_system"] == "Model 0"
    assert facts[0]["reported_baseline_comparator"] == "baseline 0"
    assert facts[0]["result_shape"] == {
        "benchmark": "GSM8K",
        "task": "math reasoning",
        "dataset": "GSM8K",
        "metric": "accuracy",
        "evaluation_protocol": "matched-budget evaluation",
        "model_system": "GSM8K systems",
        "baseline_comparator": "GSM8K benchmark baselines",
    }
    assert trace == [{
        "kind": "ai_results_index",
        "query": "llm_evaluation",
        "facts": 5,
        "status": "ok",
        "errors": [],
    }]


def test_ai_research_fetch_tries_result_bundle_alias_before_tier2_search(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = str(body.get("query") or "")
        calls.append((request.url.path, query))
        if request.url.path == "/api/v1/ai/results/search":
            return httpx.Response(
                200, json=[_ai_result_bundle()] if query == "rag" else [],
            )
        raise AssertionError("tier2 fallback should not run when alias bundle is ready")

    _mock_client(monkeypatch, handler)
    trace: list[dict[str, Any]] = []

    facts = evidence_run._fetch_facts(
        "retrieval_augmented_generation", trace=trace, domain="ai_research",
    )

    assert calls == [
        ("/api/v1/ai/results/search", "retrieval_augmented_generation"),
        ("/api/v1/ai/results/search", "retrieval augmented generation"),
        ("/api/v1/ai/results/search", "rag"),
    ]
    assert len(facts) == 5
    assert {row["query"]: row["facts"] for row in trace} == {
        "retrieval_augmented_generation": 0,
        "retrieval augmented generation": 0,
        "rag": 5,
    }


def test_ai_research_fetch_falls_back_when_result_bundle_missing(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(evidence_run, "_topic_fact_keys", lambda _t: [])
    monkeypatch.setattr(evidence_run, "_diverse_queries", lambda _t, **_kw: ["topicA"])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/ai/results/search":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[_fact("normal", "10.1/normal")],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA", domain="ai_research")

    assert calls[0] == "/api/v1/ai/results/search"
    assert "/api/v1/tier2/facts/search" in calls
    assert [fact["fact_id"] for fact in facts] == ["normal"]


def test_ai_result_bundle_receipts_pass_generic_shape_gate(tmp_path: Path) -> None:
    facts = evidence_run._facts_from_ai_result_bundles(
        [_ai_result_bundle()], "llm_evaluation", min_sources=5,
    )
    root = tmp_path / "repo"
    run = root / "runs" / "llm_evaluation-evidence-ts"
    run.mkdir(parents=True)
    ids = [str(fact["fact_id"]) for fact in facts]
    run.joinpath("alpha_memo.md").write_text(
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n",
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in ids],
    }), encoding="utf-8")
    verdict = {"run_dir": "runs/llm_evaluation-evidence-ts"}

    assert daily._direct_receipts_share_shape(verdict, root / "runs", 5) is True


def test_normalize_tier2_preserves_ai_structured_fields() -> None:
    item = _fact("ai-1", "10.ai/1") | {
        "topic": "swe_bench",
        "benchmark": "SWE-bench Verified",
        "fact": {
            "metric": "resolve rate",
            "task": "software engineering issue resolution",
            "dataset": "SWE-bench Verified",
            "model_system": "AgentX",
            "baseline_comparator": "baseline agent",
            "evaluation_protocol": "zero shot patch generation",
            "source_identifiers": {"arxiv_id": "2601.1"},
            "artifact_url": "https://github.com/example/agentx",
            "limitation": "single benchmark",
            "source_excerpt": "AgentX achieved 42% resolve rate.",
        },
    }

    fact = evidence_run._normalize_tier2(item, "swe_bench")

    assert fact["benchmark"] == "SWE-bench Verified"
    assert fact["metric"] == "resolve rate"
    assert fact["task"] == "software engineering issue resolution"
    assert fact["dataset"] == "SWE-bench Verified"
    assert fact["model_system"] == "AgentX"
    assert fact["baseline_comparator"] == "baseline agent"
    assert fact["evaluation_protocol"] == "zero shot patch generation"
    assert fact["source_identifiers"] == {"arxiv_id": "2601.1"}
    assert fact["artifact_url"] == "https://github.com/example/agentx"
    assert fact["limitation"] == "single benchmark"
    assert fact["source_topic"] == "swe_bench"


def test_normalize_tier2_preserves_ai_axis_aliases() -> None:
    fact = evidence_run._normalize_tier2(
        _fact("alias", "10.ai/alias") | {
            "topic": "llm_eval",
            "fact": {
                "task_or_benchmark": "LoCoMo",
                "metric": "accuracy",
                "model_system": "memory agents",
                "baseline_or_comparator": "published baselines",
                "evaluation_protocol": "reported benchmark evaluation",
            },
        },
        "llm_eval",
    )

    assert fact["benchmark"] == "LoCoMo"
    assert fact["task"] == "LoCoMo"
    assert fact["baseline_comparator"] == "published baselines"


def test_ai_research_tier2_fallback_rejects_mixed_model_axis_shelf(
    tmp_path: Path,
) -> None:
    facts: list[dict[str, Any]] = []
    for i in range(5):
        facts.append(evidence_run._normalize_tier2(
            _fact(f"swe-{i}", f"10.ai/swe-{i}") | {
                "topic": "swe_bench",
                "benchmark": "SWE-bench Verified",
                "fact": {
                    "metric": "resolve rate",
                    "task": "SWE-bench Verified",
                    "dataset": "SWE-bench Verified",
                    "model_system": f"agent system {i}",
                    "baseline_comparator": f"baseline {i}",
                    "canonical_phrase": (
                        f"Agent system {i} reports SWE-bench resolve rate."
                    ),
                },
            },
            "swe_bench_success",
        ))
    facts.append(evidence_run._normalize_tier2(
        _fact("mmlu", "10.ai/mmlu") | {
            "topic": "mmlu",
            "benchmark": "MMLU",
            "fact": {"metric": "accuracy", "task": "MMLU"},
        },
        "swe_bench_success",
    ))

    coherent = evidence_run._ai_axis_coherent_facts(
        facts, "swe_bench_success", min_sources=5,
    )

    assert coherent == []


def test_ai_research_tier2_fallback_extracts_same_model_axis_shelf(
    tmp_path: Path,
) -> None:
    facts: list[dict[str, Any]] = []
    for i in range(5):
        facts.append(evidence_run._normalize_tier2(
            _fact(f"swe-{i}", f"10.ai/swe-{i}") | {
                "topic": "swe_bench",
                "benchmark": "SWE-bench Verified",
                "fact": {
                    "metric": "resolve rate",
                    "task": "SWE-bench Verified",
                    "dataset": "SWE-bench Verified",
                    "model_system": "AgentX",
                    "baseline_comparator": "baseline agent",
                    "evaluation_protocol": "matched-budget evaluation",
                    "canonical_phrase": (
                        "AgentX reports SWE-bench resolve rate against baseline agent."
                    ),
                },
            },
            "swe_bench_success",
        ))
    facts.append(evidence_run._normalize_tier2(
        _fact("mmlu", "10.ai/mmlu") | {
            "topic": "mmlu",
            "benchmark": "MMLU",
            "fact": {"metric": "accuracy", "task": "MMLU"},
        },
        "swe_bench_success",
    ))

    coherent = evidence_run._ai_axis_coherent_facts(
        facts, "swe_bench_success", min_sources=5,
    )

    assert len(coherent) == 5
    assert evidence_run._source_count(coherent) == 5
    assert {fact["benchmark"] for fact in coherent} == {"SWE Bench Verified"}
    assert {fact["metric"] for fact in coherent} == {"Resolve Rate"}
    assert {fact["model_system"] for fact in coherent} == {"Agentx"}
    assert {fact["baseline_comparator"] for fact in coherent} == {"Baseline Agent"}
    assert all(fact.get("reported_model_system") for fact in coherent)
    lanes = {
        verdict.fact_id: verdict.lane
        for verdict in evidence_run.classify_lanes(coherent, "swe_bench_success")
    }
    assert set(lanes.values()) == {"A_core"}
    assert len(evidence_run._rankable_facts_for_top(
        coherent, "swe_bench_success",
    )) == 5

    root = tmp_path / "repo"
    run = root / "runs" / "swe_bench_success-evidence-ts"
    run.mkdir(parents=True)
    ids = [str(fact["fact_id"]) for fact in coherent]
    run.joinpath("alpha_memo.md").write_text(
        "## Evidence receipts\n\n"
        + "\n".join(f"- `fact_id={fid}` (`A_core`) - receipt" for fid in ids)
        + "\n",
        encoding="utf-8",
    )
    run.joinpath("all_facts.json").write_text(
        json.dumps(coherent), encoding="utf-8",
    )
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": fid, "lane": "A_core"} for fid in ids],
    }), encoding="utf-8")

    assert daily._direct_receipts_share_shape(
        {"run_dir": "runs/swe_bench_success-evidence-ts"}, root / "runs", 5,
    ) is True


def test_fetch_facts_widens_when_strict_sources_are_not_direct_bindable(
    monkeypatch: Any,
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("strict_audit_required"):
            return httpx.Response(
                200,
                json=[_fact(f"strict-{i}", f"10.1/strict-{i}", bindable=False)
                      for i in range(5)],
            )
        return httpx.Response(
            200,
            json=[_fact(f"normal-{i}", f"10.1/normal-{i}") for i in range(5)],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    # Strict sources are non-bindable, so the fetch widens into normal queries.
    assert bodies[0]["strict_audit_required"] is True
    assert any(b.get("strict_audit_required") is None for b in bodies)
    assert evidence_run._source_count(facts) == 10
    assert evidence_run._a_core_source_count(facts, "topicA") == 5


def test_fetch_facts_caps_strict_synonym_probes_before_normal(
    monkeypatch: Any,
) -> None:
    bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        evidence_run, "expand_topic_queries",
        lambda _topic, max_queries=16: ("topicA", "q1", "q2", "q3", "q4"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("strict_audit_required"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[_fact(f"normal-{i}", f"10.1/normal-{i}") for i in range(5)],
        )

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    strict_count = sum(1 for b in bodies if b.get("strict_audit_required") is True)
    normal_count = sum(1 for b in bodies if b.get("strict_audit_required") is None)
    assert strict_count == 2
    assert normal_count >= 1
    assert evidence_run._a_core_source_count(facts, "topicA") == 5


def test_fetch_facts_falls_back_when_strict_endpoint_rejects_flag(
    monkeypatch: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={"detail": "not found"})
        body = json.loads(request.content)
        if body.get("strict_audit_required"):
            return httpx.Response(422, json={"detail": "unknown flag"})
        return httpx.Response(200, json=[_fact("normal", "10.1/normal")])

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("topicA")

    assert [f["fact_id"] for f in facts] == ["normal"]


def test_fetch_facts_respects_total_budget(monkeypatch: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("fact fetch should not call DB after budget expires")

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(evidence_run, "_FACT_FETCH_BUDGET_SECONDS", 0.0)

    assert evidence_run._fetch_facts("topicA") == []


def test_select_tier2_items_filters_with_expanded_topic_queries() -> None:
    items = [
        {
            "canonical_phrase": "vitamin D changed mortality by 8%",
            "paper": {"title": "Vitamin D trial"},
        },
        {
            "canonical_phrase": "MK-7 reduced vascular calcification by 12%",
            "paper": {"title": "Menaquinone and vascular calcification"},
        },
    ]

    selected = evidence_run._select_tier2_items(
        items, "vitamin_K2_vascular_aging",
    )

    assert selected == [items[1]]


def test_select_tier2_items_keeps_synonym_match_in_pico_fields() -> None:
    items = [{
        "canonical_phrase": "Arterial stiffness changed by 12%",
        "intervention": "MK-7",
        "population": "older adults",
        "paper": {"title": "Cardiovascular trial"},
    }]

    selected = evidence_run._select_tier2_items(
        items, "vitamin_K2_vascular_aging",
    )

    assert selected == items


def test_fetch_facts_queries_tier1_synonym_topic_keys(monkeypatch: Any) -> None:
    post_bodies: list[dict[str, Any]] = []
    get_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            get_paths.append(request.url.path)
            if request.url.path == "/api/v1/topics/vitamin_k2/facts":
                return httpx.Response(
                    200,
                    json=[_tier1_fact(f"t1-{i}", f"10.1/tier1-{i}") for i in range(5)],
                )
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        post_bodies.append(body)
        return httpx.Response(200, json=[])

    _mock_client(monkeypatch, handler)

    facts = evidence_run._fetch_facts("vitamin_K2_vascular_aging")

    assert "/api/v1/topics/vitamin_k2/facts" in get_paths
    # Strict audited probe runs first; widening then adds normal queries.
    assert post_bodies[0].get("strict_audit_required") is True
    assert evidence_run._a_core_source_count(
        facts, "vitamin_K2_vascular_aging",
    ) == 5


def test_diverse_queries_add_data_derived_facets() -> None:
    """The fetch can widen beyond near-duplicate name queries without static slices."""
    qs = evidence_run._diverse_queries(
        "rapamycin", facets=("mammalian lifespan", "immune function"),
    )
    assert "rapamycin" in qs
    assert "mammalian lifespan" in qs
    assert "immune function" in qs
    assert not any(q == "rapamycin mortality" for q in qs)
    # materially more than the bare name variants that returned the same facts
    assert len(qs) > len(evidence_run.expand_topic_queries("rapamycin", max_queries=16))


def test_fetch_merges_and_dedups_distinct_slice_results(monkeypatch: Any) -> None:
    """Each targeted slice returns DIFFERENT facts; the merged+deduped result is
    materially larger than any single query's yield (the under-fetch fix)."""
    fired: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        q = json.loads(request.content)["query"]
        fired.append(q)
        slug = q.replace(" ", "_")
        # query-specific facts, plus one shared fact to prove dedup works
        if q == "topicA":
            return httpx.Response(200, json=[
                _fact("seed", "10.1/seed") | {
                    "paper": {"doi": "10.1/seed", "title": "topicA reserve reliability"},
                },
                _fact("shared", "10.1/shared"),
            ])
        return httpx.Response(200, json=(
            [_fact(f"{slug}-{i}", f"10.1/{slug}-{i}") for i in range(3)]
            + [_fact("shared", "10.1/shared")]
        ))

    _mock_client(monkeypatch, handler)
    facts = evidence_run._fetch_facts("topicA")

    assert "reserve reliability" in fired  # source-title facet was queried
    assert sum(1 for f in facts if f["fact_id"] == "shared") == 1  # deduped
    # old name-only path yielded ~2 sources; title facets yield more.
    assert evidence_run._source_count(facts) >= 5


def test_fetch_papers_merges_elite_topic_and_broad_search(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/v1/papers/topic":
            return httpx.Response(200, json=[{"doi": "10.1/a", "title": "Elite paper"}])
        return httpx.Response(200, json={
            "established": [{"doi": "10.1/a", "title": "Duplicate"}],
            "discovery": [{"doi": "10.1/b", "title": "Broad paper"}],
            "semantic": [],
        })

    _mock_client(monkeypatch, handler)

    papers = evidence_run._fetch_papers("topicA")

    assert calls == [
        ("/api/v1/papers/topic", {"topic": "topicA", "limit": 25}),
        ("/api/v1/search", {
            "query": "topicA",
            "established_k": 8,
            "discovery_k": 8,
            "semantic_k": 8,
        }),
    ]
    assert [p["doi"] for p in papers] == ["10.1/a", "10.1/b"]


def test_fetch_papers_uses_expanded_topic_queries(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/v1/papers/topic":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    _mock_client(monkeypatch, handler)

    assert evidence_run._fetch_papers("vitamin_K2_vascular_aging") == []

    assert ("/api/v1/papers/topic", {"topic": "vitamin_k2", "limit": 25}) in calls
    assert any(
        path == "/api/v1/search" and body.get("query") == "vitamin k2"
        for path, body in calls
    )
