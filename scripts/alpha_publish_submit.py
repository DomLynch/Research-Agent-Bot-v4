"""HTTP submission helpers for alpha publish cycles."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any
from uuid import UUID

Json = dict[str, Any]
Submitter = Callable[[Json], Json]


def _as_uuid(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(UUID(text))
    except ValueError:
        return ""


def _source_key(row: Json) -> str:
    return (
        str(row.get("doi") or "").strip().lower()
        or str(row.get("id") or "").strip().lower()
        or str(row.get("url") or "").strip().lower()
        or str(row.get("title") or "").strip().lower()
    )


def _source_excerpt(row: Json, evidence_by_key: dict[str, Json]) -> str:
    evidence = evidence_by_key.get(_source_key(row), {})
    raw_fact = evidence.get("source_fact")
    fact: Json = raw_fact if isinstance(raw_fact, dict) else {}
    text = (
        row.get("excerpt")
        or row.get("note")
        or fact.get("canonical_phrase")
        or fact.get("finding")
        or evidence.get("abstract")
        or row.get("title")
        or evidence.get("title")
        or "Source receipt attached for alpha memo verification."
    )
    excerpt = " ".join(str(text).split())
    return excerpt if len(excerpt) >= 20 else f"Source receipt: {excerpt}"


def _native_source_bundle(payload: Json) -> list[Json]:
    raw_evidence = payload.get("evidence_bundle")
    evidence: Json = raw_evidence if isinstance(raw_evidence, dict) else {}
    raw_papers = evidence.get("source_papers") or evidence.get("direct_source_papers") or []
    papers = [
        row for row in raw_papers
        if isinstance(row, dict)
    ]
    evidence_by_key = {_source_key(row): row for row in papers if _source_key(row)}
    out: list[Json] = []
    for row in payload.get("source_bundle") or []:
        if not isinstance(row, dict):
            continue
        source_type = str(row.get("source_type") or row.get("evidence_type") or "fullraw")[:40]
        evidence_row = evidence_by_key.get(_source_key(row), {})
        year = row.get("year") or evidence_row.get("publication_year")
        year_text = str(year or "")
        out.append({
            "source_type": source_type if len(source_type) >= 2 else "fullraw",
            "id": str(row.get("id") or row.get("doi") or row.get("url") or "").strip() or None,
            "title": " ".join(str(row.get("title") or "Untitled source").split())[:300],
            "url": row.get("url"),
            "doi": row.get("doi"),
            "excerpt": _source_excerpt(row, evidence_by_key),
            "year": int(year_text) if year_text.isdigit() else None,
        })
    return out


def _object_type(payload: Json, metadata: Json, parent: str) -> str:
    explicit = str(payload.get("object_type") or metadata.get("object_type") or "").strip()
    if explicit:
        return explicit
    return "rebuttal" if parent else "proposal"


def _native_research_object_payload(payload: Json) -> Json:
    metadata: Json = dict(payload.get("metadata") or {})
    agent_slug = str(
        payload.get("author_agent_slug")
        or payload.get("author_agent_id")
        or payload.get("agent_id")
        or ""
    ).strip()
    parent = _as_uuid(
        payload.get("parent_object_id")
        or metadata.get("revision_of_object_id")
        or payload.get("parent_submission_id")
    )
    article_type = str(payload.get("article_type") or metadata.get("article_type") or "")
    if article_type in {"", "alpha_memo"}:
        article_type = "rapid_evidence_synthesis"
    source_bundle = _native_source_bundle(payload)
    native: Json = {
        "domain_slug": str(payload.get("domain_slug") or metadata.get("domain_slug") or "").strip(),
        "author_agent_slug": agent_slug,
        "object_type": _object_type(payload, metadata, parent),
        "title": str(payload.get("title") or payload.get("topic") or "Alpha memo")[:300],
        "abstract": payload.get("abstract") or payload.get("summary"),
        "body_markdown": str(payload.get("body_markdown") or payload.get("markdown") or payload.get("summary") or payload.get("title") or ""),
        "source_bundle": source_bundle,
        "source_citations": [
            {
                "title": item["title"],
                "url": item.get("url"),
                "doi": item.get("doi"),
                "note": item.get("excerpt"),
            }
            for item in source_bundle
        ],
        "article_type": article_type,
        "research_mode": str(payload.get("research_mode") or metadata.get("research_mode") or "source_grounded_synthesis"),
        "tags": [str(payload.get("topic") or metadata.get("topic") or "").strip()],
        "visibility": str(payload.get("visibility") or "public"),
        "metadata": metadata,
        "auto_enqueue_follow_up": True,
    }
    if parent:
        native["parent_object_id"] = parent
        metadata["revision_of_object_id"] = parent
        metadata.setdefault("revision_of", parent)
    return native


def _legacy_fallback_payload(payload: Json) -> Json:
    fallback = dict(payload)
    metadata: Json = dict(fallback.get("metadata") or {})
    parent = _as_uuid(
        fallback.get("parent_submission_id")
        or fallback.get("parent_object_id")
        or metadata.get("revision_of_object_id")
        or metadata.get("revision_of")
    )
    if parent:
        fallback.setdefault("parent_submission_id", parent)
        fallback.setdefault("parent_object_id", parent)
        fallback.setdefault("object_type", _object_type(fallback, metadata, parent))
        metadata.setdefault("revision_of_object_id", parent)
        metadata.setdefault("revision_of", parent)
    fallback["metadata"] = metadata
    return fallback


def http_submitter(url: str, token: str) -> Submitter:
    def legacy_url() -> str:
        parts = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/submissions", "", ""))

    def send(target_url: str, body_payload: Json, *, native: bool) -> Json:
        body = json.dumps(body_payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": token,
            "Content-Type": "application/json",
        }
        if native:
            headers["X-Agent-Slug"] = str(body_payload.get("author_agent_slug") or "")
            headers["X-Agent-Key"] = token
        req = urllib.request.Request(
            target_url,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                text = response.read().decode("utf-8")
                return {"ok": True, "status": response.status, "response": json.loads(text)}
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "response": text[:1000]}

    def submit(payload: Json) -> Json:
        native = "/v1/research-objects" in url
        body_payload = _native_research_object_payload(payload) if native else payload
        result = send(url, body_payload, native=native)
        if native and result.get("status") == 404 and "not found" in str(result.get("response", "")).lower():
            fallback = send(legacy_url(), _legacy_fallback_payload(payload), native=False)
            fallback["fallback_from_url"] = url
            fallback["fallback_reason"] = "native_research_objects_not_found"
            return fallback
        return result
    return submit


def submit_with_backoff(
    payload: Json,
    submitter: Submitter,
    *,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Json:
    attempts: list[Json] = []
    for i in range(retries + 1):
        result = submitter(payload)
        attempts.append(result)
        status = int(result.get("status") or 0)
        if result.get("ok"):
            return {"status": "accepted", "attempts": attempts}
        text = json.dumps(result.get("response", "")).lower()
        if "duplicate" in text:
            return {"status": "rejected_duplicate", "attempts": attempts}
        if "evidence" in text or "curation" in text:
            return {"status": "rejected_needs_evidence", "attempts": attempts}
        if status < 500:
            return {"status": "rejected", "attempts": attempts}
        if i < retries:
            sleep(2**i)
    return {"status": "failed_retry_exhausted", "attempts": attempts}
