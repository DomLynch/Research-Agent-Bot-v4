"""Sprint 60 — top-5 dedup + lane render + editorial templates.

Tests the three pure-logic helpers in scripts/build_topic_evidence_run.py:
  _dedup_by_paper_subtopic — collapse same-paper same-sub_topic facts
  _render_md (lane mode)   — split when >=2 sub_topics present in top N
  _editorial_block         — deterministic Why / Caution / Next templates

Each test names the failure mode it locks (Berberine multi-biomarker
monopoly, NAD cross-subtopic mix, missing editorial context). Universal
— uses generic fact ids and `topicA / topicB` style sub_topic labels.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_topic_evidence_run import (
    _dedup_by_paper_subtopic,
    _editorial_block,
    _rankable_facts_for_top,
    _render_md,
)


def _fact(fid: str, *, doi: str = "10.1/a", sub_topic: str = "glycemic",
          phrase: str = "intervention reduced X by 50%",
          population: str = "T2D adults",
          intervention: str = "drug X",
          numeric_value: float = 50.0, units: str = "%") -> dict[str, Any]:
    return {
        "fact_id": fid,
        "source_paper": {"doi": doi, "title": f"Paper {doi}",
                         "journal": "JX", "year": 2020},
        "sub_topic": sub_topic, "canonical_phrase": phrase,
        "population": population, "intervention": intervention,
        "numeric_value": numeric_value, "units": units,
    }


def test_rankable_facts_for_top_keeps_only_a_core_and_b_context() -> None:
    """Sprint 71: top_N cards must not surface D_bad or C_noise facts."""
    facts = [
        _fact("a", phrase="topicA intervention reduced X by 50%",
              intervention="topicA intervention"),
        _fact("b", phrase="topicA biomarker changed by 40%",
              intervention="adjacent treatment", numeric_value=40.0),
        _fact("d", phrase="topicA changed at p < 0.001",
              intervention="topicA intervention", numeric_value=0.001,
              units=""),
        _fact("c", phrase="unrelated intervention reduced X by 60%",
              intervention="unrelated intervention", numeric_value=60.0),
    ]
    out = _rankable_facts_for_top(facts, "topicA")
    assert [f["fact_id"] for f in out] == ["a", "b"]


# ============= Sprint 60a: dedup =============

def test_three_biomarkers_from_one_paper_collapse_to_one_headline() -> None:
    """The Berberine bug: 3 facts from same paper measuring FBS, 2HPP,
    fructosamine should produce ONE top-card, not three."""
    scored = [
        (80, _fact("f/1", phrase="FBS decreased 24.3 mg/dL")),
        (78, _fact("f/2", phrase="2HPP decreased 43.6 mg/dL",
                    numeric_value=43.6, units="mg/dL")),
        (75, _fact("f/3", phrase="fructosamine -80.8 umol/L",
                    numeric_value=80.8, units="umol/L")),
    ]
    out = _dedup_by_paper_subtopic(scored)
    assert len(out) == 1
    headline_score, headline = out[0]
    assert headline_score == 80  # highest score becomes headline
    supp = headline.get("_supporting_facts")
    assert isinstance(supp, list) and len(supp) == 2
    # Order of supporting facts preserves input order after the headline
    assert any("2HPP" in str(s.get("canonical_phrase", "")) for s in supp)
    assert any("fructosamine" in str(s.get("canonical_phrase", "")) for s in supp)


def test_different_papers_same_subtopic_stay_separate() -> None:
    """Two trials measuring the same biomarker (different DOIs) → 2 cards."""
    out = _dedup_by_paper_subtopic([
        (80, _fact("f/1", doi="10.1/a", phrase="trial A -50%")),
        (75, _fact("f/2", doi="10.1/b", phrase="trial B -45%")),
    ])
    assert len(out) == 2


def test_same_paper_different_subtopic_stay_separate() -> None:
    """One paper reporting BOTH glycemic AND lipid outcomes → 2 cards
    (different sub_topics)."""
    out = _dedup_by_paper_subtopic([
        (80, _fact("f/1", doi="10.1/a", sub_topic="glycemic",
                    phrase="A1c down")),
        (75, _fact("f/2", doi="10.1/a", sub_topic="lipid",
                    phrase="LDL down")),
    ])
    assert len(out) == 2


def test_missing_doi_falls_back_to_title_grouping() -> None:
    """No DOI → still groups by paper title + sub_topic."""
    out = _dedup_by_paper_subtopic([
        (80, {"fact_id": "f/1", "source_paper":
              {"doi": "", "title": "Same Paper"},
              "sub_topic": "x", "canonical_phrase": "p1",
              "numeric_value": 1.0, "units": ""}),
        (70, {"fact_id": "f/2", "source_paper":
              {"doi": "", "title": "Same Paper"},
              "sub_topic": "x", "canonical_phrase": "p2",
              "numeric_value": 2.0, "units": ""}),
    ])
    assert len(out) == 1


def test_missing_doi_and_title_treated_as_unique() -> None:
    """No grouping key at all → each fact stays unique."""
    out = _dedup_by_paper_subtopic([
        (80, {"fact_id": "f/1", "source_paper": {},
              "sub_topic": "x", "canonical_phrase": "p1",
              "numeric_value": 1.0, "units": ""}),
        (70, {"fact_id": "f/2", "source_paper": {},
              "sub_topic": "x", "canonical_phrase": "p2",
              "numeric_value": 2.0, "units": ""}),
    ])
    assert len(out) == 2


def test_dedup_preserves_score_order() -> None:
    """Order of headlines = order of first appearance in input."""
    out = _dedup_by_paper_subtopic([
        (90, _fact("f/a", doi="10.1/a")),
        (80, _fact("f/b", doi="10.1/b")),
        (70, _fact("f/c", doi="10.1/a")),  # collapses into f/a
    ])
    assert [s for s, _f in out] == [90, 80]


# ============= Sprint 60b: lane render =============

def test_single_subtopic_renders_flat_not_laned() -> None:
    """All facts share one sub_topic → no lane headers."""
    top = [(80, _fact("f/1", sub_topic="glycemic")),
           (75, _fact("f/2", sub_topic="glycemic", doi="10.1/b"))]
    md = _render_md("topicA", "ts", top, 2, "tier2_search")
    assert "### Lane" not in md
    assert "Sub-topic lanes detected" not in md


def test_two_distinct_subtopics_triggers_lane_render() -> None:
    """The NAD bug: top N spans 2+ sub_topics → render lanes."""
    top = [
        (80, _fact("f/1", sub_topic="liver_disease",
                    phrase="ArLD NAD+ depleted")),
        (75, _fact("f/2", sub_topic="boosters", doi="10.1/b",
                    phrase="NMN 400 mg/kg")),
        (70, _fact("f/3", sub_topic="measurement", doi="10.1/c",
                    phrase="breath EtOH")),
    ]
    md = _render_md("NAD", "ts", top, 3, "tier2_search")
    assert "### Lane" in md
    assert "Sub-topic lanes detected" in md
    assert "liver_disease" in md
    assert "boosters" in md
    assert "measurement" in md


def test_lane_order_stable_from_input() -> None:
    """First sub_topic encountered in top → first lane rendered."""
    top = [
        (80, _fact("f/1", sub_topic="lane_z", phrase="z first")),
        (70, _fact("f/2", sub_topic="lane_a", doi="10.1/b",
                    phrase="a second")),
    ]
    md = _render_md("t", "ts", top, 2, "tier2_search")
    z_pos = md.find("`lane_z`")
    a_pos = md.find("`lane_a`")
    assert 0 < z_pos < a_pos  # z appears before a (input order)


# ============= Sprint 60c: editorial =============

def test_editorial_block_has_three_required_sections() -> None:
    out = _editorial_block(_fact("f/1"), "glycemic", 0)
    assert "**Why it matters:**" in out
    assert "**Caution:**" in out
    assert "**Next question:**" in out


def test_editorial_caution_reflects_supporting_count() -> None:
    """Single fact → k=1; with 2 supporting biomarkers → k=3."""
    bare = _editorial_block(_fact("f/1"), "glycemic", 0)
    rich = _editorial_block(_fact("f/1"), "glycemic", 2)
    assert "k=1" in bare
    assert "k=3" in rich


def test_editorial_mimo_enrichment_overrides_template() -> None:
    """Opt-in MiMo enrichment swaps in richer per-fact context."""
    out = _editorial_block(
        _fact("f/1"), "glycemic", 0,
        mimo_enrichment={
            "why_it_matters": "Specific MiMo-generated context here.",
            "caution": "MiMo notes the strain-specific limit.",
            "next_question": "MiMo's specific next question?",
        },
    )
    assert "Specific MiMo-generated context here." in out
    assert "k=1" not in out  # template caution was replaced
    assert "MiMo's specific next question?" in out


def test_editorial_partial_mimo_keeps_templates_for_missing_fields() -> None:
    """If MiMo returns only why_it_matters, template fills caution + next."""
    out = _editorial_block(
        _fact("f/1"), "glycemic", 0,
        mimo_enrichment={"why_it_matters": "MiMo overrides why."},
    )
    assert "MiMo overrides why." in out
    assert "Single trial" in out  # caution template still in place


def test_lane_render_keeps_editorial_bound_to_original_fact() -> None:
    """Lane grouping reorders cards; MiMo editorial must still follow
    the original fact index, not the rendered rank."""
    top = [
        (80, _fact("f/1", sub_topic="effect", phrase="alpha finding")),
        (75, _fact("f/2", sub_topic="rate", doi="10.1/b",
                   phrase="beta finding")),
        (70, _fact("f/3", sub_topic="effect", doi="10.1/c",
                   phrase="gamma finding")),
    ]
    md = _render_md(
        "t", "ts", top, 3, "tier2_search",
        mimo_editorial={
            0: {"why_it_matters": "why alpha"},
            1: {"why_it_matters": "why beta"},
            2: {"why_it_matters": "why gamma"},
        },
    )
    gamma = md.split("**Finding:** gamma finding", 1)[1].split("---", 1)[0]
    beta = md.split("**Finding:** beta finding", 1)[1].split("---", 1)[0]
    assert "why gamma" in gamma
    assert "why beta" in beta
    assert "why beta" not in gamma
    assert "why gamma" not in beta


# ============= Universal non-biomedical fixture =============

def test_universal_non_biomedical_carbon_tax_dedup() -> None:
    """Climate-policy fixture: two CO2-reduction biomarkers from the
    same paper collapse identically."""
    out = _dedup_by_paper_subtopic([
        (80, _fact("ct/1", doi="ipcc/swe", sub_topic="emissions",
                    phrase="CO2 reduced 8%", population="Sweden",
                    intervention="carbon_tax")),
        (75, _fact("ct/2", doi="ipcc/swe", sub_topic="emissions",
                    phrase="Industrial CO2 reduced 12%",
                    population="Sweden",
                    intervention="carbon_tax")),
    ])
    assert len(out) == 1
    assert out[0][0] == 80
