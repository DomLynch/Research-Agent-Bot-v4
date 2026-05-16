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

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_signal_post import (
    _BINDABLE_LANES,
    _adjacent_signals_block,
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
