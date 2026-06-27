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
_FULLRAW_ENV_FILE = "/etc/v5-memo/env"
_BROAD_SEED_TOKENS = frozenset({
    "business", "management", "economics", "finance", "marketing",
    "model", "performance", "effect", "effects", "outcome", "outcomes",
    "returns", "return", "research",
})
_BUSINESS_FULLRAW_FOREGROUND_SECONDS = "30"
_BUSINESS_FULLRAW_LOCK_PATH = "/tmp/researka-v4-business-fullraw.lock"
_NON_BUSINESS_QUERY_SUFFIXES = (
    "_intervention", "_supplementation", "_therapy", "_treatment",
)


def _raise_fullraw_timeout(_signum: int, _frame: Any) -> None:
    raise TimeoutError("business fullraw probe exceeded foreground budget")

def _load_fullraw_env_defaults() -> None:
    if os.environ.get("V5_MEMO_FULL_RAW_INDEX_TOKEN") or os.environ.get(
        "V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL",
    ):
        return
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
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _strict_fullraw_probe(topic: str, *, include_papers: bool = False) -> dict[str, Any]:
    _load_fullraw_env_defaults()
    if not (
        os.environ.get("V5_MEMO_FULL_RAW_INDEX_TOKEN")
        or os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL")
    ):
        return {"status": "not_configured"}
    lock_handle = None
    budget_key = "TOPIC_DISCOVERY_V5_SEARCH_BUDGET_SECONDS"
    old_budget = os.environ.get(budget_key)
    attempts_key = "TOPIC_DISCOVERY_FULLRAW_POLL_ATTEMPTS"
    old_attempts = os.environ.get(attempts_key)
    try:
        lock_path = Path(os.environ.get(
            "TOPIC_DISCOVERY_BUSINESS_FULLRAW_LOCK_PATH",
            _BUSINESS_FULLRAW_LOCK_PATH,
        ))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("a", encoding="utf-8")
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy"}
        os.environ[budget_key] = os.environ.get(
            "TOPIC_DISCOVERY_BUSINESS_FULLRAW_FOREGROUND_SECONDS",
            _BUSINESS_FULLRAW_FOREGROUND_SECONDS,
        )
        httpx_mod = importlib.import_module("httpx")
        topic_discovery_mod = importlib.import_module("agent.topic_discovery")
        discovery = importlib.import_module("scripts.run_topic_discovery")
        timeout_seconds = float(os.environ.get(
            "TOPIC_DISCOVERY_BUSINESS_FULLRAW_HTTP_TIMEOUT_SECONDS",
            os.environ.get(budget_key, _BUSINESS_FULLRAW_FOREGROUND_SECONDS),
        ))
        os.environ[attempts_key] = str(max(1, int(timeout_seconds // 2.0)))

        events = discovery.__dict__.get("_FULLRAW_PROBE_EVENTS", [])
        before = len(events)
        old_handler = signal.getsignal(signal.SIGALRM)
        old_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, _raise_fullraw_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds + max(5.0, timeout_seconds * 0.1))
        try:
            with httpx_mod.Client(timeout=timeout_seconds) as client:
                papers = discovery.__dict__["_seed_fullraw_papers"](
                    topic, client=client, limit=10,
                )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, old_handler)
            if old_timer[0] > 0.0:
                signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])
        receipt = topic_discovery_mod.__dict__.get("_FULLRAW_LAST_RECEIPT", {})
        async_sweep = topic_discovery_mod.__dict__.get("_FULLRAW_LAST_ASYNC_SWEEP", {})
        receipt_complete = bool(discovery.__dict__["_fullraw_receipt_complete"](receipt))
        events = discovery.__dict__.get("_FULLRAW_PROBE_EVENTS", [])
        event = (
            events[-1]
            if len(events) > before else {}
        )
        result = {
            "status": (
                "complete" if papers else
                "complete_no_hits" if receipt_complete else
                str(event.get("status") or "no_hits")
            ),
            "paper_count": len(papers),
            "async_status": (
                async_sweep.get("status") if isinstance(async_sweep, dict) else None
            ),
            "shards_searched": receipt.get("shards_searched") if isinstance(receipt, dict) else None,
            "partial_shard_search": (
                receipt.get("partial_shard_search") if isinstance(receipt, dict) else None
            ),
            "sweep_failed_shards": (
                receipt.get("sweep_failed_shards") if isinstance(receipt, dict) else None
            ),
            "sources_searched": receipt.get("sources_searched") if isinstance(receipt, dict) else None,
        }
        if include_papers:
            result["_papers"] = papers
        return result
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
        if lock_handle is not None:
            with suppress(OSError):
                fcntl.flock(lock_handle, fcntl.LOCK_UN)
            lock_handle.close()


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
    bad_empty = int(
        raw == 0
        and (
            str(fullraw.get("status") or "") in {
                "async_queued", "async_running", "busy", "complete_no_hits",
                "failed", "incomplete_receipt", "no_hits", "not_configured",
            }
            or str(fullraw.get("async_status") or "") in {"queued", "running"}
            or fullraw.get("partial_shard_search") is True
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


def _write_no_ready_ledgers(runs_root: Path, rows: list[dict[str, Any]], date: str) -> None:
    for domain in sorted({str(row.get("domain") or "") for row in rows if row.get("domain")}):
        domain_rows = [row for row in rows if row.get("domain") == domain]
        queue = read_json(runs_root / f"_publish_queue.{domain}.json", {})
        queue_counts = publish_status.queue_counts(queue if isinstance(queue, dict) else {})
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
                limit=max(args.topics_per_domain, args.topics_per_domain * 4),
            )
            for topic in _prioritized_seed_topics(
                args.runs_root, domain, seed_pool,
            )[:args.topics_per_domain]:
                facts, trace = fetch_business_facts(topic, domain=domain, settings=settings)
                bundle = build_candidate_bundle(facts, topic=topic, domain=domain)
                row: dict[str, Any] = {
                    "cycle": cycle + 1,
                    "domain": domain,
                    "topic": topic,
                    "facts": len(facts),
                    "trace": trace,
                    "ready": bundle is not None,
                }
                if bundle is None:
                    fullraw_trace = _strict_fullraw_probe(topic, include_papers=True)
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
                return 0
        if cycle + 1 < args.cycles and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
    summary_path = _write_sweep_summary(args.runs_root, rows)
    ledger_date = args.submit_date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    _write_no_ready_ledgers(args.runs_root, rows, ledger_date)
    print(
        f"[business-sweep] no_ready_candidate summary={summary_path}",
        file=sys.stderr,
        flush=True,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
