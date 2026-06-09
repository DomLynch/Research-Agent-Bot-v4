"""ClinicalTrials.gov API v2 search.

Public endpoint; no auth. Returns trial records (not journal articles).
For meta-syntheses where trial registry presence is part of the
audit-trail (e.g. interventional studies of geroprotective compounds),
this source surfaces NCT-id metadata that downstream gates can match
against the registry-record sentinel list.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.api_client import async_api_request
from agent.retrieval.base import PaperHit, clean_text, int_or_none
from agent.settings import Settings

_STUDIES = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsGovSource:
    name = "ctgov"

    def __init__(self, settings: Settings) -> None:
        _ = settings

    @property
    def configured(self) -> bool:
        return True

    async def search(
        self, query: str, *, client: httpx.AsyncClient, retmax: int = 100,
    ) -> list[PaperHit]:
        params: dict[str, str] = {
            "query.term": clean_text(query, limit=1024),
            "pageSize": str(min(retmax, 1000)),
            "format": "json",
        }
        r = await async_api_request(
            client, "GET", _STUDIES, service=self.name, params=params, timeout=20.0,
        )
        if r is None:
            return []
        try:
            data: Any = r.json()
        except ValueError:
            return []
        items = data.get("studies", []) if isinstance(data, dict) else []
        hits: list[PaperHit] = []
        for item in items:
            hit = _parse_item(item)
            if hit is not None:
                hits.append(hit)
        return hits


def _parse_item(item: Any) -> PaperHit | None:
    if not isinstance(item, dict):
        return None
    proto = (item.get("protocolSection") or {})
    ident = (proto.get("identificationModule") or {})
    nct = clean_text(ident.get("nctId"), limit=32)
    title = clean_text(
        ident.get("briefTitle") or ident.get("officialTitle"), limit=500,
    )
    if not title or not nct:
        return None
    desc = (proto.get("descriptionModule") or {})
    abstract = clean_text(
        desc.get("briefSummary") or desc.get("detailedDescription"), limit=8000,
    )
    status = (proto.get("statusModule") or {})
    date = clean_text(
        status.get("startDateStruct", {}).get("date")
        or status.get("studyFirstPostDateStruct", {}).get("date"),
        limit=16,
    )
    year = int_or_none(date[:4]) if date else None
    return PaperHit(
        source="ctgov",
        title=title,
        abstract=abstract,
        year=year,
        url=f"https://clinicaltrials.gov/study/{nct}",
        doi=None,
        pmid=None,
        venue="ClinicalTrials.gov",
    )
