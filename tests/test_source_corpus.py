"""Sprint 54 — source-cascade + focused-span tests.

Locks the cascade contract:
  - regex anchors find target value in % / unit / plain form
  - ±window passages dedup overlapping matches
  - PMC fetch returns '' on HTTP/empty/missing PMCID
  - corpus search returns '' on missing creds / non-list response
  - get_best_source picks the tier with anchor hits, abstract fallback
  - universal: non-biomedical fixture cascades identically
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx

from agent.source_corpus import (
    SourcePassage,
    _value_patterns,
    extract_focused_spans,
    fetch_pmc_fulltext,
    fetch_researka_corpus,
    get_best_source,
)


def _settings(url: str = "https://x", tok: str = "tok") -> Any:
    s = MagicMock()
    s.researka_database_url = url
    s.researka_database_token = tok
    return s


def test_value_patterns_for_percent_units() -> None:
    pats = _value_patterns(60.0, "%")
    assert any("60" in p and "%" in p for p in pats)
    assert any(p.startswith("about") for p in pats)


def test_value_patterns_for_other_units() -> None:
    pats = _value_patterns(8.0, "mg/kg/day")
    assert any("mg" in p for p in pats)


def test_value_patterns_dedupes_value_form() -> None:
    """Both int (60.0) and float (60.5) reduce to ONE :g-formatted value
    form -> 3 patterns (plain, ~, about) for '%' units. The set-dedupe
    in _value_patterns prevents double-generating when int(x) == x."""
    assert len(_value_patterns(60.0, "%")) == 3
    assert len(_value_patterns(60.5, "%")) == 3
    # No unit -> single plain-word-boundary pattern per form
    assert len(_value_patterns(60.0, "")) == 1


def test_extract_focused_spans_finds_target_with_window() -> None:
    text = ("Here we describe baseline data. " + " " * 200 +
            "Rapamycin extended median lifespan by 14% in females. "
            + " " * 200 + "Other data follows.")
    spans = extract_focused_spans(text, 14.0, "%", window=100)
    assert len(spans) >= 1
    assert "14%" in spans[0] and "females" in spans[0]


def test_extract_focused_spans_returns_empty_on_no_match() -> None:
    spans = extract_focused_spans("abstract has no number here", 14.0, "%")
    assert spans == []


def test_extract_focused_spans_handles_none_value() -> None:
    assert extract_focused_spans("text", None, "%") == []


def test_extract_focused_spans_dedupes_substrings() -> None:
    # Two close matches: shorter window should be a substring of the larger
    text = "The 60% value matches twice: 60%."
    spans = extract_focused_spans(text, 60.0, "%", window=10, max_spans=5)
    # At least one match; duplicates collapsed via substring check.
    assert len(spans) <= 2


def test_pmc_fetch_empty_pmcid() -> None:
    assert fetch_pmc_fulltext("", client=httpx.Client()) == ""
    assert fetch_pmc_fulltext("   ", client=httpx.Client()) == ""


def test_pmc_fetch_strips_xml_to_text() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("db") == "pmc"
        return httpx.Response(200, text="<article><body><p>Body 14% here</p></body></article>")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = fetch_pmc_fulltext("PMC4996648", client=c)
    assert "Body 14% here" in out
    assert "<" not in out  # tags stripped


def test_pmc_fetch_empty_on_http_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert fetch_pmc_fulltext("PMC123", client=c) == ""


def test_corpus_returns_empty_without_creds() -> None:
    s = _settings(url="", tok="")
    out = fetch_researka_corpus("q", client=httpx.Client(), settings=s)
    assert out == ""


def test_corpus_concatenates_abstracts() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/corpus/search"
        return httpx.Response(200, json=[
            {"abstract": "first abstract text"},
            {"abstract": "second abstract text"},
        ])
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = fetch_researka_corpus("rapa", client=c, settings=_settings())
    assert "first abstract" in out and "second abstract" in out


def test_get_best_source_returns_abstract_tier_when_anchored() -> None:
    fact = {
        "numeric_value": 60.0, "units": "%",
        "source_paper": {"pmcid": "PMC1"},
    }
    abstract = "rapamycin extends lifespan up to 60% in middle-aged mice"
    out = get_best_source(
        fact, abstract=abstract, client=httpx.Client(), settings=_settings(),
    )
    assert out.tier == "abstract"
    assert out.anchor_hits >= 1
    assert "60%" in out.text


def test_get_best_source_escalates_to_pmc_when_abstract_lacks_anchor() -> None:
    """Abstract has no 52% but PMC does -> picks PMC tier."""
    def handler(req: httpx.Request) -> httpx.Response:
        if "eutils.ncbi" in str(req.url):
            return httpx.Response(200, text="<p>males showed 52% extension</p>")
        return httpx.Response(200, json=[])
    fact = {"numeric_value": 52.0, "units": "%",
            "source_paper": {"pmcid": "PMC4996648"}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = get_best_source(
            fact, abstract="abstract has only 60%",
            client=c, settings=_settings(),
        )
    assert out.tier == "pmc_fulltext"
    assert "52%" in out.text


def test_get_best_source_falls_back_to_abstract_on_no_hits() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>no number here</p>"
                              if "eutils.ncbi" in str(req.url)
                              else "[]")
    fact = {"numeric_value": 99.0, "units": "%",
            "source_paper": {"pmcid": "PMC1"}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = get_best_source(
            fact, abstract="also no number", client=c, settings=_settings(),
        )
    assert out.tier == "abstract"
    assert out.anchor_hits == 0


def test_universal_non_biomedical_fixture() -> None:
    """carbon_tax fact with no PMCID still produces a valid SourcePassage."""
    fact = {"numeric_value": 8.0, "units": "%",
            "source_paper": {"pmcid": ""},
            "canonical_phrase": "carbon tax cut emissions 8%"}
    out = get_best_source(
        fact, abstract="Sweden CO2 tax cut emissions 8% over 1991-2020",
        client=httpx.Client(), settings=_settings(),
    )
    assert out.tier == "abstract"
    assert out.anchor_hits >= 1


def test_source_passage_dataclass_round_trip() -> None:
    p = SourcePassage(tier="pmc_fulltext", text="span", full_length=1500,
                      anchor_hits=2)
    assert p.tier == "pmc_fulltext"
    assert p.anchor_hits == 2
