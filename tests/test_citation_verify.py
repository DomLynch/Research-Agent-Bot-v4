"""Tests for agent.citation_verify — fully mocked, never hits live APIs.

Locks the safety contract: graceful degrade to SKIPPED on any failure,
conservative HALLUCINATED only on a positive not-found, and correct
VERIFIED/SUSPICIOUS classification by title similarity.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.citation_verify import (
    CiteStatus,
    verify_source,
    verify_sources,
)


class _Resp:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class _Client:
    """Routes by URL substring -> _Resp, or raises to simulate a transport error."""

    def __init__(self, routes: dict[str, _Resp | Exception]) -> None:
        self._routes = routes
        self.closed = False

    def get(self, url: str, **_: Any) -> _Resp:
        for needle, resp in self._routes.items():
            if needle in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise httpx.ConnectError("no route")

    def close(self) -> None:
        self.closed = True


_CROSSREF_OK = _Resp(200, {"message": {"title": ["Creatine supplementation and muscle strength"]}})


def test_doi_match_is_verified() -> None:
    client = _Client({"crossref": _CROSSREF_OK})
    res = verify_source(
        {"doi": "10.1/abc", "title": "Creatine supplementation and muscle strength"},
        client=client,  # type: ignore[arg-type]
    )
    assert res.status is CiteStatus.VERIFIED
    assert res.method == "crossref_doi"
    assert res.confidence >= 0.8


def test_doi_title_mismatch_is_suspicious_or_hallucinated() -> None:
    client = _Client({"crossref": _Resp(200, {"message": {"title": ["A totally different paper on quantum optics"]}})})
    res = verify_source(
        {"doi": "10.1/abc", "title": "Creatine supplementation and muscle strength"},
        client=client,  # type: ignore[arg-type]
    )
    assert res.status in (CiteStatus.SUSPICIOUS, CiteStatus.HALLUCINATED)
    assert res.confidence < 0.8


def test_doi_404_is_hallucinated() -> None:
    client = _Client({"crossref": _Resp(404, None)})
    res = verify_source(
        {"doi": "10.9999/nonexistent", "title": "Made up paper"},
        client=client,  # type: ignore[arg-type]
    )
    assert res.status is CiteStatus.HALLUCINATED
    assert res.method == "crossref_doi"


def test_doi_transport_error_falls_through_to_title_then_verified() -> None:
    client = _Client({
        "crossref": httpx.ConnectError("down"),
        "openalex": _Resp(200, {"results": [{"title": "Creatine and strength"}]}),
    })
    res = verify_source(
        {"doi": "10.1/abc", "title": "Creatine and strength"},
        client=client,  # type: ignore[arg-type]
    )
    assert res.status is CiteStatus.VERIFIED
    assert res.method == "openalex_title"


def test_openalex_empty_results_is_hallucinated() -> None:
    client = _Client({"openalex": _Resp(200, {"results": []})})
    res = verify_source(
        {"title": "A paper that does not exist anywhere"},
        client=client,  # type: ignore[arg-type]
    )
    assert res.status is CiteStatus.HALLUCINATED
    assert res.method == "openalex_title"


def test_all_apis_unreachable_is_skipped_never_raises() -> None:
    client = _Client({
        "crossref": httpx.ConnectError("down"),
        "openalex": httpx.ReadTimeout("slow"),
    })
    res = verify_source(
        {"doi": "10.1/abc", "title": "Creatine and strength"},
        client=client,  # type: ignore[arg-type]
    )
    assert res.status is CiteStatus.SKIPPED


def test_garbage_source_is_skipped() -> None:
    client = _Client({})
    res = verify_source({}, client=client)  # type: ignore[arg-type]
    assert res.status is CiteStatus.SKIPPED


def test_verify_sources_dedups_counts_and_flags() -> None:
    client = _Client({
        "crossref": _Resp(200, {"message": {"title": ["Creatine and strength"]}}),
        "openalex": _Resp(200, {"results": []}),
    })
    sources = [
        {"doi": "10.1/abc", "title": "Creatine and strength"},   # VERIFIED via doi
        {"doi": "10.1/abc", "title": "Creatine and strength"},   # duplicate -> dropped
        {"title": "A nonexistent fabricated paper title"},        # HALLUCINATED via openalex empty
    ]
    report = verify_sources(sources, client=client, max_checks=10)  # type: ignore[arg-type]
    assert report["distinct_sources"] == 2
    assert report["checked"] == 2
    counts = report["counts"]
    assert isinstance(counts, dict)
    assert counts[CiteStatus.VERIFIED.value] == 1
    assert counts[CiteStatus.HALLUCINATED.value] == 1
    assert report["has_hallucinated"] is True


def test_verify_sources_respects_max_checks() -> None:
    client = _Client({"crossref": _CROSSREF_OK})
    sources = [{"doi": f"10.1/{i}", "title": "Creatine supplementation and muscle strength"} for i in range(20)]
    report = verify_sources(sources, client=client, max_checks=5)  # type: ignore[arg-type]
    assert report["checked"] == 5
