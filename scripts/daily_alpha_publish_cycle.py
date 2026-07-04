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
from agent.fact_lanes import classify_lanes
from agent.publish_tier import publish_verdict
from agent.settings import load_settings
from agent.topic_discovery import cap_topic_slug
from scripts import alpha_publish_config as publish_config
from scripts import alpha_publish_decisions as publish_decisions
from scripts import alpha_publish_io as publish_io
from scripts import alpha_publish_literature as publish_literature
from scripts import alpha_publish_markdown as publish_markdown
from scripts import alpha_publish_preflight as preflight
from scripts import alpha_publish_public as publish_public
from scripts import alpha_publish_status as publish_status
from scripts.alpha_publish_submit import http_submitter, submit_with_backoff

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
    "use", "used", "using",
})
_COHERENCE_GENERIC_TOKENS = _CLUSTER_GENERIC_TOKENS | {
    "endpoint", "endpoints", "outcome", "outcomes", "intervention",
    "interventions", "comparator", "comparators", "group", "groups",
    "primary", "secondary", "measure", "measures", "metric", "metrics",
    "setting", "settings", "agent", "agents", "usual", "standard", "routine",
    "care",
}
_OUTCOME_GENERIC_TOKENS = frozenset({
    "change", "changed", "changes", "increase", "increased", "increases",
    "decrease", "decreased", "decreases", "reduce", "reduced", "reduces",
    "reduction", "significantly", "observed", "mean", "size",
    "male", "males", "female", "females",
})
_DISCOVERY_GENERIC_SUFFIX_TOKENS = _CLUSTER_GENERIC_TOKENS | {
    "achieve", "achieves", "finding", "findings", "result", "results",
    "show", "shows", "shown", "their", "while",
    "achieved", "achieving", "demonstrate", "demonstrated", "demonstrates",
    "average", "averages", "outperform", "outperformed", "outperforming",
    "outperforms", "our", "that", "those",
}
_DISCOVERY_SEED_SCOPE_GENERIC_TOKENS = _DISCOVERY_GENERIC_SUFFIX_TOKENS | {
    "agent", "agents", "anti", "automation", "model", "models", "research", "source",
    "system", "systems",
}
_DISCOVERY_PARENT_GENERIC_TOKENS = _DISCOVERY_SEED_SCOPE_GENERIC_TOKENS | {
    "age", "ageing", "aging", "dose", "longevity", "related",
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
_SOURCE_LITERATURE_FALLBACK_SUBMIT_ENV = "RESEARKA_SOURCE_LITERATURE_FALLBACK_SUBMIT"


def _source_literature_fallback_submit_enabled() -> bool:
    return str(os.environ.get(_SOURCE_LITERATURE_FALLBACK_SUBMIT_ENV) or "").casefold() in {
        "1", "true", "yes", "on",
    }


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
    return publish_config.alpha_memo_int(_PUBLICATION_PATH, name, default)


def _domain_alpha_memo_int(domain: str, name: str, default: int) -> int:
    return publish_config.domain_alpha_memo_int(_PUBLICATION_PATH, domain, name, default)


def _alpha_memo_float(name: str, default: float) -> float:
    return publish_config.alpha_memo_float(_PUBLICATION_PATH, name, default)


def _alpha_memo_bool(name: str, default: bool) -> bool:
    return publish_config.alpha_memo_bool(_PUBLICATION_PATH, name, default)


def _publish_tier_int(name: str, default: int) -> int:
    return publish_config.publish_tier_int(_PUBLISH_TIER_PATH, name, default)


_DEFAULT_MIN_SUBMIT_SOURCES = _alpha_memo_int("min_source_papers", 5)
_DEFAULT_MIN_DIRECT_SUBMIT_SOURCES = _alpha_memo_int("min_direct_source_papers", 2)
_SOURCE_LITERATURE_SCAN_LIMIT = max(10, _DEFAULT_MIN_SUBMIT_SOURCES * 3)
_SOURCE_LITERATURE_STRUCTURAL_BLOCK_REASONS = frozenset({
    "directional_receipt_floor_below_min",
    "source_fact_diversity_below_min",
    "source_diverse_floor_below_min",
})
_DEFAULT_REFRESH_TOP = _alpha_memo_int("refresh_top", 1)
_DEFAULT_REFRESH_COOLDOWN_HOURS = _alpha_memo_float("refresh_cooldown_hours", 2.0)
_DEFAULT_PARENT_REFRESH_TOPIC_LIMIT = _alpha_memo_int("parent_refresh_topic_limit", 4)
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
_SUBMIT_WARM_BACKLOG_MIN_PROBE_TOPICS = max(
    2, min(4, _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES)
)
_SUBMIT_WARM_BACKLOG_MAX_PROBE_TOPICS = max(
    _SUBMIT_WARM_BACKLOG_MIN_PROBE_TOPICS,
    min(4, _DEFAULT_MIN_SUBMIT_SOURCES),
)
_REFRESH_TIMEOUT_SECONDS = 1200
_ALPHA_REFRESH_FULLRAW_DEFAULTS = {
    "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS": "45",
    "TOPIC_DISCOVERY_FULLRAW_SUPPLY_PARENT_TIMEOUT_SECONDS": "420",
    "TOPIC_DISCOVERY_FULLRAW_SUPPLY_BUDGET_SECONDS": "360",
    "TOPIC_DISCOVERY_FULLRAW_SUPPLY_QUERY_BUDGET_SECONDS": "300",
    "TOPIC_DISCOVERY_FULLRAW_SUPPLY_SWEEP_WAIT_SECONDS": "240",
}
_SOURCE_LIT_PREFLIGHT_FULLRAW_DEFAULTS = {
    "RESEARKA_SOURCE_LITERATURE_FULLRAW_TIMEOUT_SECONDS": "8",
    "RESEARKA_SOURCE_LITERATURE_FULLRAW_BUDGET_SECONDS": "20",
    "RESEARKA_SOURCE_LITERATURE_FULLRAW_SWEEP_WAIT_SECONDS": "8",
    "RESEARKA_SOURCE_LITERATURE_FULLRAW_MAX_VARIANTS": "1",
}
# User-facing "3x" repair limit: one initial submit plus three repaired
# resubmits for the same evidence fingerprint.
_MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT = 4
_MAX_REJECT_ATTEMPTS_PER_FINGERPRINT = 2
_DECISION_ACCEPTED = publish_status.DecisionVerdict.ACCEPTED.value
_DECISION_PENDING = publish_status.DecisionVerdict.PENDING.value
_DECISION_REJECT = publish_status.DecisionVerdict.REJECT.value
_DECISION_REJECTED = publish_status.DecisionVerdict.REJECTED.value
_DECISION_REVISE = publish_status.DecisionVerdict.REVISE.value
_DECISION_STALE_PENDING = publish_status.DecisionVerdict.STALE_PENDING.value
_FINAL_DECISION_VERDICTS = {
    _DECISION_ACCEPTED, _DECISION_REJECTED, _DECISION_REVISE, _DECISION_STALE_PENDING,
}
_EXHAUSTED_STATUSES = publish_status.EXHAUSTED_STATUSES
_TOPIC_EXHAUSTED_STATUSES = publish_status.TOPIC_EXHAUSTED_STATUSES
_FINGERPRINT_EXHAUSTED_STATUSES = publish_status.FINGERPRINT_EXHAUSTED_STATUSES
_REFRESHABLE_SOURCE_FLOOR_STATUSES = publish_status.REFRESHABLE_SOURCE_FLOOR_STATUSES
_BATCH_TOPIC_BLOCK_STATUSES = _TOPIC_EXHAUSTED_STATUSES | frozenset({
    "agent_repair_needed",
})
_PARENT_REFRESH_BEFORE_CHILD_STATUSES = _TOPIC_EXHAUSTED_STATUSES | frozenset({
    "cycle_exhausted_topic",
    "duplicate_published_bundle",
})
_AGENT_REPAIR_DECISIONS = {
    "agent_repair_needed", "needs_operator_review", "needs_operator_approval",
}
_LOCAL_PARENT_REFRESH_BLOCKERS = frozenset({
    "blocked_label:no_signal",
    "low_alpha_score",
    "source_floor_below_min",
    "direct_source_floor_below_min",
})


def _refresh_timeout_note(refresh: Json) -> bool:
    note = str(refresh.get("note") or "")
    return "TimeoutExpired:" in note or " timed out after " in note


def _parent_refresh_topic_limit(refresh_top: int) -> int:
    if refresh_top <= 1:
        return 1
    return min(refresh_top * 2, _DEFAULT_PARENT_REFRESH_TOPIC_LIMIT)


def _submit_warm_backlog_probe_topics(refresh_top: int) -> int:
    requested = max(1, refresh_top)
    bounded = min(_SUBMIT_WARM_BACKLOG_MAX_PROBE_TOPICS, requested)
    return max(_SUBMIT_WARM_BACKLOG_MIN_PROBE_TOPICS, bounded)


_REPAIRABLE_REJECTION_REASONS = {
    "cited doi",
    "minimum_citations",
    "not verifiably grounded",
    publish_status.CycleStatus.PUBLIC_PAGE_NOT_RENDERED.value,
    "recency_ratio",
    "required revision",
    publish_status.CycleStatus.REVIEWER_REVISE.value,
    "scope reset",
    "source_bundle_schema",
    "title/abstract",
}
_SOURCE_LITERATURE_RENDER_REPAIR_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 2
)
_SOURCE_LITERATURE_CLEAN_SUPPORTED_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 3
)
_SOURCE_LITERATURE_PARENT_LINK_REPAIR_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 4
)
_SOURCE_LITERATURE_RENDERER_FEEDBACK_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 5
)
_SOURCE_LITERATURE_TITLE_OWNERSHIP_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 6
)
_SOURCE_LITERATURE_FIELD_OWNERSHIP_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 7
)
_SOURCE_LITERATURE_TERMINAL_RESUBMIT_ATTEMPT_LIMIT = (
    2
)
_SOURCE_LITERATURE_PUBLISH_FRAMING_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 9
)
_SOURCE_LITERATURE_TERMINAL_FEEDBACK_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 10
)
_SOURCE_LITERATURE_SOURCE_SCOPE_ATTEMPT_LIMIT = (
    _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 20
)
_SOURCE_LITERATURE_UNOWNED_TITLE_MARKERS = (
    "directional evidence for",
    "heterogeneous metrics",
    "null/mixed for",
)
_SOURCE_LITERATURE_SOURCE_SCOPE_OLD_MARKERS = (
    "unmatched metric-scope map",
    "unmatched metric-scope",
    "source-scope boundary note",
    "source-scoping boundary note",
    "unmatched source-scope note",
    "effect synthesis",
)
_SOURCE_LITERATURE_SOURCE_SCOPE_FEEDBACK_TERMS = (
    "source grounding",
    "only one",
    "no pooling",
    "no-pooling",
    "scoping note",
    "scoping claim",
    "scoping contrast",
    "scope caveat",
    "scope contrast",
    "boundary memo",
    "bounded signal",
    "matched industry",
    "matched setting",
    "matched design",
    "effect synthesis",
)
_SOURCE_LITERATURE_OLD_PUBLISH_FRAMING_MARKERS = (
    "null/mixed",
    "heterogeneity",
    "heterogeneous",
)
_SOURCE_LITERATURE_WRITER_REPAIR_TERMS = (
    "raw accounting",
    "headline research signal",
    "outcome-family",
    "descriptive modeling",
    "modeling-only",
    "effect accounting",
    "design heterogeneity",
    "within-source caveat",
    "insignificant effect",
)
_SOURCE_LITERATURE_FIELD_OWNERSHIP_MARKERS = (
    "policy/exposure/practice",
    "source synthesis",
    "duplicate heterogeneity",
    "duplicate heterogeneity tables",
)
_SOURCE_LITERATURE_RENDER_REPAIR_TERMS = (
    "abstract",
    "bounded research signal",
    "bounded signal",
    "context only",
    "descriptive modeling",
    "directionally consistent",
    "direction bearing",
    "directional count",
    "effect bearing",
    "falsifier",
    "heterogeneous contexts",
    "heterogeneity matrix",
    "duplicate heterogeneity",
    "matched setting",
    "metric heterogeneity",
    "outcome family",
    "policy/exposure/practice",
    "rename the title",
    "source synthesis",
    "topic level claim",
    "within outcome",
)
_SOURCE_LITERATURE_RENDER_REPAIR_BLOCK_TERMS = (
    "cited doi",
    "hallucinated",
    "minimum citations",
    "missing citation",
    "not verifiably grounded",
    "source bundle below",
    "unsupported",
)
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
    return preflight.preflight_mode()


def _preflight_summary(report: Json) -> Json:
    return preflight.preflight_summary(report)


def _attach_preflight_summary(payload: Json, report: Json) -> None:
    preflight.attach_preflight_summary(payload, report)


def _refresh_content_hash(payload: Json) -> None:
    preflight.refresh_content_hash(payload)


def _run_preflight_qa(payload: Json, run_dir: Path) -> tuple[Json | None, Json | None]:
    return preflight.run_preflight_qa(
        payload,
        run_dir,
        root=_ROOT,
        read_json=_json,
        write_json=_write_json,
        run_subprocess=_run_subprocess,
    )


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
    if (run / "business_candidate_bundle.json").exists():
        data = _json(run / "publish_verdict.json", {})
        if isinstance(data, dict) and data:
            return data
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


def _stored_verdict_for_run(run: Path) -> Json:
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


def _cached_verdict_for_run(run: Path) -> Json:
    data = _json(run / "publish_verdict.json", {})
    if isinstance(data, dict) and data:
        if (
            data.get("decision") == "ready_to_publish"
            or data.get("decision") in _AGENT_REPAIR_DECISIONS
        ):
            return _verdict_for_run(run)
        return data
    return _verdict_for_run(run)


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


def _sidecar_lane_map(run: Path) -> dict[str, str]:
    lanes_raw = _json(run / "fact_lanes.json", {})
    if not isinstance(lanes_raw, dict):
        return {}
    return {
        str(row.get("fact_id") or ""): str(row.get("lane") or "")
        for row in lanes_raw.get("verdicts", [])
        if isinstance(row, dict)
    }


def _has_structured_facts(facts: list[Any]) -> bool:
    fields = ("population", "intervention", "comparator", "endpoint", "metric")
    return any(
        isinstance(fact, dict) and any(str(fact.get(k) or "").strip() for k in fields)
        for fact in facts
    )


def _current_lane_map(run: Path, facts: list[Any], topic: str) -> dict[str, str]:
    sidecar = _sidecar_lane_map(run)
    typed = [fact for fact in facts if isinstance(fact, dict)]
    if not _has_structured_facts(typed):
        return sidecar
    current = classify_lanes(typed, topic)
    current_bindable = sum(v.lane in {"A_core", "B_context"} for v in current)
    sidecar_bindable = sum(lane in {"A_core", "B_context"} for lane in sidecar.values())
    if (
        not sidecar
        or any(v.reason == "topic_in_background_context" for v in current)
        or current_bindable > sidecar_bindable
    ):
        return {v.fact_id: v.lane for v in current}
    return sidecar


def _refresh_lane_sidecar(run: Path) -> None:
    facts = _json(run / "all_facts.json", None)
    if not isinstance(facts, list):
        return
    typed = [fact for fact in facts if isinstance(fact, dict)]
    if not _has_structured_facts(typed):
        return
    topic = run.name.split("-evidence-", 1)[0]
    sidecar = _sidecar_lane_map(run)
    current = classify_lanes(typed, topic)
    current_bindable = sum(v.lane in {"A_core", "B_context"} for v in current)
    sidecar_bindable = sum(lane in {"A_core", "B_context"} for lane in sidecar.values())
    if current_bindable > sidecar_bindable:
        _write_json(run / "fact_lanes.json", {
            "topic": topic,
            "verdicts": [v.as_dict() for v in current],
        })


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
        topic = run.name.split("-evidence-", 1)[0]
        lanes = _current_lane_map(run, facts, topic)
        cluster = densest_claim_cluster(
            facts_by_id, lanes, topic,
            min_sources=_alpha_memo_int("min_cluster_source_papers", 3),
        )
        if cluster.get("lead_fact_ids"):
            _write_json(run / "claim_cluster.json", cluster)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return


def _write_publish_verdict(run: Path) -> Json:
    _refresh_lane_sidecar(run)
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
    if status := _alpha_acceptance_status(verdict, root):
        return hold | {"status": status}
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
        return hold | {
            "status": publish_status.CandidateStatus.DIRECT_SOURCE_FLOOR_BELOW_MIN.value,
        }
    duplicate_studies = _duplicate_study_evidence(verdict, root)
    if duplicate_studies:
        return hold | {
            "status": publish_status.CandidateStatus.DUPLICATE_SOURCE_EVIDENCE.value,
            **duplicate_studies,
        }
    if (
        not _is_evidence_map_row(verdict)
        and not _direct_receipts_share_shape(verdict, root, min_direct_source_count)
    ):
        return hold | {
            "status": publish_status.CandidateStatus.RECEIPT_SHAPE_MISMATCH.value,
        }
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
                "surface_type", "receipt_expansion", "subtopic_recommendations",
            }
        })
    return refreshed


def _is_evidence_map_row(row: Json) -> bool:
    markers = (
        row.get("surface_type"),
        row.get("confidence_label"),
        row.get("surface"),
        row.get("memo_type"),
        row.get("article_type"),
    )
    if any(str(marker or "").lower() == "evidence_map" for marker in markers):
        return True
    return "evidence map" in str(row.get("headline") or "").lower()


def _queue_ready_row(row: Json, runs_root: Path) -> Json:
    if row.get("decision") == "ready_to_publish" and row.get("alpha_score") is not None:
        try:
            low_alpha = int(row.get("alpha_score") or 0) <= 0
        except (TypeError, ValueError):
            low_alpha = True
        if low_alpha:
            blockers = row.get("blockers")
            blocker_list = blockers if isinstance(blockers, list) else []
            return row | {
                "decision": "curation_needed",
                "queue_status": "low_alpha_score",
                "blockers": sorted({*(str(b) for b in blocker_list), "low_alpha_score"}),
            }
    if row.get("decision") == "ready_to_publish" and (
        status := _alpha_acceptance_status(row, runs_root)
    ):
        blockers = row.get("blockers")
        blocker_list = blockers if isinstance(blockers, list) else []
        return row | {
            "decision": "agent_repair_needed",
            "queue_status": status,
            "blockers": sorted({*(str(b) for b in blocker_list), status}),
        }
    if row.get("decision") != "ready_to_publish" or not _is_evidence_map_row(row):
        return row
    min_citations = _alpha_memo_int("evidence_map_min_citations", 10)
    if _direct_source_count(row, runs_root) < min_citations:
        status = "evidence_map_below_citation_floor"
    elif not _map_scope_coherent(row, runs_root, min_citations):
        status = "evidence_map_scope_mismatch"
    else:
        return row
    blockers = row.get("blockers")
    blocker_list = blockers if isinstance(blockers, list) else []
    return row | {
        "decision": "curation_needed",
        "queue_status": status,
        "blockers": sorted({*(str(b) for b in blocker_list), status}),
    }


def _queue_submitted_duplicate_row(
    row: Json,
    runs_root: Path,
    submitted_path: Path | None,
    domain: str | None,
) -> Json:
    if row.get("decision") != "ready_to_publish" or submitted_path is None:
        return row
    fp = memo_fingerprint(row)
    if not fp or fp not in _seen_submission_fingerprints_for_domain(submitted_path, domain):
        return row
    blockers = row.get("blockers")
    blocker_list = blockers if isinstance(blockers, list) else []
    status = "duplicate_submission_fingerprint"
    return row | {
        "decision": "curation_needed",
        "queue_status": status,
        "blockers": sorted({*(str(b) for b in blocker_list), status}),
    }


def _build_queue(
    runs_root: Path,
    include_archive: bool,
    domain: str | None = None,
    submitted_path: Path | None = None,
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
        row = _stored_verdict_for_run(run)
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
        row = _cached_verdict_for_run(run)
        row = row | {
            "domain": load_domain_profile(run_domain).as_metadata(),
            "domain_slug": run_domain,
        }
        row = _queue_ready_row(row, runs_root)
        row = _queue_submitted_duplicate_row(row, runs_root, submitted_path, run_domain)
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


def _cached_domain_queue(
    runs_root: Path, profile_slug: str, _submitted_path: Path | None,
) -> Json | None:
    path = runs_root / f"_publish_queue.{profile_slug}.json"
    if not path.exists():
        return None
    data = _json(path, {})
    if not isinstance(data, dict):
        return None
    out: Json = {
        "_meta": data.get("_meta", {}) if isinstance(data.get("_meta"), dict) else {},
    }
    for bucket in ("ready_to_publish", "agent_repair_needed", "curation_needed", "not_ready"):
        rows = data.get(bucket)
        out[bucket] = [
            row
            for row in rows if isinstance(row, dict)
        ] if isinstance(rows, list) else []
    return out


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
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", str(value))
    return {
        token.lower() for token in raw_tokens
        if (
            len(token) >= 5
            or (3 <= len(token) <= 4 and token.isupper())
        )
        and token.lower() not in _CLUSTER_GENERIC_TOKENS
    }


def _short_family_root(value: str) -> str:
    raw_tokens: list[str] = re.findall(r"[A-Za-z][A-Za-z0-9]*", str(value))
    if not raw_tokens:
        return ""
    token = str(raw_tokens[0]).lower()
    if 3 <= len(token) <= 4 and token not in _CLUSTER_GENERIC_TOKENS:
        return token
    return ""


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


def _family_alias_keys(value: str) -> set[str]:
    tokens = _CLAIM_WORD.findall(str(value).lower())
    if not tokens:
        return set()
    aliases = {"topic:" + "_".join(tokens)}
    compact = "".join(tokens)
    if 2 <= len(compact) <= 8 and compact not in _CLUSTER_GENERIC_TOKENS:
        aliases.add("acronym:" + compact)
    initials = "".join(token[0] for token in tokens if token not in _CLUSTER_GENERIC_TOKENS)
    if len(tokens) >= 2 and 2 <= len(initials) <= 8:
        aliases.add("acronym:" + initials)
    return aliases


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


def _domain_seed_prefixes(domain: str | None) -> tuple[str, ...]:
    if not domain or domain == load_domain_profile(None).slug:
        return ()
    with suppress(OSError, tomllib.TOMLDecodeError, ValueError):
        data = tomllib.loads(load_domain_profile(domain).seed_topics_path.read_text(
            encoding="utf-8",
        ))
        seeds = data.get("seeds")
        topics = seeds.get("topics") if isinstance(seeds, dict) else None
        if isinstance(topics, list):
            return tuple(
                key.removeprefix("topic:")
                for topic in topics
                if (key := _canonical_family_key(str(topic)))
            )
    return ()


def _seed_scope_tokens(seed_prefixes: Iterable[str]) -> set[str]:
    return {
        token.rstrip("s")
        for seed in seed_prefixes
        for token in seed.split("_")
        if len(token.rstrip("s")) >= 3
        and token.rstrip("s") not in _DISCOVERY_SEED_SCOPE_GENERIC_TOKENS
    }


def _topic_in_seed_scope(topic_key: str, aliases: set[str], seed_scope: set[str]) -> bool:
    if not seed_scope:
        return True
    topic_tokens = {
        token.rstrip("s")
        for token in topic_key.split("_")
        if len(token.rstrip("s")) >= 3
    }
    alias_tokens = {
        alias.removeprefix("topic:").rstrip("s")
        for alias in aliases
        if alias.startswith("topic:")
    }
    return bool((topic_tokens | alias_tokens) & seed_scope)


def _other_domain_seed_scope_tokens(domain: str | None) -> set[str]:
    current = load_domain_profile(domain)
    out: set[str] = set()
    for choice in domain_choices():
        if choice == current.slug:
            continue
        with suppress(ValueError):
            profile = load_domain_profile(choice)
        if profile.seed_topics_path == current.seed_topics_path:
            continue
        out.update(_seed_scope_tokens(_domain_seed_prefixes(profile.slug)))
    return out


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
        "decision": _DECISION_REVISE,
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


def _cluster_outcome_tokens(fact: Json, parent_tokens: set[str]) -> set[str]:
    context = set().union(*(
        _shape_tokens(fact, fields)
        for fields in (("population",), ("intervention",), ("comparator",))
    ))
    outcome = _shape_tokens(
        fact,
        ("endpoint", "metric_type", "canonical_phrase", "claim", "finding"),
    )
    return outcome - context - parent_tokens - _OUTCOME_GENERIC_TOKENS


def _facts_share_cluster_shape(anchor: Json, fact: Json, parent_tokens: set[str]) -> bool:
    if not (
        _cluster_outcome_tokens(anchor, parent_tokens)
        & _cluster_outcome_tokens(fact, parent_tokens)
    ):
        return False
    for fields in (("population",), ("intervention",), ("comparator",)):
        left = _shape_tokens(anchor, fields) - parent_tokens
        right = _shape_tokens(fact, fields) - parent_tokens
        if left and right and left & right:
            return True
    return False


def _cluster_coherent_component_ids(
    verdict: Json, cluster_ids: list[str], root: Path, *, min_direct_source_count: int,
) -> list[str]:
    run_dir = _run_path(root, verdict.get("run_dir"))
    facts = _json(run_dir / "all_facts.json", [])
    lanes_raw = _json(run_dir / "fact_lanes.json", {})
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return []
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
    parent_tokens = _topic_tokens(parent)
    usable = [
        (fid, by_id[fid], _source_key_from_fact(by_id[fid]))
        for fid in cluster_ids
        if fid in by_id and lanes.get(fid) == "A_core" and _source_key_from_fact(by_id[fid])
    ]
    for anchor_id, anchor, _source in usable:
        if not _cluster_outcome_tokens(anchor, parent_tokens):
            continue
        component = [
            (fid, source)
            for fid, fact, source in usable
            if fid == anchor_id or _facts_share_cluster_shape(anchor, fact, parent_tokens)
        ]
        sources = {source for _fid, source in component}
        if len(sources) >= min_direct_source_count:
            out: list[str] = []
            seen_sources: set[str] = set()
            for fid, source in component:
                if source in seen_sources:
                    continue
                seen_sources.add(source)
                out.append(fid)
            return out
    return []


def _cluster_has_coherent_component(
    verdict: Json, cluster_ids: list[str], root: Path, *, min_direct_source_count: int,
) -> bool:
    return bool(_cluster_coherent_component_ids(
        verdict, cluster_ids, root, min_direct_source_count=min_direct_source_count,
    ))


def _claim_cluster_repairable(verdict: Json, rec: Json) -> bool:
    decision = str(verdict.get("decision") or "")
    if decision in _AGENT_REPAIR_DECISIONS:
        return True
    if decision != "curation_needed" or rec.get("reason") != "source_coherent_child_cluster":
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
            if len(ids) < min_direct_source_count:
                continue
            ids = _cluster_coherent_component_ids(
                verdict, ids, runs_root,
                min_direct_source_count=min_direct_source_count,
            )
            if not ids:
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
                "surface_type": "publish_alpha_memo",
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
    repairable = [
        _queue_ready_row(row, runs_root)
        for row in _repairable_candidate_verdicts(runs_root, domain)
    ]
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
    for row in additions:
        bucket = str(row.get("decision") or "not_ready")
        if bucket not in merged or not isinstance(merged.get(bucket), list):
            bucket = "not_ready"
        merged[bucket] = [row, *list(merged.get(bucket) or [])]
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
    repaired = bool(verdict.get("_agent_repair_applied") or verdict.get("_staging_refreshed"))
    return (
        verdict.get("decision") in _AGENT_REPAIR_DECISIONS
        and source_count >= min_source_count
        and direct_source_count >= min_direct_source_count
        and blockers <= {"source_dispersion"}
        and (
            verdict.get("decision") != "agent_repair_needed"
            or not blockers
            or repaired
        )
    )


def _has_memo(verdict: Json, root: Path) -> bool:
    run_dir = _run_path(root, verdict.get("run_dir"))
    return (run_dir / "alpha_memo.md").exists()


def _has_falsifier(verdict: Json, root: Path) -> bool:
    """Submit gate: a memo must state what would disprove it before it ships."""
    from agent.signal_memo_writer import falsifier_present

    run_dir = _run_path(root, verdict.get("run_dir"))
    return falsifier_present(_read_text(run_dir / "alpha_memo.md"))


_BOUNDED_SIGNAL_TERMS = frozenset({
    "alpha", "boundary", "bounded", "conditional", "context", "counter",
    "contrast", "diverge", "falsif", "flip", "gap", "heterogen", "limit",
    "mixed", "paradox", "specific", "split", "tension", "threshold", "varies",
})
_BOILERPLATE_MEMO_RE = re.compile(
    r"\b(?:worth checking|new angle|source[- ]backed effect|direct evidence)\b",
    re.I,
)
_ADVICE_OR_SETTLED_RE = re.compile(
    r"\b(?:patients|clinicians|investors|managers|firms)\s+should\b|"
    r"\b(?:proves|guarantees|cures|settled science|definitively)\b",
    re.I,
)


def _alpha_acceptance_status(verdict: Json, root: Path) -> str:
    """Mirror Researka's alpha-memo intake bar before submit."""
    if _is_evidence_map_row(verdict):
        return ""
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    title = str(_memo_headline(memo) or verdict.get("headline") or "").strip()
    if not title:
        return ""
    topic = str(verdict.get("topic") or "")
    title_tokens = _CLAIM_WORD.findall(title.lower())
    topic_tokens = _CLAIM_WORD.findall(topic.replace("_", " ").lower())
    if (
        len(title_tokens) < 3
        or "/" in title
        or (title_tokens == topic_tokens and len(title_tokens) <= 4)
    ):
        return "alpha_title_not_human_readable"
    text = "\n".join((
        title,
        _plain_section(memo, "One-sentence thesis"),
        _plain_section(memo, "Why this is surprising"),
        _plain_section(memo, "What this changes"),
    )).lower()
    if _ADVICE_OR_SETTLED_RE.search(text):
        return "alpha_memo_overclaims_or_advises"
    if _BOILERPLATE_MEMO_RE.search(text):
        return "alpha_memo_boilerplate"
    if not any(term in text for term in _BOUNDED_SIGNAL_TERMS):
        return "alpha_memo_lacks_bounded_signal"
    return ""


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
    if decision.get("decision") not in {_DECISION_REJECT, _DECISION_REVISE}:
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
    if decision.get("decision") not in {_DECISION_REJECT, _DECISION_REVISE}:
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
            publish_io.write_text(path, revised)
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
        domain_slug(ledger.get("domain_slug"))
        or domain_slug(ledger.get("domain"))
        or domain_slug(candidate.get("domain_slug"))
        or domain_slug(candidate.get("domain"))
        or load_domain_profile(None).slug
    )


def _ledger_has_explicit_domain(ledger: Json) -> bool:
    candidate = ledger.get("candidate")
    if not isinstance(candidate, dict):
        candidate = {}
    return bool(
        domain_slug(ledger.get("domain_slug"))
        or domain_slug(ledger.get("domain"))
        or domain_slug(candidate.get("domain_slug"))
        or domain_slug(candidate.get("domain"))
    )


def _submitted_record_domain_for_ledger(runs_root: Path, ledger: Json) -> str:
    submission_id = str(ledger.get("submission_id") or "").strip()
    if not submission_id:
        return ""
    data = _json(runs_root / "_daily_ledger" / "_submitted_fingerprints.json", [])
    if not isinstance(data, list):
        return ""
    for row in data:
        if not isinstance(row, dict):
            continue
        if str(row.get("submission_id") or "").strip() == submission_id:
            return _row_domain(row)
    return ""


def _ledger_domain_for_runs(runs_root: Path, ledger: Json) -> str:
    if _ledger_has_explicit_domain(ledger):
        return _ledger_domain(ledger)
    return _submitted_record_domain_for_ledger(runs_root, ledger) or _ledger_domain(ledger)


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


def _ledger_submission_id(ledger: Json) -> str:
    stored = str(ledger.get("submission_id") or "").strip()
    pending_reason = str(ledger.get("pending_reason") or "").strip()
    if stored and pending_reason in {
        "terminal_resubmit_job_queued",
        "same_parent_terminal_resubmit_queued",
    }:
        terminal = ledger.get("terminal_resubmission")
        if not isinstance(terminal, dict):
            for attempt in reversed(ledger.get("source_literature_fallback_attempts") or []):
                if not isinstance(attempt, dict):
                    continue
                result = attempt.get("terminal_resubmit_submission")
                if isinstance(result, dict):
                    terminal = result
                    break
        if isinstance(terminal, dict):
            parent = (
                _terminal_resubmit_parent_submission_id(terminal)
                or str(ledger.get("parent_submission_id") or "").strip()
            )
            resolved = _terminal_resubmit_poll_submission_id(terminal, parent)
            if resolved:
                return resolved
        return stored
    from_response = publish_decisions.submission_id(ledger.get("submission", {}))
    return from_response or stored


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
    ledger["status"] = publish_status.CycleStatus.DECISION_STALE_PENDING.value
    ledger["final_verdict"] = _DECISION_STALE_PENDING
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
    memo = _read_text(run_dir / "alpha_memo.md") or _read_text(
        run_dir / "source_literature_memo.md",
    )
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


def _ledger_paths_newest_first(ledger_dir: Path) -> list[Path]:
    return sorted(
        ledger_dir.glob("*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )


def _repairable_decisions_by_fingerprint(
    ledger_dir: Path, domain: str | None = None,
) -> dict[str, Json]:
    retryable: dict[str, Json] = {}
    for path in _ledger_paths_newest_first(ledger_dir):
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
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
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
    candidate_run = candidate.get("run_dir") if isinstance(candidate, dict) else None
    if (
        isinstance(decision, dict)
        and isinstance(candidate, dict)
        and (
            _repairable_rejection(decision)
            or (
                bool(_source_literature_topic_from_run(candidate_run))
                and _source_literature_render_repair_revise(decision)
            )
        )
    ):
        decision = _decision_with_resubmission_parent(decision, ledger.get("submission_id"))
        fp = str(candidate.get("fingerprint") or "")
        if fp:
            records.append((fp, candidate.get("run_dir"), decision))
    for attempt in ledger.get("cycle_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        decision = attempt.get("researka_decision")
        run_ref = attempt.get("run_dir")
        if not isinstance(decision, dict) or not (
            _repairable_rejection(decision)
            or (
                bool(_source_literature_topic_from_run(run_ref))
                and _source_literature_render_repair_revise(decision)
            )
        ):
            continue
        decision = _decision_with_resubmission_parent(decision, attempt.get("submission_id"))
        fp = str(attempt.get("fingerprint") or "")
        if fp:
            records.append((fp, run_ref, decision))
    return records


def _decision_with_resubmission_parent(
    decision: Json,
    parent_submission_id: Any,
    *,
    override_existing: bool = False,
) -> Json:
    parent = str(parent_submission_id or "").strip()
    if not parent:
        return decision
    resubmission = decision.get("resubmission")
    if not isinstance(resubmission, dict) or resubmission.get("allowed") is not True:
        return decision
    if str(resubmission.get("parent_submission_id") or "").strip() and not override_existing:
        return decision
    merged = dict(decision)
    merged["resubmission"] = dict(resubmission) | {"parent_submission_id": parent}
    return merged


def _source_literature_topic_from_run(run_ref: Any) -> str:
    name = Path(str(run_ref or "")).name
    return name.split("-source-literature-", 1)[0] if "-source-literature-" in name else ""


def _source_literature_payload_requested_topic(payload: Json) -> str:
    if not isinstance(payload, dict):
        return ""
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    for value in (payload.get("requested_topic"), metadata.get("requested_topic")):
        topic = str(value or "").strip()
        if topic:
            return topic
    return ""


def _source_literature_payload_surface_fingerprint(payload: Json, markdown: str) -> str:
    if not isinstance(payload, dict):
        return hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    topic = str(payload.get("topic") or "").strip()
    title = str(payload.get("title") or payload.get("human_title") or "").strip()
    if topic or title:
        return hashlib.sha256(f"{topic}\n{title}\n{markdown}".encode()).hexdigest()
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _source_literature_candidate_topic(runs_root: Path, candidate: Json) -> str:
    run_ref = candidate.get("run_dir") if isinstance(candidate, dict) else ""
    run_topic = _source_literature_topic_from_run(run_ref)
    if not run_topic:
        return ""
    payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
    return (
        _source_literature_payload_requested_topic(payload)
        or str(candidate.get("topic") or "").strip()
        or run_topic
    )


def _resumable_source_literature_payloads(
    runs_root: Path, domain: str | None, min_sources: int, blocked_topics: set[str],
    *, limit: int = 3,
) -> dict[str, tuple[Json, Json, list[Json]]]:
    out: dict[str, tuple[Json, Json, list[Json]]] = {}
    profile = load_domain_profile(domain)
    for run_dir in sorted(runs_root.glob("*-source-literature-*"), reverse=True):
        run_topic = _source_literature_topic_from_run(run_dir)
        payload = _json(run_dir / "source_literature_payload.json", {})
        topic = _source_literature_payload_requested_topic(payload) or run_topic
        if not topic or topic in out or _family_blocked_topic(topic, blocked_topics):
            continue
        evidence = payload.get("evidence_bundle") if isinstance(payload, dict) else {}
        payload_domain = (
            domain_slug(payload.get("domain"))
            or domain_slug(payload.get("domain_slug"))
            if isinstance(payload, dict) else ""
        )
        if not isinstance(evidence, dict) or not _same_domain(payload_domain, domain):
            continue
        direct_papers = [
            paper for paper in evidence.get("direct_source_papers") or []
            if isinstance(paper, dict)
        ]
        source_bundle = payload.get("source_bundle")
        if (
            not isinstance(source_bundle, list)
            or len(source_bundle) < min_sources
            or int(evidence.get("direct_source_count") or 0) < min_sources
            or publish_literature.substantive_fact_count(direct_papers) < min_sources
            or publish_literature.source_identity_count(
                direct_papers, require_substantive=True,
            ) < min_sources
        ):
            continue
        markdown = str(payload.get("markdown") or "")
        if not markdown.strip():
            continue
        candidate = {
            "topic": topic,
            "run_dir": str(run_dir.relative_to(runs_root)),
            "memo_fingerprint": _source_literature_payload_surface_fingerprint(
                payload, markdown,
            ),
            "domain": profile.as_metadata(),
        }
        if _same_memo_seen(
            runs_root / "_daily_ledger" / "_submitted_fingerprints.json",
            str(candidate.get("memo_fingerprint") or ""),
            _memo_sha256(candidate, runs_root),
            domain,
        ):
            continue
        out[topic] = (candidate, payload, direct_papers)
        if len(out) >= limit:
            break
    return out


def _previous_source_literature_payload_papers(
    runs_root: Path, domain: str | None, topic: str, min_sources: int,
    *, parent_submission_id: str = "",
) -> list[Json]:
    parent = str(parent_submission_id or "").strip()
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
            or not int(ledger.get("submitted") or 0)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            continue
        if parent and str(ledger.get("submission_id") or "").strip() != parent:
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        evidence = payload.get("evidence_bundle") if isinstance(payload, dict) else {}
        source_bundle = payload.get("source_bundle") if isinstance(payload, dict) else None
        direct_papers = [
            paper for paper in evidence.get("direct_source_papers") or []
            if isinstance(paper, dict)
        ] if isinstance(evidence, dict) else []
        source_keys = {
            publish_literature.source_identity_key(source)
            for source in source_bundle if isinstance(source, dict)
        } if isinstance(source_bundle, list) else set()
        direct_keys = {
            publish_literature.source_identity_key(paper)
            for paper in direct_papers
        }
        if (
            isinstance(source_bundle, list)
            and len(source_bundle) >= min_sources
            and not _source_literature_payload_bundle_blocker(payload, min_sources)
            and isinstance(evidence, dict)
            and int(evidence.get("direct_source_count") or 0) >= min_sources
            and publish_literature.substantive_fact_count(direct_papers) >= min_sources
            and publish_literature.source_identity_count(
                direct_papers, require_substantive=True,
            ) >= min_sources
            and len(source_keys & direct_keys) >= min_sources
            and not publish_literature.source_outlet_diversity_below_min(
                direct_papers, min_sources,
            )
        ):
            return direct_papers
    return []


def _source_literature_submission_count(
    runs_root: Path, domain: str | None, topic: str,
) -> int:
    count = 0
    for path in (runs_root / "_daily_ledger").glob("*.json"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic == topic and int(ledger.get("submitted") or 0):
            count += 1
    return count


def _source_literature_clean_terminal_submission_count(
    runs_root: Path, domain: str | None, topic: str,
) -> int:
    count = 0
    for path in (runs_root / "_daily_ledger").glob("*.json"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
            or not int(ledger.get("submitted") or 0)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        decision = ledger.get("researka_decision")
        if (
            row_topic == topic
            and isinstance(decision, dict)
            and _source_literature_clean_terminal_resubmit(decision)
        ):
            count += 1
    return count


def _source_literature_parent_link_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
    *, require_submission_parent: bool = False,
) -> bool:
    parent_submission_id = _resubmission_parent_submission_id(decision)
    if not parent_submission_id:
        return False
    saw_submitted_source_literature = False
    saw_other_submission_parent_payload = False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        saw_submitted_source_literature = True
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata")
        evidence = payload.get("evidence_bundle")
        submission_parent_values = (
            str(payload.get("parent_submission_id") or "").strip(),
            str(metadata.get("revision_of") or "").strip()
            if isinstance(metadata, dict) else "",
            str(evidence.get("revision_of") or "").strip()
            if isinstance(evidence, dict) else "",
        )
        object_parent_values = (
            str(payload.get("parent_object_id") or "").strip(),
            str(metadata.get("revision_of_object_id") or "").strip()
            if isinstance(metadata, dict) else "",
            str(evidence.get("revision_of_object_id") or "").strip()
            if isinstance(evidence, dict) else "",
        )
        has_submission_parent = parent_submission_id in submission_parent_values
        has_object_parent = parent_submission_id in object_parent_values
        if require_submission_parent:
            if has_submission_parent:
                return not has_object_parent
            if any(submission_parent_values):
                saw_other_submission_parent_payload = True
            continue
        if has_submission_parent and has_object_parent:
            return False
    return (
        saw_other_submission_parent_payload
        if require_submission_parent else
        saw_submitted_source_literature
    )


def _source_literature_renderer_feedback_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if not _source_literature_render_repair_revise(decision):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        title = str(payload.get("title") or "").lower()
        markdown = str(payload.get("markdown") or "").lower()
        return (
            "directional support for" in title
            or "## directional grouping" in markdown
            or "directional estimate" in markdown
        )
    return False


def _source_literature_title_ownership_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if (
        not isinstance(decision, dict)
        or decision.get("decision") != _DECISION_REVISE
        or not _resubmission_allowed(decision)
        or str(decision.get("claim_support_verdict") or "").lower() == "unsupported"
    ):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        title = str(payload.get("title") or "").lower()
        return any(marker in title for marker in _SOURCE_LITERATURE_UNOWNED_TITLE_MARKERS)
    return False


def _source_literature_field_ownership_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if not _source_literature_render_repair_revise(decision):
        return False
    notes = _norm(_revision_notes(decision))
    if not any(marker in notes for marker in _SOURCE_LITERATURE_FIELD_OWNERSHIP_MARKERS):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        title = str(payload.get("title") or "").lower()
        markdown = str(payload.get("markdown") or "").lower()
        return (
            " vs null/mixed " not in title
            or "audit note: effect-bearing rows stay metric-specific" not in markdown
        )
    return False


def _source_literature_terminal_resubmit_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if not _clean_supported_revise(decision):
        return False
    if "external author must resubmit" not in _norm(_revision_notes(decision)):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        title = str(payload.get("title") or "").lower()
        markdown = str(payload.get("markdown") or "").lower()
        return (
            " vs null/mixed " in title
            and "audit note: effect-bearing rows stay metric-specific" in markdown
        )
    return False


def _source_literature_publish_framing_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if not _clean_supported_revise(decision):
        return False
    if "external author must resubmit" not in _norm(_revision_notes(decision)):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        text = f"{payload.get('title') or ''}\n{payload.get('markdown') or ''}".lower()
        return any(marker in text for marker in _SOURCE_LITERATURE_OLD_PUBLISH_FRAMING_MARKERS)
    return False


def _source_literature_terminal_feedback_repair_needed(decision: Json) -> bool:
    if "external author must resubmit" not in _norm(_revision_notes(decision)):
        return False
    return (
        _source_literature_render_repair_revise(decision)
        or _supported_minor_revise(decision)
    )


def _source_literature_writer_framing_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if not _source_literature_render_repair_revise(decision):
        return False
    notes = _norm(_revision_notes(decision))
    if not any(term in notes for term in _SOURCE_LITERATURE_WRITER_REPAIR_TERMS):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            return False
        title = str(payload.get("title") or "").lower()
        markdown = str(payload.get("markdown") or "").lower()
        if (
            ("raw accounting" in notes or "headline research signal" in notes)
            and ("5-source map:" in title or "direction-bearing" not in title)
        ):
            return True
        if "outcome-family" in notes and "outcome-family boundary" not in markdown:
            return True
        if (
            ("descriptive modeling" in notes or "modeling-only" in notes or "effect accounting" in notes)
            and "does not test an effect" not in markdown
        ):
            return True
        if "design heterogeneity" in notes and "design heterogeneity:" not in markdown:
            return True
        return (
            ("within-source caveat" in notes or "insignificant effect" in notes)
            and "within-source caveat:" not in markdown
        )
    return False


def _source_literature_clean_terminal_resubmit(decision: Json) -> bool:
    return (
        (_clean_supported_revise(decision) or _supported_minor_revise(decision))
        and "external author must resubmit" in _norm(_revision_notes(decision))
    )


def _source_literature_parented_terminal_resubmit(decision: Json) -> bool:
    return (
        _source_literature_clean_terminal_resubmit(decision)
        and bool(_resubmission_parent_submission_id(decision))
    )


def _source_literature_source_scope_repair_needed(
    runs_root: Path, domain: str | None, topic: str, decision: Json,
) -> bool:
    if not _source_literature_terminal_feedback_repair_needed(decision):
        return False
    notes = _norm(_revision_notes(decision))
    if not any(term in notes for term in _SOURCE_LITERATURE_SOURCE_SCOPE_FEEDBACK_TERMS):
        return False
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict) or not int(ledger.get("submitted") or 0):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        row_topic = _source_literature_candidate_topic(runs_root, candidate)
        if row_topic != topic:
            continue
        payload = _json(_run_path(runs_root, run_ref) / "source_literature_payload.json", {})
        if not isinstance(payload, dict):
            continue
        text = f"{payload.get('title') or ''}\n{payload.get('markdown') or ''}".lower()
        return (
            any(marker in text for marker in _SOURCE_LITERATURE_SOURCE_SCOPE_OLD_MARKERS)
            or "matrix guard: effect-bearing rows below" not in text
        )
    return False


def _repairable_source_literature_topics(
    runs_root: Path, domain: str | None, *, limit: int = 3,
) -> list[str]:
    return list(_repairable_source_literature_decisions(
        runs_root, domain, limit=limit,
    ))


def _recent_source_literature_floor_satisfied_topics(
    ledger_dir: Path, domain: str | None, *, days: int = 2,
) -> set[str]:
    cutoff = time.time() - (max(0, days) * 86400)
    topics: set[str] = set()
    for path in _ledger_paths_newest_first(ledger_dir):
        if path.name.startswith("_"):
            continue
        with suppress(OSError):
            if path.stat().st_mtime < cutoff:
                continue
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(ledger_dir.parent, ledger), domain)
        ):
            continue
        attempts: list[Any] = []
        fallback = ledger.get("source_literature_fallback")
        if isinstance(fallback, dict):
            attempts.append(fallback)
        raw_attempts = ledger.get("source_literature_fallback_attempts")
        if isinstance(raw_attempts, list):
            attempts.extend(raw_attempts)
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            topic = str(attempt.get("topic") or "").strip()
            if (
                topic
                and int(attempt.get("selected_source_count") or 0) >= _DEFAULT_MIN_SUBMIT_SOURCES
                and int(attempt.get("selected_source_fact_count") or 0) >= _DEFAULT_MIN_SUBMIT_SOURCES
                and int(attempt.get("selected_source_identity_count") or 0) >= _DEFAULT_MIN_SUBMIT_SOURCES
            ):
                topics.add(topic)
    return topics


def _repairable_source_literature_decisions(
    runs_root: Path, domain: str | None, *, limit: int = 3,
) -> dict[str, Json]:
    decisions: dict[str, Json] = {}
    checked_topics: set[str] = set()
    published = _recently_published_topics(
        runs_root / "_daily_ledger",
        days=_DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS,
        domain=domain,
    )
    pending = _pending_source_literature_topics(runs_root / "_daily_ledger", domain)
    source_floor_blocked = _recent_source_floor_topics(
        runs_root / "_daily_ledger", days=2, domain=domain,
        source_literature_only=True,
    )
    source_floor_satisfied = _recent_source_literature_floor_satisfied_topics(
        runs_root / "_daily_ledger", domain, days=2,
    )
    structurally_blocked = _recent_source_literature_structural_blocked_topics(
        runs_root / "_daily_ledger", days=2, domain=domain,
    )
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        candidate_topic = str(candidate.get("topic") or "") if isinstance(candidate, dict) else ""
        for _fp, run_ref, decision in _repairable_submission_records(ledger):
            topic = candidate_topic or _source_literature_topic_from_run(run_ref)
            if not topic or topic in decisions or topic in checked_topics:
                continue
            parented_terminal_resubmit = _source_literature_parented_terminal_resubmit(
                decision,
            )
            writer_framing_repair = _source_literature_writer_framing_repair_needed(
                runs_root, domain, topic, decision,
            )
            terminal_feedback_repair = _source_literature_terminal_feedback_repair_needed(
                decision,
            )
            source_floor_repair = (
                parented_terminal_resubmit
                or writer_framing_repair
                or terminal_feedback_repair
            )
            if (
                not source_floor_repair
                and (
                    topic in structurally_blocked
                    or _family_blocked_topic(topic, structurally_blocked)
                )
            ):
                continue
            if topic in published or _family_blocked_topic(topic, published):
                continue
            if topic in pending or _family_blocked_topic(topic, pending):
                continue
            if (
                not (
                    source_floor_repair
                    and (
                        topic in source_floor_satisfied
                        or _family_blocked_topic(topic, source_floor_satisfied)
                    )
                )
                and (
                    topic in source_floor_blocked
                    or _family_blocked_topic(topic, source_floor_blocked)
                )
            ):
                continue
            run_dir = _run_path(runs_root, run_ref)
            if not (run_dir / "source_literature_memo.md").exists():
                continue
            checked_topics.add(topic)
            if _source_literature_submission_count(
                runs_root, domain, topic,
            ) >= _source_literature_attempt_budget(runs_root, domain, topic):
                continue
            decisions[topic] = decision
            if len(decisions) >= limit:
                return decisions
    return decisions


def _priority_source_literature_repair_decisions(
    runs_root: Path, domain: str | None, *, limit: int = 3,
) -> dict[str, Json]:
    decisions = _repairable_source_literature_decisions(
        runs_root, domain, limit=max(limit * 3, limit),
    )
    priority: dict[str, Json] = {}
    for topic, decision in decisions.items():
        if (
            _source_literature_publish_framing_repair_needed(
                runs_root, domain, topic, decision,
            )
            or _source_literature_writer_framing_repair_needed(
                runs_root, domain, topic, decision,
            )
            or _source_literature_terminal_feedback_repair_needed(decision)
            or _source_literature_source_scope_repair_needed(
                runs_root, domain, topic, decision,
            )
        ):
            priority[topic] = decision
            if len(priority) >= limit:
                return priority
    return priority


def _exhausted_source_literature_topics(
    runs_root: Path, domain: str | None,
) -> set[str]:
    counts: dict[str, int] = {}
    for path in (runs_root / "_daily_ledger").glob("*.json"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            continue
        run_ref = candidate.get("run_dir")
        if not _source_literature_topic_from_run(run_ref):
            continue
        topic = str(candidate.get("topic") or "") or _source_literature_topic_from_run(run_ref)
        if topic and int(ledger.get("submitted") or 0):
            counts[topic] = counts.get(topic, 0) + 1
    return {
        topic for topic, count in counts.items()
        if count >= _source_literature_attempt_budget(runs_root, domain, topic)
    }


def _source_literature_attempt_budget(
    runs_root: Path, domain: str | None, topic: str,
) -> int:
    for path in _ledger_paths_newest_first(runs_root / "_daily_ledger"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or not _same_domain(_ledger_domain_for_runs(runs_root, ledger), domain)
        ):
            continue
        candidate = ledger.get("candidate")
        candidate_topic = (
            _source_literature_candidate_topic(runs_root, candidate)
            if isinstance(candidate, dict) else ""
        )
        for _fp, run_ref, decision in _repairable_submission_records(ledger):
            row_topic = candidate_topic or _source_literature_topic_from_run(run_ref)
            if row_topic == topic:
                clean_terminal_resubmit = (
                    _clean_supported_revise(decision)
                    and "external author must resubmit" in _norm(_revision_notes(decision))
                )
                budget = (
                    _SOURCE_LITERATURE_TERMINAL_RESUBMIT_ATTEMPT_LIMIT
                    if clean_terminal_resubmit else
                    _source_literature_repair_attempt_limit(decision)
                )
                if (
                    _clean_supported_revise(decision)
                    and "external author must resubmit" not in _norm(_revision_notes(decision))
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_CLEAN_SUPPORTED_ATTEMPT_LIMIT,
                        ),
                    )
                if _source_literature_parent_link_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    if clean_terminal_resubmit:
                        terminal_count = _source_literature_clean_terminal_submission_count(
                            runs_root, domain, topic,
                        )
                        missing_object_parent = _source_literature_parent_link_repair_needed(
                            runs_root, domain, topic, decision,
                            require_submission_parent=True,
                        )
                        if (
                            terminal_count < _SOURCE_LITERATURE_TERMINAL_RESUBMIT_ATTEMPT_LIMIT
                            or missing_object_parent
                        ):
                            budget = max(budget, count + 1)
                    else:
                        budget = max(
                            budget,
                            min(
                                count + 1,
                                _SOURCE_LITERATURE_PARENT_LINK_REPAIR_ATTEMPT_LIMIT,
                            ),
                        )
                if clean_terminal_resubmit:
                    return budget
                if _source_literature_renderer_feedback_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_RENDERER_FEEDBACK_ATTEMPT_LIMIT,
                        ),
                    )
                if _source_literature_title_ownership_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_TITLE_OWNERSHIP_ATTEMPT_LIMIT,
                        ),
                    )
                if _source_literature_field_ownership_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_FIELD_OWNERSHIP_ATTEMPT_LIMIT,
                        ),
                    )
                if _source_literature_publish_framing_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_PUBLISH_FRAMING_ATTEMPT_LIMIT,
                        ),
                    )
                if _source_literature_writer_framing_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(budget, count + 1)
                if (
                    _source_literature_terminal_feedback_repair_needed(decision)
                    and not _clean_supported_revise(decision)
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_TERMINAL_FEEDBACK_ATTEMPT_LIMIT,
                        ),
                    )
                if _source_literature_source_scope_repair_needed(
                    runs_root, domain, topic, decision,
                ):
                    count = _source_literature_submission_count(runs_root, domain, topic)
                    budget = max(
                        budget,
                        min(
                            count + 1,
                            _SOURCE_LITERATURE_SOURCE_SCOPE_ATTEMPT_LIMIT,
                        ),
                    )
                return budget
    return _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT


def _accepted_shape_profiles(
    runs_root: Path, *, limit: int = 25, domain: str | None = None,
) -> list[Json]:
    profiles: list[Json] = []
    ledger_dir = runs_root / "_daily_ledger"
    for path in sorted(ledger_dir.glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or ledger.get("final_verdict") != _DECISION_ACCEPTED:
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
        if ledger.get("final_verdict") != _DECISION_ACCEPTED and ledger.get("published") != 1:
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
            ledger.get("final_verdict") == _DECISION_REJECTED
            or ledger.get("status") == publish_status.CycleStatus.REVIEWER_REJECTED.value
            or decision.get("decision") == _DECISION_REJECT
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


def _pending_source_literature_topics(
    ledger_dir: Path, domain: str | None = None,
) -> set[str]:
    topics: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or not _same_domain(_ledger_domain(ledger), domain):
            continue
        if (
            ledger.get("status") != publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value
            and ledger.get("final_verdict") != _DECISION_PENDING
        ):
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        run_topic = _source_literature_topic_from_run(candidate.get("run_dir"))
        if not run_topic:
            continue
        requested_topic = _source_literature_candidate_topic(ledger_dir.parent, candidate)
        for value in (
            requested_topic,
            ledger.get("submitted_topic"),
            candidate.get("topic"),
            run_topic,
        ):
            topic = str(value or "").strip()
            if topic:
                topics.add(topic)
    return topics


def _recent_source_floor_topics(
    ledger_dir: Path, *, days: int, domain: str | None = None,
    source_literature_only: bool = False,
) -> set[str]:
    cutoff = time.time() - (max(0, days) * 86400)
    topics: set[str] = set()

    def remember(values: Any) -> None:
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return
        for value in values:
            topic = str(value or "").strip()
            if topic:
                topics.add(topic)

    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        with suppress(OSError):
            if path.stat().st_mtime < cutoff:
                continue
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or not _same_domain(_ledger_domain(ledger), domain):
            continue
        if not source_literature_only:
            remember(ledger.get("source_floor_refresh_topics"))
            for batch in ledger.get("refresh_batches") or []:
                if isinstance(batch, dict):
                    remember(batch.get("skipped_below_source_floor"))
        attempts: list[Any] = []
        fallback = ledger.get("source_literature_fallback")
        if isinstance(fallback, dict):
            attempts.append(fallback)
        raw_attempts = ledger.get("source_literature_fallback_attempts")
        if isinstance(raw_attempts, list):
            attempts.extend(raw_attempts)
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            if str(attempt.get("reason") or "") not in {
                "source_floor_below_min",
                "direct_source_floor_below_min",
                "source_bundle_below_min",
                "requires_fact_level_source_synthesis",
            }:
                continue
            remember(str(attempt.get("topic") or ""))
    return topics


def _recent_source_literature_structural_blocked_topics(
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
        attempts: list[Any] = []
        fallback = ledger.get("source_literature_fallback")
        if isinstance(fallback, dict):
            attempts.append(fallback)
        raw_attempts = ledger.get("source_literature_fallback_attempts")
        if isinstance(raw_attempts, list):
            attempts.extend(raw_attempts)
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            reason = str(attempt.get("reason") or "")
            if reason not in _SOURCE_LITERATURE_STRUCTURAL_BLOCK_REASONS:
                continue
            topic = str(attempt.get("topic") or "").strip()
            if topic:
                topics.add(topic)
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


_NON_BLOCKING_ATTEMPT_STATUSES = {
    publish_status.CycleStatus.PUBLISHED.value,
    publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
    publish_status.CycleStatus.DRY_RUN_SELECTED.value,
}


def _sync_failed_attempt_blocks(
    ledger: Json, blocked_fingerprints: set[str], blocked_topics: set[str],
) -> None:
    immediate_retry = ledger.get("repair_retry_immediate")
    immediate_retry_topic = (
        str(immediate_retry.get("topic") or "").strip()
        if isinstance(immediate_retry, dict) else ""
    )
    for attempt in ledger.get("cycle_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        status = str(attempt.get("status") or "")
        if not status or status in _NON_BLOCKING_ATTEMPT_STATUSES:
            continue
        if (
            status == publish_status.CycleStatus.REVIEWER_REVISE.value
            and immediate_retry_topic
            and immediate_retry_topic == str(attempt.get("topic") or "").strip()
        ):
            continue
        fingerprint = str(attempt.get("fingerprint") or "")
        if fingerprint:
            blocked_fingerprints.add(fingerprint)
        for topic in (
            str(attempt.get("topic") or "").strip(),
            _topic_from_run_ref(attempt.get("run_dir")),
        ):
            if topic:
                blocked_topics.add(topic)


def _repairable_rejection(decision: Json) -> bool:
    if _hard_duplicate_decision(decision):
        return False
    support = str(decision.get("claim_support_verdict") or "").lower()
    if (
        decision.get("decision") == _DECISION_REJECT
        and support == "unsupported"
        and _low_claim_grounding_score(decision)
    ):
        return False
    if _resubmission_allowed(decision):
        return True
    if decision.get("decision") == _DECISION_REVISE:
        return support != "partially_supported"
    if decision.get("decision") == _DECISION_REJECT and support == "partially_supported":
        return False
    if decision.get("decision") == _DECISION_REJECT and support == "unsupported":
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


def _hard_duplicate_decision(decision: Any) -> bool:
    if (
        not isinstance(decision, dict)
        or decision.get("decision") not in {_DECISION_REJECT, _DECISION_REVISE}
    ):
        return False
    reasons = {
        str(decision.get("failure_category") or ""),
        *(str(x) for x in decision.get("failed_checks") or []),
        _revision_notes(decision),
    }
    for gate in decision.get("gate_failures") or []:
        if isinstance(gate, dict):
            reasons.add(str(gate.get("name") or ""))
            reasons.add(str(gate.get("reason") or ""))
    text = " ".join(reasons).lower()
    return (
        "integrity_duplicate" in text
        or "exact-content duplicate" in text
        or "duplicate_submission" in text
        or "substantially new content" in text
        or "same source doi set" in text
        or "merge or differentiate from existing alpha memo" in text
    )


def _submission_attempt_budget(decision: Any) -> int:
    if _clean_supported_revise(decision):
        return _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT + 1
    if isinstance(decision, dict) and decision.get("decision") == _DECISION_REJECT:
        return _MAX_REJECT_ATTEMPTS_PER_FINGERPRINT
    return _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT


def _repair_attempt_limit(decision: Any) -> int:
    budget = _submission_attempt_budget(decision)
    if (
        isinstance(decision, dict)
        and decision.get("decision") == _DECISION_REJECT
        and _resubmission_allowed(decision)
    ):
        return budget + 1
    return budget


def _source_literature_repair_attempt_limit(decision: Any) -> int:
    budget = _repair_attempt_limit(decision)
    if _source_literature_render_repair_revise(decision):
        return max(budget, _SOURCE_LITERATURE_RENDER_REPAIR_ATTEMPT_LIMIT)
    return budget


def _source_literature_render_repair_revise(decision: Any) -> bool:
    if (
        not isinstance(decision, dict)
        or decision.get("decision") != _DECISION_REVISE
        or not _resubmission_allowed(decision)
    ):
        return False
    if str(decision.get("claim_support_verdict") or "").lower() == "unsupported":
        return False
    if decision.get("failure_category"):
        return False
    for key in ("failed_checks", "gate_failures"):
        values = decision.get(key)
        if isinstance(values, list) and values:
            return False
    scores = decision.get("rubric_scores")
    if isinstance(scores, dict):
        for key in ("claim_evidence_alignment", "source_grounding", "synthesis_quality"):
            try:
                if int(scores.get(key, 0)) <= 2:
                    return False
            except (TypeError, ValueError):
                continue
    notes = _norm(_revision_notes(decision))
    if any(term in notes for term in _SOURCE_LITERATURE_RENDER_REPAIR_BLOCK_TERMS):
        return False
    return any(term in notes for term in _SOURCE_LITERATURE_RENDER_REPAIR_TERMS)


def _clean_supported_revise(decision: Any) -> bool:
    if not _supported_revise_without_hard_failures(decision):
        return False
    for key in ("required_revisions", "major_issues", "minor_issues", "failed_checks", "gate_failures"):
        values = decision.get(key)
        if isinstance(values, list) and values:
            return False
    return True


def _supported_minor_revise(decision: Any) -> bool:
    if not _supported_revise_without_hard_failures(decision):
        return False
    for key in ("required_revisions", "major_issues", "failed_checks", "gate_failures"):
        values = decision.get(key)
        if isinstance(values, list) and values:
            return False
    minor = decision.get("minor_issues")
    return isinstance(minor, list) and bool(minor)


def _supported_revise_without_hard_failures(decision: Any) -> bool:
    if (
        not isinstance(decision, dict)
        or decision.get("decision") != _DECISION_REVISE
        or str(decision.get("claim_support_verdict") or "").lower() != "supported"
        or not _resubmission_allowed(decision)
    ):
        return False
    if decision.get("failure_category"):
        return False
    scores = decision.get("rubric_scores")
    if isinstance(scores, dict):
        for value in scores.values():
            try:
                if int(value) < 4:
                    return False
            except (TypeError, ValueError):
                continue
    return True


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


def _resubmission_parent_submission_id(decision: Json) -> str:
    if not _resubmission_allowed(decision):
        return ""
    resubmission = decision.get("resubmission")
    if not isinstance(resubmission, dict):
        return ""
    return str(resubmission.get("parent_submission_id") or "").strip()


def _terminal_resubmit_poll_submission_id(result: Json, parent_submission_id: str) -> str:
    parent = str(parent_submission_id or "").strip()
    for attempt in result.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("response")
        if not isinstance(response, dict):
            continue
        job = response.get("job")
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or "").strip()
        target_id = str(job.get("target_object_id") or "").strip()
        status = str(job.get("status") or "").lower()
        if target_id and target_id != parent:
            return target_id
        if job_id and status in {"pending", "queued", "running"}:
            return job_id
        if job_id and parent and target_id == parent:
            return job_id
    return publish_decisions.submission_id(result)


def _terminal_resubmit_queued_job_id(result: Json, parent_submission_id: str) -> str:
    parent = str(parent_submission_id or "").strip()
    if not parent:
        return ""
    for attempt in result.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("response")
        if not isinstance(response, dict):
            continue
        job = response.get("job")
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or "").strip()
        status = str(job.get("status") or "").lower()
        if job_id and status in {"pending", "queued", "running"}:
            return job_id
    return ""


def _terminal_resubmit_parent_submission_id(result: Json) -> str:
    for attempt in result.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("response")
        if not isinstance(response, dict):
            continue
        submission = response.get("submission")
        if not isinstance(submission, dict):
            continue
        for key in ("parent_submission_id", "parent_object_id"):
            value = str(submission.get(key) or "").strip()
            if value:
                return value
        metadata = submission.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("revision_of", "revision_of_object_id"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    return ""


def _terminal_resubmit_queued_submission_records(ledger: Json) -> list[Json]:
    records: list[Json] = []
    for fallback_attempt in ledger.get("source_literature_fallback_attempts") or []:
        if not isinstance(fallback_attempt, dict):
            continue
        result = fallback_attempt.get("terminal_resubmit_submission")
        if not isinstance(result, dict):
            continue
        for submit_attempt in result.get("attempts") or []:
            if not isinstance(submit_attempt, dict):
                continue
            response = submit_attempt.get("response")
            if not isinstance(response, dict):
                continue
            job = response.get("job")
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("id") or "").strip()
            parent_id = (
                _terminal_resubmit_parent_submission_id(result)
                or str(ledger.get("parent_submission_id") or ledger.get("submission_id") or "").strip()
            )
            target_id = str(job.get("target_object_id") or "").strip()
            poll_id = _terminal_resubmit_poll_submission_id(result, parent_id)
            status = str(job.get("status") or "").lower()
            if not job_id or status not in {"pending", "queued", "running"}:
                continue
            records.append({
                "date": ledger.get("date"),
                "domain": ledger.get("domain"),
                "domain_slug": _ledger_domain(ledger),
                "topic": (
                    fallback_attempt.get("topic")
                    or ledger.get("submitted_topic")
                    or ledger.get("topic")
                ),
                "run_dir": fallback_attempt.get("run_dir") or ledger.get("run_dir"),
                "fingerprint": ledger.get("fingerprint") or ledger.get("memo_sha256"),
                "memo_sha256": ledger.get("memo_sha256"),
                "submission_id": poll_id or job_id,
                "parent_submission_id": parent_id,
                "terminal_resubmit_target_object_id": target_id,
                "terminal_resubmit_queued_job_id": job_id,
                "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                "submit_status": result.get("status"),
                "pending_reason": "terminal_resubmit_job_queued",
            })
    return records


def _promote_terminal_resubmit_ledger(ledger: Json) -> bool:
    records = _terminal_resubmit_queued_submission_records(ledger)
    if not records:
        return False
    record = records[-1]
    submission_id = str(record.get("submission_id") or "").strip()
    if not submission_id:
        return False
    if (
        ledger.get("status") == publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value
        and _ledger_submission_id(ledger) == submission_id
        and ledger.get("final_verdict") == _DECISION_PENDING
    ):
        return False
    ledger.update({
        "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
        "final_verdict": _DECISION_PENDING,
        "submitted": 1,
        "published": 0,
        "submitted_topic": record.get("topic") or ledger.get("submitted_topic"),
        "submission_id": submission_id,
        "pending_reason": record.get("pending_reason"),
        "parent_submission_id": record.get("parent_submission_id"),
    })
    return True


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
        if _is_evidence_map_row(verdict):
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
    for fid in re.findall(r"`fact_id=([^`]+)`", section):
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
        r"`fact_id=([^`]+)`\s+\(`([^`]+)`\)",
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
        lanes = _current_lane_map(run_dir, facts, _selection_topic(verdict))
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


def _study_title_key_from_fact(fact: Json) -> str:
    paper = fact.get("source_paper") or {}
    if not isinstance(paper, dict):
        return ""
    tokens = _CLAIM_WORD.findall(str(paper.get("title") or "").lower())
    return " ".join(tokens) if len(tokens) >= 5 else ""


def _duplicate_study_evidence(verdict: Json, root: Path) -> Json:
    facts = (
        _map_citable_facts(verdict, root)
        if _is_evidence_map_row(verdict)
        else _memo_source_facts(verdict, root, ("Evidence",), {"A_core"})
    )
    seen: dict[str, tuple[str, str]] = {}
    duplicates: list[Json] = []
    for fact in facts:
        source_key = _source_key_from_fact(fact)
        title_key = _study_title_key_from_fact(fact)
        if not source_key or not title_key:
            continue
        paper = fact.get("source_paper") or {}
        title = str(paper.get("title") or "").strip()
        previous = seen.get(title_key)
        if previous and previous[0] != source_key:
            duplicates.append({
                "title": title or previous[1],
                "source_key": source_key,
                "duplicate_of": previous[0],
            })
        else:
            seen[title_key] = (source_key, title)
    if not duplicates:
        return {}
    return {
        "duplicate_source_evidence": {
            "count": len(duplicates),
            "examples": duplicates[:3],
        },
    }


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
    if not isinstance(facts, list):
        return []
    lane = _current_lane_map(run_dir, facts, _selection_topic(verdict))
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
        if _empirical_map_fact(f)
    ]


_NON_EMPIRICAL_MAP_RE = re.compile(
    r"\b(review|meta[- ]analysis|consensus|endpoint|power to detect|"
    r"availability|pricing|affordability|prescription rate)\b",
    flags=re.I,
)


def _empirical_map_fact(fact: Json) -> bool:
    paper = fact.get("source_paper") or {}
    title = str(paper.get("title") or "").strip()
    if not title or not (
        str(paper.get("doi") or "").strip() or str(paper.get("pmid") or "").strip()
    ):
        return False
    text = " ".join(str(fact.get(k) or "") for k in (
        "canonical_phrase", "intervention", "population", "endpoint", "sub_topic",
    ))
    return not _NON_EMPIRICAL_MAP_RE.search(f"{title} {text}")


def _topic_tokens(topic: Any) -> set[str]:
    raw = str(topic or "").replace("_", " ").lower()
    tokens = set(_CLAIM_WORD.findall(raw))
    return tokens | {t[:-1] for t in tokens if t.endswith("s") and len(t) > 4}


def _map_scope_coherent(verdict: Json, root: Path, min_sources: int) -> bool:
    """A map must be a bounded landscape, not every citable row for a broad topic.

    Citation floors prove breadth; this proves the breadth is around at least one
    shared structural axis. Topic tokens are ignored, so "metformin use" cannot
    pass merely because every row mentions metformin while populations/endpoints
    are unrelated.
    """
    if min_sources <= 1:
        return True
    topic_tokens = _topic_tokens(_selection_topic(verdict))
    fields = (("population",), ("intervention",), ("comparator",), ("endpoint",))
    for group in fields:
        counts: dict[str, set[str]] = {}
        for fact in _map_citable_facts(verdict, root):
            source = _source_key_from_fact(fact)
            if not source:
                continue
            for token in _shape_tokens(fact, group) - topic_tokens:
                counts.setdefault(token, set()).add(source)
        if any(len(sources) >= min_sources for sources in counts.values()):
            return True
    return False


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
    if _is_evidence_map_row(verdict):
        return len(_map_citable_facts(verdict, root))
    return len(_memo_source_papers(verdict, root, ("Evidence", "Evidence receipts"), {"A_core"}))


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
        for p in _memo_source_papers(verdict, root, ("Evidence", "Evidence receipts"), {"A_core"})
    } - {"", "pmid:"})
    if len(ids) < 2:
        run_dir = _run_path(root, verdict.get("run_dir"))
        payload = _json(run_dir / "source_literature_payload.json", {})
        bundle = payload.get("source_bundle") if isinstance(payload, dict) else []
        if isinstance(bundle, list):
            ids = sorted({
                (str(p.get("doi") or "").strip().lower()
                 or str(p.get("url") or "").strip().lower())
                for p in bundle if isinstance(p, dict)
            } - {""})
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
        if not (row.get("published") or row.get("final_verdict") == _DECISION_ACCEPTED):
            continue
        sig = str(row.get("bundle_signature") or "") or _bundle_signature(row, root)
        if sig:
            sigs.add(sig)
    return sigs


def _hard_duplicate_bundle_signatures(
    ledger_dir: Path, domain: str | None, root: Path,
) -> set[str]:
    sigs: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or not _same_domain(_ledger_domain(ledger), domain):
            continue
        records = [ledger, *(x for x in ledger.get("cycle_attempts") or [] if isinstance(x, dict))]
        for record in records:
            decision = record.get("researka_decision") if isinstance(record, dict) else None
            if not _hard_duplicate_decision(decision):
                continue
            candidate_raw = record.get("candidate")
            candidate = candidate_raw if isinstance(candidate_raw, dict) else {}
            run_ref = record.get("run_dir") or candidate.get("run_dir")
            sig = _bundle_signature({"run_dir": run_ref}, root) if run_ref else ""
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


def _source_titles_share_focus(facts: list[Json], min_sources: int, topic: str) -> bool:
    counts: dict[str, int] = {}
    titled_sources = 0
    title_generic = _COHERENCE_GENERIC_TOKENS | {"paper", "source", "sources"}
    topic_tokens = {
        token for token in _CLAIM_WORD.findall(topic.lower())
        if len(token) >= 4 and token not in title_generic
    }
    for fact in facts:
        paper = fact.get("source_paper") or {}
        title = str(paper.get("title") or "").strip() if isinstance(paper, dict) else ""
        tokens = {
            token for token in _CLAIM_WORD.findall(title.lower())
            if len(token) >= 4 and token not in title_generic
        }
        if not tokens:
            continue
        titled_sources += 1
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
    threshold = min(3, min_sources)
    if titled_sources < min_sources:
        return True
    if topic_tokens:
        return any(counts.get(token, 0) >= threshold for token in topic_tokens)
    return max(counts.values(), default=0) >= threshold


def _identical_result_shape_bundle(facts: list[Json], min_sources: int) -> bool:
    signatures: list[str] = []
    fields = (
        "population", "intervention", "comparator", "outcome", "endpoint",
        "metric", "signal_family", "study_design",
    )
    for fact in facts:
        shape = fact.get("result_shape")
        if not isinstance(shape, dict):
            return False
        signature = json.dumps(
            {field: _norm(shape.get(field)) for field in fields if shape.get(field)},
            sort_keys=True,
        )
        if not signature:
            return False
        signatures.append(signature)
    return len(signatures) >= min_sources and len(set(signatures)) == 1


def _llm_cluster_backed(verdict: Json, root: Path) -> bool:
    """Whether the memo leads with a validated claim cluster for source floors."""
    if verdict.get("_claim_cluster_candidate") and verdict.get("_claim_cluster_fact_ids"):
        return True
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
    if (
        _identical_result_shape_bundle(facts, min_direct_source_count)
        and not _source_titles_share_focus(
            facts, min_direct_source_count, _selection_topic(verdict),
        )
    ):
        return False
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
        return checked_dims >= 2 and shared_dims >= 2
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


def _source_year(paper: Json) -> int | None:
    explicit = _year(paper.get("year") or paper.get("publication_year"))
    if explicit is not None:
        return explicit
    text = " ".join(str(paper.get(key) or "") for key in (
        "doi", "url", "doi_url", "canonical_url", "title", "paper_title",
    ))
    for match in re.findall(r"\b(?:19|20)\d{2}\b", text):
        if (year := _year(match)) is not None:
            return year
    return None


def _evidence_type(paper: Json) -> str:
    text = _norm(" ".join(
        str(paper.get(key) or "")
        for key in (
            "title", "journal", "doi", "publication_type", "type", "source_type",
        )
    ))
    if (
        "review" in text
        or "meta-analysis" in text
        or "meta analysis" in text
        or "cochrane" in text
        or "14651858.cd" in text
        or "14651858 cd" in text
    ):
        return "review"
    return "primary"


def _source_bundle(papers: list[Json]) -> list[Json]:
    bundle: list[Json] = []
    for paper in papers:
        title = str(paper.get("title") or "").strip()
        doi = str(paper.get("doi") or "").strip() or None
        pmid = str(paper.get("pmid") or "").strip() or None
        ident = str(
            paper.get("id") or paper.get("paper_id") or paper.get("openalex_id") or "",
        ).strip()
        # Researka rejects bundles carrying unverifiable sources. A receipt is
        # only citable with a resolvable identifier or URL; drop title-only sources.
        # The accepted bundle schema has no pmid field, so a PMID-only paper is
        # made verifiable through its resolvable PubMed URL rather than presented
        # as identifier-less.
        url = paper.get("url") or None
        if not url and ident.startswith("https://openalex.org/"):
            url = ident
        if not url and ident.startswith("W") and ident[1:].isdigit():
            url = f"https://openalex.org/{ident}"
        if not title or not (doi or pmid or url):
            continue
        if not url and doi:
            url = f"https://doi.org/{doi}"
        elif not url and pmid:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        item = {
            "title": title,
            "url": url,
            "doi": doi,
            "year": _source_year(paper),
            "evidence_type": _evidence_type(paper),
        }
        for field in (
            "journal_name", "journal", "venue", "publisher", "source",
            "source_outlet", "source_name", "container_title",
            "publication_venue", "openalex_id", "doi_url", "canonical_url",
        ):
            if paper.get(field):
                item[field] = paper[field]
        if isinstance(paper.get("source_fact"), dict):
            item["source_fact"] = paper["source_fact"]
        bundle.append(item)
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
    if not isinstance(facts, list):
        return _source_count_from_verdict(verdict)
    lanes = _current_lane_map(run_dir, facts, _selection_topic(verdict))
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
    duplicate_rejected_bundle_sigs = _hard_duplicate_bundle_signatures(
        submitted_path.parent, domain, runs_root,
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
            1 if _is_evidence_map_row(r) else 0,
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
        raw_retry_decision = retry_decisions.get(raw_fp)
        if (
            not verdict.get("_claim_cluster_candidate")
            and (raw_fp not in seen or raw_fp in retry_decisions)
        ):
            verdict = _current_selection_verdict(verdict, runs_root)
        fp = memo_fingerprint(verdict)
        if raw_retry_decision is not None and fp not in retry_decisions:
            retry_decisions[fp] = raw_retry_decision
        if raw_fp in retryable:
            retryable.add(fp)
        source_count = _source_count(verdict, runs_root)
        direct_source_count = _direct_source_count(verdict, runs_root)
        corpus_source_count = _corpus_source_count(verdict, runs_root)
        shape_bonus = accepted_shape_bonus(verdict, shape_profiles)
        status = "eligible"
        duplicate_studies: Json = {}
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
        family_blocked = bool(
            canonical_family_keys & blocked_family_keys
        ) or any(_family_blocked_topic(value, topic_blocked) for value in _family_values(verdict))
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
                if agent_repair:
                    verdict["_agent_repair_applied"] = True
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
        if (fp in seen and not retry_after_rejection) or retry_fingerprint_unchanged:
            status = "duplicate_submission_fingerprint"
        elif exhausted_topic:
            status = "cycle_exhausted_topic"
        elif cycle_blocked:
            status = "cycle_failed_submission"
        elif not has_memo:
            status = "missing_alpha_memo"
        elif not approved:
            status = "agent_repair_failed" if memo_refreshed else "agent_repair_needed"
        elif not _has_falsifier(verdict, runs_root):
            status = "memo_missing_falsifier"
        else:
            alpha_acceptance_status = _alpha_acceptance_status(verdict, runs_root)
            if alpha_acceptance_status:
                status = alpha_acceptance_status
                missing_audit_sidecars = []
            else:
                missing_audit_sidecars = _missing_audit_sidecars(verdict, runs_root)
            if missing_audit_sidecars and memo_refresher and not memo_refreshed:
                run_dir = _run_path(runs_root, verdict.get("run_dir"))
                refresh_verdict = verdict | {"_repair_decision": retry_decisions.get(fp)}
                memo_refreshed = memo_refresher(run_dir, refresh_verdict)
                if memo_refreshed:
                    verdict = _reload_verdict_after_memo_refresh(refresh_verdict, run_dir)
                    if agent_repair:
                        verdict["_agent_repair_applied"] = True
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
                and _is_evidence_map_row(verdict)
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
                elif not _map_scope_coherent(
                    verdict, runs_root, _alpha_memo_int("evidence_map_min_citations", 10),
                ):
                    status = "evidence_map_scope_mismatch"
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
                # gate must use the same lower floor. Shape coherence remains a
                # final submit guard against heterogeneous receipt rows.
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
                if bundle_sig and bundle_sig in duplicate_rejected_bundle_sigs:
                    status = "duplicate_publication_bundle"
                elif bundle_sig and bundle_sig in published_bundle_sigs:
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
                else:
                    duplicate_studies = _duplicate_study_evidence(verdict, runs_root)
                    if duplicate_studies:
                        status = (
                            publish_status.CandidateStatus
                            .DUPLICATE_SOURCE_EVIDENCE.value
                        )
                    elif (
                        not _is_evidence_map_row(verdict)
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
            "domain_slug": domain or _row_domain(verdict),
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
        if duplicate_studies:
            row["duplicate_source_evidence"] = duplicate_studies["duplicate_source_evidence"]
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


def _source_literature_title_key(title: Any) -> str:
    return publish_literature.title_key(title)


def _source_literature_boundary_quality(
    topic: str, papers: list[Json], min_sources: int, profile_slug: str = "",
    *, require_substantive_sources: bool = False,
) -> tuple[bool, str]:
    selected = publish_literature.select_boundary_papers(
        topic,
        papers,
        min_sources,
        strict_topic_coverage=publish_literature._non_biomedical(profile_slug),
        profile_slug=profile_slug,
    )
    if require_substantive_sources and len(selected) >= min_sources:
        if publish_literature.substantive_fact_count(selected) < min_sources:
            return False, "requires_fact_level_source_synthesis"
        if publish_literature.source_identity_count(
            selected,
            require_substantive=True,
        ) < min_sources:
            return False, "source_fact_diversity_below_min"
        if publish_literature.source_outlet_diversity_below_min(selected, min_sources):
            return False, "source_outlet_diversity_below_min"
    ok, reason = publish_literature.boundary_quality(
        topic,
        papers,
        min_sources,
        strict_topic_coverage=publish_literature._non_biomedical(profile_slug),
        profile_slug=profile_slug,
    )
    if not ok or not require_substantive_sources:
        return ok, reason
    return True, "ok"


def _paper_key(paper: Json, default: Any = "") -> str:
    return publish_literature.paper_key(paper, default)


def _source_literature_fact(item: Json) -> Json:
    return publish_literature.source_fact(item)


def _source_literature_fact_count(papers: list[Json]) -> int:
    return publish_literature.fact_count(papers)


def _source_literature_context_family(value: Any) -> str:
    return publish_literature.context_family(value)


def _join_contexts(values: list[str]) -> str:
    return publish_literature.join_contexts(values)


def _fetch_source_literature_papers(
    topic: str, limit: int, *, domain: str = "longevity_research",
) -> list[Json]:
    return publish_literature.fetch_papers(
        topic, limit, domain=domain, settings_loader=load_settings,
    )


def _fullraw_seed_discovery_enabled() -> bool:
    disabled = {"0", "false", "no", "off"}
    if os.environ.get("TOPIC_DISCOVERY_FULLRAW_FALLBACK", "1").lower() in disabled:
        return False
    return bool(
        os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "").strip()
        or os.environ.get("V5_MEMO_FULL_RAW_INDEX_TOKEN", "").strip()
        or os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "").strip()
        or os.environ.get("RESEARKA_FULLRAW_SEARCH_URL", "").strip()
        or os.environ.get("RESEARKA_FULLRAW_INDEX_TOKEN", "").strip()
        or os.environ.get("RESEARKA_FULLRAW_TOKEN", "").strip()
    )


def _source_literature_topic_candidates(
    runs_root: Path,
    profile_slug: str,
    min_sources: int,
    blocked_topics: set[str] | None = None,
    *,
    limit: int = 5,
    soft_broad_blocked_topics: set[str] | None = None,
) -> list[str]:
    discovery_dir = runs_root / "_topics_discovery"
    seed_scope = _seed_scope_tokens(_domain_seed_prefixes(profile_slug))
    paths = sorted(
        discovery_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    exhausted_topics = _exhausted_source_literature_topics(runs_root, profile_slug)
    blocked = set(blocked_topics or set()) | exhausted_topics
    topics: list[str] = []
    seen: set[str] = set()
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
            raw_source_papers = row.get("source_papers")
            source_paper_count = (
                len(raw_source_papers) if isinstance(raw_source_papers, list) else 0
            )
            row_soft_blocked_topics = soft_broad_blocked_topics
            if source_paper_count >= min_sources:
                row_soft_blocked_topics = set(soft_broad_blocked_topics or set()) | exhausted_topics
            if not topic or topic in seen or _source_literature_family_blocked_topic(
                topic, blocked, soft_broad_blocked_topics=row_soft_blocked_topics,
            ):
                continue
            topic_key = _canonical_family_key(topic).removeprefix("topic:")
            topic_tokens = {
                token.rstrip("s") for token in topic_key.split("_")
                if len(token.rstrip("s")) >= 3
            }
            if "anti" in topic_tokens and seed_scope and not ((topic_tokens - {"anti"}) & seed_scope):
                continue
            if topic_tokens and not (topic_tokens - _DISCOVERY_PARENT_GENERIC_TOKENS):
                continue
            paper_count = int(row.get("paper_count") or 0)
            fact_source_count = int(row.get("fact_source_count") or 0)
            if paper_count >= min_sources and (
                fact_source_count >= min_sources
                or _source_literature_fallback_submit_enabled()
                or publish_literature._non_biomedical(profile_slug)
            ):
                topics.append(topic)
                seen.add(topic)
                if len(topics) >= limit:
                    return topics[:limit]
        if len(topics) >= limit:
            return topics[:limit]
    queue_paths = (
        runs_root / f"_publish_queue.{profile_slug}.json",
        runs_root / "_publish_queue.json",
    )
    for path in queue_paths:
        data = _json(path, {})
        if not isinstance(data, dict):
            continue
        for bucket in ("not_ready", "curation_needed", "agent_repair_needed"):
            rows = data.get(bucket)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or not _same_domain(_row_domain(row), profile_slug):
                    continue
                topic = str(row.get("topic") or "").strip()
                if not topic or topic in seen or _source_literature_family_blocked_topic(
                    topic, blocked,
                    soft_broad_blocked_topics=soft_broad_blocked_topics,
                ):
                    continue
                topic_key = _canonical_family_key(topic).removeprefix("topic:")
                topic_tokens = {
                    token.rstrip("s") for token in topic_key.split("_")
                    if len(token.rstrip("s")) >= 3
                }
                if "anti" in topic_tokens and seed_scope and not ((topic_tokens - {"anti"}) & seed_scope):
                    continue
                if topic_tokens and not (topic_tokens - _DISCOVERY_PARENT_GENERIC_TOKENS):
                    continue
                topics.append(topic)
                seen.add(topic)
                if len(topics) >= limit:
                    return topics[:limit]
    return topics[:limit]


def _source_literature_blocked_parent_variant_topics(
    runs_root: Path,
    profile_slug: str,
    min_sources: int,
    broad_blocked_topics: set[str],
    exact_blocked_topics: set[str],
    hard_family_blocked_topics: set[str],
    *,
    limit: int,
    soft_broad_blocked_topics: set[str] | None = None,
) -> list[str]:
    if not broad_blocked_topics or limit <= 0:
        return []
    discovery_dir = runs_root / "_topics_discovery"
    seed_scope = _seed_scope_tokens(_domain_seed_prefixes(profile_slug))
    paths = sorted(
        discovery_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    parent_limit = max(limit * 3, limit)
    parents: list[str] = []
    seen_parents: set[str] = set()
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
            if (
                not topic
                or topic in seen_parents
                or not _source_literature_family_blocked_topic(
                    topic,
                    broad_blocked_topics,
                    soft_broad_blocked_topics=soft_broad_blocked_topics,
                )
                or _source_literature_family_blocked_topic(
                    topic,
                    hard_family_blocked_topics,
                    soft_broad_blocked_topics=soft_broad_blocked_topics,
                )
            ):
                continue
            topic_key = _canonical_family_key(topic).removeprefix("topic:")
            topic_tokens = {
                token.rstrip("s") for token in topic_key.split("_")
                if len(token.rstrip("s")) >= 3
            }
            if "anti" in topic_tokens and seed_scope and not ((topic_tokens - {"anti"}) & seed_scope):
                continue
            if topic_tokens and not (topic_tokens - _DISCOVERY_PARENT_GENERIC_TOKENS):
                continue
            raw_source_papers = row.get("source_papers")
            source_paper_count = (
                len(raw_source_papers) if isinstance(raw_source_papers, list) else 0
            )
            paper_count = int(row.get("paper_count") or 0)
            fact_source_count = int(row.get("fact_source_count") or 0)
            if paper_count < min_sources or (
                fact_source_count < min_sources
                and source_paper_count < min_sources
                and not _source_literature_fallback_submit_enabled()
                and not publish_literature._non_biomedical(profile_slug)
            ):
                continue
            parents.append(topic)
            seen_parents.add(topic)
            if len(parents) >= parent_limit:
                break
        if len(parents) >= parent_limit:
            break
    exact_keys = {_canonical_family_key(topic) for topic in exact_blocked_topics}
    topics: list[str] = []
    seen: set[str] = set()
    for parent in parents:
        if not _source_literature_family_blocked_topic(
            parent,
            broad_blocked_topics,
            soft_broad_blocked_topics=soft_broad_blocked_topics,
        ):
            continue
        for variant in _source_literature_fetch_topics(parent)[1:]:
            variant = cap_topic_slug(variant)
            variant_key = _canonical_family_key(variant)
            if (
                not variant
                or variant in seen
                or variant in exact_blocked_topics
                or variant_key in exact_keys
                or _source_literature_family_blocked_topic(
                    variant,
                    hard_family_blocked_topics,
                    soft_broad_blocked_topics=soft_broad_blocked_topics,
                )
            ):
                continue
            topics.append(variant)
            seen.add(variant)
            if len(topics) >= limit:
                return topics
    return topics


def _source_literature_discovery_papers(
    runs_root: Path, profile_slug: str, topic: str, min_sources: int,
) -> list[Json]:
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
            if not isinstance(row, dict) or str(row.get("topic") or "").strip() != topic:
                continue
            raw = row.get("source_papers")
            papers = [paper for paper in raw if isinstance(paper, dict)] if isinstance(raw, list) else []
            if len(papers) >= min_sources:
                papers = publish_literature.with_metadata_source_facts(topic, papers)
                unique: list[Json] = []
                seen_titles: set[str] = set()
                for paper in papers:
                    key = publish_literature.title_key(paper.get("title"))
                    if key and key not in seen_titles:
                        seen_titles.add(key)
                        unique.append(paper)
                return unique if len(unique) >= min_sources else papers
    return []


def _source_literature_related_discovery_papers(
    runs_root: Path, profile_slug: str, topic: str, min_sources: int,
) -> list[Json]:
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
            parent = str(row.get("topic") or "").strip()
            if topic not in _source_literature_fetch_topics(parent)[1:]:
                continue
            raw = row.get("source_papers")
            papers = [paper for paper in raw if isinstance(paper, dict)] if isinstance(raw, list) else []
            if len(papers) < min_sources:
                continue
            papers = publish_literature.with_metadata_source_facts(topic, papers)
            if _source_literature_boundary_quality(
                topic, papers, min_sources, profile_slug,
                require_substantive_sources=_source_literature_fallback_submit_enabled(),
            )[0]:
                return papers
    return []


def _source_literature_candidate_papers(
    runs_root: Path, profile_slug: str, topic: str, min_sources: int, fetch_limit: int,
    *, allow_live_fetch: bool = True,
) -> list[Json]:
    papers = _source_literature_discovery_papers(
        runs_root, profile_slug, topic, min_sources,
    )
    if papers and _source_literature_boundary_quality(
        topic, papers, min_sources, profile_slug,
        require_substantive_sources=_source_literature_fallback_submit_enabled(),
    )[0]:
        return papers
    related = _source_literature_related_discovery_papers(
        runs_root, profile_slug, topic, min_sources,
    )
    if related:
        return related
    if not allow_live_fetch:
        return papers
    fetched = _fetch_source_literature_papers(topic, fetch_limit, domain=profile_slug)
    return fetched or papers


def _source_literature_preflight_candidate_papers(
    runs_root: Path, profile_slug: str, topic: str, min_sources: int, fetch_limit: int,
) -> list[Json]:
    old = {
        key: os.environ.get(key)
        for key in _SOURCE_LIT_PREFLIGHT_FULLRAW_DEFAULTS
    }
    try:
        for key, value in _SOURCE_LIT_PREFLIGHT_FULLRAW_DEFAULTS.items():
            os.environ.setdefault(key, value)
        return _source_literature_candidate_papers(
            runs_root, profile_slug, topic, min_sources, fetch_limit,
        )
    finally:
        for key, old_value in old.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _source_literature_topic_candidate(
    runs_root: Path, profile_slug: str, min_sources: int, blocked_topics: set[str] | None = None,
    *, soft_broad_blocked_topics: set[str] | None = None,
) -> str | None:
    topics = _source_literature_topic_candidates(
        runs_root, profile_slug, min_sources, blocked_topics, limit=1,
        soft_broad_blocked_topics=soft_broad_blocked_topics,
    )
    return topics[0] if topics else None


def _source_literature_fetch_topics(topic: str) -> list[str]:
    raw_tokens = publish_literature.title_key(topic).split()
    domain_token = next(
        (token for token in ("aging", "ageing", "longevity") if token in raw_tokens),
        "",
    )
    tokens = [
        token for token in raw_tokens
        if len(token) >= 3 and token not in (_DISCOVERY_PARENT_GENERIC_TOKENS | {"longevity"})
    ]
    topics = [topic]

    def add_candidate(core: list[str]) -> None:
        if len(core) < 2:
            return
        candidates = []
        if domain_token and domain_token not in core:
            candidates.append("_".join([*core, domain_token]))
        elif not domain_token:
            candidates.append("_".join(core))
        for candidate in candidates:
            if candidate and candidate not in topics:
                topics.append(candidate)

    for size in range(len(tokens) - 1, 2, -1):
        add_candidate(tokens[:size])
    if len(tokens) >= 4:
        add_candidate([*tokens[:2], tokens[-1]])
        add_candidate(tokens[-2:])
    if len(tokens) < 4 and (len(tokens) > 2 or len(tokens) == len(raw_tokens)):
        add_candidate(tokens[:2])
    if len(topics) == 1 and len(raw_tokens) >= 2:
        for pair in (raw_tokens[:2], raw_tokens[-2:]):
            candidate = "_".join(pair)
            if candidate and candidate not in topics:
                topics.append(candidate)
    return topics




def _source_literature_family_blocked_topic(
    topic: str, blocked_topics: set[str], *,
    soft_broad_blocked_topics: set[str] | None = None,
) -> bool:
    soft_blocked = soft_broad_blocked_topics or set()
    if _family_blocked_topic(topic, blocked_topics - soft_blocked):
        return True
    topic_key = _canonical_family_key(topic)
    topic_tokens = _family_tokens(topic)
    if not topic_tokens:
        return False
    for blocked in blocked_topics:
        blocked_tokens = _family_tokens(blocked)
        if blocked in soft_blocked:
            if topic == blocked or topic_key == _canonical_family_key(blocked):
                return True
            if (
                blocked_tokens < topic_tokens
                and topic_tokens & {"aging", "ageing", "longevity"}
            ):
                continue
        if _family_blocked_topic(topic, {blocked}):
            return True
        if blocked_tokens and topic_tokens & blocked_tokens and min(
            len(topic_tokens), len(blocked_tokens),
        ) == 1:
            return True
    return False


def _family_blocked_topic(topic: str, blocked_topics: set[str]) -> bool:
    if topic in blocked_topics:
        return True
    topic_key = _canonical_family_key(topic)
    topic_aliases = _family_alias_keys(topic)
    topic_tokens = _family_tokens(topic)
    if not topic_tokens and not topic_aliases:
        return False
    for blocked in blocked_topics:
        blocked_aliases = _family_alias_keys(blocked)
        if (
            topic_key and topic_key == _canonical_family_key(blocked)
        ) or (topic_aliases and blocked_aliases and topic_aliases & blocked_aliases):
            return True
        blocked_tokens = _family_tokens(blocked)
        if not blocked_tokens:
            continue
        short_root = _short_family_root(blocked)
        if short_root and short_root in {
                token.lower()
                for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", str(topic))
                if 3 <= len(token) <= 4
                and token.lower() not in _CLUSTER_GENERIC_TOKENS
        }:
            return True
        overlap = len(topic_tokens & blocked_tokens)
        if overlap >= 2 and overlap / min(len(topic_tokens), len(blocked_tokens)) >= 0.5:
            return True
    return False


def _fresh_parent_topics_from_discovery(
    runs_root: Path,
    profile_slug: str,
    blocked_topics: set[str],
    *,
    limit: int,
    min_sources: int,
    soft_source_floor_blocked_topics: set[str] | None = None,
) -> list[str]:
    discovery_dir = runs_root / "_topics_discovery"
    seed_prefixes = _domain_seed_prefixes(profile_slug)
    seed_scope = _seed_scope_tokens(seed_prefixes)
    other_seed_scope = _other_domain_seed_scope_tokens(profile_slug)
    soft_source_floor_blocked_topics = soft_source_floor_blocked_topics or set()
    soft_source_floor_blocked_keys = {
        _canonical_family_key(topic) for topic in soft_source_floor_blocked_topics
    }
    paths = sorted(
        discovery_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    candidates: list[tuple[tuple[int, int, int, int, int, int, str], str, set[str]]] = []
    for recency, path in enumerate(paths):
        data = _json(path, {})
        if not isinstance(data, dict) or not _same_domain(_row_domain(data), profile_slug):
            continue
        receipts = (data.get("fullraw_seed_probe") or {}).get("receipts") or data.get("fullraw_probe_receipts") or data.get("seed_probe_receipts")
        receipt_rank = 0 if receipts else 1
        raw_rows = data.get("all") or data.get("top")
        if not isinstance(raw_rows, list):
            continue
        discovery_mtime = 0.0
        with suppress(OSError):
            discovery_mtime = path.stat().st_mtime
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            topic = cap_topic_slug(str(row.get("topic") or "").strip())
            aliases = _family_alias_keys(topic)
            if (
                not topic
                or topic in soft_source_floor_blocked_topics
                or _canonical_family_key(topic) in soft_source_floor_blocked_keys
                or _source_literature_family_blocked_topic(
                    topic,
                    blocked_topics - soft_source_floor_blocked_topics,
                )
                or _local_parent_refresh_blocked(
                    runs_root, profile_slug, topic, discovery_mtime,
                )
            ):
                continue
            topic_key = _canonical_family_key(topic).removeprefix("topic:")
            topic_tokens = {
                token.rstrip("s") for token in topic_key.split("_")
                if len(token.rstrip("s")) >= 3
            }
            if "anti" in topic_tokens and seed_scope and not ((topic_tokens - {"anti"}) & seed_scope):
                continue
            if topic_tokens and not (topic_tokens - _DISCOVERY_PARENT_GENERIC_TOKENS):
                continue
            title_tokens = {
                token.rstrip("s")
                for token in _CLAIM_WORD.findall(str(row.get("top_paper_title") or "").lower())
                if len(token.rstrip("s")) >= 3
            }
            domain_tokens = {"aging", "ageing", "longevity", "lifespan", "healthspan"}
            if receipts and title_tokens and seed_scope and not (
                _topic_in_seed_scope(topic_key, aliases, seed_scope)
                or (topic_tokens | title_tokens) & domain_tokens
            ):
                continue
            if any(
                topic_key.startswith(f"{seed}_")
                and all(
                    token in _DISCOVERY_GENERIC_SUFFIX_TOKENS
                    for token in topic_key[len(seed) + 1:].split("_")
                )
                for seed in seed_prefixes
            ):
                continue
            if (
                _topic_in_seed_scope(topic_key, aliases, other_seed_scope)
                and not _topic_in_seed_scope(topic_key, aliases, seed_scope)
            ):
                continue
            with suppress(TypeError, ValueError):
                fact_sources = int(row.get("fact_source_count") or 0)
                papers = int(row.get("paper_count") or 0)
                if max(fact_sources, papers) < min_sources:
                    continue
                token_count = len(_CLAIM_WORD.findall(topic.replace("_", " ")))
                source_rank = -max(fact_sources, papers)
                if receipt_rank == 0:
                    score = (
                        receipt_rank, recency, source_rank, -papers,
                        -fact_sources, token_count, topic,
                    )
                else:
                    score = (
                        receipt_rank, source_rank, -papers, -fact_sources,
                        token_count, recency, topic,
                    )
                candidates.append((score, topic, aliases))
    topics: list[str] = []
    seen: set[str] = set()
    seen_families: set[str] = set()
    for _score, topic, aliases in sorted(candidates):
        if topic in seen or bool(aliases & seen_families):
            continue
        topics.append(topic)
        seen.add(topic)
        seen_families.update(aliases)
        if len(topics) >= limit:
            break
    return topics


def _local_parent_refresh_blocked(
    runs_root: Path, profile_slug: str, topic: str, discovery_mtime: float,
) -> bool:
    paths = sorted(
        runs_root.glob(f"{cap_topic_slug(topic)}-evidence-*/publish_verdict.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    if not paths:
        return False
    verdict_path = paths[0]
    with suppress(OSError):
        if verdict_path.stat().st_mtime < discovery_mtime:
            return False
    verdict = _json(verdict_path, {})
    if not isinstance(verdict, dict):
        return False
    run_domain = _run_domain(verdict_path.parent, verdict)
    if run_domain and not _same_domain(run_domain, profile_slug):
        return False
    queue_row = _queue_ready_row(verdict, runs_root)
    blockers = {str(item) for item in queue_row.get("blockers") or []}
    return (
        str(queue_row.get("decision") or "") == "curation_needed"
        and bool(blockers & _LOCAL_PARENT_REFRESH_BLOCKERS)
    )


def _source_literature_payload(
    *, profile_slug: str, topic: str, papers: list[Json], runs_root: Path, date: str,
    reviewer_notes: str = "",
    parent_submission_id: str = "",
) -> tuple[Json, Json]:
    return publish_literature.payload(
        profile_slug=profile_slug,
        topic=topic,
        papers=papers,
        runs_root=runs_root,
        date=date,
        source_bundle=_source_bundle,
        evidence_type=_evidence_type,
        year_value=_year,
        write_json=_write_json,
        safe_excerpt=_safe_excerpt,
        submission_agent_id=_submission_agent_id,
        reviewer_notes=reviewer_notes,
        parent_submission_id=parent_submission_id,
        strict_topic_coverage=publish_literature._non_biomedical(profile_slug),
    )


def _source_literature_payload_bundle_blocker(payload: Json, min_sources: int) -> str:
    bundle = payload.get("source_bundle")
    sources = (
        [source for source in bundle if isinstance(source, dict)]
        if isinstance(bundle, list) else []
    )
    if len(sources) < min_sources:
        return "source_bundle_below_min"
    if publish_literature.substantive_fact_count(sources) < min_sources:
        return "source_bundle_fact_floor_below_min"
    if (
        publish_literature.source_identity_count(sources, require_substantive=True)
        < min_sources
    ):
        return "source_bundle_fact_diversity_below_min"
    if publish_literature.source_outlet_diversity_below_min(sources, min_sources):
        return "source_bundle_outlet_diversity_below_min"
    return ""


_PUBLISH_RENDER_POLL_ATTEMPTS = publish_public.PUBLISH_RENDER_POLL_ATTEMPTS
_PUBLISH_RENDER_POLL_DELAY_S = publish_public.PUBLISH_RENDER_POLL_DELAY_S


def sync_submission_decisions(
    runs_root: Path = _RUNS,
    *,
    fetcher: DecisionFetcher = publish_decisions.decision_fetch,
    page_fetcher: PageFetcher = publish_public.fetch_public_page,
    now: dt.datetime | None = None,
    max_pending_age_hours: float = _DEFAULT_PENDING_DECISION_MAX_AGE_HOURS,
) -> Json:
    ledger_dir = runs_root / "_daily_ledger"
    with publish_io.lock_path(ledger_dir / "_sync_submission_decisions"):
        return _sync_submission_decisions_unlocked(
            runs_root,
            fetcher=fetcher,
            page_fetcher=page_fetcher,
            now=now,
            max_pending_age_hours=max_pending_age_hours,
        )


def _sync_submission_decisions_unlocked(
    runs_root: Path = _RUNS,
    *,
    fetcher: DecisionFetcher = publish_decisions.decision_fetch,
    page_fetcher: PageFetcher = publish_public.fetch_public_page,
    now: dt.datetime | None = None,
    max_pending_age_hours: float = _DEFAULT_PENDING_DECISION_MAX_AGE_HOURS,
) -> Json:
    ledger_dir = runs_root / "_daily_ledger"
    current = now or dt.datetime.now(dt.UTC)
    summary: Json = {
        "checked": 0, "updated": 0, "published": 0, _DECISION_PENDING: 0,
        "stale": 0, "errors": [],
    }
    seen_submission_ids: set[str] = set()
    submission_record_updates: dict[str, Json] = {}
    backfill_submission_records: list[Json] = []
    for path in sorted(ledger_dir.glob("*.json")):
        ledger = _json(path, {})
        if isinstance(ledger, dict):
            promoted_terminal_resubmit = _promote_terminal_resubmit_ledger(ledger)
            sid = _ledger_submission_id(ledger)
            if sid:
                seen_submission_ids.add(sid)
                patch = _submission_record_patch(ledger)
                if patch:
                    submission_record_updates[sid] = patch
            backfill_submission_records.extend(
                _terminal_resubmit_queued_submission_records(ledger),
            )
            if promoted_terminal_resubmit:
                summary["updated"] += 1
        if not isinstance(ledger, dict):
            continue
        if ledger.get("status") == publish_status.CycleStatus.PUBLISHED.value:
            summary["checked"] += 1
            page = publish_public.public_page_check(
                {"public_url": ledger.get("public_url")},
                page_fetcher=page_fetcher,
            )
            ledger["public_page_check"] = page
            if not page.get("ok"):
                ledger["status"] = publish_status.CycleStatus.PUBLIC_PAGE_NOT_RENDERED.value
                ledger["published"] = 0
                ledger["publish_failure_reason"] = "public_page_not_rendered"
                summary["updated"] += 1
                _write_ledger(path, ledger)
            continue
        if (
            ledger.get("status")
            == publish_status.CycleStatus.PUBLIC_PAGE_NOT_RENDERED.value
            and ledger.get("public_url")
        ):
            # Recover the inverse of the demotion above: a memo Researka
            # accepted whose page was not yet built at submit time. Re-check it;
            # once the page renders, promote to published instead of leaving it
            # permanently stuck (the repair path would only resubmit it and get
            # duplicate-blocked).
            summary["checked"] += 1
            page = publish_public.public_page_check(
                {"public_url": ledger.get("public_url")},
                page_fetcher=page_fetcher,
            )
            ledger["public_page_check"] = page
            if page.get("ok"):
                ledger["status"] = publish_status.CycleStatus.PUBLISHED.value
                ledger["published"] = 1
                ledger.pop("publish_failure_reason", None)
                summary["updated"] += 1
                summary["published"] += 1
                _write_ledger(path, ledger)
            continue
        if ledger.get("status") != publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value:
            continue
        if ledger.get("final_verdict") in _FINAL_DECISION_VERDICTS:
            continue
        submission_id = _ledger_submission_id(ledger)
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
        decision_status = _norm(decision.get("status") if isinstance(decision, dict) else "")
        decision_verdict = _norm(decision.get("decision") if isinstance(decision, dict) else "")
        if (
            ledger.get("pending_reason") == "terminal_resubmit_job_queued"
            and isinstance(decision, dict)
            and _source_literature_clean_terminal_resubmit(decision)
            and decision_status not in {"complete", "completed"}
            and decision_verdict not in {
                _DECISION_ACCEPTED, _DECISION_REJECTED, _DECISION_REVISE,
            }
            and not decision.get("publication")
        ):
            ledger["researka_decision"] = decision
            ledger["decision_poll"] = {
                "final_verdict": _DECISION_PENDING,
                "pending_reason": "terminal_resubmit_job_queued",
            }
            summary[_DECISION_PENDING] += 1
            summary["updated"] += 1
            _write_ledger(path, ledger)
            continue
        final = publish_decisions.apply_submission_decision(
            ledger,
            submission_id_value=submission_id,
            decision=decision,
            page_fetcher=page_fetcher,
        )
        if final != _DECISION_PENDING:
            ledger.pop("pending_reason", None)
        summary[_DECISION_PENDING] += int(final == _DECISION_PENDING)
        summary["published"] += int(final == _DECISION_ACCEPTED)
        if final == _DECISION_PENDING and _stale_pending_decision(
            ledger, stamp=path.stem, now=current,
            max_age_hours=max_pending_age_hours,
        ):
            _mark_stale_pending_decision(
                ledger, max_age_hours=max_pending_age_hours,
            )
            final = _DECISION_STALE_PENDING
            summary[_DECISION_PENDING] -= 1
            summary["stale"] += 1
        if final != _DECISION_PENDING:
            summary["updated"] += 1
        patch = _submission_record_patch(ledger)
        if patch:
            submission_record_updates[submission_id] = patch
        _write_ledger(path, ledger)
    synthetic_ledgers: list[tuple[Path, Json]] = []

    def update_submitted_records(submitted: list[Any]) -> bool:
        submitted_changed = False
        submitted_ids = {
            str(row.get("submission_id") or "").strip()
            for row in submitted
            if isinstance(row, dict)
        }
        for record in backfill_submission_records:
            submission_id = str(record.get("submission_id") or "").strip()
            if not submission_id or submission_id in submitted_ids:
                continue
            submitted.append(record)
            submitted_ids.add(submission_id)
            submitted_changed = True
        for row in list(submitted):
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
                "domain": row.get("domain"),
                "domain_slug": row.get("domain_slug"),
                "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                "submitted": 1,
                "published": 0,
                "submitted_topic": row.get("topic"),
                "submission_id": submission_id,
                "candidate": {
                    "domain": row.get("domain"),
                    "domain_slug": row.get("domain_slug"),
                    "topic": row.get("topic"),
                    "run_dir": row.get("run_dir"),
                    "fingerprint": row.get("fingerprint"),
                },
            }
            final = publish_decisions.apply_submission_decision(
                synthetic_ledger,
                submission_id_value=submission_id,
                decision=decision,
                page_fetcher=page_fetcher,
            )
            summary[_DECISION_PENDING] += int(final == _DECISION_PENDING)
            summary["published"] += int(final == _DECISION_ACCEPTED)
            if final == _DECISION_PENDING and _stale_pending_decision(
                synthetic_ledger, stamp=row.get("date"), now=current,
                max_age_hours=max_pending_age_hours,
            ):
                _mark_stale_pending_decision(
                    synthetic_ledger, max_age_hours=max_pending_age_hours,
                )
                final = _DECISION_STALE_PENDING
                summary[_DECISION_PENDING] -= 1
                summary["stale"] += 1
            if final != _DECISION_PENDING:
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


_CYCLE_SUMMARY_RE = re.compile(r"runs/_curator_cycles/([^\s]+\.json)")


def _cycle_topics_from_payload(
    cycle: Path, payload: Json, *, domain: str | None = None,
) -> Json:
    cycle_domain = domain_slug(payload.get("domain")) or domain_slug(
        payload.get("domain_slug")
    )
    if domain and cycle_domain and not _same_domain(cycle_domain, domain):
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
    skipped_excluded = [
        str(t) for t in payload.get("skipped_excluded") or [] if str(t)
    ]
    probe = payload.get("fullraw_seed_probe")
    fullraw_events = (
        [e for e in probe.get("events") or [] if isinstance(e, dict)]
        if isinstance(probe, dict) else []
    )
    return {
        "cycle": cycle.name,
        "ran_topics": ran,
        "skipped_in_cooldown": skipped,
        "skipped_excluded": skipped_excluded,
        "skipped_below_source_floor": skipped_source_floor,
        "fullraw_probe_events": fullraw_events[:10],
    }


def _latest_cycle_topics(runs_root: Path, *, domain: str | None = None) -> Json:
    cycles = sorted(
        path for path in (runs_root / "_curator_cycles").glob("*.json")
        if "_cross_topic_" not in path.name
    )
    for cycle in reversed(cycles):
        payload = _json(cycle, {})
        if not isinstance(payload, dict):
            continue
        result = _cycle_topics_from_payload(cycle, payload, domain=domain)
        if result:
            return result
    return {}


def _cycle_topics_from_note(
    runs_root: Path, note: str, *, domain: str | None = None,
) -> Json:
    match = _CYCLE_SUMMARY_RE.search(note)
    if not match:
        return {}
    cycle = runs_root / "_curator_cycles" / Path(match.group(1)).name
    payload = _json(cycle, {})
    if not isinstance(payload, dict):
        return {}
    return _cycle_topics_from_payload(cycle, payload, domain=domain)


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
    warm_probe_topics = min(
        _DEFAULT_WARM_BACKLOG_DERIVED_TOPIC_LIMIT,
        _submit_warm_backlog_probe_topics(refresh_top),
    )
    priorities = [str(topic).strip() for topic in priority_topics if str(topic).strip()]
    effective_top = min(
        len(priorities),
        1,
    ) if priorities else refresh_top
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
            str(warm_probe_topics),
            "--fact-probe-topics",
            str(warm_probe_topics),
        ])
    for topic in priorities:
        args.extend(["--priority-topic", topic])
    for topic in exclusions:
        args.extend(["--exclude-topic", topic])
    priority_key = "TOPIC_DISCOVERY_FULLRAW_PRIORITY"
    old_priority = os.environ.get(priority_key)
    old_fullraw_bounds = {
        key: os.environ.get(key) for key in _ALPHA_REFRESH_FULLRAW_DEFAULTS
    }
    os.environ[priority_key] = "1"
    for key, value in _ALPHA_REFRESH_FULLRAW_DEFAULTS.items():
        os.environ.setdefault(key, value)
    try:
        ok, note = _run_step(args, timeout=_REFRESH_TIMEOUT_SECONDS)
    finally:
        if old_priority is None:
            os.environ.pop(priority_key, None)
        else:
            os.environ[priority_key] = old_priority
        for key, old_value in old_fullraw_bounds.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
    result = {
        "ok": ok,
        "note": note,
        "top": effective_top,
        "cooldown_hours": cooldown_hours,
        "excluded_topics": exclusions,
        "priority_topics": priorities,
        "warm_backlog": warm_backlog,
    } | _cycle_topics_from_note(runs_root, note, domain=domain)
    if priorities:
        ran_raw = result.get("ran_topics")
        ran = ran_raw if isinstance(ran_raw, list) else []
        attempted = priorities[:effective_top]
        result["attempted_priority_topics"] = attempted
        if ran:
            result["ran_topics"] = list(dict.fromkeys(str(t) for t in ran if str(t)))
    return result


def _child_topics_from_queue(
    queue: Json, excluded_topics: set[str], *, limit: int, domain: str | None = None,
) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, str], str]] = []
    seen = set(excluded_topics)
    seed_prefixes = _domain_seed_prefixes(domain)
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
            if _family_blocked_topic(parent, seen):
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
                if _family_blocked_topic(child, seen):
                    continue
                child_key = _canonical_family_key(child).removeprefix("topic:")
                if seed_prefixes and not any(
                    child_key == seed or child_key.startswith(f"{seed}_")
                    for seed in seed_prefixes
                ):
                    continue
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


def _prefer_fresh_parent_refresh(considered: list[Json]) -> bool:
    statuses = {
        str(row.get("status") or "")
        for row in considered
        if isinstance(row, dict) and str(row.get("status") or "")
    }
    blockers = statuses - _AGENT_REPAIR_DECISIONS
    if not blockers or blockers & _REFRESHABLE_SOURCE_FLOOR_STATUSES:
        return False
    return blockers <= _PARENT_REFRESH_BEFORE_CHILD_STATUSES


def _cluster_has_repair_receipts(cluster: Json) -> bool:
    values = cluster.get("member_fact_ids") if isinstance(cluster, dict) else []
    if not isinstance(values, list):
        return False
    return len({str(value or "").strip() for value in values if str(value or "").strip()}) >= (
        _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES
    )


def _drop_markdown_section(memo: str, heading: str) -> str:
    return publish_markdown.drop_markdown_section(memo, heading)


def _plain_section(memo: str, heading: str) -> str:
    return publish_markdown.plain_section(memo, heading)


def _safe_excerpt(text: str, limit: int = 1200) -> str:
    return publish_markdown.safe_excerpt(text, limit=limit)


def _public_submission_markdown(memo: str) -> str:
    return publish_markdown.public_submission_markdown(memo)


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
    return publish_markdown.raw_section(memo, heading)


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
        if _is_evidence_map_row(verdict)
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
    repair_decision = verdict.get("_repair_decision")
    parent = (
        _resubmission_parent_submission_id(repair_decision)
        if isinstance(repair_decision, dict) else ""
    )
    if parent:
        payload["parent_submission_id"] = parent
        payload["parent_object_id"] = parent
        payload["metadata"]["revision_of_object_id"] = parent
        payload["metadata"].setdefault("revision_of", parent)
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
    return http_submitter(url, token)


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
    source_literature_forced_papers: dict[str, list[Json]] | None = None,
    source_literature_priority_topics: list[str] | None = None,
    fetcher: Fetcher = _crossref_fetch,
    decision_fetcher: DecisionFetcher = publish_decisions.decision_fetch,
    page_fetcher: PageFetcher = publish_public.fetch_public_page,
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
        "domain_slug": profile.slug,
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
        "status": publish_status.CycleStatus.STARTED.value,
    }
    _write_ledger(ledger_path, ledger)
    if estimated_cost_usd > max_cost_usd:
        ledger.update({
            "status": publish_status.CycleStatus.COST_CAP_EXCEEDED.value,
            "reason": "estimated_cost_above_cap",
        })
        _write_ledger(ledger_path, ledger)
        return ledger
    if submit and profile.dry_run_only:
        ledger.update({
            "status": publish_status.CycleStatus.DOMAIN_DRY_RUN_ONLY.value,
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
    source_floor_blocked_topics = _recent_source_floor_topics(
        submitted_path.parent, days=min(published_topic_cooldown_days, 2),
        domain=profile.slug,
    )
    source_literature_source_floor_blocked_topics = _recent_source_floor_topics(
        submitted_path.parent, days=min(published_topic_cooldown_days, 2),
        domain=profile.slug, source_literature_only=True,
    )
    source_literature_source_floor_revalidated_topics = {
        topic for topic in source_literature_source_floor_blocked_topics
        if _source_literature_candidate_papers(
            runs_root, profile.slug, topic, min_submit_sources,
            min_submit_sources * 3,
            allow_live_fetch=False,
        )
    }
    if source_literature_source_floor_revalidated_topics:
        source_literature_source_floor_blocked_topics -= (
            source_literature_source_floor_revalidated_topics
        )
        source_floor_blocked_topics -= source_literature_source_floor_revalidated_topics
    pending_source_literature_topics = _pending_source_literature_topics(
        submitted_path.parent, profile.slug,
    )
    blocked_topics = (
        published_blocked_topics
        | submitted_blocked_topics
        | negative_blocked_topics
        | source_floor_blocked_topics
    )
    source_literature_blocked_topics = (
        published_blocked_topics
        | submitted_blocked_topics
        | negative_blocked_topics
        | source_literature_source_floor_blocked_topics
        | pending_source_literature_topics
    )
    source_literature_soft_blocked_topics = negative_blocked_topics
    ledger["recently_published_topics_blocked"] = sorted(published_blocked_topics)
    ledger["recently_submitted_topics_blocked"] = sorted(submitted_blocked_topics)
    ledger["recent_negative_topics_blocked"] = sorted(negative_blocked_topics)
    ledger["recent_source_floor_topics_blocked"] = sorted(source_floor_blocked_topics)
    ledger["source_literature_source_floor_revalidated_topics"] = sorted(
        source_literature_source_floor_revalidated_topics,
    )
    ledger["pending_source_literature_topics_blocked"] = sorted(
        pending_source_literature_topics,
    )
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
                "status": publish_status.CycleStatus.SUBMIT_NOT_CONFIGURED.value,
                "reason": "missing_submit_token",
                "accepted_env_vars": list(_SUBMIT_TOKEN_ENVS),
            })
            _write_ledger(ledger_path, ledger)
            return ledger
        ledger["submit_token_env"] = token_env
        submitter = _http_submitter(url, token)

    def build_current_queue() -> Json:
        if queue_builder is _build_queue:
            return _build_queue(
                runs_root, include_archive,
                domain=profile.slug, submitted_path=submitted_path,
            )
        return queue_builder(runs_root, include_archive)

    def build_initial_probe_queue() -> Json:
        if queue_builder is _build_queue:
            cached = _cached_domain_queue(runs_root, profile.slug, submitted_path)
            if cached is not None:
                ledger["initial_queue_probe_source"] = "cached_domain_queue"
                _write_ledger(ledger_path, ledger)
                return cached
        ledger["initial_queue_probe_source"] = "build_queue"
        return build_current_queue()

    prev_queue_sig: frozenset[str] = frozenset()
    preflight_queue = None
    initial_probe_empty = False
    skip_refresh_note = "skipped_after_repairable_submission"
    source_lit_preflight_papers: dict[str, list[Json]] = {}
    source_lit_preflight_selected: list[str] = []
    if refresh_candidates and queue is None and queue_builder is _build_queue:
        ledger["stage"] = "initial_queue_probe"
        ledger["next_action"] = "building_current_publish_queue"
        _write_ledger(ledger_path, ledger)
        candidate_queue = build_initial_probe_queue()
        if ledger.get("initial_queue_probe_source") != "cached_domain_queue":
            candidate_queue = _with_repairable_candidates(
                candidate_queue, runs_root, profile.slug,
            )
        source_lit_available = False
        source_lit_probe_attempts: list[Json] = []
        if submit:
            source_lit_probe = source_paper_fetcher or (
                lambda topic, limit: (
                    _source_literature_preflight_candidate_papers(
                        runs_root, profile.slug, topic, min_submit_sources, limit,
                    )
                )
            )
            cached_initial_probe = (
                ledger.get("initial_queue_probe_source") == "cached_domain_queue"
            )
            if cached_initial_probe:
                ledger["initial_source_lit_repair_scan"] = "skipped_cached_domain_queue"
            source_lit_probe_topics = [] if cached_initial_probe else list(
                _priority_source_literature_repair_decisions(
                    runs_root, profile.slug, limit=1,
                ),
            )
            for topic in _source_literature_topic_candidates(
                runs_root, profile.slug, min_submit_sources,
                source_literature_blocked_topics,
                limit=1,
                soft_broad_blocked_topics=source_literature_soft_blocked_topics,
            ):
                if topic not in source_lit_probe_topics:
                    source_lit_probe_topics.append(topic)
            if not cached_initial_probe:
                for topic in _repairable_source_literature_decisions(
                    runs_root, profile.slug, limit=1,
                ):
                    if topic not in source_lit_probe_topics:
                        source_lit_probe_topics.append(topic)
            for topic in source_lit_probe_topics:
                attempt_status = "blocked"
                papers = source_lit_probe(topic, min_submit_sources * 3)
                source_lit_available, _reason = _source_literature_boundary_quality(
                    topic, papers, min_submit_sources, profile.slug,
                    require_substantive_sources=True,
                )
                if source_lit_available:
                    source_lit_preflight_papers[topic] = papers
                    source_lit_preflight_selected.append(topic)
                    attempt_status = "selected"
                source_lit_probe_attempts.append({
                    "topic": topic,
                    "status": attempt_status,
                    "reason": _reason,
                    "paper_count": len(papers),
                    "relevant_paper_count": len(publish_literature.relevant_papers(topic, papers)),
                })
                ledger["source_literature_preflight_attempts"] = source_lit_probe_attempts
                _write_ledger(ledger_path, ledger)
                if source_lit_available:
                    break
        if source_lit_probe_attempts:
            ledger["source_literature_preflight_attempts"] = source_lit_probe_attempts
        ledger["stage"] = "initial_queue_probe_complete"
        ledger["preflight_queue_counts"] = publish_status.queue_counts(candidate_queue)
        _write_ledger(ledger_path, ledger)
        preflight_candidate, preflight_considered = select_candidate(
            candidate_queue,
            runs_root=runs_root,
            submitted_path=submitted_path,
            allow_tier2=allow_tier2,
            min_source_count=min_submit_sources,
            min_direct_source_count=min_direct_submit_sources,
            blocked_fingerprints=blocked_fingerprints,
            blocked_topics=blocked_topics,
            accepted_shape_profiles=accepted_shape_profiles,
            retryable_fingerprints=session_retryable,
            retry_decision_overrides=session_retry_decisions,
            domain=profile.slug,
        )
        preflight_counts: dict[str, int] = {}
        for row in preflight_considered:
            if isinstance(row, dict):
                status = str(row.get("status") or "unknown")
                preflight_counts[status] = preflight_counts.get(status, 0) + 1
        ledger["preflight_considered_counts"] = preflight_counts
        cluster_rows = _rows(candidate_queue, allow_tier2=True) + [
            r for r in candidate_queue.get("curation_needed") or [] if isinstance(r, dict)
        ]
        seen_preflight = _seen_submission_fingerprints_for_domain(
            submitted_path, profile.slug,
        )
        cluster_available = any(
            memo_fingerprint(candidate) not in blocked_fingerprints
            and memo_fingerprint(candidate) not in seen_preflight
            and not any(
                _family_blocked_topic(value, blocked_topics)
                for value in [
                    *_family_values(candidate),
                    str(candidate.get("_parent_topic") or ""),
                ]
            )
            for candidate in _claim_cluster_candidates(
                cluster_rows, runs_root,
                min_direct_source_count=min_direct_submit_sources,
            )
        )
        if preflight_candidate is not None or cluster_available:
            preflight_queue = candidate_queue
            skip_refresh_note = "skipped_initial_queue_probe"
        elif source_lit_available:
            preflight_queue = candidate_queue
            skip_refresh_note = "skipped_source_literature_candidate_available"
        else:
            initial_probe_empty = True
    skip_next_refresh = preflight_queue is not None
    warm_backlog_next = False
    priority_refresh_topics: list[str] = []
    if (
        refresh_candidates
        and initial_probe_empty
    ):
        priority_refresh_topics = _fresh_parent_topics_from_discovery(
            runs_root,
            profile.slug,
            blocked_topics,
            limit=_parent_refresh_topic_limit(refresh_top),
            min_sources=max(min_submit_sources, min_direct_submit_sources),
            soft_source_floor_blocked_topics=source_floor_blocked_topics,
        )
        if priority_refresh_topics:
            ledger["refresh_parent_topics"] = priority_refresh_topics
    for batch in range(1, batch_limit + 1):
        _sync_failed_attempt_blocks(ledger, blocked_fingerprints, blocked_topics)
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
            ledger["stage"] = "refresh_batch_running"
            ledger["refresh_candidates"] = {
                "status": "running",
                "batch": batch,
                "top": refresh_top,
                "cooldown_hours": cooldown,
                "priority_topics": priority_refresh_topics,
                "excluded_topics": sorted(blocked_topics),
                "warm_backlog": warm_backlog_next,
            }
            _write_ledger(ledger_path, ledger)
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
                            refresh.get("ran_topics")
                            or refresh.get("attempted_priority_topics")
                            or refresh.get("priority_topics") or []
                        ) if str(t)
                    ]
                    blocked_topics.update(timed_out_topics)
                    next_parent_topics = _fresh_parent_topics_from_discovery(
                        runs_root,
                        profile.slug,
                        blocked_topics,
                        limit=_parent_refresh_topic_limit(refresh_top),
                        min_sources=max(min_submit_sources, min_direct_submit_sources),
                        soft_source_floor_blocked_topics=source_floor_blocked_topics,
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
                ledger["refresh_early_exit"] = {
                    "batch": batch,
                    "reason": "refresh_failed_before_source_literature",
                    "note": str(refresh.get("note") or "")[:240],
                }
                ledger.update({
                    "status": publish_status.CycleStatus.CANDIDATE_REFRESH_FAILED.value,
                })
                _write_ledger(ledger_path, ledger)
                break
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
        raw_ready_count = len(current_queue.get("ready_to_publish") or [])
        actionable_ready_count = (
            1 if candidate is not None and candidate.get("decision") == "ready_to_publish"
            else 0
        )
        ledger["actionable_ready_to_publish"] = actionable_ready_count
        ledger["non_actionable_ready_to_publish"] = max(
            0, raw_ready_count - actionable_ready_count,
        )
        for row in considered:
            if refresh_candidates:
                row["batch"] = batch
            if row.get("status") in _REFRESHABLE_SOURCE_FLOOR_STATUSES:
                topic = str(row.get("topic") or "")
                if topic:
                    blocked_topics.add(topic)
                    ledger.setdefault("source_floor_refresh_topics", [])
                    if topic not in ledger["source_floor_refresh_topics"]:
                        ledger["source_floor_refresh_topics"].append(topic)
                continue
            status = str(row.get("status") or "")
            if status in _EXHAUSTED_STATUSES or status in _BATCH_TOPIC_BLOCK_STATUSES:
                fingerprint = str(row.get("fingerprint") or "")
                topic = str(row.get("topic") or "")
                if fingerprint and status in _FINGERPRINT_EXHAUSTED_STATUSES:
                    blocked_fingerprints.add(fingerprint)
                if topic and status in _BATCH_TOPIC_BLOCK_STATUSES:
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
            if refresh.get("note") == "skipped_source_literature_candidate_available":
                ledger["refresh_early_exit"] = {
                    "batch": batch,
                    "reason": "source_literature_candidate_available",
                }
                break
            ran_topics = [str(t) for t in refresh.get("ran_topics") or [] if str(t)]
            if ran_topics:
                blocked_topics.update(ran_topics)
            source_floor_topics = [
                str(t) for t in refresh.get("skipped_below_source_floor") or [] if str(t)
            ]
            if source_floor_topics:
                blocked_topics.update(source_floor_topics)
            skipped_excluded = [
                str(t) for t in refresh.get("skipped_excluded") or [] if str(t)
            ]
            if skipped_excluded:
                blocked_topics.update(skipped_excluded)
            fresh_parent_topics: list[str] = []
            if (
                refresh_candidates
                and batch < search_batch_limit
                and _prefer_fresh_parent_refresh(considered)
            ):
                fresh_parent_topics = _fresh_parent_topics_from_discovery(
                    runs_root,
                    profile.slug,
                    blocked_topics,
                    limit=_parent_refresh_topic_limit(refresh_top),
                    min_sources=max(min_submit_sources, min_direct_submit_sources),
                    soft_source_floor_blocked_topics=source_floor_blocked_topics,
                )
                if fresh_parent_topics:
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
            if refresh_candidates and batch < search_batch_limit and not fresh_parent_topics:
                fresh_parent_topics = _fresh_parent_topics_from_discovery(
                    runs_root,
                    profile.slug,
                    blocked_topics,
                    limit=_parent_refresh_topic_limit(refresh_top),
                    min_sources=max(min_submit_sources, min_direct_submit_sources),
                    soft_source_floor_blocked_topics=source_floor_blocked_topics,
                )
            if refresh_candidates and fresh_parent_topics and batch < search_batch_limit:
                ledger["refresh_parent_topics"] = fresh_parent_topics
                priority_refresh_topics = fresh_parent_topics
                force_refresh = True
                continue
            if (
                refresh_candidates
                and _source_literature_topic_candidates(
                    runs_root,
                    profile.slug,
                    min_submit_sources,
                    source_literature_blocked_topics,
                    limit=1,
                    soft_broad_blocked_topics=source_literature_soft_blocked_topics,
                )
            ):
                ledger["refresh_early_exit"] = {
                    "batch": batch,
                    "reason": "source_literature_candidate_available_after_refresh",
                }
                break
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
            attempt["status"] = publish_status.CycleStatus.HELD_RETRACTION_CHECK.value
            for row in reversed(all_considered):
                if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                    row["pre_attempt_status"] = row.get("status")
                    row["status"] = publish_status.CandidateStatus.HELD_RETRACTION_CHECK.value
                    break
            ledger["cycle_attempts"].append(attempt)
            blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
            _write_json(
                runs_root / "_retracted_holds" / f"{candidate.get('topic')}-{date}.json",
                ledger,
            )
            if not refresh_candidates or batch >= search_batch_limit:
                ledger.update({
                    "status": publish_status.CycleStatus.HELD_RETRACTION_CHECK.value,
                    "candidate": candidate.get("topic"),
                })
                _write_ledger(ledger_path, ledger)
                return ledger
            continue
        if not submit:
            ledger["cycle_attempts"].append(
                attempt | {"status": publish_status.CycleStatus.DRY_RUN_SELECTED.value},
            )
            ledger.update({"status": publish_status.CycleStatus.DRY_RUN_SELECTED.value})
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
                    if hold.get("duplicate_source_evidence"):
                        row["duplicate_source_evidence"] = hold["duplicate_source_evidence"]
                    break
            ledger["cycle_attempts"].append(attempt)
            for fingerprint in {selected_fingerprint, current_fingerprint}:
                if fingerprint:
                    blocked_fingerprints.add(fingerprint)
            if not refresh_candidates or batch >= search_batch_limit:
                ledger.update({
                    "status": publish_status.CycleStatus.NO_FRESH_CANDIDATE.value,
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
            attempt["status"] = publish_status.CycleStatus.PREFLIGHT_QA_BLOCKED.value
            ledger["cycle_attempts"].append(attempt)
            ledger.update({
                "status": publish_status.CycleStatus.PREFLIGHT_QA_BLOCKED.value,
                "submitted": 0,
                "published": 0,
            })
            _write_ledger(ledger_path, ledger)
            return ledger
        result = submit_with_backoff(checked_payload, submitter)
        attempt["submission"] = result
        ledger["submission"] = result
        if result["status"] == _DECISION_ACCEPTED:
            submission_id = publish_decisions.submission_id(result)
            _record_submission_attempt(
                submitted_path,
                date=date,
                candidate=candidate,
                runs_root=runs_root,
                submission_id=submission_id,
            )
            ledger.update({
                "final_verdict": _DECISION_PENDING,
                "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                "submitted": 1,
                "submitted_topic": candidate.get("topic"),
                "submission_id": submission_id,
            })
            _write_ledger(ledger_path, ledger)
            if submission_id:
                final = publish_decisions.poll_submission_decision(
                    ledger,
                    submission_id_value=submission_id,
                    fetcher=decision_fetcher,
                    page_fetcher=page_fetcher,
                    attempts=decision_poll_attempts
                    if default_submitter or decision_fetcher is not publish_decisions.decision_fetch
                    else 0,
                    sleep_seconds=decision_poll_seconds,
                    sleep=sleep,
                )
                decision = ledger.get("researka_decision", {})
                if isinstance(decision, dict):
                    if final == _DECISION_ACCEPTED:
                        attempt["public_page_check"] = ledger.get("public_page_check")
                        ledger["cycle_attempts"].append(
                            attempt | {"status": publish_status.CycleStatus.PUBLISHED.value},
                        )
                        _write_ledger(ledger_path, ledger)
                        return ledger
                    if final in {_DECISION_REJECTED, _DECISION_REVISE}:
                        attempt["status"] = (
                            str(ledger.get("publish_failure_reason") or "")
                            or (
                                publish_status.CycleStatus.REVIEWER_REVISE.value
                                if final == _DECISION_REVISE else
                                publish_status.CycleStatus.REVIEWER_REJECTED.value
                            )
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
                            final == _DECISION_REVISE
                            and _repairable_rejection(decision)
                            and refresh_candidates
                            and batch < batch_limit
                            and memo_refresher is not None
                            and "repair_retry_immediate" not in ledger
                        ):
                            repair_decision = _decision_with_resubmission_parent(
                                decision, submission_id, override_existing=True,
                            )
                            retry_keys = {
                                str(candidate.get("memo_fingerprint") or ""),
                                str(attempt.get("fingerprint") or ""),
                            } - {""}
                            for retry_fp in retry_keys:
                                session_retryable.add(retry_fp)
                                session_retry_decisions[retry_fp] = repair_decision
                            ledger["repair_retry_immediate"] = {
                                "topic": candidate.get("topic"),
                                "reason": attempt["status"],
                                "requires": "changed_memo_sha256",
                            }
                            skip_next_refresh = True
                            skip_refresh_note = "skipped_after_immediate_repair_retry"
                            _write_ledger(ledger_path, ledger)
                            continue
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
            ledger["cycle_attempts"].append(
                attempt | {
                    "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                },
            )
            _write_ledger(ledger_path, ledger)
            return ledger
        if result["status"] == "rejected_duplicate":
            _record_submission_attempt(
                submitted_path,
                date=date,
                candidate=candidate,
                runs_root=runs_root,
                submission_id=publish_decisions.submission_id(result),
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
        and not ledger["cycle_attempts"]
    ):
        paper_fetcher = source_paper_fetcher
        source_lit_scan_limit = (
            _SOURCE_LITERATURE_SCAN_LIMIT
            if paper_fetcher is not None else
            _domain_alpha_memo_int(
                profile.slug, "source_literature_scan_limit",
                min(4, _SOURCE_LITERATURE_SCAN_LIMIT),
            )
        )
        if (
            paper_fetcher is None
            and submitted_blocked_topics
            and source_lit_scan_limit < _SOURCE_LITERATURE_SCAN_LIMIT
        ):
            source_lit_scan_limit = _SOURCE_LITERATURE_SCAN_LIMIT
            ledger["source_literature_scan_reason"] = (
                "recent_submissions_expand_candidate_window"
            )
        repair_decisions = _repairable_source_literature_decisions(
            runs_root, profile.slug,
        )
        repair_topics = list(repair_decisions)
        repair_topic_set = set(repair_topics)
        priority_repair_topics = list(_priority_source_literature_repair_decisions(
            runs_root, profile.slug,
        ))
        standard_repair_topics = [
            topic for topic in repair_topics if topic not in set(priority_repair_topics)
        ]
        forced_source_lit = source_literature_forced_papers or {}
        source_lit_published_bundle_sigs = _published_bundle_signatures(
            submitted_path, profile.slug, runs_root,
        )
        source_lit_duplicate_rejected_bundle_sigs = _hard_duplicate_bundle_signatures(
            submitted_path.parent, profile.slug, runs_root,
        )
        resumable_source_lit = _resumable_source_literature_payloads(
            runs_root, profile.slug, min_submit_sources, source_literature_blocked_topics,
            limit=source_lit_scan_limit,
        )
        fresh_topics = [
            topic for topic in _source_literature_topic_candidates(
                runs_root, profile.slug, min_submit_sources,
                source_literature_blocked_topics,
                limit=source_lit_scan_limit,
                soft_broad_blocked_topics=source_literature_soft_blocked_topics,
            ) if topic not in repair_topic_set
        ]
        blocked_parent_variant_topics = (
            [] if fresh_topics else
            _source_literature_blocked_parent_variant_topics(
                runs_root,
                profile.slug,
                min_submit_sources,
                submitted_blocked_topics
                | source_literature_source_floor_blocked_topics
                | pending_source_literature_topics,
                source_literature_blocked_topics,
                published_blocked_topics | negative_blocked_topics,
                limit=source_lit_scan_limit,
                soft_broad_blocked_topics=source_literature_soft_blocked_topics,
            )
        )
        if blocked_parent_variant_topics:
            ledger["source_literature_scan_reason"] = "blocked_parent_variant_expansion"
        forced_priority_topics = source_literature_priority_topics or []
        literature_topics: list[str] = []
        for topic in [
            *resumable_source_lit,
            *forced_source_lit,
            *forced_priority_topics,
            *priority_repair_topics,
            *source_lit_preflight_selected,
            *fresh_topics,
            *blocked_parent_variant_topics,
            *standard_repair_topics,
        ]:
            if (
                topic not in forced_source_lit
                and topic not in resumable_source_lit
                and topic not in blocked_parent_variant_topics
                and _source_literature_family_blocked_topic(
                    topic, pending_source_literature_topics,
                )
            ):
                continue
            if topic not in literature_topics:
                literature_topics.append(topic)
        if paper_fetcher is None:
            expanded_topics: list[str] = []

            def add_expanded(topic: str) -> bool:
                if topic not in expanded_topics:
                    expanded_topics.append(topic)
                return len(expanded_topics) >= source_lit_scan_limit

            for topic in literature_topics:
                if topic in forced_source_lit or topic in resumable_source_lit:
                    if add_expanded(topic):
                        break
                    continue
                if add_expanded(topic):
                    break
            if len(expanded_topics) < source_lit_scan_limit:
                for topic in literature_topics:
                    if topic in forced_source_lit or topic in resumable_source_lit:
                        continue
                    for fetch_topic in _source_literature_fetch_topics(topic)[1:]:
                        if add_expanded(fetch_topic):
                            break
                    if len(expanded_topics) >= source_lit_scan_limit:
                        break
            literature_topics = expanded_topics
        terminal_resubmit_topics: set[str] = set()
        for idx, literature_topic in enumerate(literature_topics):
            expanded_from_topic = ""
            resumed = resumable_source_lit.get(literature_topic)
            repair_decision = (
                repair_decisions.get(literature_topic, {})
                if literature_topic in repair_topic_set else {}
            )
            terminal_resubmit_reused_payload = False
            terminal_resubmit_review_supported_override = ""
            if resumed is not None:
                papers = resumed[2]
                ok, reason = True, "ok"
            else:
                papers = []
                if (
                    _source_literature_parented_terminal_resubmit(repair_decision)
                    and literature_topic not in forced_source_lit
                    and literature_topic not in source_lit_preflight_papers
                    and paper_fetcher is None
                ):
                    papers = _previous_source_literature_payload_papers(
                        runs_root, profile.slug, literature_topic, min_submit_sources,
                        parent_submission_id=_resubmission_parent_submission_id(
                            repair_decision,
                        ),
                    )
                    terminal_resubmit_reused_payload = bool(papers)
                if not papers:
                    papers = (
                        forced_source_lit[literature_topic]
                        if literature_topic in forced_source_lit else
                        source_lit_preflight_papers[literature_topic]
                        if literature_topic in source_lit_preflight_papers else
                        paper_fetcher(literature_topic, min_submit_sources)
                        if paper_fetcher is not None else
                        _source_literature_candidate_papers(
                            runs_root, profile.slug, literature_topic, min_submit_sources,
                            min_submit_sources * 3,
                            allow_live_fetch=literature_topic not in forced_source_lit,
                        )
                    )
                ok, reason = _source_literature_boundary_quality(
                    literature_topic, papers, min_submit_sources, profile.slug,
                    require_substantive_sources=True,
                )
                if (
                    terminal_resubmit_reused_payload
                    and reason == "directional_receipt_floor_below_min"
                    and _source_literature_parented_terminal_resubmit(repair_decision)
                ):
                    terminal_resubmit_review_supported_override = reason
                    ok, reason = True, "ok"
                if (
                    not ok
                    and reason in {
                        "source_floor_below_min",
                        "requires_fact_level_source_synthesis",
                        "source_fact_diversity_below_min",
                    }
                    and idx == len(literature_topics) - 1
                    and paper_fetcher is None
                    and literature_topic not in forced_source_lit
                ):
                    for fetch_topic in _source_literature_fetch_topics(literature_topic)[1:]:
                        if fetch_topic in literature_topics:
                            continue
                        expanded_papers = _source_literature_candidate_papers(
                            runs_root, profile.slug, fetch_topic, min_submit_sources,
                            min_submit_sources * 3,
                        )
                        expanded_ok, expanded_reason = _source_literature_boundary_quality(
                            fetch_topic, expanded_papers, min_submit_sources, profile.slug,
                            require_substantive_sources=True,
                        )
                        if expanded_ok:
                            expanded_from_topic = literature_topic
                            literature_topic = fetch_topic
                            papers = expanded_papers
                            ok, reason = expanded_ok, expanded_reason
                            break
            selected_for_attempt = publish_literature.select_boundary_papers(
                literature_topic,
                papers,
                min_submit_sources,
                strict_topic_coverage=publish_literature._non_biomedical(profile.slug),
                profile_slug=profile.slug,
            )
            evidence_roles = [
                publish_literature._paper_evidence_role(paper, literature_topic, profile.slug)
                for paper in selected_for_attempt
            ]
            relevant_paper_count = len(
                publish_literature.relevant_papers(literature_topic, papers),
            )
            fallback_attempt: Json = {
                "topic": literature_topic,
                "status": "selected" if ok else "blocked",
                "reason": reason,
                "paper_count": len(papers),
                "relevant_paper_count": relevant_paper_count,
            }
            fallback_attempt.update({
                "selected_source_count": len(selected_for_attempt),
                "selected_source_fact_count": publish_literature.substantive_fact_count(
                    selected_for_attempt,
                ),
                "selected_source_identity_count": publish_literature.source_identity_count(
                    selected_for_attempt,
                    require_substantive=True,
                ),
                "selected_source_evidence_roles": evidence_roles,
                "selected_directional_receipt_count": sum(
                    1 for role in evidence_roles
                    if role in {
                        "directional association",
                        "directional estimate",
                        "directionally favorable",
                    }
                ),
            })
            if expanded_from_topic:
                fallback_attempt["expanded_from_topic"] = expanded_from_topic
            if resumed is not None:
                fallback_attempt["resumed_payload"] = True
            if terminal_resubmit_reused_payload:
                fallback_attempt["terminal_resubmit_reused_payload"] = True
                fallback_attempt["parent_submission_id"] = (
                    _resubmission_parent_submission_id(repair_decision)
                )
                if terminal_resubmit_review_supported_override:
                    fallback_attempt["terminal_resubmit_review_supported_override"] = (
                        terminal_resubmit_review_supported_override
                    )
            if literature_topic in repair_topic_set:
                fallback_attempt["repair_submission"] = True
            ledger.setdefault("source_literature_fallback_attempts", []).append(fallback_attempt)
            ledger["source_literature_fallback"] = fallback_attempt
            _write_ledger(ledger_path, ledger)
            if ok:
                selected_papers = selected_for_attempt
                fact_backed = publish_literature.substantive_fact_count(
                    selected_papers,
                ) >= min_submit_sources
                source_diverse = publish_literature.source_identity_count(
                    selected_papers,
                    require_substantive=True,
                ) >= min_submit_sources and not (
                    publish_literature.source_outlet_diversity_below_min(
                        selected_papers,
                        min_submit_sources,
                    )
                )
                if not fact_backed:
                    fallback_attempt["status"] = "disabled"
                    fallback_attempt["reason"] = "requires_fact_level_source_synthesis"
                    continue
                if not source_diverse:
                    fallback_attempt["status"] = "disabled"
                    fallback_attempt["reason"] = "source_fact_diversity_below_min"
                    continue
                if resumed is not None:
                    candidate, payload, _resumed_papers = resumed
                else:
                    candidate, payload = _source_literature_payload(
                        profile_slug=profile.slug,
                        topic=literature_topic,
                        papers=papers,
                        runs_root=runs_root,
                        date=date,
                        reviewer_notes=_revision_notes(repair_decision),
                        parent_submission_id=_resubmission_parent_submission_id(repair_decision),
                    )
                fingerprint = str(candidate.get("memo_fingerprint") or "")
                bundle_sig = _bundle_signature(candidate, runs_root)
                if bundle_sig and bundle_sig in source_lit_duplicate_rejected_bundle_sigs:
                    fallback_attempt["status"] = "blocked"
                    fallback_attempt["reason"] = "duplicate_publication_bundle"
                    fallback_attempt["bundle_signature"] = bundle_sig
                    continue
                if bundle_sig and bundle_sig in source_lit_published_bundle_sigs:
                    fallback_attempt["status"] = "blocked"
                    fallback_attempt["reason"] = "duplicate_published_bundle"
                    fallback_attempt["bundle_signature"] = bundle_sig
                    continue
                if fingerprint and _same_memo_seen(
                    submitted_path, fingerprint, _memo_sha256(candidate, runs_root), profile.slug,
                ):
                    if _source_literature_parented_terminal_resubmit(repair_decision):
                        fallback_attempt["duplicate_resubmission_allowed"] = True
                        fallback_attempt["parent_submission_id"] = (
                            _resubmission_parent_submission_id(repair_decision)
                        )
                    else:
                        fallback_attempt["status"] = "blocked"
                        fallback_attempt["reason"] = "duplicate_submission_fingerprint"
                        fallback_attempt["fingerprint"] = fingerprint
                        continue
                payload_blocker = _source_literature_payload_bundle_blocker(
                    payload,
                    min_submit_sources,
                )
                if payload_blocker:
                    fallback_attempt["status"] = "blocked"
                    fallback_attempt["reason"] = payload_blocker
                    fallback_attempt["direct_source_count"] = len(
                        payload.get("source_bundle") or [],
                    )
                    continue
                assert submitter is not None
                result = submit_with_backoff(payload, submitter)
                fallback_attempt["submit_status"] = result["status"]
                ledger["candidate"] = {
                    "topic": literature_topic,
                    "run_dir": candidate.get("run_dir"),
                    "fingerprint": candidate.get("memo_fingerprint"),
                }
                ledger["submission"] = result
                if result["status"] == _DECISION_ACCEPTED:
                    submission_id = publish_decisions.submission_id(result)
                    _record_submission_attempt(
                        submitted_path,
                        date=date,
                        candidate=candidate,
                        runs_root=runs_root,
                        submission_id=submission_id,
                    )
                    ledger.update({
                        "final_verdict": _DECISION_PENDING,
                        "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                        "submitted": 1,
                        "submitted_topic": literature_topic,
                        "submission_id": submission_id,
                    })
                    _write_ledger(ledger_path, ledger)
                    if submission_id:
                        final = publish_decisions.poll_submission_decision(
                            ledger,
                            submission_id_value=submission_id,
                            fetcher=decision_fetcher,
                            page_fetcher=page_fetcher,
                            attempts=decision_poll_attempts,
                            sleep_seconds=decision_poll_seconds,
                            sleep=sleep,
                        )
                        if final == _DECISION_ACCEPTED:
                            ledger["cycle_attempts"].append({
                                "topic": literature_topic,
                                "run_dir": candidate.get("run_dir"),
                                "fingerprint": candidate.get("memo_fingerprint"),
                                "status": publish_status.CycleStatus.PUBLISHED.value,
                            })
                            _write_ledger(ledger_path, ledger)
                            return ledger
                        if final in {_DECISION_REJECTED, _DECISION_REVISE}:
                            researka_decision = ledger.get("researka_decision", {})
                            if (
                                bundle_sig
                                and final == _DECISION_REJECTED
                                and _hard_duplicate_decision(researka_decision)
                            ):
                                source_lit_duplicate_rejected_bundle_sigs.add(bundle_sig)
                                fallback_attempt["bundle_signature"] = bundle_sig
                            ledger["cycle_attempts"].append({
                                "topic": literature_topic,
                                "run_dir": candidate.get("run_dir"),
                                "fingerprint": candidate.get("memo_fingerprint"),
                                "status": (
                                    publish_status.CycleStatus.REVIEWER_REVISE.value
                                    if final == _DECISION_REVISE else
                                    publish_status.CycleStatus.REVIEWER_REJECTED.value
                                ),
                                "researka_decision": researka_decision,
                                "public_page_check": ledger.get("public_page_check"),
                            })
                            _write_ledger(ledger_path, ledger)
                            if (
                                final == _DECISION_REVISE
                                and isinstance(researka_decision, dict)
                                and _source_literature_clean_terminal_resubmit(
                                    researka_decision,
                                )
                                and literature_topic not in terminal_resubmit_topics
                            ):
                                repair_decision = _decision_with_resubmission_parent(
                                    researka_decision,
                                    submission_id,
                                    override_existing=True,
                                )
                                terminal_resubmit_topics.add(literature_topic)
                                fallback_attempt["terminal_resubmit_queued"] = True
                                fallback_attempt["terminal_resubmit_immediate"] = True
                                candidate, payload = _source_literature_payload(
                                    profile_slug=profile.slug,
                                    topic=literature_topic,
                                    papers=papers,
                                    runs_root=runs_root,
                                    date=date,
                                    reviewer_notes=_revision_notes(repair_decision),
                                    parent_submission_id=_resubmission_parent_submission_id(
                                        repair_decision,
                                    ),
                                )
                                payload_blocker = _source_literature_payload_bundle_blocker(
                                    payload,
                                    min_submit_sources,
                                )
                                if payload_blocker:
                                    fallback_attempt["terminal_resubmit_status"] = "blocked"
                                    fallback_attempt["terminal_resubmit_reason"] = payload_blocker
                                    fallback_attempt["terminal_resubmit_direct_source_count"] = len(
                                        payload.get("source_bundle") or [],
                                    )
                                    continue
                                result = submit_with_backoff(payload, submitter)
                                fallback_attempt["terminal_resubmit_status"] = result["status"]
                                fallback_attempt["terminal_resubmit_submission"] = result
                                ledger["terminal_resubmission"] = result
                                if result["status"] == _DECISION_ACCEPTED:
                                    parent_submission_id = _resubmission_parent_submission_id(
                                        repair_decision,
                                    )
                                    queued_job_id = _terminal_resubmit_queued_job_id(
                                        result,
                                        parent_submission_id,
                                    )
                                    submission_id = _terminal_resubmit_poll_submission_id(
                                        result,
                                        parent_submission_id,
                                    )
                                    ledger["submission"] = result
                                    _record_submission_attempt(
                                        submitted_path,
                                        date=date,
                                        candidate=candidate,
                                        runs_root=runs_root,
                                        submission_id=submission_id,
                                    )
                                    ledger.update({
                                        "final_verdict": _DECISION_PENDING,
                                        "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                                        "submitted": 1,
                                        "submitted_topic": literature_topic,
                                        "submission_id": submission_id,
                                    })
                                    _write_ledger(ledger_path, ledger)
                                    if queued_job_id:
                                        fallback_attempt["terminal_resubmit_queued_job_id"] = queued_job_id
                                    if queued_job_id and submission_id != queued_job_id:
                                        fallback_attempt["terminal_resubmit_poll_object_id"] = submission_id
                                    if queued_job_id:
                                        ledger["cycle_attempts"].append({
                                            "topic": literature_topic,
                                            "run_dir": candidate.get("run_dir"),
                                            "fingerprint": candidate.get("memo_fingerprint"),
                                            "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                                            "pending_reason": "terminal_resubmit_job_queued",
                                        })
                                        _write_ledger(ledger_path, ledger)
                                        return ledger
                                    if submission_id and submission_id == parent_submission_id:
                                        fallback_attempt["terminal_resubmit_same_parent_id"] = True
                                        ledger["cycle_attempts"].append({
                                            "topic": literature_topic,
                                            "run_dir": candidate.get("run_dir"),
                                            "fingerprint": candidate.get("memo_fingerprint"),
                                            "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                                            "pending_reason": "same_parent_terminal_resubmit_queued",
                                        })
                                        _write_ledger(ledger_path, ledger)
                                        return ledger
                                    if submission_id:
                                        final = publish_decisions.poll_submission_decision(
                                            ledger,
                                            submission_id_value=submission_id,
                                            fetcher=decision_fetcher,
                                            page_fetcher=page_fetcher,
                                            attempts=decision_poll_attempts,
                                            sleep_seconds=decision_poll_seconds,
                                            sleep=sleep,
                                        )
                                        if final == _DECISION_ACCEPTED:
                                            ledger["cycle_attempts"].append({
                                                "topic": literature_topic,
                                                "run_dir": candidate.get("run_dir"),
                                                "fingerprint": candidate.get("memo_fingerprint"),
                                                "status": publish_status.CycleStatus.PUBLISHED.value,
                                            })
                                            _write_ledger(ledger_path, ledger)
                                            return ledger
                                        if final in {_DECISION_REJECTED, _DECISION_REVISE}:
                                            researka_decision = ledger.get("researka_decision", {})
                                            if (
                                                bundle_sig
                                                and final == _DECISION_REJECTED
                                                and _hard_duplicate_decision(researka_decision)
                                            ):
                                                source_lit_duplicate_rejected_bundle_sigs.add(
                                                    bundle_sig,
                                                )
                                                fallback_attempt["bundle_signature"] = bundle_sig
                                            ledger["cycle_attempts"].append({
                                                "topic": literature_topic,
                                                "run_dir": candidate.get("run_dir"),
                                                "fingerprint": candidate.get("memo_fingerprint"),
                                                "status": (
                                                    publish_status.CycleStatus.REVIEWER_REVISE.value
                                                    if final == _DECISION_REVISE else
                                                    publish_status.CycleStatus.REVIEWER_REJECTED.value
                                                ),
                                                "researka_decision": ledger.get("researka_decision", {}),
                                                "public_page_check": ledger.get("public_page_check"),
                                            })
                                            _write_ledger(ledger_path, ledger)
                                            if idx + 1 < len(literature_topics):
                                                continue
                                            return ledger
                                    ledger["cycle_attempts"].append({
                                        "topic": literature_topic,
                                        "run_dir": candidate.get("run_dir"),
                                        "fingerprint": candidate.get("memo_fingerprint"),
                                        "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                                    })
                                    _write_ledger(ledger_path, ledger)
                                    return ledger
                                fallback_attempt["status"] = "blocked"
                                fallback_attempt["reason"] = result["status"]
                                if bundle_sig and result["status"] == "rejected_duplicate":
                                    source_lit_duplicate_rejected_bundle_sigs.add(bundle_sig)
                                    fallback_attempt["bundle_signature"] = bundle_sig
                                if idx + 1 < len(literature_topics):
                                    continue
                                return ledger
                            if idx + 1 < len(literature_topics):
                                continue
                            return ledger
                    ledger["cycle_attempts"].append({
                        "topic": literature_topic,
                        "run_dir": candidate.get("run_dir"),
                        "fingerprint": candidate.get("memo_fingerprint"),
                        "status": publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value,
                    })
                    _write_ledger(ledger_path, ledger)
                    return ledger
                fallback_attempt["status"] = "blocked"
                fallback_attempt["reason"] = result["status"]
                if bundle_sig and result["status"] == "rejected_duplicate":
                    source_lit_duplicate_rejected_bundle_sigs.add(bundle_sig)
                    fallback_attempt["bundle_signature"] = bundle_sig
    if ledger["cycle_attempts"]:
        last_status = str(ledger["cycle_attempts"][-1].get("status") or "failed")
        ledger.update({
            "status": publish_status.CycleStatus.SUBMIT_RETRY_EXHAUSTED.value,
            "reason": f"no candidate accepted after {batch_limit} batch(es)",
            "last_attempt_status": last_status,
            "published": 0,
        })
    else:
        fallback_attempts = [
            row for row in ledger.get("source_literature_fallback_attempts") or []
            if isinstance(row, dict)
        ]
        ledger.update({
            "status": publish_status.CycleStatus.NO_FRESH_CANDIDATE.value,
            "reason": (
                "requires_fact_level_source_synthesis"
                if fallback_attempts and all(
                    row.get("status") in {"blocked", "disabled"}
                    and row.get("reason") == "requires_fact_level_source_synthesis"
                    for row in fallback_attempts
                )
                else _no_candidate_reason(all_considered)
            ),
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
