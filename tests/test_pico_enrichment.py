"""Sprint 61 — PICO enrichment tests.

Locks the contract:
  - empty facts -> empty
  - writer not configured -> facts unchanged
  - facts with PICO already populated are skipped (and never overridden)
  - facts with empty pop/intv get MiMo-extracted values when grounded
  - MiMo error / malformed JSON -> facts preserved untouched
  - `_pico_inferred=True` flag marks changed facts
  - Universal non-biomedical fixture (carbon_tax) works identically
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from agent.pico_enrichment import (
    EnrichmentResult,
    _apply_enrichment,
    _needs_enrichment,
    enrich_facts_pico,
)


def _settings(writer: bool = True) -> Any:
    s = MagicMock()
    s.writer_configured = writer
    return s


def _resp(content: str, model: str = "mimo-v2.5-pro") -> Any:
    r = MagicMock()
    r.content = content
    r.model = model
    return r


def _fact(fid: str, *, population: str = "", intervention: str = "",
          phrase: str = "intervention reduced X by 50%",
          title: str = "Paper") -> dict[str, Any]:
    return {
        "fact_id": fid, "canonical_phrase": phrase,
        "population": population, "intervention": intervention,
        "source_paper": {"title": title, "doi": "10.1/a"},
        "numeric_value": 50.0, "units": "%",
    }


def test_empty_facts_returns_empty() -> None:
    out, res = enrich_facts_pico([], settings=_settings())
    assert out == []
    assert res.facts_inspected == 0


def test_writer_not_configured_returns_facts_unchanged() -> None:
    facts = [_fact("f/1"), _fact("f/2", population="mice")]
    out, res = enrich_facts_pico(facts, settings=_settings(writer=False))
    assert out == facts
    assert res.model == "skipped_writer_not_configured"


def test_facts_with_full_pico_skipped() -> None:
    """No candidates -> no MiMo call."""
    facts = [_fact("f/1", population="mice", intervention="rapamycin")]
    with patch("agent.pico_enrichment.call_writer_with_fallback") as mock:
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert not mock.called
    assert res.model == "skipped_no_candidates"
    assert out == facts


def test_mimo_fills_missing_pico() -> None:
    """Happy path: empty PICO + grounded extraction → filled."""
    facts = [_fact("f/1", phrase="rapamycin extended lifespan in mice")]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp(
                   '{"0": {"population": "C57BL/6 mice", '
                   '"intervention": "rapamycin"}}')):
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert out[0]["population"] == "C57BL/6 mice"
    assert out[0]["intervention"] == "rapamycin"
    assert out[0]["_pico_inferred"] is True
    assert res.facts_changed == 1
    assert res.facts_population_filled == 1
    assert res.facts_intervention_filled == 1


def test_existing_pico_never_overridden() -> None:
    """MiMo returns values for already-populated fields → ignored."""
    facts = [_fact("f/1", population="EXISTING", intervention="")]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp(
                   '{"0": {"population": "MIMO WROTE THIS", '
                   '"intervention": "drugX"}}')):
        out, _ = enrich_facts_pico(facts, settings=_settings())
    assert out[0]["population"] == "EXISTING"   # never overridden
    assert out[0]["intervention"] == "drugX"    # filled in (was empty)


def test_mimo_error_preserves_original_facts() -> None:
    """RuntimeError during MiMo call → facts pass through unchanged."""
    original = [_fact("f/1")]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               side_effect=RuntimeError("MiMo down")):
        out, res = enrich_facts_pico(original, settings=_settings())
    assert out[0]["population"] == ""
    assert out[0]["intervention"] == ""
    assert "_pico_inferred" not in out[0]
    assert res.facts_changed == 0


def test_malformed_json_preserves_original() -> None:
    facts = [_fact("f/1")]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp("not json at all")):
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert out[0]["population"] == ""
    assert res.facts_changed == 0


def test_mimo_empty_string_keeps_empty() -> None:
    """Conservative — MiMo returning empty string leaves field empty."""
    facts = [_fact("f/1")]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp(
                   '{"0": {"population": "", "intervention": ""}}')):
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert out[0]["population"] == ""
    assert "_pico_inferred" not in out[0]
    assert res.facts_changed == 0


def test_batching_handles_multiple_facts() -> None:
    """5 facts -> single batched call -> all enriched per index."""
    facts = [_fact(f"f/{i}") for i in range(5)]
    payload = "{" + ", ".join(
        f'"{i}": {{"population": "pop{i}", "intervention": "intv{i}"}}'
        for i in range(5)
    ) + "}"
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp(payload)) as mock:
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert mock.call_count == 1
    for i in range(5):
        assert out[i]["population"] == f"pop{i}"
        assert out[i]["intervention"] == f"intv{i}"
    assert res.facts_changed == 5


def test_needs_enrichment_predicate() -> None:
    assert _needs_enrichment(_fact("f/1"))  # both empty
    assert _needs_enrichment(_fact("f/1", population="x"))  # intv empty
    assert _needs_enrichment(_fact("f/1", intervention="x"))  # pop empty
    assert not _needs_enrichment(
        _fact("f/1", population="x", intervention="y"))
    assert not _needs_enrichment(_fact("f/1", phrase=""))  # no source text


def test_apply_enrichment_marks_inferred_flag_only_when_changed() -> None:
    f = _fact("f/1")
    unchanged, pf, intvf = _apply_enrichment(f, {})
    assert "_pico_inferred" not in unchanged
    assert pf is False and intvf is False
    changed, _, _ = _apply_enrichment(f, {"population": "X"})
    assert changed.get("_pico_inferred") is True


def test_non_dict_facts_silently_skipped() -> None:
    """List with non-dict entries -> graceful."""
    facts: list[Any] = [_fact("f/1"), "not-a-dict", _fact("f/2")]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp(
                   '{"0": {"population": "p0", "intervention": "i0"}, '
                   '"2": {"population": "p2", "intervention": "i2"}}')):
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert isinstance(out[0], dict) and out[0]["population"] == "p0"
    assert isinstance(out[1], str) and out[1] == "not-a-dict"
    assert isinstance(out[2], dict) and out[2]["population"] == "p2"
    assert res.facts_changed == 2


def test_universal_non_biomedical_carbon_tax() -> None:
    """Climate-policy fixture: empty population/intervention filled from
    phrase + title, identical to biomedical case."""
    facts = [{
        "fact_id": "ct/swe",
        "canonical_phrase": "carbon_tax cut emissions 8% in Sweden",
        "population": "", "intervention": "",
        "source_paper": {"title": "Sweden 1991-2020 carbon tax review"},
        "numeric_value": 8.0, "units": "%",
    }]
    with patch("agent.pico_enrichment.call_writer_with_fallback",
               return_value=_resp(
                   '{"0": {"population": "Sweden 1991-2020", '
                   '"intervention": "carbon tax"}}')):
        out, res = enrich_facts_pico(facts, settings=_settings())
    assert out[0]["population"] == "Sweden 1991-2020"
    assert out[0]["intervention"] == "carbon tax"
    assert res.facts_changed == 1


def test_as_dict_round_trip() -> None:
    r = EnrichmentResult(facts_inspected=5, facts_changed=3,
                          facts_population_filled=2,
                          facts_intervention_filled=3, model="m")
    d = r.as_dict()
    assert d["facts_inspected"] == 5
    assert d["model"] == "m"
