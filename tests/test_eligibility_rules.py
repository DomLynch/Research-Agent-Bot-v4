"""Eligibility Pass-1 rule tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.eligibility_rules import MANDATORY_KEYS, EligibilityTriage, triage
from agent.full_text_parse import ParsedFullText
from agent.screening import CandidateStudy
from agent.topic_pack import TopicPack


def _candidate(title: str = "rapamycin in mice") -> CandidateStudy:
    return CandidateStudy(
        study_id="s1", hit_key="k1", title=title, year=2020,
        venue="Nature", doi="10.1/x", pmid="123",
    )


def _parsed(text: str = "x" * 5000) -> ParsedFullText:
    return ParsedFullText(
        study_id="s1", source_url="u", source_kind="pmc-xml",
        text=text, char_count=len(text), sha256="h", fetched_at_utc="t",
    )


def _pack(
    preferred: tuple[str, ...] = ("mouse", "mice"),
    primary: tuple[str, ...] = ("rapamycin",),
    rapalog: tuple[str, ...] = ("everolimus", "rtb101"),
    endpoints: tuple[str, ...] = ("lifespan", "survival"),
    controls: tuple[str, ...] = ("control", "placebo"),
    excludes: tuple[str, ...] = ("systematic review", "meta-analysis"),
    min_chars: int = 2000,
) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=preferred, discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=primary,
        translational_only_interventions=rapalog,
        retrieval_sources=(),
        eligibility_endpoint_terms=endpoints,
        eligibility_control_terms=controls,
        eligibility_exclude_design_terms=excludes,
        eligibility_combination_terms=(),
        eligibility_min_text_chars=min_chars,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(), secondary_design_quote_markers=(),
    )


def test_all_fields_present_yields_eligible_likely() -> None:
    text = (
        "We treated mice with rapamycin and measured median lifespan. "
        "Control animals received vehicle. " + "x" * 4000
    )
    out = triage(_candidate(), _parsed(text), _pack())
    assert isinstance(out, EligibilityTriage)
    assert out.label == "eligible_likely"
    assert all(out.mandatory_fields[k] for k in MANDATORY_KEYS)


def test_excluded_design_in_title_yields_exclude_likely() -> None:
    # Sprint 7.7: exclude-design check is now TITLE-only - body mentions
    # of "systematic review" (in cited prior work) should not false-reject
    # a primary study.
    text = "Body mentions a prior systematic review of rapamycin. " + "x" * 4000
    out = triage(
        _candidate(title="A systematic review of rapamycin in mice"),
        _parsed(text), _pack(),
    )
    assert out.label == "exclude_likely"
    assert "review / non-primary design" in " ".join(out.reasons)


def test_review_in_body_does_NOT_exclude_when_title_is_primary() -> None:
    # Harrison-2009 rescue: title is a primary study, body cites reviews.
    text = (
        "Body mentions a prior systematic review and meta-analysis in cited work. "
        "We treated mice with rapamycin and measured median lifespan. "
        "Control animals received vehicle. " + "x" * 4000
    )
    out = triage(
        _candidate(title="Rapamycin extends lifespan in mice"),
        _parsed(text), _pack(),
    )
    assert out.label == "eligible_likely"


def test_rapalog_only_yields_exclude_likely() -> None:
    text = (
        "We treated mice with everolimus and measured median lifespan. "
        "Control animals received vehicle. " + "x" * 4000
    )
    out = triage(_candidate(title="everolimus in mice"), _parsed(text), _pack())
    assert out.label == "exclude_likely"
    assert out.mandatory_fields["rapalog_only_intervention"] is True


def test_missing_endpoint_yields_unclear() -> None:
    text = "We treated mice with rapamycin. Control animals received vehicle. " + "x" * 4000
    out = triage(_candidate(), _parsed(text), _pack())
    assert out.label == "unclear"
    assert out.mandatory_fields["endpoint_present"] is False
    assert any("endpoint_present" in r for r in out.reasons)


def test_short_text_yields_unclear_even_when_all_fields_match() -> None:
    text = "rapamycin mice lifespan control"  # too short
    out = triage(_candidate(), _parsed(text), _pack(min_chars=2000))
    assert out.label == "unclear"
    assert out.mandatory_fields["parsed_text_adequate"] is False


def test_title_can_supply_missing_intervention_evidence() -> None:
    # body has no intervention term; title does
    text = "Mice survived to median lifespan when given vehicle or control compound." + "x" * 4000
    out = triage(_candidate(title="Rapamycin extends life"), _parsed(text), _pack())
    assert out.mandatory_fields["intervention_match"] is True


def test_parse_error_recorded_in_reasons() -> None:
    parsed = ParsedFullText(
        study_id="s1", source_url="", source_kind="unsupported", text="",
        char_count=0, sha256="", fetched_at_utc="t",
        error="no open-access source",
    )
    out = triage(_candidate(), parsed, _pack())
    assert out.label == "unclear"
    assert any("parse error" in r for r in out.reasons)
