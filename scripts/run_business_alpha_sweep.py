"""Run repeated dry-run sweeps across business-family alpha lanes."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import importlib
import json
import os
import signal
import sys
import time
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.business_research import (
    BUSINESS_DOMAINS,
    build_candidate_bundle,
    fetch_business_facts,
    write_candidate_run,
)
from agent.domain_profile import load_domain_profile
from agent.settings import load_settings
from agent.topic_synonyms import expand_topic_queries
from scripts import alpha_publish_status as publish_status
from scripts import build_publish_queue as publish_queue
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
_BUSINESS_FULLRAW_FOREGROUND_SECONDS = "2400"
_BUSINESS_FULLRAW_LOCK_PATH = "/tmp/researka-v4-business-fullraw.lock"
_BUSINESS_FULLRAW_LOCK_WAIT_SECONDS = "0"
_BUSINESS_FULLRAW_BACKOFF_SECONDS = "180"
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


def _business_fullraw_priority_enabled() -> bool:
    return os.environ.get(
        "TOPIC_DISCOVERY_BUSINESS_FULLRAW_PRIORITY", "",
    ).strip().lower() in {"1", "true", "yes", "on"}


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


def _fullraw_backoff_path(runs_root: Path) -> Path:
    return runs_root / "_business_diagnostics" / "fullraw_backoff.json"


def _fullraw_backoff(runs_root: Path | None) -> dict[str, Any] | None:
    if runs_root is None:
        return None
    data = read_json(_fullraw_backoff_path(runs_root), {})
    if not isinstance(data, dict):
        return None
    try:
        age = time.time() - float(data.get("ts") or 0.0)
    except (TypeError, ValueError):
        return None
    ttl = _business_fullraw_backoff_seconds()
    if ttl <= 0 or age > ttl:
        return None
    return {
        "status": "busy",
        "reason": "fullraw_backoff",
        "previous_status": data.get("status"),
        "backoff_age_seconds": age,
        "backoff_seconds": ttl,
    }


def _record_fullraw_backoff(runs_root: Path | None, event: dict[str, Any]) -> None:
    if runs_root is None or not _fullraw_busy_event(event):
        return
    write_json(_fullraw_backoff_path(runs_root), {
        "ts": time.time(),
        "status": event.get("status"),
        "async_status": event.get("async_status"),
        "shards_searched": event.get("shards_searched"),
        "partial_shard_search": event.get("partial_shard_search"),
    })


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


def _strict_fullraw_probe(
    topic: str, *, include_papers: bool = False, runs_root: Path | None = None,
) -> dict[str, Any]:
    _load_fullraw_env_defaults()
    if not (
        os.environ.get("V5_MEMO_FULL_RAW_INDEX_TOKEN")
        or os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL")
    ):
        return {"status": "not_configured"}
    backoff = _fullraw_backoff(runs_root)
    if backoff:
        return backoff
    lock_handle = None
    budget_key = "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"
    old_budget = os.environ.get(budget_key)
    attempts_key = "TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"
    old_attempts = os.environ.get(attempts_key)
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
        os.environ[attempts_key] = str(max(1, int(timeout_seconds // 2.0)))
        if _business_fullraw_priority_enabled():
            os.environ[priority_key] = "1"

        old_handler = signal.getsignal(signal.SIGALRM)
        old_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, _raise_fullraw_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds + max(5.0, timeout_seconds * 0.1))
        try:
            with httpx_mod.Client(timeout=timeout_seconds) as client:
                result: dict[str, Any] = {}
                attempted: list[str] = []
                for query in _business_fullraw_queries(topic):
                    attempted.append(query)
                    events = discovery.__dict__.get("_FULLRAW_PROBE_EVENTS", [])
                    before = len(events)
                    papers = discovery.__dict__["_seed_fullraw_papers"](
                        query, client=client, limit=10,
                    )
                    receipt = topic_discovery_mod.__dict__.get("_FULLRAW_LAST_RECEIPT", {})
                    async_sweep = topic_discovery_mod.__dict__.get("_FULLRAW_LAST_ASYNC_SWEEP", {})
                    receipt_complete = bool(discovery.__dict__["_fullraw_receipt_complete"](receipt))
                    events = discovery.__dict__.get("_FULLRAW_PROBE_EVENTS", [])
                    event = events[-1] if len(events) > before else {}
                    status = (
                        "complete" if papers else
                        "complete_no_hits" if receipt_complete else
                        str(event.get("status") or "no_hits")
                    )
                    result = {
                        "status": status,
                        "query": query,
                        "attempted_queries": list(attempted),
                        "paper_count": len(papers),
                        "async_status": (
                            async_sweep.get("status") if isinstance(async_sweep, dict) else None
                        ) or event.get("async_status"),
                        "shards_searched": (
                            receipt.get("shards_searched") if isinstance(receipt, dict) else None
                        ) or event.get("shards_searched"),
                        "partial_shard_search": (
                            receipt.get("partial_shard_search") if isinstance(receipt, dict) else None
                        ) if isinstance(receipt, dict) and "partial_shard_search" in receipt
                        else event.get("partial_shard_search"),
                        "sweep_failed_shards": (
                            receipt.get("sweep_failed_shards") if isinstance(receipt, dict) else None
                        ) if isinstance(receipt, dict) and "sweep_failed_shards" in receipt
                        else event.get("sweep_failed_shards"),
                        "sources_searched": (
                            receipt.get("sources_searched") if isinstance(receipt, dict) else None
                        ) or event.get("sources_searched"),
                        "papers_searched": (
                            receipt.get("papers_searched") if isinstance(receipt, dict) else None
                        ) or event.get("papers_searched"),
                        "papers_total": (
                            receipt.get("papers_total") if isinstance(receipt, dict) else None
                        ) or event.get("papers_total"),
                        "result_count_returned": (
                            receipt.get("result_count_returned") if isinstance(receipt, dict) else None
                        ) or event.get("result_count_returned"),
                        "result_count_unique": (
                            receipt.get("result_count_unique") if isinstance(receipt, dict) else None
                        ) or event.get("result_count_unique"),
                        "result_citation_diversity": (
                            receipt.get("result_citation_diversity")
                            if isinstance(receipt, dict) else None
                        ) or event.get("result_citation_diversity"),
                    }
                    if include_papers:
                        result["_papers"] = papers
                    _record_fullraw_backoff(runs_root, result)
                    if len(papers) >= 5 or status not in {
                        "complete", "complete_no_hits", "no_hits",
                    }:
                        break
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
        if old_attempts is None:
            os.environ.pop(attempts_key, None)
        else:
            os.environ[attempts_key] = old_attempts
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
        if query and key not in seen:
            seen.add(key)
            out.append(query)

    bases = tuple(expand_topic_queries(topic, max_queries=3))
    for raw in bases[:1]:
        add(raw)
    for term in tuple(alpha_terms)[:2]:
        if out:
            add(f"{out[0]} {term}")
    for raw in bases[1:]:
        add(raw)
    return tuple(out[:4])


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
            "fact_source_count": len(unique),
            "source_papers": unique,
        }],
    }
    out_path = out_dir / f"business_sweep_fullraw.{domain}.{topic}.json"
    write_json(out_path, payload)
    return out_path


def _seed_topic_variants(topic: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for query in expand_topic_queries(topic, max_queries=8):
        slug = "_".join(query.replace("-", " ").replace("/", " ").split())
        if not slug or slug in seen or slug.endswith(_NON_BUSINESS_QUERY_SUFFIXES):
            continue
        seen.add(slug)
        out.append(slug)
    return tuple(out)


def _seed_topics(seed_path: Path, *, limit: int) -> list[str]:
    data = tomllib.loads(seed_path.read_text(encoding="utf-8"))
    topics = data.get("seeds", {}).get("topics", [])
    if not isinstance(topics, list):
        return []
    base_ranked: list[tuple[int, int, str]] = []
    variant_ranked: list[tuple[int, int, str]] = []
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
    ordered = [topic for *_rank, topic in sorted(base_ranked)]
    ordered.extend(topic for *_rank, topic in sorted(variant_ranked))
    return ordered[:limit]


def _diagnostic_rank(
    runs_root: Path, domain: str, topic: str, idx: int,
) -> tuple[int, int, int, int, int]:
    data = read_json(runs_root / "_business_diagnostics" / f"{domain}-{topic}.json", {})
    if not isinstance(data, dict):
        return (0, 0, 0, 0, idx)

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
    fullraw_pending = (
        str(fullraw.get("async_status") or "") in {"queued", "running"}
        or str(fullraw.get("status") or "") in {
            "health_unavailable", "inflight_saturated",
        }
        or fullraw.get("partial_shard_search") is True
    )
    bad_empty = int(
        raw == 0
        and not fullraw_pending
        and (
            str(fullraw.get("status") or "") in {
                "async_queued", "async_running", "busy", "complete_no_hits",
                "failed", "incomplete_receipt", "no_hits", "not_configured",
            }
        )
    )
    return (bad_empty, -top_sources, -a_core, -raw, idx)


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
            for topic in _prioritized_seed_topics(
                args.runs_root, domain, seed_pool,
            )[:args.topics_per_domain]:
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
                    fullraw_trace = _strict_fullraw_probe(
                        topic, include_papers=True, runs_root=args.runs_root,
                    )
                    fullraw_papers = [
                        paper for paper in fullraw_trace.pop("_papers", [])
                        if isinstance(paper, dict)
                    ]
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
                    trace = {**trace, "fullraw": fullraw_trace}
                    row["trace"] = trace
                    row["status"] = "no_bundle"
                    row["fullraw"] = fullraw_trace
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
                        fullraw_trace.get("status") == "complete"
                        and len(fullraw_keys) >= 5
                    )
                    if fullraw_ready:
                        discovery_path = _write_fullraw_discovery(
                            args.runs_root,
                            domain=domain,
                            topic=topic,
                            profile=profile,
                            papers=fullraw_papers,
                        )
                        row["source_literature_discovery"] = str(discovery_path)
                        row["status"] = "source_literature_candidate_available"
                        fingerprint = "|".join((
                            domain,
                            topic,
                            "fullraw_source_literature",
                            ",".join(sorted(fullraw_keys)),
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
                            refresh_candidates=True,
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
                        if row["status"] == "no_fresh_candidate":
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
                    if row["status"] == "no_fresh_candidate":
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
