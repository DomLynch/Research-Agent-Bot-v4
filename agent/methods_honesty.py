"""Rewrite Methods/Discussion overclaim verbs to honest tense.

The writer LLM produces methods + discussion prose using future-tense verbs
borrowed from systematic-review templates: "will be performed", "dual
extraction", "Egger's regression test", "leave-one-out", etc. The current
pipeline implements automated screen + automated extraction + automated
RoB notes only; the heavier moderator/sensitivity machinery is *planned*,
not built. Without correction, the manuscript overclaims the work.

This module post-processes the body text by applying ordered string
rewrites declared in `TopicPack.methods_honesty_rewrites`. Each entry maps
an overclaim phrase to a tense-honest replacement. Replacement runs in
descending-length order so longer phrases consume shorter sub-phrases
first (greedy match, no overlap).

Universal: agent code knows nothing about which phrases or domains; the
rewrites are data in the topic pack. Adding a new topic = declaring its
own `[methods_honesty_rewrites]` block.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.topic_pack import TopicPack


@dataclass(frozen=True, slots=True)
class HonestyResult:
    body: str
    rewrites_applied: tuple[str, ...]


def apply_honesty_rewrites(body: str, pack: TopicPack) -> HonestyResult:
    """Apply phrase -> replacement substitutions from the topic pack.

    Returns the rewritten body plus the list of original phrases that
    actually matched (so callers can verify the rewrites fired and an
    auditor can see which overclaim verbs were corrected).
    """
    if not pack.methods_honesty_rewrites:
        return HonestyResult(body=body, rewrites_applied=())

    rewrites = sorted(
        pack.methods_honesty_rewrites.items(),
        key=lambda kv: -len(kv[0]),
    )
    applied: list[str] = []
    out = body
    for source, target in rewrites:
        if source and source in out:
            out = out.replace(source, target)
            applied.append(source)
    return HonestyResult(body=out, rewrites_applied=tuple(applied))
