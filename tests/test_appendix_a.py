"""Sprint 11.4 — appendix_a renderer tests.

Cover:
  - render_appendix_a emits the canonical block headers + per-study lines
  - two-lane pool block separates A-core from B sensitivity
  - replace_appendix_a swaps a body's existing Appendix A with the new
    rendered version, leaving downstream sections intact
  - empty receipts render placeholder lines (no crash)
"""
from __future__ import annotations

from typing import Any

from agent.appendix_a import render_appendix_a, replace_appendix_a


def _fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary = {
        "topic": "rapamycin", "iter": 20,
        "k_hits": 502, "k_candidates": 298, "k_full_text_located": 256,
        "k_parsed_with_text": 75,
        "final_decisions": {"include": 8, "exclude": 60, "unclear": 7},
        "contract_violations": 0,
        "judge_model": "google/gemma-4-31b-it",
    }
    strict = {"A_core_direct_lifespan": [
        {"study_id": "s086", "title": "Harrison 2009",
         "year": 2009, "venue": "Nature", "doi": "10.1038/nature08221"},
        {"study_id": "s288", "title": "Bitto 2016 transient",
         "year": 2016, "venue": "eLife", "doi": "10.7554/eLife.16351"},
    ]}
    extr = {"receipts": [
        {"study_id": "s086", "status": "parse_failed", "metric": "",
         "moderators": {}},
        {"study_id": "s288", "status": "extracted",
         "metric": "median_lifespan_days",
         "treated_value": 1054.0, "control_value": 925.0,
         "treated_n": 17, "control_n": 18,
         "moderators": {"sex": "male"}},
    ]}
    pool = {
        "effects": [{
            "study_id": "s288", "metric": "log_median_ratio",
            "estimate": 0.1306, "se": 0.3382,
            "ci_low": -0.5323, "ci_high": 0.7934,
        }],
        "sensitivity_effects": [{
            "study_id": "s246", "metric": "log_median_ratio",
            "estimate": 0.3882, "se": 0.2144,
            "ci_low": -0.0319, "ci_high": 0.8084,
        }],
        "skipped_study_ids": ["s086"],
    }
    return summary, strict, extr, pool


def test_render_appendix_a_emits_canonical_blocks() -> None:
    out = render_appendix_a(*_fixture())
    for header in (
        "## Appendix A — Run audit",
        "### Strict A-core",
        "### Effect extraction receipts",
        "### Primary pool (A-core, wild-type direct-lifespan)",
        "### Sensitivity pool (B disease-model / genotype-modified)",
    ):
        assert header in out, f"missing: {header}"


def test_render_appendix_a_two_lane_split() -> None:
    out = render_appendix_a(*_fixture())
    # A-core pool has s288; sensitivity has s246
    a_pool_idx = out.find("### Primary pool")
    b_pool_idx = out.find("### Sensitivity pool")
    a_block = out[a_pool_idx:b_pool_idx]
    b_block = out[b_pool_idx:]
    assert "s288" in a_block
    assert "s288" not in b_block
    assert "s246" in b_block
    assert "s246" not in a_block


def test_render_appendix_a_lists_per_study_extraction() -> None:
    out = render_appendix_a(*_fixture())
    assert "s086: status=parse_failed" in out
    assert "s288: status=extracted" in out
    assert "median_lifespan_days" in out
    assert "treated_value=1054.0" in out


def test_replace_appendix_a_swaps_block() -> None:
    body = (
        "## Conclusion\nFin.\n\n"
        "## Appendix A — Run audit (auto-generated from receipts)\n"
        "old stale content here\n\n"
        "### Old subsection\ndata\n\n"
        "## References\n1. Harrison ...\n"
    )
    new = "## Appendix A — Run audit (auto-generated from receipts)\nfresh\n"
    out = replace_appendix_a(body, new)
    assert "old stale content here" not in out
    assert "fresh" in out
    assert "## References" in out
    assert "1. Harrison ..." in out  # downstream prose preserved
    assert "## Conclusion" in out
    assert "Fin." in out


def test_replace_appendix_a_noop_when_no_anchor() -> None:
    body = "## Methods\nx\n## Results\ny\n"
    new = "## Appendix A — new\n"
    assert replace_appendix_a(body, new) == body


def test_render_appendix_a_empty_receipts_renders_placeholders() -> None:
    out = render_appendix_a({}, {}, {}, {})
    assert "(none)" in out
    assert "no A-core contract-passing effects" in out
    assert "no B-lane contract-passing effects" in out
