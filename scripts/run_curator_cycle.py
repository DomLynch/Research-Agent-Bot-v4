"""Sprint 65 — one-command autonomous curator cycle.

Pipeline (all existing scripts, orchestrated):
  1. run_topic_discovery.py        — velocity-ranked candidates
  2. Cooldown filter               — drop topics signal-posted in
                                     the last `--cooldown-hours`
  3. For each remaining top-N:
     a. build_topic_evidence_run.py --with-editorial
     b. run_opportunities_gate.py
     c. build_signal_post.py
  4. Emit runs/_curator_cycles/<utc>.{json,md} summary

Cron-friendly: bounded by --top + --cooldown-hours, exits cleanly.
Universal — no domain literals; topics come from
topic_packs/discovery_seeds.toml.

Usage:
  python scripts/run_curator_cycle.py                     # top 5
  python scripts/run_curator_cycle.py --top 10
  python scripts/run_curator_cycle.py --cooldown-hours 6  # rerun sooner
  python scripts/run_curator_cycle.py --dry-run           # show plan, don't run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from daily_alpha_publish_cycle import (  # noqa: E402
    _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES,
    _DEFAULT_MIN_SUBMIT_SOURCES,
    _direct_source_count,
    _run_subprocess,
    _source_count,
)

from agent.domain_profile import domain_choices, domain_slug, load_domain_profile  # noqa: E402
from agent.publish_tier import _FUNCTION_WORDS  # noqa: E402
from agent.researka_facts import tier2_source_count  # noqa: E402
from agent.settings import load_settings  # noqa: E402
from agent.topic_discovery import (  # noqa: E402
    _MAX_TOPIC_TOKENS,
    _fetch_topic_fact_source_count,
    cap_topic_slug,
    topic_token_count,
)
from scripts import alpha_publish_io as publish_io  # noqa: E402

_RUNS = _ROOT / "runs"
_CYCLES_DIR = _RUNS / "_curator_cycles"
# Tier-2 supply is slow to probe (~40-90s) and occasionally returns a transient
# empty; cache successful counts so a topic is probed slowly once, then read
# instantly and reliably. Runtime state — gitignored, regenerated per cycle.
_TIER2_SUPPLY_CACHE = _RUNS / "_tier2_supply_cache.json"
_TIER2_SUPPLY_TTL_SECONDS = 86_400.0
_DEFAULT_PIPELINE_TOP_N = max(5, _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES * 2)


def _read_tier2_cache() -> dict[str, Any]:
    data = publish_io.read_json(_TIER2_SUPPLY_CACHE, {})
    return data if isinstance(data, dict) else {}


def _write_tier2_cache(cache: dict[str, Any]) -> None:
    with suppress(OSError):
        publish_io.write_json(_TIER2_SUPPLY_CACHE, cache)


def _cached_tier2_supply(
    key: str, *, cache: dict[str, Any], now: float, probe: Callable[[], int],
) -> int:
    """Tier-2 source count with a 24h cache. Cache only successful (>0) probes
    so a transient empty from the slow endpoint retries next cycle, while a
    warmed topic is read instantly. Mutates and persists ``cache`` on a miss."""
    entry = cache.get(key)
    if (isinstance(entry, dict)
            and now - float(entry.get("ts", 0.0)) < _TIER2_SUPPLY_TTL_SECONDS):
        return int(entry.get("count", 0))
    count = probe()
    if count > 0:
        cache[key] = {"count": count, "ts": now}
        _write_tier2_cache(cache)
    return count


def _write_cycle_json(path: Path, payload: dict[str, Any]) -> None:
    publish_io.write_json(path, payload)
_DISCOVERY_TIMEOUT_SECONDS = 1800
# Cheap pre-build gate: a topic whose discovery probe finds fewer bindable
# sources than this can never clear the publish source floor, so a full
# evidence build is wasted. Derived from the floor (margin for probe
# under-counting), not a domain literal. Sub-floor topics are never built —
# not even as a last-resort fallback — which stops the cycle burning ~an hour
# on dozens of zero/low-source dead candidates.
_PREBUILD_MIN_SOURCE_FLOOR = max(1, _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES - 2)
_STOP_ON_READY_DISCOVERY_FLOOR = 20
_MAX_CHILD_RERUNS_PER_PARENT = 2
_MAX_CHILD_RERUN_DEPTH = 1
# Discovery emits near-duplicate phrasings of one topic (token-shuffled breadth
# claims). Past this token-overlap a new candidate is the same topic re-worded —
# planning it just burns a second submission slot on a guaranteed duplicate.
_NEAR_DUP_JACCARD = 0.8


def _topic_token_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _discovery_top_for_plan(
    top: int, *, stop_on_ready: bool, excluded_count: int,
) -> int:
    """Over-fetch candidates before cooldown/exclusion filters in submit mode."""
    requested = max(1, top)
    if not stop_on_ready:
        return max(requested, _STOP_ON_READY_DISCOVERY_FLOOR)
    return max(requested + max(0, excluded_count), _STOP_ON_READY_DISCOVERY_FLOOR)


def _same_domain(left: str, right: str) -> bool:
    return left.removesuffix("_research") == right.removesuffix("_research")


def _add_discovery_counts(
    rows: list[dict[str, Any]], counts: dict[str, tuple[int, int]],
) -> None:
    for row in rows:
        topic = str(row.get("topic") or "").strip()
        if not topic:
            continue
        try:
            pair = (
                int(row.get("fact_source_count") or 0),
                int(row.get("paper_count") or 0),
            )
        except (TypeError, ValueError):
            continue
        counts.setdefault(topic, pair)
        counts.setdefault(cap_topic_slug(topic), pair)


def _priority_discovery_counts(
    topics: list[str], *, domain: str,
) -> dict[str, tuple[int, int]]:
    wanted = set(topics) | {cap_topic_slug(topic) for topic in topics}
    counts: dict[str, tuple[int, int]] = {}
    _add_discovery_counts(
        _read_discovery_top(_RUNS / "_topics_discovery", domain=domain), counts,
    )
    if wanted <= set(counts):
        return counts
    paths = sorted(
        (_RUNS / "_topics_discovery").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths[:20]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        record_domain = domain_slug(data.get("domain"))
        if record_domain and not _same_domain(record_domain, domain):
            continue
        rows = data.get("all") or data.get("top") or []
        if isinstance(rows, list):
            _add_discovery_counts([row for row in rows if isinstance(row, dict)], counts)
        if wanted <= set(counts):
            break
    return counts


def _priority_ranked_topics(topics: list[str], *, domain: str = "longevity") -> list[dict[str, Any]]:
    if not topics:
        return []
    discovery_counts = _priority_discovery_counts(topics, domain=domain)
    source_counts: dict[str, int] = {}
    try:
        settings = load_settings()
        with httpx.Client() as client:
            for topic in topics:
                if discovery_counts.get(topic, (0, 0))[0] > 0:
                    source_counts[topic] = discovery_counts[topic][0]
                    continue
                try:
                    source_counts[topic] = _fetch_topic_fact_source_count(
                        topic, client=client, settings=settings, domain=domain,
                    )
                except (OSError, httpx.HTTPError, ValueError):
                    source_counts[topic] = discovery_counts.get(topic, (0, 0))[0]
    except (OSError, httpx.HTTPError, ValueError):
        source_counts = {topic: discovery_counts.get(topic, (0, 0))[0] for topic in topics}
    return [
        {
            "topic": topic,
            "velocity_score": 0.0,
            "fact_source_count": source_counts.get(topic, 0),
            "paper_count": discovery_counts.get(topic, (0, 0))[1] or (
                1 if source_counts.get(topic, 0) > 0 else 0
            ),
            "child_depth": _MAX_CHILD_RERUN_DEPTH,
            "tier2_rescue_allowed": False,
        }
        for topic in topics
    ]


@dataclass(frozen=True, slots=True)
class TopicResult:
    topic: str
    velocity: float
    status: str  # ran | skipped_cooldown | failed
    run_dir: str  # relative path under runs/, empty when skipped/failed
    signal_label: str  # alpha label or empty
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "velocity": self.velocity,
                "status": self.status, "run_dir": self.run_dir,
                "signal_label": self.signal_label, "notes": self.notes}


def _recent_signal_topics(
    runs_root: Path, cooldown_hours: float, now: dt.datetime,
) -> set[str]:
    """Topics whose newest run marker is within the cooldown window.

    Prefer signal_post.md when present; otherwise use the run folder
    mtime so partial/zero-fact runs do not immediately repeat.
    """
    if not runs_root.exists():
        return set()
    cutoff = now - dt.timedelta(hours=cooldown_hours)
    recent: set[str] = set()
    evidence_dirs = list(runs_root.iterdir())
    archive_root = runs_root / "_archive"
    if archive_root.exists():
        evidence_dirs.extend(archive_root.glob("*/*-evidence-*"))
    for run_dir in evidence_dirs:
        if not run_dir.is_dir() or "-evidence-" not in run_dir.name:
            continue
        marker = run_dir / "signal_post.md"
        if not marker.exists():
            marker = run_dir
        mtime = dt.datetime.fromtimestamp(marker.stat().st_mtime, tz=dt.UTC)
        if mtime >= cutoff:
            topic = run_dir.name.split("-evidence-")[0]
            recent.add(topic)
    return recent


def _read_discovery_top(
    out_dir: Path, *, domain: str | None = None,
) -> list[dict[str, Any]]:
    """Find the newest matching discovery JSON in runs/_topics_discovery/."""
    if not out_dir.exists():
        return []
    candidates = sorted(out_dir.glob("*.json"), reverse=True)
    if not candidates:
        return []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if domain and domain_slug(data.get("domain")) != domain:
            continue
        raw = data.get("all") or data.get("top") or []
        if not isinstance(raw, list):
            return []
        return [c for c in raw if isinstance(c, dict) and c.get("topic")]
    return []


def _newest_run_for_topic(topic: str) -> Path | None:
    """Find the newest runs/<topic>-evidence-*/ folder."""
    candidates = sorted(_RUNS.glob(f"{topic}-evidence-*"))
    return candidates[-1] if candidates else None


def _is_publish_ready(run_dir: str) -> bool:
    if not run_dir:
        return False
    try:
        verdict = json.loads((_ROOT / run_dir / "publish_verdict.json").read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if str(verdict.get("decision") or "") != "ready_to_publish":
        return False
    return bool(
        _source_count(verdict, _RUNS) >= _DEFAULT_MIN_SUBMIT_SOURCES
        and _direct_source_count(verdict, _RUNS) >= _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES
    )


def _child_topics_from_verdict(run_dir: str, seen: set[str]) -> list[str]:
    if not run_dir:
        return []
    try:
        verdict = json.loads((_ROOT / run_dir / "publish_verdict.json").read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rec = verdict.get("subtopic_recommendations")
    if not isinstance(rec, dict) or not rec.get("recommended"):
        return []
    parent = str(verdict.get("topic") or "").strip()
    # A parent that is itself an accreted child spawns no further children: across
    # cycles a prior run's child re-enters as a fresh depth-0 parent, so without a
    # token-count ceiling the slug grows unbounded into word-salad.
    if topic_token_count(parent) >= _MAX_TOPIC_TOKENS:
        return []
    out: list[str] = []
    for cluster in rec.get("clusters") or []:
        if not isinstance(cluster, dict):
            continue
        label = str(cluster.get("label") or "").strip("_")
        if not label or label == "unlabeled":
            continue
        # A child must add a content word over its parent. Labels that reduce
        # to closed-class function words ("was", "with") yield junk topics that
        # bind zero receipts, so skip them (also defends against stale verdicts
        # written before the labeller dropped function words).
        if not [
            t for t in re.findall(r"[a-z0-9]{3,}", label.lower())
            if t not in _FUNCTION_WORDS
        ]:
            continue
        child = "_".join(x for x in (parent, label) if x)
        child = cap_topic_slug("_".join(re.findall(r"[a-z0-9]+", child.lower())))
        if child and child != parent and child not in seen:
            out.append(child)
            seen.add(child)
        if len(out) >= _MAX_CHILD_RERUNS_PER_PARENT:
            break
    return out


def _run_step(
    args: list[str], step_name: str, *, timeout: int = 600,
) -> tuple[bool, str]:
    """Run a subprocess; return (ok, last_line). Never raises."""
    try:
        r = _run_subprocess(args, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"{step_name}: {type(e).__name__}: {e}"
    out = (r.stdout or "").strip().splitlines()
    last = out[-1] if out else (r.stderr or "")[:200]
    return r.returncode == 0, last


def _run_topic_pipeline(
    topic: str, velocity: float, *, with_editorial: bool, top_n: int,
    py: str, pico_enrich: bool = False, frontier_review: bool = True,
    parent_topic: str = "", domain: str = "longevity",
) -> TopicResult:
    """Run build + gate + signal_post for one topic. Returns the
    aggregate result. Each step's failure is recorded; we continue
    through to give the operator a partial output trail."""
    build_args = [
        py, "scripts/build_topic_evidence_run.py",
        "--domain", domain, "--topic", topic, "--top", str(top_n),
    ]
    if parent_topic:
        build_args.extend(["--parent-topic", parent_topic])
    if with_editorial:
        build_args.append("--with-editorial")
    if not frontier_review:
        build_args.append("--no-frontier")
    if not pico_enrich:
        build_args.append("--no-pico-enrich")
    ok, last = _run_step(build_args, "build")
    if not ok:
        return TopicResult(topic=topic, velocity=velocity, status="failed",
                            run_dir="", signal_label="",
                            notes=f"build_step: {last[:200]}")
    run_dir = _newest_run_for_topic(topic)
    if run_dir is None:
        return TopicResult(topic=topic, velocity=velocity, status="failed",
                            run_dir="", signal_label="",
                            notes="no run_dir produced by build step")
    # Sprint 68: capture downstream return codes so cron can see
    # partial failures (gate or signal step failed) instead of
    # silently reporting status='ran'.
    gate_ok, gate_last = _run_step(
        [py, "scripts/run_opportunities_gate.py", "--run", str(run_dir)],
        "gate")
    signal_ok, signal_last = _run_step(
        [py, "scripts/build_signal_post.py", "--run", str(run_dir)],
        "signal")
    downstream_notes: list[str] = []
    if not gate_ok:
        downstream_notes.append(f"gate_step_failed: {gate_last[:120]}")
    if not signal_ok:
        downstream_notes.append(f"signal_step_failed: {signal_last[:120]}")
    label = ""
    sig_path = run_dir / "signal_post.md"
    if sig_path.exists():
        try:
            txt = sig_path.read_text(encoding="utf-8")
        except OSError:
            txt = ""
        for marker in (
            "evidence_backed_signal", "frontier_hypothesis",
            "speculative_alpha", "curation_needed",
            "evidence_binding_failed", "discard",
        ):
            if f"`{marker}`" in txt:
                label = marker
                break
        if not label and "# No signal" in txt:
            label = "no_signal"
    status = "partial_failure" if downstream_notes else "ran"
    return TopicResult(
        topic=topic, velocity=velocity, status=status,
        run_dir=str(run_dir.relative_to(_ROOT)),
        signal_label=label or "unknown",
        notes="; ".join(downstream_notes),
    )


def _top_card_summary(run_dir: str) -> tuple[str, str]:
    if not run_dir:
        return "", ""
    top_path = _ROOT / run_dir / "top_5.md"
    try:
        lines = top_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", ""
    finding = cues = ""
    for line in lines:
        if not finding and line.startswith("**Finding:**"):
            finding = line.removeprefix("**Finding:**").strip()
        elif not cues and line.startswith("- **Alpha cues:**"):
            cues = line.removeprefix("- **Alpha cues:**").strip()
        if finding and cues:
            break
    return finding, cues


def _plan_topics(
    ranked: list[dict[str, Any]],
    *,
    recent: set[str],
    excluded: set[str],
    top: int,
    min_fact_sources: int = 0,
    hard_floor: int = 0,
    require_papers: bool = False,
    tier2_supply: Callable[[str], int] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    plan: list[dict[str, Any]] = []
    planned_token_sets: list[set[str]] = []
    underfloor: list[dict[str, Any]] = []
    skipped: list[str] = []
    skipped_excluded: list[str] = []
    below_floor: list[str] = []
    below_floor_reserve: list[dict[str, Any]] = []
    for c in ranked:
        topic = str(c.get("topic") or "")
        if not topic:
            continue
        if topic in excluded:
            skipped_excluded.append(topic)
            continue
        if topic in recent:
            skipped.append(topic)
            continue
        if require_papers and int(c.get("paper_count") or 0) <= 0:
            below_floor.append(topic)
            continue
        count = int(c.get("fact_source_count") or 0)
        # Tier-2 rescue: the per-topic facts endpoint can read 0 while the
        # Tier-2 corpus holds the same literature untagged; the build binds it
        # via crosscheck. Promote sub-floor topics that carry >= floor distinct
        # Tier-2 source papers so rich-but-untagged topics are not filtered out
        # unbuilt. Universal — no per-topic logic, applies to every domain.
        floor = max(hard_floor, min_fact_sources)
        if (
            tier2_supply is not None and floor and count < floor
            and c.get("tier2_rescue_allowed") is not False
        ):
            count = max(count, tier2_supply(topic))
        # Hard floor first: sub-floor topics do not displace stronger
        # candidates, but nonzero topics remain a last-resort stale-run rebuild.
        if hard_floor and count < hard_floor:
            below_floor.append(topic)
            if count > 0:
                below_floor_reserve.append(c)
            continue
        if min_fact_sources and count < min_fact_sources:
            underfloor.append(c)
            continue
        toks = {t for t in topic.split("_") if t}
        if any(_topic_token_jaccard(toks, seen) >= _NEAR_DUP_JACCARD
               for seen in planned_token_sets):
            skipped.append(topic)
            continue
        planned_token_sets.append(toks)
        plan.append(c)
        if len(plan) >= top:
            break
    # Rescue underfloor candidates only for exploratory/non-submit cycles.
    # A stop-on-ready publish cycle is looking for a candidate that can clear
    # the source floor now; rebuilding known-underfloor topics just burns the
    # cycle and cannot produce a valid submission.
    if not plan and not min_fact_sources:
        for c in underfloor:
            if len(plan) >= top:
                break
            plan.append(c)
    if not plan and not min_fact_sources:
        for c in below_floor_reserve:
            if len(plan) >= top:
                break
            plan.append(c)
    planned_topics = {str(c.get("topic") or "") for c in plan}
    return (
        plan, skipped, skipped_excluded,
        [topic for topic in below_floor if topic not in planned_topics],
    )


def _summarize_md(
    cycle_ts: str, results: list[TopicResult], skipped: list[str],
    cooldown_hours: float, top_requested: int,
) -> str:
    lines = [
        f"# Curator cycle — {cycle_ts}",
        "",
        f"**Top requested:** {top_requested}",
        f"**Cooldown:** {cooldown_hours}h",
        f"**Topics ran:** {sum(1 for r in results if r.status == 'ran')}",
        f"**Topics skipped (cooldown):** {len(skipped)}",
        f"**Topics failed:** {sum(1 for r in results if r.status == 'failed')}",
        "",
        "| Rank | Topic | Velocity | Status | Signal label | Run dir |",
        "|---:|---|---:|---|---|---|",
    ]
    for i, r in enumerate(results, start=1):
        lines.append(
            f"| {i} | `{r.topic}` | {r.velocity:.2f} | {r.status} | "
            f"`{r.signal_label}` | `{r.run_dir or '—'}` |"
        )
    top_cards = [
        (r.topic, r.signal_label, *_top_card_summary(r.run_dir), r.run_dir)
        for r in results if r.run_dir
    ]
    top_cards = [row for row in top_cards if row[2]]
    if top_cards:
        lines += [
            "",
            "## Top surfaced cards",
            "",
            "| Topic | Signal | #1 finding | Alpha cues | Run dir |",
            "|---|---|---|---|---|",
        ]
        for topic, label, finding, cues, run_dir in top_cards:
            lines.append(
                f"| `{topic}` | `{label}` | {finding[:180]} | "
                f"{cues or 'baseline'} | `{run_dir}` |"
            )
    if skipped:
        lines += [
            "",
            f"## Skipped (in cooldown < {cooldown_hours}h)",
            "",
            ", ".join(f"`{t}`" for t in skipped),
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=domain_choices(), default="longevity")
    parser.add_argument("--top", type=int, default=5,
                        help="Number of topics to run this cycle (default 5)")
    parser.add_argument("--cooldown-hours", type=float, default=24.0,
                        help="Skip topics signal-posted within last H hours "
                             "(default 24)")
    parser.add_argument("--no-editorial", action="store_true",
                        help="Skip MiMo editorial polish on top-5 cards")
    parser.add_argument("--no-frontier", action="store_true",
                        help="Skip MiMo frontier-review generation")
    parser.add_argument("--with-pico-enrich", action="store_true",
                        help="Run optional MiMo PICO enrichment in build step")
    parser.add_argument("--stop-on-ready", action="store_true",
                        help="Stop after the first ready_to_publish verdict")
    parser.add_argument("--exclude-topic", action="append", default=[],
                        help="Skip a topic for this cycle; repeatable")
    parser.add_argument(
        "--priority-topic", action="append", default=[],
        help="Run this topic before discovery-ranked topics; repeatable.",
    )
    parser.add_argument(
        "--warm-backlog", action="store_true",
        help="Probe the full derived topic pool before planning; slower.",
    )
    parser.add_argument(
        "--derived-topic-limit", type=int, default=None,
        help="Override topic-discovery derived candidate cap.",
    )
    parser.add_argument(
        "--fact-probe-topics", type=int, default=None,
        help="Override extra derived topics probed for source breadth.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan; do not invoke the pipeline")
    args = parser.parse_args()
    profile = load_domain_profile(args.domain)

    cycle_start = dt.datetime.now(dt.UTC)
    cycle_ts = cycle_start.strftime("%Y-%m-%dT%H-%M-%SZ")
    py = sys.executable
    excluded = {str(t).strip() for t in args.exclude_topic if str(t).strip()}
    priority_topics = [
        cap_topic_slug(str(topic).strip())
        for topic in args.priority_topic if str(topic).strip()
    ]
    priority_only_submit = bool(args.stop_on_ready and priority_topics)

    # Step 1: refresh discovery
    print("[cycle] step 1: topic discovery")
    if priority_only_submit:
        print("[cycle] priority submit refresh: skipping broad discovery")
    elif not args.dry_run:
        discovery_top = _discovery_top_for_plan(
            args.top,
            stop_on_ready=args.stop_on_ready,
            excluded_count=len(args.exclude_topic),
        )
        seed_paper_fast_path = args.stop_on_ready and not args.warm_backlog

        def discovery_args(
            *, seed_paper_only: bool, skip_seed_paper_probe: bool = False,
        ) -> list[str]:
            out = [
                py, "scripts/run_topic_discovery.py",
                "--domain", args.domain,
                "--top", str(discovery_top),
            ]
            if args.stop_on_ready and not args.warm_backlog:
                out.append("--cache-first")
                if seed_paper_only:
                    out.append("--seed-paper-only")
                if skip_seed_paper_probe:
                    out.append("--skip-seed-paper-probe")
            if args.warm_backlog:
                out.append("--warm-backlog")
            if args.derived_topic_limit is not None:
                out.extend([
                    "--derived-topic-limit", str(max(0, args.derived_topic_limit)),
                ])
            if args.fact_probe_topics is not None:
                out.extend([
                    "--fact-probe-topics", str(max(0, args.fact_probe_topics)),
                ])
            for topic in sorted(excluded):
                out.extend(["--exclude-topic", topic])
            return out

        ok, last = _run_step(
            discovery_args(seed_paper_only=seed_paper_fast_path),
            "discovery",
            timeout=_DISCOVERY_TIMEOUT_SECONDS,
        )
        if not ok:
            print(f"[cycle] discovery failed: {last}", file=sys.stderr)
            return 1
    ranked = (
        []
        if priority_only_submit else
        _read_discovery_top(_RUNS / "_topics_discovery", domain=args.domain)
    )
    if (
        not ranked
        and not priority_only_submit
        and args.stop_on_ready
        and not args.warm_backlog
        and not args.dry_run
    ):
        print("[cycle] seed-paper discovery empty; retrying bounded discovery")
        ok, last = _run_step(
            discovery_args(seed_paper_only=False, skip_seed_paper_probe=True),
            "discovery",
            timeout=_DISCOVERY_TIMEOUT_SECONDS,
        )
        if not ok:
            print(f"[cycle] discovery fallback failed: {last}", file=sys.stderr)
            return 1
        ranked = _read_discovery_top(_RUNS / "_topics_discovery", domain=args.domain)
    if not ranked and not args.priority_topic:
        print("[cycle] no discovery candidates; aborting.", file=sys.stderr)
        return 1

    # Step 2: cooldown filter
    recent = _recent_signal_topics(_RUNS, args.cooldown_hours, cycle_start)
    # Defense-in-depth: cap every inbound priority topic to the 4-token rule so
    # a malformed slug from any caller cannot be probed raw and hang the cycle.
    priority_ranked = _priority_ranked_topics(priority_topics, domain=args.domain)
    _cycle_settings = load_settings()
    # Cap live probes per cycle so a run of supply-less candidates cannot
    # exhaust the cycle budget; cache hits are free. The planner stops once
    # `top` topics are planned, so this only bounds the cold worst case.
    _tier2_budget = [max(2 * max(1, args.top), 8)]
    _tier2_cache = _read_tier2_cache()
    _tier2_now = time.time()
    with httpx.Client() as _cycle_client:
        def _probe_tier2(topic: str) -> int:
            if _tier2_budget[0] <= 0:
                return 0
            _tier2_budget[0] -= 1
            try:
                return tier2_source_count(
                    topic, client=_cycle_client, settings=_cycle_settings,
                    domain=args.domain,
                )
            except (OSError, httpx.HTTPError, ValueError):
                return 0

        def _tier2_supply(topic: str) -> int:
            return _cached_tier2_supply(
                f"{args.domain}:{topic}", cache=_tier2_cache, now=_tier2_now,
                probe=lambda: _probe_tier2(topic),
            )

        plan_pool = (
            priority_ranked
            if args.stop_on_ready and priority_ranked
            else [*priority_ranked, *ranked]
        )
        plan, skipped, skipped_excluded, below_floor = _plan_topics(
            plan_pool, recent=recent, excluded=excluded,
            top=args.top,
            min_fact_sources=(
                _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES if args.stop_on_ready else 0
            ),
            hard_floor=_PREBUILD_MIN_SOURCE_FLOOR,
            require_papers=args.stop_on_ready,
            tier2_supply=_tier2_supply,
        )

    print(f"[cycle] plan: {len(plan)} topics to run, {len(skipped)} skipped "
          f"(cooldown {args.cooldown_hours}h), "
          f"{len(skipped_excluded)} excluded, "
          f"{len(below_floor)} below source floor (not built)")
    seen_topics = {str(c.get("topic") or "") for c in plan}
    for c in plan:
        print(f"   - {c['topic']:25}  velocity={c.get('velocity_score',0):.2f}")

    if args.dry_run:
        print("[cycle] --dry-run: stopping before pipeline execution.")
        return 0

    # Step 3: run pipeline per topic
    results: list[TopicResult] = []
    stopped_on_ready = False
    for c in plan:
        topic = str(c["topic"])
        vel = float(c.get("velocity_score") or 0.0)
        print(f"[cycle] running pipeline: {topic}")
        t0 = time.time()
        res = _run_topic_pipeline(
            topic, vel, with_editorial=not args.no_editorial,
            top_n=_DEFAULT_PIPELINE_TOP_N, py=py,
            frontier_review=not args.no_frontier,
            pico_enrich=args.with_pico_enrich,
            parent_topic=str(c.get("parent_topic") or ""),
            domain=args.domain,
        )
        elapsed = time.time() - t0
        print(f"   -> {res.status} label={res.signal_label} "
              f"({elapsed:.1f}s)")
        results.append(res)
        if args.stop_on_ready and _is_publish_ready(res.run_dir):
            stopped_on_ready = True
            print("[cycle] stop-on-ready: publishable candidate created")
            break
        if args.stop_on_ready and not args.priority_topic:
            depth = int(c.get("child_depth") or 0)
            if depth >= _MAX_CHILD_RERUN_DEPTH:
                continue
            for child in _child_topics_from_verdict(res.run_dir, seen_topics):
                print(f"[cycle] child-topic rerun: {child}")
                plan.append({
                    "topic": child,
                    "parent_topic": topic,
                    "child_depth": depth + 1,
                    "velocity_score": max(0.0, vel - 0.01),
                })

    # Step 4: emit summary
    _CYCLES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cycle_ts": cycle_ts, "domain": profile.as_metadata(),
        "top_requested": args.top,
        "cooldown_hours": args.cooldown_hours,
        "ran": [r.as_dict() for r in results],
        "skipped_in_cooldown": skipped,
        "skipped_excluded": skipped_excluded,
        "skipped_below_source_floor": below_floor,
        "stopped_on_ready": stopped_on_ready,
    }
    json_path = _CYCLES_DIR / f"{cycle_ts}.json"
    md_path = _CYCLES_DIR / f"{cycle_ts}.md"
    _write_cycle_json(json_path, payload)
    md_text = _summarize_md(cycle_ts, results, skipped,
                            args.cooldown_hours, args.top)
    cross_ok, cross_last = (False, "skipped_stop_on_ready") if stopped_on_ready else _run_step(
        [py, "scripts/run_cross_topic_synthesis.py",
         "--cycle-json", str(json_path)],
        "cross_topic",
    )
    if cross_ok:
        memo_name = f"{cycle_ts}_cross_topic_alpha_memo.md"
        payload["cross_topic_memo"] = f"runs/_curator_cycles/{memo_name}"
        _write_cycle_json(json_path, payload)
        md_text += f"\n## Cross-topic lead\n\n`runs/_curator_cycles/{memo_name}`\n"
    else:
        payload["cross_topic_memo_error"] = cross_last[:240]
        _write_cycle_json(json_path, payload)
        md_text += f"\n## Cross-topic lead\n\n_failed: {cross_last[:240]}_\n"
    domain_queue_display_path = f"runs/_publish_queue.{args.domain}.json"
    queue_ok, queue_last = _run_step(
        [py, "scripts/build_publish_queue.py", "--domain", args.domain],
        "publish_queue",
    )
    if queue_ok:
        payload["publish_queue"] = "runs/_publish_queue.json"
        payload["domain_publish_queue"] = domain_queue_display_path
        _write_cycle_json(json_path, payload)
        md_text += (
            "\n## Publish queue\n\n"
            "`runs/_publish_queue.json`\n\n"
            f"Domain queue: `{domain_queue_display_path}`\n"
        )
    else:
        payload["publish_queue_error"] = queue_last[:240]
        _write_cycle_json(json_path, payload)
        md_text += f"\n## Publish queue\n\n_failed: {queue_last[:240]}_\n"
    publish_io.write_text(md_path, md_text)
    print(f"[cycle] summary -> runs/_curator_cycles/{cycle_ts}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
