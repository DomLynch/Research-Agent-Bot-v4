"""Typed publish-cycle status helpers."""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

Json = dict[str, Any]


class CycleStatus(StrEnum):
    STARTED = "started"
    PUBLISHED = "published"
    SUBMITTED_TO_RESEARKA = "submitted_to_researka"
    DRY_RUN_SELECTED = "dry_run_selected"
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
    DEDUPED_PUBLICATION = "deduped_publication"
    PUBLIC_PAGE_NOT_RENDERED = "public_page_not_rendered"
    DECISION_STALE_PENDING = "decision_stale_pending"


class DecisionVerdict(StrEnum):
    ACCEPTED = "accepted"
    PENDING = "pending"
    REJECT = "reject"
    REJECTED = "rejected"
    REVISE = "revise"
    STALE_PENDING = "stale_pending"


class CandidateStatus(StrEnum):
    DUPLICATE_SUBMISSION_FINGERPRINT = "duplicate_submission_fingerprint"
    STALE_PUBLISH_VERDICT = "stale_publish_verdict"
    MISSING_ALPHA_MEMO = "missing_alpha_memo"
    AGENT_REPAIR_FAILED = "agent_repair_failed"
    MEMO_MISSING_FALSIFIER = "memo_missing_falsifier"
    CYCLE_FAILED_SUBMISSION = "cycle_failed_submission"
    HELD_RETRACTION_CHECK = "held_retraction_check"
    RECEIPT_SHAPE_MISMATCH = "receipt_shape_mismatch"
    DUPLICATE_SOURCE_EVIDENCE = "duplicate_source_evidence"
    EVIDENCE_MAP_BELOW_CITATION_FLOOR = "evidence_map_below_citation_floor"
    EVIDENCE_MAP_SCOPE_MISMATCH = "evidence_map_scope_mismatch"
    CORPUS_SOURCE_FLOOR_BELOW_MIN = "corpus_source_floor_below_min"
    MEMO_SOURCE_FLOOR_BELOW_MIN = "memo_source_floor_below_min"
    DIRECT_SOURCE_FLOOR_BELOW_MIN = "direct_source_floor_below_min"


SUBMIT_SUCCESS_STATUSES = frozenset({CycleStatus.PUBLISHED.value})
PENDING_SUCCESS_STATUSES = frozenset({CycleStatus.SUBMITTED_TO_RESEARKA.value})
ZERO_OUTPUT_FAILURE_STATUSES = frozenset({
    CycleStatus.NO_FRESH_CANDIDATE.value,
    CycleStatus.SUBMIT_RETRY_EXHAUSTED.value,
    CycleStatus.CANDIDATE_REFRESH_FAILED.value,
    CycleStatus.DOMAIN_DRY_RUN_ONLY.value,
    CycleStatus.PREFLIGHT_QA_BLOCKED.value,
})
EXHAUSTED_STATUSES = frozenset({
    CandidateStatus.DUPLICATE_SUBMISSION_FINGERPRINT.value,
    CandidateStatus.STALE_PUBLISH_VERDICT.value,
    CandidateStatus.MISSING_ALPHA_MEMO.value,
    CandidateStatus.AGENT_REPAIR_FAILED.value,
    CandidateStatus.MEMO_MISSING_FALSIFIER.value,
    CandidateStatus.CYCLE_FAILED_SUBMISSION.value,
    CandidateStatus.HELD_RETRACTION_CHECK.value,
    CandidateStatus.RECEIPT_SHAPE_MISMATCH.value,
    CandidateStatus.DUPLICATE_SOURCE_EVIDENCE.value,
    CandidateStatus.EVIDENCE_MAP_BELOW_CITATION_FLOOR.value,
    CandidateStatus.EVIDENCE_MAP_SCOPE_MISMATCH.value,
})
TOPIC_EXHAUSTED_STATUSES = frozenset({
    CandidateStatus.DUPLICATE_SUBMISSION_FINGERPRINT.value,
    CandidateStatus.CYCLE_FAILED_SUBMISSION.value,
    CandidateStatus.HELD_RETRACTION_CHECK.value,
    CandidateStatus.RECEIPT_SHAPE_MISMATCH.value,
    CandidateStatus.DUPLICATE_SOURCE_EVIDENCE.value,
    CandidateStatus.EVIDENCE_MAP_BELOW_CITATION_FLOOR.value,
    CandidateStatus.EVIDENCE_MAP_SCOPE_MISMATCH.value,
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
    if status == CycleStatus.STARTED.value:
        return "building_current_publish_queue"
    if status in {CycleStatus.PUBLISHED.value, CycleStatus.SUBMITTED_TO_RESEARKA.value}:
        return "watch_decision_or_public_page"
    if status == CycleStatus.DRY_RUN_SELECTED.value:
        return "submit_or_enable_live_mode"
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
    if status == CycleStatus.DEDUPED_PUBLICATION.value:
        return "refresh_or_expand_candidate_supply"
    if status in {
        CycleStatus.PUBLIC_PAGE_NOT_RENDERED.value,
        CycleStatus.DECISION_STALE_PENDING.value,
    }:
        return "sync_decision_or_public_page"
    return "inspect_ledger"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _clean_external_resubmit_decision(decision: Any) -> bool:
    if not isinstance(decision, dict):
        return False
    notes = decision.get("notes") or decision.get("required_revisions") or []
    note_text = _norm(notes) if isinstance(notes, str) else " ".join(_norm(note) for note in notes)
    if (
        _norm(decision.get("decision")) != DecisionVerdict.REVISE.value
        or "external author must resubmit" not in note_text
    ):
        return False
    if any(
        decision.get(key) not in (None, "", [], {})
        for key in (
            "required_revisions",
            "major_issues",
            "minor_issues",
            "failed_checks",
            "gate_failures",
        )
    ):
        return False
    verdicts = {
        _norm(decision.get("claim_support_verdict")),
        _norm(decision.get("overclaim_verdict")),
        _norm(decision.get("synthesis_quality_verdict")),
    }
    return not verdicts & {"unsupported", "overclaim", "weak", "insufficient", "failed"}


def _terminal_resubmit_attempted(ledger: Json) -> bool:
    rows = list(ledger.get("source_literature_fallback_attempts") or [])
    fallback = ledger.get("source_literature_fallback")
    if isinstance(fallback, dict):
        rows.append(fallback)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _norm(row.get("terminal_resubmit_status")) in {"accepted", "queued"}:
            return True
        if any(
            row.get(key)
            for key in (
                "terminal_resubmit_queued",
                "terminal_resubmit_queued_job_id",
                "terminal_resubmit_poll_object_id",
                "terminal_resubmit_submission",
            )
        ):
            return True
    for row in ledger.get("cycle_attempts") or []:
        if not isinstance(row, dict):
            continue
        if _norm(row.get("pending_reason")) in {
            "terminal_resubmit_job_queued",
            "same_parent_terminal_resubmit_queued",
        }:
            return True
    return False


def platform_publish_handoff_blocked(ledger: Json) -> bool:
    return (
        str(ledger.get("status") or "") == CycleStatus.REVIEWER_REVISE.value
        and int(ledger.get("submitted") or 0) > 0
        and int(ledger.get("published") or 0) == 0
        and not ledger.get("public_url")
        and _clean_external_resubmit_decision(ledger.get("researka_decision"))
        and _terminal_resubmit_attempted(ledger)
    )


def effective_cycle_status(ledger: Json) -> str:
    status = str(ledger.get("status") or "")
    attempts = [r for r in ledger.get("cycle_attempts") or [] if isinstance(r, dict)]
    if attempts:
        latest = attempts[-1]
        latest_status = str(latest.get("status") or "")
        if latest_status in PENDING_SUCCESS_STATUSES and latest.get("pending_reason"):
            return latest_status
    return status


def no_candidate_reason(considered: list[Json]) -> str:
    statuses = [str(row.get("status") or "") for row in considered if isinstance(row, dict)]
    duplicate = CandidateStatus.DUPLICATE_SUBMISSION_FINGERPRINT.value
    if statuses and all(status == duplicate for status in statuses):
        return "all candidates were duplicate submission fingerprints"
    duplicate_exhaustion = {
        duplicate,
        "duplicate_published_bundle",
        "cycle_exhausted_topic",
    }
    repair_needed = {"agent_repair_needed", "needs_operator_review"}
    if (
        statuses
        and set(statuses) <= duplicate_exhaustion | repair_needed
        and set(statuses) & duplicate_exhaustion
        and set(statuses) & repair_needed
    ):
        return "fresh candidates were duplicate/exhausted; remaining candidates need agent repair"
    if statuses and set(statuses) <= duplicate_exhaustion:
        return "all candidates were duplicate, already published, or topic/family exhausted"
    if statuses and all(status == "cycle_exhausted_topic" for status in statuses):
        return "all candidates were topic/family exhausted"
    if CandidateStatus.STALE_PUBLISH_VERDICT.value in statuses:
        return "selected candidate no longer matches the current publish verdict"
    if CandidateStatus.EVIDENCE_MAP_BELOW_CITATION_FLOOR.value in statuses:
        return "best evidence-map candidate was below citation floor"
    if CandidateStatus.EVIDENCE_MAP_SCOPE_MISMATCH.value in statuses:
        return "best evidence-map candidate was too broad for one bounded map"
    if CandidateStatus.DUPLICATE_SOURCE_EVIDENCE.value in statuses:
        return "best candidate counted duplicate study evidence as independent sources"
    return "no eligible non-duplicate memo"


def publish_summary(ledger: Json) -> Json:
    considered = [r for r in ledger.get("considered") or [] if isinstance(r, dict)]
    attempts = [r for r in ledger.get("cycle_attempts") or [] if isinstance(r, dict)]
    blockers: list[str] = []
    for row in considered:
        blockers.append(str(row.get("status") or ""))
        for blocker in row.get("blockers") or []:
            blockers.append(str(blocker))
    for row in ledger.get("source_literature_fallback_attempts") or []:
        if not isinstance(row, dict):
            continue
        status_text = str(row.get("status") or "")
        reason_text = str(row.get("reason") or "")
        if status_text and status_text != "selected":
            blockers.append("source_literature_" + status_text)
        if reason_text and reason_text != "ok":
            blockers.append(reason_text)
    refresh = ledger.get("refresh_candidates")
    if isinstance(refresh, dict):
        for event in refresh.get("fullraw_probe_events") or []:
            if isinstance(event, dict) and event.get("status"):
                blockers.append("fullraw_" + str(event.get("status")))
    status = effective_cycle_status(ledger)
    handoff_blocked = platform_publish_handoff_blocked(ledger)
    if status and status not in SUBMIT_SUCCESS_STATUSES | PENDING_SUCCESS_STATUSES | {CycleStatus.STARTED.value}:
        blockers.append("platform_publish_handoff_blocked" if handoff_blocked else status)
    if (
        status == CycleStatus.STARTED.value
        and not considered
        and not attempts
        and int(ledger.get("submitted") or 0) == 0
        and int(ledger.get("published") or 0) == 0
    ):
        blockers.append("cycle_started_no_terminal_status")
    page = ledger.get("public_page_check")
    page_checks = page.get("checks") if isinstance(page, dict) else []
    page_status = None
    if isinstance(page_checks, list):
        for check in page_checks:
            if isinstance(check, dict) and check.get("http_status") is not None:
                page_status = check.get("http_status")
                if check.get("url") == ledger.get("public_url"):
                    break
    top_blockers = top_counts(blockers)
    next_action = (
        next_action_for_status(status)
        if status else str(ledger.get("next_action") or "inspect_ledger")
    )
    if (
        status == CycleStatus.CANDIDATE_REFRESH_FAILED.value
        and {"fullraw_probe_busy", "fullraw_complete_receipt_missing"} & set(top_blockers)
    ):
        next_action = "wait_for_fullraw_completion"
    if handoff_blocked:
        next_action = "fix_researka_publish_handoff_or_run_admin_publish_job"
    summary = {
        "status": status,
        "submitted": int(ledger.get("submitted") or 0),
        "published": int(ledger.get("published") or 0),
        "considered": len(considered),
        "attempts": len(attempts),
        "queue_counts": ledger.get("queue_counts") or {},
        "top_blockers": top_blockers,
        "last_attempt_status": attempts[-1].get("status") if attempts else None,
        "public_url": ledger.get("public_url"),
        "public_url_status": page_status,
        "public_page_status": page.get("status") if isinstance(page, dict) else None,
        "next_action": next_action,
    }
    for key in ("actionable_ready_to_publish", "non_actionable_ready_to_publish"):
        if key in ledger:
            summary[key] = int(ledger.get(key) or 0)
    return summary


def cycle_exit_code(
    ledger: Json, *, submit: bool, allow_pending_success: bool = False,
) -> int:
    status = str(ledger.get("status") or "")
    if not submit:
        return 2 if status in ZERO_OUTPUT_FAILURE_STATUSES else 0
    if status in SUBMIT_SUCCESS_STATUSES or int(ledger.get("published") or 0) == 1:
        return 0
    if allow_pending_success and status in PENDING_SUCCESS_STATUSES:
        return 0
    return 2
