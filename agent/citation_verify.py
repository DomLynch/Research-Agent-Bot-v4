"""External citation-existence verifier — catch fabricated / mis-attributed sources.

Complements ``source_audit.py``. That module checks whether a source *abstract*
supports the stored number; this one checks whether the cited source actually
*exists* against external authorities (CrossRef by DOI, OpenAlex by title) and
whether the stored title matches what the authority returns.

Adapted from AutoResearchClaw's ``literature/verify.py`` (MIT). We use ``httpx``
(an existing dependency) instead of stdlib ``urllib`` to match repo conventions.

Design contract — must never break a working publish run:
  - **Graceful**: any network / JSON / parse failure degrades to ``SKIPPED``;
    nothing here raises.
  - **Conservative / corroborated**: ``HALLUCINATED`` requires TWO authorities to
    agree a citation is absent — a CrossRef DOI 404 *and* an OpenAlex title miss.
    A CrossRef 404 alone is never a hard reject (arXiv/DataCite DOIs aren't in
    CrossRef), and an OpenAlex-only miss (no DOI to corroborate) is downgraded to
    ``SUSPICIOUS``. When uncertain we return ``SKIPPED``, never a false reject.
  - **Bounded**: short per-call timeout, a cap on distinct sources checked, and
    a total wall-clock budget.
  - **Advisory by default**: callers gate invocation on a settings flag; this
    module computes a report, it does not decide publication.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CROSSREF_WORK = "https://api.crossref.org/works/"
_OPENALEX_WORKS = "https://api.openalex.org/works"
# CrossRef/OpenAlex "polite pool" — a UA with contact is courtesy, not auth.
_UA = "ResearchAgentBot-v4/citation-verify (https://researka.org)"

_VERIFIED_MIN = 0.80   # title similarity >= this  -> VERIFIED
_SUSPICIOUS_MIN = 0.50  # title similarity >= this  -> SUSPICIOUS, else HALLUCINATED
_DEFAULT_TIMEOUT = 8.0
_DEFAULT_MAX_CHECKS = 15
_DEFAULT_BUDGET_S = 25.0


class CiteStatus(StrEnum):
    VERIFIED = "verified"
    SUSPICIOUS = "suspicious"
    HALLUCINATED = "hallucinated"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CiteResult:
    key: str  # the source identifier we keyed on (doi or title)
    status: CiteStatus
    confidence: float  # 0..1 title similarity (or 1.0 when no expected title)
    method: str  # crossref_doi | openalex_title | skipped
    matched_title: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "matched_title": self.matched_title,
        }


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _title_sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _classify(sim: float, method: str, key: str, matched_title: str) -> CiteResult:
    if sim >= _VERIFIED_MIN:
        status = CiteStatus.VERIFIED
    elif sim >= _SUSPICIOUS_MIN:
        status = CiteStatus.SUSPICIOUS
    else:
        status = CiteStatus.HALLUCINATED
    return CiteResult(key, status, sim, method, matched_title)


def _get_json(
    client: httpx.Client, url: str, *, timeout: float,
) -> tuple[int, object | None]:
    """Return (status_code, json) — code 0 means a transport error (treat as SKIP).

    A 404 (code present, data None) is a positive "not found"; a 0 is unknown.
    """
    try:
        r = client.get(url, timeout=timeout, headers={"User-Agent": _UA})
    except httpx.HTTPError as exc:
        logger.debug("citation_verify transport error %s: %s", url, exc)
        return 0, None
    if r.status_code != 200:
        return r.status_code, None
    try:
        return 200, r.json()
    except ValueError:
        return 0, None


def _verify_by_doi(
    client: httpx.Client, doi: str, expected_title: str, *, timeout: float,
) -> tuple[CiteResult | None, bool]:
    """Resolve a DOI against CrossRef -> ``(result, doi_absent)``.

    ``result`` is set only on a CrossRef hit (200), classified by title match.
    ``doi_absent`` is True only on a 404 — but a 404 ALONE is not proof of
    fabrication: arXiv (10.48550/arXiv.*) and DataCite DOIs are not in CrossRef,
    so the caller corroborates via the title search before concluding.
    """
    raw = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.strip()
    if not raw:
        return None, False
    code, data = _get_json(
        client, _CROSSREF_WORK + urllib.parse.quote(raw, safe=""), timeout=timeout,
    )
    if code == 404:
        return None, True  # absent from CrossRef -> let the title search corroborate
    if code != 200 or not isinstance(data, dict):
        return None, False  # transport/unknown -> let title search try, else SKIP
    message = data.get("message")
    titles = message.get("title") if isinstance(message, dict) else None
    found = titles[0] if isinstance(titles, list) and titles else ""
    if not expected_title:
        return CiteResult(raw, CiteStatus.VERIFIED, 1.0, "crossref_doi", str(found)), False
    return _classify(_title_sim(expected_title, str(found)), "crossref_doi", raw, str(found)), False


def _verify_by_title(
    client: httpx.Client, title: str, *, timeout: float, doi_absent: bool = False,
) -> CiteResult | None:
    if not title.strip():
        return None
    query = urllib.parse.urlencode({"search": title, "per-page": "1"})
    code, data = _get_json(client, f"{_OPENALEX_WORKS}?{query}", timeout=timeout)
    if code != 200 or not isinstance(data, dict):
        return None  # unreachable -> SKIP (never false-reject on API outage)
    results = data.get("results")
    if not isinstance(results, list) or not results:
        # Not found in OpenAlex. HALLUCINATED only when corroborated by a CrossRef
        # 404 (two authorities agree it's absent); an OpenAlex-only miss is a
        # coverage gap -> SUSPICIOUS, never a hard reject (obscure/arXiv preprints).
        status = CiteStatus.HALLUCINATED if doi_absent else CiteStatus.SUSPICIOUS
        return CiteResult(title[:80], status, 0.0, "openalex_title", "")
    found = results[0].get("title") if isinstance(results[0], dict) else ""
    return _classify(_title_sim(title, str(found or "")), "openalex_title", title[:80], str(found or ""))


def verify_source(
    source: Mapping[str, object], *, client: httpx.Client, timeout: float = _DEFAULT_TIMEOUT,
) -> CiteResult:
    """Verify one source_paper dict ({doi, title, ...}). Never raises."""
    doi = str(source.get("doi") or "").strip()
    title = str(source.get("title") or "").strip()
    doi_absent = False
    try:
        if doi:
            res, doi_absent = _verify_by_doi(client, doi, title, timeout=timeout)
            if res is not None:
                return res
        if title:
            by_title = _verify_by_title(client, title, timeout=timeout, doi_absent=doi_absent)
            if by_title is not None:
                return by_title
    except Exception as exc:  # belt-and-braces: never propagate
        logger.debug("citation_verify unexpected error: %s", exc)
    key = doi or title[:80] or "?"
    return CiteResult(key, CiteStatus.SKIPPED, 0.0, "skipped")


def verify_sources(
    sources: Sequence[Mapping[str, object]],
    *,
    client: httpx.Client | None = None,
    max_checks: int = _DEFAULT_MAX_CHECKS,
    budget_s: float = _DEFAULT_BUDGET_S,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, object]:
    """Verify distinct source papers; return an advisory report. Never raises."""
    seen: set[str] = set()
    distinct: list[Mapping[str, object]] = []
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        key = str(src.get("doi") or "").strip().lower() or str(src.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        distinct.append(src)

    owns_client = client is None
    client = client or httpx.Client()
    results: list[CiteResult] = []
    deadline = time.monotonic() + budget_s
    try:
        for src in distinct[:max_checks]:
            if time.monotonic() >= deadline:
                results.append(CiteResult(
                    str(src.get("doi") or src.get("title") or "?")[:80],
                    CiteStatus.SKIPPED, 0.0, "budget_exhausted"))
                continue
            results.append(verify_source(src, client=client, timeout=timeout))
    finally:
        if owns_client:
            client.close()

    counts = {s.value: 0 for s in CiteStatus}
    for r in results:
        counts[r.status.value] += 1
    return {
        "checked": len(results),
        "distinct_sources": len(distinct),
        "counts": counts,
        # The advisory verdict: did any cited source confidently fail to exist?
        "has_hallucinated": counts[CiteStatus.HALLUCINATED.value] > 0,
        "has_suspicious": counts[CiteStatus.SUSPICIOUS.value] > 0,
        "results": [r.as_dict() for r in results],
    }


def verify_run(
    run_dir: Path, *, max_checks: int = _DEFAULT_MAX_CHECKS,
) -> dict[str, object]:
    """Verify the source papers cited in a run; write ``citation_verify.json``.

    Reads ``all_facts.json``, verifies each distinct ``source_paper``, and writes
    the advisory report into the run directory. Self-contained and never raises —
    a missing/corrupt facts file or write failure degrades to an empty report.
    """
    try:
        facts = json.loads((run_dir / "all_facts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"checked": 0, "distinct_sources": 0, "counts": {}, "results": []}
    sources = [
        f["source_paper"]
        for f in facts
        if isinstance(f, Mapping) and isinstance(f.get("source_paper"), Mapping)
    ]
    report = verify_sources(sources, max_checks=max_checks)
    with suppress(OSError):
        (run_dir / "citation_verify.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8",
        )
    return report
