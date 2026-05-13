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
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]


class _FakeClient:
    def __init__(self, *responses: _FakeResponse) -> None:
        # Backwards-compat: callers passing a single response get the
        # legacy "always-return-this" behaviour. Callers passing
        # multiple responses get FIFO ordering — first call returns
        # the first response, second call returns the second, etc.;
        # the last response is repeated for any additional calls.
        if not responses:
            raise ValueError("_FakeClient needs at least one response")
        self._responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url: str, **_: Any) -> _FakeResponse:
        self.calls.append(url)
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


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
    # HTML body must be substantial enough to NOT trigger the Sprint 12.9
    # Task B thin-retry chain (>_THIN_PARSE_CHARS=2000 chars stripped).
    big_html = (
        "<html><body><p>The intervention was associated with measurable "
        "outcome benefit relative to the baseline cohort across the "
        "pre-specified window. The pipeline records this as a parsed "
        "full-text record.</p></body></html>"
    ) * 30
    client = _FakeClient(_FakeResponse(big_html))
    receipt = FullTextReceipt(
        study_id="s3", retrieved=True, source="Unpaywall",
        reason="https://example.org/paper.html",
    )

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "html"
    assert client.calls == ["https://example.org/paper.html"]
    assert "intervention was associated" in out.text


def test_unpaywall_html_thin_triggers_pdf_retry_variants() -> None:
    """Sprint 12.9 Task B — when Unpaywall HTML strips to <2000 chars,
    parse_one tries a small ordered set of URL-shape PDF variants
    (<url>.pdf, <url>.full.pdf, .../pdf instead of /abstract, ...).
    Stops at the first successful PDF extraction. Universal — pure URL
    transforms with no biomedical or publisher-specific literals.
    """
    # First response is a thin HTML stub (5 chars stripped). Second is
    # a PDF that the PyMuPDF extractor will turn into substantial text.
    # We monkey-patch extract_pdf_text so the test doesn't depend on a
    # real PDF being present.
    import importlib
    parse_mod = importlib.import_module("agent.full_text_parse")

    def _fake_extract(content: bytes) -> tuple[str, str]:
        return ("Pretend this is a long PDF body. " * 200, "")

    parse_mod.extract_pdf_text = _fake_extract  # type: ignore[attr-defined]
    responses = [
        _FakeResponse("<html><p>hi</p></html>"),
        _FakeResponse("%PDF-1.4 fake bytes", content_type="application/pdf"),
    ]
    client = _FakeClient(*responses)
    receipt = FullTextReceipt(
        study_id="s4", retrieved=True, source="Unpaywall",
        reason="https://example.org/paper.html",
    )

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "pdf"
    assert "Pretend this is a long PDF body" in out.text
    # First call HTML, second call the .pdf variant.
    assert client.calls[0] == "https://example.org/paper.html"
    assert client.calls[1] == "https://example.org/paper.html.pdf"


def test_pdf_url_routes_through_pdf_extractor(monkeypatch: Any) -> None:
    # Mock extract_pdf_text so this test works regardless of whether
    # pymupdf/pdfminer are installed in the test environment.
    monkeypatch.setattr(
        "agent.full_text_parse.extract_pdf_text",
        lambda data, **_: ("rapamycin extends lifespan in mice", ""),
    )
    client = _FakeClient(_FakeResponse("PDFBYTES", content_type="application/pdf"))
    receipt = FullTextReceipt(
        study_id="s4", retrieved=True, source="Unpaywall",
        reason="https://example.org/paper.pdf",
    )

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "pdf"
    assert out.error == ""
    assert "rapamycin extends lifespan in mice" in out.text


def test_pdf_url_records_extractor_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agent.full_text_parse.extract_pdf_text",
        lambda data, **_: ("", "pymupdf: open failed | pdfminer: open failed"),
    )
    client = _FakeClient(_FakeResponse("BROKENPDF", content_type="application/pdf"))
    receipt = FullTextReceipt(
        study_id="s5", retrieved=True, source="Unpaywall",
        reason="https://example.org/paper.pdf",
    )

    async def go() -> ParsedFullText:
        return await parse_one(receipt, client=client, settings=_make_settings())  # type: ignore[arg-type]

    out = asyncio.run(go())
    assert out.source_kind == "pdf"
    assert "pymupdf" in out.error
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
    # HTML must be substantial enough not to trigger the Sprint 12.9
    # Task B thin-retry chain — this test asserts the async-client
    # routing, not retry behaviour, so we feed it a long body.
    response = _FakeResponse(
        "<p>" + ("extension of lifespan was observed in mice. " * 80) + "</p>"
    )
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
