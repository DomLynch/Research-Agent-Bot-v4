"""Signal memo renderer tests.

Locks the product-layer shift from raw Top 5 tables to sharp, citable
alpha memos. Fixtures are non-biomedical so the code path stays
universal.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.publish_tier import publish_verdict
from agent.signal_memo_writer import render_signal_memo, write_signal_memo


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
                "phrase": "Output did not improve in the comparison market.",
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
            "canonical_phrase": f"Independent source {i} replicated the contrast.",
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
