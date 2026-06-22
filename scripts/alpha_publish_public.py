"""Public alpha page helpers for publish decision reconciliation."""
from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Json = dict[str, Any]
PageFetcher = Callable[[str], Json]

PUBLISH_RENDER_POLL_ATTEMPTS = 6
PUBLISH_RENDER_POLL_DELAY_S = 5.0


def public_alpha_base() -> str:
    return os.environ.get("RESEARKA_ALPHA_BASE_URL", "https://researka.org/alpha").rstrip("/")


def public_alpha_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    return public_alpha_base() + "/" + urllib.parse.quote(raw, safe="")


def public_alpha_urls(payload: Any) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        url = public_alpha_url(value)
        if url and url not in urls:
            urls.append(url)

    if isinstance(payload, dict):
        publication = payload.get("publication")
        if isinstance(publication, dict):
            add(publication.get("url"))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_l = str(key).lower()
                if key_l in {
                    "alpha_url",
                    "canonical_url",
                    "public_url",
                    "publication_url",
                    "url",
                }:
                    # Accept the Researka public-page form regardless of scheme:
                    # the platform migrated alpha memos from /alpha/<id> to
                    # /papers/<id>. The path token still distinguishes our
                    # published page from cited-source URLs under "url" keys.
                    item_s = str(item)
                    if "url" not in key_l or "/alpha/" in item_s or "/papers/" in item_s:
                        add(item)
                elif "id" in key_l and any(
                    token in key_l for token in ("alpha", "public", "publication")
                ):
                    add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return urls


def fetch_public_page(url: str) -> Json:
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {"ok": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "body": exc.read(512).decode("utf-8", errors="replace"),
        }
    except Exception as exc:  # pragma: no cover - network defensive path
        return {
            "ok": False,
            "status": 0,
            "error": type(exc).__name__,
            "detail": str(exc)[:180],
        }


def page_rendered(result: Json) -> bool:
    body = str(result.get("body") or "").lower()
    missing_title = re.search(r"<title\b[^>]*>[^<]*(404|not found)[^<]*</title>", body)
    return (
        bool(result.get("ok"))
        and int(result.get("status") or 0) == 200
        and not missing_title
    )


def public_page_check(
    decision: Json, *, page_fetcher: PageFetcher,
    attempts: int = 1, delay_s: float = 0.0,
) -> Json:
    # Researka builds the public page asynchronously after accepting a
    # submission: the first fetch can hit the "Not Found" SPA shell (HTTP 200
    # with a not-found <title>) even though the page renders seconds later.
    # A single eager check therefore falsely marks genuinely-accepted memos as
    # `public_page_not_rendered` -> rejected -> stuck at published=0 forever
    # (the "repair" path then resubmits and gets duplicate-blocked). Poll a
    # bounded number of times before declaring the page unrendered. Defaults
    # (attempts=1, delay_s=0) preserve the original single-shot behaviour for
    # callers that re-check on their own schedule (e.g. the reconcile sweep).
    urls = public_alpha_urls(decision)
    if not urls:
        return {"ok": False, "status": "missing_public_url", "urls": []}
    checks: list[Json] = []
    for attempt in range(max(1, attempts)):
        checks = []
        for url in urls:
            result = page_fetcher(url)
            check = {
                "url": url,
                "http_status": result.get("status"),
                "ok": page_rendered(result),
            }
            if result.get("error"):
                check["error"] = result.get("error")
            checks.append(check)
            if check["ok"]:
                return {"ok": True, "status": "rendered", "url": url, "checks": checks}
        if delay_s > 0 and attempt < max(1, attempts) - 1:
            time.sleep(delay_s)
    return {"ok": False, "status": "not_rendered", "urls": urls, "checks": checks}
