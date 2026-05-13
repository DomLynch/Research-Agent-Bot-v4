"""Sprint 18 — sentinel repair plan tests.

Exercises compute_repair_plan() over hand-built SentinelRecallReceipt
fixtures. Universal: no domain literals; sentinels are generic DOI
strings, pack vocabulary is varied (biomedical + climate + finance) to
prove the plan generator has no hardcoded domain knowledge.
"""
from __future__ import annotations

from types import MappingProxyType

from agent.sentinel_recall import SentinelRecallReceipt, SentinelStatus
from agent.sentinel_repair import compute_repair_plan
from agent.topic_pack import TopicPack


def _pack(bibliography: dict[str, str]) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=(), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}),
        length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=(), translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=(),
        eligibility_control_terms=(),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
        references_bibliography=MappingProxyType(bibliography),
    )


def _receipt(*statuses: SentinelStatus) -> SentinelRecallReceipt:
    return SentinelRecallReceipt(
        statuses=statuses,
        expected_primary=sum(1 for s in statuses if s.role == "primary"),
        expected_prior_meta=sum(1 for s in statuses if s.role == "prior_meta"),
        retrieved_primary=sum(
            1 for s in statuses if s.role == "primary" and s.retrieved
        ),
        retrieved_prior_meta=sum(
            1 for s in statuses if s.role == "prior_meta" and s.retrieved
        ),
        candidate_primary=sum(
            1 for s in statuses if s.role == "primary" and s.candidate
        ),
        candidate_prior_meta=sum(
            1 for s in statuses if s.role == "prior_meta" and s.candidate
        ),
        included_primary=sum(
            1 for s in statuses if s.role == "primary" and s.eligibility == "included"
        ),
    )


def test_repair_plan_empty_when_all_sentinels_included() -> None:
    """Every sentinel terminally included → no repair needed."""
    r = _receipt(
        SentinelStatus("10.1/a", "primary", True, True, "included"),
        SentinelStatus("10.1/b", "primary", True, True, "included"),
    )
    plan = compute_repair_plan(r, _pack({}))
    assert plan.clean
    assert plan.k_repair_needed == 0
    assert plan.entries == ()


def test_repair_plan_flags_not_retrieved_with_correct_actions() -> None:
    """A sentinel the corpus never surfaced → not_retrieved → recommends
    crossref + Europe PMC + manual upload."""
    r = _receipt(
        SentinelStatus("10.1/missing", "primary", False, False, "not_retrieved"),
    )
    plan = compute_repair_plan(r, _pack({}))
    assert not plan.clean
    assert plan.k_repair_needed == 1
    e = plan.entries[0]
    assert e.sentinel_id == "10.1/missing"
    assert e.role == "primary"
    assert e.failure_mode == "not_retrieved"
    assert "crossref-doi-lookup" in e.recommended_actions
    assert "europe-pmc-search" in e.recommended_actions
    assert "manual-upload" in e.recommended_actions


def test_repair_plan_distinguishes_failure_modes() -> None:
    """Different failure modes → different action sets."""
    r = _receipt(
        SentinelStatus("10.1/oa", "primary", True, True, "no_oa"),
        SentinelStatus("10.1/parse", "primary", True, True, "no_parse"),
        SentinelStatus("10.1/unclear", "primary", True, True, "unclear"),
    )
    plan = compute_repair_plan(r, _pack({}))
    by_mode = {e.failure_mode: e for e in plan.entries}
    assert "europe-pmc-full-text" in by_mode["no_oa"].recommended_actions
    assert "manual-pdf-override" in by_mode["no_parse"].recommended_actions
    assert "manual-judge-review" in by_mode["unclear"].recommended_actions


def test_repair_plan_skips_manually_resolved_terminal_states() -> None:
    """Sentinels manually marked resolved_excluded / resolved_unavailable
    are terminal; no repair entry should be emitted."""
    r = _receipt(
        SentinelStatus("10.1/a", "primary", True, True, "excluded",
                       manually_resolved=True),
        SentinelStatus("10.1/b", "primary", False, False, "unavailable",
                       manually_resolved=True),
    )
    plan = compute_repair_plan(r, _pack({}))
    assert plan.clean


def test_repair_plan_matches_bibliography_entry_when_doi_in_pack() -> None:
    """When the bibliography entry text contains the DOI, the repair
    entry carries the full citation so the operator can search by
    metadata too."""
    biblio = {
        "harrison-2009": "Harrison DE et al. Nature 2009. doi:10.1038/nature08221",
        "miller-2011":   "Miller RA et al. J Gerontol 2011.",
    }
    r = _receipt(
        SentinelStatus("10.1038/nature08221", "primary", False, False, "not_retrieved"),
    )
    plan = compute_repair_plan(r, _pack(biblio))
    assert plan.entries[0].bibliography_entry.startswith("Harrison DE")


def test_repair_plan_handles_prior_meta_sentinels_with_separate_actions() -> None:
    """prior_meta role passes through unchanged — the action map is keyed
    by failure mode, not role, so a missing prior-meta gets the same
    crossref/Europe-PMC/manual-upload toolkit."""
    r = _receipt(
        SentinelStatus("10.2/m", "prior_meta", False, False, "not_retrieved"),
    )
    plan = compute_repair_plan(r, _pack({}))
    e = plan.entries[0]
    assert e.role == "prior_meta"
    assert "crossref-doi-lookup" in e.recommended_actions


def test_repair_plan_as_dict_round_trips_through_json() -> None:
    """Receipt-write safety: as_dict must be JSON-serialisable."""
    import json
    r = _receipt(
        SentinelStatus("10.1/a", "primary", False, False, "not_retrieved"),
        SentinelStatus("10.2/b", "primary", True, True, "included"),
    )
    plan = compute_repair_plan(r, _pack({}))
    d = plan.as_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["clean"] is False
    assert d["k_repair_needed"] == 1


def test_repair_plan_is_universal_for_non_biomedical_topic() -> None:
    """Same plan logic over a finance-style sentinel set (FRED series
    IDs as DOI placeholders) — proves no biomedical hardcoding."""
    r = _receipt(
        SentinelStatus("fred-fedfunds-1955", "primary", False, False, "not_retrieved"),
        SentinelStatus("nber-recession-2020", "prior_meta", True, True, "no_parse"),
    )
    plan = compute_repair_plan(
        r, _pack({"x": "Fed Reserve. FEDFUNDS series, doi placeholder."}),
    )
    assert plan.k_repair_needed == 2
    modes = {e.failure_mode for e in plan.entries}
    assert modes == {"not_retrieved", "no_parse"}
