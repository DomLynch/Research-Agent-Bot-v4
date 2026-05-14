"""Sprint 41 — Evidence Index CLI.

Builds the per-topic Evidence Index snapshot from the latest paper
folder, computes the delta against the prior snapshot if one exists,
and writes both to `runs/_index/<topic>/<timestamp>.json` +
`runs/_index/<topic>/_latest_snapshot.json`. Monthly movers feed off
these files.

Usage:
    python scripts/build_evidence_index.py --topic rapamycin
    python scripts/build_evidence_index.py --topic metformin --paper-dir runs/metformin-paper-...
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.evidence_delta import compute_delta, deltas_as_dict
from agent.evidence_index import EvidenceIndex, compute_evidence_index

_RUNS = Path(__file__).resolve().parent.parent / "runs"
_INDEX_DIR = _RUNS / "_index"


def _latest_paper_for(topic: str) -> Path | None:
    candidates = sorted(_RUNS.glob(f"{topic}-paper-*"), reverse=True)
    return candidates[0] if candidates else None


def _load_prior(topic_dir: Path) -> EvidenceIndex | None:
    """Load the previous snapshot's claims via the `_latest_snapshot.json`
    pointer; returns None when no prior snapshot exists."""
    ptr = topic_dir / "_latest_snapshot.json"
    if not ptr.exists():
        return None
    try:
        loaded = json.loads(ptr.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    target = topic_dir / str(loaded.get("snapshot_file", ""))
    if not target.exists():
        return None
    try:
        snap = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    from agent.evidence_index import ClaimAtom
    claims = tuple(
        ClaimAtom(
            topic=str(c.get("topic") or ""),
            claim_text=str(c.get("claim_text") or ""),
            confidence_0_100=int(c.get("confidence_0_100") or 0),
            score_breakdown=tuple(
                (str(k), int(v))
                for k, v in (c.get("score_breakdown") or {}).items()
            ),
            publication_opportunity=bool(c.get("publication_opportunity", False)),
            paper_type=str(c.get("paper_type") or ""),
            readiness_level=int(c.get("readiness_level") or 0),
            k_pool=int(c.get("k_pool") or 0),
            supporting_study_ids=tuple(c.get("supporting_study_ids") or ()),
            contradicting_study_ids=tuple(c.get("contradicting_study_ids") or ()),
            cite_audit_clean=c.get("cite_audit_clean"),
            mean_agent_confidence=float(c.get("mean_agent_confidence") or 0.0),
        )
        for c in snap.get("claims", []) if isinstance(c, dict)
    )
    return EvidenceIndex(
        topic=str(snap.get("topic") or ""),
        snapshot_utc=str(snap.get("snapshot_utc") or ""),
        paper_dir_name=str(snap.get("paper_dir_name") or ""),
        claims=claims,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--paper-dir", type=Path, default=None,
                        help="Override the latest-paper auto-discovery.")
    args = parser.parse_args()

    paper_dir = args.paper_dir or _latest_paper_for(args.topic)
    if paper_dir is None or not paper_dir.is_dir():
        print(f"ERROR: no paper folder for topic {args.topic!r}", file=sys.stderr)
        return 2

    snapshot_utc = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    idx = compute_evidence_index(paper_dir, topic=args.topic, snapshot_utc=snapshot_utc)

    topic_dir = _INDEX_DIR / args.topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    prior = _load_prior(topic_dir)
    deltas = compute_delta(idx, prior)

    snap_file = f"{snapshot_utc}.json"
    (topic_dir / snap_file).write_text(
        json.dumps(idx.as_dict(), indent=2), encoding="utf-8",
    )
    (topic_dir / f"{snapshot_utc}_movers.json").write_text(
        json.dumps(deltas_as_dict(idx, deltas), indent=2), encoding="utf-8",
    )
    (topic_dir / "_latest_snapshot.json").write_text(
        json.dumps({"snapshot_file": snap_file, "snapshot_utc": snapshot_utc},
                    indent=2),
        encoding="utf-8",
    )

    print(f"[index] {args.topic}  snapshot={snapshot_utc}  paper={paper_dir.name}")
    for c in idx.claims:
        print(f"  claim: {c.confidence_0_100}/100  L{c.readiness_level}  k={c.k_pool}  "
              f"{c.paper_type}")
    if prior is None:
        print("[index] no prior snapshot — all claims classified as `new`")
    for d in deltas:
        sign = ("+" + str(d.delta_points)) if d.delta_points > 0 else str(d.delta_points)
        print(f"  delta: {d.direction:13}  {sign:>4}pt   {d.claim_text[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
