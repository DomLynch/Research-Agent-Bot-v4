"""Sprint 11.3 — study-characteristics table tests."""
from __future__ import annotations

from agent.study_table import build_study_characteristics_table


def test_returns_empty_when_no_a_core_records() -> None:
    assert build_study_characteristics_table({}, {}, {}) == ""


def test_renders_table_with_headers_and_rows() -> None:
    strict = {"A_core_direct_lifespan": [
        {"study_id": "s086", "title": "Rapamycin late life", "year": 2009},
    ]}
    extr = {"receipts": [{
        "study_id": "s086", "status": "extracted",
        "metric": "maximum_lifespan_90th_percentile_days",
        "treated_value": 1245.0, "control_value": 1094.0,
        "treated_n": None, "control_n": None,
        "moderators": {"sex": "female", "strain": "UM-HET3"},
    }]}
    pool = {"effects": [], "skipped_study_ids": ["s086"]}
    out = build_study_characteristics_table(strict, extr, pool)
    assert "### Study Characteristics Table" in out
    assert "| Study |" in out
    assert "| s086 |" in out
    assert "UM-HET3" in out
    assert "female" in out
    assert "1245.0" in out
    assert "no inverse-variance numerics" in out
    assert "| No |" in out


def test_pooled_study_marks_yes_with_no_reason() -> None:
    strict = {"A_core_direct_lifespan": [
        {"study_id": "s246"},
    ]}
    extr = {"receipts": [{
        "study_id": "s246", "status": "extracted",
        "metric": "median_lifespan_months",
        "treated_value": 11.5, "control_value": 7.8,
        "treated_n": 31, "control_n": 73,
        "moderators": {"dose": "0.5mg/kg daily"},
    }]}
    pool = {"effects": [{"study_id": "s246"}], "skipped_study_ids": []}
    out = build_study_characteristics_table(strict, extr, pool)
    assert "| s246 |" in out
    assert "| 31 |" in out
    assert "| 73 |" in out
    assert "| Yes |" in out


def test_missing_moderator_fields_render_as_em_dash() -> None:
    strict = {"A_core_direct_lifespan": [{"study_id": "s230"}]}
    extr = {"receipts": [{
        "study_id": "s230", "status": "no_numerics",
        "metric": "survival", "moderators": {},
    }]}
    pool = {"effects": [], "skipped_study_ids": ["s230"]}
    out = build_study_characteristics_table(strict, extr, pool)
    # Each missing field renders as em-dash; we check the presence in row.
    assert "| s230 |" in out
    assert "—" in out
