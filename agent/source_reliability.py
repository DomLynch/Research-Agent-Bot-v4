"""Deterministic source reliability tiers for extracted evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlparse

ReliabilityTier = Literal["high", "medium", "low"]

_HIGH_JOURNAL_HINTS = (
    "journal", "proceedings", "transactions", "nature", "science", "cell",
    "lancet", "jama", "nejm", "bmj", "pnas", "econometrica",
    "american economic review", "quarterly journal of economics",
    "journal of finance", "management science", "strategic management journal",
)
_MEDIUM_SOURCE_HINTS = (
    "reuters", "associated press", "ap news", "bbc", "financial times",
    "economist", "wall street journal", "new york times", "bloomberg",
    "working paper", "preprint", "nber", "ssrn", "arxiv", "biorxiv",
    "medrxiv",
)
_LOW_SOURCE_HINTS = (
    "blog", "substack", "medium.com", "wordpress", "press release",
    "sponsored", "vendor", "company blog", "personal site",
)
_MEDIUM_DOMAINS = (
    "reuters.com", "apnews.com", "bbc.com", "ft.com", "economist.com",
    "wsj.com", "nytimes.com", "bloomberg.com", "nber.org", "ssrn.com",
    "arxiv.org", "biorxiv.org", "medrxiv.org",
)
_LOW_DOMAINS = (
    "medium.com", "substack.com", "wordpress.com", "blogspot.com",
)


def _text(source: Mapping[str, Any]) -> str:
    return " ".join(
        str(source.get(key) or "")
        for key in (
            "source_type", "publisher", "venue", "journal", "journal_name",
            "container_title", "title", "url", "source_url", "landing_page_url",
            "doi", "pmid", "pmcid",
        )
    ).casefold()


def _domain(source: Mapping[str, Any]) -> str:
    for key in ("url", "source_url", "landing_page_url"):
        raw = str(source.get(key) or "").strip()
        if not raw:
            continue
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.netloc or parsed.path.split("/", 1)[0]).casefold()
        return host.removeprefix("www.")
    return ""


def source_reliability_tier(source: Mapping[str, Any] | None) -> ReliabilityTier:
    """Classify a source into high/medium/low reliability.

    Unknown sparse metadata defaults to medium so legacy fact fixtures are not
    silently downgraded. Low is reserved for explicit blog/vendor/self-published
    signals.
    """
    if not source:
        return "medium"
    explicit = str(source.get("reliability") or source.get("source_reliability") or "").lower()
    if explicit in {"high", "medium", "low"}:
        return explicit  # type: ignore[return-value]

    text = _text(source)
    domain = _domain(source)
    if any(hint in text for hint in _LOW_SOURCE_HINTS) or any(
        domain == d or domain.endswith(f".{d}") for d in _LOW_DOMAINS
    ):
        return "low"
    if domain.endswith(".gov") or domain.endswith(".edu"):
        return "high"
    if any(hint in text for hint in _HIGH_JOURNAL_HINTS):
        return "high"
    if source.get("doi") or source.get("pmid") or source.get("pmcid"):
        return "high"
    if any(hint in text for hint in _MEDIUM_SOURCE_HINTS) or any(
        domain == d or domain.endswith(f".{d}") for d in _MEDIUM_DOMAINS
    ):
        return "medium"
    return "medium"
