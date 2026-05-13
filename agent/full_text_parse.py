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
# Sprint 7.9: detect non-paper content that PMC / publisher sites sometimes
# return under load (rate-limit reCAPTCHA, JS redirects, paywalls). Any of
# these in the first few hundred chars means the "parse" is junk and
# parse_one should treat it as failure + try the Unpaywall fallback.
_JUNK_MARKERS = (
    "recaptcha",
    "robot check",
    "are you a human",
    "redirecting var timerstart",
    "access denied",
    "request blocked",
    "we apologize for the inconvenience",
    # Sprint 12.9 Task B — broadened junk detection so cookie / paywall
    # splash pages no longer count as a successful parse and the
    # Europe-PMC + PDF-retry fallback chain fires for them.
    "subscribe to access this content",
    "subscribe to read",
    "purchase this article",
    "cookie consent",
    "please enable javascript",
    "checking your browser",
    "cloudflare",
    "ddos protection",
)


def _looks_like_junk(text: str) -> bool:
    head = text[:1500].casefold()
    return any(m in head for m in _JUNK_MARKERS)


# Sprint 12.9 Task B — minimum body length for a "parse counts as
# adequate" verdict in the fallback ladder. Anything below this AND a
# fallback URL exists triggers the PMC-mirror / PDF-retry chain.
_THIN_PARSE_CHARS = 2000

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


async def _fetch_europepmc_xml(
    pmcid: str, *, client: httpx.AsyncClient,
) -> tuple[str, str]:
    """Sprint 12.9 Task B — Europe PMC `fullTextXML` mirror.

    Free, public, no-auth REST endpoint that mirrors PubMed Central full-
    text. Used when NCBI's eutils PMC returns junk (reCAPTCHA / redirect)
    or thin content; Europe PMC's parser sometimes serves a clean full
    body where NCBI returns an abstract-only envelope under load.

    Returns (raw_xml, error). Empty raw on any HTTP failure — the caller
    keeps the previous fallback chain intact.
    """
    pid = pmcid.removeprefix("PMC")
    try:
        r = await client.get(
            f"https://europepmc.org/europepmc/webservices/rest/PMC{pid}/fullTextXML",
            timeout=20.0,
        )
        r.raise_for_status()
        return r.text, ""
    except httpx.HTTPError as e:
        return "", f"europepmc fetch failed: {e.__class__.__name__}"


def _pdf_retry_variants(url: str) -> tuple[str, ...]:
    """Sprint 12.9 Task B — when an HTML parse comes back thin, the same
    publisher URL often serves a PDF at a slightly different path. Try
    a small, ordered set of pure URL transforms (no probing) and let
    `_fetch_html_or_pdf` decide if any of them returned PDF bytes.

    Universal: pure URL-shape heuristics, no biomedical or publisher-
    specific literals. Order: most-likely-PDF-suffix variants first.
    """
    candidates: list[str] = []
    low = url.lower()
    if not low.endswith(".pdf"):
        candidates.append(url + ".pdf")
        candidates.append(url + ".full.pdf")
    if "/abstract" in url:
        candidates.append(url.replace("/abstract", "/pdf"))
    if "/article/" in url and "/pdf/" not in url:
        candidates.append(url.replace("/article/", "/pdf/"))
    # Dedupe, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c != url and c not in seen:
            seen.add(c)
            out.append(c)
    return tuple(out)


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
        # Sprint 7.9: NCBI under load returns a reCAPTCHA / "Redirecting"
        # page instead of real XML; PMC also sometimes returns abstract-
        # only envelopes (Miller-2011 at 4041 chars). In either case the
        # PMC parse is unusable - drop it so the Europe-PMC / Unpaywall
        # fallback chain fires.
        if _looks_like_junk(text):
            text = ""
            err = "pmc returned junk content (reCAPTCHA/redirect/blocked)"
        # Sprint 12.9 Task B — Europe PMC mirror is the first fallback
        # because it shares the PMC XML format (no source_kind change)
        # and frequently serves what NCBI is rate-limiting / blocking.
        if len(text) < 5000:
            ep_raw, ep_err = await _fetch_europepmc_xml(
                receipt.reason, client=client,
            )
            ep_text = _strip(ep_raw) if ep_raw else ""
            if _looks_like_junk(ep_text):
                ep_text = ""
            if len(ep_text) > len(text):
                text = ep_text
                source_url = (
                    f"https://europepmc.org/europepmc/webservices/rest/"
                    f"PMC{receipt.reason.removeprefix('PMC')}/fullTextXML"
                )
                err = ep_err if not ep_text else ""
        if len(text) < 5000 and receipt.fallback_url:
            fb_raw, fb_kind, fb_err = await _fetch_html_or_pdf(
                receipt.fallback_url, client=client,
            )
            if fb_kind == "pdf" and fb_raw:
                fb_text = _WS_RE.sub(" ", fb_raw).strip()[:_MAX_CHARS]
            elif fb_raw:
                fb_text = _strip(fb_raw)
            else:
                fb_text = ""
            if len(fb_text) > len(text):
                text = fb_text
                kind = "pdf" if fb_kind == "pdf" else "html"
                source_url = receipt.fallback_url
                err = fb_err if not fb_text else ""
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
        # Sprint 12.9 Task B — HTML strip came back thin or junk;
        # try a small, ordered set of URL-shape PDF variants. Stops at
        # the first successful PDF extraction. Pure URL transforms, no
        # publisher-specific literals.
        if (kind == "html" and (
            len(text) < _THIN_PARSE_CHARS or _looks_like_junk(text)
        )):
            for variant in _pdf_retry_variants(receipt.reason):
                v_raw, v_kind, v_err = await _fetch_html_or_pdf(
                    variant, client=client,
                )
                if v_kind == "pdf" and v_raw:
                    v_text = _WS_RE.sub(" ", v_raw).strip()[:_MAX_CHARS]
                    if len(v_text) > len(text):
                        text = v_text
                        kind = "pdf"
                        source_url = variant
                        err = v_err if not v_text else ""
                        break
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


def load_manual_full_text_overrides(
    topic: str, candidates_doi_pmid: dict[str, tuple[str, str]],
    *, base_dir: str | None = None,
) -> dict[str, str]:
    """Sprint 9 corpus recovery: load manual full-text overrides.

    The pipeline keeps an opt-in directory at
    `topic_packs/manual_full_text/<topic>/` where the operator can drop
    a verbatim full-text file per sentinel paper that the auto retrieval
    cannot recover (Nature paywall / OUP auth / abstract-only PMC strip).
    Files are looked up by normalised DOI ('10.1038-nature08221.txt') or
    by PMID ('19587680.txt'); returns a {study_id: text} dict for any
    candidate whose identifier matches a file on disk. Universal: no
    biomedical literals; the directory is topic-pack-scoped, the lookup
    is identifier-based.
    """
    from pathlib import Path
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent / "topic_packs" / "manual_full_text" / topic
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for study_id, (doi, pmid) in candidates_doi_pmid.items():
        candidates = []
        if doi:
            candidates.append(doi.casefold().replace("/", "-") + ".txt")
        if pmid:
            candidates.append(pmid + ".txt")
        for name in candidates:
            path = root / name
            if path.exists():
                out[study_id] = path.read_text(encoding="utf-8", errors="replace")[:_MAX_CHARS]
                break
    return out


def apply_manual_overrides(
    parsed_docs: tuple[ParsedFullText, ...],
    overrides: dict[str, str],
) -> tuple[ParsedFullText, ...]:
    """Replace parsed docs whose study_id has a manual text override.
    Marks the override with source_url='manual:full_text' so audit can
    distinguish operator-supplied content from auto-fetched bytes."""
    if not overrides:
        return parsed_docs
    result: list[ParsedFullText] = []
    for d in parsed_docs:
        if d.study_id in overrides:
            text = overrides[d.study_id]
            result.append(ParsedFullText(
                study_id=d.study_id, source_url="manual:full_text",
                source_kind="html", text=text, char_count=len(text),
                sha256=_hash(text), fetched_at_utc=_now_utc(),
                error="" if text.strip() else "manual override empty",
            ))
        else:
            result.append(d)
    return tuple(result)


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
