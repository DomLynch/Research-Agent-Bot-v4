"""Daily ReseaRka alpha memo publish cycle.

Safe by default: builds/reads the publish queue, selects at most one
publishable memo, writes a daily ledger, and only calls Researka when
`--submit` is explicit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from agent.alpha_selector import accepted_shape_bonus
from agent.publish_tier import publish_verdict

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"
_PUBLICATION_PATH = _ROOT / "topic_packs" / "publication.toml"
_PUBLISH_TIER_PATH = _ROOT / "topic_packs" / "publish_tier.toml"

Json = dict[str, Any]
Fetcher = Callable[[str], Json]
DecisionFetcher = Callable[[str], Json]
Submitter = Callable[[Json], Json]
MemoRefresher = Callable[[Path, Json], bool]
QueueBuilder = Callable[[Path, bool], Json]
PageFetcher = Callable[[str], Json]
_SUBMIT_TOKEN_ENVS = (
    "RESEARKA_API_KEY_V4",
    "RESEARKA_API_TOKEN_V4",
    "RESEARKA_AGENT_TOKEN_V4",
    "RESEARCH_API_KEY_V4",
)


def _terminate_process_group(proc: subprocess.Popen[str], sig: signal.Signals | int) -> None:
    if proc.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(proc.pid, int(sig))


def _run_subprocess(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run child pipelines in one process group so stop/timeout kills descendants."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    previous: dict[signal.Signals, Any] = {}

    def forward_stop(signum: int, _frame: object) -> None:
        stop_signal = signal.Signals(signum)
        _terminate_process_group(proc, stop_signal)
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        if proc.poll() is None:
            _terminate_process_group(proc, signal.SIGKILL)
        signal.signal(stop_signal, previous.get(stop_signal, signal.SIG_DFL))
        os.kill(os.getpid(), signum)

    for managed_signal in (signal.SIGTERM, signal.SIGINT):
        previous[managed_signal] = signal.getsignal(managed_signal)
        signal.signal(managed_signal, forward_stop)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(proc, signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        if proc.poll() is None:
            _terminate_process_group(proc, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(
            args, timeout, output=stdout, stderr=stderr,
        ) from exc
    finally:
        for managed_signal, handler in previous.items():
            if signal.getsignal(managed_signal) is forward_stop:
                signal.signal(managed_signal, handler)
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _alpha_memo_int(name: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    if not isinstance(alpha, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(alpha.get(name))))
    return default


def _alpha_memo_float(name: str, default: float) -> float:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    if not isinstance(alpha, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0.0, float(str(alpha.get(name))))
    return default


def _publish_tier_int(name: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUBLISH_TIER_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    thresholds = data.get("thresholds") if isinstance(data, dict) else {}
    if not isinstance(thresholds, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(thresholds.get(name))))
    return default


_DEFAULT_MIN_SUBMIT_SOURCES = _alpha_memo_int("min_source_papers", 5)
_DEFAULT_MIN_DIRECT_SUBMIT_SOURCES = _alpha_memo_int("min_direct_source_papers", 2)
_DEFAULT_REFRESH_TOP = _alpha_memo_int("refresh_top", 1)
_DEFAULT_REFRESH_COOLDOWN_HOURS = _alpha_memo_float("refresh_cooldown_hours", 2.0)
_DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS = _alpha_memo_int(
    "published_topic_cooldown_days", 30,
)
_DEFAULT_DECISION_POLL_ATTEMPTS = _alpha_memo_int("decision_poll_attempts", 30)
_DEFAULT_DECISION_POLL_SECONDS = _alpha_memo_float("decision_poll_seconds", 10.0)
_DEFAULT_PENDING_DECISION_MAX_AGE_HOURS = _alpha_memo_float(
    "pending_decision_max_age_hours", 24.0,
)
_DEFAULT_MAX_REFRESH_BATCHES = 5
_DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT = _alpha_memo_int(
    "warm_backlog_derived_topic_limit", 250,
)
_REFRESH_TIMEOUT_SECONDS = 1200
# User-facing "3x" repair limit: one initial submit plus three repaired
# resubmits for the same evidence fingerprint.
_MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT = 4
_MAX_REJECT_ATTEMPTS_PER_FINGERPRINT = 2
_FINAL_DECISION_VERDICTS = {"accepted", "rejected", "revise", "stale_pending"}
_EXHAUSTED_STATUSES = {
    "duplicate_submission_fingerprint",
    "missing_alpha_memo",
    "agent_repair_failed",
    "memo_missing_falsifier",
    "cycle_failed_submission",
    "held_retraction_check",
}
_TOPIC_EXHAUSTED_STATUSES = {
    "duplicate_submission_fingerprint",
    "cycle_failed_submission",
    "held_retraction_check",
}
_FINGERPRINT_EXHAUSTED_STATUSES = _TOPIC_EXHAUSTED_STATUSES | {"agent_repair_failed"}
_REFRESHABLE_SOURCE_FLOOR_STATUSES = {
    "corpus_source_floor_below_min",
    "memo_source_floor_below_min",
    "direct_source_floor_below_min",
}
_AGENT_REPAIR_DECISIONS = {
    "agent_repair_needed", "needs_operator_review", "needs_operator_approval",
}


def _refresh_timeout_note(refresh: Json) -> bool:
    note = str(refresh.get("note") or "")
    return "TimeoutExpired:" in note or " timed out after " in note
_REPAIRABLE_REJECTION_REASONS = {
    "cited doi",
    "minimum_citations",
    "not verifiably grounded",
    "public_page_not_rendered",
    "recency_ratio",
    "required revision",
    "reviewer_revise",
    "scope reset",
    "source_bundle_schema",
    "title/abstract",
}
# Hard scope-reset rejects: the title/claims fundamentally miss the cited
# bundle, so the repair skips the cosmetic note and rebuilds the memo around
# the grounded source angle (a genuinely different, bundle-aligned memo instead
# of a byte-identical resubmit that gets duplicate-blocked).
_SCOPE_RESET_TERMS = (
    "scope reset", "not verifiably grounded", "provided source bundle",
    "source bundle", "title/abstract", "cited doi",
    "title and abstract", "actual scope",
    "narrow the title", "scope mismatch", "core evidence bundle",
    "cited bundle", "directly supported", "coherent research question",
    "irrelevant counter-evidence", "claim_evidence_alignment",
    "tighten the evidence receipts", "single systematic review",
    "single meta-analysis",
)
# Broader set adds clarification-level cues; these only trigger the cosmetic
# scope-clarification note in _apply_reviewer_revision_notes, not a full rebuild.
_GROUNDING_REJECT_TERMS = (
    *_SCOPE_RESET_TERMS,
    "context receipts", "contextual support", "single primary",
)
_REVISION_NARROWING_TERMS = (
    "bounded research signal", "hypothesis-generating", "hypothesis generating",
    "integrate evidence", "overstate tension", "overstate", "redundant",
    "repetition", "separate", "surprising section",
)
def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _ledger_stamp(now: dt.datetime | None = None) -> str:
    current = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z").replace(":", "-")


def _submit_token() -> tuple[str, str]:
    for name in _SUBMIT_TOKEN_ENVS:
        token = os.environ.get(name, "").strip()
        if token:
            return token, name
    return "", ""


def _topic(run: Path) -> str:
    return run.name.split("-evidence-", 1)[0]


def _can_recompute_verdict(run: Path) -> bool:
    return all(
        run.joinpath(name).exists()
        for name in ("alpha_memo.md", "opportunities_gate.json", "fact_lanes.json", "all_facts.json")
    )


def _verdict_for_run(run: Path) -> Json:
    if _can_recompute_verdict(run):
        return publish_verdict(run)
    data = _json(run / "publish_verdict.json", {})
    return data if isinstance(data, dict) else {}


def _write_publish_verdict(run: Path) -> Json:
    verdict = publish_verdict(run)
    _write_json(run / "publish_verdict.json", verdict)
    return verdict


def _current_selection_verdict(verdict: Json, root: Path) -> Json:
    run_dir = _run_path(root, verdict.get("run_dir"))
    if not run_dir.exists():
        return verdict
    current = _verdict_for_run(run_dir)
    if not current:
        return verdict
    private = {k: v for k, v in verdict.items() if str(k).startswith("_")}
    if verdict.get("_claim_cluster_candidate"):
        private.update({
            "topic": verdict.get("topic"),
            "receipt_expansion": verdict.get("receipt_expansion"),
            "subtopic_recommendations": verdict.get("subtopic_recommendations"),
        })
    return current | private


def _reload_verdict_after_memo_refresh(verdict: Json, run_dir: Path) -> Json:
    if not _can_recompute_verdict(run_dir):
        return verdict
    try:
        refreshed = _write_publish_verdict(run_dir)
    except (OSError, ValueError, TypeError, KeyError):
        return verdict
    repair_decision = verdict.get("_repair_decision")
    if repair_decision is not None:
        refreshed["_repair_decision"] = repair_decision
    if verdict.get("_claim_cluster_candidate"):
        refreshed.update({
            k: v for k, v in verdict.items()
            if str(k).startswith("_")
            or k in {"topic", "receipt_expansion", "subtopic_recommendations"}
        })
    return refreshed


def _build_queue(runs_root: Path, include_archive: bool) -> Json:
    """Build current verdicts without mutating run artifacts."""
    patterns = ["*-evidence-*/alpha_memo.md", "*-evidence-*/publish_verdict.json"]
    if include_archive:
        patterns += [
            "_archive/*/*-evidence-*/alpha_memo.md",
            "_archive/*/*-evidence-*/publish_verdict.json",
        ]
    latest: dict[str, Path] = {}
    for pattern in patterns:
        for path in runs_root.glob(pattern):
            run = path.parent
            topic = _topic(run)
            if topic not in latest or run.name > latest[topic].name:
                latest[topic] = run
    rows = [_verdict_for_run(run) for run in latest.values()]
    valid = [r for r in rows if isinstance(r, dict)]
    rank = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2}
    valid.sort(key=lambda r: (
        rank.get(str(r.get("publish_tier")), 9),
        -int(r.get("alpha_score") or 0),
        str(r.get("topic") or ""),
    ))
    return {
        "ready_to_publish": [
            r for r in valid if r.get("decision") == "ready_to_publish"
        ],
        "agent_repair_needed": [
            r for r in valid if r.get("decision") in _AGENT_REPAIR_DECISIONS
        ],
        "curation_needed": [
            r for r in valid if r.get("decision") == "curation_needed"
        ],
    }


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _source_key_from_paper(paper: Json) -> str:
    if not isinstance(paper, dict):
        return ""
    return _norm(
        paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
        or paper.get("paper_id") or paper.get("id") or paper.get("title")
    )


def _run_path(root: Path, run_ref: Any) -> Path:
    ref = Path(str(run_ref or ""))
    if ref.parts[:1] == ("runs",):
        return root.parent / ref if root.name == "runs" else root / ref
    return root / ref


def memo_fingerprint(verdict: Json) -> str:
    """Deterministic duplicate key, stable across headline rewording."""
    receipts = verdict.get("receipt_expansion") or {}
    axes_raw = verdict.get("axes")
    axes = axes_raw if isinstance(axes_raw, dict) else {}
    cluster_ids = verdict.get("_claim_cluster_fact_ids")
    cited_source = cluster_ids if isinstance(cluster_ids, list) else receipts.get("cited_bound_fact_ids", [])
    cited = sorted(str(x) for x in cited_source)[:3]
    papers = axes.get("source_papers", [])
    dois = sorted(
        _source_key_from_paper(p)
        for p in papers if isinstance(p, dict)
    )[:2]
    direction = "|".join([
        _norm(_selection_topic(verdict)),
        _norm(verdict.get("surface_type")),
        _norm(verdict.get("confidence_label")),
        _norm(verdict.get("publish_tier")),
    ])
    raw = json.dumps({
        "cited": cited,
        "dois": dois,
        "direction": direction,
    }, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _selection_topic(verdict: Json) -> str:
    return str(verdict.get("_claim_cluster_topic") or verdict.get("topic") or "")


def _needs_tension_enrichment(verdict: Json) -> bool:
    blockers = {str(x) for x in verdict.get("blockers") or []}
    return (
        verdict.get("decision") in _AGENT_REPAIR_DECISIONS
        and "weak_counter_consensus_tension" in blockers
        and not blockers - {"weak_counter_consensus_tension"}
    )


def _source_floor_repair_candidate(
    verdict: Json,
    *,
    source_count: int,
    direct_source_count: int,
    min_source_count: int,
    min_direct_source_count: int,
) -> bool:
    blockers = {str(x) for x in verdict.get("blockers") or []}
    source_floor_blockers = {"source_floor_below_min", "direct_source_floor_below_min"}
    repairable_blockers = source_floor_blockers | {
        "cross_domain_forced", "source_dispersion",
    }
    measured_floor_gap = (
        source_count < min_source_count
        or direct_source_count < min_direct_source_count
    )
    return (
        verdict.get("decision") in _AGENT_REPAIR_DECISIONS
        and (measured_floor_gap or bool(blockers & source_floor_blockers))
        and not blockers - repairable_blockers
    )


def _agent_repair_candidate(
    verdict: Json,
    *,
    source_count: int,
    direct_source_count: int,
    corpus_source_count: int,
    min_source_count: int,
    min_direct_source_count: int,
) -> bool:
    blockers = {str(x) for x in verdict.get("blockers") or []}
    repairable = {
        "cross_domain_forced",
        "source_dispersion",
        "weak_counter_consensus_tension",
        "source_floor_below_min",
        "direct_source_floor_below_min",
    }
    has_repair_signal = (
        direct_source_count < min_direct_source_count
        or bool(blockers & {"source_dispersion", "weak_counter_consensus_tension"})
    )
    has_available_supply = (
        source_count >= min_source_count
        or corpus_source_count >= min_source_count
    )
    return (
        verdict.get("decision") in _AGENT_REPAIR_DECISIONS
        and has_repair_signal
        and has_available_supply
        and not blockers - repairable
    )


def _agent_repair_decision(verdict: Json) -> Json:
    return {
        "decision": "revise",
        "agent_repair": True,
        "resubmission": {"allowed": True},
        "failure_category": "agentic_publish_gate_repair",
        "required_revisions": [
            "Rebuild around one bounded claim with the strongest direct A_core receipts.",
            "Keep context receipts secondary; do not submit until source and direct-source floors pass.",
            "If the parent topic cannot clear the gates, narrow to a source-coherent child claim.",
        ],
        "blockers": verdict.get("blockers") or [],
    }


def _with_agent_repair_contract(verdict: Json, decision: Json | None) -> Json:
    base = _agent_repair_decision(verdict)
    if isinstance(decision, dict):
        merged = base | decision
        merged["agent_repair"] = True
        resubmission = merged.get("resubmission")
        if not isinstance(resubmission, dict):
            merged["resubmission"] = {"allowed": True}
        return merged
    return base


def _rows(
    queue: Json, *, allow_tier2: bool, enrich_weak_tension: bool = False,
) -> list[Json]:
    out = list(queue.get("ready_to_publish") or [])
    repair_rows = list(queue.get("agent_repair_needed") or [])
    repair_rows.extend(queue.get("needs_operator_review") or [])
    if allow_tier2:
        out.extend(repair_rows)
    elif enrich_weak_tension:
        out.extend(
            r for r in repair_rows
            if isinstance(r, dict) and _needs_tension_enrichment(r)
        )
    return [r for r in out if isinstance(r, dict)]


def _cluster_child_topic(parent: str, label: str) -> str:
    child = "_".join(re.findall(r"[a-z0-9]+", f"{parent}_{label}".lower()))
    return child or parent


def _cluster_fact_ids(cluster: Json) -> list[str]:
    values = cluster.get("member_fact_ids") if isinstance(cluster, dict) else []
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        fid = str(value or "").strip()
        if fid and fid not in out:
            out.append(fid)
    return out


def _cluster_direct_source_count(verdict: Json, cluster_ids: list[str], root: Path) -> int:
    run_dir = _run_path(root, verdict.get("run_dir"))
    facts = _json(run_dir / "all_facts.json", [])
    lanes_raw = _json(run_dir / "fact_lanes.json", {})
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return 0
    lanes = {
        str(row.get("fact_id") or ""): str(row.get("lane") or "")
        for row in lanes_raw.get("verdicts", [])
        if isinstance(row, dict)
    }
    by_id = {
        str(fact.get("fact_id") or ""): fact
        for fact in facts if isinstance(fact, dict)
    }
    sources = {
        _source_key_from_fact(by_id[fid])
        for fid in cluster_ids
        if fid in by_id and lanes.get(fid) == "A_core"
    }
    return len({source for source in sources if source})


def _claim_cluster_repairable(verdict: Json, rec: Json) -> bool:
    decision = str(verdict.get("decision") or "")
    if decision in _AGENT_REPAIR_DECISIONS:
        return True
    blockers = {str(x) for x in verdict.get("blockers") or []}
    return (
        decision == "curation_needed"
        and rec.get("reason") == "source_coherent_child_cluster"
        and int(verdict.get("alpha_score") or 0)
        >= _publish_tier_int("review_min_alpha_score", 30)
        and not any(blocker.startswith("blocked_label:") for blocker in blockers)
    )


def _claim_cluster_candidates(
    rows: list[Json], runs_root: Path, *, min_direct_source_count: int,
) -> list[Json]:
    out: list[Json] = []
    seen: set[str] = set()
    for verdict in rows:
        parent = str(verdict.get("topic") or "").strip()
        rec = verdict.get("subtopic_recommendations")
        clusters = rec.get("clusters") if isinstance(rec, dict) else []
        if (
            not parent
            or not isinstance(rec, dict)
            or not isinstance(clusters, list)
            or not _claim_cluster_repairable(verdict, rec)
        ):
            continue
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            ids = _cluster_fact_ids(cluster)
            if (
                len(ids) < min_direct_source_count
                or _cluster_direct_source_count(verdict, ids, runs_root) < min_direct_source_count
            ):
                continue
            label = str(cluster.get("label") or "claim_cluster").strip("_")
            topic = _cluster_child_topic(parent, label)
            expansion = verdict.get("receipt_expansion")
            if not isinstance(expansion, dict):
                expansion = {}
            candidate = verdict | {
                "_claim_cluster_candidate": True,
                "_claim_cluster_fact_ids": ids,
                "_claim_cluster_topic": topic,
                "_parent_topic": parent,
                "topic": topic,
                "decision": "agent_repair_needed",
                "blockers": ["source_dispersion"],
                "receipt_expansion": expansion | {"cited_bound_fact_ids": ids},
                "subtopic_recommendations": {
                    "recommended": True,
                    "reason": "claim_cluster_first_selection",
                    "clusters": [cluster],
                },
            }
            fp = memo_fingerprint(candidate)
            if fp in seen:
                continue
            seen.add(fp)
            out.append(candidate)
    return out


def _with_repairable_candidates(queue: Json, runs_root: Path) -> Json:
    repairable = _repairable_candidate_verdicts(runs_root)
    if not repairable:
        return queue
    existing = {
        memo_fingerprint(row)
        for bucket in queue.values() if isinstance(bucket, list)
        for row in bucket if isinstance(row, dict)
    }
    additions = [row for row in repairable if memo_fingerprint(row) not in existing]
    if not additions:
        return queue
    merged = dict(queue)
    merged["ready_to_publish"] = additions + list(queue.get("ready_to_publish") or [])
    return merged


def _selection_approved(
    verdict: Json,
    root: Path,
    *,
    allow_tier2: bool,
    source_count: int,
    direct_source_count: int,
    min_source_count: int,
    min_direct_source_count: int,
) -> bool:
    _ = (
        root, allow_tier2, source_count, direct_source_count,
        min_source_count, min_direct_source_count,
    )
    return verdict.get("decision") == "ready_to_publish"


def _agent_repair_passed_submit_gates(
    verdict: Json,
    *,
    source_count: int,
    direct_source_count: int,
    min_source_count: int,
    min_direct_source_count: int,
) -> bool:
    blockers = {str(x) for x in verdict.get("blockers") or []}
    return (
        verdict.get("decision") in _AGENT_REPAIR_DECISIONS
        and source_count >= min_source_count
        and direct_source_count >= min_direct_source_count
        and blockers <= {"source_dispersion"}
    )


def _has_memo(verdict: Json, root: Path) -> bool:
    run_dir = _run_path(root, verdict.get("run_dir"))
    return (run_dir / "alpha_memo.md").exists()


def _has_falsifier(verdict: Json, root: Path) -> bool:
    """Submit gate: a memo must state what would disprove it before it ships."""
    from agent.signal_memo_writer import falsifier_present

    run_dir = _run_path(root, verdict.get("run_dir"))
    return falsifier_present(_read_text(run_dir / "alpha_memo.md"))


_REQUIRED_AUDIT_SIDECARS = (
    "claim_receipt_matrix.json",
    "typed_counter_evidence.json",
    "novelty_delta.json",
    "memo_audit.json",
)


def _missing_audit_sidecars(verdict: Json, root: Path) -> list[str]:
    run_dir = _run_path(root, verdict.get("run_dir"))
    missing: list[str] = []
    for name in _REQUIRED_AUDIT_SIDECARS:
        if not isinstance(_json(run_dir / name, None), (dict, list)):
            missing.append(name)
    return missing


def _refresh_alpha_memo(run_dir: Path, verdict: Json) -> bool:
    if "_archive" in run_dir.parts:
        return False
    if not (run_dir / "signal_post.md").exists():
        return False
    decision = verdict.get("_repair_decision")
    grounded = isinstance(decision, dict) and _is_grounding_reject(decision)
    structural = isinstance(decision, dict) and _resubmission_allowed(decision)
    from agent.signal_memo_writer import write_signal_memo

    # Direct text edits are only a compatibility shim for reviewer wording.
    # Every successful repair still regenerates the memo sidecars and verdict
    # below, so published text and machine-readable audit artifacts cannot drift.
    patched = (
        not grounded and not structural and isinstance(decision, dict)
        and _apply_reviewer_revision_notes(run_dir, decision)
    )
    if patched and not _can_recompute_verdict(run_dir):
        return True
    write_signal_memo(run_dir, publish_verdict=verdict, grounded=grounded)
    if _can_recompute_verdict(run_dir):
        _write_publish_verdict(run_dir)
    return True


def _is_grounding_reject(decision: Json) -> bool:
    """True when the reviewer demanded a scope reset — the title/claims must be
    rebuilt around the cited bundle. Such a repair regenerates in grounded mode
    instead of softening prose, or the resubmit is byte-identical."""
    if decision.get("decision") not in {"reject", "revise"}:
        return False
    if _resubmission_allowed(decision) and _low_claim_grounding_score(decision):
        return True
    notes = _norm(_revision_notes(decision))
    return any(term in notes for term in _SCOPE_RESET_TERMS)


def _low_claim_grounding_score(decision: Json) -> bool:
    scores = decision.get("rubric_scores")
    if not isinstance(scores, dict):
        return False
    for key in ("claim_evidence_alignment", "source_grounding", "synthesis_quality"):
        try:
            if int(scores.get(key, 0)) <= 2:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _is_explicit_scope_reset(decision: Json) -> bool:
    notes = _norm(_revision_notes(decision))
    return (
        "scope reset" in notes
        or "claim_evidence_alignment" in notes
        or "title thesis" in notes
        or "title and thesis" in notes
    )


def _revision_notes(decision: Json) -> str:
    parts: list[str] = []
    for key in ("failure_category", "review_summary", "notes"):
        values = decision.get(key)
        if isinstance(values, list):
            parts.extend(str(v) for v in values if v)
        elif values:
            parts.append(str(values))
    for key in ("required_revisions", "major_issues", "minor_issues", "failed_checks"):
        values = decision.get(key)
        if isinstance(values, list):
            parts.extend(str(v) for v in values if v)
    for gate in decision.get("gate_failures") or []:
        if isinstance(gate, dict):
            parts.extend(str(gate.get(k) or "") for k in ("name", "reason"))
    return " ".join(parts)


def _clean_title_claim(line: str) -> str:
    return re.sub(
        r":\s*(?:a\s+)?(?:systematic review|meta-analysis|meta analysis|"
        r"meta-regression|meta regression)"
        r"(?:\s+and\s+(?:meta-analysis|meta analysis|meta-regression|"
        r"meta regression))?(?:\s+of\s+[^.\n]+)?",
        "",
        line,
        flags=re.I,
    )


def _insert_scope_clarification(text: str) -> str:
    note = (
        "**Scope clarification:** The lead claim should be read as a narrow "
        "direct-source signal. Other cited sources provide context and boundary "
        "checks, not independent confirmation of the lead claim.\n"
    )
    if note in text:
        return text
    marker = "\n## Why this is surprising"
    if marker in text:
        return text.replace(marker, f"\n\n{note}{marker}", 1)
    return text.rstrip() + "\n\n" + note


def _soften_overclaim_language(text: str) -> str:
    replacements = (
        (r"\bnovel\s+(approach|framework|finding|method|insight|signal|claim)\b", r"bounded \1"),
        (r"\bunprecedented\s+", "unusual "),
        (r"\bgroundbreaking\s+", "notable "),
        (r"\bfirst\s+to\s+(show|demonstrate|report)\b", "reports"),
    )
    out = text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.I)
    return out


def _insert_reviewer_revision_note(text: str) -> str:
    note = (
        "**Reviewer revision:** The memo is narrowed to the direct receipts "
        "named below. Treat the lead claim as hypothesis-generating; broader "
        "context is background only unless it shares the same endpoint, "
        "comparator, and population.\n"
    )
    if note in text:
        return text
    marker = "\n## Why this is surprising"
    if marker in text:
        return text.replace(marker, f"\n\n{note}{marker}", 1)
    return text.rstrip() + "\n\n" + note


def _soften_surprise_language(text: str) -> str:
    return re.sub(r"(?im)^Real tension:", "Bounded signal:", text)


def _apply_reviewer_revision_notes(run_dir: Path, decision: Json) -> bool:
    if decision.get("decision") not in {"reject", "revise"}:
        return False
    notes = _revision_notes(decision)
    if not notes:
        return False
    path = run_dir / "alpha_memo.md"
    with suppress(OSError):
        original = path.read_text(encoding="utf-8")
        revised = original
        notes_norm = _norm(notes)
        if "title" in notes_norm and any(
            term in notes_norm
            for term in (
                "systematic review",
                "meta-analysis",
                "meta analysis",
                "meta-regression",
                "meta regression",
            )
        ):
            lines = []
            for line in revised.splitlines():
                if line.startswith("**Headline:**") or line.startswith("- **Suggested citation:**"):
                    line = _clean_title_claim(line)
                lines.append(line)
            revised = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
        if any(term in notes_norm for term in _GROUNDING_REJECT_TERMS):
            revised = _insert_scope_clarification(revised)
        if any(term in notes_norm for term in _REVISION_NARROWING_TERMS):
            revised = _insert_reviewer_revision_note(revised)
            revised = _soften_surprise_language(revised)
        if any(
            term in notes_norm
            for term in (
                "unsupported_novelty",
                "novel",
                "overclaim",
                "unprecedented",
                "groundbreaking",
                "first to",
            )
        ):
            revised = _soften_overclaim_language(revised)
        if revised != original:
            path.write_text(revised, encoding="utf-8")
            return True
    return False


def _seen_submission_fingerprints(path: Path) -> set[str]:
    data = _json(path, [])
    if isinstance(data, list):
        return {str(x.get("fingerprint")) for x in data if isinstance(x, dict)}
    return set()


def _same_memo_seen(path: Path, fingerprint: str, memo_sha256: str) -> bool:
    data = _json(path, [])
    if not isinstance(data, list):
        return False
    for row in data:
        if not isinstance(row, dict) or row.get("fingerprint") != fingerprint:
            continue
        if memo_sha256:
            if row.get("memo_sha256") == memo_sha256:
                return True
        else:
            return True
    return False


def _record_submission_attempt(
    path: Path,
    *,
    date: str,
    candidate: Json,
    runs_root: Path,
    submission_id: str = "",
    submit_status: str = "",
) -> None:
    records = _json(path, [])
    if not isinstance(records, list):
        records = []
    record = {
        "date": date,
        "topic": candidate.get("topic"),
        "run_dir": candidate.get("run_dir"),
        "fingerprint": candidate.get("memo_fingerprint"),
        "memo_sha256": _memo_sha256(candidate, runs_root),
        "submission_id": submission_id,
    }
    if submit_status:
        record["submit_status"] = submit_status
    records.append(record)
    _write_json(path, records)


def _submission_record_patch(ledger: Json) -> Json:
    patch: Json = {}
    for key in (
        "final_verdict",
        "status",
        "published",
        "public_url",
        "publish_failure_reason",
    ):
        value = ledger.get(key)
        if value not in (None, ""):
            patch[key] = value
    return patch


def _stamp_to_utc(value: Any) -> dt.datetime | None:
    match = re.search(
        r"(\d{4}-\d{2}-\d{2})[Tt](\d{2})[-:](\d{2})[-:](\d{2})",
        str(value or ""),
    )
    if not match:
        return None
    date, hour, minute, second = match.groups()
    try:
        year, month, day = (int(part) for part in date.split("-"))
        return dt.datetime(
            year, month, day, int(hour), int(minute), int(second), tzinfo=dt.UTC,
        )
    except ValueError:
        return None


def _stale_pending_decision(
    ledger: Json,
    *,
    stamp: Any,
    now: dt.datetime,
    max_age_hours: float,
) -> bool:
    if max_age_hours <= 0:
        return False
    started = _stamp_to_utc(ledger.get("date") or stamp)
    if started is None:
        return False
    return (now - started).total_seconds() >= max_age_hours * 3600


def _mark_stale_pending_decision(ledger: Json, *, max_age_hours: float) -> None:
    ledger["status"] = "decision_stale_pending"
    ledger["final_verdict"] = "stale_pending"
    ledger["published"] = 0
    ledger["publish_failure_reason"] = "decision_pending_timeout"
    ledger["decision_pending_timeout_hours"] = max_age_hours


def _merge_submission_record(row: Json, patch: Json) -> bool:
    changed = False
    for key, value in patch.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


def _memo_sha256(verdict: Json, root: Path) -> str:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    return hashlib.sha256(memo.encode("utf-8")).hexdigest() if memo else ""


def _memo_headline_mismatch(verdict: Json, root: Path) -> bool:
    expected = str(verdict.get("headline") or "").strip()
    if not expected:
        return False
    run_dir = _run_path(root, verdict.get("run_dir"))
    return _memo_headline(_read_text(run_dir / "alpha_memo.md")) != expected


def _memo_self_counter_signal(verdict: Json, root: Path) -> bool:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    if "**Selected angle:** `counter_signal`" not in memo:
        return False
    first_receipt = next(iter(_memo_receipt_ids(memo, ("Evidence",))), "")
    if not first_receipt:
        return False
    audit = _json(run_dir / "memo_audit.json", {})
    contradictions = audit.get("contradiction_receipts") if isinstance(audit, dict) else []
    return any(
        isinstance(item, dict) and str(item.get("fact_id") or "") == first_receipt
        for item in contradictions or []
    )


def _fingerprint_attempt_count(path: Path, fingerprint: str) -> int:
    data = _json(path, [])
    if not isinstance(data, list):
        return 0
    return sum(
        1
        for row in data
        if isinstance(row, dict)
        and row.get("fingerprint") == fingerprint
    )


def _repairable_rejected_fingerprints(ledger_dir: Path) -> set[str]:
    retryable: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        for fp, _run_ref, _decision in _repairable_submission_records(ledger):
            retryable.add(fp)
    return retryable


def _repairable_decisions_by_fingerprint(ledger_dir: Path) -> dict[str, Json]:
    retryable: dict[str, Json] = {}
    for path in sorted(ledger_dir.glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        for fp, _run_ref, decision in _repairable_submission_records(ledger):
            if fp in retryable:
                continue
            retryable[fp] = decision
    return retryable


def _repairable_candidate_verdicts(runs_root: Path) -> list[Json]:
    verdicts: list[Json] = []
    seen: set[str] = set()
    for path in sorted((runs_root / "_daily_ledger").glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        for fp, run_ref, _decision in _repairable_submission_records(ledger):
            if fp in seen:
                continue
            run_dir = _run_path(runs_root, run_ref)
            verdict = _json(run_dir / "publish_verdict.json", {})
            if not isinstance(verdict, dict) or not verdict:
                continue
            seen.add(fp)
            verdicts.append(verdict)
    return verdicts


def _repairable_submission_records(ledger: Json) -> list[tuple[str, Any, Json]]:
    records: list[tuple[str, Any, Json]] = []
    decision = ledger.get("researka_decision")
    candidate = ledger.get("candidate")
    if (
        isinstance(decision, dict)
        and isinstance(candidate, dict)
        and _repairable_rejection(decision)
    ):
        fp = str(candidate.get("fingerprint") or "")
        if fp:
            records.append((fp, candidate.get("run_dir"), decision))
    for attempt in ledger.get("cycle_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        decision = attempt.get("researka_decision")
        if not isinstance(decision, dict) or not _repairable_rejection(decision):
            continue
        fp = str(attempt.get("fingerprint") or "")
        if fp:
            records.append((fp, attempt.get("run_dir"), decision))
    return records


def _accepted_shape_profiles(runs_root: Path, *, limit: int = 25) -> list[Json]:
    profiles: list[Json] = []
    ledger_dir = runs_root / "_daily_ledger"
    for path in sorted(ledger_dir.glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or ledger.get("final_verdict") != "accepted":
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        fp = str(candidate.get("fingerprint") or "")
        profile: Json = {}
        run_dir = _run_path(runs_root, candidate.get("run_dir"))
        verdict = _json(run_dir / "publish_verdict.json", {})
        if isinstance(verdict, dict):
            profile.update(verdict)
        for row in ledger.get("considered") or []:
            if isinstance(row, dict) and (not fp or row.get("fingerprint") == fp):
                profile.update(row)
                break
        if profile:
            profiles.append(profile)
        if len(profiles) >= limit:
            break
    return profiles


def _recently_published_topics(ledger_dir: Path, *, days: int) -> set[str]:
    cutoff = time.time() - (max(0, days) * 86400)
    topics: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        with suppress(OSError):
            if path.stat().st_mtime < cutoff:
                continue
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        if ledger.get("final_verdict") != "accepted" and ledger.get("published") != 1:
            continue
        topic = (
            ledger.get("published_topic")
            or ledger.get("submitted_topic")
            or (ledger.get("candidate") or {}).get("topic")
        )
        if topic:
            topics.add(str(topic))
    return topics


def _repairable_rejection(decision: Json) -> bool:
    support = str(decision.get("claim_support_verdict") or "").lower()
    if (
        decision.get("decision") == "reject"
        and support == "unsupported"
        and _low_claim_grounding_score(decision)
    ):
        return False
    if _resubmission_allowed(decision):
        return True
    if decision.get("decision") == "revise":
        return support != "partially_supported"
    if decision.get("decision") == "reject" and support == "partially_supported":
        return False
    if decision.get("decision") == "reject" and support == "unsupported":
        return False
    reasons = {
        str(decision.get("failure_category") or ""),
        *(str(x) for x in decision.get("failed_checks") or []),
    }
    for gate in decision.get("gate_failures") or []:
        if isinstance(gate, dict):
            reasons.add(str(gate.get("name") or ""))
            reasons.add(str(gate.get("reason") or ""))
    text = " ".join(reasons).lower()
    text = f"{text} {_revision_notes(decision).lower()}"
    return any(reason in text for reason in _REPAIRABLE_REJECTION_REASONS)


def _submission_attempt_budget(decision: Any) -> int:
    if isinstance(decision, dict) and decision.get("decision") == "reject":
        return _MAX_REJECT_ATTEMPTS_PER_FINGERPRINT
    return _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT


def _repair_attempt_limit(decision: Any) -> int:
    budget = _submission_attempt_budget(decision)
    if (
        isinstance(decision, dict)
        and decision.get("decision") == "reject"
        and _resubmission_allowed(decision)
    ):
        return budget + 1
    return budget


def _retry_after_rejection(
    fingerprint: str,
    *,
    attempt_count: int,
    retryable: set[str],
    decisions: dict[str, Json],
) -> bool:
    return (
        fingerprint in retryable
        and attempt_count < _repair_attempt_limit(decisions.get(fingerprint))
    )


def _resubmission_allowed(decision: Json) -> bool:
    resubmission = decision.get("resubmission")
    return isinstance(resubmission, dict) and resubmission.get("allowed") is True


def _repairable_ledger(ledger: Json) -> bool:
    decision = ledger.get("researka_decision")
    if isinstance(decision, dict) and _repairable_rejection(decision):
        return True
    page = ledger.get("public_page_check")
    return (
        isinstance(page, dict)
        and str(page.get("status") or "") in {"missing_public_url", "not_rendered", "error"}
    )


def _source_count(verdict: Json, root: Path | None = None) -> int:
    if root is not None:
        papers = _memo_source_papers(verdict, root)
        if papers:
            return len(papers)
    return _source_count_from_verdict(verdict)


def _memo_receipt_ids(
    text: str,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
) -> list[str]:
    names = "|".join(re.escape(name) for name in section_names)
    sections = re.findall(
        rf"^## (?:{names}) receipts\n\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.M | re.S,
    )
    section = "\n".join(sections)
    seen: set[str] = set()
    out: list[str] = []
    for fid in re.findall(r"`fact_id=([^`\s]+)`", section):
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def _memo_receipt_lanes(
    text: str,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
) -> dict[str, str]:
    names = "|".join(re.escape(name) for name in section_names)
    sections = re.findall(
        rf"^## (?:{names}) receipts\n\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.M | re.S,
    )
    lanes: dict[str, str] = {}
    for fid, lane in re.findall(
        r"`fact_id=([^`\s]+)`\s+\(`([^`]+)`\)",
        "\n".join(sections),
    ):
        lanes.setdefault(fid, lane)
    return lanes


def _source_key_from_fact(fact: Json) -> str:
    paper = fact.get("source_paper") or {}
    # Identity order: DOI > PMID > PMCID > DB paper id > title. A blank key is
    # NOT a source — never collapse identifier-less papers into one phantom
    # source (that under-counts unique sources and can sink a topic below floor).
    return _source_key_from_paper(paper)


def _memo_source_papers(
    verdict: Json,
    root: Path,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
    lane_names: set[str] | None = None,
) -> list[Json]:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    ids = _memo_receipt_ids(memo, section_names)
    if not ids:
        return []
    facts = _json(run_dir / "all_facts.json", [])
    if not isinstance(facts, list):
        return []
    by_id = {
        str(f.get("fact_id") or ""): f
        for f in facts if isinstance(f, dict)
    }
    lanes: dict[str, str] = {}
    if lane_names is not None:
        lanes_raw = _json(run_dir / "fact_lanes.json", {})
        if isinstance(lanes_raw, dict):
            lanes = {
                str(row.get("fact_id") or ""): str(row.get("lane") or "")
                for row in lanes_raw.get("verdicts", [])
                if isinstance(row, dict)
            }
        if not lanes:
            lanes = _memo_receipt_lanes(memo, section_names)
    seen: set[str] = set()
    papers: list[Json] = []
    for fid in ids:
        if lane_names is not None and lanes.get(fid) not in lane_names:
            continue
        fact = by_id.get(fid) or {}
        key = _source_key_from_fact(fact)
        if not key or key in seen:
            continue
        seen.add(key)
        paper = fact.get("source_paper") or {}
        if isinstance(paper, dict):
            papers.append({
                "doi": str(paper.get("doi") or ""),
                "title": str(paper.get("title") or ""),
                "journal": str(paper.get("journal") or ""),
                "url": paper.get("url") or paper.get("source_url"),
                "year": paper.get("year"),
                "is_retracted": bool(paper.get("is_retracted")),
            })
    return papers


def _direct_source_count(verdict: Json, root: Path) -> int:
    return len(_memo_source_papers(verdict, root, ("Evidence",), {"A_core"}))


def _memo_headline(memo: str) -> str:
    match = re.search(r"^\*\*Headline:\*\*\s*(.+?)\s*$", memo, flags=re.M)
    return match.group(1).strip() if match else ""


def _year(value: Any) -> int | None:
    try:
        year = int(str(value))
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 3000 else None


def _evidence_type(paper: Json) -> str:
    title = _norm(paper.get("title"))
    if "review" in title or "meta-analysis" in title or "meta analysis" in title:
        return "review"
    return "primary"


def _source_bundle(papers: list[Json]) -> list[Json]:
    bundle: list[Json] = []
    for paper in papers:
        title = str(paper.get("title") or "").strip()
        if not title:
            continue
        bundle.append({
            "title": title,
            "url": paper.get("url") or None,
            "doi": str(paper.get("doi") or "").strip() or None,
            "year": _year(paper.get("year")),
            "evidence_type": _evidence_type(paper),
        })
    return bundle


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _source_count_from_verdict(verdict: Json) -> int:
    axes_raw = verdict.get("axes")
    axes = axes_raw if isinstance(axes_raw, dict) else {}
    papers = axes.get("source_papers") or []
    if isinstance(papers, list):
        keys = {
            _source_key_from_paper(p)
            for p in papers if isinstance(p, dict)
        }
        if keys:
            return len([k for k in keys if k])
    for count in (axes.get("source_count"), axes.get("selected_count")):
        if count is None:
            continue
        with suppress(TypeError, ValueError):
            return int(str(count))
    return 0


def _corpus_source_count(verdict: Json, root: Path) -> int:
    run_dir = _run_path(root, verdict.get("run_dir"))
    facts = _json(run_dir / "all_facts.json", [])
    lanes_raw = _json(run_dir / "fact_lanes.json", {})
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return _source_count_from_verdict(verdict)
    lanes = {
        str(row.get("fact_id") or ""): str(row.get("lane") or "")
        for row in lanes_raw.get("verdicts", [])
        if isinstance(row, dict)
    }
    sources = {
        _source_key_from_fact(fact)
        for fact in facts
        if isinstance(fact, dict)
        and lanes.get(str(fact.get("fact_id") or "")) in {"A_core", "B_context"}
    }
    return len({s for s in sources if s})


def select_candidate(
    queue: Json,
    *,
    runs_root: Path,
    submitted_path: Path,
    allow_tier2: bool = False,
    min_source_count: int = 0,
    min_direct_source_count: int = 0,
    memo_refresher: MemoRefresher | None = None,
    blocked_fingerprints: set[str] | None = None,
    blocked_topics: set[str] | None = None,
    accepted_shape_profiles: list[Json] | None = None,
    retryable_fingerprints: set[str] | None = None,
    retry_decision_overrides: dict[str, Json] | None = None,
) -> tuple[Json | None, list[Json]]:
    seen = _seen_submission_fingerprints(submitted_path)
    retryable = _repairable_rejected_fingerprints(submitted_path.parent)
    retry_decisions = _repairable_decisions_by_fingerprint(submitted_path.parent)
    retryable.update(retryable_fingerprints or set())
    retry_decisions.update(retry_decision_overrides or {})
    blocked = blocked_fingerprints or set()
    topic_blocked = blocked_topics or set()
    shape_profiles = accepted_shape_profiles or []
    considered: list[Json] = []
    rows = _rows(
        queue, allow_tier2=allow_tier2,
        enrich_weak_tension=memo_refresher is not None,
    )
    cluster_rows = rows + [
        r for r in queue.get("curation_needed") or [] if isinstance(r, dict)
    ]
    candidates = sorted(
        _claim_cluster_candidates(
            cluster_rows, runs_root, min_direct_source_count=min_direct_source_count,
        ) + rows,
        key=lambda r: (
            0 if r.get("decision") == "ready_to_publish"
            else 1 if r.get("_claim_cluster_candidate") else 2,
            -(int(r.get("alpha_score") or 0) + accepted_shape_bonus(r, shape_profiles)),
            str(r.get("topic") or ""),
        ),
    )
    for verdict in candidates:
        raw_fp = memo_fingerprint(verdict)
        if (
            raw_fp not in seen
            and raw_fp not in retry_decisions
            and not verdict.get("_claim_cluster_candidate")
        ):
            verdict = _current_selection_verdict(verdict, runs_root)
        fp = memo_fingerprint(verdict)
        source_count = _source_count(verdict, runs_root)
        direct_source_count = _direct_source_count(verdict, runs_root)
        corpus_source_count = _corpus_source_count(verdict, runs_root)
        shape_bonus = accepted_shape_bonus(verdict, shape_profiles)
        status = "eligible"
        memo_refreshed = False
        retry_fingerprint_unchanged = False
        has_memo = _has_memo(verdict, runs_root)
        memo_sha256 = _memo_sha256(verdict, runs_root) if has_memo else ""
        approved = (
            has_memo
            and (
                _selection_approved(
                    verdict,
                    runs_root,
                    allow_tier2=allow_tier2,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
                or _agent_repair_passed_submit_gates(
                    verdict,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
            )
        )
        cycle_blocked = fp in blocked
        exhausted_topic = _selection_topic(verdict) in topic_blocked
        attempt_count = _fingerprint_attempt_count(submitted_path, fp)
        retry_after_rejection = _retry_after_rejection(
            fp,
            attempt_count=attempt_count,
            retryable=retryable,
            decisions=retry_decisions,
        )
        retry_budget_exhausted = (
            fp in seen
            and attempt_count >= _repair_attempt_limit(retry_decisions.get(fp))
        )
        duplicate_without_retry = fp in seen and not retry_after_rejection
        agent_repair = (
            not duplicate_without_retry
            and _agent_repair_candidate(
                verdict,
                source_count=source_count,
                direct_source_count=direct_source_count,
                corpus_source_count=corpus_source_count,
                min_source_count=min_source_count,
                min_direct_source_count=min_direct_source_count,
            )
        )
        if (
            not cycle_blocked
            and not exhausted_topic
            and not retry_budget_exhausted
            and has_memo
            and (
                approved
                or agent_repair
                or _source_floor_repair_candidate(
                    verdict,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
            )
            and (
                source_count < min_source_count
                or direct_source_count < min_direct_source_count
                or agent_repair
            )
            and (
                corpus_source_count >= min_source_count
                or source_count >= min_source_count
            )
            and memo_refresher
        ):
            run_dir = _run_path(runs_root, verdict.get("run_dir"))
            repair_decision = retry_decisions.get(fp)
            if agent_repair:
                repair_decision = _with_agent_repair_contract(verdict, repair_decision)
            refresh_verdict = verdict | {"_repair_decision": repair_decision}
            retry_fp = fp
            retry_memo_sha256 = memo_sha256
            memo_refreshed = memo_refresher(run_dir, refresh_verdict)
            if memo_refreshed:
                verdict = _reload_verdict_after_memo_refresh(refresh_verdict, run_dir)
                fp = memo_fingerprint(verdict)
                memo_sha256 = _memo_sha256(verdict, runs_root)
                if retry_after_rejection and fp == retry_fp and memo_sha256 == retry_memo_sha256:
                    retry_fingerprint_unchanged = True
                source_count = _source_count(verdict, runs_root)
                direct_source_count = _direct_source_count(verdict, runs_root)
                corpus_source_count = _corpus_source_count(verdict, runs_root)
                approved = _selection_approved(
                    verdict,
                    runs_root,
                    allow_tier2=allow_tier2,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
                approved = approved or _agent_repair_passed_submit_gates(
                    verdict,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
                cycle_blocked = fp in blocked
                attempt_count = _fingerprint_attempt_count(submitted_path, fp)
                retry_after_rejection = _retry_after_rejection(
                    fp,
                    attempt_count=attempt_count,
                    retryable=retryable,
                    decisions=retry_decisions,
                )
                agent_repair = False
        if (
            not cycle_blocked
            and not exhausted_topic
            and not duplicate_without_retry
            and not retry_budget_exhausted
            and has_memo
            and approved
            and memo_refresher
            and (
                _memo_headline_mismatch(verdict, runs_root)
                or _memo_self_counter_signal(verdict, runs_root)
            )
        ):
            run_dir = _run_path(runs_root, verdict.get("run_dir"))
            refresh_verdict = verdict | {"_repair_decision": retry_decisions.get(fp)}
            memo_refreshed = memo_refresher(run_dir, refresh_verdict)
            if memo_refreshed:
                verdict = _reload_verdict_after_memo_refresh(refresh_verdict, run_dir)
                fp = memo_fingerprint(verdict)
                source_count = _source_count(verdict, runs_root)
                direct_source_count = _direct_source_count(verdict, runs_root)
                corpus_source_count = _corpus_source_count(verdict, runs_root)
                memo_sha256 = _memo_sha256(verdict, runs_root)
                approved = _selection_approved(
                    verdict,
                    runs_root,
                    allow_tier2=allow_tier2,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
                cycle_blocked = fp in blocked
                attempt_count = _fingerprint_attempt_count(submitted_path, fp)
                retry_after_rejection = _retry_after_rejection(
                    fp,
                    attempt_count=attempt_count,
                    retryable=retryable,
                    decisions=retry_decisions,
                )
        if (
            not cycle_blocked
            and not exhausted_topic
            and not duplicate_without_retry
            and not retry_budget_exhausted
            and has_memo
            and memo_refresher
            and _needs_tension_enrichment(verdict)
        ):
            run_dir = _run_path(runs_root, verdict.get("run_dir"))
            memo_refreshed = memo_refresher(run_dir, verdict)
            if memo_refreshed:
                verdict = _write_publish_verdict(run_dir)
                fp = memo_fingerprint(verdict)
                source_count = _source_count(verdict, runs_root)
                direct_source_count = _direct_source_count(verdict, runs_root)
                corpus_source_count = _corpus_source_count(verdict, runs_root)
                memo_sha256 = _memo_sha256(verdict, runs_root)
                approved = _selection_approved(
                    verdict,
                    runs_root,
                    allow_tier2=allow_tier2,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
                cycle_blocked = fp in blocked
                attempt_count = _fingerprint_attempt_count(submitted_path, fp)
                retry_after_rejection = _retry_after_rejection(
                    fp,
                    attempt_count=attempt_count,
                    retryable=retryable,
                    decisions=retry_decisions,
                )
        missing_audit_sidecars: list[str] = []
        if exhausted_topic:
            status = "cycle_exhausted_topic"
        elif cycle_blocked:
            status = "cycle_failed_submission"
        elif (fp in seen and not retry_after_rejection) or retry_fingerprint_unchanged:
            status = "duplicate_submission_fingerprint"
        elif not has_memo:
            status = "missing_alpha_memo"
        elif not approved:
            status = "agent_repair_failed" if memo_refreshed else "agent_repair_needed"
        elif not _has_falsifier(verdict, runs_root):
            status = "memo_missing_falsifier"
        else:
            missing_audit_sidecars = _missing_audit_sidecars(verdict, runs_root)
            if missing_audit_sidecars and memo_refresher and not memo_refreshed:
                run_dir = _run_path(runs_root, verdict.get("run_dir"))
                refresh_verdict = verdict | {"_repair_decision": retry_decisions.get(fp)}
                memo_refreshed = memo_refresher(run_dir, refresh_verdict)
                if memo_refreshed:
                    verdict = _reload_verdict_after_memo_refresh(refresh_verdict, run_dir)
                    fp = memo_fingerprint(verdict)
                    source_count = _source_count(verdict, runs_root)
                    direct_source_count = _direct_source_count(verdict, runs_root)
                    corpus_source_count = _corpus_source_count(verdict, runs_root)
                    memo_sha256 = _memo_sha256(verdict, runs_root)
                    approved = _selection_approved(
                        verdict,
                        runs_root,
                        allow_tier2=allow_tier2,
                        source_count=source_count,
                        direct_source_count=direct_source_count,
                        min_source_count=min_source_count,
                        min_direct_source_count=min_direct_source_count,
                    )
                    cycle_blocked = fp in blocked
                    attempt_count = _fingerprint_attempt_count(submitted_path, fp)
                    retry_after_rejection = _retry_after_rejection(
                        fp,
                        attempt_count=attempt_count,
                        retryable=retryable,
                        decisions=retry_decisions,
                    )
                    missing_audit_sidecars = _missing_audit_sidecars(verdict, runs_root)
            if status == "eligible" and retry_after_rejection and memo_refresher and not memo_refreshed:
                run_dir = _run_path(runs_root, verdict.get("run_dir"))
                retry_fp = fp
                retry_memo_sha256 = memo_sha256
                refresh_verdict = verdict | {"_repair_decision": retry_decisions.get(fp)}
                memo_refreshed = memo_refresher(run_dir, refresh_verdict)
                if memo_refreshed:
                    verdict = _reload_verdict_after_memo_refresh(refresh_verdict, run_dir)
                    fp = memo_fingerprint(verdict)
                    memo_sha256 = _memo_sha256(verdict, runs_root)
                    source_count = _source_count(verdict, runs_root)
                    direct_source_count = _direct_source_count(verdict, runs_root)
                    corpus_source_count = _corpus_source_count(verdict, runs_root)
                    approved = _selection_approved(
                        verdict,
                        runs_root,
                        allow_tier2=allow_tier2,
                        source_count=source_count,
                        direct_source_count=direct_source_count,
                        min_source_count=min_source_count,
                        min_direct_source_count=min_direct_source_count,
                    )
                    cycle_blocked = fp in blocked
                    attempt_count = _fingerprint_attempt_count(submitted_path, fp)
                    retry_after_rejection = _retry_after_rejection(
                        fp,
                        attempt_count=attempt_count,
                        retryable=retryable,
                        decisions=retry_decisions,
                    )
                    missing_audit_sidecars = _missing_audit_sidecars(verdict, runs_root)
                    if fp == retry_fp and memo_sha256 == retry_memo_sha256:
                        status = "duplicate_submission_fingerprint"
            if missing_audit_sidecars:
                status = "memo_missing_audit_sidecars"
            if retry_fingerprint_unchanged:
                status = "duplicate_submission_fingerprint"
            if status == "eligible":
                if fp in seen and _same_memo_seen(submitted_path, fp, memo_sha256):
                    status = "duplicate_submission_fingerprint"
                elif source_count < min_source_count:
                    status = (
                        "corpus_source_floor_below_min"
                        if corpus_source_count < min_source_count else
                        "memo_source_floor_below_min"
                    )
                    if source_count >= min_source_count:
                        status = "eligible"
                elif direct_source_count < min_direct_source_count:
                    status = "direct_source_floor_below_min"
        row = {
            "topic": _selection_topic(verdict),
            "decision": verdict.get("decision"),
            "publish_tier": verdict.get("publish_tier"),
            "surface_type": verdict.get("surface_type"),
            "alpha_score": verdict.get("alpha_score"),
            "blockers": verdict.get("blockers"),
            "run_dir": verdict.get("run_dir"),
            "fingerprint": fp,
            "source_count": source_count,
            "direct_source_count": direct_source_count,
            "corpus_ab_paper_count": corpus_source_count,
            "min_source_count": min_source_count,
            "min_direct_source_count": min_direct_source_count,
            "accepted_shape_bonus": shape_bonus,
            "status": status,
        }
        if memo_refreshed:
            row["memo_refreshed"] = True
        if retry_after_rejection:
            row["retry_after_rejection"] = True
            row["retry_attempt_count"] = attempt_count
        if missing_audit_sidecars:
            row["missing_audit_sidecars"] = missing_audit_sidecars
        considered.append(row)
        if status == "eligible":
            return verdict | {"memo_fingerprint": fp}, considered
    return None, considered


def _cited_dois(verdict: Json, runs_root: Path | None = None) -> list[str]:
    memo_papers = (
        _memo_source_papers(verdict, runs_root)
        if runs_root is not None else
        []
    )
    papers = memo_papers or ((verdict.get("axes") or {}).get("source_papers") or [])
    out: list[str] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        doi = _norm(paper.get("doi"))
        if doi and doi not in out:
            out.append(doi)
    return out


def _crossref_fetch(doi: str) -> Json:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _decision_fetch(submission_id: str) -> Json:
    base = os.environ.get("RESEARKA_DECISION_URL_BASE", "https://api.researka.org/submissions")
    url = base.rstrip("/") + "/" + urllib.parse.quote(submission_id, safe="") + "/decision"
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _submission_id(payload: Json) -> str:
    direct = payload.get("submission_id")
    if direct:
        return str(direct)
    submission = payload.get("submission")
    if isinstance(submission, dict) and submission.get("id"):
        return str(submission.get("id"))
    for key in ("detail", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _submission_id(nested)
            if found:
                return found
    for attempt in payload.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("response")
        if isinstance(response, dict):
            found = _submission_id(response)
            if found:
                return found
        elif isinstance(response, str):
            with suppress(json.JSONDecodeError):
                found = _submission_id(json.loads(response))
                if found:
                    return found
    nested = payload.get("submission")
    return str(nested.get("id") if isinstance(nested, dict) else "")


def _public_alpha_base() -> str:
    return os.environ.get("RESEARKA_ALPHA_BASE_URL", "https://researka.org/alpha").rstrip("/")


def _public_alpha_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    return _public_alpha_base() + "/" + urllib.parse.quote(raw, safe="")


def _public_alpha_urls(payload: Any) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        url = _public_alpha_url(value)
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
                    if "url" not in key_l or "/alpha/" in str(item):
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


def _fetch_public_page(url: str) -> Json:
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {"ok": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read(512).decode("utf-8", errors="replace")}
    except Exception as exc:  # pragma: no cover - network defensive path
        return {"ok": False, "status": 0, "error": type(exc).__name__, "detail": str(exc)[:180]}


def _page_rendered(result: Json) -> bool:
    body = str(result.get("body") or "").lower()
    missing_title = re.search(r"<title\b[^>]*>[^<]*(404|not found)[^<]*</title>", body)
    return (
        bool(result.get("ok"))
        and int(result.get("status") or 0) == 200
        and not missing_title
    )


def _public_page_check(decision: Json, *, page_fetcher: PageFetcher) -> Json:
    urls = _public_alpha_urls(decision)
    if not urls:
        return {"ok": False, "status": "missing_public_url", "urls": []}
    checks: list[Json] = []
    for url in urls:
        result = page_fetcher(url)
        check = {
            "url": url,
            "http_status": result.get("status"),
            "ok": _page_rendered(result),
        }
        if result.get("error"):
            check["error"] = result.get("error")
        checks.append(check)
        if check["ok"]:
            return {"ok": True, "status": "rendered", "url": url, "checks": checks}
    return {"ok": False, "status": "not_rendered", "urls": urls, "checks": checks}


def _apply_submission_decision(
    ledger: Json,
    *,
    submission_id: str,
    decision: Json,
    page_fetcher: PageFetcher,
) -> str:
    final = "pending"
    if decision.get("status") == "complete":
        if decision.get("decision") == "accept":
            page = _public_page_check(decision, page_fetcher=page_fetcher)
            ledger["public_page_check"] = page
            if page.get("ok"):
                final = "accepted"
                ledger["status"] = "published"
                ledger["published"] = 1
                ledger["published_topic"] = (
                    ledger.get("submitted_topic")
                    or (ledger.get("candidate") or {}).get("topic")
                )
                ledger["public_url"] = page.get("url")
            elif page.get("status") == "missing_public_url":
                final = "pending"
                ledger["status"] = "submitted_to_researka"
                ledger["published"] = 0
                ledger["accepted_pending_public_url"] = True
                ledger.pop("publish_failure_reason", None)
            else:
                final = "rejected"
                ledger["status"] = "public_page_not_rendered"
                ledger["published"] = 0
                ledger["publish_failure_reason"] = "public_page_not_rendered"
        elif decision.get("decision") == "revise":
            final = "revise"
            ledger["status"] = "reviewer_revise"
        else:
            final = "rejected"
            ledger["status"] = "reviewer_rejected"
    ledger["submission_id"] = submission_id
    ledger["researka_decision"] = decision
    ledger["final_verdict"] = final
    return final


def _poll_submission_decision(
    ledger: Json,
    *,
    submission_id: str,
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
            decision = fetcher(submission_id)
        except Exception as exc:  # pragma: no cover - network defensive path
            ledger["decision_check_error"] = {
                "error": type(exc).__name__,
                "detail": str(exc)[:180],
                "attempt": idx + 1,
            }
            return final
        final = _apply_submission_decision(
            ledger,
            submission_id=submission_id,
            decision=decision,
            page_fetcher=page_fetcher,
        )
        ledger["decision_poll"] = {"attempts": idx + 1, "final_verdict": final}
        if final != "pending":
            return final
    return final


def sync_submission_decisions(
    runs_root: Path = _RUNS,
    *,
    fetcher: DecisionFetcher = _decision_fetch,
    page_fetcher: PageFetcher = _fetch_public_page,
    now: dt.datetime | None = None,
    max_pending_age_hours: float = _DEFAULT_PENDING_DECISION_MAX_AGE_HOURS,
) -> Json:
    ledger_dir = runs_root / "_daily_ledger"
    current = now or dt.datetime.now(dt.UTC)
    summary: Json = {
        "checked": 0, "updated": 0, "published": 0, "pending": 0,
        "stale": 0, "errors": [],
    }
    seen_submission_ids: set[str] = set()
    submission_record_updates: dict[str, Json] = {}
    for path in sorted(ledger_dir.glob("*.json")):
        ledger = _json(path, {})
        if isinstance(ledger, dict):
            sid = str(ledger.get("submission_id") or "") or _submission_id(
                ledger.get("submission", {}),
            )
            if sid:
                seen_submission_ids.add(sid)
                patch = _submission_record_patch(ledger)
                if patch:
                    submission_record_updates[sid] = patch
        if not isinstance(ledger, dict) or ledger.get("status") != "submitted_to_researka":
            continue
        if ledger.get("final_verdict") in _FINAL_DECISION_VERDICTS:
            continue
        submission_id = str(ledger.get("submission_id") or "") or _submission_id(
            ledger.get("submission", {}),
        )
        if not submission_id:
            continue
        summary["checked"] += 1
        try:
            decision = fetcher(submission_id)
        except Exception as exc:  # pragma: no cover - network defensive path
            summary["errors"].append({
                "ledger": path.name,
                "submission_id": submission_id,
                "error": type(exc).__name__,
                "detail": str(exc)[:180],
            })
            continue
        final = _apply_submission_decision(
            ledger,
            submission_id=submission_id,
            decision=decision,
            page_fetcher=page_fetcher,
        )
        summary["pending"] += int(final == "pending")
        summary["published"] += int(final == "accepted")
        if final == "pending" and _stale_pending_decision(
            ledger, stamp=path.stem, now=current,
            max_age_hours=max_pending_age_hours,
        ):
            _mark_stale_pending_decision(
                ledger, max_age_hours=max_pending_age_hours,
            )
            final = "stale_pending"
            summary["pending"] -= 1
            summary["stale"] += 1
        if final != "pending":
            summary["updated"] += 1
        patch = _submission_record_patch(ledger)
        if patch:
            submission_record_updates[submission_id] = patch
        _write_json(path, ledger)
    submitted = _json(ledger_dir / "_submitted_fingerprints.json", [])
    if isinstance(submitted, list):
        submitted_changed = False
        for row in submitted:
            if not isinstance(row, dict):
                continue
            submission_id = str(row.get("submission_id") or "")
            if not submission_id:
                continue
            row_patch = submission_record_updates.get(submission_id)
            if row_patch:
                submitted_changed |= _merge_submission_record(row, row_patch)
            if (
                submission_id in seen_submission_ids
                or row.get("final_verdict") in _FINAL_DECISION_VERDICTS
            ):
                continue
            summary["checked"] += 1
            try:
                decision = fetcher(submission_id)
            except Exception as exc:  # pragma: no cover - network defensive path
                summary["errors"].append({
                    "ledger": "_submitted_fingerprints.json",
                    "submission_id": submission_id,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:180],
                })
                continue
            synthetic_ledger: Json = {
                "date": row.get("date"),
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
                "submitted_topic": row.get("topic"),
                "submission_id": submission_id,
                "candidate": {
                    "topic": row.get("topic"),
                    "run_dir": row.get("run_dir"),
                    "fingerprint": row.get("fingerprint"),
                },
            }
            final = _apply_submission_decision(
                synthetic_ledger,
                submission_id=submission_id,
                decision=decision,
                page_fetcher=page_fetcher,
            )
            summary["pending"] += int(final == "pending")
            summary["published"] += int(final == "accepted")
            if final == "pending" and _stale_pending_decision(
                synthetic_ledger, stamp=row.get("date"), now=current,
                max_age_hours=max_pending_age_hours,
            ):
                _mark_stale_pending_decision(
                    synthetic_ledger, max_age_hours=max_pending_age_hours,
                )
                final = "stale_pending"
                summary["pending"] -= 1
                summary["stale"] += 1
            if final != "pending":
                summary["updated"] += 1
            submitted_changed |= _merge_submission_record(
                row, _submission_record_patch(synthetic_ledger),
            )
            stamp = _norm(row.get("date")).replace(" ", "-") or "undated"
            _write_json(
                ledger_dir / f"{stamp}-decision-{submission_id[:8]}.json",
                synthetic_ledger,
            )
            seen_submission_ids.add(submission_id)
        if submitted_changed:
            _write_json(ledger_dir / "_submitted_fingerprints.json", submitted)
    return summary


def _has_retraction_marker(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_l = str(key).lower()
            if (
                key_l in {"subtype", "type", "update-type"}
                and "retraction" in str(value).lower()
            ):
                return True
            if key_l in {"update-to", "update-from"} and _has_retraction_marker(value):
                return True
            if key_l == "relation":
                if any("retract" in str(k).lower() for k in value):
                    return True
                if _has_retraction_marker(value):
                    return True
            if key_l.startswith("is-retract"):
                return True
    elif isinstance(payload, list):
        return any(_has_retraction_marker(item) for item in payload)
    return False


def retraction_check(
    verdict: Json,
    *,
    mode: str,
    fetcher: Fetcher = _crossref_fetch,
    runs_root: Path | None = None,
) -> Json:
    dois = _cited_dois(verdict, runs_root)
    if mode == "skip":
        return {"status": "skipped", "checked_dois": dois, "retracted": []}
    if mode == "metadata":
        memo_papers = (
            _memo_source_papers(verdict, runs_root)
            if runs_root is not None else
            []
        )
        papers = memo_papers or ((verdict.get("axes") or {}).get("source_papers") or [])
        hits = [
            p for p in papers
            if isinstance(p, dict) and bool(p.get("is_retracted"))
        ]
        return {
            "status": "blocked" if hits else "clean",
            "checked_dois": dois,
            "retracted": hits,
        }
    retracted: list[Json] = []
    errors: list[Json] = []
    for doi in dois:
        try:
            payload = fetcher(doi)
        except Exception as exc:  # pragma: no cover - network defensive path
            errors.append({"doi": doi, "error": type(exc).__name__, "detail": str(exc)[:180]})
            continue
        message = payload.get("message", payload) if isinstance(payload, dict) else payload
        if _has_retraction_marker(message):
            retracted.append({"doi": doi, "source": "crossref"})
    status = "blocked" if retracted else ("error" if errors else "clean")
    return {
        "status": status,
        "checked_dois": dois,
        "retracted": retracted,
        "errors": errors,
    }


def _run_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
    try:
        result = _run_subprocess(args, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    lines = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().splitlines()
    return result.returncode == 0, (lines[-1] if lines else "")


def _latest_cycle_topics(runs_root: Path) -> Json:
    cycles = sorted(
        path for path in (runs_root / "_curator_cycles").glob("*.json")
        if "_cross_topic_" not in path.name
    )
    if not cycles:
        return {}
    payload = _json(cycles[-1], {})
    if not isinstance(payload, dict):
        return {}
    ran = [
        str(row.get("topic") or "")
        for row in payload.get("ran") or []
        if isinstance(row, dict) and row.get("topic")
    ]
    skipped = [str(t) for t in payload.get("skipped_in_cooldown") or [] if str(t)]
    return {
        "cycle": cycles[-1].name,
        "ran_topics": ran,
        "skipped_in_cooldown": skipped,
    }


def _refresh_candidate_batch(
    refresh_top: int,
    excluded_topics: set[str] | None = None,
    cooldown_hours: float = _DEFAULT_REFRESH_COOLDOWN_HOURS,
    runs_root: Path = _RUNS,
    warm_backlog: bool = False,
    priority_topics: Iterable[str] = (),
) -> Json:
    exclusions = sorted(t for t in (excluded_topics or set()) if t)
    warm_probe_topics = min(
        _DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT,
        max(refresh_top, _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES, refresh_top + len(exclusions)),
    )
    args = [
        sys.executable, "scripts/run_curator_cycle.py",
        "--stop-on-ready", "--top", str(refresh_top),
        "--cooldown-hours", f"{cooldown_hours:g}",
        "--no-editorial", "--no-frontier",
    ]
    if warm_backlog:
        args.extend([
            "--warm-backlog",
            "--derived-topic-limit",
            str(_DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT),
            "--fact-probe-topics",
            str(warm_probe_topics),
        ])
    priorities = [str(topic).strip() for topic in priority_topics if str(topic).strip()]
    for topic in priorities:
        args.extend(["--priority-topic", topic])
    for topic in exclusions:
        args.extend(["--exclude-topic", topic])
    ok, note = _run_step(args, timeout=_REFRESH_TIMEOUT_SECONDS)
    result = {
        "ok": ok,
        "note": note,
        "top": refresh_top,
        "cooldown_hours": cooldown_hours,
        "excluded_topics": exclusions,
        "priority_topics": priorities,
        "warm_backlog": warm_backlog,
    } | _latest_cycle_topics(runs_root)
    if priorities:
        ran_raw = result.get("ran_topics")
        ran = ran_raw if isinstance(ran_raw, list) else []
        result["ran_topics"] = list(dict.fromkeys(
            [str(t) for t in ran if str(t)] + priorities
        ))
    return result


def _child_topics_from_queue(
    queue: Json, excluded_topics: set[str], *, limit: int,
) -> list[str]:
    out: list[str] = []
    seen = set(excluded_topics)
    for bucket_name in ("agent_repair_needed", "curation_needed"):
        for verdict in queue.get(bucket_name) or []:
            if not isinstance(verdict, dict):
                continue
            parent = str(verdict.get("topic") or "").strip()
            rec = verdict.get("subtopic_recommendations")
            if not parent or not isinstance(rec, dict) or not rec.get("recommended"):
                continue
            for cluster in rec.get("clusters") or []:
                if not isinstance(cluster, dict):
                    continue
                if _cluster_has_repair_receipts(cluster):
                    continue
                label = str(cluster.get("label") or "").strip("_")
                if not label or label == "unlabeled":
                    continue
                child = "_".join(re.findall(r"[a-z0-9]+", f"{parent}_{label}".lower()))
                if child and child not in seen:
                    out.append(child)
                    seen.add(child)
                    if len(out) >= limit:
                        return out
    return out


def _cluster_has_repair_receipts(cluster: Json) -> bool:
    values = cluster.get("member_fact_ids") if isinstance(cluster, dict) else []
    if not isinstance(values, list):
        return False
    return len({str(value or "").strip() for value in values if str(value or "").strip()}) >= (
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES
    )


def _queue_counts(queue: Json) -> Json:
    return {
        "ready_to_publish": len(queue.get("ready_to_publish") or []),
        "agent_repair_needed": (
            len(queue.get("agent_repair_needed") or [])
            + len(queue.get("needs_operator_review") or [])
        ),
        "curation_needed": len(queue.get("curation_needed") or []),
    }


def _drop_markdown_section(memo: str, heading: str) -> str:
    out: list[str] = []
    dropping = False
    for line in memo.splitlines():
        if line.strip() == heading:
            dropping = True
            continue
        if dropping and line.startswith("## "):
            dropping = False
        if not dropping:
            out.append(line)
    return "\n".join(out)


def _plain_section(memo: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n+(.*?)(?=^## |\Z)", memo, re.M | re.S)
    if not match:
        return ""
    text = re.sub(r"`([^`]+)`", r"\1", match.group(1))
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    lines = [
        re.sub(r"^[-*]\s+", "", line.strip())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("|")
    ]
    return " ".join(" ".join(lines).split())


def _safe_excerpt(text: str, limit: int = 1200) -> str:
    excerpt = " ".join(str(text or "").split())
    sentence_cuts = [
        match.end()
        for match in re.finditer(r"[.!?](?=\s|$)", excerpt[:limit + 1])
    ]
    if len(excerpt) <= limit:
        if sentence_cuts:
            return excerpt[:sentence_cuts[-1]]
        return ""
    if sentence_cuts:
        return excerpt[:sentence_cuts[-1]]
    return ""


def _public_submission_markdown(memo: str) -> str:
    memo = _drop_markdown_section(memo, "## Provenance / priority")
    memo = _drop_markdown_section(memo, "## Next extraction")
    memo = _drop_markdown_section(memo, "## Subtopic recommendations")
    internal_prefixes = (
        "# Alpha memo",
        "**Headline:**",
        "**Alpha score:**",
        "**Alpha triage:**",
        "**Confidence:**",
        "**Memo surface:**",
        "**Snapshot:**",
        "**Run:**",
        "**Direct source breadth:**",
        "**Source thesis:**",
        "**Source breadth:**",
    )
    lines = [
        line for line in memo.splitlines()
        if not line.startswith(internal_prefixes)
    ]
    text = "\n".join(lines).strip() + "\n"
    note = (
        "**Interpretation note:** This is a hypothesis-generating alpha memo, "
        "not confirmatory evidence; subgroup or context-derived claims require "
        "independent replication.\n"
    )
    if "## Why this is surprising" in text and note not in text:
        text = text.replace("\n## Why this is surprising", f"\n\n{note}\n## Why this is surprising", 1)
    landscape_note = (
        "_Evidence-map boundary: cited receipts are separate evidence streams "
        "unless an integrated analysis is explicitly stated; this memo maps a "
        "testable contrast, not a pooled meta-analysis or settled conclusion._\n"
    )
    change_note = (
        "_Interpretation boundary: this is a hypothesis-generating alpha map, "
        "not confirmatory evidence or a settled conclusion._\n"
    )
    if "## Evidence Landscape\n\n" in text and landscape_note not in text:
        text = text.replace("## Evidence Landscape\n\n", f"## Evidence Landscape\n\n{landscape_note}\n", 1)
    if "## What this changes\n\n" in text and change_note not in text:
        text = text.replace("## What this changes\n\n", f"## What this changes\n\n{change_note}\n", 1)
    return text.replace(
        "## Context receipts\n\n",
        "## Context receipts\n\n"
        "_Boundary evidence only; these receipts broaden source context but do "
        "not independently prove the lead claim._\n\n",
    )


def _audit_sidecars(run_dir: Path) -> Json:
    out: Json = {}
    for name in _REQUIRED_AUDIT_SIDECARS:
        data = _json(run_dir / name, None)
        if isinstance(data, (dict, list)):
            out[name.removesuffix(".json")] = data
    return out


def _submission_payload(verdict: Json, root: Path) -> Json:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = ""
    with suppress(OSError):
        memo = (run_dir / "alpha_memo.md").read_text(encoding="utf-8")
    public_memo = _public_submission_markdown(memo)
    title = str(
        _memo_headline(memo)
        or verdict.get("headline")
        or verdict.get("topic")
        or "Alpha memo"
    )
    abstract = next(
        (
            excerpt for excerpt in (
                _safe_excerpt(_plain_section(memo, "One-sentence thesis")),
                _safe_excerpt(_plain_section(memo, "Why this is surprising")),
                _safe_excerpt(title),
                title,
            ) if excerpt
        ),
        title,
    )
    source_papers = _memo_source_papers(verdict, root)
    direct_source_papers = _memo_source_papers(verdict, root, ("Evidence",), {"A_core"})
    source_bundle = _source_bundle(direct_source_papers)
    direct_source_count = len(direct_source_papers)
    receipt_count = len(_memo_receipt_ids(memo))
    return {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": "agent-v4-alpha-memo",
        "agent_id": "agent-v4-alpha-memo",
        "title": title,
        "abstract": abstract,
        "summary": abstract,
        "topic": verdict.get("topic"),
        "markdown": public_memo,
        "citations": source_bundle,
        "source_bundle": source_bundle,
        "novelty_score": verdict.get("alpha_score"),
        "confidence_score": verdict.get("maturity_level"),
        "evidence_bundle": {
            "publish_verdict": verdict,
            "run_dir": verdict.get("run_dir"),
            "audit_sidecars": _audit_sidecars(run_dir),
            "source_papers": source_papers,
            "direct_source_papers": direct_source_papers,
            "bound_receipt_count": receipt_count,
            "bound_source_count": len(source_papers),
            "source_bundle_count": len(source_bundle),
            "direct_source_count": direct_source_count,
            "context_source_count": max(0, len(source_papers) - direct_source_count),
            "context_sources_are_not_direct_support": "## Context receipts" in memo,
        },
        "content_hash": "sha256:" + hashlib.sha256(public_memo.encode("utf-8")).hexdigest(),
    }


def _http_submitter(url: str, token: str) -> Submitter:
    def submit(payload: Json) -> Json:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "x-api-key": token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                text = response.read().decode("utf-8")
                return {"ok": True, "status": response.status, "response": json.loads(text)}
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "response": text[:1000]}
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


def run_cycle(
    *,
    runs_root: Path = _RUNS,
    date: str,
    queue: Json | None = None,
    include_archive: bool = False,
    refresh_candidates: bool = False,
    allow_tier2: bool = False,
    estimated_cost_usd: float = 0.0,
    max_cost_usd: float = 5.0,
    refresh_top: int = _DEFAULT_REFRESH_TOP,
    refresh_cooldown_hours: float = _DEFAULT_REFRESH_COOLDOWN_HOURS,
    max_refresh_batches: int = _DEFAULT_MAX_REFRESH_BATCHES,
    published_topic_cooldown_days: int = _DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS,
    submit: bool = False,
    retraction_mode: str = "metadata",
    min_submit_sources: int = _DEFAULT_MIN_SUBMIT_SOURCES,
    min_direct_submit_sources: int = _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES,
    decision_poll_attempts: int = _DEFAULT_DECISION_POLL_ATTEMPTS,
    decision_poll_seconds: float = _DEFAULT_DECISION_POLL_SECONDS,
    submitter: Submitter | None = None,
    fetcher: Fetcher = _crossref_fetch,
    decision_fetcher: DecisionFetcher = _decision_fetch,
    page_fetcher: PageFetcher = _fetch_public_page,
    memo_refresher: MemoRefresher = _refresh_alpha_memo,
    queue_builder: QueueBuilder = _build_queue,
    sleep: Callable[[float], None] = time.sleep,
) -> Json:
    ledger_path = runs_root / "_daily_ledger" / f"{date}.json"
    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    decision_sync = sync_submission_decisions(
        runs_root, fetcher=decision_fetcher, page_fetcher=page_fetcher,
    )
    ledger: Json = {
        "date": date,
        "dry_run": not submit,
        "decision_sync": decision_sync,
        "estimated_cost_usd": estimated_cost_usd,
        "max_cost_usd": max_cost_usd,
        "refresh_top": refresh_top,
        "refresh_cooldown_hours": refresh_cooldown_hours,
        "max_refresh_batches": max_refresh_batches,
        "published_topic_cooldown_days": published_topic_cooldown_days,
        "min_submit_sources": min_submit_sources,
        "min_direct_submit_sources": min_direct_submit_sources,
        "decision_poll_attempts": decision_poll_attempts,
        "decision_poll_seconds": decision_poll_seconds,
        "refresh_batches": [],
        "cycle_attempts": [],
        "published": 0,
        "published_topic": None,
        "submitted": 0,
        "submitted_topic": None,
        "status": "started",
    }
    if estimated_cost_usd > max_cost_usd:
        ledger.update({"status": "cost_cap_exceeded", "reason": "estimated_cost_above_cap"})
        _write_json(ledger_path, ledger)
        return ledger
    blocked_fingerprints: set[str] = set()
    session_retryable: set[str] = set()
    session_retry_decisions: dict[str, Json] = {}
    blocked_topics = _recently_published_topics(
        submitted_path.parent, days=published_topic_cooldown_days,
    )
    ledger["recently_published_topics_blocked"] = sorted(blocked_topics)
    force_refresh = False
    accepted_shape_profiles = _accepted_shape_profiles(runs_root)
    all_considered: list[Json] = []
    search_batch_limit = max(1, max_refresh_batches if refresh_candidates else 1)
    batch_limit = search_batch_limit + (
        _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT
        if submit and refresh_candidates else 0
    )
    default_submitter = submitter is None
    if submit and submitter is None:
        url = os.environ.get("RESEARKA_SUBMIT_URL", "https://api.researka.org/submissions")
        token, token_env = _submit_token()
        if not token:
            ledger.update({
                "status": "submit_not_configured",
                "reason": "missing_submit_token",
                "accepted_env_vars": list(_SUBMIT_TOKEN_ENVS),
            })
            _write_json(ledger_path, ledger)
            return ledger
        ledger["submit_token_env"] = token_env
        submitter = _http_submitter(url, token)
    prev_queue_sig: frozenset[str] = frozenset()
    preflight_queue = None
    skip_refresh_note = "skipped_after_repairable_submission"
    if refresh_candidates and queue is None and queue_builder is _build_queue:
        candidate_queue = queue_builder(runs_root, include_archive)
        if candidate_queue.get("ready_to_publish"):
            preflight_queue = candidate_queue
            skip_refresh_note = "skipped_initial_queue_probe"
    skip_next_refresh = preflight_queue is not None
    warm_backlog_next = False
    priority_refresh_topics: list[str] = []
    for batch in range(1, batch_limit + 1):
        if refresh_candidates and batch > search_batch_limit and not skip_next_refresh:
            break
        refresh: Json = {}
        if refresh_candidates and skip_next_refresh:
            refresh = {
                "ok": True,
                "note": skip_refresh_note,
                "top": refresh_top,
                "cooldown_hours": refresh_cooldown_hours,
                "excluded_topics": sorted(blocked_topics),
            }
            skip_next_refresh = False
            skip_refresh_note = "skipped_after_repairable_submission"
            refresh["batch"] = batch
            ledger["refresh_batches"].append(refresh)
            ledger["refresh_candidates"] = refresh
        elif refresh_candidates:
            cooldown = 0.0 if blocked_topics or force_refresh else refresh_cooldown_hours
            refresh = _refresh_candidate_batch(
                refresh_top, blocked_topics, cooldown, runs_root,
                warm_backlog=warm_backlog_next,
                priority_topics=priority_refresh_topics,
            )
            priority_refresh_topics = []
            if cooldown != refresh_cooldown_hours:
                refresh["cooldown_reason"] = (
                    "retry_after_blocked_topic"
                    if blocked_topics else "retry_after_empty_refresh"
                )
            force_refresh = False
            warm_backlog_next = False
            refresh["batch"] = batch
            ledger["refresh_batches"].append(refresh)
            ledger["refresh_candidates"] = refresh
            if not refresh["ok"]:
                if refresh.get("warm_backlog") or _refresh_timeout_note(refresh):
                    ledger["refresh_early_exit"] = {
                        "batch": batch,
                        "reason": (
                            "warm_backlog_failed" if refresh.get("warm_backlog")
                            else "refresh_timeout"
                        ),
                        "note": str(refresh.get("note") or "")[:240],
                    }
                    break
                ledger["considered"] = all_considered
                ledger.update({"status": "candidate_refresh_failed"})
                _write_json(ledger_path, ledger)
                return ledger
        current_queue = (
            queue if queue is not None else preflight_queue
            if preflight_queue is not None else queue_builder(runs_root, include_archive)
        )
        preflight_queue = None
        current_queue = _with_repairable_candidates(current_queue, runs_root)
        # Fingerprint the queue so we can detect a refresh batch that changed
        # nothing. memo_fingerprint shifts when a candidate's cited receipts
        # change, so a genuine build/refresh moves the signature.
        queue_sig = frozenset(
            memo_fingerprint(r)
            for bucket in current_queue.values() if isinstance(bucket, list)
            for r in bucket if isinstance(r, dict)
        )
        queue_unchanged = queue_sig == prev_queue_sig
        prev_queue_sig = queue_sig
        ledger["queue_counts"] = _queue_counts(current_queue)
        candidate, considered = select_candidate(
            current_queue, runs_root=runs_root, submitted_path=submitted_path,
            allow_tier2=allow_tier2,
            min_source_count=min_submit_sources if submit else 0,
            min_direct_source_count=min_direct_submit_sources if submit else 0,
            memo_refresher=memo_refresher if submit else None,
            blocked_fingerprints=blocked_fingerprints,
            blocked_topics=blocked_topics,
            accepted_shape_profiles=accepted_shape_profiles,
            retryable_fingerprints=session_retryable,
            retry_decision_overrides=session_retry_decisions,
        )
        for row in considered:
            if refresh_candidates:
                row["batch"] = batch
            if row.get("status") in _REFRESHABLE_SOURCE_FLOOR_STATUSES:
                topic = str(row.get("topic") or "")
                if topic:
                    ledger.setdefault("source_floor_refresh_topics", [])
                    if topic not in ledger["source_floor_refresh_topics"]:
                        ledger["source_floor_refresh_topics"].append(topic)
                continue
            if row.get("status") in _EXHAUSTED_STATUSES:
                fingerprint = str(row.get("fingerprint") or "")
                topic = str(row.get("topic") or "")
                if fingerprint and row.get("status") in _FINGERPRINT_EXHAUSTED_STATUSES:
                    blocked_fingerprints.add(fingerprint)
                if topic and row.get("status") in _TOPIC_EXHAUSTED_STATUSES:
                    blocked_topics.add(topic)
        all_considered.extend(considered)
        ledger["considered"] = all_considered
        if candidate is None:
            ran_topics = [str(t) for t in refresh.get("ran_topics") or [] if str(t)]
            if ran_topics:
                blocked_topics.update(ran_topics)
            priority_children = _child_topics_from_queue(
                current_queue, blocked_topics, limit=refresh_top,
            )
            if refresh_candidates and priority_children and batch < search_batch_limit:
                ledger["refresh_child_topics"] = priority_children
                priority_refresh_topics = priority_children
                force_refresh = True
                continue
            if refresh_candidates and refresh.get("skipped_in_cooldown"):
                force_refresh = True
            elif refresh_candidates and refresh.get("warm_backlog"):
                ledger["refresh_early_exit"] = {
                    "batch": batch,
                    "reason": "warm_backlog_empty_no_candidate",
                }
                break
            elif (
                refresh_candidates
                and not refresh.get("warm_backlog")
                and batch < search_batch_limit
            ):
                ledger["refresh_backlog_escalation"] = {
                    "after_batch": batch,
                    "reason": "empty_refresh_no_candidate",
                }
                warm_backlog_next = True
                force_refresh = True
                continue
            elif refresh_candidates and queue_unchanged:
                # This refresh batch produced an identical candidate queue and
                # no publishable candidate. Escalate once into progressive
                # backlog warming before stopping; this lets the source-rich
                # cache grow when the normal fast window is exhausted.
                if not refresh.get("warm_backlog") and batch < search_batch_limit:
                    ledger["refresh_backlog_escalation"] = {
                        "after_batch": batch,
                        "reason": "queue_unchanged_no_candidate",
                    }
                    warm_backlog_next = True
                    force_refresh = True
                    continue
                ledger["refresh_early_exit"] = {
                    "batch": batch, "reason": "queue_unchanged_no_candidate",
                }
                break
            continue
        check_mode = "crossref" if submit and retraction_mode == "metadata" else retraction_mode
        retraction = retraction_check(
            candidate, mode=check_mode, fetcher=fetcher, runs_root=runs_root,
        )
        attempt = {
            "batch": batch,
            "topic": candidate.get("topic"),
            "run_dir": candidate.get("run_dir"),
            "fingerprint": candidate.get("memo_fingerprint"),
            "retraction_check": retraction,
        }
        ledger["retraction_check"] = retraction
        ledger["candidate"] = {
            "topic": candidate.get("topic"),
            "run_dir": candidate.get("run_dir"),
            "fingerprint": candidate.get("memo_fingerprint"),
        }
        if retraction.get("status") != "clean":
            attempt["status"] = "held_retraction_check"
            for row in reversed(all_considered):
                if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                    row["pre_attempt_status"] = row.get("status")
                    row["status"] = "held_retraction_check"
                    break
            ledger["cycle_attempts"].append(attempt)
            blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
            _write_json(
                runs_root / "_retracted_holds" / f"{candidate.get('topic')}-{date}.json",
                ledger,
            )
            if not refresh_candidates or batch >= search_batch_limit:
                ledger.update({
                    "status": "held_retraction_check",
                    "candidate": candidate.get("topic"),
                })
                _write_json(ledger_path, ledger)
                return ledger
            continue
        if not submit:
            ledger["cycle_attempts"].append(attempt | {"status": "dry_run_selected"})
            ledger.update({"status": "dry_run_selected"})
            _write_json(ledger_path, ledger)
            return ledger
        assert submitter is not None
        result = submit_with_backoff(_submission_payload(candidate, runs_root), submitter)
        attempt["submission"] = result
        ledger["submission"] = result
        if result["status"] == "accepted":
            submission_id = _submission_id(result)
            _record_submission_attempt(
                submitted_path,
                date=date,
                candidate=candidate,
                runs_root=runs_root,
                submission_id=submission_id,
            )
            ledger.update({
                "final_verdict": "pending",
                "status": "submitted_to_researka",
                "submitted": 1,
                "submitted_topic": candidate.get("topic"),
                "submission_id": submission_id,
            })
            if submission_id:
                final = _poll_submission_decision(
                    ledger,
                    submission_id=submission_id,
                    fetcher=decision_fetcher,
                    page_fetcher=page_fetcher,
                    attempts=decision_poll_attempts
                    if default_submitter or decision_fetcher is not _decision_fetch
                    else 0,
                    sleep_seconds=decision_poll_seconds,
                    sleep=sleep,
                )
                decision = ledger.get("researka_decision", {})
                if isinstance(decision, dict):
                    if final == "accepted":
                        attempt["public_page_check"] = ledger.get("public_page_check")
                        ledger["cycle_attempts"].append(attempt | {"status": "published"})
                        _write_json(ledger_path, ledger)
                        return ledger
                    if final in {"rejected", "revise"}:
                        attempt["status"] = (
                            str(ledger.get("publish_failure_reason") or "")
                            or ("reviewer_revise" if final == "revise" else "reviewer_rejected")
                        )
                        attempt["researka_decision"] = decision
                        attempt["public_page_check"] = ledger.get("public_page_check")
                        for row in reversed(all_considered):
                            if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                                row["pre_attempt_status"] = row.get("status")
                                row["status"] = "cycle_failed_submission"
                                row["submit_status"] = attempt["status"]
                                break
                        ledger["cycle_attempts"].append(attempt)
                        if (
                            _repairable_rejection(decision)
                            and refresh_candidates
                            and batch < batch_limit
                        ):
                            fingerprint = str(candidate.get("memo_fingerprint") or "")
                            if fingerprint:
                                blocked_fingerprints.add(fingerprint)
                            ledger["repair_retry_deferred"] = {
                                "topic": candidate.get("topic"),
                                "reason": attempt["status"],
                                "requires": "new_memo_fingerprint",
                            }
                            _write_json(ledger_path, ledger)
                            continue
                        blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
                        topic = str(candidate.get("topic") or "")
                        if topic:
                            blocked_topics.add(topic)
                        if not refresh_candidates or batch >= search_batch_limit:
                            ledger.update({"status": attempt["status"], "published": 0})
                            _write_json(ledger_path, ledger)
                            return ledger
                        continue
            ledger["cycle_attempts"].append(attempt | {"status": "submitted_to_researka"})
            _write_json(ledger_path, ledger)
            return ledger
        if result["status"] == "rejected_duplicate":
            _record_submission_attempt(
                submitted_path,
                date=date,
                candidate=candidate,
                runs_root=runs_root,
                submission_id=_submission_id(result),
                submit_status="rejected_duplicate",
            )
        attempt["status"] = result["status"]
        for row in reversed(all_considered):
            if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                row["pre_attempt_status"] = row.get("status")
                row["status"] = "cycle_failed_submission"
                row["submit_status"] = result["status"]
                break
        ledger["cycle_attempts"].append(attempt)
        blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
        topic = str(candidate.get("topic") or "")
        if topic:
            blocked_topics.add(topic)
        if not refresh_candidates or batch >= search_batch_limit:
            ledger.update({"status": result["status"], "published": 0})
            _write_json(ledger_path, ledger)
            return ledger
    if ledger["cycle_attempts"]:
        last_status = str(ledger["cycle_attempts"][-1].get("status") or "failed")
        ledger.update({
            "status": "submit_retry_exhausted",
            "reason": f"no candidate accepted after {batch_limit} batch(es)",
            "last_attempt_status": last_status,
            "published": 0,
        })
    else:
        ledger.update({
            "status": "no_publishable_candidate",
            "reason": "no eligible non-duplicate memo",
        })
    _write_json(ledger_path, ledger)
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=_ledger_stamp())
    parser.add_argument("--include-archive", action="store_true")
    parser.add_argument("--refresh-candidates", action="store_true")
    parser.add_argument("--allow-tier2", action="store_true")
    parser.add_argument("--estimated-cost-usd", type=float, default=0.0)
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--refresh-top", type=int, default=_DEFAULT_REFRESH_TOP)
    parser.add_argument("--refresh-cooldown-hours", type=float, default=_DEFAULT_REFRESH_COOLDOWN_HOURS)
    parser.add_argument("--max-refresh-batches", type=int, default=_DEFAULT_MAX_REFRESH_BATCHES)
    parser.add_argument(
        "--published-topic-cooldown-days",
        type=int,
        default=_DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS,
    )
    parser.add_argument("--min-submit-sources", type=int, default=_DEFAULT_MIN_SUBMIT_SOURCES)
    parser.add_argument("--min-direct-submit-sources", type=int, default=_DEFAULT_MIN_DIRECT_SUBMIT_SOURCES)
    parser.add_argument("--decision-poll-attempts", type=int, default=_DEFAULT_DECISION_POLL_ATTEMPTS)
    parser.add_argument("--decision-poll-seconds", type=float, default=_DEFAULT_DECISION_POLL_SECONDS)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--retraction-check",
        choices=("metadata", "crossref", "skip"),
        default="metadata",
    )
    args = parser.parse_args()
    ledger = run_cycle(
        date=args.date,
        include_archive=args.include_archive,
        refresh_candidates=args.refresh_candidates,
        allow_tier2=args.allow_tier2,
        estimated_cost_usd=args.estimated_cost_usd,
        max_cost_usd=args.max_cost_usd,
        refresh_top=args.refresh_top,
        refresh_cooldown_hours=args.refresh_cooldown_hours,
        max_refresh_batches=args.max_refresh_batches,
        published_topic_cooldown_days=args.published_topic_cooldown_days,
        min_submit_sources=args.min_submit_sources,
        min_direct_submit_sources=args.min_direct_submit_sources,
        decision_poll_attempts=args.decision_poll_attempts,
        decision_poll_seconds=args.decision_poll_seconds,
        submit=args.submit,
        retraction_mode=args.retraction_check,
    )
    print(
        "[daily-alpha] "
        f"status={ledger['status']} submitted={ledger.get('submitted', 0)} "
        f"published={ledger['published']} "
        f"topic={ledger.get('submitted_topic') or ledger.get('published_topic') or ledger.get('candidate', {}).get('topic') or '-'}"
    )
    return 2 if ledger["status"] == "candidate_refresh_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
