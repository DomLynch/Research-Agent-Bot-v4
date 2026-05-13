"""Sprint 15 — one-command runner for the 9-stage research-paper pipeline.

Drives each stage in `scripts/` sequentially. Stops on the first non-zero
exit (subprocess). Resolves the s7 eligibility-run directory by globbing
`runs/<topic>-s7-iter-*` after the eligibility step so the downstream
freeze/extract scripts get the correct input dir.

Stages (in order):
  1. run_eligibility.py  --topic T --iter N
  2. freeze_primary_set.py <s7-dir> --topic T
  3. extract_effects.py   <s7-dir> --topic T
  4. draft_main.py       --topic T --iter N --section title_abstract_intro
  5. draft_main.py       --topic T --iter N --section methods
  6. build_results.py    --topic T --iter N
  7. draft_main.py       --topic T --iter N --section discussion
  8. stitch_paper.py     --topic T
  9. build_supplement.py <paper-dir> --topic T

No new logic — each stage is the same CLI the operator invokes by hand,
so this runner inherits every per-stage gate (writer fallback,
SECTIONS_PENDING refusal, sentinel recall, etc.). Universal: no
biomedical literals; the topic flag flows through unchanged.

Usage:
    python scripts/build_topic_paper.py --topic rapamycin
    python scripts/build_topic_paper.py --topic acarbose --iter 2
    python scripts/build_topic_paper.py --topic nmn --skip eligibility,extract
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
_RUNS = _ROOT / "runs"
_PY = sys.executable

_ALL_STAGES = (
    "eligibility", "freeze", "extract",
    "intro", "methods", "results", "discussion",
    "stitch", "supplement",
)


def _latest(topic: str, short: str) -> Path | None:
    """Return the most recent `runs/<topic>-<short>-iter-*` directory."""
    matches = sorted(_RUNS.glob(f"{topic}-{short}-iter-*"), reverse=True)
    return matches[0] if matches else None


def _latest_paper(topic: str) -> Path | None:
    """Return the most recent `runs/<topic>-paper-*` directory."""
    matches = sorted(_RUNS.glob(f"{topic}-paper-*"), reverse=True)
    return matches[0] if matches else None


def _run(label: str, cmd: list[str]) -> None:
    """Run one stage; raise on non-zero exit so the orchestrator stops."""
    print(f"\n[runner] >>> stage={label}  cmd={' '.join(str(c) for c in cmd)}", flush=True)
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=_ROOT, check=False)
    elapsed = time.monotonic() - t0
    if proc.returncode != 0:
        raise RuntimeError(
            f"stage {label!r} exited {proc.returncode} after {elapsed:.1f}s — "
            f"halting pipeline; fix the failing stage and re-run with --skip"
        )
    print(f"[runner] <<< stage={label}  ok  ({elapsed:.1f}s)", flush=True)


def build(topic: str, *, iter_n: int = 1, skip: set[str] | None = None,
          repository_url: str = "") -> Path:
    skip = skip or set()
    unknown = skip - set(_ALL_STAGES)
    if unknown:
        raise ValueError(f"unknown stage(s) in --skip: {sorted(unknown)}")

    if "eligibility" not in skip:
        _run("eligibility", [
            _PY, str(_SCRIPTS / "run_eligibility.py"),
            "--topic", topic, "--iter", str(iter_n),
        ])
    s7 = _latest(topic, "s7")
    if s7 is None:
        raise RuntimeError(
            f"no runs/{topic}-s7-iter-* directory after eligibility — "
            f"cannot continue"
        )

    if "freeze" not in skip:
        _run("freeze", [
            _PY, str(_SCRIPTS / "freeze_primary_set.py"),
            str(s7), "--topic", topic,
        ])
    if "extract" not in skip:
        _run("extract", [
            _PY, str(_SCRIPTS / "extract_effects.py"),
            str(s7), "--topic", topic,
        ])
    for section, label in (
        ("title_abstract_intro", "intro"),
        ("methods", "methods"),
    ):
        if label in skip:
            continue
        _run(label, [
            _PY, str(_SCRIPTS / "draft_main.py"),
            "--topic", topic, "--iter", str(iter_n),
            "--section", section,
        ])
    if "results" not in skip:
        _run("results", [
            _PY, str(_SCRIPTS / "build_results.py"),
            "--topic", topic, "--iter", str(iter_n),
        ])
    if "discussion" not in skip:
        _run("discussion", [
            _PY, str(_SCRIPTS / "draft_main.py"),
            "--topic", topic, "--iter", str(iter_n),
            "--section", "discussion",
        ])
    if "stitch" not in skip:
        cmd = [
            _PY, str(_SCRIPTS / "stitch_paper.py"), "--topic", topic,
        ]
        if repository_url:
            cmd += ["--repository-url", repository_url]
        _run("stitch", cmd)
    paper = _latest_paper(topic)
    if paper is None:
        raise RuntimeError(
            f"no runs/{topic}-paper-* directory after stitch — "
            f"cannot continue to supplement"
        )
    if "supplement" not in skip:
        _run("supplement", [
            _PY, str(_SCRIPTS / "build_supplement.py"),
            str(paper), "--topic", topic,
        ])
    print(f"\n[runner] DONE  paper={paper}", flush=True)
    return paper


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="research topic")
    parser.add_argument("--iter", type=int, default=1, help="iteration number")
    parser.add_argument(
        "--skip", default="",
        help=f"comma-separated stages to skip (any of: {','.join(_ALL_STAGES)})",
    )
    parser.add_argument(
        "--repository-url", default="",
        help="public repo URL for the Data and Code Availability section",
    )
    args = parser.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    try:
        build(args.topic, iter_n=args.iter, skip=skip,
              repository_url=args.repository_url)
    except RuntimeError as e:
        print(f"\n[runner] FAIL  {e}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
