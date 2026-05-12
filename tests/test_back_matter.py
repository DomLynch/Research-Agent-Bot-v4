"""Sprint 11.1 — back-matter tests.

Cover:
  - all six sections render and join into `as_markdown()`
  - ethics + conflicts statements are pack-driven (no domain routing
    in core code): when `pack.ethics_statement` / `pack.conflicts_statement`
    are supplied they appear verbatim; otherwise the rendered prose
    falls through to the neutral previously-published-data wording
  - data/code line wires in retrieval sources and run-dir/repo refs
  - AI-use line names both writer + judge model strings
"""
from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from agent.back_matter import build_back_matter
from agent.settings import Settings
from agent.topic_pack import TopicPack


def _empty_settings() -> Settings:
    return Settings(
        mimo_api_key="", mimo_base_url="", mimo_model="mimo-test",
        mimo_timeout_sec=10.0,
        openrouter_api_key="", openrouter_base_url="",
        judge_model="judge-test",
        writer_max_retries=0,
        researka_database_url="", researka_database_token="",
        ncbi_api_key="", semantic_scholar_api_key="", core_api_key="",
        crossref_polite_email="", unpaywall_email="",
        bot_enabled=False, daily_cost_cap_usd=0.0, runs_dir="runs",
    )


def _pack(
    primary_system: str = "",
    *,
    ethics_statement: str = "",
    conflicts_statement: str = "",
) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system=primary_system,
        preferred_terms=(), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}),
        length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=(), translational_only_interventions=(),
        retrieval_sources=("pubmed", "europe-pmc"),
        eligibility_endpoint_terms=(),
        eligibility_control_terms=(),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
        references_bibliography=MappingProxyType({}),
        ethics_statement=ethics_statement,
        conflicts_statement=conflicts_statement,
    )


def test_all_six_sections_render() -> None:
    bm = build_back_matter(
        _pack("mouse"), _empty_settings(),
        run_dir_name="runs/foo", repository_url="https://example.test/repo",
    )
    md = bm.as_markdown()
    for header in (
        "## Data and Code Availability",
        "## AI-Use and Automation Disclosure",
        "## Ethics Statement",
        "## Author Contributions",
        "## Conflicts of Interest",
        "## Funding",
    ):
        assert header in md, f"missing header {header}"


def test_data_and_code_wires_run_dir_repo_and_sources() -> None:
    bm = build_back_matter(
        _pack("mouse"), _empty_settings(),
        run_dir_name="runs/rapamycin-paper-2026-05-12T15-10-22Z",
        repository_url="https://github.com/example/repo",
    )
    assert "runs/rapamycin-paper-2026-05-12T15-10-22Z" in bm.data_and_code_availability
    assert "https://github.com/example/repo" in bm.data_and_code_availability
    assert "pubmed" in bm.data_and_code_availability
    assert "europe-pmc" in bm.data_and_code_availability


def test_ai_use_names_both_models() -> None:
    settings = replace(_empty_settings(), mimo_model="mimo-v2.5-pro",
                       judge_model="google/gemma-4-31b-it")
    bm = build_back_matter(_pack("mouse"), settings)
    assert "mimo-v2.5-pro" in bm.ai_use_disclosure
    assert "google/gemma-4-31b-it" in bm.ai_use_disclosure


def test_ethics_uses_pack_supplied_statement_verbatim() -> None:
    """When the pack supplies an ethics paragraph (e.g. animal-research
    framing for a mouse-lifespan pack, human-subjects framing for a
    clinical pack), back_matter renders it verbatim — no domain
    routing in core code."""
    custom = ("This synthesis re-analyses published animal-research "
              "data. Reviewers are referred to the primary references.")
    bm = build_back_matter(
        _pack("mouse", ethics_statement=custom), _empty_settings(),
    )
    assert bm.ethics_statement == custom


def test_ethics_falls_through_to_neutral_when_pack_omits_it() -> None:
    """Packs that don't declare ethics_statement (e.g. a fresh
    climate-time-series pack) get the neutral previously-published-data
    fallback — no animal/human framing leaks from core code."""
    bm = build_back_matter(_pack("climate-time-series"), _empty_settings())
    assert "previously published data" in bm.ethics_statement
    assert "animal" not in bm.ethics_statement.lower()
    assert "human-subjects" not in bm.ethics_statement.lower()


def test_conflicts_uses_pack_supplied_statement_verbatim() -> None:
    custom = ("The operator declares no financial conflicts of "
              "interest related to mTOR-pathway pharmacology.")
    bm = build_back_matter(
        _pack("mouse", conflicts_statement=custom), _empty_settings(),
    )
    assert bm.conflicts_of_interest == custom


def test_conflicts_falls_through_to_neutral_when_pack_omits_it() -> None:
    """Packs that don't declare conflicts_statement get a domain-
    agnostic neutral paragraph — no biomedical literals leak from
    core code."""
    bm = build_back_matter(_pack("climate-time-series"), _empty_settings())
    assert "subject matter of this synthesis" in bm.conflicts_of_interest
    assert "mTOR" not in bm.conflicts_of_interest
    assert "geroprotective" not in bm.conflicts_of_interest
