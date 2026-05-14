"""Sprint 46 — DB-backed claim feed tests.

Locks the canonical-source aggregator contract:
  - facts with same canonical_phrase → ONE claim, k_supp counts unique DOIs
  - confidence formula deterministic across CI / validator / supersession
  - publication_opportunity fires only at confidence >= 70 AND k_supp >= 2
  - HTTP / JSON / config errors return [] silently
  - Universal: non-biomedical fixture renders identically
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.researka_claims import _aggregate, fetch_topic_claims


def _fact(phrase: str, doi: str, *, ci: bool = False,
          validator: str = "", superseded: bool = False) -> dict[str, Any]:
    return {
        "canonical_phrase": phrase,
        "source_paper": {"doi": doi},
        "ci_lower": 0.1 if ci else None,
        "ci_upper": 0.5 if ci else None,
        "validator": validator,
        "superseded_by": "x" if superseded else None,
        "claim_type": "effect_size",
    }


def test_two_facts_same_phrase_collapse_to_one_claim() -> None:
    out = _aggregate([
        _fact("X causes Y", "10.1/a"),
        _fact("X causes Y", "10.1/b"),
    ])
    assert len(out) == 1
    assert out[0]["claim_text"] == "X causes Y"
    assert out[0]["supporting_study_ids"] == ["10.1/a", "10.1/b"]


def test_confidence_scales_with_signals() -> None:
    bare = _aggregate([_fact("p", "10.1/a")])
    # bare: k_dois=1, no CI, no validator, not superseded → 50 + 0 + 0 + 0 + 10 = 60
    assert bare[0]["confidence_0_100"] == 60
    rich = _aggregate([
        _fact("q", "10.1/a", ci=True, validator="alice"),
        _fact("q", "10.1/b", ci=True, validator="alice"),
    ])
    # k_dois=2 (+10), CI (+10), validator (+10), not-superseded (+10), base 50 = 90
    assert rich[0]["confidence_0_100"] == 90


def test_superseded_costs_ten_points() -> None:
    out = _aggregate([
        _fact("r", "10.1/a", superseded=True),
        _fact("r", "10.1/b", superseded=True),
    ])
    # k>=2 (+10), no CI, no validator, superseded (+0): 50 + 10 = 60
    assert out[0]["confidence_0_100"] == 60


def test_publication_opportunity_gate_requires_conf70_and_k2() -> None:
    # k=1, all signals → 50 + 0 + 10 + 10 + 10 = 80, but k=1 so pub_opp must be False
    single = _aggregate([_fact("s", "10.1/a", ci=True, validator="v")])
    assert single[0]["confidence_0_100"] == 80
    assert single[0]["publication_opportunity"] is False
    # k=2 same signals → 90, fires
    dual = _aggregate([_fact("t", "10.1/a", ci=True, validator="v"),
                       _fact("t", "10.1/b", ci=True, validator="v")])
    assert dual[0]["publication_opportunity"] is True


def test_empty_phrase_facts_dropped() -> None:
    out = _aggregate([
        {"canonical_phrase": "", "source_paper": {"doi": "10.1/a"}},
        {"source_paper": {"doi": "10.1/b"}},  # missing phrase
    ])
    assert out == []


def test_output_sorted_confidence_desc() -> None:
    out = _aggregate([
        _fact("low", "10.1/a"),                                    # 60
        _fact("high", "10.1/x", ci=True, validator="v"),
        _fact("high", "10.1/y", ci=True, validator="v"),           # 90
    ])
    assert [c["claim_text"] for c in out] == ["high", "low"]


def test_fetch_returns_empty_on_no_token() -> None:
    s = type("S", (), {"researka_database_url": "https://x",
                       "researka_database_token": "   "})()
    out = fetch_topic_claims("any", client=httpx.Client(), settings=s)
    assert out == []


def test_fetch_returns_empty_on_http_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})
    s = type("S", (), {"researka_database_url": "https://x",
                       "researka_database_token": "tok"})()
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = fetch_topic_claims("any", client=c, settings=s)
    assert out == []


def test_fetch_aggregates_live_shape() -> None:
    """Mocks the real /api/v1/topics/{topic}/facts response shape."""
    payload = [
        {"canonical_phrase": "rapamycin extends lifespan",
         "source_paper": {"doi": "10.7554/eLife.16351"},
         "ci_lower": None, "ci_upper": None,
         "validator": "researka-curator", "superseded_by": None,
         "claim_type": "effect_size"},
        {"canonical_phrase": "rapamycin extends lifespan",
         "source_paper": {"doi": "10.1038/nature19324"},
         "ci_lower": 0.05, "ci_upper": 0.40,
         "validator": "researka-curator", "superseded_by": None,
         "claim_type": "effect_size"},
    ]
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/topics/rapamycin/facts"
        assert req.headers.get("x-researka-token") == "tok"
        # 2026-05-14 audit gate: writer pipeline must request only
        # source-verified facts (drops 43%-error-rate bootstrap seeds).
        assert req.url.params.get("validated_only") == "true"
        return httpx.Response(200, json=payload)
    s = type("S", (), {"researka_database_url": "https://x",
                       "researka_database_token": "tok"})()
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = fetch_topic_claims("rapamycin", client=c, settings=s)
    assert len(out) == 1
    assert out[0]["confidence_0_100"] == 90
    assert out[0]["publication_opportunity"] is True
    assert out[0]["supporting_study_ids"] == [
        "10.1038/nature19324", "10.7554/eLife.16351"]


def test_universal_non_biomedical_topic() -> None:
    """climate-policy fixture proves no domain coupling."""
    out = _aggregate([
        _fact("carbon tax reduces emissions", "country/norway/2019"),
        _fact("carbon tax reduces emissions", "city/stockholm/2022",
              ci=True, validator="ipcc-wg3"),
    ])
    assert out[0]["claim_text"] == "carbon tax reduces emissions"
    assert len(out[0]["supporting_study_ids"]) == 2
