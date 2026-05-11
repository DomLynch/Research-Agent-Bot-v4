"""Full-text parsing for eligibility adjudication.

Dereferences a `FullTextReceipt` (PMC XML id or Unpaywall HTML URL),
strips markup, hashes, and returns a `ParsedFullText`. Fail-soft: any
HTTP / parse error sets `error` and leaves `text` empty so downstream
stages can refuse cleanly. PDFs are out of scope for Sprint 7 and
yield a `PDF extraction not supported` error.

Universal: no biomedical literals; only HTTP + regex tag stripping.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx

from agent.pdf_parse import extract_pdf_text
from agent.screening import FullTextReceipt, ParsedFullTextReceipt
from agent.settings import Settings

_EFETCH_PMC = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_MAX_CHARS = 80_000
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

SourceKind = Literal["pmc-xml", "html", "pdf", "unsupported"]


@dataclass(frozen=True, slots=True)
class ParsedFullText:
    study_id: str
    source_url: str
    source_kind: SourceKind
    text: str
    char_count: int
    sha256: str
    fetched_at_utc: str
    error: str = ""

    def to_receipt(self) -> ParsedFullTextReceipt:
        """Project the heavy parsed document down to the slim audit-trail
        receipt that EvidenceState stores."""
        return ParsedFullTextReceipt(
            study_id=self.study_id,
            source_url=self.source_url,
            parsed=bool(self.text),
            text_hash=self.sha256,
            char_count=self.char_count,
            failure_reason=self.error,
        )


def _now_utc() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _strip(markup: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", markup)).strip()[:_MAX_CHARS]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


async def _fetch_pmc_xml(
    pmcid: str, *, client: httpx.AsyncClient, api_key: str
) -> tuple[str, str]:
    params: dict[str, str] = {
        "db": "pmc", "id": pmcid.removeprefix("PMC"),
        "rettype": "full", "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key
    try:
        r = await client.get(_EFETCH_PMC, params=params, timeout=20.0)
        r.raise_for_status()
        return r.text, ""
    except httpx.HTTPError as e:
        return "", f"pmc fetch failed: {e.__class__.__name__}"


async def _fetch_html_or_pdf(
    url: str, *, client: httpx.AsyncClient,
) -> tuple[str, str, str]:
    """Fetch + decode. Returns (text, source_kind_hint, error). Source kind
    is "pdf" or "html" so the caller can record it correctly."""
    try:
        r = await client.get(url, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return "", "html", f"html fetch failed: {e.__class__.__name__}"
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        text, err = extract_pdf_text(r.content)
        return text, "pdf", err
    return r.text, "html", ""


async def parse_one(
    receipt: FullTextReceipt, *, client: httpx.AsyncClient, settings: Settings,
) -> ParsedFullText:
    if not receipt.retrieved:
        return ParsedFullText(
            study_id=receipt.study_id, source_url="", source_kind="unsupported",
            text="", char_count=0, sha256="", fetched_at_utc=_now_utc(),
            error="no open-access source",
        )
    if receipt.source == "PMC":
        raw, err = await _fetch_pmc_xml(
            receipt.reason, client=client, api_key=settings.ncbi_api_key,
        )
        kind: SourceKind = "pmc-xml"
        source_url = f"{_EFETCH_PMC}?db=pmc&id={receipt.reason}"
        text = _strip(raw) if raw else ""
    elif receipt.source == "Unpaywall":
        raw, kind_hint, err = await _fetch_html_or_pdf(receipt.reason, client=client)
        source_url = receipt.reason
        if kind_hint == "pdf":
            kind = "pdf"
            # PyMuPDF/pdfminer return plain text; normalise whitespace + cap length.
            text = _WS_RE.sub(" ", raw).strip()[:_MAX_CHARS] if raw else ""
        else:
            kind = "html"
            text = _strip(raw) if raw else ""
    else:
        return ParsedFullText(
            study_id=receipt.study_id, source_url=receipt.reason,
            source_kind="unsupported", text="", char_count=0, sha256="",
            fetched_at_utc=_now_utc(), error=f"unknown source {receipt.source!r}",
        )
    return ParsedFullText(
        study_id=receipt.study_id, source_url=source_url, source_kind=kind,
        text=text, char_count=len(text), sha256=_hash(text),
        fetched_at_utc=_now_utc(), error=err,
    )


async def parse_full_texts(
    receipts: tuple[FullTextReceipt, ...], *, settings: Settings,
) -> tuple[ParsedFullText, ...]:
    if not receipts:
        return ()
    async with httpx.AsyncClient(timeout=25.0) as client:
        parsed = await asyncio.gather(
            *(parse_one(r, client=client, settings=settings) for r in receipts),
            return_exceptions=False,
        )
    return tuple(parsed)
