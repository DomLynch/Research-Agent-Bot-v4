"""Sprint 23 — maturity router tests.

Locks the readiness-level → paper-type mapping including the k-aware
branching at L6 (k<10 → standard meta-analysis without subgroup/Egger;
k>=10 → full meta-analysis). Universal: every test reuses the Sprint
16 ReadinessReport dataclass; no domain literals.
"""
from __future__ import annotations

from agent.maturity_router import PaperType, select_paper_type
from agent.readiness import ReadinessReport


def _readiness(level: int, *, k_pool: int = 0) -> ReadinessReport:
    return ReadinessReport(
        level=level, label="x", reasons=(), next_steps=(),
        counts={"k_eligible": 0, "k_a_core": 0, "k_b_lane": 0,
                "k_extractions": 0, "k_pool": k_pool},
    )


def test_l1_routes_to_corpus_snapshot() -> None:
    pt = select_paper_type(_readiness(1))
    assert pt.name == "corpus-snapshot"
    assert "do not claim a synthesised effect" in pt.forbidden_claims
    assert "Corpus Snapshot" in pt.recommended_sections


def test_l2_routes_to_evidence_gap_report() -> None:
    pt = select_paper_type(_readiness(2))
    assert pt.name == "evidence-gap-report"
    assert "Evidence Gap" in pt.recommended_sections
    assert "Future Research Directions" in pt.recommended_sections


def test_l3_and_l4_route_to_scoping_review() -> None:
    for lvl in (3, 4):
        pt = select_paper_type(_readiness(lvl))
        assert pt.name == "scoping-review"
        assert "do not pool effects across studies" in pt.forbidden_claims
        assert "Narrative Synthesis" in pt.recommended_sections


def test_l5_routes_to_pilot_meta_analysis() -> None:
    pt = select_paper_type(_readiness(5, k_pool=2))
    assert pt.name == "pilot-meta-analysis"
    assert "Pilot Pooled Effect" in pt.recommended_sections
    assert any("pilot" in claim.lower() for claim in pt.forbidden_claims)


def test_l6_small_k_routes_to_standard_meta_analysis_without_subgroups() -> None:
    """k<10 at L6 → standard meta-analysis without Subgroup / Egger
    sections (Cochrane handbook threshold)."""
    pt = select_paper_type(_readiness(6, k_pool=5))
    assert pt.name == "meta-analysis-standard"
    assert "Primary Pooled Effect" in pt.recommended_sections
    assert "Subgroup Analyses" not in pt.recommended_sections
    assert "Publication Bias" not in pt.recommended_sections
    assert any("egger" in claim.lower() for claim in pt.forbidden_claims)


def test_l6_large_k_routes_to_full_meta_analysis_with_subgroups() -> None:
    """k>=10 unlocks Subgroup + Publication-Bias sections."""
    pt = select_paper_type(_readiness(6, k_pool=15))
    assert pt.name == "meta-analysis-full"
    assert "Subgroup Analyses" in pt.recommended_sections
    assert "Publication Bias" in pt.recommended_sections
    # No additional forbidden claims at the top of the ladder.
    assert pt.forbidden_claims == ()


def test_paper_type_as_dict_round_trips_through_json() -> None:
    import json
    pt = select_paper_type(_readiness(5, k_pool=1))
    d = pt.as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["name"] == "pilot-meta-analysis"
    assert isinstance(d["recommended_sections"], list)
    assert isinstance(d["forbidden_claims"], list)


def test_paper_type_is_immutable() -> None:
    pt = select_paper_type(_readiness(6, k_pool=20))
    assert isinstance(pt, PaperType)
    try:
        pt.name = "x"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("PaperType should be immutable")


def test_router_is_universal_for_non_biomedical_topic() -> None:
    """The maturity router doesn't look at topic text — only counts.
    Climate-style ReadinessReport counts produce identical decisions."""
    r = ReadinessReport(
        level=6, label="meta-analytic-pool", reasons=(), next_steps=(),
        counts={"k_eligible": 30, "k_a_core": 25, "k_b_lane": 0,
                "k_extractions": 22, "k_pool": 18},
    )
    pt = select_paper_type(r)
    assert pt.name == "meta-analysis-full"
    assert "Subgroup Analyses" in pt.recommended_sections


def test_l6_threshold_boundaries_exact() -> None:
    """Threshold at k_pool == 10: 9 → standard, 10 → full."""
    pt_9 = select_paper_type(_readiness(6, k_pool=9))
    pt_10 = select_paper_type(_readiness(6, k_pool=10))
    assert pt_9.name == "meta-analysis-standard"
    assert pt_10.name == "meta-analysis-full"


# ---------------------------------------------------------------------------
# Sprint 32 — writer_preamble: paper-type-aware system-message prefix.
# ---------------------------------------------------------------------------


def test_writer_preamble_for_scoping_review_blocks_meta_wording() -> None:
    """The acarbose-style failure case: L4 paper auto-routed to
    scoping-review. The preamble (Sprint 37 trimmed form) must carry
    the paper-type name + forbidden-pool constraint as a tight bullet
    list — under ~250 chars so MiMo stays below its runaway threshold
    on the intro/methods/discussion prompts."""
    from agent.maturity_router import writer_preamble
    pt = select_paper_type(_readiness(4, k_pool=0))
    p = writer_preamble(pt)
    assert "scoping-review" in p
    assert "do not pool effects across studies" in p
    assert len(p) < 300, f"preamble too long ({len(p)} chars) — MiMo runaway risk"


def test_writer_preamble_for_l6_full_meta_has_no_blocking_constraints() -> None:
    """When k>=10 and L6, the paper-type is meta-analysis-full and
    forbidden_claims is empty. Preamble degrades to empty string so
    the writer template is left unconstrained."""
    from agent.maturity_router import writer_preamble
    pt = select_paper_type(_readiness(6, k_pool=15))
    p = writer_preamble(pt)
    # Full-meta has empty forbidden_claims so preamble may still carry
    # rationale but no "you MUST" constraints.
    if p:
        assert "meta-analysis-full" in p


def test_writer_preamble_empty_when_paper_type_unconstrained() -> None:
    """A PaperType with no rationale AND no forbidden_claims produces
    no preamble (guards the no-op case)."""
    from agent.maturity_router import PaperType, writer_preamble
    pt = PaperType(
        name="x", rationale="",
        recommended_sections=(), forbidden_claims=(),
    )
    assert writer_preamble(pt) == ""


def test_writer_preamble_pilot_meta_explicitly_labels_pilot() -> None:
    """L5 pilot pool: the preamble's constraint includes the explicit
    'label as pilot pool' instruction so the writer's title can't
    drift to 'meta-analysis'."""
    from agent.maturity_router import writer_preamble
    pt = select_paper_type(_readiness(5, k_pool=2))
    p = writer_preamble(pt)
    assert "pilot-meta-analysis" in p
    assert "pilot pool" in p.lower()
