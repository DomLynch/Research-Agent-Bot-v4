"""Sprint 8.1 - stitch section bundles into one paper_draft.md.

The pipeline currently writes three independent section bundles:

  runs/<topic>-s1-iter-NN-<ts>/main_draft.md  Title + Abstract + Introduction
  runs/<topic>-s2-iter-NN-<ts>/main_draft.md  Methods
  runs/<topic>-s7-iter-NN-<ts>/main_draft.md  Section 3 Results
                                              (study_selection -> sentinel ->
                                              corpus -> primary effect -> ...)

Each bundle is auto-generated; their wiring is otherwise independent. This
stitcher concatenates the most recent bundle of each kind (by run_dir name,
which embeds the ISO timestamp) into a single Markdown file and writes it
into the s7 run dir as paper_draft.md, so the canonical run-dir bundle holds
the complete draft alongside its receipts.

No LLM, no retrieval, no judging. Pure file IO. Topic-agnostic.

Usage:
    python scripts/stitch_paper.py --topic rapamycin
    python scripts/stitch_paper.py --topic rapamycin --target-s7 runs/latest
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

_RUNS = Path(__file__).resolve().parent.parent / "runs"


def _latest_bundle(topic: str, section_short: str) -> Path | None:
    """Return the lexicographically-latest <topic>-<short>-iter-NN-<ts> dir."""
    candidates = sorted(
        _RUNS.glob(f"{topic}-{section_short}-iter-*"), reverse=True,
    )
    return candidates[0] if candidates else None


def _read(path: Path | None) -> str:
    if path is None:
        return ""
    f = path / "main_draft.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument(
        "--target-s7", type=Path, default=None,
        help="Path to the s7 (Results) run dir. Defaults to latest by name.",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    s1 = _latest_bundle(args.topic, "s1")
    s2 = _latest_bundle(args.topic, "s2")
    s7 = args.target_s7.resolve() if args.target_s7 else _latest_bundle(args.topic, "s7")

    title_abs_intro = _read(s1).rstrip()
    methods = _read(s2).rstrip()
    results = _read(s7).rstrip()

    if not (title_abs_intro or methods or results):
        print("ERROR: no section bundles found; run draft_main.py + build_results.py first")
        return 2

    parts: list[str] = []
    if title_abs_intro:
        parts.append(title_abs_intro)
    if methods:
        parts.append(methods)
    if results:
        parts.append(results)
    body = "\n\n".join(parts) + "\n"

    stamp = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    header = (
        "<!-- AUTO-STITCHED — do not edit by hand. Bundles used:\n"
        f"  s1: {s1.name if s1 else '(none)'}\n"
        f"  s2: {s2.name if s2 else '(none)'}\n"
        f"  s7: {s7.name if s7 else '(none)'}\n"
        f"  stamped: {stamp}\n"
        "-->\n\n"
    )
    body = header + body

    if args.out is not None:
        target = args.out
    elif s7 is not None:
        target = s7 / "paper_draft.md"
    else:
        target = _RUNS / "paper_draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"[stitch] wrote {target} (s1={bool(s1)} s2={bool(s2)} s7={bool(s7)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
