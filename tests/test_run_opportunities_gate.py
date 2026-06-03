from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_opportunities_gate import _deterministic_cluster_audit

from agent.fact_lanes import classify_lanes


def _fact(fid: str, phrase: str, *, doi: str) -> dict[str, Any]:
    return {
        "fact_id": fid,
        "canonical_phrase": phrase,
        "population": "middle-aged mice",
        "intervention": "rapamycin",
        "numeric_value": 10.0,
        "units": "%",
        "source_paper": {"doi": doi, "pmid": doi.rsplit("/", 1)[-1]},
    }


def test_deterministic_cluster_audit_recovers_no_thesis_a_core_cluster() -> None:
    facts = [
        _fact(f"f/{i}", f"rapamycin extended lifespan by {10 + i}% in mice", doi=f"10.1/{i}")
        for i in range(5)
    ]
    lanes = classify_lanes(facts, topic="rapamycin")

    audit = _deterministic_cluster_audit("rapamycin", facts, lanes)

    assert audit is not None
    assert audit.thesis_idx == -1
    assert audit.status == "survives"
    assert audit.capped_opportunity == 80
    assert len(audit.cited_fact_ids) == 5


def test_deterministic_cluster_audit_refuses_mixed_a_core_claims() -> None:
    facts = [
        _fact("f/1", "rapamycin extended lifespan by 10% in mice", doi="10.1/1"),
        _fact("f/2", "rapamycin reduced tumor volume by 10% in mice", doi="10.1/2"),
        _fact("f/3", "rapamycin reduced seizures by 10% in mice", doi="10.1/3"),
        _fact("f/4", "rapamycin improved wound closure by 10% in mice", doi="10.1/4"),
        _fact("f/5", "rapamycin changed glucose by 10% in mice", doi="10.1/5"),
    ]
    lanes = classify_lanes(facts, topic="rapamycin")

    assert _deterministic_cluster_audit("rapamycin", facts, lanes) is None
