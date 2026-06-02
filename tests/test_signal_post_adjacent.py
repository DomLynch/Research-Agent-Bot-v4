"""Sprint 76 — adjacent-signals block lock tests.

The auditor's 2026-05-16 sirtuin verdict: Sprint 75's evidence
boundary correctly refused fake theses, but over-pruned the
signal_post. C/D-lane facts (real signal, just unbound) were
discarded entirely. The fix surfaces top-N by magnitude as
'research prompts, NOT cited evidence'. These tests lock:

* C/D facts appear in the section ordered by absolute magnitude.
* Each entry carries its source DOI, fact_id, and current lane.
* A_core / B_context facts NEVER appear (they belong in Evidence).
* Empty C/D pool produces an empty section (no "Adjacent" header).
* Universal — magnitude-based, no domain literals.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_signal_post import (
    _BINDABLE_LANES,
    _adjacent_signals_block,
    _render_signal_post,
)
from build_signal_post import (
    main as signal_post_main,
)


def _fact(fid: str, value: float, phrase: str,
          doi: str = "10.x/y") -> dict[str, Any]:
    return {
        "fact_id": fid, "numeric_value": value,
        "canonical_phrase": phrase,
        "source_paper": {"doi": doi},
    }


def test_adjacent_block_orders_by_absolute_magnitude() -> None:
    """Top-N pulled from C_noise/D_bad facts, sorted by |value|."""
    facts_by_id = {
        "f1": _fact("f1", 10.0, "small effect"),
        "f2": _fact("f2", 80.0, "huge effect"),
        "f3": _fact("f3", 40.0, "medium effect"),
        "f4": _fact("f4", 99.0, "binds to evidence"),
    }
    lanes = {
        "f1": "C_noise", "f2": "D_bad_extraction",
        "f3": "C_noise", "f4": "A_core",   # excluded
    }
    block = _adjacent_signals_block(facts_by_id, lanes, top_n=3)
    assert "## Adjacent signals to consider" in block
    # Order: 80 > 40 > 10
    huge_pos = block.find("huge effect")
    med_pos = block.find("medium effect")
    small_pos = block.find("small effect")
    assert 0 < huge_pos < med_pos < small_pos
    # A_core fact must not leak in.
    assert "binds to evidence" not in block


def test_adjacent_block_labels_as_research_prompts() -> None:
    """The section header must make it explicit these are NOT cited
    evidence. Prevents operators (or downstream tools) treating
    these as published facts."""
    facts_by_id = {"f1": _fact("f1", 50.0, "some C-lane finding")}
    block = _adjacent_signals_block(facts_by_id, {"f1": "C_noise"})
    assert "NOT cited evidence" in block
    assert "research prompts" in block
    # Lane + fact_id present for operator triage.
    assert "lane=`C_noise`" in block
    assert "fact_id=`f1`" in block


def test_adjacent_block_empty_when_no_unbound_facts() -> None:
    """All-A/B fact pool produces no Adjacent section (empty string)."""
    facts_by_id = {"f1": _fact("f1", 60.0, "evidence")}
    block = _adjacent_signals_block(facts_by_id, {"f1": "A_core"})
    assert block == ""


def test_adjacent_block_universal_non_biomedical() -> None:
    """Climate-policy fixture: same magnitude-based ordering, no
    domain literals in the code path."""
    facts_by_id = {
        "f1": _fact("f1", 8.0, "carbon tax cut emissions 8%",
                    doi="10.x/sweden"),
        "f2": _fact("f2", 30.0, "policy reduced poverty 30%",
                    doi="10.x/policy"),
    }
    lanes = {"f1": "C_noise", "f2": "D_bad_extraction"}
    block = _adjacent_signals_block(facts_by_id, lanes, top_n=2)
    assert "policy reduced poverty 30%" in block
    assert "carbon tax cut emissions 8%" in block
    # Larger magnitude first
    assert block.find("30%") < block.find("8%")


def test_bindable_lanes_constant_is_correct() -> None:
    """Sanity check — Adjacent block contract depends on this set."""
    assert frozenset({"A_core", "B_context"}) == _BINDABLE_LANES


def test_curation_needed_evidence_text_matches_label() -> None:
    """A curation-needed post must not render the old evidence-binding
    failure wording under Evidence. The label and evidence copy should
    point to the constructive curation path."""
    audit = {
        "title": "Unbound thesis",
        "status": "rejected",
        "blocking_flags": [],
        "cited_fact_ids": ["f1"],
    }
    facts_by_id = {"f1": _fact("f1", 50.0, "unbound candidate")}
    text = _render_signal_post(
        "topic",
        "ts",
        {"lens": "lens", "next_extractions": ["harvest f1"]},
        audit,
        facts_by_id,
        bound_count=0,
        lane_verdicts={"f1": "D_bad_extraction"},
    )
    assert "## Confidence — `curation_needed`" in text
    assert "- **Curation needed.**" in text
    assert "- **Evidence binding failed.**" not in text


def test_main_writes_curation_brief_and_manifest(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    run = tmp_path / "topic-evidence-ts"
    run.mkdir()
    (run / "frontier_review.json").write_text(json.dumps({
        "topic": "topic",
        "snapshot_utc": "ts",
        "lens": "lens",
        "next_extractions": ["harvest f1"],
        "theses": [{"title": "T"}],
    }), encoding="utf-8")
    (run / "all_facts.json").write_text(json.dumps([
        _fact("f1", 50.0, "needs curation"),
    ]), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": "f1", "lane": "D_bad_extraction"}],
    }), encoding="utf-8")
    (run / "opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "title": "T",
            "status": "rejected",
            "blocking_flags": [],
            "cited_fact_ids": ["f1"],
        }],
    }), encoding="utf-8")
    (run / "MANIFEST.json").write_text(json.dumps({"files": {}}),
                                       encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["build_signal_post.py", "--run", str(run)])
    assert signal_post_main() == 0

    assert "curation_needed" in (run / "signal_post.md").read_text()
    assert "Alpha memo" in (run / "alpha_memo.md").read_text()
    brief = (run / "curation_brief.md").read_text()
    assert "fact_id=f1" in brief
    assert "harvest f1" in brief
    manifest = json.loads((run / "MANIFEST.json").read_text())
    assert "signal_post_md" in manifest["files"]
    assert "alpha_memo_md" in manifest["files"]
    assert "curation_brief_md" in manifest["files"]


def test_main_renders_when_frontier_review_was_skipped(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    run = tmp_path / "quercetin-evidence-2026-06-02T04-22-56Z"
    run.mkdir()
    (run / "MANIFEST.json").write_text(json.dumps({
        "topic": "quercetin",
        "snapshot_utc": "2026-06-02T04-22-56Z",
        "frontier_model": "skipped",
        "files": {},
    }), encoding="utf-8")
    facts = [
        _fact(f"f{i}", float(i), "quercetin improved senescence signal",
              f"10.q/{i}")
        for i in range(1, 6)
    ]
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": f"f{i}", "lane": "A_core"} for i in range(1, 6)],
    }), encoding="utf-8")
    (run / "opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "title": "Quercetin senescence signal",
            "status": "survives",
            "capped_opportunity": 90,
            "blocking_flags": [],
            "cited_fact_ids": [f"f{i}" for i in range(1, 6)],
        }],
    }), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["build_signal_post.py", "--run", str(run)])
    assert signal_post_main() == 0

    assert "Frontier review skipped" in (run / "signal_post.md").read_text()
    assert (run / "alpha_memo.md").exists()
    assert (run / "publish_verdict.json").exists()
    manifest = json.loads((run / "MANIFEST.json").read_text())
    assert "signal_post_md" in manifest["files"]


def test_main_preserves_claim_coherent_source_diversity(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    run = tmp_path / "grid_storage-evidence-ts"
    run.mkdir()
    (run / "frontier_review.json").write_text(json.dumps({
        "topic": "grid_storage",
        "snapshot_utc": "ts",
        "lens": "Real contrast: reliability rises while costs fall.",
        "theses": [{"title": "Storage threshold contrast in reserve markets"}],
    }), encoding="utf-8")
    facts = [
        _fact("f1", 50.0, "storage threshold improved reliability", "10.same/a"),
        _fact("f2", 40.0, "storage threshold reduced outages", "10.other/e"),
        _fact("f3", 30.0, "storage threshold lowered costs", "10.same/a"),
        _fact("f4", 20.0, "storage threshold reserve reliability changed prices", "10.other/b"),
        _fact("f5", 10.0, "storage threshold reserve reliability shifted dispatch", "10.other/c"),
        _fact("f6", 5.0, "storage threshold reserve reliability changed risk", "10.other/d"),
    ]
    for f in facts:
        f["source_paper"]["title"] = "Grid storage reserve threshold reliability"
        f["source_paper"]["journal"] = "Grid Review"
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({
        "verdicts": [{"fact_id": f"f{i}", "lane": "A_core"} for i in range(1, 7)],
    }), encoding="utf-8")
    (run / "opportunities_gate.json").write_text(json.dumps({
        "audits": [{
            "title": "Storage threshold contrast in reserve markets",
            "status": "survives",
            "capped_opportunity": 90,
            "blocking_flags": [],
            "cited_fact_ids": ["f1", "f4", "f5", "f6"],
        }],
    }), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["build_signal_post.py", "--run", str(run)])
    assert signal_post_main() == 0

    gate = json.loads((run / "opportunities_gate.json").read_text())
    audit = gate["audits"][0]
    assert audit["cited_fact_ids"] == ["f1", "f4", "f5", "f6"]
    assert "self_repair" not in audit
    verdict = json.loads((run / "publish_verdict.json").read_text())
    assert verdict["decision"] == "ready_to_publish"
    assert "source_dispersion" not in verdict["blockers"]
    assert verdict["axes"]["claim_coherent_source_diversity"] is True
