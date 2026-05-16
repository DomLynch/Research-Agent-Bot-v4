"""Sprint 49 — frontier-model review tests.

Locks the lens-generation contract:
  - empty facts -> empty review with model='error:no_facts'
  - LLM runtime error -> empty review, model='error:llm_call_failed:*'
  - opportunity_score = strength * novelty / max(risk, 10), capped 100
  - tolerant JSON parser strips code fences, returns {} on bad JSON
  - schema-violating thesis (no title) dropped silently
  - universal: non-biomedical fixture renders structurally identically
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from agent.frontier_review import (
    FrontierReview,
    PaperThesis,
    _build_messages,
    _parse,
    _parse_thesis,
    _try_repair_json,
    run_frontier_review,
)


def _fact(phrase: str, year: int = 2020, value: float = 50.0) -> dict[str, Any]:
    return {
        "canonical_phrase": phrase,
        "source_paper": {"year": year, "journal": "JX", "doi": "10.1/a"},
        "numeric_value": value, "units": "%",
        "population": "pop", "intervention": "drug",
        "validator": "v", "superseded_by": None,
    }


def _settings(writer_configured: bool = True) -> Any:
    s = MagicMock()
    s.writer_configured = writer_configured
    return s


def test_no_facts_returns_empty_review() -> None:
    r = run_frontier_review(topic="t", snapshot_utc="ts", evidence_facts=[],
                            papers=None, settings=_settings())
    assert r.model == "error:no_facts"
    assert r.lens == "" and r.theses == ()


def test_writer_not_configured_returns_empty_review() -> None:
    r = run_frontier_review(topic="t", snapshot_utc="ts",
                            evidence_facts=[_fact("x")], papers=None,
                            settings=_settings(writer_configured=False))
    assert r.model == "error:writer_not_configured"


def test_llm_runtime_error_returns_empty_review() -> None:
    with patch("agent.frontier_review.call_writer_with_fallback") as mock:
        mock.side_effect = RuntimeError("MiMo runaway: max attempts")
        r = run_frontier_review(topic="t", snapshot_utc="ts",
                                evidence_facts=[_fact("x")], papers=None,
                                settings=_settings())
    assert r.model.startswith("error:llm_call_failed:RuntimeError")


def test_thesis_opportunity_score_caps_at_100() -> None:
    # 60 * 80 / 20 = 240, must cap to 100
    t = PaperThesis(title="x", paper_type="y", novelty=80,
                    evidence_strength=60, reviewer_risk=20, rationale="z")
    assert t.opportunity_score == 100


def test_thesis_opportunity_score_uncapped_math() -> None:
    # 40 * 50 / 40 = 50 (below the 100 cap, verifies the formula)
    t = PaperThesis(title="x", paper_type="y", novelty=50,
                    evidence_strength=40, reviewer_risk=40, rationale="z")
    assert t.opportunity_score == 50


def test_thesis_opportunity_score_floors_risk_to_ten() -> None:
    # reviewer_risk=0 floors to 10; 50*50/10 = 250, capped to 100
    t = PaperThesis(title="x", paper_type="y", novelty=50,
                    evidence_strength=50, reviewer_risk=0, rationale="z")
    assert t.opportunity_score == 100
    # below-cap version proving the floor is applied (not divided by 0)
    t2 = PaperThesis(title="x", paper_type="y", novelty=10,
                     evidence_strength=10, reviewer_risk=0, rationale="z")
    assert t2.opportunity_score == 10  # 10 * 10 / 10 == 10


def test_parse_handles_bare_json() -> None:
    d = _parse('{"lens": "ok", "theses": []}')
    assert d == {"lens": "ok", "theses": []}


def test_parse_strips_markdown_fence() -> None:
    d = _parse('```json\n{"lens": "x"}\n```')
    assert d == {"lens": "x"}


def test_parse_returns_empty_on_unrecoverable_json() -> None:
    assert _parse("not json at all") == {}
    assert _parse("") == {}


def test_repair_closes_truncated_object() -> None:
    # MiMo cut off mid-array of strings inside an object value
    truncated = '{"lens": "x", "tensions": ["a", "b", "c'
    fixed = _try_repair_json(truncated)
    assert json.loads(fixed) == {"lens": "x", "tensions": ["a", "b"]}


def test_repair_closes_truncated_nested() -> None:
    truncated = ('{"theses": [{"title": "T1", "novelty": 70}, '
                 '{"title": "T2", "novelty": 80, "rationale": "trun')
    fixed = _try_repair_json(truncated)
    loaded = json.loads(fixed)
    assert loaded["theses"][0]["title"] == "T1"
    assert len(loaded["theses"]) >= 1


def test_repair_handles_dangling_comma() -> None:
    fixed = _try_repair_json('{"a": 1, "b": 2,')
    assert json.loads(fixed) == {"a": 1, "b": 2}


def test_repair_leaves_valid_unchanged() -> None:
    valid = '{"a": 1, "b": [1, 2, 3]}'
    assert _try_repair_json(valid) == valid


def test_parse_recovers_truncated_response() -> None:
    """Real-world: MiMo runs out of tokens mid-stream in a 4k cap."""
    truncated = ('{"lens": "important framing here", '
                 '"known_to_ignore": ["fact 1", "fact 2"], '
                 '"tensions": ["t1", "t2"], "gaps": ["g1"], '
                 '"theses": [{"title": "Paper A", "rationale": "incomplete')
    d = _parse(truncated)
    assert d.get("lens") == "important framing here"
    assert d.get("known_to_ignore") == ["fact 1", "fact 2"]
    assert d.get("tensions") == ["t1", "t2"]


def test_parse_thesis_drops_titleless_entries() -> None:
    assert _parse_thesis({"title": "  "}) is None
    assert _parse_thesis({"novelty": 50}) is None
    t = _parse_thesis({"title": "real", "novelty": 60,
                       "evidence_strength": 70, "reviewer_risk": 20})
    assert t is not None
    assert t.title == "real"


def test_build_messages_includes_topic_and_facts() -> None:
    msgs = _build_messages(
        "rapamycin",
        [_fact("rapamycin extends lifespan", 2016, 60.0)],
        [], None,
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "research strategist" in msgs[0]["content"].lower()
    assert "rapamycin" in msgs[1]["content"]
    assert "extends lifespan" in msgs[1]["content"]
    assert "2016" in msgs[1]["content"]


def test_build_messages_includes_paper_metadata_when_provided() -> None:
    papers = [{"journal_name": "eLife", "publication_year": 2016,
               "cited_by_count": 500, "fwci": 4.2, "quality_score": 88,
               "doi": "10.1"}]
    msgs = _build_messages("rapamycin", [_fact("x")], [], papers)
    user = msgs[1]["content"]
    assert "PAPER METADATA" in user
    assert "eLife" in user
    assert "cited=500" in user


def test_build_messages_evidence_vs_hints_boundary() -> None:
    """Sprint 75 — EVIDENCE FACTS get fact_id tags (citable); ALPHA
    HINTS get no fact_id (inspiration only). Prompt must instruct the
    model not to cite hints."""
    msgs = _build_messages(
        "carbon_tax",
        [{"fact_id": "ev_1", "canonical_phrase": "tax cut emissions 8%",
          "numeric_value": 8, "units": "%",
          "source_paper": {"year": 2020}}],
        [{"fact_id": "hint_1",
          "canonical_phrase": "noise-prone hint phrase",
          "source_paper": {"doi": "10.x/hint"}}],
        None,
    )
    user = msgs[1]["content"]
    sys = msgs[0]["content"]
    assert "EVIDENCE FACTS" in user
    assert "ALPHA HINTS" in user
    assert "ev_1" in user
    assert "hint_1" not in user
    assert "INSPIRATION ONLY" in user
    assert "cited_fact_ids must reference only ids from EVIDENCE" in sys


def test_universal_non_biomedical_fixture() -> None:
    msgs = _build_messages(
        "carbon_tax",
        [{
            "canonical_phrase": "carbon tax reduces emissions 8% in Sweden",
            "source_paper": {"year": 2020, "journal": "Nature Climate"},
            "numeric_value": 8, "units": "%",
            "population": "Sweden 1991-2020", "intervention": "CO2 tax",
            "validator": "ipcc-wg3", "superseded_by": None,
        }],
        [], None,
    )
    assert "carbon_tax" in msgs[1]["content"]
    assert "Sweden" in msgs[1]["content"]


def test_full_flow_with_mocked_llm() -> None:
    mock_resp = MagicMock()
    mock_resp.content = (
        '{"lens": "the lens", '
        '"known_to_ignore": ["obvious"], '
        '"tensions": ["t1", "t2"], "gaps": ["g1"], '
        '"theses": [{"title": "Paper A", "paper_type": "scoping-review", '
        '"novelty": 70, "evidence_strength": 60, "reviewer_risk": 30, '
        '"rationale": "good"}], '
        '"reviewer_objections": ["o1"], "next_extractions": ["e1"]}'
    )
    mock_resp.model = "mimo-v2.5-pro"
    with patch("agent.frontier_review.call_writer_with_fallback",
               return_value=mock_resp):
        r = run_frontier_review(topic="t", snapshot_utc="ts",
                                evidence_facts=[_fact("x")], papers=None,
                                settings=_settings())
    assert isinstance(r, FrontierReview)
    assert r.model == "mimo-v2.5-pro"
    assert r.lens == "the lens"
    assert r.known_to_ignore == ("obvious",)
    assert r.tensions == ("t1", "t2")
    assert len(r.theses) == 1
    assert r.theses[0].title == "Paper A"
    # 60 * 70 / 30 = 140, capped to 100
    assert r.theses[0].opportunity_score == 100


def test_as_dict_round_trip() -> None:
    review = FrontierReview(
        topic="t", snapshot_utc="ts", model="m", lens="L",
        known_to_ignore=("ko",), tensions=("tn",), gaps=("g",),
        theses=(PaperThesis(title="T", paper_type="x", novelty=50,
                            evidence_strength=50, reviewer_risk=50,
                            rationale="r"),),
        reviewer_objections=("o",), next_extractions=("e",),
        raw_response="",
    )
    d = review.as_dict()
    assert d["lens"] == "L"
    assert d["theses"][0]["opportunity_score"] == 50
