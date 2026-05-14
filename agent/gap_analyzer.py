"""Sprint 44 — v4 gap-analyser + publish-opportunity trigger.

Reads per-topic Evidence Index snapshots from `runs/_index/<topic>/`,
emits prioritized PublishOpportunity payloads that downstream consumers
(Research Agent v3 writer, Researka website, monthly digest) consume.
When DB endpoints ship, swap _latest_snapshot_path data source only.
Universal: no biomedical literals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_MIN_DELTA_FOR_MOVER = 10        # confidence movement >=10pt = notable
_MAX_TOPICS_PER_DIGEST = 5       # monthly top-N cap


@dataclass(frozen=True, slots=True)
class PublishOpportunity:
    """Trigger payload for Research Agent v3."""
    topic: str
    reason: str               # publication_opportunity_fires / strong_mover
    confidence_0_100: int
    delta_points: int
    claim_text: str
    paper_type: str
    supporting_study_count: int
    snapshot_utc: str
    priority: int             # 0..100; higher = stronger trigger

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic, "reason": self.reason,
            "confidence_0_100": self.confidence_0_100,
            "delta_points": self.delta_points,
            "claim_text": self.claim_text,
            "paper_type": self.paper_type,
            "supporting_study_count": self.supporting_study_count,
            "snapshot_utc": self.snapshot_utc, "priority": self.priority,
        }


def _latest_snapshot_path(topic_dir: Path) -> Path | None:
    ptr = topic_dir / "_latest_snapshot.json"
    if not ptr.exists():
        return None
    try:
        data = json.loads(ptr.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    f = str(data.get("snapshot_file", ""))
    return (topic_dir / f) if f else None


def _movers_path_for(snapshot_path: Path) -> Path:
    """Convention: every snapshot has a sibling `<ts>_movers.json`."""
    return snapshot_path.with_name(snapshot_path.stem + "_movers.json")


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_list_of_dict(d: dict[str, object], key: str) -> list[dict[str, object]]:
    """Narrow `d[key]` to a list of dicts, dropping non-dict entries."""
    v = d.get(key)
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, dict)]


def _safe_int(d: dict[str, object], key: str) -> int:
    v = d.get(key, 0)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _safe_str_list(d: dict[str, object], key: str) -> list[str]:
    v = d.get(key)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if x]


def _opportunities_for_topic(
    topic: str, snapshot: dict[str, object], movers: dict[str, object],
) -> list[PublishOpportunity]:
    """Walk one topic's latest snapshot + movers, emit qualifying
    trigger payloads. Universal: every read goes through the typed
    safe-* helpers so malformed JSON never raises."""
    out: list[PublishOpportunity] = []
    snapshot_utc = str(snapshot.get("snapshot_utc") or "")
    claims = _safe_list_of_dict(snapshot, "claims")
    movers_list = _safe_list_of_dict(movers, "movers")
    movers_by_claim = {str(m.get("claim_text", "")): m for m in movers_list}

    for claim in claims:
        text = str(claim.get("claim_text", ""))
        conf = _safe_int(claim, "confidence_0_100")
        pub_opp = bool(claim.get("publication_opportunity", False))
        pt = str(claim.get("paper_type", ""))
        supp_count = len(_safe_str_list(claim, "supporting_study_ids"))
        delta_int = _safe_int(movers_by_claim.get(text, {}), "delta_points")

        if pub_opp:
            out.append(PublishOpportunity(
                topic=topic, reason="publication_opportunity_fires",
                confidence_0_100=conf, delta_points=delta_int,
                claim_text=text, paper_type=pt,
                supporting_study_count=supp_count,
                snapshot_utc=snapshot_utc,
                priority=min(100, conf + max(0, delta_int)),
            ))
            continue  # don't double-count

        if abs(delta_int) >= _MIN_DELTA_FOR_MOVER:
            out.append(PublishOpportunity(
                topic=topic, reason="strong_mover",
                confidence_0_100=conf, delta_points=delta_int,
                claim_text=text, paper_type=pt,
                supporting_study_count=supp_count,
                snapshot_utc=snapshot_utc,
                priority=min(100, abs(delta_int) * 4),
            ))
    return out


@dataclass(frozen=True, slots=True)
class GapDigest:
    """Aggregate output: top movers + publication opportunities across
    every topic that has at least one snapshot. Consumed by v3 trigger
    (one-at-a-time) and by the monthly digest renderer (all-at-once)."""
    snapshot_utc: str
    topics_inspected: int
    opportunities: tuple[PublishOpportunity, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "snapshot_utc": self.snapshot_utc,
            "topics_inspected": self.topics_inspected,
            "opportunities": [o.as_dict() for o in self.opportunities],
        }


def run_gap_analysis(index_root: Path, *, snapshot_utc: str) -> GapDigest:
    """Walk every topic in `index_root` (one subdir per topic), find
    each topic's latest snapshot + movers, emit a prioritized
    `GapDigest`. Skips topics with no snapshot yet (no work to do)."""
    if not index_root.exists():
        return GapDigest(
            snapshot_utc=snapshot_utc, topics_inspected=0, opportunities=(),
        )
    opportunities: list[PublishOpportunity] = []
    inspected = 0
    for topic_dir in sorted(index_root.iterdir()):
        if not topic_dir.is_dir() or topic_dir.name.startswith("_"):
            continue
        snap_path = _latest_snapshot_path(topic_dir)
        if snap_path is None or not snap_path.exists():
            continue
        inspected += 1
        snapshot = _read_json(snap_path)
        movers = _read_json(_movers_path_for(snap_path))
        opportunities.extend(
            _opportunities_for_topic(topic_dir.name, snapshot, movers),
        )
    # Sort by priority descending; cap at the configured top-N.
    opportunities.sort(key=lambda o: o.priority, reverse=True)
    return GapDigest(
        snapshot_utc=snapshot_utc, topics_inspected=inspected,
        opportunities=tuple(opportunities[:_MAX_TOPICS_PER_DIGEST]),
    )
