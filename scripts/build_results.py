"""End-to-end Section 3 build: retrieval -> screening -> state -> packets -> writer.

Usage:
    .venv/bin/python scripts/build_results.py --topic rapamycin

Writes:
    runs/<topic>-s3-iter-<NN>-<ts>/main_draft.md
    runs/<topic>-s3-iter-<NN>-<ts>/state.json
    runs/<topic>-s3-iter-<NN>-<ts>/gates.json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.evidence_state import EvidenceState
from agent.results_compiler import InformationalPacket, compile_all
from agent.results_contract import validate_results_text
from agent.results_packets import ResultsPacket
from agent.results_writer import write_results_section
from agent.retrieval.unified import search_all
from agent.screening_rules import build_candidate_studies, screen_hits
from agent.settings import load_settings
from agent.topic_pack import TopicPack, load_topic_pack


def _query_for(pack: TopicPack) -> str:
    """Compose a search query from topic-pack scope vocabulary."""
    pref = " ".join(pack.preferred_terms[:1]) if pack.preferred_terms else ""
    endpoint = pack.endpoint
    primary = (
        " ".join(pack.primary_interventions[:1])
        if pack.primary_interventions
        else pack.topic
    )
    return " ".join(t for t in (primary, endpoint, pref) if t)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument("--iter", type=int, default=1)
    args = parser.parse_args()

    settings = load_settings()
    pack = load_topic_pack(args.topic)
    if pack is None:
        print(f"ERROR: no topic pack for {args.topic!r}", file=sys.stderr)
        return 2

    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_id = f"{args.topic}-s3-iter-{args.iter:02d}-{ts}"
    out_dir = Path(settings.runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    query = _query_for(pack)
    print(f"[s3] topic={args.topic} query={query!r}")

    hits = await search_all(query, settings=settings, pack=pack)
    print(f"[s3] retrieved {len(hits)} hits")

    receipts = screen_hits(tuple(hits), pack)
    n_include_ta = sum(1 for r in receipts if r.decision == "include" and r.stage == "title-abstract")
    print(f"[s3] screened {len(receipts)} TA receipts; {n_include_ta} candidates")

    candidates = build_candidate_studies(tuple(hits), receipts)
    state = EvidenceState.build(
        topic=args.topic,
        hits=tuple(hits),
        receipts=receipts,
        candidates=candidates,
    )
    packets = compile_all(state, moderators=())
    text = write_results_section(packets)
    violations = validate_results_text(text, packets)

    (out_dir / "main_draft.md").write_text(text, encoding="utf-8")
    (out_dir / "state.json").write_text(
        json.dumps(
            {
                "topic": state.topic,
                "k_hits": state.k_hits,
                "k_screened": state.k_screened,
                "k_candidates": state.k_candidates,
                "k_eligible": state.k_eligible,
                "k_outcomes": state.k_outcomes,
                "k_effects": state.k_effects,
                "k_packets": len(packets),
                "packet_ids": [p.packet_id for p in packets],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "gates.json").write_text(
        json.dumps(
            {
                "summary": {"total": len(violations), "by_gate": {}},
                "violations": [v.as_dict() for v in violations],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    info_packets = sum(1 for p in packets if isinstance(p, InformationalPacket))
    result_packets = sum(1 for p in packets if isinstance(p, ResultsPacket))
    print(f"[s3] packets: {info_packets} informational, {result_packets} results")
    print(f"[s3] contract violations: {len(violations)}")
    print(f"[s3] saved -> {out_dir}/main_draft.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
