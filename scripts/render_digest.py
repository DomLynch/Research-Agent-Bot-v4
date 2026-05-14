"""Sprint 45 — markdown view of the v4 gap-analyser digest.

Reads `runs/_index/_digest_<ts>.json` (or any path passed via --in),
emits a `<same-stem>.md` alongside it: priority-ordered list of
publish-opportunities with reason / confidence / delta / claim text,
designed for human curation review before publication to Researka.

Pure presentation layer — lives in scripts/ so it does not consume
agent/ LOC ceiling. Universal: no domain literals, tolerant of
missing/malformed fields.

Usage:
    python scripts/render_digest.py
    python scripts/render_digest.py --in path/to/_digest_X.json
    python scripts/render_digest.py --in X.json --out X.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_INDEX_ROOT = Path(__file__).resolve().parent.parent / "runs" / "_index"

_REASON_LABEL = {
    "publication_opportunity_fires": "Publication opportunity",
    "strong_mover": "Strong confidence mover",
}


def _latest_digest(index_root: Path) -> Path | None:
    if not index_root.exists():
        return None
    candidates = sorted(index_root.glob("_digest_*.json"))
    return candidates[-1] if candidates else None


def _safe_str(d: dict[str, object], key: str, default: str = "") -> str:
    v = d.get(key, default)
    return str(v) if v is not None else default


def _safe_int(d: dict[str, object], key: str) -> int:
    v = d.get(key, 0)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _render_opportunity(idx: int, op: dict[str, object]) -> str:
    topic = _safe_str(op, "topic", "(unknown)")
    priority = _safe_int(op, "priority")
    reason_raw = _safe_str(op, "reason", "unknown")
    reason = _REASON_LABEL.get(reason_raw, reason_raw)
    conf = _safe_int(op, "confidence_0_100")
    delta = _safe_int(op, "delta_points")
    claim = _safe_str(op, "claim_text", "(no claim text)")
    paper_type = _safe_str(op, "paper_type", "(unspecified)")
    supp = _safe_int(op, "supporting_study_count")
    snap = _safe_str(op, "snapshot_utc", "(no snapshot timestamp)")
    delta_str = f"{delta:+d}" if delta else "0"
    return (
        f"## #{idx} — {topic} · priority {priority}\n\n"
        f"- **Trigger:** {reason} (Δ {delta_str} pts)\n"
        f"- **Confidence:** {conf} / 100\n"
        f"- **Paper type:** {paper_type}\n"
        f"- **Supporting studies:** {supp}\n"
        f"- **Claim:** {claim}\n"
        f"- **From snapshot:** {snap}\n"
    )


def render_digest(digest: dict[str, object]) -> str:
    """Render a digest dict to a human-readable markdown string."""
    snap = _safe_str(digest, "snapshot_utc", "(no snapshot timestamp)")
    inspected = _safe_int(digest, "topics_inspected")
    raw_ops = digest.get("opportunities", [])
    ops = [o for o in raw_ops if isinstance(o, dict)] if isinstance(raw_ops, list) else []
    lines: list[str] = [
        "# Publish-Opportunity Digest\n",
        f"- **Snapshot:** {snap}",
        f"- **Topics inspected:** {inspected}",
        f"- **Opportunities surfaced:** {len(ops)}\n",
        "---\n",
    ]
    if not ops:
        lines.append("_No publish-opportunities triggered for this snapshot._\n")
    else:
        for i, op in enumerate(ops, start=1):
            lines.append(_render_opportunity(i, op))
            lines.append("---\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", type=Path, default=None,
                        help="Path to a digest JSON (default: latest in runs/_index/)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Override output path (default: <in>.md alongside)")
    args = parser.parse_args()
    in_path = args.in_path or _latest_digest(_INDEX_ROOT)
    if in_path is None or not in_path.exists():
        print(f"[digest-render] no digest found at {in_path or _INDEX_ROOT}", file=sys.stderr)
        return 1
    try:
        loaded = json.loads(in_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[digest-render] could not read {in_path}: {e}", file=sys.stderr)
        return 1
    if not isinstance(loaded, dict):
        print(f"[digest-render] {in_path} is not a JSON object", file=sys.stderr)
        return 1
    md = render_digest(loaded)
    out_path = args.out or in_path.with_suffix(".md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    raw_ops = loaded.get("opportunities", [])
    n_ops = len([o for o in raw_ops if isinstance(o, dict)]) if isinstance(raw_ops, list) else 0
    print(f"[digest-render] opportunities={n_ops} → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
