"""Full-text availability check via PMC and Unpaywall.

Per Sprint 6 scope: produce a `FullTextReceipt` for each candidate that
records whether an open-access full-text URL is *available*. Actual byte
download / parsing is deferred to a later sprint. This module is
fail-soft: every HTTP failure logs a non-retrieved receipt with a
reason; one bad call does not sink the run.

Universal: this is the open-access pipeline (PMC for PubMed-indexed work,
Unpaywall for any DOI). Domains without PubMed coverage simply skip the
PMC stage and rely on Unpaywall + DOI; future packs can register other
fetchers without touching this module.
"""
from __future__ import annotations

import asyncio

import httpx

from agent.screening import CandidateStudy, FullTextReceipt
from agent.settings import Settings

_ELINK = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
_UNPAYWALL = "https://api.unpaywall.org/v2/"


async def _pmc_lookup(
    pmid: str, *, client: httpx.AsyncClient, api_key: str
) -> str | None:
    """PMID -> PMCID via NCBI elink. Returns PMCID or None."""
    params: dict[str, str] = {
        "dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key
    try:
        r = await client.get(_ELINK, params=params, timeout=15.0)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    linksets = data.get("linksets") or []
    for ls in linksets:
        for db in ls.get("linksetdbs") or []:
            if db.get("dbto") == "pmc":
                ids = db.get("links") or []
                if ids:
                    return f"PMC{ids[0]}"
    return None


async def _unpaywall_lookup(
    doi: str, *, client: httpx.AsyncClient, email: str
) -> str | None:
    """DOI -> open-access full-text URL or None."""
    if not doi or not email:
        return None
    try:
        r = await client.get(
            f"{_UNPAYWALL}{doi}", params={"email": email}, timeout=15.0
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not data.get("is_oa"):
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or loc.get("url")
    if not isinstance(url, str) or not url:
        return None
    return url


async def fetch_full_text_receipt(
    study: CandidateStudy,
    *,
    client: httpx.AsyncClient,
    settings: Settings,
) -> FullTextReceipt:
    """Try PMC (PMID-based), then Unpaywall (DOI-based). Fail soft."""
    if study.pmid:
        pmc_id = await _pmc_lookup(
            study.pmid, client=client, api_key=settings.ncbi_api_key
        )
        if pmc_id:
            return FullTextReceipt(
                study_id=study.study_id, retrieved=True, source="PMC",
                reason=pmc_id,
            )
    if study.doi:
        oa_url = await _unpaywall_lookup(
            study.doi, client=client, email=settings.unpaywall_email,
        )
        if oa_url:
            return FullTextReceipt(
                study_id=study.study_id, retrieved=True, source="Unpaywall",
                reason=oa_url,
            )
    return FullTextReceipt(
        study_id=study.study_id, retrieved=False, source="none",
        reason="no open-access full text located via PMC or Unpaywall",
    )


async def fetch_full_text_receipts(
    candidates: tuple[CandidateStudy, ...], *, settings: Settings
) -> tuple[FullTextReceipt, ...]:
    """Fan out fetches in parallel; preserve candidate order."""
    if not candidates:
        return ()
    async with httpx.AsyncClient(timeout=20.0) as client:
        receipts = await asyncio.gather(
            *(fetch_full_text_receipt(s, client=client, settings=settings) for s in candidates),
            return_exceptions=False,
        )
    return tuple(receipts)
