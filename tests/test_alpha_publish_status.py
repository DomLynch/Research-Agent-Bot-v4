"""Publish status policy tests."""
from __future__ import annotations

from scripts.alpha_publish_status import (
    CycleStatus,
    cycle_exit_code,
    next_action_for_status,
    no_candidate_reason,
    publish_summary,
    queue_counts,
)


def test_submit_exit_codes_fail_closed_for_zero_output_statuses() -> None:
    for status in (
        CycleStatus.NO_FRESH_CANDIDATE,
        CycleStatus.PREFLIGHT_QA_BLOCKED,
        CycleStatus.SUBMIT_RETRY_EXHAUSTED,
        CycleStatus.DOMAIN_DRY_RUN_ONLY,
        CycleStatus.CANDIDATE_REFRESH_FAILED,
    ):
        assert cycle_exit_code({"status": status.value, "published": 0}, submit=True) == 2


def test_submit_exit_codes_only_allow_pending_when_explicit() -> None:
    ledger = {"status": CycleStatus.SUBMITTED_TO_RESEARKA.value, "published": 0}

    assert cycle_exit_code(ledger, submit=True) == 2
    assert cycle_exit_code(ledger, submit=True, allow_pending_success=True) == 0


def test_terminal_publication_edge_statuses_have_operator_actions() -> None:
    assert (
        next_action_for_status(CycleStatus.DRY_RUN_SELECTED.value)
        == "submit_or_enable_live_mode"
    )
    assert (
        next_action_for_status(CycleStatus.DEDUPED_PUBLICATION.value)
        == "refresh_or_expand_candidate_supply"
    )
    for status in (
        CycleStatus.PUBLIC_PAGE_NOT_RENDERED,
        CycleStatus.DECISION_STALE_PENDING,
    ):
        assert next_action_for_status(status.value) == "sync_decision_or_public_page"


def test_publish_summary_contains_operator_blocker_fields() -> None:
    summary = publish_summary({
        "status": CycleStatus.NO_FRESH_CANDIDATE.value,
        "submitted": 0,
        "published": 0,
        "queue_counts": {"ready_to_publish": 1, "curation_needed": 2},
        "cycle_attempts": [{"status": "reviewer_revise"}],
        "considered": [
            {"status": "duplicate_submission_fingerprint"},
            {"status": "agent_repair_needed", "blockers": ["receipt_shape_mismatch"]},
        ],
        "public_url": "https://researka.org/alpha/example",
        "public_page_check": {"status": "not_rendered"},
    })

    assert summary["considered"] == 2
    assert summary["queue_counts"] == {"ready_to_publish": 1, "curation_needed": 2}
    assert summary["next_action"] == "refresh_or_expand_candidate_supply"
    assert summary["public_url"] == "https://researka.org/alpha/example"
    assert summary["public_page_status"] == "not_rendered"
    assert summary["top_blockers"] == {
        "agent_repair_needed": 1,
        "duplicate_submission_fingerprint": 1,
        "receipt_shape_mismatch": 1,
    }


def test_no_candidate_reason_reports_mixed_duplicate_exhaustion() -> None:
    assert no_candidate_reason([
        {"status": "duplicate_submission_fingerprint"},
        {"status": "duplicate_published_bundle"},
        {"status": "cycle_exhausted_topic"},
    ]) == "all candidates were duplicate, already published, or topic/family exhausted"


def test_queue_counts_include_legacy_operator_review_bucket() -> None:
    assert queue_counts({
        "ready_to_publish": [{}, {}],
        "agent_repair_needed": [{}],
        "needs_operator_review": [{}, {}],
        "curation_needed": [{}],
        "not_ready": [{}, {}],
    }) == {
        "ready_to_publish": 2,
        "agent_repair_needed": 3,
        "curation_needed": 1,
        "not_ready": 2,
    }
