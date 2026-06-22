"""Decision API helpers for alpha publish cycles."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from scripts import alpha_publish_public as publish_public
from scripts import alpha_publish_status as publish_status

Json = dict[str, Any]
DecisionFetcher = Callable[[str], Json]
PageFetcher = Callable[[str], Json]


def decision_fetch(submission_id: str) -> Json:
    base = os.environ.get("RESEARKA_DECISION_URL_BASE", "https://api.researka.org/submissions")
    url = base.rstrip("/") + "/" + urllib.parse.quote(submission_id, safe="") + "/decision"
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def submission_id(payload: Json) -> str:
    direct = payload.get("submission_id")
    if direct:
        return str(direct)
    submission = payload.get("submission")
    if isinstance(submission, dict) and submission.get("id"):
        return str(submission.get("id"))
    for key in ("detail", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = submission_id(nested)
            if found:
                return found
    for attempt in payload.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("response")
        if isinstance(response, dict):
            found = submission_id(response)
            if found:
                return found
        elif isinstance(response, str):
            with suppress(json.JSONDecodeError):
                found = submission_id(json.loads(response))
                if found:
                    return found
    nested = payload.get("submission")
    return str(nested.get("id") if isinstance(nested, dict) else "")


def apply_submission_decision(
    ledger: Json,
    *,
    submission_id_value: str,
    decision: Json,
    page_fetcher: PageFetcher,
) -> str:
    final = "pending"
    if decision.get("status") == "complete":
        if decision.get("decision") == "accept":
            if decision.get("failure_category") == "integrity_duplicate":
                final = "accepted"
                ledger["status"] = publish_status.CycleStatus.DEDUPED_PUBLICATION.value
                ledger["published"] = 0
                ledger["published_topic"] = (
                    ledger.get("submitted_topic")
                    or (ledger.get("candidate") or {}).get("topic")
                )
                ledger.pop("publish_failure_reason", None)
                ledger["submission_id"] = submission_id_value
                ledger["researka_decision"] = decision
                ledger["final_verdict"] = final
                return final
            page = publish_public.public_page_check(
                decision,
                page_fetcher=page_fetcher,
                attempts=publish_public.PUBLISH_RENDER_POLL_ATTEMPTS,
                delay_s=publish_public.PUBLISH_RENDER_POLL_DELAY_S,
            )
            ledger["public_page_check"] = page
            if page.get("ok"):
                final = "accepted"
                ledger["status"] = publish_status.CycleStatus.PUBLISHED.value
                ledger["published"] = 1
                ledger["published_topic"] = (
                    ledger.get("submitted_topic")
                    or (ledger.get("candidate") or {}).get("topic")
                )
                ledger["public_url"] = page.get("url")
            elif page.get("status") == "missing_public_url":
                final = "pending"
                ledger["status"] = publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value
                ledger["published"] = 0
                ledger["accepted_pending_public_url"] = True
                ledger.pop("publish_failure_reason", None)
            else:
                final = "rejected"
                ledger["status"] = publish_status.CycleStatus.PUBLIC_PAGE_NOT_RENDERED.value
                ledger["published"] = 0
                ledger["publish_failure_reason"] = "public_page_not_rendered"
        elif decision.get("decision") == "revise":
            final = "revise"
            ledger["status"] = publish_status.CycleStatus.REVIEWER_REVISE.value
        else:
            final = "rejected"
            ledger["status"] = publish_status.CycleStatus.REVIEWER_REJECTED.value
    ledger["submission_id"] = submission_id_value
    ledger["researka_decision"] = decision
    ledger["final_verdict"] = final
    return final


def poll_submission_decision(
    ledger: Json,
    *,
    submission_id_value: str,
    fetcher: DecisionFetcher,
    page_fetcher: PageFetcher,
    attempts: int,
    sleep_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    final = "pending"
    if attempts <= 0:
        ledger["decision_poll"] = {"attempts": 0, "final_verdict": final}
        return final
    for idx in range(attempts):
        if idx and sleep_seconds > 0:
            sleep(sleep_seconds)
        try:
            decision = fetcher(submission_id_value)
        except Exception as exc:  # pragma: no cover - network defensive path
            ledger["decision_check_error"] = {
                "error": type(exc).__name__,
                "detail": str(exc)[:180],
                "attempt": idx + 1,
            }
            return final
        final = apply_submission_decision(
            ledger,
            submission_id_value=submission_id_value,
            decision=decision,
            page_fetcher=page_fetcher,
        )
        ledger["decision_poll"] = {"attempts": idx + 1, "final_verdict": final}
        if final != "pending":
            return final
    return final
