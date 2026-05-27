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
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"
_CYCLES_DIR = _RUNS / "_curator_cycles"


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


def _read_discovery_top(out_dir: Path) -> list[dict[str, Any]]:
    """Find the newest discovery JSON in runs/_topics_discovery/."""
    if not out_dir.exists():
        return []
    candidates = sorted(out_dir.glob("*.json"))
    if not candidates:
        return []
    try:
        data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("all") or data.get("top") or []
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, dict) and c.get("topic")]


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
    return str(verdict.get("decision") or "") == "ready_to_publish"


def _run_step(args: list[str], step_name: str) -> tuple[bool, str]:
    """Run a subprocess; return (ok, last_line). Never raises."""
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=600, check=False)
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"{step_name}: {type(e).__name__}: {e}"
    out = (r.stdout or "").strip().splitlines()
    last = out[-1] if out else (r.stderr or "")[:200]
    return r.returncode == 0, last


def _run_topic_pipeline(
    topic: str, velocity: float, *, with_editorial: bool, top_n: int,
    py: str, pico_enrich: bool = False,
) -> TopicResult:
    """Run build + gate + signal_post for one topic. Returns the
    aggregate result. Each step's failure is recorded; we continue
    through to give the operator a partial output trail."""
    build_args = [py, "scripts/build_topic_evidence_run.py",
                  "--topic", topic, "--top", str(top_n)]
    if with_editorial:
        build_args.append("--with-editorial")
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
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    plan: list[dict[str, Any]] = []
    skipped: list[str] = []
    skipped_excluded: list[str] = []
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
        plan.append(c)
        if len(plan) >= top:
            break
    return plan, skipped, skipped_excluded


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
    parser.add_argument("--top", type=int, default=5,
                        help="Number of topics to run this cycle (default 5)")
    parser.add_argument("--cooldown-hours", type=float, default=24.0,
                        help="Skip topics signal-posted within last H hours "
                             "(default 24)")
    parser.add_argument("--no-editorial", action="store_true",
                        help="Skip MiMo editorial polish on top-5 cards")
    parser.add_argument("--with-pico-enrich", action="store_true",
                        help="Run optional MiMo PICO enrichment in build step")
    parser.add_argument("--stop-on-ready", action="store_true",
                        help="Stop after the first ready_to_publish verdict")
    parser.add_argument("--exclude-topic", action="append", default=[],
                        help="Skip a topic for this cycle; repeatable")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan; do not invoke the pipeline")
    args = parser.parse_args()

    cycle_start = dt.datetime.now(dt.UTC)
    cycle_ts = cycle_start.strftime("%Y-%m-%dT%H-%M-%SZ")
    py = sys.executable

    # Step 1: refresh discovery
    print("[cycle] step 1: topic discovery")
    if not args.dry_run:
        _run_step([py, "scripts/run_topic_discovery.py", "--top", "20"],
                  "discovery")
    ranked = _read_discovery_top(_RUNS / "_topics_discovery")
    if not ranked:
        print("[cycle] no discovery candidates; aborting.", file=sys.stderr)
        return 1

    # Step 2: cooldown filter
    recent = _recent_signal_topics(_RUNS, args.cooldown_hours, cycle_start)
    excluded = {str(t).strip() for t in args.exclude_topic if str(t).strip()}
    plan, skipped, skipped_excluded = _plan_topics(
        ranked, recent=recent, excluded=excluded, top=args.top,
    )

    print(f"[cycle] plan: {len(plan)} topics to run, {len(skipped)} skipped "
          f"(cooldown {args.cooldown_hours}h), "
          f"{len(skipped_excluded)} excluded")
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
            top_n=5, py=py, pico_enrich=args.with_pico_enrich,
        )
        elapsed = time.time() - t0
        print(f"   -> {res.status} label={res.signal_label} "
              f"({elapsed:.1f}s)")
        results.append(res)
        if args.stop_on_ready and _is_publish_ready(res.run_dir):
            stopped_on_ready = True
            print("[cycle] stop-on-ready: publishable candidate created")
            break

    # Step 4: emit summary
    _CYCLES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cycle_ts": cycle_ts, "top_requested": args.top,
        "cooldown_hours": args.cooldown_hours,
        "ran": [r.as_dict() for r in results],
        "skipped_in_cooldown": skipped,
        "skipped_excluded": skipped_excluded,
        "stopped_on_ready": stopped_on_ready,
    }
    json_path = _CYCLES_DIR / f"{cycle_ts}.json"
    md_path = _CYCLES_DIR / f"{cycle_ts}.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_text += f"\n## Cross-topic lead\n\n`runs/_curator_cycles/{memo_name}`\n"
    else:
        payload["cross_topic_memo_error"] = cross_last[:240]
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_text += f"\n## Cross-topic lead\n\n_failed: {cross_last[:240]}_\n"
    queue_ok, queue_last = _run_step(
        [py, "scripts/build_publish_queue.py"],
        "publish_queue",
    )
    if queue_ok:
        payload["publish_queue"] = "runs/_publish_queue.json"
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_text += "\n## Publish queue\n\n`runs/_publish_queue.json`\n"
    else:
        payload["publish_queue_error"] = queue_last[:240]
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_text += f"\n## Publish queue\n\n_failed: {queue_last[:240]}_\n"
    md_path.write_text(md_text, encoding="utf-8")
    print(f"[cycle] summary -> runs/_curator_cycles/{cycle_ts}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
