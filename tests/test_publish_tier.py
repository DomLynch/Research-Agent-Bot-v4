"""Publish-tier gate tests.

Fixtures are non-biomedical. The gate should classify by structure:
binding, source concentration, tension, and cross-domain coherence.
"""
from __future__ import annotations

import json
from pathlib import Path

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


def test_cross_domain_forced_routes_to_operator_review(tmp_path: Path) -> None:
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

    assert verdict["decision"] == "needs_operator_review"
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

    assert verdict["decision"] == "needs_operator_review"
    assert verdict["axes"]["bound_receipts"] == 3
    assert verdict["axes"]["direct_source_papers"] == 3
    assert "source_floor_below_min" in verdict["blockers"]
    assert "direct_source_floor_below_min" in verdict["blockers"]
    assert "source_dispersion" not in verdict["blockers"]


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

    assert verdict["decision"] == "needs_operator_review"
    assert verdict["axes"]["source_papers"]
    assert verdict["axes"]["direct_source_papers"] == 1
    assert "direct_source_floor_below_min" in verdict["blockers"]


def test_incoherent_source_dispersion_routes_to_operator_review(
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

    assert verdict["decision"] == "needs_operator_review"
    assert "source_dispersion" in verdict["blockers"]
    assert verdict["axes"]["claim_coherent_source_diversity"] is False
    assert "cross_domain_forced" not in verdict["blockers"]


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

    assert verdict["decision"] == "needs_operator_review"
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
