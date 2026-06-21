"""Publish-tier gate tests.

Fixtures are non-biomedical. The gate should classify by structure:
binding, source concentration, tension, and cross-domain coherence.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import publish_tier as tier
from agent.publish_tier import publish_verdict, write_publish_verdict


def _run(
    root: Path,
    *,
    label: str = "evidence_backed_signal",
    score: int = 80,
    lanes: tuple[str, ...] = ("A_core", "A_core", "A_core", "A_core", "A_core"),
    dois: tuple[str, ...] = ("10.a", "10.b", "10.c", "10.d", "10.e"),
    titles: tuple[str, ...] = (
        "Grid storage threshold improves reserve reliability",
        "Grid storage threshold improves reserve reliability",
        "Grid storage threshold improves reserve reliability",
        "Grid storage threshold improves reserve reliability",
        "Grid storage threshold improves reserve reliability",
    ),
    journals: tuple[str, ...] = (
        "Energy Systems", "Energy Systems", "Energy Systems",
        "Energy Systems", "Energy Systems",
    ),
    tension: bool = True,
) -> Path:
    run = root / "grid_storage-evidence-ts"
    run.mkdir()
    ids = [str(i + 1) for i in range(len(lanes))]
    def _fit(values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) >= len(ids):
            return values[:len(ids)]
        return values + (values[-1],) * (len(ids) - len(values))
    dois = _fit(dois)
    titles = _fit(titles)
    journals = _fit(journals)
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - grid_storage\n\n"
        "**Headline:** Storage threshold paradox in reserve markets\n"
        f"**Alpha score:** {score}/100\n"
        f"**Confidence:** `{label}`\n\n"
        "## Why this is surprising\n\n"
        + ("Real tension: reserve reliability rises while costs fall.\n\n"
           if tension else "Expected result without a clear contrast.\n\n")
        + "## Evidence receipts\n\n"
        + "\n".join(
            f"- `fact_id={fid}` (`{lane}`) - receipt"
            for fid, lane in zip(ids, lanes, strict=True)
        )
        + "\n",
        encoding="utf-8",
    )
    run.joinpath("opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "status": "survives",
            "capped_opportunity": score,
            "cited_fact_ids": ids,
        }],
    }), encoding="utf-8")
    run.joinpath("fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": fid, "lane": lane}
            for fid, lane in zip(ids, lanes, strict=True)
        ],
    }), encoding="utf-8")
    run.joinpath("all_facts.json").write_text(json.dumps([
        {
            "fact_id": fid,
            "canonical_phrase": title,
            "source_paper": {
                "doi": doi, "title": title, "journal": journal, "year": 2026,
            },
        }
        for fid, doi, title, journal in zip(ids, dois, titles, journals, strict=True)
    ]), encoding="utf-8")
    return run


def _add_fact(
    run: Path,
    *,
    fact_id: str,
    lane: str,
    doi: str,
    title: str,
    phrase: str,
    journal: str = "Policy Review",
    population: str = "operators",
    intervention: str = "intervention",
) -> None:
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    facts.append({
        "fact_id": fact_id,
        "canonical_phrase": phrase,
        "population": population,
        "intervention": intervention,
        "source_paper": {
            "doi": doi, "title": title, "journal": journal, "year": 2026,
        },
    })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    lanes["verdicts"].append({"fact_id": fact_id, "lane": lane})
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")


def _set_phrase(run: Path, fact_id: str, phrase: str) -> None:
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    for fact in facts:
        if str(fact.get("fact_id")) == fact_id:
            fact["canonical_phrase"] = phrase
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")


def test_source_key_uses_full_identifier_order() -> None:
    assert tier._source_key({"source_paper": {"pmcid": "PMC1", "title": "T"}}) == "PMC1"
    assert tier._source_key({"source_paper": {"paper_id": "P2", "title": "T"}}) == "P2"
    assert tier._source_key({"source_paper": {"id": "I3", "title": "T"}}) == "I3"


def test_ready_to_publish_accepts_bound_concentrated_tension(tmp_path: Path) -> None:
    verdict = publish_verdict(_run(tmp_path))

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["publish_tier"] == "TIER_1"
    assert verdict["maturity_level"] == "L5"
    assert verdict["blockers"] == []


def test_no_bound_receipts_routes_to_curation(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        label="curation_needed",
        lanes=("D_bad_extraction", "D_bad_extraction", "D_bad_extraction"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "curation_needed"
    assert "no_bound_receipts" in verdict["blockers"]


def test_cross_domain_forced_routes_to_agent_repair(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        dois=("10.a", "10.b", "10.b"),
        titles=(
            "Tariff auctions shift grid reserve reliability",
            "Ceramic kiln glazing changes pigment adhesion",
            "Ceramic kiln firing changes pigment durability",
        ),
        journals=("Energy Markets", "Materials Craft", "Materials Craft"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["publish_tier"] == "TIER_2"
    assert "cross_domain_forced" in verdict["blockers"]


def test_claim_coherent_source_diversity_is_publishable(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Reserve auctions threshold changes grid storage reliability",
            "Reserve dispatch threshold changes grid storage reliability",
            "Reserve pricing threshold changes grid storage reliability",
            "Reserve settlement threshold changes grid storage reliability",
        ),
        journals=("Grid Review", "Grid Letters", "Grid Reports", "Grid Notes", "Grid Briefs"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert "source_dispersion" not in verdict["blockers"]
    assert verdict["axes"]["source_concentrated"] is False
    assert verdict["axes"]["claim_coherent_source_diversity"] is True
    assert "cross_domain_forced" not in verdict["blockers"]


def test_ai_benchmark_fields_count_toward_claim_fit(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.ai/a", "10.ai/b", "10.ai/c", "10.ai/d", "10.ai/e"),
        titles=(
            "AgentX SWE-bench Verified issue resolution study",
            "AgentX SWE-bench Verified repair benchmark report",
            "AgentX SWE-bench Verified software engineering evaluation",
            "AgentX SWE-bench Verified resolve-rate replication",
            "AgentX SWE-bench Verified coding benchmark audit",
        ),
        journals=("AI Eval", "AI Eval", "AI Eval", "AI Eval", "AI Eval"),
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - swe_bench\n\n"
        "**Headline:** AgentX resolve-rate gains on SWE-bench Verified\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "AgentX shows a direct resolve-rate signal on SWE-bench Verified.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the benchmark gain is direct but still bounded.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(
            f"- `fact_id={idx}` (`A_core`) - receipt"
            for idx in range(1, 6)
        )
        + "\n",
        encoding="utf-8",
    )
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    for fact in facts:
        fact.update({
            "canonical_phrase": "The system reported a benchmark result.",
            "metric": "resolve rate",
            "benchmark": "SWE-bench Verified",
            "task": "software engineering issue resolution",
            "model_system": "AgentX",
            "baseline_comparator": "baseline agent",
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["axes"]["direct_match_receipts"] == 5
    assert verdict["axes"]["direct_source_papers"] == 5


def test_metric_type_mismatch_blocks_result_shape_publish(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        score=90,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.ai/swift", "10.ai/weaver", "10.ai/memori", "10.ai/kumiho", "10.ai/v33"),
        titles=(
            "SwiftMem LoCoMo memory benchmark accuracy evaluation",
            "MemWeaver LoCoMo memory benchmark accuracy evaluation",
            "Memori LoCoMo memory benchmark accuracy evaluation",
            "Kumiho LoCoMo memory benchmark accuracy evaluation",
            "SuperLocalMemory LoCoMo memory benchmark accuracy evaluation",
        ),
        journals=("AI Eval", "AI Eval", "AI Eval", "AI Eval", "AI Eval"),
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - ai_agents\n\n"
        "**Headline:** AI agents: LoCoMo accuracy is the shared direct-receipt signal\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "Across 5 direct receipts sharing LoCoMo and accuracy, memory systems "
        "report comparable performance.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the benchmark evidence looks comparable.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(
            f"- `fact_id={idx}` (`A_core`) - receipt"
            for idx in range(1, 6)
        )
        + "\n",
        encoding="utf-8",
    )
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    rows = [
        (
            "SwiftMem",
            "Experiments on LoCoMo demonstrate that SwiftMem achieves 47x faster "
            "search than baselines while maintaining competitive accuracy.",
            47,
            "x",
        ),
        (
            "MemWeaver",
            "Experiments on LoCoMo demonstrate that MemWeaver improves reasoning "
            "accuracy while reducing input context length by over 95%.",
            95,
            "%",
        ),
        (
            "Memori",
            "Evaluated on LoCoMo, Memori achieves 81.95% accuracy.",
            81.95,
            "%",
        ),
        (
            "Kumiho",
            "On LoCoMo-Plus, Kumiho achieves 93.3% judge accuracy.",
            93.3,
            "%",
        ),
        (
            "SuperLocalMemory",
            "V3.3 achieves 70.4% accuracy on LoCoMo in Mode A.",
            70.4,
            "%",
        ),
    ]
    for fact, (_system, phrase, value, units) in zip(facts, rows, strict=True):
        fact.update({
            "canonical_phrase": phrase,
            "benchmark": "LoCoMo",
            "task": "memory benchmark",
            "dataset": "LoCoMo",
            "metric": "accuracy",
            "baseline_comparator": "LoCoMo benchmark baselines",
            "evaluation_protocol": "reported LoCoMo benchmark evaluation",
            "numeric_value": value,
            "units": units,
            "result_key": "locomo::accuracy",
            "result_shape": {
                "benchmark": "LoCoMo",
                "task": "memory benchmark",
                "dataset": "LoCoMo",
                "metric": "accuracy",
                "baseline_comparator": "LoCoMo benchmark baselines",
                "evaluation_protocol": "reported LoCoMo benchmark evaluation",
            },
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["axes"]["direct_match_receipts"] == 5
    assert verdict["axes"]["direct_source_papers"] == 5
    assert verdict["axes"]["direct_receipt_shape_coherent"] is True
    assert verdict["axes"]["direct_metric_type_coherent"] is False
    assert "metric_type_mismatch" in verdict["blockers"]


def test_metric_type_mismatch_checks_all_direct_receipts(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        score=90,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.ai/a", "10.ai/b", "10.ai/c", "10.ai/d", "10.ai/e"),
        titles=("LoCoMo memory evaluation",) * 5,
        journals=("AI Eval",) * 5,
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - ai_agents\n\n"
        "**Headline:** AI agents: LoCoMo accuracy is the shared direct-receipt signal\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "Across 5 direct receipts sharing LoCoMo accuracy, memory systems report comparable performance.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the benchmark evidence looks comparable.\n\n"
        "## Evidence receipts\n\n"
        + "\n".join(
            f"- `fact_id={idx}` (`A_core`) - receipt"
            for idx in range(1, 6)
        )
        + "\n",
        encoding="utf-8",
    )
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    rows = (
        ("Model A reports 80% LoCoMo accuracy against baseline.", 80, "%"),
        ("Model B reports 82% LoCoMo accuracy against baseline.", 82, "%"),
        ("Model C reports 84% LoCoMo accuracy against baseline.", 84, "%"),
        ("Model D reports 47x faster LoCoMo search against baseline.", 47, "x"),
        ("Model E reports 95% LoCoMo context length reduction.", 95, "%"),
    )
    for fact, (phrase, value, units) in zip(facts, rows, strict=True):
        fact.update({
            "canonical_phrase": phrase,
            "benchmark": "LoCoMo",
            "task": "memory benchmark",
            "dataset": "LoCoMo",
            "metric": "accuracy",
            "baseline_comparator": "LoCoMo benchmark baselines",
            "evaluation_protocol": "reported LoCoMo benchmark evaluation",
            "numeric_value": value,
            "units": units,
            "result_shape": {
                "benchmark": "LoCoMo",
                "task": "memory benchmark",
                "dataset": "LoCoMo",
                "metric": "accuracy",
                "baseline_comparator": "LoCoMo benchmark baselines",
                "evaluation_protocol": "reported LoCoMo benchmark evaluation",
            },
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["axes"]["direct_source_papers"] == 5
    assert verdict["axes"]["direct_metric_type_coherent"] is False
    assert "metric_type_mismatch" in verdict["blockers"]


def test_bridge_chain_source_overlap_is_not_claim_coherent(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Alpha beta levels increased with",
            "Beta gamma levels increased with",
            "Gamma delta levels increased with",
            "Delta epsilon levels increased with",
            "Epsilon zeta levels increased with",
        ),
        journals=("Grid A", "Grid B", "Grid C", "Grid D", "Grid E"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert "claim_alignment_partial" in verdict["blockers"]
    assert "direct_source_floor_below_min" in verdict["blockers"]
    assert verdict["axes"]["claim_coherent_source_diversity"] is False
    assert verdict["axes"]["direct_match_receipts"] < verdict["axes"]["bound_receipts"]


def test_claim_coherence_accepts_source_cluster_not_every_receipt(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core", "B_context", "B_context"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e", "10.x", "10.y"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Reserve auctions threshold changes grid storage reliability",
            "Reserve dispatch threshold changes grid storage reliability",
            "Reserve pricing threshold changes grid storage reliability",
            "Reserve settlement threshold changes grid storage reliability",
            "Operations handbook for unrelated market oversight",
            "Governance report for unrelated tariff offices",
        ),
        journals=(
            "Grid Review", "Grid Letters", "Grid Reports", "Grid Notes",
            "Grid Briefs", "Admin Review", "Policy Notes",
        ),
    )

    verdict = publish_verdict(run)

    assert "source_dispersion" not in verdict["blockers"]
    assert verdict["axes"]["claim_coherent_source_diversity"] is True


def test_ready_to_publish_requires_direct_receipt_shape_coherence(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    for fact, metric, model in zip(
        facts,
        ("accuracy", "precision", "recall", "latency", "faithfulness"),
        ("GPT", "RAG", "LLM", "MoE", "BLOOM"),
        strict=True,
    ):
        fact.update({
            "population": "reserve-market benchmark",
            "intervention": "storage threshold controller",
            "comparator": "manual reserve baseline",
            "metric": metric,
            "model_system": model,
            "evaluation_protocol": "zero shot dispatch evaluation",
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert "receipt_shape_mismatch" in verdict["blockers"]
    assert verdict["axes"]["direct_receipt_shape_coherent"] is False


def test_ready_to_publish_accepts_preclustered_result_shape(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    for i, fact in enumerate(facts):
        fact.update({
            "population": "ai agents LoCoMo",
            "intervention": f"memory system {i}",
            "comparator": f"baseline {i}",
            "metric": f"accuracy variant {i}",
            "model_system": f"Model {i}",
            "baseline_comparator": f"baseline {i}",
            "evaluation_protocol": f"paper protocol {i}",
            "result_shape": {
                "benchmark": "LoCoMo",
                "task": "long context memory",
                "dataset": "LoCoMo",
                "metric": "accuracy",
                "model_system": "LoCoMo memory systems",
                "baseline_comparator": "LoCoMo benchmark baselines",
                "evaluation_protocol": "LoCoMo benchmark evaluation",
            },
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["blockers"] == []
    assert verdict["axes"]["direct_receipt_shape_coherent"] is True


def test_ready_to_publish_accepts_result_key_cluster_when_text_fit_is_partial(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    for i, fact in enumerate(facts):
        fact.update({
            "canonical_phrase": (
                "Evaluated without fine tuning, the system reports a "
                "benchmark accuracy result against a baseline."
            ),
            "population": "rag MedQA",
            "intervention": f"medical qa system {i}",
            "comparator": f"baseline {i}",
            "endpoint": "accuracy",
            "metric": "accuracy",
            "model_system": f"Model {i}",
            "baseline_comparator": f"baseline {i}",
            "evaluation_protocol": f"paper protocol {i}",
            "result_key": "rag::medqa::accuracy",
            "result_shape": {
                "benchmark": "MedQA",
                "task": "MedQA",
                "dataset": "MedQA",
                "metric": "accuracy",
                "model_system": "MedQA systems",
                "baseline_comparator": "MedQA benchmark baselines",
                "evaluation_protocol": "MedQA benchmark evaluation",
            },
        })
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["blockers"] == []
    assert verdict["axes"]["direct_match_receipts"] == 5
    assert verdict["axes"]["direct_source_papers"] == 5


def test_structural_ready_can_publish_frontier_label(tmp_path: Path) -> None:
    run = _run(tmp_path, label="frontier_hypothesis")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["blockers"] == []


def test_publish_tier_judges_rendered_memo_receipts_before_lead_audit(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Reserve auctions threshold changes grid storage reliability",
            "Reserve dispatch threshold changes grid storage reliability",
            "Ceramic kiln pigment adhesion after firing",
        ),
        journals=("Grid Review", "Grid Letters", "Grid Reports", "Craft Notes"),
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - grid_storage\n\n"
        "**Headline:** Storage threshold paradox in reserve markets\n"
        "**Alpha score:** 80/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## Why this is surprising\n\n"
        "Real tension: reserve reliability rises while costs fall.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n"
        "- `fact_id=2` (`A_core`) - receipt\n"
        "- `fact_id=3` (`A_core`) - receipt\n",
        encoding="utf-8",
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["axes"]["bound_receipts"] == 3
    assert verdict["axes"]["direct_source_papers"] == 3
    assert "source_floor_below_min" in verdict["blockers"]
    assert "direct_source_floor_below_min" in verdict["blockers"]
    assert "source_dispersion" not in verdict["blockers"]


def test_source_floors_can_be_domain_owned_without_code_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = tmp_path / "publication.toml"
    policy.write_text(
        "[alpha_memo]\n"
        "min_source_papers = 5\n"
        "min_direct_source_papers = 5\n"
        "min_cluster_source_papers = 3\n\n"
        "[alpha_memo.domains.ai_research]\n"
        "min_source_papers = 4\n"
        "min_direct_source_papers = 4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tier, "_PUBLICATION_PATH", policy)
    root = tmp_path / "ai"
    root.mkdir()
    run = _run(
        root,
        lanes=("A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Reserve auctions threshold changes grid storage reliability",
            "Reserve dispatch threshold changes grid storage reliability",
            "Reserve pricing threshold changes grid storage reliability",
        ),
    )
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert "source_floor_below_min" not in verdict["blockers"]
    assert "direct_source_floor_below_min" not in verdict["blockers"]


def test_default_source_floor_still_blocks_four_source_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = tmp_path / "publication.toml"
    policy.write_text(
        "[alpha_memo]\n"
        "min_source_papers = 5\n"
        "min_direct_source_papers = 5\n"
        "min_cluster_source_papers = 3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tier, "_PUBLICATION_PATH", policy)
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Reserve auctions threshold changes grid storage reliability",
            "Reserve dispatch threshold changes grid storage reliability",
            "Reserve pricing threshold changes grid storage reliability",
        ),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert "source_floor_below_min" in verdict["blockers"]
    assert "direct_source_floor_below_min" in verdict["blockers"]


def test_llm_cluster_publishes_three_homogeneous_sources(tmp_path: Path) -> None:
    """A writer-validated homogeneous cluster publishes at the cluster floor
    (3 sources) and surfaces NO active blockers — Researka intake's 2-4 source
    alpha exception (TIER_1/L5, empty blockers) accepts this narrow shape, which
    the plain path would block on source_floor_below_min."""
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c"),
        titles=(
            "Grid storage threshold improves reserve reliability",
            "Grid storage threshold improves reserve reliability",
            "Grid storage threshold improves reserve reliability",
        ),
        journals=("Energy Systems", "Energy Systems", "Energy Systems"),
    )
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": (
            "Grid storage thresholds improve reserve reliability vs "
            "unthresholded dispatch in day-ahead markets"
        ),
        "lead_fact_ids": ["1", "2", "3"],
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["publish_tier"] == "TIER_1"
    # The 2-4 source intake exception requires an empty active-blockers field;
    # the waived ones move to waived_blockers.
    assert verdict["blockers"] == []
    assert verdict["waived_blockers"]


def test_llm_cluster_below_cluster_floor_does_not_publish(tmp_path: Path) -> None:
    """A cluster below the 3-source floor must not publish: the waiver must not
    collapse into publishing any cluster at all."""
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core"),
        dois=("10.a", "10.b"),
        titles=(
            "Grid storage threshold improves reserve reliability",
            "Grid storage threshold improves reserve reliability",
        ),
        journals=("Energy Systems", "Energy Systems"),
    )
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "Grid storage thresholds improve reserve reliability",
        "lead_fact_ids": ["1", "2"],
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] != "ready_to_publish"


def test_heterogeneous_cluster_routes_to_evidence_map(tmp_path: Path) -> None:
    """When the clusterer flags the lead cluster as a landscape (homogeneous=False)
    and the topic is source-rich, the verdict surfaces an evidence_map — not a
    doomed single-claim memo — even without the writer's evidence_map label. This
    is the auto-routing lever: heterogeneous topics (most AI single-claim attempts)
    publish as maps instead of rejecting as incoherent alpha memos."""
    run = _run(tmp_path, score=10)  # 5 A_core; low score forces the waived-cluster
    # path (ready=False) that real heterogeneous topics hit via source dispersion.
    # A real heterogeneous landscape varies by population — the non-waived
    # stratification gate requires it (a constant-population map is a fake one).
    facts = json.loads((run / "all_facts.json").read_text())
    for fact, pop in zip(facts, (
        "day-ahead markets", "real-time markets", "frequency reserve",
        "capacity markets", "ancillary services"), strict=True):
        fact["population"] = pop
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "Storage thresholds improve reserve reliability across markets",
        "lead_fact_ids": ["1", "2", "3", "4", "5"],
        "homogeneous": False,
        "conformance": 0.38,
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["surface_type"] == "evidence_map"


def test_source_rich_no_signal_landscape_routes_to_evidence_map(tmp_path: Path) -> None:
    """A broad parent can have no single publishable claim but still be a valid
    source-rich evidence map. This does not lower quality: it requires the map
    citation floor and a stratified A_core landscape."""
    n = 12
    run = _run(
        tmp_path,
        label="no_signal",
        score=0,
        lanes=tuple("A_core" for _ in range(n)),
        dois=tuple(f"10.map/{i}" for i in range(n)),
        titles=tuple(f"Storage threshold finding {i}" for i in range(n)),
    )
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    populations = (
        "older adults", "diabetic cohorts", "frailty cohorts",
        "cardiometabolic patients",
    )
    endpoints = ("mortality", "glycemic control", "physical function")
    for i, fact in enumerate(facts):
        fact["population"] = populations[i % len(populations)]
        fact["endpoint"] = endpoints[i % len(endpoints)]
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["surface_type"] == "evidence_map"
    assert verdict["blockers"] == []
    assert "blocked_label:no_signal" in verdict["waived_blockers"]


def test_no_signal_landscape_below_map_floor_stays_blocked(tmp_path: Path) -> None:
    n = 8
    run = _run(
        tmp_path,
        label="no_signal",
        score=0,
        lanes=tuple("A_core" for _ in range(n)),
        dois=tuple(f"10.map/{i}" for i in range(n)),
        titles=tuple(f"Storage threshold finding {i}" for i in range(n)),
    )
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    populations = (
        "older adults", "diabetic cohorts", "frailty cohorts",
        "cardiometabolic patients",
    )
    endpoints = ("mortality", "glycemic control", "physical function")
    for i, fact in enumerate(facts):
        fact["population"] = populations[i % len(populations)]
        fact["endpoint"] = endpoints[i % len(endpoints)]
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "curation_needed"
    assert verdict["surface_type"] != "evidence_map"
    assert "blocked_label:no_signal" in verdict["blockers"]


def test_unstratified_landscape_is_not_a_publishable_map(tmp_path: Path) -> None:
    """A heterogeneous cluster whose findings all share ONE population (and no
    other varying axis) is a fake landscape — the panel rejects it as a
    constant-population map, so the non-waived stratification gate must keep it
    out of the evidence_map lane rather than route it to a guaranteed reject."""
    run = _run(tmp_path, score=10)
    facts = json.loads((run / "all_facts.json").read_text())
    for fact in facts:
        fact["population"] = "grid operators"  # constant -> not a landscape
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "x", "lead_fact_ids": ["1", "2", "3", "4", "5"],
        "homogeneous": False, "conformance": 0.38,
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["surface_type"] != "evidence_map"


def test_homogeneous_cluster_stays_single_claim(tmp_path: Path) -> None:
    """The same source-rich run, but a homogeneous cluster (homogeneous=True),
    publishes as a single-claim alpha_memo — the crisp lane is preserved for
    genuinely coherent claims like rapamycin."""
    run = _run(tmp_path, score=10)
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "Storage thresholds improve reserve reliability across markets",
        "lead_fact_ids": ["1", "2", "3", "4", "5"],
        "homogeneous": True,
        "conformance": 0.86,
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["decision"] == "ready_to_publish"
    assert verdict["surface_type"] == "publish_alpha_memo"


def test_legacy_cluster_without_homogeneity_flag_stays_single_claim(
    tmp_path: Path,
) -> None:
    """A cluster from before the homogeneity pass (no `homogeneous` key) defaults
    to single-claim, so the routing change is inert without the signal."""
    run = _run(tmp_path, score=10)
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "Storage thresholds improve reserve reliability across markets",
        "lead_fact_ids": ["1", "2", "3", "4", "5"],
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert verdict["surface_type"] == "publish_alpha_memo"


def test_memo_receipt_ids_dedupes_evidence_and_context() -> None:
    memo = (
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n"
        "- `fact_id=2` (`A_core`) - receipt\n\n"
        "## Context receipts\n\n"
        "- `fact_id=2` (`B_context`) - repeated\n"
        "- `fact_id=3` (`B_context`) - receipt\n"
    )

    assert tier._memo_receipt_ids(memo) == ["1", "2", "3"]


def test_context_sources_do_not_satisfy_direct_source_floor(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "B_context", "B_context", "B_context"),
        dois=("10.a", "10.a", "10.a", "10.b", "10.c", "10.d"),
        titles=(
            "Grid storage threshold changes reserve reliability",
            "Grid storage threshold changes reserve reliability",
            "Grid storage threshold changes reserve reliability",
            "Grid storage context changes reserve reliability",
            "Grid storage context changes reserve reliability",
            "Grid storage context changes reserve reliability",
        ),
        journals=("Grid Review", "Grid Review", "Grid Review", "Grid Notes", "Grid Letters", "Grid Briefs"),
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - grid_storage\n\n"
        "**Headline:** Storage threshold paradox in reserve markets\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## Why this is surprising\n\n"
        "Real tension: reserve reliability rises while costs fall.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n"
        "- `fact_id=2` (`A_core`) - receipt\n"
        "- `fact_id=3` (`A_core`) - receipt\n\n"
        "## Context receipts\n\n"
        "- `fact_id=4` (`B_context`) - receipt\n"
        "- `fact_id=5` (`B_context`) - receipt\n"
        "- `fact_id=6` (`B_context`) - receipt\n",
        encoding="utf-8",
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["axes"]["source_papers"]
    assert verdict["axes"]["direct_source_papers"] == 1
    assert "direct_source_floor_below_min" in verdict["blockers"]


def test_incoherent_source_dispersion_routes_to_agent_repair(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Ceramic kiln pigment adhesion after firing",
            "Maritime insurance premiums after port dredging",
            "Retail payroll compliance after tax notices",
            "Aquifer sediment maps after flood plain surveys",
        ),
        journals=(
            "Grid Review", "Craft Notes", "Port Reports", "Payroll Notes",
            "Hydrology Notes",
        ),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert "claim_alignment_partial" in verdict["blockers"]
    assert "direct_source_floor_below_min" in verdict["blockers"]
    assert verdict["axes"]["claim_coherent_source_diversity"] is False
    assert "cross_domain_forced" not in verdict["blockers"]


def test_adjacent_a_core_receipts_do_not_satisfy_claim_source_floor(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.stroke/a", "10.stroke/b", "10.gi/a", "10.gi/b", "10.gi/c"),
        titles=(
            "SGLT2 inhibitors reduced stroke risk in older adults",
            "SGLT2 inhibitor exposure reduced ischemic stroke risk",
            "GLP1 treatment increased gastrointestinal adverse events",
            "Semaglutide nausea drove discontinuation rates",
            "Incretin therapy changed bodyweight endpoints",
        ),
    )
    run.joinpath("alpha_memo.md").write_text(
        "# Alpha memo - metabolic_agents\n\n"
        "**Headline:** SGLT2 inhibitors reduced stroke risk\n"
        "**Alpha score:** 90/100\n"
        "**Confidence:** `evidence_backed_signal`\n\n"
        "## One-sentence thesis\n\n"
        "SGLT2 inhibitor receipts report reduced stroke risk.\n\n"
        "## Why this is surprising\n\n"
        "Real tension: the signal is endpoint-specific.\n\n"
        "## Evidence receipts\n\n"
        "- `fact_id=1` (`A_core`) - receipt\n"
        "- `fact_id=2` (`A_core`) - receipt\n"
        "- `fact_id=3` (`A_core`) - receipt\n"
        "- `fact_id=4` (`A_core`) - receipt\n"
        "- `fact_id=5` (`A_core`) - receipt\n",
        encoding="utf-8",
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["surface_type"] == "receipt_map"
    assert verdict["axes"]["direct_match_receipts"] == 2
    assert verdict["axes"]["direct_source_papers"] == 2
    assert "claim_alignment_partial" in verdict["blockers"]
    assert "direct_source_floor_below_min" in verdict["blockers"]


def test_dispersed_parent_recommends_a_core_child_cluster(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Reserve markets threshold changes grid storage reliability",
            "Ceramic kiln pigment adhesion after firing",
            "Maritime insurance premiums after port dredging",
            "Retail payroll compliance after tax notices",
            "Aquifer sediment maps after flood plain surveys",
        ),
        journals=(
            "Grid Review", "Craft Notes", "Port Reports", "Payroll Notes",
            "Hydrology Notes",
        ),
    )
    for i in range(6, 11):
        _add_fact(
            run, fact_id=str(i), lane="A_core", doi=f"10.child/{i}",
            title=f"Reserve auction threshold reliability replication {i}",
            phrase="Reserve auction threshold improved reliability under pricing.",
            population="reserve auction operators",
            intervention="threshold pricing reliability",
        )

    verdict = publish_verdict(run)
    rec = verdict["subtopic_recommendations"]

    assert verdict["decision"] == "agent_repair_needed"
    assert rec["recommended"] is True
    assert rec["reason"] == "source_coherent_child_cluster"
    assert len(rec["clusters"][0]["member_fact_ids"]) >= 5
    child = next(
        item for item in rec["clusters"] if "6" in item["member_fact_ids"]
    )
    assert set(child["label"].split("_")) & {"threshold", "pricing", "reliability"}
    assert "review" not in child["label"]
    assert "replication" not in child["label"]
    assert "operators" not in child["label"]


def test_underfloor_submit_cluster_does_not_recommend_child_rerun(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Battery inverter maintenance changes dispatch durability",
            "Ceramic kiln pigment adhesion after firing",
            "Maritime insurance premiums after port dredging",
            "Retail payroll compliance after tax notices",
            "Aquifer sediment maps after flood plain surveys",
        ),
        journals=(
            "Grid Review", "Craft Notes", "Port Reports", "Payroll Notes",
            "Hydrology Notes",
        ),
    )
    for i in range(6, 10):
        _add_fact(
            run, fact_id=str(i), lane="A_core", doi=f"10.child/{i}",
            title=f"Reserve auction threshold reliability replication {i}",
            phrase="Reserve auction threshold improved reliability under pricing.",
            population="reserve auction operators",
            intervention="threshold pricing reliability",
        )

    verdict = publish_verdict(run)
    rec = verdict["subtopic_recommendations"]

    assert verdict["decision"] != "ready_to_publish"
    assert rec["recommended"] is False
    assert rec["reason"] == "not_broad_or_not_noisy_enough"
    assert rec["clusters"] == []


def test_intervention_only_child_cluster_is_not_recommended(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Trauma recovery after shared device exposure",
            "Blood withdrawal after shared device exposure",
            "Bacterial removal after shared device exposure",
            "Cognitive aging after shared device exposure",
            "Dental recovery after shared device exposure",
        ),
    )
    facts = json.loads((run / "all_facts.json").read_text())
    for fact, phrase, population in zip(
        facts,
        (
            "neurological deficit scores improved after treatment.",
            "first-attempt withdrawal failure fell after treatment.",
            "bactericidal rates increased after treatment.",
            "meningeal lymphatic drainage changed after treatment.",
            "oral pathology management improved after treatment.",
        ),
        (
            "traumatic brain injury patients",
            "pediatric blood withdrawal patients",
            "pathogenic bacteria samples",
            "aged Alzheimer model mice",
            "dental care patients",
        ),
        strict=True,
    ):
        fact["canonical_phrase"] = phrase
        fact["population"] = population
        fact["intervention"] = "near infrared photobiomodulation"
    (run / "all_facts.json").write_text(json.dumps(facts))

    rec = publish_verdict(run)["subtopic_recommendations"]

    assert rec["recommended"] is False
    assert rec["reason"] == "not_broad_or_not_noisy_enough"


def test_low_alpha_score_routes_to_curation(tmp_path: Path) -> None:
    verdict = publish_verdict(_run(tmp_path, score=0))

    assert verdict["decision"] == "curation_needed"
    assert "low_alpha_score" in verdict["blockers"]


def test_feed_scope_mismatch_routes_to_curation(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        titles=(
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
        ),
        journals=("Crop Systems", "Crop Systems", "Crop Systems"),
    )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "curation_needed"
    assert "feed_scope_mismatch" in verdict["blockers"]


def test_feed_scope_markers_are_domain_scoped(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        titles=(
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
        ),
        journals=("Crop Systems", "Crop Systems", "Crop Systems"),
    )
    run.joinpath("MANIFEST.json").write_text(json.dumps({
        "domain": {"slug": "ai_research"},
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert "feed_scope_mismatch" not in verdict["blockers"]


def test_feed_scope_markers_accept_string_domain_metadata(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        titles=(
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
            "Rice seed storage threshold improves harvest durability",
        ),
        journals=("Crop Systems", "Crop Systems", "Crop Systems"),
    )
    run.joinpath("search_trace.json").write_text(json.dumps({
        "domain": "ai_research",
    }), encoding="utf-8")

    verdict = publish_verdict(run)

    assert "feed_scope_mismatch" not in verdict["blockers"]


def test_feed_scope_marker_does_not_match_inside_word(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        titles=(
            "Kidney transplant threshold improves reserve reliability",
            "Kidney transplant threshold improves reserve reliability",
            "Kidney transplant threshold improves reserve reliability",
        ),
    )

    verdict = publish_verdict(run)

    assert "feed_scope_mismatch" not in verdict["blockers"]


def test_feed_scope_marker_is_allowed_when_marker_is_topic_term(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        titles=(
            "Plant based diet threshold improves reserve reliability",
            "Plant based diet threshold improves reserve reliability",
            "Plant based diet threshold improves reserve reliability",
        ),
    )
    topic_run = tmp_path / "plant_based_diet-evidence-ts"
    run.rename(topic_run)

    verdict = publish_verdict(topic_run)

    assert "feed_scope_mismatch" not in verdict["blockers"]


def test_write_publish_verdict_writes_file(tmp_path: Path) -> None:
    run = _run(tmp_path)

    path, verdict = write_publish_verdict(run)

    assert path == run / "publish_verdict.json"
    assert json.loads(path.read_text(encoding="utf-8")) == verdict


def test_thin_memo_with_unused_bound_receipts_gets_context_surface(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        label="frontier_hypothesis",
        lanes=("A_core", "A_core"),
        dois=("10.same/a", "10.same/a"),
        titles=(
            "Storage tariff improves reserve reliability",
            "Storage tariff improves reserve reliability",
        ),
    )
    for i in range(3, 6):
        _add_fact(
            run,
            fact_id=str(i),
            lane="A_core",
            doi=f"10.extra/{i}",
            title=f"Reserve market context {i} changes dispatch reliability",
            phrase=f"Independent context {i} did not match the lead effect.",
        )

    verdict = publish_verdict(run)

    assert verdict["decision"] == "agent_repair_needed"
    assert verdict["surface_type"] == "context_dependence_memo"
    assert verdict["axes"]["bound_receipts"] == 2
    assert verdict["axes"]["available_bound_receipts"] == 5
    assert verdict["receipt_expansion"]["needed"] is True
    assert len(verdict["receipt_expansion"]["candidate_receipts"]) == 3


def test_receipt_expansion_candidates_are_ranked_by_claim_fit(tmp_path: Path) -> None:
    run = _run(tmp_path, lanes=("A_core", "A_core"), dois=("10.same/a", "10.same/a"))
    _set_phrase(run, "1", "Reserve reliability improved after storage threshold changes.")
    _set_phrase(run, "2", "Reserve reliability improved after storage threshold changes.")
    _add_fact(
        run, fact_id="3", lane="A_core", doi="10.extra/off",
        title="Payroll audit", phrase="Payroll timing changed for rural exporters.",
    )
    _add_fact(
        run, fact_id="4", lane="A_core", doi="10.extra/on",
        title="Reserve reliability audit",
        phrase="Reserve reliability improved after independent threshold changes.",
    )

    verdict = publish_verdict(run)

    assert verdict["receipt_expansion"]["candidate_receipts"][0]["fact_id"] == "4"


def test_available_expansion_pool_scoped_to_cluster(tmp_path: Path) -> None:
    """The expansion pool lists facts that can extend THIS claim, so a bound
    A_core fact the writer-validated cluster split out (e.g. a house-cricket
    receipt under an "in mice" claim) must not appear in available_bound_fact_ids
    — leaving it in feeds the expansion path back into a claim it contradicts."""
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c"),
        titles=("Grid storage threshold improves reserve reliability",) * 3,
        journals=("Energy Systems",) * 3,
    )
    _add_fact(
        run, fact_id="9", lane="A_core", doi="10.offclaim/9",
        title="Reserve reliability in an unrelated isolated microgrid",
        phrase="Reserve reliability improved in an unrelated isolated microgrid.",
    )
    run.joinpath("claim_cluster.json").write_text(json.dumps({
        "claim": "Grid storage thresholds improve reserve reliability",
        "lead_fact_ids": ["1", "2", "3"],
    }), encoding="utf-8")

    pool = publish_verdict(run)["receipt_expansion"]["available_bound_fact_ids"]

    assert "9" not in pool                 # off-cluster bound fact excluded
    assert set(pool) <= {"1", "2", "3"}    # pool scoped to the cluster


def test_counter_evidence_is_explicit_when_a_bound_opposing_fact_exists(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, lanes=("A_core", "A_core"))
    _set_phrase(run, "1", "Reserve reliability improved after storage dispatch changes.")
    _set_phrase(run, "2", "Reserve reliability improved after storage dispatch changes.")
    _add_fact(
        run,
        fact_id="3",
        lane="A_core",
        doi="10.counter/a",
        title="Independent tariff audit finds no reserve improvement",
        phrase="The intervention did not improve reserve reliability.",
    )

    verdict = publish_verdict(run)

    assert verdict["counter_evidence"]["status"] == "found"
    assert verdict["counter_evidence"]["items"][0]["fact_id"] == "3"


def test_cited_opposing_receipt_still_counts_as_counter_evidence(tmp_path: Path) -> None:
    run = _run(tmp_path, lanes=("A_core", "A_core", "A_core"))
    _set_phrase(run, "1", "Reserve reliability improved after storage dispatch changes.")
    _set_phrase(run, "2", "Storage dispatch did not improve reserve reliability.")
    _set_phrase(run, "3", "Reserve reliability improved after storage dispatch changes.")

    verdict = publish_verdict(run)

    assert verdict["counter_evidence"]["status"] == "found"
    assert verdict["counter_evidence"]["items"][0]["fact_id"] == "2"


def test_counter_evidence_prefers_load_bearing_contradiction(tmp_path: Path) -> None:
    run = _run(tmp_path, lanes=("A_core", "A_core"))
    _set_phrase(run, "1", "Reserve reliability improved after storage dispatch changes.")
    _set_phrase(run, "2", "Reserve reliability improved after storage dispatch changes.")
    _add_fact(
        run, fact_id="3", lane="A_core", doi="10.counter/off",
        title="Payroll audit", phrase="The intervention did not change payroll timing.",
    )
    _add_fact(
        run, fact_id="4", lane="A_core", doi="10.counter/on",
        title="Reserve reliability counter-audit",
        phrase="Storage dispatch did not improve reserve reliability.",
    )

    verdict = publish_verdict(run)

    assert verdict["counter_evidence"]["items"][0]["fact_id"] == "4"


def test_counter_evidence_ignores_marker_without_claim_overlap(tmp_path: Path) -> None:
    run = _run(tmp_path, lanes=("A_core", "A_core"))
    _set_phrase(run, "1", "Reserve reliability improved after storage dispatch changes.")
    _set_phrase(run, "2", "Reserve reliability improved after storage dispatch changes.")
    _add_fact(
        run, fact_id="3", lane="A_core", doi="10.counter/off",
        title="Payroll audit", phrase="The intervention did not change payroll timing.",
    )

    verdict = publish_verdict(run)

    assert verdict["counter_evidence"]["status"] == "none_found"
    assert verdict["counter_evidence"]["items"] == []


def test_counter_evidence_satisfies_tension_gate(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        lanes=("A_core", "A_core", "A_core", "A_core", "A_core"),
        dois=("10.a", "10.b", "10.c", "10.d", "10.e"),
        titles=(
            "Reserve dispatch improves grid storage reliability",
            "Reserve auctions improve grid storage reliability",
            "Reserve pricing improves grid storage reliability",
            "Reserve thresholds improve grid storage reliability",
            "Reserve contracts improve grid storage reliability",
        ),
        tension=False,
    )
    for fid in ("1", "2", "3", "4", "5"):
        _set_phrase(
            run, fid,
            "Grid storage dispatch improved reserve reliability after threshold changes.",
        )
    _add_fact(
        run,
        fact_id="6",
        lane="A_core",
        doi="10.counter/on",
        title="Reserve reliability counter-audit",
        phrase="Grid storage dispatch did not improve reserve reliability.",
    )

    verdict = publish_verdict(run)

    assert verdict["counter_evidence"]["status"] == "found"
    assert verdict["counter_evidence"]["items"][0]["claim_fit"] == "opposing"
    assert verdict["axes"]["counter_consensus_tension"] is True
    assert "weak_counter_consensus_tension" not in verdict["blockers"]
    assert verdict["decision"] == "ready_to_publish"


def test_noisy_broad_topic_gets_subtopic_recommendations(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        label="frontier_hypothesis",
        lanes=("A_core", "A_core"),
        dois=("10.same/a", "10.same/a"),
    )
    for i in range(3, 11):
        _add_fact(
            run,
            fact_id=str(i),
            lane="D_bad_extraction",
            doi=f"10.noisy/{i}",
            title=f"Different market domain {i} changes operator behavior",
            phrase=f"Malformed or off-target numeric fragment {i}.",
            population=f"context {i}",
            intervention=f"policy variant {i}",
        )

    verdict = publish_verdict(run)

    rec = verdict["subtopic_recommendations"]
    assert rec["recommended"] is True
    assert rec["reason"] == "high_d_bad_share_plus_semantic_dispersion"
    assert rec["clusters"]


def test_tokens_drops_function_words_keeps_content() -> None:
    """Closed-class function words (>=3 chars, so they survive the length
    filter) must never be emitted as label/shape tokens — the source of the
    live "..._was" junk child topics. Content words must still survive."""
    toks = tier._tokens(
        "the dose was reduced with rapamycin", "rapamycin", frozenset(),
    )
    assert toks == {"dose", "reduced"}
    for function_word in ("was", "were", "the", "with", "from", "that"):
        assert function_word in tier._FUNCTION_WORDS
        assert function_word not in tier._tokens(
            f"effect {function_word} measured", "topic", frozenset(),
        )


def test_asserts_unnegated_gain_excludes_supporting_keeps_genuine() -> None:
    from agent import publish_tier as pt

    # Un-negated improvement = supporting source (must NOT be counter-evidence).
    assert pt._asserts_unnegated_gain(
        "RAG-Chain improves the accuracy by 6.9% on MedQA without fine-tuning")
    assert pt._asserts_unnegated_gain(
        "achieves ~5% accuracy improvement over single-agent baselines")
    # Genuine null / negated findings must still qualify as counter-evidence.
    assert not pt._asserts_unnegated_gain("the model did not improve over baseline")
    assert not pt._asserts_unnegated_gain("failed to outperform the baseline")
    assert not pt._asserts_unnegated_gain("no significant increase in accuracy")
    assert not pt._asserts_unnegated_gain("accuracy was unchanged versus control")
