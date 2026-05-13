"""Sprint 28 — dual-pass routes Pass-B through Gemma (call_judge).

Locks two contracts:
  1. Pass-B is invoked via agent.llm_client.call_judge (Gemma 4 31B),
     NOT call_writer (MiMo). The dual-agent layer is therefore
     cross-family.
  2. On agreement, the reviewer tag carries the Pass-B model id —
     `mimo-dual-pass-agreed:<gemma_model>` — so Sprint 27's
     dual_agent_audit attributes extractor_b correctly.

Universal: no biomedical literals; mocked LLM responses use generic
JSON. The dual-pass orchestrator lives in scripts/extract_effects.py
(outside the agent/ import path); we load it via importlib like
other script tests.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest


def _load_extract_module() -> Any:
    path = Path(__file__).resolve().parent.parent / "scripts" / "extract_effects.py"
    spec = importlib.util.spec_from_file_location("extract_effects", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_EX = _load_extract_module()


def _primary_receipt() -> Any:
    """Pass-A (MiMo) receipt with all pool-critical fields set."""
    from agent.effect_extraction import ExtractionReceipt
    return ExtractionReceipt(
        study_id="s01", status="extracted", metric="lifespan_days",
        treated_value=1100.0, control_value=1000.0,
        treated_n=50, control_n=50,
        hazard_ratio=None, hazard_ratio_ci_low=None, hazard_ratio_ci_high=None,
        percent_change=10.0,
        moderators=MappingProxyType({}),
        evidence_quotes=("treated lived 1100 days vs 1000 days",),
        failure_reason="",
        reviewer="mimo:mimo-v2.5-pro", text_hash="hash", timestamp_utc="2026-05-13T00:00:00Z",
    )


def _pack_stub() -> Any:
    """Minimal pack just for the strict-verify prompt builder."""
    from agent.topic_pack import TopicPack
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=(), discouraged_terms=(),
        endpoint="lifespan", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=("test",), translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=("lifespan_days",),
        eligibility_control_terms=("vehicle",),
        eligibility_exclude_design_terms=(),
        eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=(), sentinel_prior_meta=(),
        non_mouse_species_terms=(),
        secondary_design_quote_markers=(),
        references_bibliography=MappingProxyType({}),
    )


def _settings_stub() -> Any:
    """Settings sufficient to satisfy call_judge guard rails."""
    return SimpleNamespace(
        mimo_api_key="k", mimo_base_url="http://mimo", mimo_model="m",
        mimo_timeout_sec=5.0,
        openrouter_api_key="ork", openrouter_base_url="http://or",
        judge_model="google/gemma-4-31b-it",
        writer_max_retries=0, writer_configured=True,
    )


def _agreeing_b_resp(model_id: str = "google/gemma-4-31b-it") -> Any:
    """Mock LLMResponse from Gemma — fields agree with Pass-A primary."""
    from agent.llm_client import LLMResponse
    payload = {
        "status": "extracted", "metric": "lifespan_days",
        "treated_value": 1100.0, "control_value": 1000.0,
        "treated_n": 50, "control_n": 50,
        "hazard_ratio": None, "hazard_ratio_ci_low": None,
        "hazard_ratio_ci_high": None, "percent_change": 10.0,
        "moderators": {},
        "evidence_quotes": ["treated lived 1100 days vs 1000 days"],
        "failure_reason": "",
    }
    return LLMResponse(
        content=json.dumps(payload), model=model_id,
        prompt_tokens=100, completion_tokens=80,
    )


def test_dual_pass_routes_pass_b_through_call_judge_not_call_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass-B must invoke call_judge (Gemma). call_writer must NOT be
    invoked during the Pass-B phase (it's used for adjudication only)."""
    judge_calls: list[int] = []
    writer_calls: list[int] = []

    def fake_judge(_s: Any, _msg: Any, *, temperature: float = 0.0) -> Any:
        judge_calls.append(1)
        return _agreeing_b_resp()

    def fake_writer(_s: Any, _msg: Any, **_kw: Any) -> Any:
        writer_calls.append(1)
        return _agreeing_b_resp()  # never reached in the agreed path

    monkeypatch.setattr(_EX, "call_judge", fake_judge)
    monkeypatch.setattr(_EX, "call_writer", fake_writer)

    result = _EX._run_dual_pass(
        primary=_primary_receipt(), pack=_pack_stub(),
        study_id="s01", title="Test study", parsed_text="excerpt",
        settings=_settings_stub(), text_hash="hash", temperature=0.3,
    )
    assert len(judge_calls) == 1, "Pass-B must route through call_judge (Gemma)"
    assert len(writer_calls) == 0, "Pass-B must NOT route through call_writer (MiMo)"
    # Agreed path → reviewer carries Pass-B model id.
    assert result.reviewer.startswith("mimo-dual-pass-agreed:")
    assert "gemma" in result.reviewer.lower()


def test_dual_pass_agreed_tag_includes_full_pass_b_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full Gemma model id (e.g. `google/gemma-4-31b-it`) must
    survive into the reviewer tag so the audit layer can attribute
    extractor_b precisely."""
    monkeypatch.setattr(
        _EX, "call_judge",
        lambda *_a, **_kw: _agreeing_b_resp("google/gemma-4-31b-it"),
    )
    result = _EX._run_dual_pass(
        primary=_primary_receipt(), pack=_pack_stub(),
        study_id="s01", title="Test", parsed_text="x",
        settings=_settings_stub(), text_hash="h", temperature=0.3,
    )
    assert result.reviewer == "mimo-dual-pass-agreed:google/gemma-4-31b-it"


def test_dual_pass_agreed_reviewer_is_parseable_by_sprint27_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new reviewer tag must round-trip through the Sprint 27
    audit parser: agent_agreed status + extractor_b populated."""
    from agent.dual_agent_audit import _parse_reviewer
    monkeypatch.setattr(
        _EX, "call_judge",
        lambda *_a, **_kw: _agreeing_b_resp("google/gemma-4-31b-it"),
    )
    result = _EX._run_dual_pass(
        primary=_primary_receipt(), pack=_pack_stub(),
        study_id="s01", title="T", parsed_text="x",
        settings=_settings_stub(), text_hash="h", temperature=0.3,
    )
    status, ext_a, ext_b, disagreed = _parse_reviewer(result.reviewer)
    assert status == "agent_agreed"
    assert ext_a == "mimo"
    assert ext_b == "google/gemma-4-31b-it"
    assert disagreed == ()


def test_dual_pass_falls_back_when_judge_endpoint_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemma endpoint throwing (network / config / parse failure) must
    NOT sink the extraction — the primary MiMo receipt survives with
    a pass-b-failed reviewer tag."""
    def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("openrouter unreachable")

    monkeypatch.setattr(_EX, "call_judge", boom)
    result = _EX._run_dual_pass(
        primary=_primary_receipt(), pack=_pack_stub(),
        study_id="s01", title="T", parsed_text="x",
        settings=_settings_stub(), text_hash="h", temperature=0.3,
    )
    assert result.reviewer == "mimo-dual-pass-pass-b-failed"
    # Primary receipt's numerics survive untouched.
    assert result.treated_value == 1100.0


def test_dual_pass_adjudicator_runs_when_passes_disagree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Pass-A and Pass-B differ on a pool-critical field, the
    adjudicator (call_writer / MiMo) is invoked exactly once."""
    from agent.llm_client import LLMResponse

    judge_calls: list[int] = []
    writer_calls: list[int] = []

    # Pass-B (Gemma) returns a DIFFERENT treated_value than Pass-A.
    def disagreeing_judge(*_a: Any, **_kw: Any) -> Any:
        judge_calls.append(1)
        return LLMResponse(
            content=json.dumps({
                "status": "extracted", "metric": "lifespan_days",
                "treated_value": 1200.0,   # ← differs from primary's 1100.0
                "control_value": 1000.0,
                "treated_n": 50, "control_n": 50,
                "hazard_ratio": None, "hazard_ratio_ci_low": None,
                "hazard_ratio_ci_high": None, "percent_change": 20.0,
                "moderators": {}, "evidence_quotes": ["alt quote"],
                "failure_reason": "",
            }),
            model="google/gemma-4-31b-it", prompt_tokens=100, completion_tokens=80,
        )

    # Adjudicator (MiMo) picks Pass-A's value.
    def adjudicating_writer(*_a: Any, **_kw: Any) -> Any:
        writer_calls.append(1)
        return LLMResponse(
            content=json.dumps({
                "status": "extracted", "metric": "lifespan_days",
                "treated_value": 1100.0, "control_value": 1000.0,
                "treated_n": 50, "control_n": 50,
                "hazard_ratio": None, "hazard_ratio_ci_low": None,
                "hazard_ratio_ci_high": None, "percent_change": 10.0,
                "moderators": {}, "evidence_quotes": ["adj quote"],
                "failure_reason": "",
            }),
            model="mimo-v2.5-pro", prompt_tokens=100, completion_tokens=80,
        )

    monkeypatch.setattr(_EX, "call_judge", disagreeing_judge)
    monkeypatch.setattr(_EX, "call_writer", adjudicating_writer)

    result = _EX._run_dual_pass(
        primary=_primary_receipt(), pack=_pack_stub(),
        study_id="s01", title="T", parsed_text="x",
        settings=_settings_stub(), text_hash="h", temperature=0.3,
    )
    assert len(judge_calls) == 1   # Pass-B
    assert len(writer_calls) == 1  # adjudicator
    assert result.reviewer.startswith("mimo-dual-pass-adjudicated:")
    assert "disagreements=" in result.reviewer
