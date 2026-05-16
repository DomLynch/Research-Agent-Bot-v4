"""Render the cycle-level cross-topic alpha memo.

Default input is the newest curator-cycle JSON. The script reads the
run dirs listed there, loads their `alpha_memo.md` files, applies the
cross-topic density gate, and writes one cycle-level memo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.cross_topic_synthesizer import write_cross_topic_memo
from agent.settings import load_settings

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"
_CYCLES = _RUNS / "_curator_cycles"


def _latest_cycle_json() -> Path | None:
    candidates = sorted(_CYCLES.glob("*.json"))
    return candidates[-1] if candidates else None


def _run_dirs_from_cycle(path: Path) -> list[Path]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("ran") if isinstance(data, dict) else []
    out: list[Path] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        run_dir = str(item.get("run_dir") or "")
        if run_dir:
            out.append(_ROOT / run_dir)
    return out


def _fallback_run_dirs(limit: int) -> list[Path]:
    candidates = sorted(
        p.parent for p in _RUNS.glob("*-evidence-*/alpha_memo.md")
    )
    return candidates[-limit:]


def _default_output(cycle_json: Path | None) -> Path:
    stem = (
        cycle_json.stem
        if cycle_json is not None
        else dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    )
    return _CYCLES / f"{stem}_cross_topic_alpha_memo.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle-json", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-topics", type=int, default=3)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    cycle_json = args.cycle_json or _latest_cycle_json()
    run_dirs = _run_dirs_from_cycle(cycle_json) if cycle_json else []
    if not run_dirs:
        run_dirs = _fallback_run_dirs(args.limit)
    out = args.output or _default_output(cycle_json)
    settings = None if args.no_llm else load_settings()
    path, text = write_cross_topic_memo(
        run_dirs, out, settings=settings, min_topics=args.min_topics,
    )
    status = (
        "publishable_cross_topic_signal"
        if "publishable_cross_topic_signal" in text
        else "insufficient_density"
    )
    print(f"[cross-topic] {status}: {len(run_dirs)} runs -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
