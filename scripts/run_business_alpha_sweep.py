"""Run repeated dry-run sweeps across business-family alpha lanes."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib
import json
import math
import os
import re
import signal
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.business_research import (
    BUSINESS_DOMAINS,
    MIN_DIRECT_SOURCES,
    build_candidate_bundle,
    fetch_business_facts,
    normalize_business_fact,
    write_candidate_run,
)
from agent.business_research import (
    source_key as business_fact_source_key,
)
from agent.domain_profile import load_domain_profile
from agent.researka_facts import tier2_domain
from agent.settings import load_settings
from agent.topic_synonyms import expand_topic_queries
from scripts import alpha_publish_literature as publish_literature
from scripts import alpha_publish_status as publish_status
from scripts import build_publish_queue as publish_queue
from scripts import daily_alpha_publish_cycle as publish_cycle
from scripts.alpha_publish_io import read_json, update_json_list, write_json, write_ledger
from scripts.build_business_alpha_candidate import (
    no_bundle_blockers_from_diagnostics,
    write_no_bundle_diagnostics,
)
from scripts.daily_alpha_publish_cycle import run_cycle

_RUNS = Path(__file__).resolve().parent.parent / "runs"
_DOMAINS = (
    "management_research",
    "economics_research",
    "finance_research",
    "business_research",
    "marketing_research",
)
_FULLRAW_ENV_FILE = "/etc/researka-fullraw.env"
_BROAD_SEED_TOKENS = frozenset({
    "business", "management", "economics", "finance", "marketing",
    "model", "performance", "effect", "effects", "outcome", "outcomes",
    "returns", "return", "research",
})
_BUSINESS_OUTCOME_QUERY_TOKENS = frozenset({
    "employment", "margin", "margins", "performance", "productivity",
    "profit", "profitability", "return", "returns", "sales", "value",
})
_BUSINESS_DERIVED_OUTCOME_TOKENS = (
    "performance", "productivity", "profitability", "margin",
    "sales", "value", "returns", "employment",
)
_BUSINESS_REPLACEABLE_OUTCOME_TOKENS = _BUSINESS_OUTCOME_QUERY_TOKENS | {
    "effect", "effects", "improvement",
}
_BUSINESS_FULLRAW_FOREGROUND_SECONDS = "2400"
_BUSINESS_FULLRAW_RESULT_LIMIT = "10"
_BUSINESS_FULLRAW_LOCK_PATH = "/tmp/researka-v4-business-fullraw.lock"
_BUSINESS_FULLRAW_LOCK_WAIT_SECONDS = "600"
_BUSINESS_FULLRAW_BACKOFF_SECONDS = "180"
_BUSINESS_FULLRAW_ADVANCE_MAX_SECONDS = "60"
_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS = "600"
_BUSINESS_FULLRAW_CACHE_PROBE_TIMEOUT_SECONDS = "2"
_FULLRAW_ENV_ALIASES = {
    "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL": ("RESEARKA_FULLRAW_SEARCH_URL",),
    "V5_MEMO_FULL_RAW_INDEX_TOKEN": (
        "RESEARKA_FULLRAW_INDEX_TOKEN", "RESEARKA_FULLRAW_TOKEN",
    ),
    "V5_MEMO_FULL_RAW_CORPUS_TOKEN": ("RESEARKA_FULLRAW_TOKEN",),
    "V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED": ("RESEARKA_FULLRAW_MIN_SHARDS_SEARCHED",),
    "V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED": ("RESEARKA_FULLRAW_MIN_SOURCES_SEARCHED",),
    "V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH": ("RESEARKA_FULLRAW_REQUIRE_COMPLETE_SEARCH",),
    "V5_MEMO_FULL_RAW_MAX_VARIANTS": ("RESEARKA_FULLRAW_MAX_VARIANTS",),
    "V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS": ("RESEARKA_FULLRAW_SEARCH_BUDGET_SECONDS",),
    "V5_MEMO_FULL_RAW_SWEEP_WAIT_SECONDS": ("RESEARKA_FULLRAW_SWEEP_WAIT_SECONDS",),
    "V5_MEMO_FULL_RAW_FOREGROUND_SWEEP_WAIT_SECONDS": (
        "RESEARKA_FULLRAW_FOREGROUND_SWEEP_WAIT_SECONDS",
        "RESEARKA_FULLRAW_SWEEP_WAIT_SECONDS",
    ),
}
_NON_BUSINESS_QUERY_SUFFIXES = (
    "_intervention", "_supplementation", "_therapy", "_treatment",
)


def _seed_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value).replace("-", "_").lower()))


def _variant_keeps_seed_intent(seed: str, variant: str) -> bool:
    base_tokens = _seed_tokens(seed)
    variant_tokens = _seed_tokens(variant)
    base_specific = base_tokens - _BROAD_SEED_TOKENS
    variant_specific = variant_tokens - _BROAD_SEED_TOKENS
    if base_specific:
        return base_specific <= variant_specific
    return base_tokens <= variant_tokens


def _business_fullraw_foreground_seconds() -> str:
    if explicit := os.environ.get("TOPIC_DISCOVERY_BUSINESS_FULLRAW_FOREGROUND_SECONDS"):
        return explicit
    configured = (
        os.environ.get("TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS")
        or os.environ.get("V5_MEMO_FULL_RAW_SEARCH_BUDGET_SECONDS")
    )
    try:
        return str(int(max(float(configured or 0), float(_BUSINESS_FULLRAW_FOREGROUND_SECONDS))))
    except ValueError:
        return _BUSINESS_FULLRAW_FOREGROUND_SECONDS


def _business_fullraw_result_limit() -> int:
    raw = os.environ.get("BUSINESS_SWEEP_FULLRAW_RESULT_LIMIT", _BUSINESS_FULLRAW_RESULT_LIMIT)
    with suppress(ValueError):
        return max(MIN_DIRECT_SOURCES, int(raw))
    return int(_BUSINESS_FULLRAW_RESULT_LIMIT)


def _business_fullraw_lock_wait_seconds() -> float:
    try:
        return max(
            0.0,
            float(
                os.environ.get("TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_WAIT_SECONDS")
                or _BUSINESS_FULLRAW_LOCK_WAIT_SECONDS
            ),
        )
    except ValueError:
        return 0.0


def _business_fullraw_backoff_seconds() -> float:
    try:
        return max(
            0.0,
            float(
                os.environ.get("TOPIC_DISCOVERY_BUSINESS_FULLRAW_BACKOFF_SECONDS")
                or _BUSINESS_FULLRAW_BACKOFF_SECONDS
            ),
        )
    except ValueError:
        return float(_BUSINESS_FULLRAW_BACKOFF_SECONDS)


def _business_fullraw_advance_max_seconds() -> float:
    try:
        return max(
            0.0,
            float(
                os.environ.get("TOPIC_DISCOVERY_BUSINESS_FULLRAW_ADVANCE_MAX_SECONDS")
                or _BUSINESS_FULLRAW_ADVANCE_MAX_SECONDS
            ),
        )
    except ValueError:
        return float(_BUSINESS_FULLRAW_ADVANCE_MAX_SECONDS)


def _business_fullraw_queue_retry_seconds() -> float:
    raw = os.environ.get("TOPIC_DISCOVERY_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS")
    if raw is None:
        raw = _BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS
    try:
        return max(
            0.0,
            float(raw),
        )
    except ValueError:
        return float(_BUSINESS_FULLRAW_QUEUE_RETRY_SECONDS)


def _business_fullraw_cache_probe_timeout_seconds() -> float:
    try:
        return max(
            0.2,
            float(
                os.environ.get("BUSINESS_SWEEP_FULLRAW_CACHE_PROBE_TIMEOUT_SECONDS")
                or _BUSINESS_FULLRAW_CACHE_PROBE_TIMEOUT_SECONDS
            ),
        )
    except ValueError:
        return float(_BUSINESS_FULLRAW_CACHE_PROBE_TIMEOUT_SECONDS)


def _business_fullraw_priority_enabled() -> bool:
    return os.environ.get(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_PRIORITY", "1",
    ).strip().lower() in {"1", "true", "yes", "on"}


def _business_fullraw_query_limit() -> int:
    default = "1" if _business_fullraw_priority_enabled() else "3"
    try:
        return max(1, int(os.environ.get("BUSINESS_SWEEP_FULLRAW_QUERY_LIMIT", default)))
    except ValueError:
        return int(default)


def _business_fullraw_poll_attempts(poll_seconds: float) -> int:
    if poll_seconds <= 0:
        return 1
    return max(1, math.ceil(_business_fullraw_advance_max_seconds() / poll_seconds))


def _fullraw_busy_event(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "")
    return (
        status in {
            "async_queue_saturated", "async_queued", "async_running", "busy",
            "failed", "health_unavailable", "in_progress_cache_hit",
            "incomplete_receipt", "inflight_saturated", "queue_saturated",
        }
        or str(event.get("async_status") or "") in {"queued", "running"}
        or event.get("partial_shard_search") is True
    )


def _fullraw_can_try_next_query(event: dict[str, Any]) -> bool:
    if not _business_fullraw_priority_enabled():
        return False
    status = str(event.get("status") or "")
    if status in {"busy", "failed", "health_unavailable"}:
        return False
    if event.get("key_queued") is True or event.get("key_running") is True:
        return False
    return (
        status in {
            "async_queued", "async_running", "in_progress_cache_hit",
            "in_progress_poll_due", "incomplete_receipt",
        }
        or str(event.get("async_status") or "") in {"queued", "running"}
        or event.get("partial_shard_search") is True
    )


def _fullraw_unadmitted_queue_event(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "")
    if status not in {"async_queue_saturated", "inflight_saturated", "queue_saturated"}:
        return False
    return event.get("key_queued") is not True and event.get("key_running") is not True


def _fullraw_queue_full(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "")
    saturated_status = status in {
        "async_queue_saturated", "inflight_saturated", "queue_saturated",
    }
    try:
        queued = int(event.get("queued_count") or 0)
        max_queue = int(event.get("max_queue") or 0)
    except (TypeError, ValueError):
        return saturated_status
    if saturated_status and max_queue <= 0:
        return True
    return max_queue > 0 and queued >= max_queue


def _fullraw_admitted_pending_event(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "")
    probe_status = str(event.get("probe_status") or "")
    if (
        _business_fullraw_priority_enabled()
        and str(event.get("async_status") or "") in {"queued", "running"}
    ):
        return True
    if event.get("key_queued") is not True and event.get("key_running") is not True:
        return (
            probe_status == "in_progress_cache_hit"
            and _count_int(event.get("paper_count")) > 0
        ) or (
            status == "in_progress_cache_hit" and _fullraw_queue_full(event)
        )
    return (
        status in {
            "async_queued", "async_running", "in_progress_cache_hit",
            "in_progress_poll_due", "incomplete_receipt",
        }
        or event.get("partial_shard_search") is True
    )


def _fullraw_backoff_path(runs_root: Path) -> Path:
    return runs_root / "_business_diagnostics" / "fullraw_backoff.json"


def _fullraw_backoff_key(topic: str) -> str:
    tokens = [
        token for token in str(topic or "").replace("_", " ").casefold().split()
        if token
    ]
    while len(tokens) > 1 and tokens[-1] in _BUSINESS_REPLACEABLE_OUTCOME_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _fullraw_family_diverse_topics(topics: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        family_key = _fullraw_backoff_key(topic)
        if family_key and family_key in seen:
            continue
        if family_key:
            seen.add(family_key)
        out.append(topic)
    return out


def _fullraw_backoff_ttl_seconds(event: dict[str, Any]) -> float:
    ttl = _business_fullraw_backoff_seconds()
    status = str(event.get("status") or event.get("previous_status") or "")
    async_status = str(event.get("async_status") or "")
    if (
        async_status in {"queued", "running"}
        or event.get("partial_shard_search") is True
        or status in {
            "async_queued", "async_running", "in_progress_cache_hit",
            "in_progress_poll_due", "incomplete_receipt",
        }
    ):
        with suppress(ValueError):
            ttl = max(ttl, float(_business_fullraw_foreground_seconds()))
    elif _fullraw_queue_full(event):
        ttl = max(ttl, _business_fullraw_queue_retry_seconds())
    return ttl


def _fullraw_backoff(runs_root: Path | None, topic: str) -> dict[str, Any] | None:
    if runs_root is None:
        return None
    data = read_json(_fullraw_backoff_path(runs_root), {})
    if not isinstance(data, dict):
        return None
    key = _fullraw_backoff_key(topic)
    entries = data.get("entries")
    if isinstance(entries, dict):
        data = entries.get(key, {})
        if not isinstance(data, dict):
            return None
    elif data.get("key") != key:
        return None
    try:
        age = time.time() - float(data.get("ts") or 0.0)
    except (TypeError, ValueError):
        return None
    ttl = _fullraw_backoff_ttl_seconds(data)
    raw_ttl = data.get("backoff_seconds")
    if raw_ttl is not None:
        with suppress(TypeError, ValueError):
            ttl = float(raw_ttl)
    if ttl <= 0 or age > ttl:
        return None
    return {
        "status": "busy",
        "reason": "fullraw_backoff",
        "previous_status": data.get("status"),
        "backoff_age_seconds": age,
        "backoff_seconds": ttl,
        "backoff_key": key,
    }


def _record_fullraw_backoff(runs_root: Path | None, topic: str, event: dict[str, Any]) -> None:
    if runs_root is None or not _fullraw_busy_event(event):
        return
    path = _fullraw_backoff_path(runs_root)
    current = read_json(path, {})
    entries = current.get("entries") if isinstance(current, dict) else {}
    if not isinstance(entries, dict):
        entries = {}
    key = _fullraw_backoff_key(topic)
    entries[key] = {
        "key": key,
        "ts": time.time(),
        "status": event.get("status"),
        "async_status": event.get("async_status"),
        "backoff_seconds": _fullraw_backoff_ttl_seconds(event),
        "queued_count": event.get("queued_count"),
        "max_queue": event.get("max_queue"),
        "shards_searched": event.get("shards_searched"),
        "partial_shard_search": event.get("partial_shard_search"),
    }
    write_json(path, {"entries": entries})


def _raise_fullraw_timeout(_signum: int, _frame: Any) -> None:
    raise TimeoutError("business fullraw probe exceeded foreground budget")


def _load_fullraw_env_defaults() -> None:
    try:
        lines = Path(os.environ.get("V5_MEMO_FULL_RAW_ENV_FILE", _FULLRAW_ENV_FILE)).read_text(
            encoding="utf-8",
        ).splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), raw_value.strip().strip("'\""))
    for target, sources in _FULLRAW_ENV_ALIASES.items():
        if os.environ.get(target):
            continue
        for source in sources:
            alias_value = os.environ.get(source)
            if alias_value:
                os.environ[target] = alias_value
                break


def _cached_complete_fullraw_probe(
    topic: str, *, include_papers: bool = False,
    queries: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    result_limit = _business_fullraw_result_limit()
    attempted: list[str] = []
    for query in _rank_fullraw_queries_by_cached_receipt(
        queries or _business_fullraw_queries(topic),
    ):
        attempted.append(query)
        data = _fullraw_search_response(
            query,
            limit=result_limit,
            queue_if_missing=False,
            timeout_seconds=_business_fullraw_cache_probe_timeout_seconds(),
        )
        if not data or not _fullraw_response_complete(data):
            continue
        items = data.get("results") or data.get("hits") or []
        papers = [item for item in items if isinstance(item, dict)]
        if len(papers) < MIN_DIRECT_SOURCES:
            continue
        raw_meta = data.get("meta")
        meta = raw_meta if isinstance(raw_meta, dict) else data
        raw_receipt = meta.get("shard_receipt")
        receipt = raw_receipt if isinstance(raw_receipt, dict) else meta
        result: dict[str, Any] = {
            "status": "complete",
            "probe_status": "cache_complete",
            "source": "fullraw_cache_complete",
            "query": query,
            "attempted_queries": list(attempted),
            "paper_count": len(papers),
            "shards_searched": receipt.get("shards_searched"),
            "partial_shard_search": receipt.get("partial_shard_search"),
            "sweep_failed_shards": receipt.get("sweep_failed_shards"),
            "sources_searched": receipt.get("sources_searched"),
            "papers_searched": receipt.get("papers_searched"),
            "papers_total": receipt.get("papers_total"),
            "result_count_returned": receipt.get("result_count_returned"),
            "result_count_unique": receipt.get("result_count_unique"),
            "result_citation_diversity": receipt.get("result_citation_diversity"),
            "candidate_fact_source_count": _fullraw_substantive_fact_candidates(
                topic, papers,
            ),
        }
        if include_papers:
            result["_papers"] = papers
        return result
    return None


def _strict_fullraw_probe(
    topic: str, *, include_papers: bool = False, runs_root: Path | None = None,
    queries: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    _load_fullraw_env_defaults()
    if not (
        os.environ.get("V5_MEMO_FULL_RAW_INDEX_TOKEN")
        or os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL")
    ):
        return {"status": "not_configured"}
    backoff = _fullraw_backoff(runs_root, topic)
    if backoff:
        cached_complete = _cached_complete_fullraw_probe(
            topic, include_papers=include_papers, queries=queries,
        )
        if cached_complete:
            cached_complete["backoff_bypassed"] = True
            cached_complete["previous_status"] = backoff.get("previous_status")
            cached_complete["backoff_key"] = backoff.get("backoff_key")
            return cached_complete
        return backoff
    lock_handle = None
    budget_key = "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"
    old_budget = os.environ.get(budget_key)
    timeout_key = "TOPIC_DISCOVERY_FULLRAW_TIMEOUT_SECONDS"
    old_timeout = os.environ.get(timeout_key)
    attempts_key = "TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"
    old_attempts = os.environ.get(attempts_key)
    poll_seconds_key = "TOPIC_DISCOVERY_FULLRAW_POLL_SECONDS"
    old_poll_seconds = os.environ.get(poll_seconds_key)
    sweep_wait_key = "TOPIC_DISCOVERY_V5_SWEEP_WAIT_SECONDS"
    old_sweep_wait = os.environ.get(sweep_wait_key)
    priority_key = "TOPIC_DISCOVERY_FULLRAW_PRIORITY"
    old_priority = os.environ.get(priority_key)
    try:
        lock_path = Path(os.environ.get(
            "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
            _BUSINESS_FULLRAW_LOCK_PATH,
        ))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("a", encoding="utf-8")
        lock_deadline = time.monotonic() + _business_fullraw_lock_wait_seconds()
        while True:
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = lock_deadline - time.monotonic()
                if remaining <= 0:
                    return {"status": "busy"}
                time.sleep(min(5.0, remaining))
        os.environ[budget_key] = _business_fullraw_foreground_seconds()
        httpx_mod = importlib.import_module("httpx")
        topic_discovery_mod = importlib.import_module("agent.topic_discovery")
        discovery = importlib.import_module("scripts.run_topic_discovery")
        timeout_seconds = float(os.environ.get(
            "TOPIC_DISCOVERY_BUSINESS_FULLRAW_HTTP_TIMEOUT_SECONDS",
            os.environ.get(budget_key, _BUSINESS_FULLRAW_FOREGROUND_SECONDS),
        ))
        os.environ[timeout_key] = str(timeout_seconds)
        os.environ[sweep_wait_key] = str(timeout_seconds)
        try:
            poll_seconds = float(os.environ.get(
                "TOPIC_DISCOVERY_BUSINESS_FULLRAW_POLL_SECONDS", "15",
            ))
        except ValueError:
            poll_seconds = 15.0
        os.environ[poll_seconds_key] = str(
            int(poll_seconds) if poll_seconds.is_integer() else poll_seconds
        )
        os.environ[attempts_key] = str(_business_fullraw_poll_attempts(poll_seconds))
        if _business_fullraw_priority_enabled():
            os.environ[priority_key] = "1"

        old_handler = signal.getsignal(signal.SIGALRM)
        old_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, _raise_fullraw_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds + max(5.0, timeout_seconds * 0.1))
        try:
            with httpx_mod.Client(timeout=timeout_seconds) as client:
                result: dict[str, Any] = {}
                best_progress: dict[str, Any] = {}
                attempted: list[str] = []
                result_limit = _business_fullraw_result_limit()
                queries = _rank_fullraw_queries_by_cached_receipt(
                    queries or _business_fullraw_queries(topic),
                )
                queue_retry_deadline = (
                    time.monotonic() + _business_fullraw_queue_retry_seconds()
                )
                while True:
                    for idx, query in enumerate(queries):
                        attempted.append(query)
                        events = discovery.__dict__.get("_FULLRAW_PROBE_EVENTS", [])
                        before = len(events)
                        papers = discovery.__dict__["_seed_fullraw_papers"](
                            query, client=client, limit=result_limit,
                        )
                        receipt = topic_discovery_mod.__dict__.get("_FULLRAW_LAST_RECEIPT", {})
                        if (not isinstance(receipt, dict) or not receipt) and papers:
                            paper_receipt = papers[0].get("fullraw_shard_receipt")
                            if isinstance(paper_receipt, dict):
                                receipt = paper_receipt
                        async_sweep = topic_discovery_mod.__dict__.get(
                            "_FULLRAW_LAST_ASYNC_SWEEP", {},
                        )
                        receipt_complete = bool(
                            discovery.__dict__["_fullraw_receipt_complete"](receipt),
                        )
                        events = discovery.__dict__.get("_FULLRAW_PROBE_EVENTS", [])
                        new_events = [
                            event for event in events[before:]
                            if isinstance(event, dict)
                        ]
                        event = next(
                            (item for item in reversed(new_events) if _fullraw_busy_event(item)),
                            new_events[-1] if new_events else {},
                        )
                        status = (
                            "complete" if papers and receipt_complete else
                            "incomplete_receipt" if papers else
                            "complete_no_hits" if receipt_complete else
                            str(event.get("status") or "no_hits")
                        )
                        result = {
                            "status": status,
                            "probe_status": event.get("status"),
                            "query": query,
                            "attempted_queries": list(attempted),
                            "paper_count": len(papers),
                            "async_status": (
                                async_sweep.get("status")
                                if isinstance(async_sweep, dict) else None
                            ) or event.get("async_status"),
                            "key_queued": (
                                async_sweep.get("key_queued")
                                if isinstance(async_sweep, dict)
                                and "key_queued" in async_sweep else event.get("key_queued")
                            ),
                            "key_running": (
                                async_sweep.get("key_running")
                                if isinstance(async_sweep, dict)
                                and "key_running" in async_sweep else event.get("key_running")
                            ),
                            "queued_count": (
                                async_sweep.get("queued_count")
                                if isinstance(async_sweep, dict)
                                and "queued_count" in async_sweep else event.get("queued_count")
                            ),
                            "inflight_count": (
                                async_sweep.get("inflight_count")
                                if isinstance(async_sweep, dict)
                                and "inflight_count" in async_sweep
                                else event.get("inflight_count")
                            ),
                            "max_inflight": (
                                async_sweep.get("max_inflight")
                                if isinstance(async_sweep, dict)
                                and "max_inflight" in async_sweep else event.get("max_inflight")
                            ),
                            "max_queue": (
                                async_sweep.get("max_queue")
                                if isinstance(async_sweep, dict)
                                and "max_queue" in async_sweep else event.get("max_queue")
                            ),
                            "shards_searched": (
                                receipt.get("shards_searched")
                                if isinstance(receipt, dict) else None
                            ) or event.get("shards_searched"),
                            "partial_shard_search": (
                                receipt.get("partial_shard_search")
                                if isinstance(receipt, dict)
                                and "partial_shard_search" in receipt
                                else event.get("partial_shard_search")
                            ),
                            "sweep_failed_shards": (
                                receipt.get("sweep_failed_shards")
                                if isinstance(receipt, dict)
                                and "sweep_failed_shards" in receipt
                                else event.get("sweep_failed_shards")
                            ),
                            "sources_searched": (
                                receipt.get("sources_searched")
                                if isinstance(receipt, dict) else None
                            ) or event.get("sources_searched"),
                            "papers_searched": (
                                receipt.get("papers_searched")
                                if isinstance(receipt, dict) else None
                            ) or event.get("papers_searched"),
                            "papers_total": (
                                receipt.get("papers_total")
                                if isinstance(receipt, dict) else None
                            ) or event.get("papers_total"),
                            "result_count_returned": (
                                receipt.get("result_count_returned")
                                if isinstance(receipt, dict) else None
                            ) or event.get("result_count_returned"),
                            "result_count_unique": (
                                receipt.get("result_count_unique")
                                if isinstance(receipt, dict) else None
                            ) or event.get("result_count_unique"),
                            "result_citation_diversity": (
                                receipt.get("result_citation_diversity")
                                if isinstance(receipt, dict) else None
                            ) or event.get("result_citation_diversity"),
                        }
                        if status == "incomplete_receipt" and not result.get("async_status"):
                            live_status = _fullraw_search_response(
                                query,
                                limit=result_limit,
                                queue_if_missing=True,
                                timeout_seconds=_business_fullraw_cache_probe_timeout_seconds(),
                            )
                            meta = live_status.get("meta") if isinstance(live_status, dict) else {}
                            async_sweep = (
                                meta.get("async_sweep") if isinstance(meta, dict) else {}
                            )
                            if isinstance(async_sweep, dict):
                                result["async_status"] = async_sweep.get("status")
                                for key in (
                                    "cache_key", "inflight_count", "key_queued",
                                    "key_running", "max_inflight", "max_queue",
                                    "queued_count", "shard_limit",
                                ):
                                    if async_sweep.get(key) is not None:
                                        result[key] = async_sweep.get(key)
                        source_papers = papers
                        if status == "complete" and papers:
                            source_papers = _merge_fullraw_hit_text(
                                papers, _fullraw_search_hits(query, limit=result_limit),
                            )
                            result["candidate_fact_source_count"] = (
                                _fullraw_substantive_fact_candidates(topic, source_papers)
                            )
                        if include_papers:
                            result["_papers"] = source_papers
                        _record_fullraw_backoff(runs_root, topic, result)
                        if _fullraw_busy_event(result):
                            best_progress = result
                        source_candidates = int(result.get("candidate_fact_source_count") or 0)
                        if (
                            _fullraw_unadmitted_queue_event(result)
                            and _fullraw_queue_full(result)
                        ):
                            result["queue_waiting"] = True
                            result["backoff_seconds"] = _business_fullraw_backoff_seconds()
                            break
                        if source_candidates >= MIN_DIRECT_SOURCES or idx + 1 >= len(queries):
                            break
                        if status in {"complete", "complete_no_hits", "no_hits"}:
                            continue
                        if _fullraw_can_try_next_query(result):
                            continue
                        break
                    if (
                        not _fullraw_unadmitted_queue_event(result)
                        and not _fullraw_admitted_pending_event(result)
                    ):
                        break
                    if (
                        _fullraw_unadmitted_queue_event(result)
                        and _fullraw_queue_full(result)
                    ):
                        result["queue_shed"] = True
                        result.setdefault(
                            "backoff_seconds", _business_fullraw_backoff_seconds(),
                        )
                        break
                    if result.get("queue_shed") is True:
                        break
                    remaining = queue_retry_deadline - time.monotonic()
                    if _fullraw_admitted_pending_event(result):
                        result["queue_waiting"] = True
                        result.setdefault(
                            "backoff_seconds", _business_fullraw_backoff_seconds(),
                        )
                        if result.get("key_running") is not True or remaining <= 0:
                            break
                        time.sleep(min(max(poll_seconds, 0.1), remaining))
                        continue
                    if remaining <= 0:
                        break
                    time.sleep(min(poll_seconds, remaining))
                if (
                    best_progress
                    and result.get("status") in {"complete_no_hits", "no_hits"}
                ):
                    result = best_progress | {"attempted_queries": list(attempted)}
                return result
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, old_handler)
            if old_timer[0] > 0.0:
                signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])
    except Exception as exc:
        return {"status": "failed", "error": exc.__class__.__name__}
    finally:
        if old_budget is None:
            os.environ.pop(budget_key, None)
        else:
            os.environ[budget_key] = old_budget
        if old_timeout is None:
            os.environ.pop(timeout_key, None)
        else:
            os.environ[timeout_key] = old_timeout
        if old_attempts is None:
            os.environ.pop(attempts_key, None)
        else:
            os.environ[attempts_key] = old_attempts
        if old_poll_seconds is None:
            os.environ.pop(poll_seconds_key, None)
        else:
            os.environ[poll_seconds_key] = old_poll_seconds
        if old_sweep_wait is None:
            os.environ.pop(sweep_wait_key, None)
        else:
            os.environ[sweep_wait_key] = old_sweep_wait
        if old_priority is None:
            os.environ.pop(priority_key, None)
        else:
            os.environ[priority_key] = old_priority
        if lock_handle is not None:
            with suppress(OSError):
                fcntl.flock(lock_handle, fcntl.LOCK_UN)
            lock_handle.close()


def _business_fullraw_queries(topic: str) -> tuple[str, ...]:
    discovery = importlib.import_module("scripts.run_topic_discovery")
    compact = discovery.__dict__.get("_compact_fullraw_query", lambda q: " ".join(q.split()))
    alpha_terms = discovery.__dict__.get("_alpha_shape_query_terms", lambda: ())()
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str) -> None:
        query = str(compact(raw.replace("_", " "))).strip()
        key = " ".join(sorted(set(query.split())))
        if out and not _variant_keeps_seed_intent(topic, query):
            return
        if query and key not in seen:
            seen.add(key)
            out.append(query)

    bases = tuple(expand_topic_queries(topic, max_queries=3))
    if bases:
        base = str(compact(str(bases[0]).replace("_", " "))).strip()
        if _seed_tokens(base) & _BUSINESS_OUTCOME_QUERY_TOKENS:
            add(base)
        else:
            add(f"{base} performance")
            add(base)
    if out:
        base = out[0]
        base_tokens = _seed_tokens(base)
        if not base_tokens & {"performance", "profitability", "return", "returns"}:
            add(f"{base} performance")
        add(f"{base} empirical")
    for term in tuple(alpha_terms)[:2]:
        if out:
            add(f"{out[0]} {term}")
    for raw in bases[1:]:
        add(raw)
    return tuple(out[:_business_fullraw_query_limit()])


def _write_fullraw_discovery(
    runs_root: Path, *, domain: str, topic: str, profile: Any, papers: list[dict[str, Any]],
) -> Path:
    out_dir = runs_root / "_topics_discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in papers:
        key = str(
            paper.get("doi")
            or paper.get("pmid")
            or paper.get("paper_id")
            or paper.get("title")
            or ""
        )
        if not key or key.casefold() in seen:
            continue
        seen.add(key.casefold())
        unique.append(paper)
    payload = {
        "domain": profile.as_metadata(),
        "source": "business_sweep_fullraw",
        "all": [{
            "topic": topic,
            "paper_count": len(unique),
            "fact_source_count": publish_literature.substantive_fact_count(unique),
            "source_papers": unique,
        }],
    }
    out_path = out_dir / f"business_sweep_fullraw.{domain}.{topic}.json"
    write_json(out_path, payload)
    return out_path


_FULLRAW_METADATA_ARTIFACT_TERMS = (
    "dataset", "data set", "replication package", "research instrument",
    "survey instrument", "supplementary material",
)

_BUSINESS_ENDPOINT_PHRASES = (
    "environmental performance", "firm performance", "firm value",
    "firm profitability", "profitability", "competitiveness",
    "supply chain performance", "supply chain disruption risk",
    "supply chain resilience",
    "inventory management", "human capital",
)
_ABSTRACT_FINDING_TERMS = (
    "finding", "findings", "result", "results", "revealed", "shows", "showed",
    "significant", "significantly", "positive", "negative", "associated",
    "effect", "effects", "impact", "impacts", "improves", "improved",
    "enhances", "enhanced", "mediates", "moderates", "increases", "decreases",
    "reveal", "reveals", "indicate", "indicates", "demonstrate",
    "demonstrates", "suggest", "suggests", "substantially",
)
_ABSTRACT_RESULT_TERMS = set(_ABSTRACT_FINDING_TERMS) - {
    "effect", "effects", "impact", "impacts",
}
_ABSTRACT_INTRO_STARTS = (
    "abstract", "background", "introduction", "purpose", "objective",
    "this paper aims", "this study aims", "this research aims",
    "this paper examines", "this study examines", "this research examines",
    "this paper investigates", "this study investigates", "this research investigates",
    "using a sample", "using data", "we employ", "we use",
    "design/methodology/approach",
)
_ABSTRACT_AIM_ONLY_RE = re.compile(
    r"\b(?:aim|aims|aimed|purpose|objective|objectives|"
    r"this (?:paper|study|research) (?:examines|investigates|seeks)|"
    r"identify|evaluate|assess)\b"
)
_ABSTRACT_RESULT_CUE_RE = re.compile(
    r"\b(?:findings?|results?|reveals?|revealed|shows?|showed|indicates?|"
    r"indicated|demonstrates?|demonstrated|suggests?|suggested|confirms?|"
    r"confirmed|we find|we found)\b"
)
_ABSTRACT_GAP_CUE_RE = re.compile(
    r"\b(?:although|however|not fully understood|gap|aims? to|purpose|"
    r"objective|background)\b"
)


def _first_sentence(text: str, *, limit: int = 220) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    sentence = str(re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0]).strip()
    if len(sentence) <= limit:
        return sentence.rstrip(".")
    return sentence[:limit].rsplit(" ", 1)[0].rstrip(".,;")


def _abstract_finding_sentence(text: str, *, limit: int = 700) -> str:
    clean = re.sub(r"<[^>]+>", " ", str(text or ""))
    clean = " ".join(clean.split()).strip()
    candidates: list[tuple[int, int, str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", clean):
        candidate = sentence.strip()
        lowered = candidate.casefold()
        if not candidate or any(lowered.startswith(prefix) for prefix in _ABSTRACT_INTRO_STARTS):
            continue
        tokens = set(re.findall(r"[a-z]+", lowered))
        if _ABSTRACT_AIM_ONLY_RE.search(lowered) and not (tokens & _ABSTRACT_RESULT_TERMS):
            continue
        if tokens & _ABSTRACT_RESULT_TERMS:
            score = 0
            if _ABSTRACT_RESULT_CUE_RE.search(lowered):
                score += 3
            if lowered.startswith(("findings", "results", "we find", "we found")):
                score += 2
            if _ABSTRACT_GAP_CUE_RE.search(lowered):
                score -= 2
            candidates.append((score, -len(candidates), candidate))
    if candidates:
        candidate = max(candidates)[2]
        if len(candidate) <= limit:
            return candidate.rstrip(".")
        return candidate[:limit].rsplit(" ", 1)[0].rstrip(".,;")
    return ""


def _strip_markup_text(value: Any) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", str(value or "")).split()).strip()


def _norm_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _clean_topic(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip()


def _clean_endpoint_tail(value: str) -> str:
    tail = re.split(
        r"\b(?:using|among|within|during|while|where|when|through|based on|from)\b",
        value,
        maxsplit=1,
    )[0]
    tail = re.split(r"\bof\s+(?:a|an|the|chemical|manufacturing|listed|public|private)\b", tail, maxsplit=1)[0]
    words = [word for word in tail.split() if len(word) > 1]
    return " ".join(words[:8]).strip()


def _abstract_endpoint_phrase(topic: str, finding: str, artifact_text: str) -> str:
    topic_words = set(_norm_text(topic).split()) - _BROAD_SEED_TOKENS
    candidates = [phrase for phrase in _BUSINESS_ENDPOINT_PHRASES if phrase in artifact_text]
    finding_text = _norm_text(finding)
    for pattern in (
        r"\b(?:effect|impact|influence)s?\s+of\b[^.;]{0,120}\b(?:on|to)\s+([a-z ]{3,100})",
        r"\b(?:effect|impact|influence)s?\s+on\s+([a-z ]{3,100})",
        r"\b(?:affects?|improves?|improved|enhances?|enhanced|influences?)\s+([a-z ]{3,100})",
    ):
        match = re.search(pattern, finding_text)
        if not match:
            continue
        endpoint = _clean_endpoint_tail(match.group(1))
        if endpoint:
            for phrase in candidates:
                phrase_words = set(_norm_text(phrase).split())
                if phrase in endpoint and not phrase_words <= topic_words:
                    return phrase
            return endpoint
    if not candidates:
        return "business outcome"
    for phrase in candidates:
        phrase_words = set(_norm_text(phrase).split())
        if phrase_words and not phrase_words <= topic_words:
            return phrase
    return candidates[0]


def _fullraw_hit_key(item: dict[str, Any]) -> str:
    return str(
        item.get("doi") or item.get("pmid") or item.get("pmcid")
        or item.get("paper_id") or item.get("id") or item.get("title") or ""
    ).strip().casefold()


def _count_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cached_fullraw_discovery_papers(
    runs_root: Path, domain: str, topic: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    discovery = read_json(
        runs_root / "_topics_discovery" / f"business_sweep_fullraw.{domain}.{topic}.json",
        {},
    )
    rows = discovery.get("all") if isinstance(discovery, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return [], {}
    row = rows[0]
    papers = [paper for paper in row.get("source_papers") or [] if isinstance(paper, dict)]
    if _count_int(row.get("paper_count")) < MIN_DIRECT_SOURCES:
        return [], {}
    query = str(row.get("query") or topic)
    cached_hits = _fullraw_search_response(
        query,
        limit=_business_fullraw_result_limit(),
        queue_if_missing=False,
        timeout_seconds=_business_fullraw_cache_probe_timeout_seconds(),
    )
    hit_items = cached_hits.get("results") or cached_hits.get("hits") or []
    papers = _merge_fullraw_hit_text(
        papers,
        [item for item in hit_items if isinstance(item, dict)],
    )
    fact_count = publish_literature.substantive_fact_count(papers)
    candidate_fact_count = max(
        fact_count,
        _fullraw_substantive_fact_candidates(topic, papers),
    )
    source_count = publish_literature.source_identity_count(papers)
    if candidate_fact_count <= 0 or source_count < MIN_DIRECT_SOURCES:
        return [], {}
    trace = {
        "status": "complete",
        "source": "business_sweep_fullraw_cache",
        "query": query,
        "paper_count": len(papers),
        "fact_source_count": fact_count,
        "candidate_fact_source_count": candidate_fact_count,
        "source_identity_count": source_count,
    }
    return papers, trace


def _source_literature_cache_topics(topic: str) -> tuple[str, ...]:
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", str(topic).replace("-", "_").lower())
        if token
    ]
    if not tokens:
        return ()
    variants = ["_".join(tokens)]
    trimmed = list(tokens)
    while len(trimmed) > 1 and trimmed[-1] in _BUSINESS_REPLACEABLE_OUTCOME_TOKENS:
        trimmed = trimmed[:-1]
        alias = "_".join(trimmed)
        if alias and alias not in variants:
            variants.append(alias)
    if len(tokens) >= 3:
        for alias in _derived_seed_topic_variants(variants[0]):
            if alias not in variants:
                variants.append(alias)
    return tuple(variants)


def _cache_alias_selected_papers_allowed(
    topic: str, cache_topic: str, selected: list[dict[str, Any]],
) -> bool:
    if cache_topic == topic:
        return True
    topic_tokens = set(publish_literature._topic_token_sequence(topic))
    cache_tokens = set(publish_literature._topic_token_sequence(cache_topic))
    removed = topic_tokens - cache_tokens
    added = cache_tokens - topic_tokens
    base_tokens = topic_tokens - _BUSINESS_REPLACEABLE_OUTCOME_TOKENS
    if (
        len(topic_tokens) < 3
        or not cache_tokens
        or not removed
        or not (removed | added) <= _BUSINESS_REPLACEABLE_OUTCOME_TOKENS
        or not base_tokens <= cache_tokens
    ):
        return False
    required = len(topic_tokens)
    return all(
        publish_literature._topic_token_coverage(topic, paper) >= required
        for paper in selected
    ) and _cache_alias_outcome_supported_by_sources(removed, selected)


def _cache_alias_outcome_supported_by_sources(
    outcome_tokens: set[str], selected: list[dict[str, Any]],
) -> bool:
    if not outcome_tokens:
        return True
    supported_sources = 0
    for paper in selected:
        fact = paper.get("source_fact")
        fact = fact if isinstance(fact, dict) else {}
        source_text = publish_literature.title_key(" ".join(str(value or "") for value in (
            paper.get("title"),
            paper.get("paper_title"),
            paper.get("abstract"),
            paper.get("snippet"),
            paper.get("source_excerpt"),
            fact.get("source_excerpt"),
        )))
        words = source_text.split()
        if words and all(
            any(publish_literature._token_matches(word, token) for word in words)
            for token in outcome_tokens
        ):
            supported_sources += 1
    return supported_sources >= MIN_DIRECT_SOURCES


def _merge_source_literature_papers(
    *paper_sets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for papers in paper_sets:
        for paper in papers:
            key = publish_literature.source_identity_key(paper) or _fullraw_hit_key(paper)
            if not key:
                continue
            existing_idx = seen.get(key)
            if existing_idx is not None:
                existing = merged[existing_idx]
                if (
                    publish_literature.substantive_fact_count([paper]) > 0
                    and publish_literature.substantive_fact_count([existing]) <= 0
                ):
                    merged[existing_idx] = paper
                continue
            seen[key] = len(merged)
            merged.append(paper)
    return sorted(
        merged,
        key=lambda paper: not publish_literature.substantive_fact_count([paper]),
    )


def _business_fact_source_literature_papers(
    facts: list[dict[str, Any]], *, topic: str, domain: str,
) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in facts:
        if not isinstance(item, dict):
            continue
        fact = normalize_business_fact(item, topic=topic, domain=domain)
        key = business_fact_source_key(fact)
        phrase = str(fact.get("canonical_phrase") or "").strip()
        if not key or key in seen or not phrase:
            continue
        source_paper = fact.get("source_paper")
        source_paper = source_paper if isinstance(source_paper, dict) else {}
        title = str(source_paper.get("title") or phrase).strip()
        source_fact = publish_literature.source_fact(fact | {"id": fact.get("fact_id") or key})
        candidate = {
            "id": key,
            "title": title,
            "paper_title": title,
            "doi": source_paper.get("doi"),
            "pmid": source_paper.get("pmid"),
            "pmcid": source_paper.get("pmcid"),
            "paper_id": source_paper.get("paper_id") or key,
            "source_fact": source_fact,
        }
        for field in (
            "journal_name", "journal", "venue", "publisher", "publication_year",
            "url", "source_url",
        ):
            if source_paper.get(field):
                candidate[field] = source_paper.get(field)
        if publish_literature.substantive_fact_count([candidate]) <= 0:
            continue
        if not publish_literature.topic_relevant(topic, candidate):
            continue
        seen.add(key)
        papers.append(candidate)
    return papers


_SOURCE_COMPLETION_QUERY_STOP_TOKENS = _BROAD_SEED_TOKENS | frozenset({
    "analysis", "approach", "dataset", "evidence", "impact", "impacts",
    "on", "paper", "role", "study", "using",
})


def _ordered_query_tokens(value: Any) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[a-z0-9]+", str(value or "").casefold())))


def _source_completion_fullraw_queries(
    topic: str, papers: list[dict[str, Any]],
) -> tuple[str, ...]:
    discovery = importlib.import_module("scripts.run_topic_discovery")
    compact = discovery.__dict__.get("_compact_fullraw_query", lambda q: " ".join(q.split()))
    base = [
        token for token in _ordered_query_tokens(topic.replace("_", " "))
        if token not in _BROAD_SEED_TOKENS
    ]
    if not base:
        base = _ordered_query_tokens(_business_fullraw_queries(topic)[0] if _business_fullraw_queries(topic) else topic)
    seen = {" ".join(sorted(set(query.split()))) for query in _business_fullraw_queries(topic)}
    out: list[str] = []

    def add(extras: list[str]) -> None:
        room = max(1, 5 - len(base))
        tail = [token for token in extras if token not in base][-_business_fullraw_query_limit():]
        query = str(compact(" ".join([*base, *tail[-room:]]))).strip()
        key = " ".join(sorted(set(query.split())))
        if query and key not in seen:
            seen.add(key)
            out.append(query)

    for paper in papers:
        if publish_literature.substantive_fact_count([paper]) > 0:
            continue
        text = " ".join(str(paper.get(key) or "") for key in (
            "title", "paper_title", "abstract", "source_excerpt", "snippet",
        )).casefold()
        if any(term in text for term in _FULLRAW_METADATA_ARTIFACT_TERMS):
            continue
        before = len(out)
        for phrase in _BUSINESS_ENDPOINT_PHRASES:
            if phrase in text:
                add([
                    token for token in _ordered_query_tokens(phrase)
                    if token not in _SOURCE_COMPLETION_QUERY_STOP_TOKENS
                ])
        if len(out) > before:
            continue
        add([
            token for token in _ordered_query_tokens(text)
            if token not in _SOURCE_COMPLETION_QUERY_STOP_TOKENS
        ])
        if len(out) >= 2:
            break
    return tuple(out[:2])


def _strict_fullraw_probe_papers(
    topic: str, runs_root: Path, *, queries: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trace = _strict_fullraw_probe(
        topic, include_papers=True, runs_root=runs_root, queries=queries,
    )
    papers = [paper for paper in trace.pop("_papers", []) if isinstance(paper, dict)]
    if trace.get("status") == "complete":
        papers = _merge_fullraw_hit_text(
            papers,
            _fullraw_search_hits(str(trace.get("query") or topic)),
        )
    return papers, trace


def _source_fact_claim_key(paper: dict[str, Any]) -> str:
    fact = paper.get("source_fact")
    if not isinstance(fact, dict):
        return ""
    return _norm_text(" ".join(str(fact.get(key) or "") for key in (
        "canonical_phrase", "population", "intervention", "endpoint", "metric",
    )))


def _source_outlet_key(paper: dict[str, Any]) -> str:
    for key in (
        "journal_name", "journal", "venue", "publisher", "source",
        "source_name", "container_title", "publication_venue",
    ):
        value = paper.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title")
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item)
        if cleaned := _norm_text(value):
            return cleaned
    doi_prefix = str(paper.get("doi") or "").strip().casefold().split("/", 1)[0]
    for key in ("url", "source_url", "landing_page_url"):
        value = str(paper.get(key) or "").strip()
        host = urllib.parse.urlparse(value).netloc.casefold().removeprefix("www.")
        if host == "doi.org" and doi_prefix:
            return "doi-prefix:" + doi_prefix
        if host:
            return host
    return ""


def _source_outlet_count(papers: list[dict[str, Any]]) -> int:
    return len({key for paper in papers if (key := _source_outlet_key(paper))})


def _claim_diverse_source_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    for paper in papers:
        claim_key = _source_fact_claim_key(paper)
        if claim_key and claim_key in seen_claims:
            continue
        if claim_key:
            seen_claims.add(claim_key)
        out.append(paper)
    return out


def _source_literature_ready_papers(
    topic: str, domain: str, papers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    papers = _claim_diverse_source_papers(papers)
    selected = publish_literature.select_boundary_papers(
        topic,
        papers,
        MIN_DIRECT_SOURCES,
        strict_topic_coverage=publish_literature._non_biomedical(domain),
        profile_slug=domain,
    )
    if publish_literature.substantive_fact_count(selected) < MIN_DIRECT_SOURCES:
        return [], "requires_fact_level_source_synthesis"
    if (
        publish_literature.source_identity_count(selected, require_substantive=True)
        < MIN_DIRECT_SOURCES
    ):
        return selected, "source_fact_diversity_below_min"
    if publish_literature.source_outlet_diversity_below_min(
        selected,
        MIN_DIRECT_SOURCES,
    ):
        return selected, "source_outlet_diversity_below_min"
    if (
        publish_literature._non_biomedical(domain)
        and not publish_literature._directional_floor_met(
            selected, topic, domain, MIN_DIRECT_SOURCES,
        )
    ):
        return selected, "directional_receipt_floor_below_min"
    return selected, "ok"


def _fullraw_search_response(
    query: str, *, limit: int | None = None, queue_if_missing: bool = True,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    _load_fullraw_env_defaults()
    limit = _business_fullraw_result_limit() if limit is None else limit
    url = str(os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL") or "").strip()
    token = str(
        os.environ.get("V5_MEMO_FULL_RAW_INDEX_TOKEN")
        or os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TOKEN")
        or ""
    ).strip()
    if not url:
        return {}
    req = urllib.request.Request(
        url,
        data=json.dumps({
            "query": query,
            "limit": limit,
            "rank_mode": "relevance",
            "cache_only": True,
            "queue_if_missing": queue_if_missing,
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds or 30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fullraw_search_hits(query: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    data = _fullraw_search_response(query, limit=limit)
    items = data.get("results") or data.get("hits") or []
    return [item for item in items if isinstance(item, dict)]


def _fullraw_response_complete(data: dict[str, Any]) -> bool:
    raw_meta = data.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else data
    raw_receipt = meta.get("shard_receipt")
    receipt = raw_receipt if isinstance(raw_receipt, dict) else meta
    try:
        shards = int(receipt.get("shards_searched") or 0)
        failed = int(receipt.get("sweep_failed_shards") or 0)
        min_shards = int(os.environ.get("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED") or 1525)
    except (TypeError, ValueError):
        return False
    return shards >= min_shards and not bool(receipt.get("partial_shard_search")) and failed == 0


def _cached_fullraw_complete_hit_count(topic: str) -> int:
    best = 0
    for query in _business_fullraw_queries(topic):
        data = _fullraw_search_response(
            query,
            limit=_business_fullraw_result_limit(),
            queue_if_missing=False,
            timeout_seconds=_business_fullraw_cache_probe_timeout_seconds(),
        )
        if not data or not _fullraw_response_complete(data):
            continue
        items = data.get("results") or data.get("hits") or []
        best = max(best, _fullraw_substantive_fact_candidates(
            query, [item for item in items if isinstance(item, dict)],
        ))
        if best >= MIN_DIRECT_SOURCES:
            break
    return best


def _rank_fullraw_queries_by_cached_receipt(queries: tuple[str, ...]) -> tuple[str, ...]:
    ranked: list[tuple[int, int, int, int, str]] = []
    for idx, query in enumerate(queries):
        data = _fullraw_search_response(
            query,
            limit=_business_fullraw_result_limit(),
            queue_if_missing=False,
            timeout_seconds=_business_fullraw_cache_probe_timeout_seconds(),
        )
        items = data.get("results") or data.get("hits") or []
        complete = bool(data and _fullraw_response_complete(data))
        complete_items = [item for item in items if isinstance(item, dict)] if complete else []
        complete_hits = len(complete_items)
        fact_candidates = (
            _fullraw_substantive_fact_candidates(query, complete_items)
            if complete else 0
        )
        rank = (
            0 if fact_candidates >= MIN_DIRECT_SOURCES else
            1 if fact_candidates else
            3 if complete_hits else
            2
        )
        ranked.append((
            rank,
            -fact_candidates,
            -complete_hits,
            idx,
            query,
        ))
    return tuple(item[-1] for item in sorted(ranked))


def _clean_paper_source_fact(paper: dict[str, Any]) -> dict[str, Any]:
    fact = paper.get("source_fact")
    if not isinstance(fact, dict):
        return paper
    cleaned = dict(fact)
    for key in ("canonical_phrase", "source_excerpt"):
        if cleaned.get(key):
            cleaned[key] = _strip_markup_text(cleaned[key])
    return paper | {"source_fact": cleaned}


def _fullraw_substantive_fact_candidates(topic: str, papers: list[dict[str, Any]]) -> int:
    count = 0
    for paper in papers:
        if publish_literature.substantive_fact_count([paper]) > 0:
            count += 1
            continue
        if _abstract_source_fact(topic, paper) is not None:
            count += 1
    return count


def _merge_fullraw_hit_text(
    papers: list[dict[str, Any]], hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        key: hit
        for hit in hits
        if (key := _fullraw_hit_key(hit))
    }
    out: list[dict[str, Any]] = []
    for paper in papers:
        hit = by_key.get(_fullraw_hit_key(paper))
        if not hit:
            out.append(paper)
            continue
        enriched = dict(paper)
        for source_key, target_key in (
            ("abstract", "abstract"),
            ("source_excerpt", "source_excerpt"),
            ("snippet", "source_excerpt"),
            ("text", "source_excerpt"),
        ):
            value = str(hit.get(source_key) or "").strip()
            if value and not enriched.get(target_key):
                enriched[target_key] = value
        out.append(enriched)
    return out


def _abstract_source_fact(topic: str, paper: dict[str, Any]) -> dict[str, Any] | None:
    title = str(paper.get("title") or paper.get("paper_title") or "").strip()
    abstract = str(
        paper.get("abstract") or paper.get("source_excerpt") or paper.get("snippet") or "",
    ).strip()
    abstract = _strip_markup_text(abstract)
    if len(abstract) < 80:
        return None
    artifact_title = title.casefold()
    if any(term in artifact_title for term in _FULLRAW_METADATA_ARTIFACT_TERMS):
        return None
    artifact_text = f"{title} {abstract}".casefold()
    topic_tokens = set(_norm_text(topic).split()) - _BROAD_SEED_TOKENS
    text_tokens = set(_norm_text(f"{title} {abstract}").split())
    if len(topic_tokens & text_tokens) < min(2, len(topic_tokens)):
        return None
    finding = _abstract_finding_sentence(abstract)
    if not finding:
        return None
    endpoint = _abstract_endpoint_phrase(topic, finding, artifact_text)
    return {
        "canonical_phrase": finding,
        "population": "firms",
        "intervention": " ".join(sorted(topic_tokens)) or _clean_topic(topic),
        "endpoint": endpoint,
        "source_tier": "fullraw_abstract",
        "source_excerpt": finding,
    }


def _fullraw_paper_lookup_ids(paper: dict[str, Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    ids: list[str] = []
    for key in ("paper_id", "id", "doi", "pmid", "openalex_id"):
        raw = str(paper.get(key) or "").strip()
        if not raw:
            continue
        candidates = [raw]
        if key == "openalex_id" and "/" in raw:
            candidates.append(raw.rstrip("/").rsplit("/", 1)[-1])
        for candidate in candidates:
            if candidate and candidate.casefold() not in seen:
                seen.add(candidate.casefold())
                ids.append(candidate)
    return tuple(ids)


def _source_fact_covers_active_topic(topic: str, domain: str, paper: dict[str, Any]) -> bool:
    if publish_literature.substantive_fact_count([paper]) <= 0:
        return False
    if not publish_literature.topic_relevant(topic, paper):
        return False
    if publish_literature._non_biomedical(domain):
        topic_tokens = set(publish_literature._topic_token_sequence(topic))
        if (
            len(topic_tokens) >= 3
            and publish_literature._topic_token_coverage(topic, paper) < len(topic_tokens)
        ):
            return False
    return True


def _pubmed_backfill_limit() -> int:
    explicit = os.environ.get("BUSINESS_SWEEP_PUBMED_ABSTRACT_BACKFILL_LIMIT")
    raw = explicit or os.environ.get("RESEARKA_FULLRAW_DOI_ABSTRACT_BACKFILL_LIMIT") or "10"
    with suppress(ValueError):
        limit = max(0, int(raw))
        return limit if explicit is not None else max(_business_fullraw_result_limit(), limit)
    return 0 if explicit is not None else _business_fullraw_result_limit()


def _fetch_pubmed_abstract(pmid: str, settings: Any) -> str:
    if not str(pmid or "").strip():
        return ""
    try:
        httpx_mod = importlib.import_module("httpx")
        source_audit = importlib.import_module("agent.source_audit")
        with httpx_mod.Client(timeout=15.0) as client:
            return str(source_audit.fetch_pubmed_abstract(
                str(pmid), client=client,
                ncbi_api_key=str(getattr(settings, "ncbi_api_key", "") or ""),
            ) or "").strip()
    except Exception:
        return ""


def _fetch_crossref_abstract(doi: str, settings: Any) -> str:
    if not str(doi or "").strip():
        return ""
    try:
        retrieval_base = importlib.import_module("agent.retrieval.base")
        params = ""
        email = str(getattr(settings, "crossref_polite_email", "") or "").strip()
        if email:
            params = "?mailto=" + urllib.parse.quote(email, safe="")
        req = urllib.request.Request(
            "https://api.crossref.org/works/"
            + urllib.parse.quote(str(doi).strip(), safe="")
            + params,
            headers={"User-Agent": "researka-v4/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        message = data.get("message") if isinstance(data, dict) else {}
        abstract = message.get("abstract") if isinstance(message, dict) else ""
        return str(retrieval_base.clean_text(abstract, limit=8000) or "").strip()
    except Exception:
        return ""


def _tier2_facts_for_paper(
    *,
    base: str,
    token: str,
    paper_id: str,
    domain: str,
    timeout: float,
    numeric_only: bool = True,
) -> list[dict[str, Any]]:
    req = urllib.request.Request(
        f"{base}/api/v1/tier2/facts/by-paper",
        data=json.dumps({
            "paper_id": paper_id,
            "limit": 5,
            "min_confidence": "medium",
            "numeric_only": numeric_only,
            "strict_audit_required": False,
            "domain": tier2_domain(domain),
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Researka-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _enrich_fullraw_papers_with_db_facts(
    topic: str, *, domain: str, papers: list[dict[str, Any]], settings: Any,
) -> list[dict[str, Any]]:
    base = str(getattr(settings, "researka_database_url", "") or "").rstrip("/")
    token = str(getattr(settings, "researka_database_token", "") or "").strip()
    try:
        timeout = max(0.5, float(os.environ.get(
            "BUSINESS_SWEEP_BY_PAPER_FACT_TIMEOUT_SECONDS", "4",
        )))
    except ValueError:
        timeout = 4.0
    backfills_remaining = _pubmed_backfill_limit()
    enriched: list[dict[str, Any]] = []
    for paper in papers:
        paper = _clean_paper_source_fact(paper)
        if _source_fact_covers_active_topic(topic, domain, paper):
            enriched.append(paper)
            continue
        replacement = paper
        if base and token:
            numeric_modes = (
                (True, False)
                if publish_literature._non_biomedical(domain)
                else (True,)
            )
            lookup_ids = _fullraw_paper_lookup_ids(paper)
            for numeric_only in numeric_modes:
                for paper_id in lookup_ids:
                    rows = _tier2_facts_for_paper(
                        base=base,
                        token=token,
                        paper_id=paper_id,
                        domain=domain,
                        timeout=timeout,
                        numeric_only=numeric_only,
                    )
                    for row in rows:
                        candidate = paper | {
                            "id": publish_literature.paper_key(paper, paper_id),
                            "source_fact": publish_literature.source_fact(row),
                        }
                        if (
                            publish_literature.substantive_fact_count([candidate]) > 0
                            and publish_literature.topic_relevant(topic, candidate)
                        ):
                            replacement = candidate
                            break
                    if replacement is not paper:
                        break
                if replacement is not paper:
                    break
        if replacement is paper:
            if (
                backfills_remaining > 0
                and not str(paper.get("abstract") or paper.get("source_excerpt") or "").strip()
            ):
                pmid = str(paper.get("pmid") or "").strip()
                doi = str(paper.get("doi") or "").strip()
                abstract = _fetch_pubmed_abstract(pmid, settings) if pmid else ""
                if not abstract and doi:
                    abstract = _fetch_crossref_abstract(doi, settings)
                if pmid or doi:
                    backfills_remaining -= 1
                if abstract:
                    paper = paper | {"abstract": abstract}
            abstract_fact = _abstract_source_fact(topic, paper)
            if abstract_fact is not None:
                replacement = paper | {
                    "id": publish_literature.paper_key(paper, _fullraw_hit_key(paper)),
                    "source_fact": abstract_fact,
                }
        enriched.append(replacement)
    return enriched


def _seed_topic_variants(topic: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for query in expand_topic_queries(topic, max_queries=8):
        slug = "_".join(query.replace("-", " ").replace("/", " ").split())
        if not slug or slug in seen or slug.endswith(_NON_BUSINESS_QUERY_SUFFIXES):
            continue
        if out and not _variant_keeps_seed_intent(topic, slug):
            continue
        seen.add(slug)
        out.append(slug)
    return tuple(out)


def _derived_seed_topic_variants(topic: str) -> tuple[str, ...]:
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", topic.replace("-", "_").lower())
        if token
    ]
    if len(tokens) < 2:
        return ()
    core = [
        token for token in tokens
        if token not in _BROAD_SEED_TOKENS
        and token not in _BUSINESS_REPLACEABLE_OUTCOME_TOKENS
    ]
    if len(core) < 2:
        core = [
            token for token in tokens
            if token not in _BUSINESS_REPLACEABLE_OUTCOME_TOKENS
        ]
    if len(core) < 2:
        return ()
    out: list[str] = []
    seen = {topic}
    for outcome in _BUSINESS_DERIVED_OUTCOME_TOKENS:
        slug = "_".join([*core, outcome])
        if slug in seen or slug == topic or slug.endswith(_NON_BUSINESS_QUERY_SUFFIXES):
            continue
        seen.add(slug)
        out.append(slug)
    return tuple(out)


def _seed_topics(seed_path: Path, *, limit: int) -> list[str]:
    data = tomllib.loads(seed_path.read_text(encoding="utf-8"))
    seeds = data.get("seeds", {})
    topics = seeds.get("topics", []) if isinstance(seeds, dict) else []
    if not isinstance(topics, list):
        return []
    try:
        effective_limit = max(limit, int(seeds.get("derived_topic_limit") or 0))
    except (TypeError, ValueError, AttributeError):
        effective_limit = limit
    base_ranked: list[tuple[int, int, str]] = []
    variant_ranked: list[tuple[int, int, str]] = []
    derived_ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(topics):
        for offset, topic in enumerate(_seed_topic_variants(str(raw).strip())):
            if topic in seen:
                continue
            seen.add(topic)
            tokens = {
                token for token in topic.replace("-", "_").split("_")
                if token and token not in _BROAD_SEED_TOKENS
            }
            row = (-len(tokens), idx * 10 + offset, topic)
            if offset == 0:
                base_ranked.append(row)
            else:
                variant_ranked.append(row)
        for offset, topic in enumerate(_derived_seed_topic_variants(str(raw).strip())):
            if topic in seen:
                continue
            seen.add(topic)
            tokens = {
                token for token in topic.replace("-", "_").split("_")
                if token and token not in _BROAD_SEED_TOKENS
            }
            derived_ranked.append((-len(tokens), idx * 10 + offset, topic))
    ordered = [topic for *_rank, topic in sorted(base_ranked)]
    ordered.extend(topic for *_rank, topic in sorted(variant_ranked))
    ordered.extend(topic for *_rank, topic in sorted(derived_ranked))
    return ordered[:effective_limit]


def _diagnostic_rank(
    runs_root: Path, domain: str, topic: str, idx: int,
) -> tuple[int, int, int, int, int]:
    data = read_json(runs_root / "_business_diagnostics" / f"{domain}-{topic}.json", {})
    if not isinstance(data, dict):
        data = {}

    def count(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    clusters = data.get("top_clusters") or []
    top_sources = max(
        (count(cluster.get("source_count")) for cluster in clusters if isinstance(cluster, dict)),
        default=0,
    )
    raw = count(data.get("raw_fact_count"))
    a_core = count(data.get("a_core_fact_count"))
    trace = data.get("retrieval_trace")
    fullraw = trace.get("fullraw") if isinstance(trace, dict) else {}
    if not isinstance(fullraw, dict):
        fullraw = {}
    status = str(fullraw.get("status") or "")
    fullraw_fact_count = count(fullraw.get("fact_source_count"))
    cached_fact_count = 0
    cached_paper_count = 0
    discovery = read_json(
        runs_root / "_topics_discovery"
        / f"business_sweep_fullraw.{domain}.{topic}.json",
        {},
    )
    if isinstance(discovery, dict):
        rows = discovery.get("all")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            cached_fact_count = count(rows[0].get("fact_source_count"))
            cached_paper_count = count(rows[0].get("paper_count"))
            if not fullraw_fact_count:
                fullraw_fact_count = cached_fact_count
    fullraw_pending = (
        str(fullraw.get("async_status") or "") in {"queued", "running"}
        or status in {"async_queued", "async_running"}
        or fullraw.get("partial_shard_search") is True
    )
    source_rich = top_sources >= MIN_DIRECT_SOURCES or a_core >= MIN_DIRECT_SOURCES
    source_literature_ready = (
        status == "complete" and fullraw_fact_count >= MIN_DIRECT_SOURCES
    )
    if source_literature_ready:
        return (0, -fullraw_fact_count, -top_sources, -a_core, idx)
    cached_receipt_reusable = (
        cached_paper_count >= MIN_DIRECT_SOURCES
        and cached_fact_count > 0
    )
    if cached_receipt_reusable:
        return (0, -fullraw_fact_count, -top_sources, -a_core, idx)
    if fullraw_pending and fullraw_fact_count > 0:
        return (1, -fullraw_fact_count, -top_sources, -a_core, idx)
    if fullraw_fact_count > 0:
        return (1, -fullraw_fact_count, -top_sources, -a_core, idx)
    if source_rich or fullraw_pending:
        return (0, -top_sources, -a_core, -raw, idx)
    service_busy = status in {
        "busy", "health_unavailable", "inflight_saturated",
        "queue_saturated", "async_queue_saturated",
    }
    if service_busy:
        return (2, -top_sources, -a_core, -raw, idx)
    reprocessable_complete = (
        status == "complete"
        and not source_rich
        and (raw > 0 or fullraw_fact_count > 0)
    )
    if reprocessable_complete:
        return (0, -fullraw_fact_count, -top_sources, -a_core, idx)
    insufficient_fullraw_facts = (
        status == "complete"
        and fullraw_fact_count < MIN_DIRECT_SOURCES
        and not source_rich
    )
    if insufficient_fullraw_facts:
        return (3, -fullraw_fact_count, -top_sources, -a_core, idx)
    weak_complete = status == "complete" and raw == 0 and not source_rich
    if weak_complete:
        return (2, -top_sources, -a_core, -raw, idx)
    bad_empty = int(
        raw == 0
        and not fullraw_pending
        and (
            status in {
                "complete_no_hits", "failed", "incomplete_receipt",
                "no_hits", "not_configured",
            }
        )
    )
    return (4 if bad_empty else 1, -top_sources, -a_core, -raw, idx)


def _prioritized_seed_topics(runs_root: Path, domain: str, topics: list[str]) -> list[str]:
    return [
        topic for idx, topic in sorted(
            enumerate(topics),
            key=lambda item: _diagnostic_rank(runs_root, domain, item[1], item[0]),
        )
    ]


def _selected_domains(value: str) -> tuple[str, ...]:
    if not value.strip():
        return _DOMAINS
    wanted = tuple(item.strip() for item in value.split(",") if item.strip())
    unknown = sorted(set(wanted) - set(_DOMAINS))
    if unknown:
        raise ValueError(f"unknown business sweep domain(s): {', '.join(unknown)}")
    return wanted


def _topic_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _source_lit_topic_key_variants(value: Any) -> set[str]:
    topic = str(value or "").strip()
    if not topic:
        return set()
    variants = [topic, *publish_cycle._source_literature_fetch_topics(topic)[1:]]
    return {key for variant in variants if (key := _topic_key(variant))}


_SOURCE_LIT_DUPLICATE_BLOCK_REASONS = frozenset({
    "duplicate_publication_bundle",
    "duplicate_published_bundle",
    "duplicate_submission_fingerprint",
    "rejected_duplicate",
})


def _source_lit_family_cooldown_days(domain: str) -> int:
    return max(
        1,
        publish_cycle._domain_alpha_memo_int(
            domain, "source_literature_family_cooldown_days", 30,
        ),
    )


def _recent_source_lit_attempt_topics(
    runs_root: Path, domain: str, reasons: frozenset[str], *, days: int = 2,
) -> set[str]:
    ledger_dir = runs_root / "_daily_ledger"
    cutoff = time.time() - (max(0, days) * 86400)
    topics: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        with suppress(OSError):
            if path.stat().st_mtime < cutoff:
                continue
        ledger = read_json(path, {})
        if not isinstance(ledger, dict):
            continue
        raw_domain = ledger.get("domain_slug") or ledger.get("domain")
        ledger_domain = (
            str(raw_domain.get("slug") or "") if isinstance(raw_domain, dict)
            else str(raw_domain or "")
        )
        if ledger_domain and ledger_domain != domain:
            continue
        attempts = [ledger.get("source_literature_fallback")]
        raw_attempts = ledger.get("source_literature_fallback_attempts")
        if isinstance(raw_attempts, list):
            attempts.extend(raw_attempts)
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            if str(attempt.get("reason") or "") not in reasons:
                continue
            topic = str(attempt.get("topic") or "").strip()
            if topic:
                topics.add(topic)
    return topics


def _recent_source_literature_blocked_topics(runs_root: Path, domain: str) -> set[str]:
    ledger_dir = runs_root / "_daily_ledger"
    submitted_path = ledger_dir / "_submitted_fingerprints.json"
    days = _source_lit_family_cooldown_days(domain)
    family_blocked = (
        publish_cycle._recently_published_topics(ledger_dir, days=days, domain=domain)
        | publish_cycle._recent_submission_topics(submitted_path, days=days, domain=domain)
        | publish_cycle._recent_negative_topics(ledger_dir, days=days, domain=domain)
        | _recent_source_lit_attempt_topics(
            runs_root, domain, _SOURCE_LIT_DUPLICATE_BLOCK_REASONS,
        )
    )
    exact_blocked = publish_cycle._recent_source_floor_topics(
        ledger_dir, days=2, domain=domain,
    )
    structurally_blocked = publish_cycle._recent_source_literature_structural_blocked_topics(
        ledger_dir, days=2, domain=domain,
    )
    repairable_keys = {
        key for topic in publish_cycle._repairable_source_literature_topics(
            runs_root, domain,
        )
        if (key := _topic_key(topic))
    }
    return {
        key for topic in structurally_blocked
        if (key := _topic_key(topic)) and key not in repairable_keys
    } | {
        key for topic in exact_blocked
        if (key := _topic_key(topic)) and key not in repairable_keys
    } | {
        key for topic in family_blocked
        if _topic_key(topic) not in repairable_keys
        for key in _source_lit_topic_key_variants(topic)
    }


def _recent_reviewer_revise_submission_topic_keys(
    runs_root: Path, domain: str,
) -> set[str]:
    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    days = int(getattr(publish_cycle, "_DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS", 30))
    cutoff = time.time() - (max(0, days) * 86400)
    data = read_json(submitted_path, [])
    if not isinstance(data, list):
        return set()
    topics: set[str] = set()
    for row in data:
        if not isinstance(row, dict) or row.get("status") != "reviewer_revise":
            continue
        raw_domain = row.get("domain_slug") or row.get("domain")
        row_domain = (
            str(raw_domain.get("slug") or "") if isinstance(raw_domain, dict)
            else str(raw_domain or "")
        )
        if row_domain and row_domain != domain:
            continue
        ts = publish_cycle._stamp_ts(row.get("date"))
        if ts is None or ts < cutoff:
            continue
        if key := _topic_key(row.get("topic")):
            topics.add(key)
    return topics


def _hard_source_literature_blocked_topic_keys(runs_root: Path, domain: str) -> set[str]:
    ledger_dir = runs_root / "_daily_ledger"
    days = _source_lit_family_cooldown_days(domain)
    hard_blocked = (
        publish_cycle._recently_published_topics(ledger_dir, days=days, domain=domain)
        | publish_cycle._recent_negative_topics(ledger_dir, days=days, domain=domain)
    )
    return {key for topic in hard_blocked for key in _source_lit_topic_key_variants(topic)}


def _cached_ready_source_literature_papers_with_topic(
    runs_root: Path, domain: str, topic: str, settings: Any,
) -> tuple[list[dict[str, Any]], str]:
    for cache_topic in _source_literature_cache_topics(topic):
        papers, _trace = _cached_fullraw_discovery_papers(runs_root, domain, cache_topic)
        if not papers:
            continue
        papers = _enrich_fullraw_papers_with_db_facts(
            topic, domain=domain, papers=papers, settings=settings,
        )
        ready, reason = _source_literature_ready_papers(topic, domain, papers)
        if reason == "ok" and _cache_alias_selected_papers_allowed(
            topic, cache_topic, ready,
        ):
            return ready, cache_topic
    return [], ""


def _cached_ready_source_literature_papers(
    runs_root: Path, domain: str, topic: str, settings: Any,
) -> list[dict[str, Any]]:
    ready, _cache_topic = _cached_ready_source_literature_papers_with_topic(
        runs_root, domain, topic, settings,
    )
    return ready


def _cached_source_literature_discovery_topics(
    runs_root: Path, domain: str, *, limit: int,
) -> list[str]:
    discovery_dir = runs_root / "_topics_discovery"
    prefix = f"business_sweep_fullraw.{domain}."
    topics: list[str] = []
    seen: set[str] = set()
    files = sorted(
        discovery_dir.glob(f"{prefix}*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in files:
        if len(topics) >= limit:
            break
        discovery = read_json(path, {})
        rows = discovery.get("all") if isinstance(discovery, dict) else None
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        if _count_int(row.get("paper_count")) < MIN_DIRECT_SOURCES:
            continue
        topic = str(row.get("topic") or "").strip()
        if not topic and path.name.startswith(prefix):
            topic = path.name[len(prefix):-5]
        key = _topic_key(topic)
        if not key or key in seen:
            continue
        seen.add(key)
        topics.append(topic)
    return topics


def _source_literature_bundle_signature(papers: list[dict[str, Any]]) -> str:
    ids: set[str] = set()
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        doi = str(paper.get("doi") or "").strip().casefold()
        pmid = str(paper.get("pmid") or "").strip()
        url = str(paper.get("url") or paper.get("source_url") or "").strip().casefold()
        key = doi or (f"pmid:{pmid}" if pmid else "") or url
        if key:
            ids.add(key)
    sorted_ids = sorted(ids)
    return (
        hashlib.sha256("|".join(sorted_ids).encode("utf-8")).hexdigest()
        if len(sorted_ids) >= 2 else ""
    )


def _submitted_source_literature_bundle_signatures(
    runs_root: Path, domain: str,
) -> set[str]:
    data = read_json(runs_root / "_daily_ledger" / "_submitted_fingerprints.json", [])
    if not isinstance(data, list):
        return set()
    signatures: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        raw_domain = row.get("domain_slug") or row.get("domain")
        row_domain = (
            str(raw_domain.get("slug") or "") if isinstance(raw_domain, dict)
            else str(raw_domain or "")
        )
        if row_domain and row_domain != domain:
            continue
        signature = str(row.get("bundle_signature") or "").strip()
        if signature:
            signatures.add(signature)
    return signatures


def _cached_pending_fullraw_completion(topic: str) -> bool:
    try:
        discovery = importlib.import_module("scripts.run_topic_discovery")
    except (ImportError, AttributeError):
        return False
    fingerprint = discovery.__dict__.get("_fullraw_query_fingerprint")
    cached = discovery.__dict__.get("_cached_fullraw_in_progress")
    if not callable(fingerprint) or not callable(cached):
        return False
    for query in _business_fullraw_queries(topic):
        key = fingerprint(query)
        if key and cached(key):
            return True
    return False


def _recent_source_literature_repair_attempt_topics(
    runs_root: Path, domain: str, *, days: int = 2,
) -> list[str]:
    ledger_dir = runs_root / "_daily_ledger"
    cutoff = time.time() - (max(0, days) * 86400)
    topics: list[str] = []
    seen: set[str] = set()
    for path in sorted(ledger_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name.startswith("_"):
            continue
        with suppress(OSError):
            if path.stat().st_mtime < cutoff:
                continue
        ledger = read_json(path, {})
        if not isinstance(ledger, dict):
            continue
        raw_domain = ledger.get("domain_slug") or ledger.get("domain")
        ledger_domain = (
            str(raw_domain.get("slug") or "") if isinstance(raw_domain, dict)
            else str(raw_domain or "")
        )
        if ledger_domain and ledger_domain != domain:
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
            topic = str(attempt.get("topic") or "").strip()
            key = _topic_key(topic)
            if reason == "duplicate_submission_fingerprint":
                if key:
                    seen.add(key)
                continue
            if not attempt.get("repair_submission"):
                continue
            if reason not in publish_cycle._SOURCE_LITERATURE_STRUCTURAL_BLOCK_REASONS:
                continue
            if not key or key in seen:
                continue
            if (
                int(attempt.get("selected_source_count") or 0) >= MIN_DIRECT_SOURCES
                and int(attempt.get("selected_source_fact_count") or 0) >= MIN_DIRECT_SOURCES
                and int(attempt.get("selected_source_identity_count") or 0) >= MIN_DIRECT_SOURCES
            ):
                seen.add(key)
                topics.append(topic)
    return topics


def _write_sweep_summary(runs_root: Path, rows: list[dict[str, Any]]) -> Path:
    out_dir = runs_root / "_business_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"results": rows}
    out_path = out_dir / "latest_sweep.json"
    write_json(out_path, payload)
    domains = sorted({
        str(row.get("domain") or "").strip()
        for row in rows
        if str(row.get("domain") or "").strip()
    })
    for domain in domains:
        write_json(
            out_dir / f"latest_sweep.{domain}.json",
            {
                "domain": domain,
                "results": [
                    row for row in rows
                    if str(row.get("domain") or "").strip() == domain
                ],
            },
        )
        _refresh_domain_queue(runs_root, domain)
    return out_path


def _refresh_domain_queue(runs_root: Path, domain: str) -> None:
    previous = publish_queue._RUNS
    publish_queue._RUNS = runs_root
    try:
        queue = publish_queue.build_queue(include_archive=False, domain=domain)
    finally:
        publish_queue._RUNS = previous
    write_json(runs_root / f"_publish_queue.{domain}.json", queue)


def _queue_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 0,
    }
    for row in rows:
        status = str(row.get("status") or "not_ready")
        if status in {"ready", "source_literature_candidate_available"}:
            counts["ready_to_publish"] += 1
        else:
            counts["not_ready"] += 1
    return counts


def _write_no_ready_ledgers(runs_root: Path, rows: list[dict[str, Any]], date: str) -> None:
    for domain in sorted({str(row.get("domain") or "") for row in rows if row.get("domain")}):
        domain_rows = [row for row in rows if row.get("domain") == domain]
        queue = read_json(runs_root / f"_publish_queue.{domain}.json", {})
        queue_counts = publish_status.queue_counts(queue if isinstance(queue, dict) else {})
        if not any(int(queue_counts.get(key) or 0) for key in _queue_counts_from_rows([])):
            queue_counts = _queue_counts_from_rows(domain_rows)
        considered = [
            {
                "topic": row.get("topic"),
                "status": row.get("status") or "not_ready",
                "domain_slug": domain,
                "blockers": row.get("blockers") or (
                    ["no_source_diverse_bundle"] if row.get("status") == "no_bundle" else []
                ),
            }
            for row in domain_rows
        ]
        reason = (
            "no_source_diverse_bundle"
            if considered and all(row.get("status") == "no_bundle" for row in domain_rows)
            else "no_ready_business_candidate"
        )
        ledger = {
            "date": date,
            "domain": load_domain_profile(domain).as_metadata(),
            "domain_slug": domain,
            "status": publish_status.CycleStatus.CANDIDATE_REFRESH_FAILED.value,
            "reason": reason,
            "submitted": 0,
            "published": 0,
            "considered": considered,
            "queue_counts": queue_counts,
            "next_action": "inspect_refresh_failure",
        }
        path = runs_root / "_daily_ledger" / f"{date}-{domain}.json"
        write_ledger(path, ledger)
        print(
            f"[business-sweep] domain={domain} "
            f"summary={json.dumps(ledger['publish_summary'], sort_keys=True)}",
            flush=True,
        )


def _sweep_end_summary(
    runs_root: Path, rows: list[dict[str, Any]], date: str,
) -> dict[str, Any]:
    domains = sorted({str(row.get("domain") or "") for row in rows if row.get("domain")})
    queue_counts = {
        "ready_to_publish": 0,
        "agent_repair_needed": 0,
        "curation_needed": 0,
        "not_ready": 0,
    }
    considered: list[dict[str, Any]] = []
    submitted = 0
    published = 0
    public_url_status: dict[str, Any] = {}
    for domain in domains:
        queue = read_json(runs_root / f"_publish_queue.{domain}.json", {})
        counts = publish_status.queue_counts(queue if isinstance(queue, dict) else {})
        if not any(int(counts.get(key) or 0) for key in queue_counts):
            counts = _queue_counts_from_rows([
                row for row in rows if str(row.get("domain") or "") == domain
            ])
        for key in queue_counts:
            queue_counts[key] += int(counts.get(key) or 0)
        public_url_status[domain] = None
    for row in rows:
        status = str(row.get("status") or "not_ready")
        blockers = row.get("blockers")
        if not isinstance(blockers, list):
            blockers = ["no_source_diverse_bundle"] if status == "no_bundle" else []
        considered.append({
            "topic": row.get("topic"),
            "status": status,
            "domain_slug": row.get("domain"),
            "blockers": blockers,
        })
        ledger = row.get("submission_ledger")
        if isinstance(ledger, dict):
            raw_summary = ledger.get("publish_summary")
            summary = (
                raw_summary if isinstance(raw_summary, dict)
                else publish_status.publish_summary(ledger)
            )
            submitted += int(summary.get("submitted") or ledger.get("submitted") or 0)
            published += int(summary.get("published") or ledger.get("published") or 0)
            domain = str(row.get("domain") or "")
            if domain:
                public_url_status[domain] = summary.get("public_url_status")
    status = (
        publish_status.CycleStatus.PUBLISHED.value if published else
        publish_status.CycleStatus.SUBMITTED_TO_RESEARKA.value if submitted else
        publish_status.CycleStatus.CANDIDATE_REFRESH_FAILED.value if considered else
        publish_status.CycleStatus.NO_FRESH_CANDIDATE.value
    )
    payload = publish_status.publish_summary({
        "date": date,
        "status": status,
        "submitted": submitted,
        "published": published,
        "considered": considered,
        "queue_counts": queue_counts,
    })
    payload["candidates_considered"] = payload["considered"]
    payload["public_url_status"] = public_url_status
    payload["domains"] = domains
    return payload


def _write_sweep_end_summary(
    runs_root: Path, rows: list[dict[str, Any]], date: str,
) -> Path:
    path = runs_root / "_daily_ledger" / "business_alpha_sweep_summary.json"
    summary = _sweep_end_summary(runs_root, rows, date)
    summary["summary_artifact"] = str(path)
    write_json(path, summary)
    print("[business-sweep] end_summary=" + json.dumps(summary, sort_keys=True), flush=True)
    return path


def _bundle_fingerprint(bundle: Any) -> str:
    return "|".join((
        str(bundle.domain),
        str(bundle.topic),
        str(bundle.result_key),
        ",".join(sorted(str(fact.get("fact_id") or "") for fact in bundle.receipts)),
    ))


def _record_consistent_pass(
    runs_root: Path, *, domain: str, topic: str, fingerprint: str,
) -> int:
    path = runs_root / "_business_diagnostics" / f"ready_consistency.{domain}.json"
    passes = 1
    stamp = dt.datetime.now(dt.UTC).isoformat()

    def mutate(rows: list[Any]) -> bool:
        nonlocal passes
        rows[:] = [row for row in rows if isinstance(row, dict)]
        for row in rows:
            if str(row.get("fingerprint") or "") != fingerprint:
                continue
            try:
                passes = int(row.get("passes") or 0) + 1
            except (TypeError, ValueError):
                passes = 1
            row.update({
                "domain": domain,
                "topic": topic,
                "fingerprint": fingerprint,
                "passes": passes,
                "updated_utc": stamp,
            })
            return True
        rows.append({
            "domain": domain,
            "topic": topic,
            "fingerprint": fingerprint,
            "passes": passes,
            "updated_utc": stamp,
        })
        return True

    update_json_list(path, mutate)
    return passes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--topics-per-domain", type=int, default=2)
    parser.add_argument("--domains", default="")
    parser.add_argument("--runs-root", type=Path, default=_RUNS)
    parser.add_argument(
        "--submit-after-consistent-passes",
        type=int,
        default=0,
        help="Opt-in submit guard: require the same ready bundle this many times before submit.",
    )
    parser.add_argument("--submit-date", default="")
    args = parser.parse_args()
    settings = load_settings()
    rows: list[dict[str, Any]] = []
    domains = _selected_domains(args.domains)
    for cycle in range(max(1, args.cycles)):
        for domain in domains:
            profile = load_domain_profile(domain)
            if profile.slug not in BUSINESS_DOMAINS:
                continue
            seed_pool = _seed_topics(
                profile.seed_topics_path,
                limit=max(args.topics_per_domain, args.topics_per_domain * 8),
            )
            priority_source_lit_topics = list(
                publish_cycle._priority_source_literature_repair_decisions(
                    args.runs_root, domain, limit=max(args.topics_per_domain, 3),
                )
            )
            repairable_source_lit_topics = publish_cycle._repairable_source_literature_topics(
                args.runs_root, domain, limit=max(args.topics_per_domain, 3),
            )
            fallback_repair_topics = _recent_source_literature_repair_attempt_topics(
                args.runs_root, domain,
            )
            pending_source_lit_topic_keys = {
                key
                for topic in publish_cycle._pending_source_literature_topics(
                    args.runs_root / "_daily_ledger",
                    domain,
                )
                for key in _source_lit_topic_key_variants(topic)
            }
            recent_submission_topic_keys = {
                key
                for topic in publish_cycle._recent_submission_topics(
                    args.runs_root / "_daily_ledger" / "_submitted_fingerprints.json",
                    days=int(
                        getattr(
                            publish_cycle,
                            "_DEFAULT_PUBLISHED_TOPIC_COOLDOWN_DAYS",
                            30,
                        ),
                    ),
                    domain=domain,
                )
                for key in _source_lit_topic_key_variants(topic)
            }
            soft_source_lit_repair_keys = {
                _topic_key(topic)
                for topic in (
                    publish_cycle._recent_source_floor_topics(
                        args.runs_root / "_daily_ledger",
                        days=2,
                        domain=domain,
                        source_literature_only=True,
                    )
                    | publish_cycle._recent_source_literature_structural_blocked_topics(
                        args.runs_root / "_daily_ledger",
                        days=2,
                        domain=domain,
                    )
                )
                if _topic_key(topic)
            }
            reviewer_revise_topic_keys = _recent_reviewer_revise_submission_topic_keys(
                args.runs_root, domain,
            )
            repairable_source_lit_topics = list(dict.fromkeys([
                *priority_source_lit_topics,
                *repairable_source_lit_topics,
                *fallback_repair_topics,
            ]))
            repairable_source_lit_topics = [
                topic for topic in repairable_source_lit_topics
                if _topic_key(topic) not in pending_source_lit_topic_keys
            ]
            seed_pool = list(dict.fromkeys([*repairable_source_lit_topics, *seed_pool]))
            blocked_topic_keys = _recent_source_literature_blocked_topics(
                args.runs_root, domain,
            )
            hard_blocked_topic_keys = _hard_source_literature_blocked_topic_keys(
                args.runs_root, domain,
            )
            submitted_source_lit_bundle_signatures = (
                _submitted_source_literature_bundle_signatures(args.runs_root, domain)
            )
            repairable_source_lit_topic_keys = {
                _topic_key(topic) for topic in repairable_source_lit_topics
            }
            cached_ready_source_lit: dict[str, list[dict[str, Any]]] = {}
            duplicate_cached_source_lit_keys: set[str] = set()
            cached_pending_source_lit: set[str] = set()
            for seed_topic in seed_pool:
                seed_key = _topic_key(seed_topic)
                if (
                    seed_key in hard_blocked_topic_keys
                    or (
                        seed_key not in blocked_topic_keys
                        and seed_key not in repairable_source_lit_topic_keys
                    )
                ):
                    continue
                soft_repair = (
                    (
                        seed_key in soft_source_lit_repair_keys
                        or seed_key in reviewer_revise_topic_keys
                    )
                    and seed_key not in pending_source_lit_topic_keys
                )
                if seed_topic not in priority_source_lit_topics and not soft_repair:
                    continue
                ready_papers = _cached_ready_source_literature_papers(
                    args.runs_root, domain, seed_topic, settings,
                )
                if len(ready_papers) >= MIN_DIRECT_SOURCES:
                    ready_signature = _source_literature_bundle_signature(ready_papers)
                    if ready_signature in submitted_source_lit_bundle_signatures:
                        duplicate_cached_source_lit_keys.add(seed_key)
                    else:
                        cached_ready_source_lit[seed_topic] = ready_papers
                elif (
                    soft_repair
                    and seed_key not in recent_submission_topic_keys
                    and _cached_pending_fullraw_completion(seed_topic)
                ):
                    cached_pending_source_lit.add(seed_topic)
            if cached_ready_source_lit or cached_pending_source_lit:
                blocked_topic_keys -= {
                    _topic_key(topic) for topic in cached_ready_source_lit
                } | {
                    _topic_key(topic) for topic in cached_pending_source_lit
                }
                repairable_source_lit_topics = list(dict.fromkeys([
                    *cached_ready_source_lit,
                    *cached_pending_source_lit,
                    *repairable_source_lit_topics,
                ]))
                seed_pool = list(dict.fromkeys([
                    *cached_ready_source_lit,
                    *cached_pending_source_lit,
                    *seed_pool,
                ]))
            prioritized_topics = _prioritized_seed_topics(
                args.runs_root, domain, seed_pool,
            )
            selected_topics: list[str] = []
            skipped_recent: list[str] = []
            fresh_topics: list[str] = []
            for seed_topic in prioritized_topics:
                seed_key = _topic_key(seed_topic)
                if seed_key in blocked_topic_keys or seed_key in pending_source_lit_topic_keys:
                    skipped_recent.append(seed_topic)
                    continue
                fresh_topics.append(seed_topic)
            repairable_source_lit_set = set(repairable_source_lit_topics)
            priority_source_lit_set = set(priority_source_lit_topics)
            cached_ready_source_lit_set = set(cached_ready_source_lit)
            cached_pending_source_lit_set = set(cached_pending_source_lit)
            repairable_fresh_topics = [
                topic for topic in repairable_source_lit_topics
                if topic in fresh_topics
                and (
                    topic in priority_source_lit_set
                    or topic in cached_ready_source_lit_set
                    or topic in cached_pending_source_lit_set
                )
            ]
            repairable_budget_fresh_topics = {
                topic for topic in repairable_source_lit_topics
                if topic in fresh_topics
            }
            repairable_fresh_set = set(repairable_fresh_topics)
            non_repair_fresh_topics = [
                topic for topic in fresh_topics
                if topic not in repairable_fresh_set
            ]
            repairable_extra_budget = len(
                repairable_budget_fresh_topics - repairable_fresh_set,
            )
            cache_rank_limit = max(args.topics_per_domain, args.topics_per_domain * 3)
            cache_ready_scan_limit = max(cache_rank_limit, args.topics_per_domain * 8)
            cache_ready_scan_topics = [
                topic for topic in non_repair_fresh_topics
                if _topic_key(topic) not in repairable_source_lit_topic_keys
            ]
            discovery_cache_scan_topics = [
                topic for topic in _cached_source_literature_discovery_topics(
                    args.runs_root, domain, limit=cache_ready_scan_limit,
                )
                if (
                    _topic_key(topic) not in blocked_topic_keys
                    and _topic_key(topic) not in pending_source_lit_topic_keys
                    and _topic_key(topic) not in repairable_source_lit_topic_keys
                )
            ]
            cache_ready_scan_topics = list(dict.fromkeys([
                *cache_ready_scan_topics,
                *discovery_cache_scan_topics,
            ]))
            cached_ready_fresh_topics: list[str] = []
            if not repairable_fresh_topics:
                for topic in cache_ready_scan_topics[:cache_ready_scan_limit]:
                    ready_papers = _cached_ready_source_literature_papers(
                        args.runs_root, domain, topic, settings,
                    )
                    signature = _source_literature_bundle_signature(ready_papers)
                    if (
                        len(ready_papers) >= MIN_DIRECT_SOURCES
                        and signature not in submitted_source_lit_bundle_signatures
                    ):
                        cached_ready_fresh_topics.append(topic)
            cache_rank_topics = non_repair_fresh_topics[:cache_rank_limit]
            ranked_topics = _fullraw_family_diverse_topics([
                topic for _hits, _idx, topic in sorted(
                    (
                        (-_cached_fullraw_complete_hit_count(topic), idx, topic)
                        for idx, topic in enumerate(cache_rank_topics)
                    )
                )
            ] + non_repair_fresh_topics[cache_rank_limit:])
            selected_limit = max(
                args.topics_per_domain,
                args.topics_per_domain
                + len(repairable_fresh_topics)
                + repairable_extra_budget,
            )
            if not repairable_fresh_topics and not cached_ready_fresh_topics:
                selected_limit = max(selected_limit, cache_rank_limit)
            selected_topics = list(dict.fromkeys([
                *repairable_fresh_topics,
                *cached_ready_fresh_topics,
                *ranked_topics,
            ]))[:selected_limit]
            if skipped_recent:
                print(
                    "[business-sweep] skipped_recent_source_literature_topics "
                    f"{domain} topics={','.join(skipped_recent[:5])}",
                    flush=True,
                )
            source_lit_attempted_topic_keys: set[str] = set()
            deferred_cache_ready_scan_done = not repairable_fresh_topics
            topic_idx = 0
            while topic_idx < len(selected_topics):
                topic = selected_topics[topic_idx]
                topic_idx += 1
                if _topic_key(topic) in source_lit_attempted_topic_keys:
                    continue
                cached_repair_papers: list[dict[str, Any]] = []
                cached_repair_below_floor = False
                cached_repair_duplicate = (
                    _topic_key(topic) in duplicate_cached_source_lit_keys
                )
                if topic in repairable_source_lit_set:
                    if topic in cached_ready_source_lit:
                        cached_repair_papers = cached_ready_source_lit[topic]
                    else:
                        cached_repair_papers, _cached_repair_trace = (
                            _cached_fullraw_discovery_papers(args.runs_root, domain, topic)
                        )
                        cached_repair_papers = _enrich_fullraw_papers_with_db_facts(
                            topic, domain=domain, papers=cached_repair_papers,
                            settings=settings,
                        )
                        cached_repair_ready, _cached_repair_reason = (
                            _source_literature_ready_papers(
                                topic, domain, cached_repair_papers,
                            )
                        )
                        if (
                            cached_repair_ready
                            and _source_literature_bundle_signature(cached_repair_ready)
                            not in submitted_source_lit_bundle_signatures
                        ):
                            cached_repair_papers = cached_repair_ready
                        else:
                            cached_repair_duplicate = (
                                _source_literature_bundle_signature(cached_repair_ready)
                                in submitted_source_lit_bundle_signatures
                            )
                            cached_repair_below_floor = bool(cached_repair_papers)
                            cached_repair_papers = []
                    if not cached_repair_papers and not cached_repair_duplicate:
                        ready_check = _cached_ready_source_literature_papers(
                            args.runs_root, domain, topic, settings,
                        )
                        cached_repair_duplicate = (
                            len(ready_check) >= MIN_DIRECT_SOURCES
                            and _source_literature_bundle_signature(ready_check)
                            in submitted_source_lit_bundle_signatures
                        )
                    if cached_repair_duplicate:
                        source_lit_attempted_topic_keys.add(_topic_key(topic))
                        continue
                source_lit_repair_kwargs: dict[str, Any] = {}
                if cached_repair_papers:
                    source_lit_repair_kwargs["source_literature_forced_papers"] = {
                        topic: cached_repair_papers,
                    }
                elif (
                    topic in priority_source_lit_set
                    and not cached_repair_below_floor
                    and not cached_repair_duplicate
                ):
                    source_lit_repair_kwargs["source_literature_priority_topics"] = [topic]
                if source_lit_repair_kwargs and args.submit_after_consistent_passes > 0:
                    repair_row: dict[str, Any] = {
                        "cycle": cycle + 1,
                        "domain": domain,
                        "domain_slug": domain,
                        "topic": topic,
                        "ready": True,
                        "status": "source_literature_repair_candidate",
                    }
                    rows.append(repair_row)
                    if profile.dry_run_only:
                        repair_row["status"] = "submit_blocked_domain_dry_run_only"
                        _write_sweep_summary(args.runs_root, rows)
                        _write_sweep_end_summary(
                            args.runs_root,
                            rows,
                            args.submit_date or dt.datetime.now(dt.UTC).strftime(
                                "%Y-%m-%dT%H-%M-%SZ",
                            ),
                        )
                        print(
                            "[business-sweep] submit_blocked_domain_dry_run_only "
                            f"{domain} {topic} via_source_literature_repair",
                            file=sys.stderr,
                            flush=True,
                        )
                        return 2
                    ledger = run_cycle(
                        runs_root=args.runs_root,
                        date=args.submit_date
                        or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                        domain=domain,
                        submit=True,
                        refresh_candidates=False,
                        **source_lit_repair_kwargs,
                    )
                    repair_row["status"] = str(ledger.get("status") or "submit_failed")
                    repair_row["submission_ledger"] = ledger
                    for attempt in ledger.get("source_literature_fallback_attempts") or []:
                        if isinstance(attempt, dict) and attempt.get("topic"):
                            source_lit_attempted_topic_keys.add(_topic_key(attempt["topic"]))
                    _write_sweep_summary(args.runs_root, rows)
                    _write_sweep_end_summary(
                        args.runs_root,
                        rows,
                        str(ledger.get("date") or args.submit_date)
                        or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                    )
                    if isinstance(ledger.get("publish_summary"), dict):
                        print(
                            f"[business-sweep] domain={domain} "
                            f"summary={json.dumps(ledger['publish_summary'], sort_keys=True)}",
                            flush=True,
                        )
                    print(
                        "[business-sweep] "
                        f"{repair_row['status']} {domain} {topic} via_source_literature_repair",
                        flush=True,
                    )
                    if repair_row["status"] in {
                        "no_fresh_candidate",
                        "reviewer_rejected",
                        "reviewer_revise",
                    }:
                        if not deferred_cache_ready_scan_done:
                            deferred_cache_ready_scan_done = True
                            existing_topic_keys = {
                                _topic_key(item) for item in selected_topics
                            }
                            extra_ready_topics: list[str] = []
                            for candidate_topic in (
                                cache_ready_scan_topics[:cache_ready_scan_limit]
                            ):
                                candidate_key = _topic_key(candidate_topic)
                                if (
                                    candidate_key in existing_topic_keys
                                    or candidate_key in source_lit_attempted_topic_keys
                                    or candidate_key in blocked_topic_keys
                                    or candidate_key in pending_source_lit_topic_keys
                                ):
                                    continue
                                ready_papers = _cached_ready_source_literature_papers(
                                    args.runs_root, domain, candidate_topic, settings,
                                )
                                signature = _source_literature_bundle_signature(ready_papers)
                                if (
                                    len(ready_papers) >= MIN_DIRECT_SOURCES
                                    and signature not in submitted_source_lit_bundle_signatures
                                ):
                                    extra_ready_topics.append(candidate_topic)
                                    existing_topic_keys.add(candidate_key)
                            if extra_ready_topics:
                                selected_topics[topic_idx:] = extra_ready_topics
                        continue
                    return 0 if repair_row["status"] in {
                        "submitted_to_researka", "published",
                    } else 2
                facts, trace = fetch_business_facts(topic, domain=domain, settings=settings)
                bundle = build_candidate_bundle(facts, topic=topic, domain=domain)
                row: dict[str, Any] = {
                    "cycle": cycle + 1,
                    "domain": domain,
                    "domain_slug": domain,
                    "topic": topic,
                    "facts": len(facts),
                    "trace": trace,
                    "ready": bundle is not None,
                }
                if bundle is None:
                    cached_ready_papers, cache_topic = (
                        _cached_ready_source_literature_papers_with_topic(
                            args.runs_root, domain, topic, settings,
                        )
                    )
                    if cached_ready_papers:
                        signature = _source_literature_bundle_signature(cached_ready_papers)
                        if signature in submitted_source_lit_bundle_signatures:
                            cached_ready_papers = []
                            cache_topic = ""
                    if cached_ready_papers:
                        fullraw_papers = cached_ready_papers
                        fullraw_trace = {
                            "status": "complete",
                            "source": "business_sweep_fullraw_cache",
                            "query": cache_topic or topic,
                            "paper_count": len(cached_ready_papers),
                            "fact_source_count": (
                                publish_literature.substantive_fact_count(
                                    cached_ready_papers,
                                )
                            ),
                            "candidate_fact_source_count": (
                                publish_literature.substantive_fact_count(
                                    cached_ready_papers,
                                )
                            ),
                            "source_identity_count": (
                                publish_literature.source_identity_count(
                                    cached_ready_papers,
                                    require_substantive=True,
                                )
                            ),
                        }
                        if cache_topic and cache_topic != topic:
                            fullraw_trace["requested_topic"] = topic
                            fullraw_trace["cached_alias_topic"] = cache_topic
                            fullraw_trace["cached_alias_reused"] = True
                            print(
                                "[business-sweep] source_literature_cache_alias "
                                f"{domain} requested={topic} cache={cache_topic}",
                                flush=True,
                            )
                    else:
                        fullraw_papers, fullraw_trace = _cached_fullraw_discovery_papers(
                            args.runs_root, domain, topic,
                        )
                    fullraw_from_cache = bool(fullraw_papers)
                    cached_complete_trace = (
                        dict(fullraw_trace)
                        if fullraw_from_cache and fullraw_trace.get("status") == "complete"
                        else {}
                    )
                    if not fullraw_papers:
                        fullraw_papers, fullraw_trace = _strict_fullraw_probe_papers(
                            topic, args.runs_root,
                        )
                    fullraw_papers = _enrich_fullraw_papers_with_db_facts(
                        topic, domain=domain, papers=fullraw_papers, settings=settings,
                    )
                    fact_papers = _business_fact_source_literature_papers(
                        facts, topic=topic, domain=domain,
                    )
                    if (
                        fullraw_papers
                        and publish_literature.substantive_fact_count(fact_papers)
                        < MIN_DIRECT_SOURCES
                    ):
                        source_lit_facts, source_lit_trace = fetch_business_facts(
                            topic,
                            domain=domain,
                            settings=settings,
                            numeric_only=False,
                        )
                        source_lit_fact_papers = _business_fact_source_literature_papers(
                            source_lit_facts,
                            topic=topic,
                            domain=domain,
                        )
                        if source_lit_fact_papers:
                            fact_papers = _merge_source_literature_papers(
                                fact_papers,
                                source_lit_fact_papers,
                            )
                            fullraw_trace["source_literature_fact_fetch_status"] = (
                                source_lit_trace.get("status")
                            )
                            fullraw_trace["source_literature_fact_fetch_count"] = len(
                                source_lit_facts,
                            )
                    if fact_papers:
                        fullraw_papers = _merge_source_literature_papers(
                            fullraw_papers, fact_papers,
                        )
                        fullraw_trace["db_fact_source_count"] = (
                            publish_literature.substantive_fact_count(fact_papers)
                        )
                        fullraw_trace["db_fact_source_identity_count"] = (
                            publish_literature.source_identity_count(
                                fact_papers, require_substantive=True,
                            )
                        )
                    if (
                        fullraw_from_cache
                        and publish_literature.substantive_fact_count(fullraw_papers)
                        < MIN_DIRECT_SOURCES
                    ):
                        cached_trace = dict(fullraw_trace)
                        cached_papers = list(fullraw_papers)
                        cached_fact_count = publish_literature.substantive_fact_count(
                            cached_papers,
                        )
                        completion_queries = _source_completion_fullraw_queries(
                            topic, cached_papers,
                        )
                        fullraw_papers, fullraw_trace = _strict_fullraw_probe_papers(
                            topic, args.runs_root,
                            queries=completion_queries or None,
                        )
                        if completion_queries:
                            fullraw_trace["source_completion_queries"] = list(
                                completion_queries,
                            )
                        fullraw_trace["cached_fact_source_count"] = cached_trace.get(
                            "fact_source_count",
                        )
                        fullraw_papers = _enrich_fullraw_papers_with_db_facts(
                            topic, domain=domain, papers=fullraw_papers, settings=settings,
                        )
                        if fact_papers:
                            fullraw_papers = _merge_source_literature_papers(
                                fullraw_papers, fact_papers,
                            )
                            fullraw_trace["db_fact_source_count"] = (
                                publish_literature.substantive_fact_count(fact_papers)
                            )
                            fullraw_trace["db_fact_source_identity_count"] = (
                                publish_literature.source_identity_count(
                                    fact_papers, require_substantive=True,
                                )
                            )
                        live_fact_count = publish_literature.substantive_fact_count(
                            fullraw_papers,
                        )
                        if cached_papers and live_fact_count < MIN_DIRECT_SOURCES:
                            merged_papers = _merge_source_literature_papers(
                                cached_papers, fullraw_papers,
                            )
                            if (
                                publish_literature.substantive_fact_count(merged_papers)
                                >= max(
                                    cached_fact_count,
                                    live_fact_count,
                                )
                            ):
                                fullraw_papers = merged_papers
                    fullraw_keys: set[str] = set()
                    for paper in fullraw_papers:
                        key = str(
                            paper.get("doi")
                            or paper.get("pmid")
                            or paper.get("paper_id")
                            or paper.get("title")
                            or ""
                        ).strip()
                        if key:
                            fullraw_keys.add(key.casefold())
                    fullraw_has_complete_receipt = (
                        fullraw_trace.get("status") == "complete"
                        and len(fullraw_keys) >= 5
                    )
                    fullraw_fact_count = publish_literature.substantive_fact_count(
                        fullraw_papers,
                    )
                    fullraw_source_identity_count = publish_literature.source_identity_count(
                        fullraw_papers,
                        require_substantive=True,
                    )
                    fullraw_trace["paper_count"] = max(
                        _count_int(fullraw_trace.get("paper_count")),
                        len(fullraw_papers),
                    )
                    fullraw_trace["fact_source_count"] = fullraw_fact_count
                    fullraw_trace["source_fact_identity_count"] = fullraw_source_identity_count
                    pre_enrichment_fact_count = _count_int(
                        fullraw_trace.get("candidate_fact_source_count"),
                    )
                    fullraw_trace["candidate_fact_source_count"] = max(
                        pre_enrichment_fact_count, fullraw_fact_count,
                    )
                    ready_papers, ready_blocker = _source_literature_ready_papers(
                        topic, domain, fullraw_papers,
                    )
                    if (
                        cached_complete_trace
                        and fullraw_trace.get("status") != "complete"
                        and ready_blocker == "ok"
                        and len(ready_papers) >= MIN_DIRECT_SOURCES
                    ):
                        live_completion_status = fullraw_trace.get("status")
                        live_completion_async_status = fullraw_trace.get("async_status")
                        live_completion_query = fullraw_trace.get("query")
                        fullraw_trace = {**fullraw_trace, **cached_complete_trace}
                        fullraw_trace["status"] = "complete"
                        fullraw_trace["source"] = (
                            "business_sweep_fullraw_cache_plus_fact_enrichment"
                        )
                        fullraw_trace["cached_complete_receipt_reused"] = True
                        fullraw_trace["live_completion_status"] = live_completion_status
                        if live_completion_async_status:
                            fullraw_trace["live_completion_async_status"] = (
                                live_completion_async_status
                            )
                        if live_completion_query:
                            fullraw_trace["live_completion_query"] = live_completion_query
                        fullraw_trace["paper_count"] = max(
                            _count_int(fullraw_trace.get("paper_count")),
                            len(fullraw_papers),
                        )
                        fullraw_trace["fact_source_count"] = fullraw_fact_count
                        fullraw_trace["source_fact_identity_count"] = (
                            fullraw_source_identity_count
                        )
                        fullraw_trace["candidate_fact_source_count"] = max(
                            _count_int(fullraw_trace.get("candidate_fact_source_count")),
                            fullraw_fact_count,
                        )
                    ready_keys = {
                        key.casefold()
                        for paper in ready_papers
                        if (key := str(
                            paper.get("doi")
                            or paper.get("pmid")
                            or paper.get("paper_id")
                            or paper.get("title")
                            or "",
                        ).strip())
                    }
                    fullraw_trace["selected_source_count"] = len(ready_papers)
                    fullraw_trace["selected_source_fact_count"] = (
                        publish_literature.substantive_fact_count(ready_papers)
                    )
                    fullraw_trace["selected_source_identity_count"] = (
                        publish_literature.source_identity_count(
                            ready_papers, require_substantive=True,
                        )
                    )
                    selected_roles = [
                        publish_literature._paper_evidence_role(paper, topic, domain)
                        for paper in ready_papers
                    ]
                    fullraw_trace["selected_source_evidence_roles"] = selected_roles
                    fullraw_trace["selected_directional_receipt_count"] = sum(
                        1 for role in selected_roles
                        if role in {
                            "directional association",
                            "directional estimate",
                            "directionally favorable",
                        }
                    )
                    fullraw_trace["selected_source_outlet_metadata_count"] = sum(
                        1 for paper in ready_papers if _source_outlet_key(paper)
                    )
                    fullraw_trace["selected_source_outlet_count"] = _source_outlet_count(
                        ready_papers,
                    )
                    fullraw_has_complete_receipt = (
                        fullraw_trace.get("status") == "complete"
                        and len(fullraw_keys) >= 5
                    )
                    trace = {**trace, "fullraw": fullraw_trace}
                    row["trace"] = trace
                    row["status"] = "no_bundle"
                    row["fullraw"] = fullraw_trace
                    row["fullraw_fact_source_count"] = fullraw_fact_count
                    diagnostics_path = write_no_bundle_diagnostics(
                        runs_root=args.runs_root,
                        domain=domain,
                        topic=topic,
                        facts=facts,
                        trace=trace,
                    )
                    row["diagnostics"] = str(diagnostics_path)
                    diagnostics = read_json(diagnostics_path, {})
                    if isinstance(diagnostics, dict):
                        row["blockers"] = no_bundle_blockers_from_diagnostics(diagnostics)
                    fullraw_ready = (
                        fullraw_has_complete_receipt
                        and ready_blocker == "ok"
                        and len(ready_papers) >= MIN_DIRECT_SOURCES
                    )
                    if fullraw_has_complete_receipt:
                        discovery_path = _write_fullraw_discovery(
                            args.runs_root,
                            domain=domain,
                            topic=topic,
                            profile=profile,
                            papers=ready_papers or fullraw_papers,
                        )
                        row["source_literature_discovery"] = str(discovery_path)
                    if fullraw_has_complete_receipt and not fullraw_ready:
                        blockers = list(row.get("blockers") or [])
                        missing = ready_blocker
                        if missing not in blockers:
                            blockers.append(missing)
                        row["blockers"] = blockers
                    if fullraw_ready:
                        row["status"] = "source_literature_candidate_available"
                        row["ready"] = True
                        row["blockers"] = []
                        fingerprint = "|".join((
                            domain,
                            topic,
                            "fullraw_source_literature",
                            ",".join(sorted(ready_keys)),
                        ))
                        submit_after = max(0, args.submit_after_consistent_passes)
                        row["candidate_fingerprint"] = fingerprint
                        row["consistent_passes"] = (
                            _record_consistent_pass(
                                args.runs_root,
                                domain=domain,
                                topic=topic,
                                fingerprint=fingerprint,
                            )
                            if submit_after else 1
                        )
                    rows.append(row)
                    print(
                        f"[business-sweep] no_bundle {domain} {topic} facts={len(facts)}",
                        flush=True,
                    )
                    if not fullraw_ready:
                        ledger_date = args.submit_date or dt.datetime.now(dt.UTC).strftime(
                            "%Y-%m-%dT%H-%M-%SZ",
                        )
                        _write_no_ready_ledgers(args.runs_root, [row], ledger_date)
                    if fullraw_ready and max(0, args.submit_after_consistent_passes):
                        if row["consistent_passes"] < args.submit_after_consistent_passes:
                            row["status"] = "source_literature_waiting_consistency"
                            _write_sweep_summary(args.runs_root, rows)
                            print(
                                "[business-sweep] source_literature_waiting_consistency "
                                f"{domain} {topic} passes={row['consistent_passes']}/"
                                f"{args.submit_after_consistent_passes}",
                                flush=True,
                            )
                            continue
                        if profile.dry_run_only:
                            row["status"] = "submit_blocked_domain_dry_run_only"
                            _write_sweep_summary(args.runs_root, rows)
                            _write_sweep_end_summary(
                                args.runs_root,
                                rows,
                                args.submit_date or dt.datetime.now(dt.UTC).strftime(
                                    "%Y-%m-%dT%H-%M-%SZ",
                                ),
                            )
                            print(
                                "[business-sweep] submit_blocked_domain_dry_run_only "
                                f"{domain} {topic} via_fullraw_source_literature",
                                file=sys.stderr,
                                flush=True,
                            )
                            return 2
                        ledger = run_cycle(
                            runs_root=args.runs_root,
                            date=args.submit_date
                            or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                            domain=domain,
                            submit=True,
                            refresh_candidates=False,
                            source_literature_forced_papers={topic: ready_papers},
                        )
                        row["status"] = str(ledger.get("status") or "submit_failed")
                        row["submission_ledger"] = ledger
                        _write_sweep_summary(args.runs_root, rows)
                        _write_sweep_end_summary(
                            args.runs_root,
                            rows,
                            str(ledger.get("date") or args.submit_date)
                            or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                        )
                        if isinstance(ledger.get("publish_summary"), dict):
                            print(
                                f"[business-sweep] domain={domain} "
                                f"summary={json.dumps(ledger['publish_summary'], sort_keys=True)}",
                                flush=True,
                            )
                        print(
                            "[business-sweep] "
                            f"{row['status']} {domain} {topic} via_fullraw_source_literature",
                            flush=True,
                        )
                        if row["status"] in {
                            "no_fresh_candidate",
                            "reviewer_rejected",
                            "reviewer_revise",
                        }:
                            continue
                        return 0 if row["status"] in {
                            "submitted_to_researka", "published",
                        } else 2
                    continue
                fingerprint = _bundle_fingerprint(bundle)
                run_dir = write_candidate_run(bundle, profile=profile, runs_root=args.runs_root)
                submit_after = max(0, args.submit_after_consistent_passes)
                consistent_passes = (
                    _record_consistent_pass(
                        args.runs_root, domain=domain, topic=topic, fingerprint=fingerprint,
                    )
                    if submit_after else 1
                )
                row["run_dir"] = str(run_dir)
                row["source_count"] = bundle.source_count
                row["candidate_fingerprint"] = fingerprint
                row["consistent_passes"] = consistent_passes
                row["status"] = "ready"
                rows.append(row)
                summary_path = _write_sweep_summary(args.runs_root, rows)
                if submit_after:
                    if consistent_passes < submit_after:
                        row["status"] = "ready_waiting_consistency"
                        _write_sweep_summary(args.runs_root, rows)
                        print(
                            "[business-sweep] ready_waiting_consistency "
                            f"{domain} {topic} passes={consistent_passes}/{submit_after}",
                            flush=True,
                        )
                        continue
                    if profile.dry_run_only:
                        row["status"] = "submit_blocked_domain_dry_run_only"
                        _write_sweep_summary(args.runs_root, rows)
                        _write_sweep_end_summary(
                            args.runs_root,
                            rows,
                            args.submit_date or dt.datetime.now(dt.UTC).strftime(
                                "%Y-%m-%dT%H-%M-%SZ",
                            ),
                        )
                        print(
                            "[business-sweep] submit_blocked_domain_dry_run_only "
                            f"{domain} {topic} passes={consistent_passes}/{submit_after}",
                            file=sys.stderr,
                            flush=True,
                        )
                        return 2
                    ledger = run_cycle(
                        runs_root=args.runs_root,
                        date=args.submit_date
                        or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                        domain=domain,
                        submit=True,
                    )
                    row["status"] = str(ledger.get("status") or "submit_failed")
                    row["submission_ledger"] = ledger
                    _write_sweep_summary(args.runs_root, rows)
                    _write_sweep_end_summary(
                        args.runs_root,
                        rows,
                        str(ledger.get("date") or args.submit_date)
                        or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
                    )
                    if isinstance(ledger.get("publish_summary"), dict):
                        print(
                            f"[business-sweep] domain={domain} "
                            f"summary={json.dumps(ledger['publish_summary'], sort_keys=True)}",
                            flush=True,
                        )
                    print(
                        f"[business-sweep] {row['status']} {domain} {topic} -> {run_dir}",
                        flush=True,
                    )
                    if row["status"] in {
                        "no_fresh_candidate",
                        "reviewer_rejected",
                        "reviewer_revise",
                    }:
                        continue
                    return 0 if row["status"] in {"submitted_to_researka", "published"} else 2
                print(f"[business-sweep] ready {domain} {topic} -> {run_dir}", flush=True)
                print(f"[business-sweep] summary={summary_path}", flush=True)
                _write_sweep_end_summary(
                    args.runs_root,
                    rows,
                    args.submit_date or dt.datetime.now(dt.UTC).strftime(
                        "%Y-%m-%dT%H-%M-%SZ",
                    ),
                )
                return 0
        if cycle + 1 < args.cycles and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    ledger_date = args.submit_date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    _write_no_ready_ledgers(args.runs_root, rows, ledger_date)
    _write_sweep_end_summary(args.runs_root, rows, ledger_date)
    summary_path = _write_sweep_summary(args.runs_root, rows)
    print(
        f"[business-sweep] no_ready_candidate summary={summary_path}",
        file=sys.stderr,
        flush=True,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
