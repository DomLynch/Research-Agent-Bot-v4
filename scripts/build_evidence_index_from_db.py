"""Sprint 46 — DB-backed Evidence Index snapshot builder.

Fetches canonical facts for a topic via
  GET https://database.researka.org/api/v1/topics/{topic}/facts
aggregates them into claim dicts, and writes the same snapshot
shape `gap_analyzer.run_gap_analysis` already reads from
`runs/_index/<topic>/<ts>.json`. No engine-side changes — this is a
drop-in canonical data source.

Usage:
    python scripts/build_evidence_index_from_db.py --topic rapamycin
    python scripts/build_evidence_index_from_db.py --topic carbon_tax --sub-topic policy
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.researka_claims import fetch_topic_claims
from agent.settings import load_settings

_INDEX_ROOT = Path(__file__).resolve().parent.parent / "runs" / "_index"


def _safe_int(d: dict[str, object], key: str) -> int:
    v = d.get(key, 0)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _prev_snapshot_claims(topic_dir: Path) -> list[dict[str, object]]:
    """Returns prior snapshot's claims (for delta computation), or []."""
    ptr = topic_dir / "_latest_snapshot.json"
    if not ptr.exists():
        return []
    try:
        ptr_data = json.loads(ptr.read_text(encoding="utf-8"))
        prev_file = topic_dir / str(ptr_data.get("snapshot_file", ""))
        if not prev_file.exists():
            return []
        prev = json.loads(prev_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    claims = prev.get("claims", []) if isinstance(prev, dict) else []
    return [c for c in claims if isinstance(c, dict)]


def _movers(curr: list[dict[str, object]],
            prev: list[dict[str, object]]) -> list[dict[str, object]]:
    """Delta points = curr_conf - prev_conf, keyed by claim_text."""
    prev_by_text = {str(c.get("claim_text", "")): _safe_int(c, "confidence_0_100")
                    for c in prev}
    out: list[dict[str, object]] = []
    for c in curr:
        text = str(c.get("claim_text", ""))
        if not text:
            continue
        delta = _safe_int(c, "confidence_0_100") - prev_by_text.get(text, 0)
        if delta != 0:
            out.append({"claim_text": text, "delta_points": delta})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--sub-topic", default=None,
                        help="Optional sub_topic filter passed to the API")
    args = parser.parse_args()
    settings = load_settings()
    snapshot_utc = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    with httpx.Client() as client:
        claims = fetch_topic_claims(
            args.topic, client=client, settings=settings,
            sub_topic=args.sub_topic,
        )
    topic_dir = _INDEX_ROOT / args.topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    prev_claims = _prev_snapshot_claims(topic_dir)
    snap_file = topic_dir / f"{snapshot_utc}.json"
    snap_file.write_text(json.dumps({
        "topic": args.topic, "snapshot_utc": snapshot_utc,
        "paper_dir_name": "db", "claims": claims,
        "source": "researka_db",
    }, indent=2), encoding="utf-8")
    movers_file = topic_dir / f"{snapshot_utc}_movers.json"
    movers_file.write_text(json.dumps({
        "topic": args.topic, "snapshot_utc": snapshot_utc,
        "movers": _movers(claims, prev_claims),
    }, indent=2), encoding="utf-8")
    (topic_dir / "_latest_snapshot.json").write_text(json.dumps({
        "snapshot_file": snap_file.name, "snapshot_utc": snapshot_utc,
    }, indent=2), encoding="utf-8")
    pub_opps = sum(1 for c in claims if c.get("publication_opportunity"))
    print(f"[db-index] topic={args.topic} claims={len(claims)} "
          f"pub_opps={pub_opps} → {snap_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
