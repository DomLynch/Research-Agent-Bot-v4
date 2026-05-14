"""Sprint 52 — source-audit layer tests.

Locks the audit contract:
  - no abstract -> needs_extraction (not raise)
  - judge not configured -> needs_extraction
  - LLM runtime error -> needs_extraction (graceful)
  - Gemma returns 'dies' with quote -> verdict carried through
  - Gemma returns bad-JSON / non-verdict string -> needs_extraction
  - Per-PMID cache: siblings sharing a paper only fetch once
  - Empty fact list -> empty report, all counts 0
  - Universal: non-biomedical fixture works structurally identically
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from agent.source_audit import (
    FactVerdict,
    SourceAuditReport,
    _fact_summary,
    _parse_verdict,
    _reconcile,
    fetch_pubmed_abstract,
    run_source_audit,
    verify_fact,
)


def _v(verdict: str, judge: str = "gemma", reason: str = "r") -> FactVerdict:
    """Compact FactVerdict factory for consensus tests."""
    return FactVerdict(
        fact_id="f/x", verdict=verdict, db_value="9.0%", pmid="123",
        source_quote="q", reason=reason, judge=judge,
    )


def _settings(judge: bool = True, writer: bool = True,
              researka: bool = False) -> Any:
    """MagicMock settings. researka=False (default) leaves the DB URL
    + token empty so the corpus-search cascade short-circuits without
    making real HTTP calls during unit tests."""
    s = MagicMock()
    s.judge_configured = judge
    s.writer_configured = writer
    s.researka_database_url = "https://x" if researka else ""
    s.researka_database_token = "tok" if researka else ""
    return s


def _fact(fid: str, *, pmid: str = "12345", phrase: str = "X causes Y",
          nv: float = 9.0, pop: str = "male mice") -> dict[str, Any]:
    return {
        "fact_id": fid,
        "source_paper": {"pmid": pmid, "title": "Paper", "year": 2009},
        "canonical_phrase": phrase, "numeric_value": nv, "units": "%",
        "population": pop, "intervention": "drug",
    }


def _mock_judge_resp(content: str, model: str = "gemma-judge") -> Any:
    r = MagicMock()
    r.content = content
    r.model = model
    return r


def test_no_abstract_returns_needs_extraction() -> None:
    v = verify_fact(_fact("f/1"), abstract="", settings=_settings())
    assert v.verdict == "needs_extraction"
    assert v.reason == "abstract_unavailable"


def test_judge_not_configured_returns_needs_extraction() -> None:
    v = verify_fact(_fact("f/1"), abstract="some text",
                    settings=_settings(judge=False))
    assert v.verdict == "needs_extraction"
    assert v.reason == "gemma_not_configured"


def test_judge_runtime_error_returns_needs_extraction() -> None:
    with patch("agent.source_audit.call_judge",
               side_effect=RuntimeError("model down")):
        v = verify_fact(_fact("f/1"), abstract="some text",
                        settings=_settings())
    assert v.verdict == "needs_extraction"
    assert v.reason.startswith("gemma_call_failed:RuntimeError")


def test_mimo_judge_uses_writer_path() -> None:
    """judge='mimo' routes through call_writer_with_fallback, not call_judge."""
    with (
        patch("agent.source_audit.call_writer_with_fallback",
              return_value=_mock_judge_resp(
                  '{"verdict": "dies", "source_quote": "q", "reason": "r"}',
                  model="mimo-v2.5-pro")) as mwriter,
        patch("agent.source_audit.call_judge") as mjudge,
    ):
        v = verify_fact(_fact("f/x"), abstract="abs",
                        settings=_settings(), judge="mimo")
    assert mwriter.called and not mjudge.called
    assert v.verdict == "dies" and v.judge == "mimo"


def test_mimo_writer_not_configured_returns_needs_extraction() -> None:
    v = verify_fact(_fact("f/1"), abstract="abs",
                    settings=_settings(writer=False), judge="mimo")
    assert v.verdict == "needs_extraction"
    assert v.reason == "mimo_not_configured"


def test_invalid_judge_falls_back_to_gemma() -> None:
    with patch("agent.source_audit.call_judge",
               return_value=_mock_judge_resp(
                   '{"verdict": "survives"}')) as mjudge:
        v = verify_fact(_fact("f/1"), abstract="abs",
                        settings=_settings(), judge="claude")
    assert mjudge.called  # invalid -> coerced to gemma
    assert v.judge == "gemma"


def test_dies_verdict_carries_through() -> None:
    with patch(
        "agent.source_audit.call_judge",
        return_value=_mock_judge_resp(
            '{"verdict": "dies", '
            '"source_quote": "14% for females and 9% for males", '
            '"reason": "sex attribution flipped"}'),
    ):
        v = verify_fact(
            _fact("f/harrison_male", pop="male mice", nv=14.0),
            abstract="...rapamycin led to an increase of 14% for females "
                     "and 9% for males...", settings=_settings(),
        )
    assert v.verdict == "dies"
    assert "14% for females" in v.source_quote
    assert v.db_value == "14.0%"


def test_survives_verdict_carries_through() -> None:
    with patch(
        "agent.source_audit.call_judge",
        return_value=_mock_judge_resp(
            '{"verdict": "survives", "source_quote": "9% in males", '
            '"reason": "matches"}'),
    ):
        v = verify_fact(_fact("f/1", nv=9.0), abstract="9% in males was observed",
                        settings=_settings())
    assert v.verdict == "survives"


def test_unknown_verdict_clamps_to_needs_extraction() -> None:
    with patch(
        "agent.source_audit.call_judge",
        return_value=_mock_judge_resp(
            '{"verdict": "MAYBE", "source_quote": "", "reason": "?"}'),
    ):
        v = verify_fact(_fact("f/1"), abstract="abstract text",
                        settings=_settings())
    assert v.verdict == "needs_extraction"


def test_malformed_json_clamps_to_needs_extraction() -> None:
    with patch("agent.source_audit.call_judge",
               return_value=_mock_judge_resp("not JSON at all, just prose")):
        v = verify_fact(_fact("f/1"), abstract="abstract text",
                        settings=_settings())
    assert v.verdict == "needs_extraction"


def test_parse_strips_markdown_fence() -> None:
    assert _parse_verdict('```json\n{"verdict": "dies"}\n```') == \
        {"verdict": "dies"}
    assert _parse_verdict('not json') == {}


def test_run_caches_abstracts_per_pmid() -> None:
    """Two facts sharing one PMID -> fetch_pubmed_abstract called once."""
    facts = [
        _fact("f/male", pmid="19587680", pop="male mice", nv=9.0),
        _fact("f/female", pmid="19587680", pop="female mice", nv=14.0),
    ]
    with (
        patch("agent.source_audit.fetch_pubmed_abstract",
              return_value="abs") as mfetch,
        patch("agent.source_audit.call_judge",
              return_value=_mock_judge_resp(
                  '{"verdict": "survives", "source_quote": "x", "reason": "ok"}')),
    ):
        rpt = run_source_audit(
            topic="t", snapshot_utc="ts", facts=facts,
            settings=_settings(), client=httpx.Client(),
        )
    assert mfetch.call_count == 1  # cache hit on the second fact
    assert rpt.facts_inspected == 2
    assert rpt.survives == 2


def test_run_empty_facts_returns_zero_counts() -> None:
    rpt = run_source_audit(topic="t", snapshot_utc="ts", facts=[],
                           settings=_settings(), client=httpx.Client())
    assert rpt.facts_inspected == 0
    assert rpt.survives == 0 and rpt.dies == 0 and rpt.needs_extraction == 0


def test_run_aggregates_mixed_verdicts() -> None:
    facts = [_fact("f/a", pmid="1", nv=1.0),
             _fact("f/b", pmid="2", nv=2.0),
             _fact("f/c", pmid="3", nv=3.0)]
    responses = iter([
        _mock_judge_resp('{"verdict": "survives"}'),
        _mock_judge_resp('{"verdict": "dies"}'),
        _mock_judge_resp('{"verdict": "needs_extraction"}'),
    ])
    with (
        patch("agent.source_audit.fetch_pubmed_abstract", return_value="abs"),
        patch("agent.source_audit.call_judge",
              side_effect=lambda *_a, **_k: next(responses)),
    ):
        rpt = run_source_audit(topic="t", snapshot_utc="ts", facts=facts,
                               settings=_settings(), client=httpx.Client())
    assert (rpt.survives, rpt.dies, rpt.needs_extraction) == (1, 1, 1)


def test_fetch_returns_empty_on_http_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream blew up")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert fetch_pubmed_abstract("12345", client=c) == ""


def test_fetch_returns_empty_on_missing_pmid() -> None:
    assert fetch_pubmed_abstract("", client=httpx.Client()) == ""
    assert fetch_pubmed_abstract("   ", client=httpx.Client()) == ""


def test_fetch_returns_text_on_success() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("id") == "9999"
        return httpx.Response(200, text="abstract body here")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert fetch_pubmed_abstract("9999", client=c) == "abstract body here"


def test_fact_summary_includes_value_and_population() -> None:
    s = _fact_summary(_fact("f/x", pop="elderly humans", nv=20.0,
                            phrase="vaccine response"))
    assert "vaccine response" in s
    assert "20.0%" in s
    assert "elderly humans" in s


def test_run_with_escalate_false_skips_pmc_fetch() -> None:
    """escalate=False -> never calls get_best_source / PMC."""
    facts = [_fact("f/a", pmid="1", nv=1.0)]
    with (
        patch("agent.source_audit.fetch_pubmed_abstract",
              return_value="some abstract"),
        patch("agent.source_audit.get_best_source") as mcascade,
        patch("agent.source_audit.call_judge",
              return_value=_mock_judge_resp('{"verdict": "survives"}')),
    ):
        rpt = run_source_audit(
            topic="t", snapshot_utc="ts", facts=facts,
            settings=_settings(), client=httpx.Client(), escalate=False,
        )
    assert not mcascade.called
    assert rpt.facts_inspected == 1


def test_verdict_carries_source_tier_and_anchor_hits() -> None:
    """verdict.source_tier reflects whichever tier got the anchor."""
    from agent.source_corpus import SourcePassage
    p = SourcePassage(tier="pmc_fulltext", text="...52% in males...",
                      full_length=12345, anchor_hits=2)
    with patch("agent.source_audit.call_judge",
               return_value=_mock_judge_resp('{"verdict": "dies"}')):
        v = verify_fact(_fact("f/1", nv=52.0), abstract="ignored",
                        settings=_settings(), passage=p)
    assert v.source_tier == "pmc_fulltext"
    assert v.anchor_hits == 2


def test_reconcile_same_verdict_high_confidence() -> None:
    out = _reconcile(_v("dies", "gemma"), _v("dies", "mimo"))
    assert out.verdict == "dies"
    assert out.judge == "both"
    assert out.secondary_verdict == "dies"
    assert out.secondary_judge == "mimo"


def test_reconcile_survives_disagrees_dies_flagged() -> None:
    out = _reconcile(_v("survives", "gemma"), _v("dies", "mimo"))
    assert out.verdict == "disagreement"
    assert out.secondary_verdict == "dies"


def test_reconcile_dies_plus_needs_extraction_promotes_to_dies() -> None:
    out = _reconcile(_v("dies", "gemma"), _v("needs_extraction", "mimo"))
    assert out.verdict == "dies"  # strong: silent contradiction


def test_reconcile_survives_plus_needs_extraction_keeps_survives() -> None:
    out = _reconcile(_v("survives", "gemma"),
                     _v("needs_extraction", "mimo"))
    assert out.verdict == "survives"


def test_reconcile_both_needs_extraction() -> None:
    out = _reconcile(_v("needs_extraction"), _v("needs_extraction", "mimo"))
    assert out.verdict == "needs_extraction"


def test_run_dual_judge_aggregates_disagreement_count() -> None:
    """End-to-end: facts return mixed verdicts; report counts agreement
    + disagreement separately."""
    facts = [_fact("f/a", pmid="1", nv=1.0),
             _fact("f/b", pmid="2", nv=2.0)]
    # First fact: gemma=survives, mimo=dies -> disagreement
    # Second fact: both say dies -> dies
    judge_responses = iter([
        _mock_judge_resp('{"verdict": "survives"}'),  # gemma fact a
        _mock_judge_resp('{"verdict": "dies"}'),       # gemma fact b
    ])
    writer_responses = iter([
        _mock_judge_resp('{"verdict": "dies"}'),       # mimo fact a
        _mock_judge_resp('{"verdict": "dies"}'),       # mimo fact b
    ])
    with (
        patch("agent.source_audit.fetch_pubmed_abstract", return_value="abs"),
        patch("agent.source_audit.get_best_source", return_value=None),
        patch("agent.source_audit.call_judge",
              side_effect=lambda *_a, **_k: next(judge_responses)),
        patch("agent.source_audit.call_writer_with_fallback",
              side_effect=lambda *_a, **_k: next(writer_responses)),
    ):
        rpt = run_source_audit(
            topic="t", snapshot_utc="ts", facts=facts,
            settings=_settings(), client=httpx.Client(), judge="both",
        )
    assert rpt.facts_inspected == 2
    assert rpt.disagreement == 1
    assert rpt.dies == 1
    # Per-fact: first verdict carries both judges' opinions
    fact_a = next(v for v in rpt.verdicts if v.fact_id == "f/a")
    assert fact_a.verdict == "disagreement"
    assert fact_a.judge == "both"
    assert {fact_a.secondary_verdict, fact_a.verdict} | {"dies"}


def test_as_dict_round_trip() -> None:
    v = FactVerdict(fact_id="x/y", verdict="dies", db_value="14%",
                    source_quote="q", reason="r", pmid="123")
    rpt = SourceAuditReport(topic="t", snapshot_utc="ts",
                            facts_inspected=1, survives=0, dies=1,
                            needs_extraction=0, verdicts=(v,))
    d = rpt.as_dict()
    assert d["verdicts"][0]["fact_id"] == "x/y"
    assert d["dies"] == 1


def test_universal_non_biomedical_fixture() -> None:
    """climate-policy fact runs through identically (no PMID -> NE)."""
    fact = {
        "fact_id": "carbon_tax/sweden/2022",
        "source_paper": {"pmid": "", "title": "Sweden CO2 tax",
                         "year": 2022},
        "canonical_phrase": "carbon tax cut emissions 8% in Sweden",
        "numeric_value": 8.0, "units": "%",
        "population": "Sweden 1991-2020", "intervention": "CO2 tax",
    }
    with patch("agent.source_audit.fetch_pubmed_abstract", return_value=""):
        rpt = run_source_audit(topic="carbon_tax", snapshot_utc="ts",
                               facts=[fact], settings=_settings(),
                               client=httpx.Client())
    assert rpt.facts_inspected == 1
    assert rpt.needs_extraction == 1  # no PMID -> can't verify
    assert rpt.verdicts[0].reason == "abstract_unavailable"
