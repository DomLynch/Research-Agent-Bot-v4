"""Eligibility Pass-2 LLM-judge tests (LLM call mocked)."""
from __future__ import annotations

from types import MappingProxyType, SimpleNamespace
from typing import Any

from agent.eligibility_judge import (
    EligibilityProposal,
    _normalise,
    _parse_json,
    _strip_fence,
    curated_proposal,
    judge_eligibility,
    judge_eligibility_with_variance,
)
from agent.eligibility_rules import EligibilityTriage
from agent.full_text_parse import ParsedFullText
from agent.llm_client import LLMResponse
from agent.screening import CandidateStudy
from agent.topic_pack import TopicPack


def _candidate() -> CandidateStudy:
    return CandidateStudy(
        study_id="s1", hit_key="k1", title="rapamycin in mice", year=2020,
        venue="Nature", doi="10.1/x", pmid="123",
    )


def _parsed(text: str = "a body discussing rapamycin and mice lifespan extension." * 100) -> ParsedFullText:
    return ParsedFullText(
        study_id="s1", source_url="u", source_kind="pmc-xml",
        text=text, char_count=len(text), sha256="h", fetched_at_utc="t",
    )


def _triage() -> EligibilityTriage:
    return EligibilityTriage(
        study_id="s1", label="eligible_likely",
        mandatory_fields=MappingProxyType({
            "species_match": True, "intervention_match": True,
            "endpoint_present": True, "control_present": True,
            "primary_research_design": True, "rapalog_only_intervention": False,
            "parsed_text_adequate": True,
        }),
        reasons=("ok",),
    )


def _pack() -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=("mouse",), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("rapamycin",),
        translational_only_interventions=("everolimus",), retrieval_sources=(),
        eligibility_endpoint_terms=("lifespan",),
        eligibility_control_terms=("control",),
        eligibility_exclude_design_terms=("review",),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=2000,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(), secondary_design_quote_markers=(),
    )


def _settings() -> Any:
    return SimpleNamespace(
        judge_model="google/gemma-4-31b-it",
        openrouter_api_key="x", openrouter_base_url="x", mimo_timeout_sec=60.0,
        judge_configured=True,
    )


def test_strip_fence_removes_code_blocks() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert _strip_fence(raw) == '{"a": 1}'


def test_parse_json_returns_none_on_garbage() -> None:
    assert _parse_json("not json at all") is None
    assert _parse_json('"a string"') is None  # not a dict
    assert _parse_json('{"x": 1}') == {"x": 1}


def test_parse_json_finds_object_after_paragraph() -> None:
    # The reasoning-first variant emits prose, then JSON. Parser must find
    # the first balanced {...} object, not fail on the prefix prose.
    raw = (
        "This paper is a primary mouse rapamycin lifespan study with a clean "
        "control arm and extractable median lifespan endpoints.\n\n"
        '{"decision": "include", "confidence": 0.9, "reasons": ["clear"], '
        '"evidence_quotes": ["q"], "eligibility_fields": {"species_match": true}}'
    )
    obj = _parse_json(raw)
    assert obj is not None
    assert obj["decision"] == "include"
    assert obj["confidence"] == 0.9


def test_normalise_clamps_confidence_and_filters_types() -> None:
    obj = {
        "decision": "include", "confidence": 1.5,
        "reasons": ["good"], "evidence_quotes": ["q", 42],
        "eligibility_fields": {"species_match": "truthy"},
    }
    decision, conf, reasons, quotes, fields = _normalise(obj)
    assert decision == "include"
    assert conf == 1.0
    assert reasons == ("good",)
    assert quotes == ("q",)
    assert fields == {"species_match": True}


def test_normalise_unknown_decision_falls_back_to_unclear() -> None:
    decision, _, _, _, _ = _normalise({"decision": "maybe"})
    assert decision == "unclear"


def test_judge_returns_unclear_when_text_empty() -> None:
    parsed = ParsedFullText(
        study_id="s1", source_url="", source_kind="pmc-xml", text="",
        char_count=0, sha256="", fetched_at_utc="t",
    )
    out = judge_eligibility(
        _candidate(), parsed, _triage(), _pack(), _settings(),
    )
    assert out.decision == "unclear"
    assert "empty" in out.parse_error


def test_judge_uses_only_documented_gemma_model(monkeypatch: Any) -> None:
    """Lock the 2-model stack: eligibility judge MUST go through call_judge
    without any per-call model override. Adding an override path requires
    explicit prior approval (AGENTS.md non-negotiable)."""
    captured: dict[str, Any] = {}

    def fake_call(settings: Any, messages: list[dict[str, str]], **kw: Any) -> LLMResponse:
        captured["kwargs"] = kw
        return LLMResponse(
            content='{"decision":"include","confidence":0.9,'
                    '"reasons":["ok"],"evidence_quotes":["q"],'
                    '"eligibility_fields":{"species_match":true}}',
            model=settings.judge_model,
            prompt_tokens=10, completion_tokens=10,
        )

    monkeypatch.setattr("agent.eligibility_judge.call_judge", fake_call)
    out = judge_eligibility(_candidate(), _parsed(), _triage(), _pack(), _settings())
    assert "model_override" not in captured["kwargs"]
    assert out.model == "google/gemma-4-31b-it"
    assert out.decision == "include"


def test_judge_fail_soft_on_http_error(monkeypatch: Any) -> None:
    def bad_call(*_: Any, **__: Any) -> LLMResponse:
        raise RuntimeError("boom")

    monkeypatch.setattr("agent.eligibility_judge.call_judge", bad_call)
    out = judge_eligibility(_candidate(), _parsed(), _triage(), _pack(), _settings())
    assert isinstance(out, EligibilityProposal)
    assert out.decision == "unclear"
    assert "llm call failed" in out.parse_error


def test_judge_fail_soft_on_bad_json(monkeypatch: Any) -> None:
    def call(*_: Any, **__: Any) -> LLMResponse:
        return LLMResponse(
            content="not json", model="m", prompt_tokens=1, completion_tokens=1,
        )

    monkeypatch.setattr("agent.eligibility_judge.call_judge", call)
    out = judge_eligibility(_candidate(), _parsed(), _triage(), _pack(), _settings())
    assert out.decision == "unclear"
    assert "json parse failed" in out.parse_error


def _llm_response(decision: str, conf: float, content_suffix: str = "") -> LLMResponse:
    body = (
        '{"decision":"' + decision + '","confidence":' + str(conf) +
        ',"reasons":["r"],"evidence_quotes":["q"],'
        '"eligibility_fields":{"species_match":true}}'
    )
    return LLMResponse(
        content=body + content_suffix, model="google/gemma-4-31b-it",
        prompt_tokens=10, completion_tokens=10,
    )


def test_variance_check_consensus_returns_higher_confidence(monkeypatch: Any) -> None:
    calls = [_llm_response("include", 0.80), _llm_response("include", 0.90, " ")]
    monkeypatch.setattr(
        "agent.eligibility_judge.call_judge",
        lambda *_, **__: calls.pop(0),
    )
    out = judge_eligibility_with_variance(
        _candidate(), _parsed(), _triage(), _pack(), _settings(),
    )
    assert out.decision == "include"
    assert out.confidence == 0.90


def test_variance_check_disagreement_downgrades_to_unclear(monkeypatch: Any) -> None:
    calls = [_llm_response("include", 0.85), _llm_response("exclude", 0.80)]
    monkeypatch.setattr(
        "agent.eligibility_judge.call_judge",
        lambda *_, **__: calls.pop(0),
    )
    out = judge_eligibility_with_variance(
        _candidate(), _parsed(), _triage(), _pack(), _settings(),
    )
    assert out.decision == "unclear"
    assert out.confidence == 0.0
    assert "variance check" in out.reasons[0]
    assert out.parse_error == "variance disagreement"


def _researka_candidate(lane: str = "established") -> CandidateStudy:
    return CandidateStudy(
        study_id="s1", hit_key="k1", title="rapamycin in mice", year=2020,
        venue="Nature", doi="10.1/x", pmid="123",
        source=f"researka:{lane}",
    )


def test_curated_proposal_short_circuits_llm_for_researka_hits() -> None:
    """Sprint 12.9: a Researka-source candidate whose Pass-1 triage passes
    all mandatory fields must produce an include proposal directly from
    the rule triage + parsed-text scan, with no LLM call. The model
    string records the curated-source provenance so the receipt is
    auditable."""
    out = curated_proposal(_researka_candidate(), _parsed(), _triage(), _pack())
    assert out.decision == "include"
    assert out.confidence > 0.0 and out.confidence < 0.95
    assert out.model.startswith("curated:researka:")
    assert out.parse_error == ""
    # Evidence quotes were scraped from the parsed body, not invented.
    assert all(q in _parsed().text for q in out.evidence_quotes)


def test_curated_proposal_returns_unclear_when_triage_misses_a_field() -> None:
    """Curation trust never overrides the deterministic rule triage. If
    Pass-1 says a mandatory field is missing, the proposal is 'unclear'
    so the downstream merge + universal evidence contract can demote it."""
    missing_field = EligibilityTriage(
        study_id="s1", label="unclear",
        mandatory_fields=MappingProxyType({
            "species_match": True, "intervention_match": True,
            "endpoint_present": False,  # missing
            "control_present": True, "primary_research_design": True,
            "rapalog_only_intervention": False, "parsed_text_adequate": True,
        }),
        reasons=("endpoint missing",),
    )
    out = curated_proposal(_researka_candidate(), _parsed(), missing_field, _pack())
    assert out.decision == "unclear"
    assert out.confidence < 0.6


def test_curated_proposal_is_universal_no_biomedical_literals_required() -> None:
    """The curated-proposal helper reads ONLY pack.primary_interventions +
    pack.eligibility_endpoint_terms when scanning the parsed text. A
    pack with arbitrary non-biomedical vocabulary (e.g. a climate or
    economics pack) gets the same short-circuit behavior with no code
    changes."""
    climate_pack = TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=(), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("policy_X",),
        translational_only_interventions=(), retrieval_sources=(),
        eligibility_endpoint_terms=("emissions_reduction",),
        eligibility_control_terms=("baseline",),
        eligibility_exclude_design_terms=(), eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(), secondary_design_quote_markers=(),
    )
    climate_text = (
        "Adoption of policy_X across cities led to measurable "
        "emissions_reduction over a five-year window relative to the "
        "matched baseline cohort." * 100
    )
    parsed = ParsedFullText(
        study_id="s1", source_url="u", source_kind="html",
        text=climate_text, char_count=len(climate_text),
        sha256="h", fetched_at_utc="t",
    )
    out = curated_proposal(_researka_candidate(), parsed, _triage(), climate_pack)
    assert out.decision == "include"
    # Quotes were pulled from the climate body, not biomedical literals.
    assert any("policy_X" in q or "emissions_reduction" in q for q in out.evidence_quotes)
