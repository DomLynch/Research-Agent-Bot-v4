"""Sprint 45 — digest-renderer tests.

Locks the markdown view contract:
  - empty digest renders without error
  - opportunities surface in priority order (carried from input)
  - missing/wrong-type fields coerce to placeholders, never raise
  - reason label maps known triggers; unknown reasons pass through verbatim
Universal: every fixture uses generic topic ids; no domain literals.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from render_digest import render_digest


def test_empty_digest_renders_placeholder() -> None:
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 0,
                        "opportunities": []})
    assert "Publish-Opportunity Digest" in md
    assert "Opportunities surfaced:** 0" in md
    assert "No publish-opportunities triggered" in md


def test_known_reason_labels_map_to_human_text() -> None:
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 1,
                        "opportunities": [{
                            "topic": "topic_a", "reason": "publication_opportunity_fires",
                            "confidence_0_100": 80, "delta_points": 5,
                            "claim_text": "c", "paper_type": "x",
                            "supporting_study_count": 2, "snapshot_utc": "t",
                            "priority": 85,
                        }]})
    assert "Publication opportunity" in md
    assert "publication_opportunity_fires" not in md  # raw key not surfaced


def test_unknown_reason_passes_through_verbatim() -> None:
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 1,
                        "opportunities": [{
                            "topic": "topic_a", "reason": "novel_trigger_kind",
                            "confidence_0_100": 50, "delta_points": 0,
                            "claim_text": "c", "paper_type": "x",
                            "supporting_study_count": 0, "snapshot_utc": "t",
                            "priority": 50,
                        }]})
    assert "novel_trigger_kind" in md  # unknown reasons not silently dropped


def test_priority_order_preserved_from_input() -> None:
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 2,
                        "opportunities": [
                            {"topic": "first", "priority": 95, "reason": "strong_mover",
                             "confidence_0_100": 40, "delta_points": -25,
                             "claim_text": "c1", "paper_type": "x",
                             "supporting_study_count": 0, "snapshot_utc": "t"},
                            {"topic": "second", "priority": 70, "reason": "strong_mover",
                             "confidence_0_100": 60, "delta_points": 15,
                             "claim_text": "c2", "paper_type": "x",
                             "supporting_study_count": 1, "snapshot_utc": "t"},
                        ]})
    assert md.index("first") < md.index("second")  # ordering preserved
    assert "#1 — first" in md and "#2 — second" in md


def test_malformed_opportunity_does_not_raise() -> None:
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 1,
                        "opportunities": [
                            "not-a-dict",  # wrong type — must be skipped
                            {"topic": None, "priority": "bad",  # wrong types
                             "confidence_0_100": "x", "delta_points": "y",
                             "claim_text": None, "paper_type": None,
                             "supporting_study_count": None, "snapshot_utc": None,
                             "reason": None},
                        ]})
    # The dict survives (with coerced defaults); the string is dropped.
    assert "#1" in md and "#2" not in md
    assert "(no claim text)" in md
    assert "(unspecified)" in md


def test_opportunities_not_a_list_renders_empty() -> None:
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 0,
                        "opportunities": "not-a-list"})
    assert "Opportunities surfaced:** 0" in md
    assert "No publish-opportunities" in md


def test_delta_sign_rendered_explicitly() -> None:
    md_neg = render_digest({"snapshot_utc": "t", "topics_inspected": 1,
                            "opportunities": [{
                                "topic": "t", "reason": "strong_mover",
                                "confidence_0_100": 38, "delta_points": -32,
                                "claim_text": "c", "paper_type": "x",
                                "supporting_study_count": 0,
                                "snapshot_utc": "t", "priority": 100,
                            }]})
    assert "Δ -32 pts" in md_neg
    md_pos = render_digest({"snapshot_utc": "t", "topics_inspected": 1,
                            "opportunities": [{
                                "topic": "t", "reason": "strong_mover",
                                "confidence_0_100": 62, "delta_points": 12,
                                "claim_text": "c", "paper_type": "x",
                                "supporting_study_count": 0,
                                "snapshot_utc": "t", "priority": 48,
                            }]})
    assert "Δ +12 pts" in md_pos  # sign explicit for positive deltas


def test_universal_no_biomedical_coupling() -> None:
    """Renderer treats a climate-policy topic identically to any other."""
    md = render_digest({"snapshot_utc": "t", "topics_inspected": 1,
                        "opportunities": [{
                            "topic": "carbon_tax", "reason": "publication_opportunity_fires",
                            "confidence_0_100": 78, "delta_points": 8,
                            "claim_text": "carbon tax → emissions reduction",
                            "paper_type": "pilot-meta-analysis",
                            "supporting_study_count": 2,
                            "snapshot_utc": "t", "priority": 86,
                        }]})
    assert "carbon_tax" in md
    assert "carbon tax → emissions reduction" in md
