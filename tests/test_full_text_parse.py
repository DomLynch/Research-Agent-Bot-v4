"""Full-text parse tests — no network."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from agent.full_text_parse import (
    ParsedFullText,
    parse_full_texts,
    parse_one,
)
from agent.screening import FullTextReceipt


def _make_settings() -> Any:
    return SimpleNamespace(ncbi_api_key="")


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200, content_type: str = "text/html"):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[str] = []

    async def get(self, url: str, **_: Any) -> _FakeResponse:
        self.calls.append(url)
        return self.response


def test_no_oa_source_returns_empty_record() -> None:
    receipt = FullTextReceipt(
        study_id="s1", retrieved=False, source="none", reason="not found",
    )
    client = _FakeClient(_FakeResponse("ignored"))

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.error == "no open-access source"
    assert out.text == ""
    assert client.calls == []


def test_pmc_xml_strips_tags_and_hashes() -> None:
    raw = "<article><body><p>Lifespan was   extended  in mice.</p></body></article>"
    client = _FakeClient(_FakeResponse(raw, content_type="text/xml"))
    receipt = FullTextReceipt(study_id="s2", retrieved=True, source="PMC", reason="PMC12345")

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "pmc-xml"
    assert "lifespan was extended in mice" in out.text.lower()
    assert "<" not in out.text
    assert out.sha256
    assert out.char_count == len(out.text)


def test_unpaywall_html_path_used_for_doi_url() -> None:
    client = _FakeClient(_FakeResponse("<html><p>hello</p></html>"))
    receipt = FullTextReceipt(
        study_id="s3", retrieved=True, source="Unpaywall",
        reason="https://example.org/paper.html",
    )

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "html"
    assert client.calls == ["https://example.org/paper.html"]
    assert "hello" in out.text


def test_pdf_url_returns_unsupported_error() -> None:
    client = _FakeClient(_FakeResponse("ignored", content_type="application/pdf"))
    receipt = FullTextReceipt(
        study_id="s4", retrieved=True, source="Unpaywall",
        reason="https://example.org/paper.pdf",
    )

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert "PDF extraction not supported" in out.error
    assert out.text == ""


def test_unknown_source_returns_unsupported() -> None:
    receipt = FullTextReceipt(study_id="s5", retrieved=True, source="ResearkaDB", reason="x")
    client = _FakeClient(_FakeResponse("ignored"))

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "unsupported"
    assert "unknown source" in out.error


def test_parse_full_texts_empty_returns_empty_tuple() -> None:
    assert asyncio.run(parse_full_texts((), settings=_make_settings())) == ()


def test_parse_full_texts_routes_through_async_client(monkeypatch: Any) -> None:
    response = _FakeResponse("<p>extension of lifespan</p>")
    fake = _FakeClient(response)

    class _CM:
        async def __aenter__(self) -> _FakeClient:
            return fake

        async def __aexit__(self, *_: Any) -> None:
            return None

    monkeypatch.setattr("agent.full_text_parse.httpx.AsyncClient", lambda **_: _CM())
    receipts = (FullTextReceipt(study_id="s6", retrieved=True, source="Unpaywall", reason="u"),)
    out = asyncio.run(parse_full_texts(receipts, settings=_make_settings()))
    assert len(out) == 1
    assert out[0].source_kind == "html"
    assert "extension of lifespan" in out[0].text


def test_fail_soft_on_http_error() -> None:
    import httpx

    class _BadClient:
        async def get(self, *_: Any, **__: Any) -> _FakeResponse:
            raise httpx.ConnectError("dns")

    receipt = FullTextReceipt(study_id="s7", retrieved=True, source="PMC", reason="PMC9")

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=_BadClient(), settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert "pmc fetch failed" in out.error
    assert out.text == ""
    # Hash of empty string is deterministic (sha256 of "")
    assert out.sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


_ = patch  # silence unused import on some platforms
