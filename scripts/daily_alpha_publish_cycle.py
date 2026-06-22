"""Daily ReseaRka alpha memo publish cycle.

Safe by default: builds/reads the publish queue, selects at most one
publishable memo, writes a daily ledger, and only calls Researka when
`--submit` is explicit.
"""
# ruff: noqa: E402
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

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.alpha_selector import accepted_shape_bonus
from agent.domain_profile import domain_choices, domain_slug, load_domain_profile
from agent.llm_client import call_writer
from agent.publish_tier import publish_verdict
from agent.settings import load_settings
from agent.topic_discovery import cap_topic_slug
from scripts import alpha_publish_io as publish_io
from scripts import alpha_publish_status as publish_status

_RUNS = _ROOT / "runs"
_PUBLICATION_PATH = _ROOT / "topic_packs" / "publication.toml"
_PUBLISH_TIER_PATH = _ROOT / "topic_packs" / "publish_tier.toml"
_CLAIM_WORD = re.compile(r"[a-z][a-z0-9]*")
_CLUSTER_GENERIC_TOKENS = frozenset({
    "the", "and", "with", "from", "that", "this", "study", "studies",
    "patients", "participants", "adults", "risk", "effect", "effects",
    "lower", "higher", "high", "low", "adherence", "score", "scores",
    "significant", "association", "associated", "compared", "versus", "was",
    "were", "population", "exposure", "all",
    "confidence", "interval", "ratio", "meta", "analysis", "review",
    "control", "controls", "placebo", "once", "weekly", "daily", "without",
    "within", "over", "most", "not", "parent", "topic", "claim",
})
_COHERENCE_GENERIC_TOKENS = _CLUSTER_GENERIC_TOKENS | {
    "endpoint", "endpoints", "outcome", "outcomes", "intervention",
    "interventions", "comparator", "comparators", "group", "groups",
    "primary", "secondary", "measure", "measures",
}

Json = dict[str, Any]
Fetcher = Callable[[str], Json]
DecisionFetcher = Callable[[str], Json]
Submitter = Callable[[Json], Json]
MemoRefresher = Callable[[Path, Json], bool]
QueueBuilder = Callable[[Path, bool], Json]
PageFetcher = Callable[[str], Json]
SourcePaperFetcher = Callable[[str, int], list[Json]]


def _cycle_exit_code(
    ledger: Json, *, submit: bool, allow_pending_success: bool = False,
) -> int:
    return publish_status.cycle_exit_code(
        ledger, submit=submit, allow_pending_success=allow_pending_success,
    )


def _no_candidate_reason(considered: list[Json]) -> str:
    return publish_status.no_candidate_reason(considered)


def _publish_summary(ledger: Json) -> Json:
    return publish_status.publish_summary(ledger)


_SUBMIT_TOKEN_ENVS = (
    "RESEARKA_API_KEY_V4",
    "RESEARKA_API_TOKEN_V4",
    "RESEARKA_AGENT_TOKEN_V4",
    "RESEARCH_API_KEY_V4",
)
_PREFLIGHT_MODE_ENV = "RESEARKA_PREFLIGHT_QA"
_PREFLIGHT_ROOT_ENV = "RESEARKA_PREFLIGHT_QA_ROOT"
_PREFLIGHT_USE_M3_ENV = "RESEARKA_PREFLIGHT_USE_M3"
_PREFLIGHT_TIMEOUT_SECONDS = 90.0


def _terminate_process_group(proc: subprocess.Popen[str], sig: signal.Signals | int) -> None:
    if proc.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(proc.pid, int(sig))


def _run_subprocess(
    args: list[str], *, timeout: float, cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run child pipelines in one process group so stop/timeout kills descendants."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        cwd=cwd,
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


def _domain_alpha_memo_int(domain: str, name: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    domains = alpha.get("domains") if isinstance(alpha, dict) else {}
    domain_cfg = domains.get(domain) if isinstance(domains, dict) else {}
    if not isinstance(domain_cfg, dict) or name not in domain_cfg:
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(domain_cfg.get(name))))
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


def _alpha_memo_bool(name: str, default: bool) -> bool:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    if not isinstance(alpha, dict) or name not in alpha:
        return default
    return bool(alpha.get(name))


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
_EXHAUSTED_STATUSES = publish_status.EXHAUSTED_STATUSES
_TOPIC_EXHAUSTED_STATUSES = publish_status.TOPIC_EXHAUSTED_STATUSES
_FINGERPRINT_EXHAUSTED_STATUSES = publish_status.FINGERPRINT_EXHAUSTED_STATUSES
_REFRESHABLE_SOURCE_FLOOR_STATUSES = publish_status.REFRESHABLE_SOURCE_FLOOR_STATUSES
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
    return publish_io.read_json(path, default)


def _write_json(path: Path, payload: Any) -> None:
    publish_io.write_json(path, payload)


def _update_json_list(path: Path, mutate: Callable[[list[Any]], bool]) -> bool:
    return publish_io.update_json_list(path, mutate)


def _write_ledger(path: Path, ledger: Json) -> None:
    publish_io.write_ledger(path, ledger)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _regenerate_on_resubmit() -> bool:
    # Re-render the selected memo through the current writer just before
    # submission, so writer fixes reach already-built run dirs (the cycle reads
    # the on-disk alpha_memo.md, so a stale candidate would otherwise resubmit
    # pre-fix text). render is deterministic (no LLM call), so this is a no-op
    # for a freshly-built memo. Default on; kill switch REGENERATE_ON_RESUBMIT=off.
    return os.environ.get(
        "REGENERATE_ON_RESUBMIT", "on"
    ).strip().lower() not in {"0", "false", "no", "off"}


def _preflight_mode() -> str:
    mode = os.environ.get(_PREFLIGHT_MODE_ENV, "off").strip().lower()
    return mode if mode in {"shadow", "enforce"} else "off"


def _preflight_summary(report: Json) -> Json:
    reasons = report.get("blocked_reasons")
    reason_rows = reasons if isinstance(reasons, list) else []
    advisories = report.get("advisories")
    advisory_rows = advisories if isinstance(advisories, list) else []
    m3 = report.get("m3_result")
    return {
        "status": str(report.get("status") or "unknown"),
        "qa_version": str(report.get("qa_version") or ""),
        "safe_fixes_applied": report.get("safe_fixes_applied")
        if isinstance(report.get("safe_fixes_applied"), list) else [],
        "blocked_reason_codes": [
            str(row.get("code")) for row in reason_rows
            if isinstance(row, dict) and row.get("code")
        ],
        "advisory_codes": [
            str(row.get("code")) for row in advisory_rows
            if isinstance(row, dict) and row.get("code")
        ],
        "m3_status": str(m3.get("status") or "") if isinstance(m3, dict) else "",
    }


def _attach_preflight_summary(payload: Json, report: Json) -> None:
    evidence = payload.get("evidence_bundle")
    if not isinstance(evidence, dict):
        evidence = {}
        payload["evidence_bundle"] = evidence
    evidence["preflight_qa"] = _preflight_summary(report)


def _refresh_content_hash(payload: Json) -> None:
    markdown = str(payload.get("markdown") or payload.get("body_markdown") or "")
    if markdown:
        payload["content_hash"] = "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _run_preflight_qa(payload: Json, run_dir: Path) -> tuple[Json | None, Json | None]:
    mode = _preflight_mode()
    if mode == "off":
        return payload, None

    tool_root = Path(
        os.environ.get(_PREFLIGHT_ROOT_ENV, str(_ROOT.parent / "researka-preflight-qa")),
    ).expanduser()
    input_path = run_dir / "researka_preflight_input.json"
    report_path = run_dir / "researka_preflight_report.json"
    clean_path = run_dir / "researka_preflight_cleaned_payload.json"
    _write_json(input_path, payload)

    cmd = [
        sys.executable, "-m", "preflight_qa", "check",
        "--input", str(input_path),
        "--out", str(report_path),
        "--clean-out", str(clean_path),
    ]
    if _env_truthy(_PREFLIGHT_USE_M3_ENV):
        cmd.append("--use-m3")
    try:
        proc = _run_subprocess(cmd, timeout=_PREFLIGHT_TIMEOUT_SECONDS, cwd=tool_root)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report: Json = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "safe_fixes_applied": [],
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_runtime_error",
                "severity": "minor",
                "message": f"{type(exc).__name__}: {exc}",
            }],
        }
        _write_json(report_path, report)
    else:
        raw_report = _json(report_path, {})
        report = raw_report if isinstance(raw_report, dict) else {}
        if proc.returncode not in {0, 2}:
            report = {
                "status": "pass",
                "qa_version": "preflight-v2",
                "safe_fixes_applied": [],
                "blocked_reasons": [],
                "advisories": [{
                    "code": "preflight_runtime_error",
                    "severity": "minor",
                    "message": (proc.stderr or proc.stdout or "preflight process failed")[:500],
                }],
            }
            _write_json(report_path, report)

    if mode == "shadow":
        _attach_preflight_summary(payload, report)
        return payload, report
    if report.get("status") != "pass":
        _attach_preflight_summary(payload, report)
        return payload, report
    cleaned = _json(clean_path, {})
    if not isinstance(cleaned, dict) or not cleaned:
        report = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "safe_fixes_applied": [],
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_missing_cleaned_payload",
                "severity": "minor",
                "message": "Preflight passed but did not write a cleaned payload.",
            }],
        }
        _write_json(report_path, report)
        _attach_preflight_summary(payload, report)
        return payload, report
    _attach_preflight_summary(cleaned, report)
    _refresh_content_hash(cleaned)
    return cleaned, report


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


def _stage_blockers(run: Path) -> list[str]:
    required = (
        "alpha_memo.md",
        "opportunities_gate.json",
        "fact_lanes.json",
        "all_facts.json",
        "claim_receipt_matrix.json",
        "typed_counter_evidence.json",
        "novelty_delta.json",
        "memo_audit.json",
    )
    return [
        f"missing_{name.rsplit('.', 1)[0]}"
        for name in required if not run.joinpath(name).exists()
    ]


def _verdict_for_run(run: Path) -> Json:
    if _can_recompute_verdict(run):
        return publish_verdict(run)
    data = _json(run / "publish_verdict.json", {})
    if isinstance(data, dict) and data:
        return data
    blockers = _stage_blockers(run)
    return {
        "topic": _topic(run),
        "run_dir": str(run.relative_to(_ROOT)) if run.is_relative_to(_ROOT) else str(run),
        "decision": "not_ready",
        "publish_tier": "UNBUILT",
        "blockers": blockers,
        "stage": blockers[0] if blockers else "not_ready",
    }


def _run_domain(run: Path, verdict: Json) -> str:
    return (
        domain_slug(verdict.get("domain"))
        or domain_slug(_json(run / "MANIFEST.json", {}).get("domain"))
        or domain_slug(_json(run / "search_trace.json", {}).get("domain"))
    )


def _run_domain_required(run: Path, verdict: Json) -> str:
    domain = _run_domain(run, verdict)
    if not domain:
        raise ValueError(f"missing domain metadata for run: {run}")
    return domain


def _with_domain_metadata(verdict: Json, run: Path, fallback: Json | None = None) -> Json:
    domain = _run_domain(run, verdict) or domain_slug((fallback or {}).get("domain"))
    return (
        verdict | {"domain": load_domain_profile(domain).as_metadata(), "domain_slug": domain}
        if domain else verdict
    )


def _refresh_claim_cluster(run: Path) -> None:
    """Recompute claim_cluster.json (and its homogeneity flag) from the run's
    A_core facts before the verdict reads it.

    The flag is only written at fresh-build time; the daily refresh/retry path
    never re-clustered, so stale and pre-fix runs lack it and default to
    homogeneous=True — heterogeneous bundles then surface as single-claim memos
    and reject for incoherence (the dominant failure). Only runs missing the flag
    are recomputed (fresh builds keep theirs, so no repeat model cost). Degrade
    silently to the existing cluster on any failure — never block submission."""
    existing = _json(run / "claim_cluster.json", {})
    if isinstance(existing, dict) and "homogeneous" in existing:
        return
    facts = _json(run / "all_facts.json", None)
    lanes_raw = _json(run / "fact_lanes.json", None)
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return
    try:
        from agent.claim_clusterer import densest_claim_cluster
        facts_by_id = {
            str(f.get("fact_id")): f for f in facts if isinstance(f, dict)
        }
        lanes = {
            str(v.get("fact_id")): str(v.get("lane") or "")
            for v in lanes_raw.get("verdicts", []) if isinstance(v, dict)
        }
        topic = run.name.split("-evidence-", 1)[0]
        cluster = densest_claim_cluster(
            facts_by_id, lanes, topic,
            min_sources=_alpha_memo_int("min_cluster_source_papers", 3),
        )
        if cluster.get("lead_fact_ids"):
            _write_json(run / "claim_cluster.json", cluster)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return


def _write_publish_verdict(run: Path) -> Json:
    _refresh_claim_cluster(run)
    verdict = publish_verdict(run)
    _write_json(run / "publish_verdict.json", verdict)
    _run_advisories(run, verdict)
    return verdict


def _advisory_on(flag: str) -> bool:
    return os.environ.get(flag, "").strip().lower() in ("1", "true", "yes", "on")


def _run_advisories(run: Path, verdict: Json) -> None:
    """Opt-in, advisory post-verdict analyses — each env-gated, isolated, and
    incapable of blocking or changing the publish ``decision``.

    Off by default. Enable per-feature (e.g. in the systemd EnvironmentFile):
      - ``ALPHA_CITATION_VERIFY``   external citation-existence check
      - ``ALPHA_CONSENSUS_SPLIT``   evidence-map agree/disagree/open partition
      - ``ALPHA_QUALITY_SCORECARD`` composed multi-dimension quality scorecard
    Each writes its own sidecar + a compact verdict summary, and degrades
    silently so it can never break publishing. Order matters only in that the
    scorecard reads the citation sidecar when both are enabled.
    """
    mutated = False
    if _advisory_on("ALPHA_CITATION_VERIFY"):
        with suppress(Exception):  # advisory: best-effort, must never crash the cycle
            from agent.citation_verify import verify_run
            rep = verify_run(run)
            verdict["citation_verify"] = {
                "checked": rep.get("checked"), "counts": rep.get("counts"),
                "has_hallucinated": rep.get("has_hallucinated"),
            }
            mutated = True
    if _advisory_on("ALPHA_CONSENSUS_SPLIT"):
        with suppress(Exception):  # advisory: best-effort, must never crash the cycle
            from agent.consensus_split import partition
            raw = json.loads((run / "all_facts.json").read_text(encoding="utf-8"))
            report = partition(raw if isinstance(raw, list) else [])
            _write_json(run / "consensus_split.json", report.as_dict())
            verdict["consensus_split"] = {
                "consensus_direction": report.consensus_direction,
                "has_disagreement": report.has_disagreement,
                "summary": report.summary,
            }
            mutated = True
    if _advisory_on("ALPHA_QUALITY_SCORECARD"):
        with suppress(Exception):  # advisory: best-effort, must never crash the cycle
            from agent.quality_scorecard import scorecard
            sc = scorecard(run)
            verdict["quality_scorecard"] = {
                "overall": sc.get("overall"), "band": sc.get("band"),
                "floor_breaches": sc.get("floor_breaches"),
            }
            mutated = True
    if mutated:
        with suppress(OSError):
            _write_json(run / "publish_verdict.json", verdict)


def _current_selection_verdict(verdict: Json, root: Path) -> Json:
    run_dir = _run_path(root, verdict.get("run_dir"))
    if not run_dir.exists():
        return verdict
    current = _verdict_for_run(run_dir)
    if not current:
        return verdict
    if current.get("decision") == "not_ready" and verdict.get("decision") != "not_ready":
        return verdict
    private = {k: v for k, v in verdict.items() if str(k).startswith("_")}
    if verdict.get("_claim_cluster_candidate"):
        private.update({
            "topic": verdict.get("topic"),
            "receipt_expansion": verdict.get("receipt_expansion"),
            "subtopic_recommendations": verdict.get("subtopic_recommendations"),
        })
    return _with_domain_metadata(current | private, run_dir, verdict)


def _current_submit_verdict(verdict: Json, root: Path) -> Json:
    if verdict.get("_claim_cluster_candidate"):
        return verdict
    run_dir = _run_path(root, verdict.get("run_dir"))
    if not run_dir.exists():
        return verdict
    if (
        not _can_recompute_verdict(run_dir)
        and not (run_dir / "publish_verdict.json").exists()
    ):
        return verdict
    current = _verdict_for_run(run_dir)
    if not isinstance(current, dict) or not current:
        return verdict
    private = {k: v for k, v in verdict.items() if str(k).startswith("_")}
    merged = current | private
    for key in ("run_dir", "topic"):
        if not merged.get(key) and verdict.get(key):
            merged[key] = verdict[key]
    return _with_domain_metadata(merged, run_dir, verdict)


def _pre_submit_hold(
    verdict: Json,
    root: Path,
    *,
    allow_tier2: bool,
    min_source_count: int,
    min_direct_source_count: int,
) -> Json:
    source_count = _source_count(verdict, root)
    direct_source_count = _direct_source_count(verdict, root)
    corpus_source_count = _corpus_source_count(verdict, root)
    hold = {
        "source_count": source_count,
        "direct_source_count": direct_source_count,
        "corpus_ab_paper_count": corpus_source_count,
        "min_source_count": min_source_count,
        "min_direct_source_count": min_direct_source_count,
        "current_decision": verdict.get("decision"),
        "blockers": verdict.get("blockers") or [],
    }
    approved = _selection_approved(
        verdict,
        root,
        allow_tier2=allow_tier2,
        source_count=source_count,
        direct_source_count=direct_source_count,
        min_source_count=min_source_count,
        min_direct_source_count=min_direct_source_count,
    ) or _agent_repair_passed_submit_gates(
        verdict,
        source_count=source_count,
        direct_source_count=direct_source_count,
        min_source_count=min_source_count,
        min_direct_source_count=min_direct_source_count,
    )
    if not _has_memo(verdict, root):
        return hold | {"status": "missing_alpha_memo"}
    if not approved:
        return hold | {"status": "stale_publish_verdict"}
    if not _has_falsifier(verdict, root):
        return hold | {"status": "memo_missing_falsifier"}
    missing_audit_sidecars = _missing_audit_sidecars(verdict, root)
    if missing_audit_sidecars:
        return hold | {
            "status": "memo_missing_audit_sidecars",
            "missing_audit_sidecars": missing_audit_sidecars,
        }
    cluster_backed = _llm_cluster_backed(verdict, root)
    cluster_floor = _alpha_memo_int("min_cluster_source_papers", 3)
    eff_min_source_count = (
        min(min_source_count, cluster_floor) if cluster_backed else min_source_count
    )
    eff_min_direct_count = (
        min(min_direct_source_count, cluster_floor)
        if cluster_backed else min_direct_source_count
    )
    if source_count < eff_min_source_count:
        status = (
            "corpus_source_floor_below_min"
            if corpus_source_count < eff_min_source_count else
            "memo_source_floor_below_min"
        )
        return hold | {"status": status}
    if direct_source_count < eff_min_direct_count:
        return hold | {"status": "direct_source_floor_below_min"}
    if (
        verdict.get("surface_type") != "evidence_map"
        and not cluster_backed
        and not _direct_receipts_share_shape(verdict, root, min_direct_source_count)
    ):
        return hold | {"status": "receipt_shape_mismatch"}
    return hold | {"status": ""}


def _reload_verdict_after_memo_refresh(verdict: Json, run_dir: Path) -> Json:
    if not _can_recompute_verdict(run_dir):
        return verdict
    try:
        refreshed = _write_publish_verdict(run_dir)
    except (OSError, ValueError, TypeError, KeyError):
        return verdict
    refreshed = _with_domain_metadata(refreshed, run_dir, verdict)
    repair_decision = verdict.get("_repair_decision")
    if repair_decision is not None:
        refreshed["_repair_decision"] = repair_decision
    if verdict.get("_claim_cluster_candidate"):
        refreshed.update({
            k: v for k, v in verdict.items()
            if str(k).startswith("_")
            or k in {
                "topic", "decision", "publish_tier", "blockers",
                "receipt_expansion", "subtopic_recommendations",
            }
        })
    return refreshed


def _build_queue(
    runs_root: Path, include_archive: bool, domain: str | None = None,
) -> Json:
    """Build current verdicts without mutating run artifacts."""
    patterns = ["*-evidence-*"]
    if include_archive:
        patterns += ["_archive/*/*-evidence-*"]
    latest: dict[str, Path] = {}
    for pattern in patterns:
        for path in runs_root.glob(pattern):
            run = path if path.is_dir() else path.parent
            topic = _topic(run)
            if topic not in latest or run.name > latest[topic].name:
                latest[topic] = run
    seed_tokens = _domain_seed_tokens(domain)
    domain_rows = []
    missing_domain_count = 0
    untagged_seed_claimed_count = 0
    for run in latest.values():
        row = _verdict_for_run(run)
        run_domain = _run_domain(run, row)
        if not run_domain:
            # Universal claim rule (no hardcoded slug): an untagged run joins the
            # domain being built when its topic sits in that domain's seed corpus.
            # The default domain is the unscoped catch-all (empty seed_tokens) and
            # claims untagged runs directly; scoped domains claim seed members only.
            if domain and (
                not seed_tokens
                or _family_keys(_family_values(row), set()) & seed_tokens
            ):
                run_domain = domain
                untagged_seed_claimed_count += 1
            else:
                missing_domain_count += 1
                continue
        if domain and run_domain != domain:
            continue
        row = row | {
            "domain": load_domain_profile(run_domain).as_metadata(),
            "domain_slug": run_domain,
        }
        domain_rows.append(row)
    rows = domain_rows
    seed_scope_dropped_count = 0
    seed_scope_fallback_count = 0
    if seed_tokens:
        scoped_rows = [
            row for row in domain_rows
            if _family_keys(_family_values(row), set()) & seed_tokens
        ]
        seed_scope_dropped_count = len(domain_rows) - len(scoped_rows)
        rows = scoped_rows
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
        "not_ready": [
            r for r in valid if r.get("decision") == "not_ready"
        ],
        "_meta": {
            "missing_domain_count": missing_domain_count,
            "untagged_seed_claimed_count": untagged_seed_claimed_count,
            "seed_scope_dropped_count": seed_scope_dropped_count,
            "seed_scope_fallback_count": seed_scope_fallback_count,
            "seed_scope_fallback_used": bool(seed_scope_fallback_count),
        },
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
    raw_payload = {
        "cited": cited,
        "dois": dois,
        "direction": direction,
    }
    domain = domain_slug(verdict.get("domain"))
    if domain:
        raw_payload["domain"] = domain
    raw = json.dumps(raw_payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _selection_topic(verdict: Json) -> str:
    return str(verdict.get("_claim_cluster_topic") or verdict.get("topic") or "")


def _topic_from_run_ref(value: Any) -> str:
    name = Path(str(value or "")).name
    return name.split("-evidence-", 1)[0] if "-evidence-" in name else ""


def _family_values(verdict: Json) -> list[str]:
    if verdict.get("_claim_cluster_candidate"):
        values = [
            _selection_topic(verdict),
            str(verdict.get("topic_family") or ""),
        ]
        return [v for v in dict.fromkeys(values) if v]
    values = [
        _selection_topic(verdict),
        str(verdict.get("topic") or ""),
        str(verdict.get("topic_family") or ""),
        str(verdict.get("parent_topic") or verdict.get("_parent_topic") or ""),
        _topic_from_run_ref(verdict.get("run_dir")),
    ]
    return [v for v in dict.fromkeys(values) if v]


def _family_tokens(value: str) -> set[str]:
    return {
        token for token in _CLAIM_WORD.findall(value.lower())
        if len(token) >= 5 and token not in _CLUSTER_GENERIC_TOKENS
    }


def _common_family_tokens(values: Iterable[str]) -> set[str]:
    counts: dict[str, int] = {}
    total = 0
    for value in values:
        tokens = _family_tokens(value)
        if not tokens:
            continue
        total += 1
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
    return {
        token for token, count in counts.items()
        if count > max(8, total // 6)
    }


def _family_keys(values: Iterable[str], common_tokens: set[str]) -> set[str]:
    keys: set[str] = set()
    for value in values:
        exact = _canonical_family_key(value)
        if exact:
            keys.add(exact)
        keys.update(
            "token:" + token
            for token in _family_tokens(value)
            if token not in common_tokens
        )
    return keys


def _canonical_family_key(value: str) -> str:
    exact = "_".join(_CLAIM_WORD.findall(str(value).lower()))
    return "topic:" + exact if exact else ""


def _canonical_family_keys(values: Iterable[str]) -> set[str]:
    return {
        key for value in values
        if (key := _canonical_family_key(str(value)))
    }


def _domain_seed_tokens(domain: str | None) -> set[str]:
    if not domain or domain == load_domain_profile(None).slug:
        return set()
    with suppress(OSError, tomllib.TOMLDecodeError, ValueError):
        data = tomllib.loads(load_domain_profile(domain).seed_topics_path.read_text(
            encoding="utf-8",
        ))
        seeds = data.get("seeds")
        topics = seeds.get("topics") if isinstance(seeds, dict) else None
        if isinstance(topics, list):
            return _family_keys((str(t) for t in topics), set())
    return set()


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


def _cluster_tokens(fact: Json, parent: str) -> set[str]:
    text = " ".join(
        str(fact.get(key) or "") for key in (
            "canonical_phrase", "population", "intervention", "endpoint", "comparator",
        )
    )
    parent_tokens = set(_CLAIM_WORD.findall(parent.lower()))
    return set(_CLAIM_WORD.findall(text.lower())) - parent_tokens - _CLUSTER_GENERIC_TOKENS


def _cluster_has_coherent_component(
    verdict: Json, cluster_ids: list[str], root: Path, *, min_direct_source_count: int,
) -> bool:
    run_dir = _run_path(root, verdict.get("run_dir"))
    facts = _json(run_dir / "all_facts.json", [])
    lanes_raw = _json(run_dir / "fact_lanes.json", {})
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return False
    lanes = {
        str(row.get("fact_id") or ""): str(row.get("lane") or "")
        for row in lanes_raw.get("verdicts", [])
        if isinstance(row, dict)
    }
    by_id = {
        str(fact.get("fact_id") or ""): fact
        for fact in facts if isinstance(fact, dict)
    }
    parent = str(verdict.get("topic") or "")
    usable = [
        (fid, by_id[fid], _source_key_from_fact(by_id[fid]))
        for fid in cluster_ids
        if fid in by_id and lanes.get(fid) == "A_core" and _source_key_from_fact(by_id[fid])
    ]
    for anchor_id, anchor, _source in usable:
        anchor_tokens = _cluster_tokens(anchor, parent)
        if not anchor_tokens:
            continue
        sources = {
            source for fid, fact, source in usable
            if fid == anchor_id or len(anchor_tokens & _cluster_tokens(fact, parent)) >= 2
        }
        if len(sources) >= min_direct_source_count:
            return True
    return False


def _claim_cluster_repairable(verdict: Json, rec: Json) -> bool:
    decision = str(verdict.get("decision") or "")
    if decision in _AGENT_REPAIR_DECISIONS:
        return True
    if decision != "curation_needed" or rec.get("reason") != "source_coherent_child_cluster":
        return False
    if int(verdict.get("alpha_score") or 0) <= 0:
        return False
    blockers = verdict.get("blockers")
    return not (
        isinstance(blockers, list)
        and any(str(blocker).startswith("blocked_label:") for blocker in blockers)
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
                or not _cluster_has_coherent_component(
                    verdict, ids, runs_root,
                    min_direct_source_count=min_direct_source_count,
                )
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


def _with_repairable_candidates(
    queue: Json, runs_root: Path, domain: str | None = None,
) -> Json:
    repairable = _repairable_candidate_verdicts(runs_root, domain)
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


def _row_domain(row: Json) -> str:
    return (
        domain_slug(row.get("domain_slug"))
        or domain_slug(row.get("domain"))
        or load_domain_profile(None).slug
    )


def _ledger_domain(ledger: Json) -> str:
    candidate = ledger.get("candidate")
    if not isinstance(candidate, dict):
        candidate = {}
    return (
        domain_slug(ledger.get("domain"))
        or domain_slug(candidate.get("domain"))
        or load_domain_profile(None).slug
    )


def _same_domain(record_domain: str, domain: str | None) -> bool:
    if not domain:
        return True
    return record_domain.removesuffix("_research") == domain.removesuffix("_research")


def _seen_submission_fingerprints_for_domain(path: Path, domain: str | None) -> set[str]:
    data = _json(path, [])
    if isinstance(data, list):
        return {
            str(x.get("fingerprint"))
            for x in data
            if isinstance(x, dict) and _same_domain(_row_domain(x), domain)
        }
    return set()


def _same_memo_seen(
    path: Path, fingerprint: str, memo_sha256: str, domain: str | None = None,
) -> bool:
    data = _json(path, [])
    if not isinstance(data, list):
        return False
    for row in data:
        if not isinstance(row, dict) or row.get("fingerprint") != fingerprint:
            continue
        if not _same_domain(_row_domain(row), domain):
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
    record = {
        "date": date,
        "domain": candidate.get("domain"),
        "topic": candidate.get("topic"),
        "run_dir": candidate.get("run_dir"),
        "fingerprint": candidate.get("memo_fingerprint"),
        "bundle_signature": _bundle_signature(candidate, runs_root),
        "memo_sha256": _memo_sha256(candidate, runs_root),
        "submission_id": submission_id,
    }
    if submit_status:
        record["submit_status"] = submit_status

    def append_record(records: list[Any]) -> bool:
        records.append(record)
        return True

    _update_json_list(path, append_record)


def _submission_record_patch(ledger: Json) -> Json:
    patch: Json = {}
    for key in (
        "domain",
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


def _fingerprint_attempt_count(
    path: Path, fingerprint: str, domain: str | None = None,
) -> int:
    data = _json(path, [])
    if not isinstance(data, list):
        return 0
    return sum(
        1
        for row in data
        if isinstance(row, dict)
        and row.get("fingerprint") == fingerprint
        and _same_domain(_row_domain(row), domain)
    )


def _repairable_rejected_fingerprints(
    ledger_dir: Path, domain: str | None = None,
) -> set[str]:
    retryable: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        if not _same_domain(_ledger_domain(ledger), domain):
            continue
        for fp, _run_ref, _decision in _repairable_submission_records(ledger):
            retryable.add(fp)
    return retryable


def _repairable_decisions_by_fingerprint(
    ledger_dir: Path, domain: str | None = None,
) -> dict[str, Json]:
    retryable: dict[str, Json] = {}
    for path in sorted(ledger_dir.glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        if not _same_domain(_ledger_domain(ledger), domain):
            continue
        for fp, _run_ref, decision in _repairable_submission_records(ledger):
            if fp in retryable:
                continue
            retryable[fp] = decision
    return retryable


def _repairable_candidate_verdicts(
    runs_root: Path, domain: str | None = None,
) -> list[Json]:
    verdicts: list[Json] = []
    seen: set[str] = set()
    for path in sorted((runs_root / "_daily_ledger").glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict):
            continue
        if not _same_domain(_ledger_domain(ledger), domain):
            continue
        for fp, run_ref, _decision in _repairable_submission_records(ledger):
            if fp in seen:
                continue
            run_dir = _run_path(runs_root, run_ref)
            verdict = _json(run_dir / "publish_verdict.json", {})
            if not isinstance(verdict, dict) or not verdict:
                continue
            run_domain = _run_domain(run_dir, verdict)
            if domain and run_domain != domain:
                continue
            if run_domain:
                verdict = verdict | {"domain": load_domain_profile(run_domain).as_metadata()}
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


def _accepted_shape_profiles(
    runs_root: Path, *, limit: int = 25, domain: str | None = None,
) -> list[Json]:
    profiles: list[Json] = []
    ledger_dir = runs_root / "_daily_ledger"
    for path in sorted(ledger_dir.glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or ledger.get("final_verdict") != "accepted":
            continue
        if not _same_domain(_ledger_domain(ledger), domain):
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


def _recently_published_topics(
    ledger_dir: Path, *, days: int, domain: str | None = None,
) -> set[str]:
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
        if not _same_domain(_ledger_domain(ledger), domain):
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


def _recent_negative_topics(
    ledger_dir: Path, *, days: int, domain: str | None = None,
) -> set[str]:
    cutoff = time.time() - (max(0, days) * 86400)
    topics: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        with suppress(OSError):
            if path.stat().st_mtime < cutoff:
                continue
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or not _same_domain(_ledger_domain(ledger), domain):
            continue
        decision = ledger.get("researka_decision")
        if not isinstance(decision, dict):
            decision = {}
        rejected = (
            ledger.get("final_verdict") == "rejected"
            or ledger.get("status") == "reviewer_rejected"
            or decision.get("decision") == "reject"
        )
        unsupported = str(decision.get("claim_support_verdict") or "").lower() == "unsupported"
        if not (rejected and unsupported and not _repairable_rejection(decision)):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        for value in (
            ledger.get("submitted_topic"),
            ledger.get("published_topic"),
            ledger.get("topic_family"),
            candidate.get("topic"),
            candidate.get("topic_family"),
        ):
            if value:
                topics.add(str(value))
    return topics


def _stamp_ts(value: Any) -> float | None:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%dT%H-%M-%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        with suppress(ValueError):
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.UTC).timestamp()
    return None


def _recent_submission_topics(
    path: Path, *, days: int, domain: str | None = None, now: float | None = None,
) -> set[str]:
    cutoff = (time.time() if now is None else now) - (max(0, days) * 86400)
    data = _json(path, [])
    if not isinstance(data, list):
        return set()
    topics: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        if not _same_domain(_row_domain(row), domain):
            continue
        ts = _stamp_ts(row.get("date"))
        if ts is None or ts < cutoff:
            continue
        topic = str(row.get("topic") or "").strip()
        run_topic = _topic_from_run_ref(row.get("run_dir"))
        topics.update(t for t in (topic, run_topic) if t)
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
        if str(verdict.get("surface_type") or "") == "evidence_map":
            landscape = len(_map_citable_facts(verdict, root))
            if landscape:
                return landscape
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


def _memo_source_facts(
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
    source_facts: list[Json] = []
    for fid in ids:
        if lane_names is not None and lanes.get(fid) not in lane_names:
            continue
        fact = by_id.get(fid) or {}
        key = _source_key_from_fact(fact)
        if not key or key in seen:
            continue
        seen.add(key)
        source_facts.append(fact)
    return source_facts


def _normalize_paper(paper: Json) -> Json:
    return {
        "doi": str(paper.get("doi") or ""),
        "pmid": str(paper.get("pmid") or ""),
        "title": str(paper.get("title") or ""),
        "journal": str(paper.get("journal") or ""),
        "url": paper.get("url") or paper.get("source_url"),
        "year": paper.get("year"),
        "is_retracted": bool(paper.get("is_retracted")),
    }


def _memo_source_papers(
    verdict: Json,
    root: Path,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
    lane_names: set[str] | None = None,
) -> list[Json]:
    papers: list[Json] = []
    for fact in _memo_source_facts(verdict, root, section_names, lane_names):
        paper = fact.get("source_paper") or {}
        if isinstance(paper, dict):
            papers.append(_normalize_paper(paper))
    return papers


def _landscape_source_facts(verdict: Json, root: Path, *, cap: int = 40) -> list[Json]:
    """Every A_core fact in the run, deduped to one per distinct source paper —
    the full evidence-map landscape, newest-first and capped for readability.

    The memo narrows its receipts to the single-claim cluster the alpha lane
    leads with (e.g. metformin renders 6 of its 31 A_core source papers). A map
    is a landscape, not a single claim: it must cite its whole A_core breadth or
    it under-cites and trips Researka's >=10-citation intake gate. Reading the
    lanes directly recovers the sources the memo dropped."""
    run_dir = _run_path(root, verdict.get("run_dir"))
    facts = _json(run_dir / "all_facts.json", [])
    lanes_raw = _json(run_dir / "fact_lanes.json", {})
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return []
    lane = {
        str(row.get("fact_id") or ""): str(row.get("lane") or "")
        for row in lanes_raw.get("verdicts", [])
        if isinstance(row, dict)
    }
    seen: set[str] = set()
    picked: list[Json] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if lane.get(str(fact.get("fact_id") or "")) != "A_core":
            continue
        key = _source_key_from_fact(fact)
        if not key or key in seen:
            continue
        seen.add(key)
        picked.append(fact)
    picked.sort(
        key=lambda f: _year(
            f.get("canonical_year") or (f.get("source_paper") or {}).get("year")
        ) or 0,
        reverse=True,
    )
    return picked[:cap]


def _map_citable_facts(verdict: Json, root: Path) -> list[Json]:
    """A_core landscape facts whose source is citable (title + resolvable id) —
    exactly the rows an evidence map ships. Shared by the submit gate's
    citation-floor check and the payload builder so the held/submitted decision
    matches what is actually sent (the gate must see the full landscape, not the
    memo's narrowed cluster, or it holds a source-rich map below floor)."""
    return [
        f for f in _landscape_source_facts(verdict, root)
        if str((f.get("source_paper") or {}).get("title") or "").strip()
        and (str((f.get("source_paper") or {}).get("doi") or "").strip()
             or str((f.get("source_paper") or {}).get("pmid") or "").strip())
    ]


def _evidence_map_header(topic: str, n: int) -> tuple[str, str]:
    """Canonical title + abstract for an evidence map, both rendered from the one
    cited-source count `n`.

    Structured rendering, not regex reconciliation: the map's title, abstract,
    Findings Map table, source bundle, and section text all derive from the same
    `n` (the count of sources actually cited), so they cannot disagree — the
    "17 in the title / 5 in the abstract" class of bug is unrepresentable. The
    memo's own narrow single-claim headline/thesis is bypassed for the map (it
    counts the cluster, not the landscape). Universal — `topic` is the only input
    beyond the count; no per-topic or per-phrasing literals.
    """
    label = " ".join(str(topic or "topic").replace("_", " ").split())
    label = (label[:1].upper() + label[1:]) if label else "Topic"
    title = f"{label}: evidence map — {n} findings across {n} sources"
    abstract = (
        f"Scoping review of {label}: {n} findings across {n} independent "
        "sources, catalogued by population, comparator, endpoint, and effect "
        "size. Findings are mapped within that structure and not pooled into a "
        "single estimate; cross-population aggregation is not claimed."
    )
    return title, abstract


def _findings_map_table(facts: list[Json]) -> str:
    """A domain-stratified source table: one row per A_core source carrying its
    own population, comparator, finding, and a resolvable identifier, so every
    row is verifiable against the source bundle (the attribution the reviewer
    checks before accepting a map). Universal — populated from generic fact
    fields, no domain text."""
    def cell(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split()).replace("|", "/")
        if len(text) > limit:
            return text[:limit].rstrip() + "…"
        return text or "—"

    rows = [
        "| Population | Comparator | Finding | Source |",
        "|---|---|---|---|",
    ]
    for fact in facts:
        paper = fact.get("source_paper") or {}
        doi = str(paper.get("doi") or "").strip()
        pmid = str(paper.get("pmid") or "").strip()
        ident = f"doi:{doi}" if doi else (f"pmid:{pmid}" if pmid else "")
        year = _year(fact.get("canonical_year") or paper.get("year"))
        source = " ".join(p for p in (str(year) if year else "", ident) if p)
        rows.append(
            f"| {cell(fact.get('population'), 38)} "
            f"| {cell(fact.get('comparator'), 28)} "
            f"| {cell(fact.get('canonical_phrase'), 90)} "
            f"| {source or cell(paper.get('title'), 40)} |"
        )
    return "\n".join(rows)


def _direct_source_count(verdict: Json, root: Path) -> int:
    # A map cites its full A_core landscape (the rows it ships), not the memo's
    # narrowed single-claim cluster — so every source-floor and citation-floor
    # gate sees what is actually submitted, not the 6 the memo happened to list.
    if str(verdict.get("surface_type") or "") == "evidence_map":
        return len(_map_citable_facts(verdict, root))
    return len(_memo_source_papers(verdict, root, ("Evidence",), {"A_core"}))


def _bundle_signature(verdict: Json, root: Path) -> str:
    """Content key = the set of cited source identifiers, topic-name-independent.

    Two word-salad child topics of one parent (semaglutide_weight vs
    semaglutide_loss) cite the same papers and render near-identical content, but
    their topic names give them different memo_fingerprints, so both submit and
    Researka rejects the second as an exact-content duplicate. Keying on the
    cited DOIs/PMIDs catches that regardless of topic name. Empty for a bundle
    too thin (<2 ids) to dedup reliably.
    """
    ids = sorted({
        (str(p.get("doi") or "").strip().lower()
         or f"pmid:{str(p.get('pmid') or '').strip()}")
        for p in _memo_source_papers(verdict, root, ("Evidence",), {"A_core"})
    } - {"", "pmid:"})
    if len(ids) < 2:
        return ""
    return hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()


def _published_bundle_signatures(
    path: Path, domain: str | None, root: Path,
) -> set[str]:
    """Bundle signatures of already-PUBLISHED/accepted submissions in this domain.

    Only published content can be duplicated; rejected memos are not live, so a
    repaired resubmit reusing the same papers must NOT be blocked here.
    """
    data = _json(path, [])
    sigs: set[str] = set()
    if not isinstance(data, list):
        return sigs
    for row in data:
        if not isinstance(row, dict) or not _same_domain(_row_domain(row), domain):
            continue
        if not (row.get("published") or row.get("final_verdict") == "accepted"):
            continue
        sig = str(row.get("bundle_signature") or "") or _bundle_signature(row, root)
        if sig:
            sigs.add(sig)
    return sigs


def _shape_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_shape_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_shape_text(v) for v in value)
    return str(value or "")


def _shape_tokens(fact: Json, fields: tuple[str, ...]) -> set[str]:
    text = " ".join(_shape_text(fact.get(field)) for field in fields)
    return {
        token for token in _CLAIM_WORD.findall(text.lower())
        if len(token) >= 4 and token not in _COHERENCE_GENERIC_TOKENS
    }


def _llm_cluster_backed(verdict: Json, root: Path) -> bool:
    """Whether the memo leads with an M3-validated claim cluster. publish_tier
    waives single-claim shape coherence for these (the writer confirmed the
    receipts make one claim, and it already gated the cluster's source count for
    ready_to_publish). The submit gate must agree, or a cluster-backed memo that
    publish_tier passed gets re-blocked here on the very check publish waived."""
    run_dir = _run_path(root, verdict.get("run_dir"))
    cluster = _json(run_dir / "claim_cluster.json", {})
    ids = cluster.get("lead_fact_ids") if isinstance(cluster, dict) else None
    return bool(ids)


def _direct_receipts_share_shape(
    verdict: Json, root: Path, min_direct_source_count: int,
) -> bool:
    if min_direct_source_count <= 0:
        return True
    facts = _memo_source_facts(verdict, root, ("Evidence",), {"A_core"})
    if len(facts) < min_direct_source_count:
        return True
    shared_dims = 0
    checked_dims = 0
    for fields in (("population",), ("intervention",), ("comparator",), ("endpoint",)):
        shapes = [_shape_tokens(fact, fields) for fact in facts]
        if not all(shapes):
            continue
        checked_dims += 1
        if set.intersection(*shapes):
            shared_dims += 1
    if checked_dims:
        return shared_dims >= (2 if checked_dims >= 2 else 1)
    shapes = [_shape_tokens(fact, ("canonical_phrase", "claim", "finding")) for fact in facts]
    return not all(shapes) or bool(set.intersection(*shapes))


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
        doi = str(paper.get("doi") or "").strip() or None
        pmid = str(paper.get("pmid") or "").strip() or None
        # Researka rejects bundles carrying unverifiable sources. A receipt is
        # only citable with a resolvable identifier; drop any title-only source.
        # The accepted bundle schema has no pmid field, so a PMID-only paper is
        # made verifiable through its resolvable PubMed URL rather than presented
        # as identifier-less.
        if not title or not (doi or pmid):
            continue
        url = paper.get("url") or None
        if not url and pmid:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        bundle.append({
            "title": title,
            "url": url,
            "doi": doi,
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
    domain: str | None = None,
) -> tuple[Json | None, list[Json]]:
    seen = _seen_submission_fingerprints_for_domain(submitted_path, domain)
    published_bundle_sigs = _published_bundle_signatures(
        submitted_path, domain, runs_root,
    )
    retryable = _repairable_rejected_fingerprints(submitted_path.parent, domain)
    retry_decisions = _repairable_decisions_by_fingerprint(
        submitted_path.parent, domain,
    )
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
            # Bounded single-claim memos clear editorial review; evidence maps
            # do not yet (the reviewer panel wants a synthesized claim, not a
            # findings table), so try every single claim before any map rather
            # than letting a source-rich map's high alpha jump the queue.
            1 if r.get("surface_type") == "evidence_map" else 0,
            -(int(r.get("alpha_score") or 0) + accepted_shape_bonus(r, shape_profiles)),
            str(r.get("topic") or ""),
        ),
    )
    family_common = _common_family_tokens([
        *topic_blocked,
        *(value for verdict in candidates for value in _family_values(verdict)),
    ])
    blocked_family_keys = _canonical_family_keys(topic_blocked)
    for verdict in candidates:
        if domain:
            run_dir = _run_path(runs_root, verdict.get("run_dir"))
            verdict_domain = _run_domain(run_dir, verdict)
            if not verdict_domain:
                considered.append({
                    "topic": verdict.get("topic"),
                    "status": "missing_domain_metadata",
                    "decision": verdict.get("decision"),
                })
                continue
            if verdict_domain != domain:
                considered.append({
                    "topic": verdict.get("topic"),
                    "status": "wrong_domain",
                    "domain": verdict_domain,
                    "decision": verdict.get("decision"),
                })
                continue
            verdict = verdict | {"domain": load_domain_profile(verdict_domain).as_metadata()}
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
        selection_memo_sha256 = memo_sha256
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
        family_keys = _family_keys(_family_values(verdict), family_common)
        canonical_family_keys = _canonical_family_keys(_family_values(verdict))
        family_blocked = bool(canonical_family_keys & blocked_family_keys)
        attempt_count = _fingerprint_attempt_count(submitted_path, fp, domain)
        retry_after_rejection = _retry_after_rejection(
            fp,
            attempt_count=attempt_count,
            retryable=retryable,
            decisions=retry_decisions,
        )
        # Whether this candidate is a RESUBMIT of an already-seen / retryable
        # memo (vs a first submit). Only resubmits must be blocked when a rewrite
        # leaves the memo byte-identical; a first submit whose refresh merely
        # adds audit sidecars or runs agent repair legitimately keeps the memo.
        selection_is_resubmit = fp in seen or retry_after_rejection
        # A repairable revise/reject (Researka returned editorial notes and
        # allowed resubmission) must re-enter for the feedback re-write even when
        # its topic/family was recently submitted — otherwise the revise loop is
        # duplicate-blocked as cycle_exhausted_topic and never resubmits. Bounded:
        # retry_after_rejection requires fp in retryable AND attempt_count < limit.
        exhausted_topic = (
            not retry_after_rejection
            and (_selection_topic(verdict) in topic_blocked or family_blocked)
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
                attempt_count = _fingerprint_attempt_count(submitted_path, fp, domain)
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
                approved = approved or _agent_repair_passed_submit_gates(
                    verdict,
                    source_count=source_count,
                    direct_source_count=direct_source_count,
                    min_source_count=min_source_count,
                    min_direct_source_count=min_direct_source_count,
                )
                cycle_blocked = fp in blocked
                attempt_count = _fingerprint_attempt_count(submitted_path, fp, domain)
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
                verdict = _with_domain_metadata(_write_publish_verdict(run_dir), run_dir, verdict)
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
                attempt_count = _fingerprint_attempt_count(submitted_path, fp, domain)
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
                    attempt_count = _fingerprint_attempt_count(submitted_path, fp, domain)
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
                    attempt_count = _fingerprint_attempt_count(submitted_path, fp, domain)
                    retry_after_rejection = _retry_after_rejection(
                        fp,
                        attempt_count=attempt_count,
                        retryable=retryable,
                        decisions=retry_decisions,
                    )
                    missing_audit_sidecars = _missing_audit_sidecars(verdict, runs_root)
                    if fp == retry_fp and memo_sha256 == retry_memo_sha256:
                        status = "duplicate_submission_fingerprint"
            # Unified no-op-rewrite guard across every refresh block above: a
            # resubmit whose rewrite returns a byte-identical memo earns the same
            # reviewer verdict, so it must not be resubmitted. The fingerprint can
            # shift on reload (receipt_expansion re-derivation) without the memo
            # changing, so gate on content (memo_sha256), not the fingerprint.
            if (
                memo_refreshed
                and has_memo
                and selection_is_resubmit
                and memo_sha256 == selection_memo_sha256
            ):
                retry_fingerprint_unchanged = True
            if missing_audit_sidecars:
                status = "memo_missing_audit_sidecars"
            if retry_fingerprint_unchanged:
                status = "duplicate_submission_fingerprint"
            if (
                status == "eligible"
                and verdict.get("surface_type") == "evidence_map"
            ):
                # Evidence maps publish (Researka accepts them as landscape
                # syntheses — verified 2026-06-12). Two guards before submit:
                # (1) submit_evidence_maps must be on; (2) a pre-submit mirror of
                # the intake floor — a map needs >= evidence_map_min_citations (10)
                # cited sources, so a sub-floor map is held rather than burning an
                # intake reject (v3 dev §4). Source/recency are otherwise easily met.
                if not _alpha_memo_bool("submit_evidence_maps", False):
                    status = "evidence_map_submission_held"
                elif direct_source_count < _alpha_memo_int(
                    "evidence_map_min_citations", 10,
                ):
                    # direct_source_count counts the full A_core landscape the map
                    # ships (see _direct_source_count), not the memo's narrowed
                    # cluster — a source-rich topic (metformin: 31 citable A_core
                    # sources) is not held at the 6 its single-claim memo cites.
                    status = "evidence_map_below_citation_floor"
            if (
                status == "eligible"
                and verdict.get("surface_type") == "publish_alpha_memo"
                and not _alpha_memo_bool("submit_single_claim_alpha", True)
            ):
                # Single-claim memos reach editorial but currently reject on
                # synthesis quality: the thesis is a raw concatenation of receipt
                # fragments and the falsifier is boilerplate (every single-claim
                # submission 2026-06-11/12 rejected this way). Hold them out of
                # submission until the synthesis pass lands (the abstract/thesis
                # work in the calibration task), so the timers don't burn editorial
                # rejects. Flip submit_single_claim_alpha=true when it's fixed.
                status = "single_claim_submission_held"
            if status == "eligible":
                # An M3-cluster-backed memo publishes at the cluster floor
                # (min_cluster_source_papers, default 3) — publish_tier already
                # waives the 5-source direct/source floors for it, so the submit
                # gate must use the same lower floor or it re-blocks a memo
                # publish_tier passed. Shape coherence is likewise waived (the
                # cluster is the writer-validated homogeneous unit).
                cluster_backed = _llm_cluster_backed(verdict, runs_root)
                cluster_floor = _alpha_memo_int("min_cluster_source_papers", 3)
                eff_min_source_count = (
                    min(min_source_count, cluster_floor) if cluster_backed
                    else min_source_count
                )
                eff_min_direct_count = (
                    min(min_direct_source_count, cluster_floor) if cluster_backed
                    else min_direct_source_count
                )
                bundle_sig = _bundle_signature(verdict, runs_root)
                if bundle_sig and bundle_sig in published_bundle_sigs:
                    # Same cited papers as an already-published memo (a different
                    # topic-name variant) — Researka would reject it as an
                    # exact-content duplicate, so never spend the submission.
                    status = "duplicate_published_bundle"
                elif fp in seen and _same_memo_seen(
                    submitted_path, fp, memo_sha256, domain,
                ):
                    status = "duplicate_submission_fingerprint"
                elif source_count < eff_min_source_count:
                    status = (
                        "corpus_source_floor_below_min"
                        if corpus_source_count < eff_min_source_count else
                        "memo_source_floor_below_min"
                    )
                    if source_count >= eff_min_source_count:
                        status = "eligible"
                elif direct_source_count < eff_min_direct_count:
                    status = "direct_source_floor_below_min"
                elif (
                    verdict.get("surface_type") != "evidence_map"
                    and not cluster_backed
                    and not _direct_receipts_share_shape(
                        verdict, runs_root, min_direct_source_count,
                    )
                ):
                    # An evidence map is an honest multi-shape scoping review, and
                    # an M3-cluster-backed single claim was already shape-waived by
                    # publish_tier; the single-claim token-shape gate applies to
                    # neither. Without these waivers a memo publish_tier passed is
                    # re-blocked here and never submits.
                    status = "receipt_shape_mismatch"
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
            "topic_family_keys": sorted(family_keys),
            "canonical_family_keys": sorted(canonical_family_keys),
            "family_blocked": family_blocked,
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
            # _staging_refreshed tells the submit path this memo was already
            # re-rendered here (with any repair decision applied), so the
            # pre-submit regeneration must NOT run again and revert the repair.
            return verdict | {
                "memo_fingerprint": fp, "_staging_refreshed": memo_refreshed,
            }, considered
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


def _source_literature_title_key(title: Any) -> str:
    raw = str(title or "").casefold()
    raw = re.sub(r"\b(?:19|20)\d{2}(?:\s*[-/]\s*(?:19|20)\d{2})?\b", " ", raw)
    raw = re.sub(r"\d+", " ", raw)
    raw = re.sub(r"[^a-z]+", " ", raw)
    return " ".join(token for token in raw.split() if token)


def _source_literature_boundary_quality(
    topic: str, papers: list[Json], min_sources: int,
) -> tuple[bool, str]:
    usable = [
        paper for paper in papers
        if isinstance(paper, dict)
        and str(paper.get("title") or "").strip()
        and (paper.get("doi") or paper.get("url") or paper.get("pmid") or paper.get("id"))
    ]
    if len(usable) < min_sources:
        return False, "source_floor_below_min"
    keys = [_source_literature_title_key(paper.get("title")) for paper in usable[:min_sources]]
    counts = {key: keys.count(key) for key in set(keys) if key}
    if any(count >= max(3, min_sources - 1) for count in counts.values()):
        return False, "repeated_title_series"
    topic_key = _source_literature_title_key(topic)
    if topic_key and len({key for key in keys if key and key != topic_key}) < min_sources:
        return False, "repeated_title_series"
    return True, "ok"


def _source_literature_topic_candidate(
    runs_root: Path, profile_slug: str, min_sources: int,
) -> str | None:
    discovery_dir = runs_root / "_topics_discovery"
    paths = sorted(
        discovery_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    for path in paths:
        data = _json(path, {})
        if not isinstance(data, dict) or not _same_domain(_row_domain(data), profile_slug):
            continue
        rows = data.get("all")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            topic = str(row.get("topic") or "").strip()
            if not topic:
                continue
            paper_count = int(row.get("paper_count") or 0)
            fact_source_count = int(row.get("fact_source_count") or 0)
            if paper_count >= min_sources and fact_source_count < min_sources:
                return topic
    return None


def _family_blocked_topic(topic: str, blocked_topics: set[str]) -> bool:
    if topic in blocked_topics:
        return True
    topic_tokens = _family_tokens(topic)
    if not topic_tokens:
        return False
    for blocked in blocked_topics:
        blocked_tokens = _family_tokens(blocked)
        if not blocked_tokens:
            continue
        overlap = len(topic_tokens & blocked_tokens)
        if overlap and overlap / min(len(topic_tokens), len(blocked_tokens)) >= 0.5:
            return True
    return False


def _fresh_parent_topics_from_discovery(
    runs_root: Path,
    profile_slug: str,
    blocked_topics: set[str],
    *,
    limit: int,
    min_sources: int,
) -> list[str]:
    discovery_dir = runs_root / "_topics_discovery"
    paths = sorted(
        discovery_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    ranked: list[tuple[tuple[int, int, float, str], str]] = []
    seen: set[str] = set()
    for path in paths:
        data = _json(path, {})
        if not isinstance(data, dict) or not _same_domain(_row_domain(data), profile_slug):
            continue
        raw_rows = data.get("all") or data.get("top")
        if not isinstance(raw_rows, list):
            continue
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            topic = cap_topic_slug(str(row.get("topic") or "").strip())
            if not topic or topic in seen or _family_blocked_topic(topic, blocked_topics):
                continue
            with suppress(TypeError, ValueError):
                fact_sources = int(row.get("fact_source_count") or 0)
                papers = int(row.get("paper_count") or 0)
                velocity = float(row.get("velocity_score") or 0.0)
                if max(fact_sources, papers) < min_sources:
                    continue
                ranked.append(((-fact_sources, -papers, -velocity, topic), topic))
                seen.add(topic)
        if len(ranked) >= limit:
            break
    return [topic for _score, topic in sorted(ranked)[:limit]]


def _source_literature_payload(
    *, profile_slug: str, topic: str, papers: list[Json], runs_root: Path, date: str,
) -> tuple[Json, Json]:
    profile = load_domain_profile(profile_slug)
    selected = papers[:5]
    run_dir = runs_root / f"{topic}-source-literature-{date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Source literature boundary memo", "", "## Boundary map", ""]
    source_bundle: list[Json] = []
    for idx, paper in enumerate(selected, start=1):
        title = str(paper.get("title") or "Untitled source").strip()
        doi = str(paper.get("doi") or "").strip()
        year = paper.get("year") or paper.get("publication_year")
        source_bundle.append({
            "title": title,
            "doi": doi,
            "year": year,
            "source_index": idx,
        })
        suffix = f" ({year})" if year else ""
        lines.append(f"- {title}{suffix}" + (f" doi:{doi}" if doi else ""))
    settings = load_settings()
    synthesis = (
        "The selected source-literature boundary keeps the claim scoped to "
        f"{topic} and the directly listed source titles."
    )
    writer_meta: Json = {"status": "skipped"}
    if settings.writer_configured:
        response = call_writer(settings, [{
            "role": "user",
            "content": (
                "Write a concise source-literature boundary synthesis for "
                f"{topic}. Use only these paper titles: "
                + "; ".join(str(paper.get("title") or "") for paper in selected)
            ),
        }], max_tokens=700)
        synthesis = response.content.strip() or synthesis
        writer_meta = {
            "status": "used",
            "model": response.model,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "content_hash": hashlib.sha256(synthesis.encode("utf-8")).hexdigest(),
        }
    if writer_meta.get("status") != "used":
        writer_meta = writer_meta | {
            "model": getattr(settings, "mimo_model", ""),
            "content_hash": hashlib.sha256(synthesis.encode("utf-8")).hexdigest(),
        }
    lines.extend(["", "## Source synthesis", "", synthesis, ""])
    markdown = "\n".join(lines)
    _write_json(run_dir / "source_literature_writer.json", writer_meta)
    candidate = {
        "topic": topic,
        "run_dir": str(run_dir.relative_to(runs_root)),
        "memo_fingerprint": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "domain": profile.as_metadata(),
    }
    payload = {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": _submission_agent_id(profile.slug),
        "agent_id": _submission_agent_id(profile.slug),
        "domain": profile.as_metadata(),
        "domain_slug": profile.slug,
        "category": profile.slug.removesuffix("_research"),
        "title": f"{topic} source-literature boundary",
        "abstract": _safe_excerpt(synthesis),
        "summary": _safe_excerpt(synthesis),
        "topic": topic,
        "metadata": {
            "article_type": "alpha_memo",
            "category": profile.slug.removesuffix("_research"),
            "domain_slug": profile.slug,
            "topic": topic,
        },
        "markdown": markdown,
        "citations": source_bundle,
        "source_bundle": source_bundle,
        "evidence_bundle": {
            "domain": profile.as_metadata(),
            "surface_type": "source_literature_boundary",
            "direct_source_count": len(source_bundle),
            "source_literature_writer": writer_meta,
        },
        "content_hash": "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    }
    return candidate, payload


# Public page rendering is eventually-consistent after acceptance; poll the
# fresh-accept check this many times before concluding the page is unrendered.
_PUBLISH_RENDER_POLL_ATTEMPTS = 6
_PUBLISH_RENDER_POLL_DELAY_S = 5.0


def _public_page_check(
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
    urls = _public_alpha_urls(decision)
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
                "ok": _page_rendered(result),
            }
            if result.get("error"):
                check["error"] = result.get("error")
            checks.append(check)
            if check["ok"]:
                return {"ok": True, "status": "rendered", "url": url, "checks": checks}
        if delay_s > 0 and attempt < max(1, attempts) - 1:
            time.sleep(delay_s)
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
            if decision.get("failure_category") == "integrity_duplicate":
                final = "accepted"
                ledger["status"] = "deduped_publication"
                ledger["published"] = 0
                ledger["published_topic"] = (
                    ledger.get("submitted_topic")
                    or (ledger.get("candidate") or {}).get("topic")
                )
                ledger.pop("publish_failure_reason", None)
                ledger["submission_id"] = submission_id
                ledger["researka_decision"] = decision
                ledger["final_verdict"] = final
                return final
            page = _public_page_check(
                decision, page_fetcher=page_fetcher,
                attempts=_PUBLISH_RENDER_POLL_ATTEMPTS,
                delay_s=_PUBLISH_RENDER_POLL_DELAY_S,
            )
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
        if not isinstance(ledger, dict):
            continue
        if ledger.get("status") == "published":
            summary["checked"] += 1
            page = _public_page_check(
                {"public_url": ledger.get("public_url")},
                page_fetcher=page_fetcher,
            )
            ledger["public_page_check"] = page
            if not page.get("ok"):
                ledger["status"] = "public_page_not_rendered"
                ledger["published"] = 0
                ledger["publish_failure_reason"] = "public_page_not_rendered"
                summary["updated"] += 1
                _write_ledger(path, ledger)
            continue
        if ledger.get("status") == "public_page_not_rendered" and ledger.get("public_url"):
            # Recover the inverse of the demotion above: a memo Researka
            # accepted whose page was not yet built at submit time. Re-check it;
            # once the page renders, promote to published instead of leaving it
            # permanently stuck (the repair path would only resubmit it and get
            # duplicate-blocked).
            summary["checked"] += 1
            page = _public_page_check(
                {"public_url": ledger.get("public_url")},
                page_fetcher=page_fetcher,
            )
            ledger["public_page_check"] = page
            if page.get("ok"):
                ledger["status"] = "published"
                ledger["published"] = 1
                ledger.pop("publish_failure_reason", None)
                summary["updated"] += 1
                summary["published"] += 1
                _write_ledger(path, ledger)
            continue
        if ledger.get("status") != "submitted_to_researka":
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
        _write_ledger(path, ledger)
    synthetic_ledgers: list[tuple[Path, Json]] = []

    def update_submitted_records(submitted: list[Any]) -> bool:
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
            synthetic_ledgers.append((
                ledger_dir / f"{stamp}-decision-{submission_id[:8]}.json",
                synthetic_ledger,
            ))
            seen_submission_ids.add(submission_id)
        return submitted_changed

    _update_json_list(
        ledger_dir / "_submitted_fingerprints.json",
        update_submitted_records,
    )
    for synthetic_path, synthetic_ledger in synthetic_ledgers:
        _write_ledger(synthetic_path, synthetic_ledger)
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
        except urllib.error.HTTPError as exc:
            # A Crossref 404 means the DOI is simply absent from Crossref
            # (e.g. arXiv/OSF DOIs that resolve via doi.org only). Absence is
            # not a retraction and not a transport failure, so it must not hold
            # the submission. A genuinely retracted paper IS in Crossref (200 +
            # retraction marker), so this cannot let a real retraction through.
            # Other HTTP errors (5xx, rate limits) remain real errors.
            if exc.code == 404:
                continue
            errors.append({"doi": doi, "error": type(exc).__name__, "detail": str(exc)[:180]})
            continue
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
    skipped_source_floor = [
        str(t) for t in payload.get("skipped_below_source_floor") or [] if str(t)
    ]
    return {
        "cycle": cycles[-1].name,
        "ran_topics": ran,
        "skipped_in_cooldown": skipped,
        "skipped_below_source_floor": skipped_source_floor,
    }


def _refresh_candidate_batch(
    refresh_top: int,
    excluded_topics: set[str] | None = None,
    cooldown_hours: float = _DEFAULT_REFRESH_COOLDOWN_HOURS,
    runs_root: Path = _RUNS,
    warm_backlog: bool = False,
    priority_topics: Iterable[str] = (),
    domain: str = "longevity",
) -> Json:
    exclusions = sorted(t for t in (excluded_topics or set()) if t)
    warm_probe_topics = _DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT
    priorities = [str(topic).strip() for topic in priority_topics if str(topic).strip()]
    effective_top = min(refresh_top, len(priorities)) if priorities else refresh_top
    args = [
        sys.executable, "scripts/run_curator_cycle.py",
        "--domain", domain, "--stop-on-ready", "--top", str(effective_top),
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
    for topic in priorities:
        args.extend(["--priority-topic", topic])
    for topic in exclusions:
        args.extend(["--exclude-topic", topic])
    ok, note = _run_step(args, timeout=_REFRESH_TIMEOUT_SECONDS)
    result = {
        "ok": ok,
        "note": note,
        "top": effective_top,
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
    queue: Json, excluded_topics: set[str], *, limit: int, domain: str | None = None,
) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, str], str]] = []
    seen = set(excluded_topics)
    floor = _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES
    for bucket_order, bucket_name in enumerate(("agent_repair_needed", "curation_needed")):
        for verdict in queue.get(bucket_name) or []:
            if not isinstance(verdict, dict):
                continue
            if not _same_domain(_row_domain(verdict), domain):
                continue
            parent = str(verdict.get("topic") or "").strip()
            rec = verdict.get("subtopic_recommendations")
            if not parent or not isinstance(rec, dict) or not rec.get("recommended"):
                continue
            for cluster in rec.get("clusters") or []:
                if not isinstance(cluster, dict):
                    continue
                if (
                    bucket_name == "agent_repair_needed"
                    and _cluster_has_repair_receipts(cluster)
                ):
                    continue
                ids = _cluster_fact_ids(cluster)
                member_count = len(ids)
                if bucket_name == "curation_needed" and ids and member_count < floor:
                    continue
                label = str(cluster.get("label") or "").strip("_")
                if not label or label == "unlabeled":
                    continue
                # Cap to the 4-token limit (cap_topic_slug, the codebase-wide
                # rule) so a multi-word cluster label cannot emit a 6-9 token
                # word-salad child slug. Uncapped slugs are probed raw by the
                # curator subprocess, find zero corpus facts, and exhaust the
                # refresh timeout before the clean discovery candidate is reached.
                child = cap_topic_slug(
                    "_".join(re.findall(r"[a-z0-9]+", f"{parent}_{label}".lower()))
                )
                if child and child not in seen:
                    reason_rank = (
                        0 if rec.get("reason") == "source_coherent_child_cluster" else 1
                    )
                    alpha = int(verdict.get("alpha_score") or 0)
                    candidates.append((
                        (reason_rank, -member_count, -alpha, f"{bucket_order}:{child}"),
                        child,
                    ))
                    seen.add(child)
    return [child for _score, child in sorted(candidates)[:limit]]


def _cluster_has_repair_receipts(cluster: Json) -> bool:
    values = cluster.get("member_fact_ids") if isinstance(cluster, dict) else []
    if not isinstance(values, list):
        return False
    return len({str(value or "").strip() for value in values if str(value or "").strip()}) >= (
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES
    )


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
    if re.fullmatch(r"(?i)(abstract:|review summary:)?\s*alpha memo(?:\s*[—-]\s*[\w -]+)?\.?", excerpt):
        return ""
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
    # Drop internal pipeline tells the reviewer reads as "procedurally generated":
    # the gate-audit fallback note (when frontier review is skipped) is an
    # implementation detail, not part of the published synthesis.
    internal_markers = ("Frontier review skipped", "deterministic gate audit")
    lines = [
        line for line in memo.splitlines()
        if not line.startswith(internal_prefixes)
        and not any(marker in line for marker in internal_markers)
    ]
    text = "\n".join(lines).strip() + "\n"
    note = (
        "**Interpretation note:** This is a hypothesis-generating alpha memo, "
        "not confirmatory evidence; subgroup or context-derived claims require "
        "independent replication.\n"
    )
    if "## Why this is surprising" in text and note not in text:
        text = text.replace("\n## Why this is surprising", f"\n\n{note}\n## Why this is surprising", 1)
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


def _submission_agent_id(domain: str) -> str:
    if domain == load_domain_profile(None).slug:
        return "agent-v4-alpha-memo"
    return "agent-v4-alpha-" + domain.replace("_", "-")


def _raw_section(memo: str, heading: str) -> str:
    """A section's body with tables/markdown preserved (unlike _plain_section,
    which drops table rows). Internal fact_id reconciliation markers are removed
    so the public section reads as a clean source table."""
    match = re.search(rf"^## {re.escape(heading)}\n+(.*?)(?=^## |\Z)", memo, re.M | re.S)
    if not match:
        return ""
    return re.sub(r"\s*`?fact_id=[A-Za-z0-9_-]+`?\s*", " ", match.group(1)).strip()


def _evidence_map_sections(
    verdict: Json, memo: str, n_sources: int, findings: str | None = None,
) -> dict[str, str]:
    """The six sections Researka reviews an evidence map for (landscape fidelity,
    not convergence). Intake requires the 'Evidence Landscape' section to carry
    >= 30 words; the rest are recommended. The Findings Map is the domain-
    stratified source table. Universal — no domain-specific text."""
    topic = str(verdict.get("topic") or "topic").replace("_", " ")
    findings = findings or _raw_section(memo, "Evidence receipts") or _raw_section(
        memo, "Findings Map")
    return {
        "Scope": (
            f"What is the range of reported effects across the {topic} literature, "
            "and how do they vary by population, comparator, and endpoint? This map "
            "catalogues the findings rather than converging them to one claim."
        ),
        "Search Summary": (
            f"{n_sources} direct (A_core) sources were retrieved from the Tier-2 "
            "semantic corpus for this topic and lane-classified; each is cited with "
            "a resolvable identifier in the source bundle below."
        ),
        "Evidence Landscape": (
            f"This evidence map surveys {n_sources} independent {topic} sources drawn "
            "from the Tier-2 corpus and classified as direct findings. They vary "
            "across population, comparator, and/or endpoint and are catalogued by "
            "source in the Findings Map rather than pooled into one estimate — "
            "cross-population aggregation is not claimed. Each row records its own "
            "population, comparator, endpoint, and effect, so the spread of the "
            "literature and any tensions between findings remain explicit."
        ),
        "Findings Map": findings or "See the cited source bundle.",
        "Tensions and Gaps": (
            "Findings differ in population, comparator, endpoint, and effect size, so "
            "they are not directly comparable and are not pooled. Gaps remain where a "
            "population or comparator is represented by only a single source."
        ),
        "Limitations": (
            "This is a scoping map of retrieved direct findings, not a meta-analysis: "
            "no pooled effect is computed, coverage is bounded by the Tier-2 corpus, "
            "and heterogeneity across rows precludes a single unified conclusion."
        ),
    }


def _submission_payload(verdict: Json, root: Path) -> Json:
    run_dir = _run_path(root, verdict.get("run_dir"))
    profile = load_domain_profile(_run_domain_required(run_dir, verdict))
    domain_metadata = profile.as_metadata()
    category = profile.slug.removesuffix("_research")
    agent_id = _submission_agent_id(profile.slug)
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
                "This alpha memo maps directly cited receipts and their limits.",
                title,
            ) if excerpt
        ),
        "This alpha memo maps directly cited receipts and their limits.",
    )
    source_papers = _memo_source_papers(verdict, root)
    direct_source_papers = _memo_source_papers(verdict, root, ("Evidence",), {"A_core"})
    # The submitted source_bundle must cover EVERY source the memo cites, not just
    # the A_core/Evidence direct set — else Researka rejects on citation_membership
    # ("every cited DOI must appear in the source bundle") when the memo legitimately
    # cites a Context-lane receipt. Build from the full cited set; direct_source_count
    # (the source-floor gate input) still measures the A_core direct set only.
    source_bundle = _source_bundle(source_papers)
    direct_source_count = len(direct_source_papers)
    receipt_count = len(_memo_receipt_ids(memo))
    # Researka routes on article_type: evidence-map memos must declare
    # themselves or core review judges them against single-claim criteria.
    article_type = (
        "evidence_map"
        if str(verdict.get("surface_type") or "") == "evidence_map"
        else "alpha_memo"
    )
    payload: Json = {
        "artifact_type": "alpha_memo",
        "article_type": article_type,
        "author_agent_id": agent_id,
        "agent_id": agent_id,
        "domain": domain_metadata,
        "domain_slug": profile.slug,
        "category": category,
        "title": title,
        "abstract": abstract,
        "summary": abstract,
        "topic": verdict.get("topic"),
        "metadata": {
            "article_type": article_type,
            "category": category,
            "domain_slug": profile.slug,
            "topic": verdict.get("topic"),
        },
        "markdown": public_memo,
        "citations": source_bundle,
        "source_bundle": source_bundle,
        "novelty_score": verdict.get("alpha_score"),
        "confidence_score": verdict.get("maturity_level"),
        "evidence_bundle": {
            "domain": domain_metadata,
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
    # An evidence map is validated on its structured sections (Researka intake
    # reads sections["Evidence Landscape"] for its >=30-word research-question
    # gate). The alpha_memo lane needs no sections (its word budget is 0), so we
    # only attach them for maps to keep the proven single-claim path untouched.
    if article_type == "evidence_map":
        # A map is a landscape, so cite the full A_core breadth, not the memo's
        # single-claim cluster. The narrowed memo (e.g. 6 of metformin's 31
        # A_core sources) under-cites and trips the >=10-citation intake gate;
        # rebuilding the bundle and Findings Map from every A_core source clears
        # the floor and renders the domain-stratified table the reviewer verifies
        # row by row. Only citable sources (title + resolvable id) are kept, so
        # every table row maps 1:1 to a bundle entry — the attribution match the
        # panel rejects v3 maps for breaking.
        citable = _map_citable_facts(verdict, root)
        map_bundle = _source_bundle([
            _normalize_paper(f.get("source_paper") or {}) for f in citable
        ])
        findings: str | None = None
        if len(map_bundle) > len(source_bundle):
            source_bundle = map_bundle
            payload["citations"] = source_bundle
            payload["source_bundle"] = source_bundle
            direct_source_count = len(source_bundle)
            findings = _findings_map_table(citable)
        # One canonical count (direct_source_count = the sources actually cited)
        # renders the title and abstract structurally; the Findings Map table and
        # source bundle are built from the same set. No field is reconciled from
        # prose, so the counts cannot drift apart.
        payload["title"], payload["abstract"] = _evidence_map_header(
            str(verdict.get("topic") or ""), direct_source_count)
        payload["summary"] = payload["abstract"]
        payload["sections"] = _evidence_map_sections(
            verdict, memo, direct_source_count, findings=findings)
        # Critically, do NOT send a body for a map: intake maps markdown ->
        # body_markdown, and the publish stage validates any non-alpha body as a
        # FULL MANUSCRIPT (## Abstract/Methods/Results/.../References) — our memo
        # body fails that gate ('Abstract' empty, 0 chars) and an ACCEPTED
        # submission never becomes a publication (autonomous_publish job fails).
        # With no body, the publish stage compiles the body FROM the sections —
        # the designed evidence-map path.
        payload.pop("markdown", None)
    return payload


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
    domain: str = "longevity",
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
    source_paper_fetcher: SourcePaperFetcher | None = None,
    fetcher: Fetcher = _crossref_fetch,
    decision_fetcher: DecisionFetcher = _decision_fetch,
    page_fetcher: PageFetcher = _fetch_public_page,
    memo_refresher: MemoRefresher = _refresh_alpha_memo,
    queue_builder: QueueBuilder = _build_queue,
    sleep: Callable[[float], None] = time.sleep,
) -> Json:
    profile = load_domain_profile(domain)
    ledger_path = runs_root / "_daily_ledger" / f"{date}.json"
    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    decision_sync = sync_submission_decisions(
        runs_root, fetcher=decision_fetcher, page_fetcher=page_fetcher,
    )
    ledger: Json = {
        "date": date,
        "domain": profile.as_metadata(),
        "dry_run": (not submit) or profile.dry_run_only,
        "submit_requested": bool(submit),
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
        "family_blocked_count": 0,
        "seed_scope_dropped_count": 0,
        "seed_scope_fallback_count": 0,
        "seed_scope_fallback_used": False,
        "status": "started",
    }
    if estimated_cost_usd > max_cost_usd:
        ledger.update({"status": "cost_cap_exceeded", "reason": "estimated_cost_above_cap"})
        _write_ledger(ledger_path, ledger)
        return ledger
    if submit and profile.dry_run_only:
        ledger.update({
            "status": "domain_dry_run_only",
            "reason": f"domain {profile.slug} is not allowed to submit yet",
            "submitted": 0,
            "published": 0,
        })
        _write_ledger(ledger_path, ledger)
        return ledger
    blocked_fingerprints: set[str] = set()
    session_retryable: set[str] = set()
    session_retry_decisions: dict[str, Json] = {}
    published_blocked_topics = _recently_published_topics(
        submitted_path.parent, days=published_topic_cooldown_days,
        domain=profile.slug,
    )
    submitted_blocked_topics = _recent_submission_topics(
        submitted_path, days=published_topic_cooldown_days,
        domain=profile.slug, now=_stamp_ts(date),
    )
    negative_blocked_topics = _recent_negative_topics(
        submitted_path.parent, days=published_topic_cooldown_days,
        domain=profile.slug,
    )
    blocked_topics = published_blocked_topics | submitted_blocked_topics | negative_blocked_topics
    ledger["recently_published_topics_blocked"] = sorted(published_blocked_topics)
    ledger["recently_submitted_topics_blocked"] = sorted(submitted_blocked_topics)
    ledger["recent_negative_topics_blocked"] = sorted(negative_blocked_topics)
    force_refresh = False
    accepted_shape_profiles = _accepted_shape_profiles(runs_root, domain=profile.slug)
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
            _write_ledger(ledger_path, ledger)
            return ledger
        ledger["submit_token_env"] = token_env
        submitter = _http_submitter(url, token)

    def build_current_queue() -> Json:
        if queue_builder is _build_queue:
            return _build_queue(runs_root, include_archive, domain=profile.slug)
        return queue_builder(runs_root, include_archive)

    prev_queue_sig: frozenset[str] = frozenset()
    preflight_queue = None
    skip_refresh_note = "skipped_after_repairable_submission"
    if refresh_candidates and queue is None and queue_builder is _build_queue:
        candidate_queue = _with_repairable_candidates(
            build_current_queue(), runs_root, profile.slug,
        )
        cluster_rows = _rows(candidate_queue, allow_tier2=True) + [
            r for r in candidate_queue.get("curation_needed") or [] if isinstance(r, dict)
        ]
        if candidate_queue.get("ready_to_publish") or _claim_cluster_candidates(
            cluster_rows, runs_root, min_direct_source_count=min_direct_submit_sources,
        ):
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
                domain=profile.slug,
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
                if (
                    _refresh_timeout_note(refresh)
                    and refresh.get("priority_topics")
                    and batch < search_batch_limit
                ):
                    timed_out_topics = [
                        str(t) for t in (
                            refresh.get("ran_topics") or refresh.get("priority_topics") or []
                        ) if str(t)
                    ]
                    blocked_topics.update(timed_out_topics)
                    next_parent_topics = _fresh_parent_topics_from_discovery(
                        runs_root,
                        profile.slug,
                        blocked_topics,
                        limit=1,
                        min_sources=max(min_submit_sources, min_direct_submit_sources),
                    )
                    if next_parent_topics:
                        ledger.setdefault("refresh_timeout_deferrals", []).append({
                            "batch": batch,
                            "timed_out_topics": timed_out_topics,
                            "next_priority_topics": next_parent_topics,
                            "note": str(refresh.get("note") or "")[:240],
                        })
                        priority_refresh_topics = next_parent_topics
                        force_refresh = True
                        continue
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
                _write_ledger(ledger_path, ledger)
                return ledger
        current_queue = (
            queue if queue is not None else preflight_queue
            if preflight_queue is not None else build_current_queue()
        )
        preflight_queue = None
        current_queue = _with_repairable_candidates(
            current_queue, runs_root, profile.slug,
        )
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
        ledger["queue_counts"] = publish_status.queue_counts(current_queue)
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
            domain=profile.slug,
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
        queue_meta = current_queue.get("_meta")
        if isinstance(queue_meta, dict):
            with suppress(TypeError, ValueError):
                ledger["seed_scope_dropped_count"] = max(
                    int(ledger.get("seed_scope_dropped_count") or 0),
                    int(queue_meta.get("seed_scope_dropped_count") or 0),
                )
                ledger["seed_scope_fallback_count"] = max(
                    int(ledger.get("seed_scope_fallback_count") or 0),
                    int(queue_meta.get("seed_scope_fallback_count") or 0),
                )
            ledger["seed_scope_fallback_used"] = bool(
                ledger.get("seed_scope_fallback_used")
                or queue_meta.get("seed_scope_fallback_used")
            )
        ledger["family_blocked_count"] = sum(
            1 for row in all_considered if row.get("family_blocked")
        )
        if candidate is None:
            ran_topics = [str(t) for t in refresh.get("ran_topics") or [] if str(t)]
            if ran_topics:
                blocked_topics.update(ran_topics)
            source_floor_topics = [
                str(t) for t in refresh.get("skipped_below_source_floor") or [] if str(t)
            ]
            if source_floor_topics:
                blocked_topics.update(source_floor_topics)
            fresh_parent_topics = _fresh_parent_topics_from_discovery(
                runs_root,
                profile.slug,
                blocked_topics,
                limit=1,
                min_sources=max(min_submit_sources, min_direct_submit_sources),
            )
            if refresh_candidates and fresh_parent_topics and batch < search_batch_limit:
                ledger["refresh_parent_topics"] = fresh_parent_topics
                priority_refresh_topics = fresh_parent_topics
                force_refresh = True
                continue
            priority_children = _child_topics_from_queue(
                current_queue, blocked_topics, limit=refresh_top, domain=profile.slug,
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
                _write_ledger(ledger_path, ledger)
                return ledger
            continue
        if not submit:
            ledger["cycle_attempts"].append(attempt | {"status": "dry_run_selected"})
            ledger.update({"status": "dry_run_selected"})
            _write_ledger(ledger_path, ledger)
            return ledger
        assert submitter is not None
        run_dir = _run_path(runs_root, candidate.get("run_dir"))
        # Re-render through the current writer so writer fixes propagate to a
        # candidate built by older code. SKIP when staging already re-rendered
        # it: that pass applied any repair decision (e.g. scope narrowing), and
        # a decision-less re-render here would re-derive the full receipt set and
        # revert the repair. Reload after a successful render so the recorded
        # fingerprint matches the submitted memo. Failures fall back to disk.
        staging_refreshed = bool(candidate.pop("_staging_refreshed", False))
        if (
            memo_refresher is not None
            and _regenerate_on_resubmit()
            and not staging_refreshed
        ):
            with suppress(Exception):
                if memo_refresher(run_dir, candidate):
                    candidate = _reload_verdict_after_memo_refresh(candidate, run_dir)
                    candidate = candidate | {"memo_fingerprint": memo_fingerprint(candidate)}
        selected_fingerprint = str(candidate.get("memo_fingerprint") or "")
        candidate = _current_submit_verdict(candidate, runs_root)
        current_fingerprint = memo_fingerprint(candidate)
        candidate = candidate | {"memo_fingerprint": current_fingerprint}
        hold = _pre_submit_hold(
            candidate,
            runs_root,
            allow_tier2=allow_tier2,
            min_source_count=min_submit_sources,
            min_direct_source_count=min_direct_submit_sources,
        )
        if hold["status"]:
            attempt.update(hold)
            attempt["status"] = hold["status"]
            if current_fingerprint != selected_fingerprint:
                attempt["selected_fingerprint"] = selected_fingerprint
                attempt["current_fingerprint"] = current_fingerprint
            for row in reversed(all_considered):
                if row.get("fingerprint") in {selected_fingerprint, current_fingerprint}:
                    row["pre_attempt_status"] = row.get("status")
                    row["status"] = hold["status"]
                    row["current_decision"] = hold["current_decision"]
                    row["blockers"] = hold["blockers"]
                    row["source_count"] = hold["source_count"]
                    row["direct_source_count"] = hold["direct_source_count"]
                    row["corpus_ab_paper_count"] = hold["corpus_ab_paper_count"]
                    if hold.get("missing_audit_sidecars"):
                        row["missing_audit_sidecars"] = hold["missing_audit_sidecars"]
                    break
            ledger["cycle_attempts"].append(attempt)
            for fingerprint in {selected_fingerprint, current_fingerprint}:
                if fingerprint:
                    blocked_fingerprints.add(fingerprint)
            if not refresh_candidates or batch >= search_batch_limit:
                ledger.update({
                    "status": "no_fresh_candidate",
                    "published": 0,
                    "reason": publish_status.no_candidate_reason(all_considered),
                })
                _write_ledger(ledger_path, ledger)
                return ledger
            continue
        payload = _submission_payload(candidate, runs_root)
        checked_payload, preflight_report = _run_preflight_qa(payload, run_dir)
        if preflight_report is not None:
            attempt["preflight_qa"] = _preflight_summary(preflight_report)
            ledger["preflight_qa"] = attempt["preflight_qa"]
        if checked_payload is None:
            attempt["status"] = "preflight_qa_blocked"
            ledger["cycle_attempts"].append(attempt)
            ledger.update({"status": "preflight_qa_blocked", "submitted": 0, "published": 0})
            _write_ledger(ledger_path, ledger)
            return ledger
        result = submit_with_backoff(checked_payload, submitter)
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
                        _write_ledger(ledger_path, ledger)
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
                            topic = str(candidate.get("topic") or "")
                            if topic:
                                blocked_topics.add(topic)
                            ledger["repair_retry_deferred"] = {
                                "topic": candidate.get("topic"),
                                "reason": attempt["status"],
                                "requires": "new_memo_fingerprint",
                            }
                            _write_ledger(ledger_path, ledger)
                            continue
                        blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
                        topic = str(candidate.get("topic") or "")
                        if topic:
                            blocked_topics.add(topic)
                        if not refresh_candidates or batch >= search_batch_limit:
                            ledger.update({"status": attempt["status"], "published": 0})
                            _write_ledger(ledger_path, ledger)
                            return ledger
                        continue
            ledger["cycle_attempts"].append(attempt | {"status": "submitted_to_researka"})
            _write_ledger(ledger_path, ledger)
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
            _write_ledger(ledger_path, ledger)
            return ledger
    if (
        submit
        and source_paper_fetcher is not None
        and profile.slug != "ai_research"
        and not ledger["cycle_attempts"]
    ):
        literature_topic = _source_literature_topic_candidate(
            runs_root, profile.slug, min_submit_sources,
        )
        if literature_topic:
            papers = source_paper_fetcher(literature_topic, min_submit_sources)
            ok, reason = _source_literature_boundary_quality(
                literature_topic, papers, min_submit_sources,
            )
            ledger["source_literature_fallback"] = {
                "topic": literature_topic,
                "status": "selected" if ok else "blocked",
                "reason": reason,
                "paper_count": len(papers),
            }
            if ok:
                candidate, payload = _source_literature_payload(
                    profile_slug=profile.slug,
                    topic=literature_topic,
                    papers=papers,
                    runs_root=runs_root,
                    date=date,
                )
                assert submitter is not None
                result = submit_with_backoff(payload, submitter)
                ledger["candidate"] = {
                    "topic": literature_topic,
                    "run_dir": candidate.get("run_dir"),
                    "fingerprint": candidate.get("memo_fingerprint"),
                }
                ledger["submission"] = result
                if result["status"] == "accepted":
                    submission_id = _submission_id(result)
                    ledger.update({
                        "final_verdict": "pending",
                        "status": "submitted_to_researka",
                        "submitted": 1,
                        "submitted_topic": literature_topic,
                        "submission_id": submission_id,
                    })
                    if submission_id:
                        final = _poll_submission_decision(
                            ledger,
                            submission_id=submission_id,
                            fetcher=decision_fetcher,
                            page_fetcher=page_fetcher,
                            attempts=decision_poll_attempts,
                            sleep_seconds=decision_poll_seconds,
                            sleep=sleep,
                        )
                        if final == "accepted":
                            ledger["cycle_attempts"].append({
                                "topic": literature_topic,
                                "run_dir": candidate.get("run_dir"),
                                "fingerprint": candidate.get("memo_fingerprint"),
                                "status": "published",
                            })
                            _write_ledger(ledger_path, ledger)
                            return ledger
                    ledger["cycle_attempts"].append({
                        "topic": literature_topic,
                        "run_dir": candidate.get("run_dir"),
                        "fingerprint": candidate.get("memo_fingerprint"),
                        "status": "submitted_to_researka",
                    })
                    _write_ledger(ledger_path, ledger)
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
            "status": "no_fresh_candidate",
            "reason": _no_candidate_reason(all_considered),
        })
    _write_ledger(ledger_path, ledger)
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=domain_choices(), default="longevity")
    parser.add_argument("--date", default=_ledger_stamp())
    parser.add_argument("--include-archive", action="store_true")
    parser.add_argument("--refresh-candidates", action="store_true")
    parser.add_argument(
        "--allow-tier2-repair",
        dest="allow_tier2",
        action="store_true",
        help="Allow Tier 2 rows to enter repair; does not lower final submit gates.",
    )
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
    parser.add_argument("--min-submit-sources", type=int, default=None)
    parser.add_argument("--min-direct-submit-sources", type=int, default=None)
    parser.add_argument("--decision-poll-attempts", type=int, default=_DEFAULT_DECISION_POLL_ATTEMPTS)
    parser.add_argument("--decision-poll-seconds", type=float, default=_DEFAULT_DECISION_POLL_SECONDS)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--allow-pending-success",
        action="store_true",
        help="Treat submitted-but-not-yet-published as exit 0 for submit runs.",
    )
    parser.add_argument(
        "--retraction-check",
        choices=("metadata", "crossref", "skip"),
        default="metadata",
    )
    args = parser.parse_args()
    ledger = run_cycle(
        date=args.date,
        domain=args.domain,
        include_archive=args.include_archive,
        refresh_candidates=args.refresh_candidates,
        allow_tier2=args.allow_tier2,
        estimated_cost_usd=args.estimated_cost_usd,
        max_cost_usd=args.max_cost_usd,
        refresh_top=args.refresh_top,
        refresh_cooldown_hours=args.refresh_cooldown_hours,
        max_refresh_batches=args.max_refresh_batches,
        published_topic_cooldown_days=args.published_topic_cooldown_days,
        min_submit_sources=args.min_submit_sources
        if args.min_submit_sources is not None else
        _domain_alpha_memo_int(args.domain, "min_source_papers", _DEFAULT_MIN_SUBMIT_SOURCES),
        min_direct_submit_sources=args.min_direct_submit_sources
        if args.min_direct_submit_sources is not None else
        _domain_alpha_memo_int(
            args.domain, "min_direct_source_papers", _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES,
        ),
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
    summary = ledger.get("publish_summary")
    if isinstance(summary, dict):
        print("[daily-alpha] summary=" + json.dumps(summary, sort_keys=True))
    return _cycle_exit_code(
        ledger, submit=args.submit, allow_pending_success=args.allow_pending_success,
    )


if __name__ == "__main__":
    raise SystemExit(main())
