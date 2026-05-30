"""Golden memo eval (HeurekaBench-style): render memos from synthetic runs and
assert the memo-quality dimensions — angle selected, falsifier present, evidence
receipts bound, source breadth, claim->receipt support. Locks a regression gate
so boring / unsupported memos cannot pass silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.signal_memo_writer import (
    build_claim_receipt_matrix,
    falsifier_present,
    render_signal_memo,
)

_GOLDEN = Path(__file__).parent / "golden_memo_eval.jsonl"
_VERDICT = {"surface_type": "publish_alpha_memo"}


def _make_run(run: Path) -> None:
    """Self-contained synthetic run (non-biomedical, keeps the path universal)."""
    run.mkdir()
    (run / "signal_post.md").write_text(
        "# Signal — carbon_tax\n\n"
        "## Carbon pricing may cut emissions without the expected output penalty\n\n"
        "## Why this is surprising\n\nChallenges a cost-only story.\n",
        encoding="utf-8",
    )
    (run / "frontier_review.json").write_text(
        json.dumps({"topic": "carbon_tax", "snapshot_utc": "ts"}), encoding="utf-8")
    (run / "opportunities_gate.json").write_text(json.dumps({"audits": [{
        "status": "survives", "capped_opportunity": 80,
        "rationale": "Bound receipts show a policy signal.",
        "cited_fact_ids": ["101"]}]}), encoding="utf-8")
    (run / "fact_lanes.json").write_text(
        json.dumps({"verdicts": [{"fact_id": "101", "lane": "A_core"}]}), encoding="utf-8")
    (run / "all_facts.json").write_text(json.dumps([
        {"fact_id": "101",
         "canonical_phrase": "Emissions fell 8% after the carbon pricing intervention.",
         "source_paper": {"doi": "10.x/policy"}}]), encoding="utf-8")


def _dimensions(memo: str) -> dict[str, Any]:
    angle = re.search(r"\*\*Selected angle:\*\*\s*`([a-z_]+)`", memo)
    breadth = re.search(r"\*\*Source breadth:\*\*\s*`(\d+)/", memo)
    return {
        "angle": angle.group(1) if angle else "",
        "falsifier": falsifier_present(memo),
        "receipts": len(re.findall(r"`fact_id=", memo)),
        "source_breadth": int(breadth.group(1)) if breadth else 0,
    }


def _golden_rows() -> dict[str, dict[str, Any]]:
    rows = [json.loads(ln) for ln in _GOLDEN.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return {str(r["id"]): r for r in rows}


def test_golden_set_is_present() -> None:
    assert _golden_rows(), "golden eval set must not be empty"


def test_grounded_memo_passes_quality_bar(tmp_path: Path) -> None:
    run = tmp_path / "carbon_tax-evidence-ts"
    _make_run(run)
    dims = _dimensions(render_signal_memo(run, publish_verdict=_VERDICT))
    assert dims["angle"]                       # an angle was selected
    assert dims["falsifier"] is True           # states what would disprove it
    assert int(dims["receipts"]) >= 1          # evidence is bound
    assert int(dims["source_breadth"]) >= 1    # has cited source breadth
    # claim -> receipt -> support matrix (C3): pure, auditable.
    facts = {"101": {"fact_id": "101",
                     "canonical_phrase": "Emissions fell 8% after the carbon pricing intervention.",
                     "source_paper": {"doi": "10.x/policy"}}}
    matrix = build_claim_receipt_matrix({"emissions", "fell"}, ["101"], ["101"], facts)
    assert matrix["support_level"] in {"weak", "moderate", "strong"}
    assert matrix["direct_sources"] == 1


def test_eval_catches_unsupported_memo(tmp_path: Path) -> None:
    """A run with no facts renders a memo with zero bound receipts -> fails the
    bar, proving the eval flags boring/unsupported output."""
    run = tmp_path / "empty_topic-evidence-ts"
    run.mkdir()
    (run / "signal_post.md").write_text("# Signal — empty_topic\n", encoding="utf-8")
    dims = _dimensions(render_signal_memo(run))
    assert int(dims["receipts"]) == 0


def test_golden_rows_match_rendered_dimensions(tmp_path: Path) -> None:
    row = _golden_rows()["carbon_tax_source"]
    run = tmp_path / "carbon_tax-evidence-ts"
    _make_run(run)
    dims = _dimensions(render_signal_memo(run, publish_verdict=_VERDICT))
    assert bool(dims["angle"]) == row["expect_angle"]
    assert dims["falsifier"] == row["expect_falsifier"]
    assert int(dims["receipts"]) >= int(row["min_receipts"])
    assert int(dims["source_breadth"]) >= int(row["min_source_breadth"])
