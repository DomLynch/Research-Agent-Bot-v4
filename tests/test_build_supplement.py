"""Sprint 11.1 — supplement generator tests.

Cover S1-S10 rendering from a synthetic receipts fixture. The supplement
is a pure consumer of files in a run-dir; this test writes a minimal
fixture run-dir with the receipts the builder reads, then asserts every
canonical block surfaces with the values supplied by the fixture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.topic_pack import TopicPack
from scripts.build_supplement import build


def _pack() -> TopicPack:
    return TopicPack(
        topic="rapamycin",
        display_name="Rapamycin / Murine Lifespan",
        primary_system="mouse",
        preferred_terms=("mouse",),
        discouraged_terms=("yeast",),
        endpoint="lifespan",
        cite_role_default="literature-reference",
        cite_roles_allowed=("primary-study", "prior-meta-analysis"),
        anchors=MappingProxyType({}),
        length_caps=MappingProxyType({}),
        min_words_per_citation=80,
        outcome_nouns_extra=(),
        direction_verbs_extra=(),
        subjects_extra=(),
        primary_interventions=("rapamycin", "sirolimus"),
        translational_only_interventions=("everolimus",),
        retrieval_sources=("pubmed", "europe-pmc"),
        eligibility_endpoint_terms=("lifespan", "survival"),
        eligibility_control_terms=("vehicle", "ad libitum control"),
        eligibility_exclude_design_terms=("yeast",),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=2000,
        sentinel_primary=("harrison-2009-rapamycin",),
        sentinel_prior_meta=("swindell-2017-meta",),
        non_mouse_species_terms=("rat",),
        secondary_design_quote_markers=("crossover",),
        references_bibliography=MappingProxyType(
            {"harrison-2009-rapamycin": "Harrison DE et al. Nature 2009."}
        ),
    )


def _write_fixture_run_dir(tmp_path: Path) -> Path:
    pd = tmp_path / "rapamycin-paper-fixture"
    pd.mkdir()
    (pd / "eligibility_summary.json").write_text(json.dumps({
        "k_hits": 502, "k_candidates": 298, "k_full_text_located": 256,
        "k_parsed_with_text": 75, "k_eligible": 8,
        "final_decisions": {"include": 8, "exclude": 60, "unclear": 7},
        "judge_model": "google/gemma-4-31b-it",
    }), encoding="utf-8")
    (pd / "primary_effect_input_set_strict.json").write_text(json.dumps({
        "A_core_direct_lifespan": [
            {"study_id": "s086",
             "title": "Rapamycin fed late in life extends lifespan",
             "year": 2009, "venue": "Nature", "doi": "10.1038/nature08221"},
        ],
        "C_secondary_contextual": [
            {"study_id": "s999", "title": "Demoted study",
             "demoted_from": "A_core", "demote_reasons": ["wrong species"]},
        ],
        "demote_reasons": {"s999": ["wrong species"]},
    }), encoding="utf-8")
    (pd / "effect_extractions.json").write_text(json.dumps({
        "receipts": [
            {"study_id": "s086", "status": "extracted",
             "metric": "maximum_lifespan_90th_percentile_days",
             "treated_value": 1245.0, "control_value": 1094.0,
             "treated_n": None, "control_n": None,
             "hazard_ratio": None, "percent_change": 14.0},
        ],
    }), encoding="utf-8")
    (pd / "effect_pool.json").write_text(json.dumps({
        "effects": [
            {"study_id": "s246", "metric": "log_median_ratio",
             "estimate": 0.3882, "se": 0.2144,
             "ci_low": -0.0319, "ci_high": 0.8084},
        ],
        "skipped_study_ids": ["s086", "s230", "s235"],
    }), encoding="utf-8")
    (pd / "manual_full_text_audit.json").write_text(json.dumps([
        {"study_id": "s086",
         "source_path": "topic_packs/manual_full_text/rapamycin/harrison-2009.txt",
         "byte_count": 12345,
         "file_hash_sha256": "abc123def456abc123def456abc123def456",
         "reason": "sentinel paper not auto-retrievable"},
    ]), encoding="utf-8")
    (pd / "qa_report.md").write_text(
        "# QA report\n\nAll gates green.\n", encoding="utf-8",
    )
    return pd


def test_supplement_renders_all_canonical_blocks(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    for header in (
        "## S1 — Search Strategy",
        "## S2 — Screening Counts",
        "## S3 — Eligibility Receipts",
        "## S4 — Strict A-core Corpus",
        "## S5 — Effect Extraction Receipts",
        "### S5b — Inverse-variance pool",
        "## S6 — Risk-of-Bias Notes",
        "## S7 — Sentinel Recall Audit",
        "## S8 — Excluded / Demoted Studies",
        "## S9 — Code and Data Availability",
        "## S10 — QA Report (verbatim, from upstream eligibility run)",
    ):
        assert header in out, f"missing header: {header}"


def test_supplement_pulls_counts_from_eligibility_summary(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "**502**" in out  # k_hits
    assert "**298**" in out  # candidates
    assert "**256**" in out  # full-text located
    assert "**75**" in out   # parsed
    assert "google/gemma-4-31b-it" in out


def test_supplement_does_not_claim_absent_eligibility_receipts(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "`eligibility_receipts.json` alongside this supplement" not in out
    assert "not packaged in this final paper folder" in out


def test_supplement_sentinel_text_points_to_embedded_s10_when_qa_loaded(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "rendered below in S10 from the upstream QA report" in out
    assert "is rendered in `qa_report.md`" not in out


def test_supplement_strict_a_core_table_lists_study(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "s086" in out
    assert "10.1038/nature08221" in out
    assert "(k = 1)" in out


def test_supplement_demoted_studies_table_shows_reasons(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "s999" in out
    assert "wrong species" in out


def test_supplement_inverse_variance_table_renders_pool(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "s246" in out
    assert "log_median_ratio" in out
    assert "0.3882" in out
    assert "Skipped (no inverse-variance numerics)" in out


def test_supplement_sentinel_audit_shows_manual_override_hash(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    # SHA-256 truncated to 18 chars in the supplement table.
    assert "abc123def456abc12" in out
    assert "harrison-2009-rapamycin" in out


def test_supplement_appends_verbatim_qa_report(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    with patch("scripts.build_supplement.load_topic_pack", return_value=_pack()):
        out = build(pd, "rapamycin")
    assert "All gates green." in out


def test_supplement_raises_without_topic_pack(tmp_path: Path) -> None:
    pd = _write_fixture_run_dir(tmp_path)
    import pytest
    with (
        patch("scripts.build_supplement.load_topic_pack", return_value=None),
        pytest.raises(RuntimeError, match="no topic pack"),
    ):
        build(pd, "ghost-topic")
