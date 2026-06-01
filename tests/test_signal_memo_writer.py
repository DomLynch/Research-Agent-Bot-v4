"""Signal memo renderer tests.

Locks the product-layer shift from raw Top 5 tables to sharp, citable
alpha memos. Fixtures are non-biomedical so the code path stays
universal.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from agent.publish_tier import publish_verdict
from agent.signal_memo_writer import (
    _format_large_numbers,
    _memo_alpha_int,
    render_signal_memo,
    write_signal_memo,
)


def _write_run(run: Path) -> None:
    run.mkdir()
    (run / "signal_post.md").write_text(
        "# Signal — carbon_tax\n\n"
        "_Snapshot:_ `2026-05-16T18-00-00Z`\n\n"
        "## Carbon pricing may cut emissions without the expected output penalty\n\n"
        "## Why this is surprising\n\n"
        "The signal challenges a simple cost-only story.\n\n"
        "## Evidence\n\n"
        "- Emissions fell 8%.\n\n"
        "## Confidence — `evidence_backed_signal`\n\n"
        "High.\n\n"
        "## Next question\n\n"
        "Which independent receipt replicates the contrast?\n",
        encoding="utf-8",
    )
    (run / "frontier_review.json").write_text(json.dumps({
        "topic": "carbon_tax",
        "snapshot_utc": "2026-05-16T18-00-00Z",
        "reviewer_objections": ["policy timing could explain the effect"],
        "next_extractions": ["replicate in a second jurisdiction"],
    }), encoding="utf-8")
    (run / "opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "title": "Carbon pricing may cut emissions",
            "status": "survives",
            "capped_opportunity": 88,
            "rationale": "Bound receipts show a counter-narrative policy signal.",
            "cited_fact_ids": ["101", "202"],
        }],
    }), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({
        "verdicts": [
            {"fact_id": "101", "lane": "A_core"},
            {"fact_id": "202", "lane": "D_bad_extraction"},
        ],
    }), encoding="utf-8")
    (run / "all_facts.json").write_text(json.dumps([
        {
            "fact_id": "101",
            "canonical_phrase": "Emissions fell 8% after the intervention.",
            "source_paper": {"doi": "10.x/policy"},
        },
        {
            "fact_id": "202",
            "canonical_phrase": "Unbound adjacent claim.",
            "source_paper": {"doi": "10.x/noise"},
        },
    ]), encoding="utf-8")
    (run / "top_5.md").write_text(
        "# Top 1\n\n"
        "## #1 — score 90\n\n"
        "**Finding:** Emissions fell 8% after the intervention.\n"
        "- **Alpha cues:** contrast, functional_endpoint\n",
        encoding="utf-8",
    )


def test_signal_memo_has_required_alpha_sections_and_bound_receipts(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    memo = render_signal_memo(run)

    assert "# Alpha memo — carbon_tax" in memo
    assert "## One-sentence thesis" in memo
    assert "## Limitations" in memo
    assert "## What would weaken this" in memo
    assert "## Provenance / priority" in memo
    assert "`fact_id=101` (`A_core`)" in memo
    assert "fact_id=202" not in memo
    assert "**Alpha score:** 98/100" in memo
    assert "**Alpha triage:** `high` (internal ranking; not a certainty claim)" in memo
    assert "Suggested citation" in memo
    assert "Run bundle SHA-256" in memo


def test_write_signal_memo_writes_alpha_memo(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    out, text = write_signal_memo(run)

    assert out == run / "alpha_memo.md"
    assert out.read_text(encoding="utf-8") == text
    assert publish_verdict(run)["alpha_score"] == 98


def test_no_signal_memo_does_not_promote_mimo_note_heading(tmp_path: Path) -> None:
    run = tmp_path / "topic-evidence-ts"
    _write_run(run)
    (run / "signal_post.md").write_text(
        "# No signal — topic\n\n"
        "## MiMo's note\n\nNo publishable thesis.\n",
        encoding="utf-8",
    )

    memo = render_signal_memo(run)

    assert "**Headline:** No signal — topic" in memo
    assert "**Headline:** MiMo's note" not in memo


def test_signal_memo_renders_publish_verdict_sections(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "context_dependence_memo",
        "counter_evidence": {
            "status": "found",
            "items": [{
                "fact_id": "303",
                "lane": "A_core",
                "phrase": "Output did not improve in the comparison market.",
                "source_paper": {"title": "Independent market comparison"},
            }],
        },
        "receipt_expansion": {
            "needed": True,
            "cited_bound_fact_ids": ["101"],
            "available_bound_fact_ids": ["101", "303"],
            "candidate_receipts": [{
                "fact_id": "303",
                "lane": "A_core",
                "phrase": "Emissions fell after the intervention in the comparison market.",
            }],
        },
        "subtopic_recommendations": {
            "recommended": True,
            "clusters": [{
                "label": "market_comparison",
                "source_paper": {"title": "Independent market comparison"},
            }],
        },
    })

    assert "**Memo surface:** `context dependence memo`" in memo
    assert "**Headline:** Carbon tax may be context-specific, not broadly generalizable" in memo
    assert "**Source thesis:** Carbon pricing may cut emissions" in memo
    assert "comparison market" in memo
    assert "## Strongest counter-evidence" in memo
    assert "`fact_id=303` (`A_core`)" in memo
    assert "## Receipt expansion candidates" in memo
    assert "lead thesis is thinner than the available corpus" in memo
    assert "## Subtopic recommendations" in memo
    assert "`market_comparison`" in memo
    typed = json.loads((run / "typed_counter_evidence.json").read_text(encoding="utf-8"))
    novelty = json.loads((run / "novelty_delta.json").read_text(encoding="utf-8"))
    assert typed["items"][0]["type"] == "null_result"
    assert novelty["novelty_delta"]["label"] == "contradictory"


def test_publish_alpha_surface_is_not_rendered_as_publish_command(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
    })

    assert "**Memo surface:** `alpha memo`" in memo
    assert "`publish alpha memo`" not in memo


def test_alpha_memo_expands_receipts_to_five_sources_when_available(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for i in range(3, 7):
        fid = str(i * 101)
        facts.append({
            "fact_id": fid,
            "canonical_phrase": (
                f"Emissions fell after the carbon pricing intervention "
                f"in jurisdiction {i}."
            ),
            "source_paper": {"doi": f"10.x/policy-{i}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "axes": {
            "source_concentrated": True,
            "source_papers": [{"doi": "10.x/policy"}],
        },
    })

    assert "**Headline:** Carbon pricing may cut emissions" in memo
    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "separate evidence streams" in memo
    assert "matched direct-receipt table" in memo
    assert "does not conduct a new meta-analysis or systematic review" in memo
    assert "Real tension:" not in memo
    assert "**Source breadth:** `5/5` unique cited source(s)" in memo
    assert "## Context receipts" not in memo
    assert "`fact_id=101` (`A_core`)" in memo
    assert "doi=10.x/policy" in memo
    assert "doi=10.x/policy-5" in memo
    assert "`fact_id=202`" not in memo
    assert "`fact_id=505` (`A_core`)" in memo
    assert "## Supporting Top cards" not in memo


def test_alpha_memo_does_not_pad_with_off_claim_receipts(tmp_path: Path) -> None:
    """Off-claim A_core facts (valid lane + unique source, but unrelated to the
    lead claim) must NOT pad the bundle to the source floor. Researka rejects
    'disparate facts that do not cohere'; breadth must stay below 5 so the
    existing source-floor gate blocks/rotates instead of submitting junk."""
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for i in (3, 4):  # coherent carbon-pricing receipts, unique sources
        facts.append({
            "fact_id": str(i * 101),
            "canonical_phrase": (
                f"Emissions fell after the carbon pricing intervention "
                f"in region {i}."
            ),
            "source_paper": {"doi": f"10.x/policy-{i}"},
        })
        lanes["verdicts"].append({"fact_id": str(i * 101), "lane": "A_core"})
    # Off-claim A_core facts: valid lane + unique source, unrelated content.
    facts.append({
        "fact_id": "7001",
        "canonical_phrase": "Vitamin D supplementation improved cognition in elders.",
        "source_paper": {"doi": "10.x/brain"},
    })
    facts.append({
        "fact_id": "7002",
        "canonical_phrase": "Resistance training raised muscle mass over twelve weeks.",
        "source_paper": {"doi": "10.x/muscle"},
    })
    lanes["verdicts"].append({"fact_id": "7001", "lane": "A_core"})
    lanes["verdicts"].append({"fact_id": "7002", "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run)

    assert "10.x/brain" not in memo
    assert "10.x/muscle" not in memo
    assert "fact_id=7001" not in memo
    assert "fact_id=7002" not in memo
    # only the 3 coherent sources count -> below the 5 floor, so the gate blocks
    assert "**Source breadth:** `5/5` unique cited source(s)" not in memo
    assert "`fact_id=303` (`A_core`)" in memo


def test_alpha_memo_semantic_receipt_fallback_uses_word_roots(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    facts[0]["canonical_phrase"] = "Emissions reduction followed carbon price adoption."
    for fid, phrase in (
        ("303", "Emission reductions followed carbon pricing in port cities."),
        ("404", "Reduction in emissions followed carbon-price compliance audits."),
        ("505", "Carbon pricing reduced emissions in cross-border firms."),
        ("606", "Emissions reductions followed price changes in exporters."),
    ):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": phrase,
            "source_paper": {"doi": f"10.x/root-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run)

    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "`fact_id=606` (`A_core`)" in memo


def test_alpha_memo_uses_gate_receipt_expansion_candidates(tmp_path: Path) -> None:
    """When publish_tier says a memo underuses available bound receipts, the
    writer should bind those vetted receipts instead of merely listing them."""
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for fid, phrase in (
        ("303", "Emissions fell after the intervention in border regions."),
        ("404", "Emissions fell after the intervention among audited suppliers."),
        ("505", "Emissions fell after the intervention for small exporters."),
        ("606", "Emissions fell after the intervention despite administrative delays."),
    ):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": phrase,
            "source_paper": {"doi": f"10.x/expansion-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "receipt_expansion": {
            "needed": True,
            "cited_bound_fact_ids": ["101"],
            "available_bound_fact_ids": ["101", "303", "404", "505", "606"],
            "candidate_receipts": [{"fact_id": "606", "lane": "A_core"}],
        },
    })

    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "**Source breadth:** `5/5` unique cited source(s)" in memo
    assert "`fact_id=606` (`A_core`)" in memo
    assert "10.x/expansion-606" in memo


def test_alpha_memo_trusts_gate_candidate_receipts_for_source_floor(
    tmp_path: Path,
) -> None:
    """publish_tier candidate receipts are already structural A/B expansion
    picks; the writer should not drop them solely because the lead claim text is
    narrower than the candidate phrase."""
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for fid, phrase in (
        ("303", "Carbon tax audited suppliers reported lower output variance."),
        ("404", "Carbon tax border regions showed lower administrative burden."),
        ("505", "Carbon tax small exporters reported lower compliance costs."),
        ("606", "Carbon tax late adopters showed lower enforcement volatility."),
    ):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": phrase,
            "source_paper": {"doi": f"10.x/gate-candidate-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "receipt_expansion": {
            "needed": True,
            "cited_bound_fact_ids": ["101"],
            "candidate_receipts": [
                {"fact_id": fid, "lane": "A_core"}
                for fid in ("303", "404", "505", "606")
            ],
        },
    })

    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "10.x/gate-candidate-606" in memo


def test_dispersion_repair_reselects_coherent_receipt_cluster(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    additions = {
        "303": ("Carbon pricing reduced port emissions after audit checks.", "A_core"),
        "404": ("Carbon pricing reduced port emissions in border regions.", "A_core"),
        "505": ("Carbon pricing reduced port emissions for regulated firms.", "A_core"),
        "606": ("Carbon pricing reduced port emissions after compliance checks.", "A_core"),
        "707": ("Carbon pricing reduced port emissions in audited suppliers.", "A_core"),
        "808": ("Carbon pricing effects hinge on exporter compliance context.", "B_context"),
        "909": ("Ceramic kiln pigment adhesion improved after firing.", "A_core"),
    }
    for fid, (phrase, lane) in additions.items():
        facts.append({
            "fact_id": fid,
            "canonical_phrase": phrase,
            "population": "regulated port firms" if fid != "909" else "ceramic studios",
            "source_paper": {"doi": f"10.x/{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": lane})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")
    (run / "opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "title": "Carbon pricing port-emissions signal",
            "status": "survives",
            "capped_opportunity": 88,
            "cited_fact_ids": ["909", "303", "101"],
        }],
    }), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "blockers": ["source_dispersion", "weak_counter_consensus_tension"],
    })

    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "fact_id=909" not in memo
    assert "`fact_id=808` (`B_context`)" in memo
    assert "Real tension:" in memo


def test_counter_signal_names_collision_and_testable_split(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for fid, phrase in (
        ("303", "Carbon pricing reduced emissions in 1570,975 audited port-city records."),
        ("404", "Carbon pricing reduced emissions in audited suppliers."),
        ("505", "Carbon pricing reduced emissions in small exporters."),
        ("606", "Carbon pricing reduced emissions after compliance checks."),
    ):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": phrase,
            "population": "regulated firms",
            "source_paper": {"doi": f"10.x/counter-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "counter_evidence": {
            "status": "found",
            "items": [{
                "fact_id": "909",
                "lane": "A_core",
                "phrase": "Carbon pricing did not reduce emissions in heavy industry.",
                "population": "heavy industry firms",
                "source_paper": {"title": "Independent output endpoint study"},
            }],
        },
    })

    assert "**Selected angle:** `counter_signal`" in memo
    assert "The cited receipts show an apparent collision" in memo
    assert "heavy industry firms" in memo
    assert "## Evidence Landscape" in memo
    assert "**Bounded research question:** Does the contrast between" in memo
    assert "population, endpoint, comparator, and time window" in memo
    assert "Testable hypothesis:" in memo
    assert "The value is the collision between receipts" not in memo


def test_counter_signal_formats_malformed_large_numbers() -> None:
    assert (
        _format_large_numbers("659,640 of 1570,975 cancers")
        == "659,640 of 1,570,975 cancers"
    )


def test_grounded_repair_does_not_trust_off_claim_candidate_receipts(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for fid, phrase in (
        ("303", "Vitamin D supplementation improved cognition in elders."),
        ("404", "Resistance training raised muscle mass over twelve weeks."),
        ("505", "Blue-light exposure changed sleep duration."),
        ("606", "Protein timing changed grip strength."),
    ):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": phrase,
            "source_paper": {"doi": f"10.x/off-claim-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "receipt_expansion": {
            "needed": True,
            "cited_bound_fact_ids": ["101"],
            "candidate_receipts": [
                {"fact_id": fid, "lane": "A_core"}
                for fid in ("303", "404", "505", "606")
            ],
        },
    }, grounded=True)

    assert "10.x/off-claim-303" not in memo
    assert "`fact_id=606` (`A_core`)" not in memo


def test_grounded_repair_preserves_gate_approved_cited_source_floor(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for fid in ("303", "404", "505", "606"):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": "Carbon pricing reduced emissions in audited firms.",
            "source_paper": {"doi": f"10.x/cited-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "receipt_expansion": {
            "cited_bound_fact_ids": ["101", "303", "404", "505", "606"],
            "candidate_receipts": [
                {"fact_id": "7001", "lane": "A_core"},
            ],
        },
    }, grounded=True)

    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "**Source breadth:** `5/5` unique cited source(s)" in memo
    assert "10.x/cited-606" in memo


def test_alpha_memo_uses_available_receipts_when_sources_are_concentrated(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    for fid in ("303", "404", "505", "606"):
        facts.append({
            "fact_id": fid,
            "canonical_phrase": "Emissions reduction followed carbon pricing.",
            "source_paper": {"doi": f"10.x/diverse-{fid}"},
        })
        lanes["verdicts"].append({"fact_id": fid, "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "receipt_expansion": {
            "needed": False,
            "cited_bound_fact_ids": ["101"],
            "available_bound_fact_ids": ["101", "303", "404", "505", "606"],
        },
    })

    assert "**Direct source breadth:** `5` direct cited source(s)" in memo
    assert "`fact_id=606` (`A_core`)" in memo


def test_alpha_memo_turns_repeated_title_into_declarative_thesis(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    gate = json.loads((run / "opportunities_gate.json").read_text(encoding="utf-8"))
    gate["audits"][0]["rationale"] = "Carbon pricing may cut emissions without the expected output penalty"
    (run / "opportunities_gate.json").write_text(json.dumps(gate), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={"surface_type": "publish_alpha_memo"})
    thesis = memo.split("## One-sentence thesis\n\n", 1)[1].split("\n\n## ", 1)[0]

    assert thesis != gate["audits"][0]["rationale"]
    assert "The cited A/B receipts support a specific working claim" in thesis


def test_alpha_memo_selects_boundary_angle_over_generic_surprise(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    facts.append({
        "fact_id": "303",
        "canonical_phrase": "Emissions fell in cities but output losses persisted elsewhere.",
        "source_paper": {"doi": "10.x/boundary"},
    })
    lanes["verdicts"].append({"fact_id": "303", "lane": "B_context"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={"surface_type": "publish_alpha_memo"})

    assert "**Selected angle:** `boundary_condition`" in memo
    assert "**Headline:** Carbon tax may hinge on a boundary condition" in memo
    assert "where the evidence stops generalizing" in memo
    assert "output losses persisted elsewhere" in memo


def test_alpha_memo_abandons_weak_angles_below_config_floor(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)

    memo = render_signal_memo(run, publish_verdict={"surface_type": "publish_alpha_memo"})

    assert _memo_alpha_int("min_angle_score", 0) == 45
    assert "**Selected angle:** `source`" in memo
    assert "**Headline:** Carbon pricing may cut emissions" in memo
    assert "has a live counter-signal" not in memo
    assert "may hinge on a boundary condition" not in memo


def test_grounded_repair_rebuilds_headline_from_direct_receipts(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)

    memo = render_signal_memo(
        run,
        publish_verdict={"surface_type": "publish_alpha_memo"},
        grounded=True,
    )

    assert "**Selected angle:** `source`" in memo
    assert (
        "**Headline:** Bounded Carbon tax signal: "
        "Emissions fell 8% after the intervention"
    ) in memo
    assert "**Source thesis:** Carbon pricing may cut emissions" in memo


def test_source_angle_grounds_unsupported_tension_headline(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    (run / "signal_post.md").write_text(
        "# Signal — carbon_tax\n\n"
        "## Carbon tax paradox may obscure harm in the majority subgroup\n\n"
        "## Why this is surprising\n\n"
        "A speculative tension frame.\n\n"
        "## Confidence — `evidence_backed_signal`\n",
        encoding="utf-8",
    )

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "counter_evidence": {"status": "none_found", "items": []},
    })

    assert "**Selected angle:** `source`" in memo
    assert "**Headline:** Bounded Carbon tax signal: Emissions fell 8%" in memo
    assert "Carbon tax paradox may obscure harm" not in memo


def test_alpha_memo_selects_counter_signal_angle_when_counter_receipt_exists(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "counter_evidence": {"items": [{
            "fact_id": "404",
            "lane": "A_core",
            "phrase": "Output fell after the intervention in a matched market.",
        }]},
    })

    assert "**Selected angle:** `counter_signal`" in memo
    assert "**Headline:** Carbon tax has a live counter-signal" in memo
    assert "The cited receipts show an apparent collision" in memo
    assert "opposing endpoint" in memo
    assert "**Bounded research question:** Does the contrast between" in memo
    assert "Testable hypothesis:" in memo
    assert "not a generalizable finding" in memo
    assert "matched market" in memo


def test_alpha_memo_rejects_incoherent_counter_and_boundary_angles(
    tmp_path: Path,
) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _write_run(run)
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    facts.append({
        "fact_id": "303",
        "canonical_phrase": "Hospital payroll timing did not change after a staffing audit.",
        "source_paper": {"doi": "10.x/payroll"},
    })
    lanes["verdicts"].append({"fact_id": "303", "lane": "A_core"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={
        "surface_type": "publish_alpha_memo",
        "counter_evidence": {"items": [{
            "fact_id": "404",
            "lane": "A_core",
            "phrase": "Hepatic exposure did not change in a pharmacokinetic substudy.",
        }]},
        "receipt_expansion": {
            "needed": True,
            "available_bound_fact_ids": ["101", "303"],
            "candidate_receipts": [{"fact_id": "303", "lane": "A_core"}],
        },
    })

    assert "**Selected angle:** `source`" in memo
    assert "fact_id=303" not in memo
    assert "has a live counter-signal" not in memo
    assert "may hinge on a boundary condition" not in memo


def test_alpha_angle_selection_uses_live_publication_config(tmp_path: Path) -> None:
    run = tmp_path / "grid_storage_tariff-evidence-ts"
    _write_run(run)
    review = json.loads((run / "frontier_review.json").read_text(encoding="utf-8"))
    review["topic"] = "grid_storage_tariff"
    (run / "frontier_review.json").write_text(json.dumps(review), encoding="utf-8")
    facts = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
    lanes = json.loads((run / "fact_lanes.json").read_text(encoding="utf-8"))
    facts[0]["canonical_phrase"] = "Grid storage tariffs improved adoption in cities."
    facts.append({
        "fact_id": "303",
        "canonical_phrase": "Grid storage tariffs improved adoption but raised peak prices elsewhere.",
        "source_paper": {"doi": "10.x/grid"},
    })
    lanes["verdicts"].append({"fact_id": "303", "lane": "B_context"})
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps(lanes), encoding="utf-8")

    memo = render_signal_memo(run, publish_verdict={"surface_type": "publish_alpha_memo"})

    assert _memo_alpha_int("angle_candidates", 0) == 5
    assert "**Selected angle:** `boundary_condition`" in memo
    assert "**Headline:** Grid storage tariff may hinge on a boundary condition" in memo


def test_recent_angle_history_flips_selection() -> None:
    """C2 novelty archive: the same evidence bundle picks the sharp boundary
    angle fresh, but once that angle dominates recent siblings the repeat
    penalty rejects it and a different angle is selected."""
    from agent.signal_memo_writer import _select_angle

    facts: dict[str, dict[str, Any]] = {
        "a": {"canonical_phrase": "Primary outcome improved by 30%"},
        "b": {"canonical_phrase": "Primary outcome improved differently in older adults"},
    }
    kw = dict(
        topic="t", headline="H", thesis="T", why="W", facts=facts,
        lead_ids=["a"], context_ids=["b"], verdict=None, source_count=5,
    )
    fresh = _select_angle(**kw)  # type: ignore[arg-type]
    repeated = _select_angle(**kw, recent_kinds={"boundary_condition": 3})  # type: ignore[arg-type]
    assert fresh["kind"] == "boundary_condition"
    assert repeated["kind"] != "boundary_condition"


def test_recent_angle_kinds_reads_sibling_memos(tmp_path: Path) -> None:
    """_recent_angle_kinds parses selected-angle lines from sibling alpha memos."""
    from agent.signal_memo_writer import _recent_angle_kinds

    root = tmp_path / "runs"
    for name, kind in (("t1-evidence-a", "source"), ("t2-evidence-b", "boundary_condition")):
        d = root / name
        d.mkdir(parents=True)
        (d / "alpha_memo.md").write_text(
            f"# Alpha memo\n\n**Selected angle:** `{kind}`\n", encoding="utf-8")
    target = root / "t3-evidence-c"
    target.mkdir()
    counts = _recent_angle_kinds(target)
    assert counts == {"source": 1, "boundary_condition": 1}


def test_journal_quality_signal_summarizes_cited_sources() -> None:
    """paper-qa-style source-quality signal: counts journal-named sources and
    means the curated quality_score over the cited receipts."""
    from agent.signal_memo_writer import journal_quality

    facts: dict[str, dict[str, Any]] = {
        "1": {"source_paper": {"doi": "10.x/a", "journal_name": "Nature", "quality_score": 90}},
        "2": {"source_paper": {"doi": "10.x/b", "journal_name": "", "quality_score": 50}},
        "3": {"source_paper": {"doi": "10.x/c", "title": "Preprint"}},  # no journal/score
    }
    q = journal_quality(facts, ["1", "2", "3"])
    assert q["sources"] == 3
    assert q["with_journal"] == 1            # only "Nature" is named
    assert q["mean_quality_score"] == 70.0   # (90 + 50) / 2
    assert journal_quality({}, [])["mean_quality_score"] is None


def test_claim_receipt_matrix_carries_journal_quality() -> None:
    from agent.signal_memo_writer import build_claim_receipt_matrix

    facts = {"1": {"canonical_phrase": "Emissions fell 8%",
                   "source_paper": {"doi": "10.x/a", "journal_name": "Nature",
                                    "quality_score": 88}}}
    matrix = build_claim_receipt_matrix({"emissions", "fell"}, ["1"], ["1"], facts)
    assert matrix["journal_quality"]["with_journal"] == 1
    assert matrix["journal_quality"]["mean_quality_score"] == 88.0


def test_memo_audit_verdict_thresholds() -> None:
    """FactReview-style verdict from v4's own signals: 1 direct -> inconclusive,
    2 -> partially_supported, >=floor -> supported, any conflict -> in_conflict."""
    from agent.signal_memo_writer import build_memo_audit

    facts = {
        str(i): {"canonical_phrase": "Emissions fell after carbon pricing",
                 "source_paper": {"doi": f"10.x/{i}", "journal_name": "Nature",
                                  "quality_score": 80}}
        for i in range(1, 6)
    }
    claim = {"emissions", "fell"}
    nov = {"selected": "source", "repeats": 0}

    a1 = build_memo_audit(claim, ["1"], ["1"], facts, None, falsifier=True, novelty=nov)
    assert a1["verdict"] == "inconclusive"
    a2 = build_memo_audit(claim, ["1", "2"], ["1", "2"], facts, None,
                          falsifier=True, novelty=nov)
    assert a2["verdict"] == "partially_supported"
    a5 = build_memo_audit(claim, list("12345"), list("12345"), facts, None,
                          falsifier=True, novelty=nov, min_direct=5)
    assert a5["verdict"] == "supported"
    conflict = {"counter_evidence": {"items": [
        {"fact_id": "9", "lane": "A_core", "phrase": "No effect found",
         "source_paper": {"title": "Null study"}}]}}
    ac = build_memo_audit(claim, list("12345"), list("12345"), facts, conflict,
                          falsifier=True, novelty=nov, min_direct=5)
    assert ac["verdict"] == "in_conflict"
    assert len(ac["contradiction_receipts"]) == 1
    assert ac["contradiction_receipts"][0]["snippet"] == "No effect found"


def test_memo_audit_carries_novelty_delta_and_gate_failures() -> None:
    """Audit pack aggregates v4's deterministic novelty signals without new
    model calls or external datastore dependencies."""
    from agent.signal_memo_writer import build_memo_audit

    facts = {"1": {"canonical_phrase": "Emissions fell 8%",
                   "source_paper": {"doi": "10.x/a", "journal_name": "Nature",
                                    "quality_score": 90}}}
    audit = build_memo_audit({"emissions", "fell"}, ["1"], ["1"], facts, None,
                             falsifier=False, novelty={"selected": "boundary_condition",
                                                       "repeats": 3})
    assert audit["falsifier_present"] is False
    assert audit["novelty"] == {"selected_angle": "boundary_condition",
                                "recent_repeats": 3, "signal": "repeated"}
    assert audit["source_hygiene"]["mean_quality_score"] == 90.0
    assert audit["risk_of_bias"] == "not_required"
    assert audit["nearest_literature"] == []
    assert audit["novelty_delta"]["label"] == "repeated"
    assert audit["audit_gate"] == {
        "passed": False,
        "failures": ["novelty_delta_repeated", "memo_missing_falsifier"],
    }


def test_memo_audit_types_counter_evidence_and_nearest_claims() -> None:
    from agent.signal_memo_writer import build_memo_audit

    facts = {
        "1": {
            "canonical_phrase": "Emissions fell after carbon pricing",
            "source_paper": {"doi": "10.x/a", "title": "Randomized trial in patients"},
        },
        "2": {
            "canonical_phrase": "Emissions were unchanged after carbon pricing",
            "source_paper": {"doi": "10.x/b", "title": "Null result in patients"},
        },
    }
    verdict = {"counter_evidence": {"items": [{
        "fact_id": "2", "lane": "A_core",
        "phrase": "Emissions were unchanged after carbon pricing",
        "source_paper": {"doi": "10.x/b", "title": "Null result in patients"},
    }]}}

    audit = build_memo_audit(
        {"emissions", "carbon", "pricing"}, ["1"], ["1"], facts, verdict,
        falsifier=True, novelty={"selected": "counter_signal", "repeats": 0},
    )

    assert audit["contradiction_receipts"][0]["type"] == "null_result"
    assert audit["contradiction_receipts"][0]["opposition_strength"] == 80
    assert audit["nearest_literature"][0]["reference"] == "2"
    assert audit["novelty_delta"]["label"] == "contradictory"
    assert audit["risk_of_bias"] == "missing_for_human_claim"
    assert "risk_of_bias_missing_for_human_claim" in audit["audit_gate"]["failures"]


def test_memo_audit_schema_is_strictly_typed() -> None:
    from agent.signal_memo_writer import build_memo_audit, validate_memo_audit_schema

    facts = {
        str(i): {"canonical_phrase": "Emissions fell after carbon pricing",
                 "source_paper": {"doi": f"10.x/{i}"}}
        for i in range(1, 6)
    }
    audit = build_memo_audit(
        {"emissions", "fell"}, list("12345"), list("12345"), facts, None,
        falsifier=True, novelty={"selected": "source", "repeats": 0},
    )

    assert validate_memo_audit_schema(audit) == []
    broken = audit | {"claim_units": "not-a-list"}
    assert validate_memo_audit_schema(broken) == ["claim_units"]


def test_alpha_memo_runtime_excludes_full_paper_and_ingestion_deps() -> None:
    """v4 alpha memos borrow patterns from heavier tools without adding them
    to the runtime/parser surface."""
    config = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    def package_name(dependency: str) -> str:
        return re.split(r"[<>=!~\[]", dependency, maxsplit=1)[0].lower().replace("_", "-")

    runtime_deps = {
        package_name(str(dep)) for dep in config["project"].get("dependencies", [])
    }
    dev_deps = {
        package_name(str(dep))
        for dep in config["project"].get("optional-dependencies", {}).get("dev", [])
    }
    alpha_runtime_exclusions = {
        "deepeval",
        "docling",
        "dspy",
        "flagembedding",
        "outlines",
        "scispacy",
        "sciwrite-lint",
        "sentence-transformers",
        "textgrad",
        "typst",
    }
    full_paper_or_parser_deps = {"docling", "scispacy", "sciwrite-lint", "typst"}

    assert not runtime_deps & alpha_runtime_exclusions
    assert not dev_deps & full_paper_or_parser_deps
