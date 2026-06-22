"""Typed publish-cycle status helpers."""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

Json = dict[str, Any]


class CycleStatus(StrEnum):
    PUBLISHED = "published"
    SUBMITTED_TO_RESEARKA = "submitted_to_researka"
    NO_FRESH_CANDIDATE = "no_fresh_candidate"
    SUBMIT_RETRY_EXHAUSTED = "submit_retry_exhausted"
    CANDIDATE_REFRESH_FAILED = "candidate_refresh_failed"
    DOMAIN_DRY_RUN_ONLY = "domain_dry_run_only"
    SUBMIT_NOT_CONFIGURED = "submit_not_configured"
    COST_CAP_EXCEEDED = "cost_cap_exceeded"
    PREFLIGHT_QA_BLOCKED = "preflight_qa_blocked"
    HELD_RETRACTION_CHECK = "held_retraction_check"
    REVIEWER_REJECTED = "reviewer_rejected"
    REVIEWER_REVISE = "reviewer_revise"


class CandidateStatus(StrEnum):
    DUPLICATE_SUBMISSION_FINGERPRINT = "duplicate_submission_fingerprint"
    STALE_PUBLISH_VERDICT = "stale_publish_verdict"
    MISSING_ALPHA_MEMO = "missing_alpha_memo"
    AGENT_REPAIR_FAILED = "agent_repair_failed"
    MEMO_MISSING_FALSIFIER = "memo_missing_falsifier"
    CYCLE_FAILED_SUBMISSION = "cycle_failed_submission"
    HELD_RETRACTION_CHECK = "held_retraction_check"
    RECEIPT_SHAPE_MISMATCH = "receipt_shape_mismatch"
    EVIDENCE_MAP_BELOW_CITATION_FLOOR = "evidence_map_below_citation_floor"
    CORPUS_SOURCE_FLOOR_BELOW_MIN = "corpus_source_floor_below_min"
    MEMO_SOURCE_FLOOR_BELOW_MIN = "memo_source_floor_below_min"
    DIRECT_SOURCE_FLOOR_BELOW_MIN = "direct_source_floor_below_min"


SUBMIT_SUCCESS_STATUSES = frozenset({CycleStatus.PUBLISHED.value})
PENDING_SUCCESS_STATUSES = frozenset({CycleStatus.SUBMITTED_TO_RESEARKA.value})
EXHAUSTED_STATUSES = frozenset({
    CandidateStatus.DUPLICATE_SUBMISSION_FINGERPRINT.value,
    CandidateStatus.STALE_PUBLISH_VERDICT.value,
    CandidateStatus.MISSING_ALPHA_MEMO.value,
    CandidateStatus.AGENT_REPAIR_FAILED.value,
    CandidateStatus.MEMO_MISSING_FALSIFIER.value,
    CandidateStatus.CYCLE_FAILED_SUBMISSION.value,
    CandidateStatus.HELD_RETRACTION_CHECK.value,
    CandidateStatus.RECEIPT_SHAPE_MISMATCH.value,
    CandidateStatus.EVIDENCE_MAP_BELOW_CITATION_FLOOR.value,
})
TOPIC_EXHAUSTED_STATUSES = frozenset({
    CandidateStatus.DUPLICATE_SUBMISSION_FINGERPRINT.value,
    CandidateStatus.CYCLE_FAILED_SUBMISSION.value,
    CandidateStatus.HELD_RETRACTION_CHECK.value,
    CandidateStatus.RECEIPT_SHAPE_MISMATCH.value,
    CandidateStatus.EVIDENCE_MAP_BELOW_CITATION_FLOOR.value,
})
FINGERPRINT_EXHAUSTED_STATUSES = (
    TOPIC_EXHAUSTED_STATUSES | {
        CandidateStatus.AGENT_REPAIR_FAILED.value,
        CandidateStatus.STALE_PUBLISH_VERDICT.value,
    }
)
REFRESHABLE_SOURCE_FLOOR_STATUSES = frozenset({
    CandidateStatus.CORPUS_SOURCE_FLOOR_BELOW_MIN.value,
    CandidateStatus.MEMO_SOURCE_FLOOR_BELOW_MIN.value,
    CandidateStatus.DIRECT_SOURCE_FLOOR_BELOW_MIN.value,
})


def top_counts(values: Iterable[str], *, limit: int = 5) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit])


def queue_counts(queue: Json) -> Json:
    return {
        "ready_to_publish": len(queue.get("ready_to_publish") or []),
        "agent_repair_needed": (
            len(queue.get("agent_repair_needed") or [])
            + len(queue.get("needs_operator_review") or [])
        ),
        "curation_needed": len(queue.get("curation_needed") or []),
        "not_ready": len(queue.get("not_ready") or []),
    }


def next_action_for_status(status: str) -> str:
    if status in {CycleStatus.PUBLISHED.value, CycleStatus.SUBMITTED_TO_RESEARKA.value}:
        return "watch_decision_or_public_page"
    if status in {
        CycleStatus.NO_FRESH_CANDIDATE.value,
        CycleStatus.SUBMIT_RETRY_EXHAUSTED.value,
    }:
        return "refresh_or_expand_candidate_supply"
    if status == CycleStatus.CANDIDATE_REFRESH_FAILED.value:
        return "inspect_refresh_failure"
    if status in {
        CycleStatus.DOMAIN_DRY_RUN_ONLY.value,
        CycleStatus.SUBMIT_NOT_CONFIGURED.value,
        CycleStatus.COST_CAP_EXCEEDED.value,
    }:
        return "fix_runtime_configuration"
    if status in {
        CycleStatus.PREFLIGHT_QA_BLOCKED.value,
        CycleStatus.HELD_RETRACTION_CHECK.value,
    }:
        return "repair_candidate_quality"
    if status in {CycleStatus.REVIEWER_REJECTED.value, CycleStatus.REVIEWER_REVISE.value}:
        return "repair_researka_review_feedback"
    return "inspect_ledger"


def no_candidate_reason(considered: list[Json]) -> str:
    statuses = [str(row.get("status") or "") for row in considered if isinstance(row, dict)]
    if statuses and all(status == "duplicate_submission_fingerprint" for status in statuses):
        return "all candidates were duplicate submission fingerprints"
    if statuses and all(status == "cycle_exhausted_topic" for status in statuses):
        return "all candidates were topic/family exhausted"
    if "stale_publish_verdict" in statuses:
        return "selected candidate no longer matches the current publish verdict"
    if "evidence_map_below_citation_floor" in statuses:
        return "best evidence-map candidate was below citation floor"
    return "no eligible non-duplicate memo"


def publish_summary(ledger: Json) -> Json:
    considered = [r for r in ledger.get("considered") or [] if isinstance(r, dict)]
    attempts = [r for r in ledger.get("cycle_attempts") or [] if isinstance(r, dict)]
    blockers: list[str] = []
    for row in considered:
        blockers.append(str(row.get("status") or ""))
        for blocker in row.get("blockers") or []:
            blockers.append(str(blocker))
    page = ledger.get("public_page_check")
    return {
        "status": ledger.get("status"),
        "submitted": int(ledger.get("submitted") or 0),
        "published": int(ledger.get("published") or 0),
        "considered": len(considered),
        "attempts": len(attempts),
        "queue_counts": ledger.get("queue_counts") or {},
        "top_blockers": top_counts(blockers),
        "last_attempt_status": attempts[-1].get("status") if attempts else None,
        "public_url": ledger.get("public_url"),
        "public_page_status": page.get("status") if isinstance(page, dict) else None,
        "next_action": next_action_for_status(str(ledger.get("status") or "")),
    }


def cycle_exit_code(
    ledger: Json, *, submit: bool, allow_pending_success: bool = False,
) -> int:
    status = str(ledger.get("status") or "")
    if not submit:
        return 2 if status == CycleStatus.CANDIDATE_REFRESH_FAILED.value else 0
    if status in SUBMIT_SUCCESS_STATUSES or int(ledger.get("published") or 0) == 1:
        return 0
    if allow_pending_success and status in PENDING_SUCCESS_STATUSES:
        return 0
    return 2
