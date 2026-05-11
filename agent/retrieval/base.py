"""Shared contracts for retrieval sources.

`PaperHit` is the single output shape every source must emit. Helpers
below normalise free-form text, DOIs, and integers so each source client
stays small.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaperHit:
    source: str
    title: str
    abstract: str
    year: int | None
    url: str
    doi: str | None = None
    pmid: str | None = None
    venue: str | None = None

    @property
    def dedupe_key(self) -> str:
        if self.doi:
            return f"doi:{self.doi.casefold()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        return f"title:{self.title.casefold()}:{self.year or ''}"


def clean_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def normalize_doi(value: object) -> str | None:
    doi = clean_text(value, limit=256).lower()
    if not doi:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi or None


def int_or_none(value: object) -> int | None:
    if not isinstance(value, int | float | str | bytes | bytearray):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
