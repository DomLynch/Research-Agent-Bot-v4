#!/usr/bin/env python3
"""Controlled AI Results Index scale runner.

Runs the existing no-LLM evidence path for AI topics with hard caps. This is
deliberately not a daemon: operators choose the topic/time bounds explicitly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_RUNS = _ROOT / "runs"
_DEFAULT_SEEDS = _ROOT / "topic_packs" / "ai_research_discovery_seeds.toml"
_DOMAIN = "ai_research"


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    note: str
    elapsed_seconds: float


def _utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_seed_topics(path: Path = _DEFAULT_SEEDS) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    topics = data.get("seeds", {}).get("topics", [])
    return [str(topic).strip() for topic in topics if str(topic).strip()]


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _plan_topics(
    requested: list[str],
    *,
    seed_path: Path = _DEFAULT_SEEDS,
    max_topics: int,
) -> list[str]:
    topics = requested if requested else _load_seed_topics(seed_path)
    return _dedupe(topics)[:max_topics]


def _topic_build_args(py: str, topic: str, top_facts: int) -> list[str]:
    return [
        py,
        "scripts/build_topic_evidence_run.py",
        "--domain",
        _DOMAIN,
        "--topic",
        topic,
        "--top",
        str(top_facts),
        "--no-frontier",
        "--no-pico-enrich",
    ]


def _latest_run_for_topic(topic: str, runs_root: Path = _RUNS) -> Path | None:
    runs = sorted(runs_root.glob(f"{topic}-evidence-*"))
    return runs[-1] if runs else None


def _run_step(args: list[str], *, timeout: int) -> Step:
    start = time.monotonic()
    try:
        result = subprocess.run(
            args,
            cwd=_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Step(
            args[1] if len(args) > 1 else "step",
            False,
            f"{type(exc).__name__}: {exc}",
            time.monotonic() - start,
        )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    last = output.splitlines()[-1] if output else ""
    return Step(
        args[1] if len(args) > 1 else "step",
        result.returncode == 0,
        last[:240],
        time.monotonic() - start,
    )


def _write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_ROOT))
    except ValueError:
        return str(path)


def _remaining_timeout(start: float, max_seconds: int) -> int:
    remaining = max_seconds - int(time.monotonic() - start)
    return max(1, remaining)


def _run_topic(
    topic: str,
    *,
    py: str,
    top_facts: int,
    started: float,
    max_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    build_args = _topic_build_args(py, topic, top_facts)
    if dry_run:
        return {"topic": topic, "status": "planned", "commands": [build_args]}

    steps: list[Step] = []
    build = _run_step(build_args, timeout=_remaining_timeout(started, max_seconds))
    steps.append(build)
    run_dir = _latest_run_for_topic(topic)
    if build.ok and run_dir:
        for args in (
            [py, "scripts/run_opportunities_gate.py", "--run", str(run_dir)],
            [py, "scripts/build_signal_post.py", "--run", str(run_dir)],
        ):
            steps.append(
                _run_step(args, timeout=_remaining_timeout(started, max_seconds))
            )
    ok = bool(steps) and all(step.ok for step in steps)
    return {
        "topic": topic,
        "status": "ok" if ok else "failed",
        "run_dir": str(run_dir.relative_to(_ROOT)) if run_dir else "",
        "steps": [asdict(step) for step in steps],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", action="append", default=[],
                        help="AI topic slug to run; repeatable.")
    parser.add_argument("--seed-topic-file", type=Path, default=_DEFAULT_SEEDS)
    parser.add_argument("--max-topics", type=int, default=5)
    parser.add_argument("--max-seconds", type=int, default=600)
    parser.add_argument("--top-facts", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-jsonl", type=Path, default=None)
    args = parser.parse_args()

    if args.max_topics < 1 or args.max_seconds < 1 or args.top_facts < 1:
        parser.error("--max-topics, --max-seconds, and --top-facts must be >= 1")

    topics = _plan_topics(
        [str(topic).strip() for topic in args.topic],
        seed_path=args.seed_topic_file,
        max_topics=args.max_topics,
    )
    if not topics:
        parser.error("no topics selected")

    log_path = args.log_jsonl or (
        _RUNS / "_ai_results_index_scale" / f"{_utc_stamp()}.jsonl"
    )
    started = time.monotonic()
    _write_jsonl(log_path, {
        "event": "start",
        "domain": _DOMAIN,
        "topics": topics,
        "dry_run": args.dry_run,
        "max_seconds": args.max_seconds,
        "top_facts": args.top_facts,
    })

    failures = 0
    for topic in topics:
        if time.monotonic() - started >= args.max_seconds:
            _write_jsonl(log_path, {"event": "stop", "reason": "time_cap"})
            break
        row = _run_topic(
            topic,
            py=sys.executable,
            top_facts=args.top_facts,
            started=started,
            max_seconds=args.max_seconds,
            dry_run=args.dry_run,
        )
        _write_jsonl(log_path, {"event": "topic", **row})
        if row.get("status") == "failed":
            failures += 1

    if not args.dry_run:
        queue = _run_step(
            [sys.executable, "scripts/build_publish_queue.py", "--domain", _DOMAIN],
            timeout=_remaining_timeout(started, args.max_seconds),
        )
        _write_jsonl(log_path, {"event": "publish_queue", **asdict(queue)})
        if not queue.ok:
            failures += 1

    _write_jsonl(log_path, {
        "event": "finish",
        "failures": failures,
        "log_jsonl": _display_path(log_path),
    })
    print(f"[ai-results-scale] log -> {_display_path(log_path)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
