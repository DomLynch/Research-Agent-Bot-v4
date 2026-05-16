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
    """Topics whose newest signal_post.md is within the cooldown
    window — those should be skipped on this cycle."""
    if not runs_root.exists():
        return set()
    cutoff = now - dt.timedelta(hours=cooldown_hours)
    recent: set[str] = set()
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir() or "-evidence-" not in run_dir.name:
            continue
        signal_path = run_dir / "signal_post.md"
        if not signal_path.exists():
            continue
        mtime = dt.datetime.fromtimestamp(
            signal_path.stat().st_mtime, tz=dt.UTC)
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
    py: str,
) -> TopicResult:
    """Run build + gate + signal_post for one topic. Returns the
    aggregate result. Each step's failure is recorded; we continue
    through to give the operator a partial output trail."""
    build_args = [py, "scripts/build_topic_evidence_run.py",
                  "--topic", topic, "--top", str(top_n)]
    if with_editorial:
        build_args.append("--with-editorial")
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
    plan: list[dict[str, Any]] = []
    skipped: list[str] = []
    for c in ranked:
        topic = str(c.get("topic") or "")
        if not topic:
            continue
        if topic in recent:
            skipped.append(topic)
            continue
        plan.append(c)
        if len(plan) >= args.top:
            break

    print(f"[cycle] plan: {len(plan)} topics to run, {len(skipped)} skipped "
          f"(cooldown {args.cooldown_hours}h)")
    for c in plan:
        print(f"   - {c['topic']:25}  velocity={c.get('velocity_score',0):.2f}")

    if args.dry_run:
        print("[cycle] --dry-run: stopping before pipeline execution.")
        return 0

    # Step 3: run pipeline per topic
    results: list[TopicResult] = []
    for c in plan:
        topic = str(c["topic"])
        vel = float(c.get("velocity_score") or 0.0)
        print(f"[cycle] running pipeline: {topic}")
        t0 = time.time()
        res = _run_topic_pipeline(
            topic, vel, with_editorial=not args.no_editorial,
            top_n=5, py=py,
        )
        elapsed = time.time() - t0
        print(f"   -> {res.status} label={res.signal_label} "
              f"({elapsed:.1f}s)")
        results.append(res)

    # Step 4: emit summary
    _CYCLES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cycle_ts": cycle_ts, "top_requested": args.top,
        "cooldown_hours": args.cooldown_hours,
        "ran": [r.as_dict() for r in results],
        "skipped_in_cooldown": skipped,
    }
    (_CYCLES_DIR / f"{cycle_ts}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (_CYCLES_DIR / f"{cycle_ts}.md").write_text(
        _summarize_md(cycle_ts, results, skipped,
                      args.cooldown_hours, args.top),
        encoding="utf-8")
    print(f"[cycle] summary -> runs/_curator_cycles/{cycle_ts}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
