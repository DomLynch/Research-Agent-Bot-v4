"""Sprint 22 — CLI wrapper for the universal submission-package builder.

Usage:
    python scripts/build_submission_package.py runs/rapamycin-paper-... \\
        --topic rapamycin --target-journal "Aging Cell"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.submission_package import build_submission
from agent.topic_pack import load_topic_pack


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_dir", type=Path)
    parser.add_argument("--topic", default="")
    parser.add_argument("--target-journal", default="(target journal TBD)")
    parser.add_argument("--operator-handle", default="the operator")
    args = parser.parse_args()

    if not args.paper_dir.is_dir():
        print(f"ERROR: not a directory: {args.paper_dir}", file=sys.stderr)
        return 2

    display = args.topic
    if args.topic:
        pack = load_topic_pack(args.topic)
        if pack is not None and pack.display_name:
            display = pack.display_name

    pkg = build_submission(
        args.paper_dir, target_journal=args.target_journal,
        topic_display=display or "(topic)",
        operator_handle=args.operator_handle,
    )
    print(f"[submission] wrote {len(pkg.files_written)} files → {pkg.target_dir}")
    for name in pkg.files_written:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
