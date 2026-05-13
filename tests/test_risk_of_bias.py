"""Sprint 21 — risk-of-bias adapter tests.

Locks the canonical framework item counts (SYRCLE 10, Cochrane-RoB-2 5,
ROBINS-I 7), the assessment loader robustness, and the markdown
renderer contract. Universal: every test uses generic study IDs.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.risk_of_bias import (
    COCHRANE_ROB2,
    ROBINS_I,
    SYRCLE,
    RobAssessment,
    load_assessments,
    load_framework,
    render_summary_table,
)


def _write(p: Path, payload: object) -> None:
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_canonical_framework_item_counts() -> None:
    """Item counts match the published framework specs verbatim. If
    these counts ever change, the framework authors revised the spec —
    cross-check before updating."""
    assert len(SYRCLE.items) == 10
    assert len(COCHRANE_ROB2.items) == 5
    assert len(ROBINS_I.items) == 7


def test_load_framework_is_case_insensitive() -> None:
    for name in ("SYRCLE", "syrcle", "Cochrane-RoB-2", "robins-i"):
        f = load_framework(name)
        assert f is not None
        assert f.name.casefold() == name.casefold()


def test_load_framework_returns_none_for_unknown() -> None:
    assert load_framework("Bogus-Framework") is None


def test_load_assessments_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_assessments(tmp_path) == ()


def test_load_assessments_malformed_json_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "risk_of_bias_assessments.json").write_text("oops", encoding="utf-8")
    assert load_assessments(tmp_path) == ()


def test_load_assessments_parses_valid_syrcle_entry(tmp_path: Path) -> None:
    _write(tmp_path / "risk_of_bias_assessments.json", {"assessments": [{
        "study_id": "s01", "framework": "SYRCLE",
        "judgments": {
            "sequence_generation": "low",
            "allocation_concealment": "unclear",
            "blinding_caregivers": "high",
        },
        "notes": {"blinding_caregivers": "neither blinding mention"},
    }]})
    rows = load_assessments(tmp_path)
    assert len(rows) == 1
    a = rows[0]
    assert a.study_id == "s01"
    assert a.framework == "SYRCLE"
    by_id = dict(a.judgments)
    assert by_id["sequence_generation"] == "low"
    assert by_id["allocation_concealment"] == "unclear"
    assert by_id["blinding_caregivers"] == "high"


def test_load_assessments_drops_invalid_judgment_values(tmp_path: Path) -> None:
    """Only the four allowed judgments (low/some-concerns/high/unclear)
    survive the parser. Anything else is silently dropped — the JSON
    file is operator-edited so bad cells are common."""
    _write(tmp_path / "risk_of_bias_assessments.json", {"assessments": [{
        "study_id": "s01", "framework": "SYRCLE",
        "judgments": {
            "sequence_generation": "low",
            "selective_reporting": "definitely-no",  # invalid → dropped
            "blinding_caregivers": "some-concerns",
        },
    }]})
    a = load_assessments(tmp_path)[0]
    ids = {k for k, _ in a.judgments}
    assert ids == {"sequence_generation", "blinding_caregivers"}


def test_load_assessments_drops_unknown_framework_entries(tmp_path: Path) -> None:
    _write(tmp_path / "risk_of_bias_assessments.json", {"assessments": [
        {"study_id": "s01", "framework": "Bogus-RoB",
         "judgments": {"x": "low"}},
        {"study_id": "s02", "framework": "Cochrane-RoB-2",
         "judgments": {"randomization": "low"}},
    ]})
    rows = load_assessments(tmp_path)
    assert len(rows) == 1
    assert rows[0].study_id == "s02"


def test_render_summary_table_returns_empty_when_no_rows() -> None:
    assert render_summary_table((), SYRCLE) == ""


def test_render_summary_table_emits_markdown_table_with_judgments() -> None:
    a1 = RobAssessment(
        study_id="s01", framework="SYRCLE",
        judgments=(
            ("sequence_generation", "low"),
            ("allocation_concealment", "high"),
        ),
        notes=(),
    )
    a2 = RobAssessment(
        study_id="s02", framework="SYRCLE",
        judgments=(
            ("sequence_generation", "unclear"),
            ("blinding_caregivers", "some-concerns"),
        ),
        notes=(),
    )
    md = render_summary_table((a1, a2), SYRCLE)
    assert md.startswith("### Risk of Bias (SYRCLE)")
    assert "| s01 |" in md
    assert "| s02 |" in md
    assert "| low |" in md
    assert "| high |" in md
    assert "| some-concerns |" in md
    # Missing-cell sentinel for items the operator didn't score.
    assert "| — |" in md


def test_render_summary_table_filters_to_requested_framework() -> None:
    """An assessment under a different framework is excluded from the
    chosen-framework table — prevents cross-framework leakage."""
    a1 = RobAssessment(
        study_id="s01", framework="SYRCLE",
        judgments=(("sequence_generation", "low"),), notes=(),
    )
    a2 = RobAssessment(
        study_id="s02", framework="Cochrane-RoB-2",
        judgments=(("randomization", "low"),), notes=(),
    )
    md_s = render_summary_table((a1, a2), SYRCLE)
    md_c = render_summary_table((a1, a2), COCHRANE_ROB2)
    assert "s01" in md_s and "s02" not in md_s
    assert "s02" in md_c and "s01" not in md_c


def test_rob_adapter_universal_for_climate_or_econ_topics(tmp_path: Path) -> None:
    """Same framework + loader works on non-biomedical study ids. The
    framework choice is up to the operator/pack; the adapter is
    domain-agnostic."""
    _write(tmp_path / "risk_of_bias_assessments.json", {"assessments": [
        {"study_id": "city-stockholm-2022", "framework": "ROBINS-I",
         "judgments": {"confounding": "some-concerns",
                       "measurement": "low"}},
    ]})
    rows = load_assessments(tmp_path)
    assert len(rows) == 1
    md = render_summary_table(rows, ROBINS_I)
    assert "city-stockholm-2022" in md
    assert "ROBINS-I" in md
