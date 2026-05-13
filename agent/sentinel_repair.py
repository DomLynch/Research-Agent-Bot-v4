"""Sprint 18 — universal sentinel repair plan.

Computes an actionable list of missing sentinels from the
sentinel_recall receipt + topic pack. Network repair is a separate
sprint; this module emits the plan only. Universal: action mapping is
keyed off the failure_mode enum, no domain literals.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent.sentinel_recall import SentinelRecallReceipt
from agent.topic_pack import TopicPack

_ACTIONS: Mapping[str, tuple[str, ...]] = {
    "not_retrieved": ("crossref-doi-lookup", "europe-pmc-search", "manual-upload"),
    "no_oa": ("europe-pmc-full-text", "publisher-direct", "manual-pdf-upload"),
    "no_parse": ("manual-pdf-override", "europe-pmc-retry"),
    "unclear": ("verify-extraction-quotes", "manual-judge-review"),
    "resolved_available_pending": ("rerun-extraction-with-fresh-parse",),
    "resolved_needs_review": ("manual-judge-review",),
}
_DONE: frozenset[str] = frozenset({"included", "excluded", "unavailable"})


@dataclass(frozen=True, slots=True)
class SentinelRepairEntry:
    sentinel_id: str
    role: str
    failure_mode: str
    bibliography_entry: str
    recommended_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SentinelRepairPlan:
    entries: tuple[SentinelRepairEntry, ...]

    @property
    def k_repair_needed(self) -> int:
        return len(self.entries)

    @property
    def clean(self) -> bool:
        return not self.entries

    def as_dict(self) -> dict[str, object]:
        return {
            "clean": self.clean, "k_repair_needed": self.k_repair_needed,
            "entries": [{
                "sentinel_id": e.sentinel_id, "role": e.role,
                "failure_mode": e.failure_mode,
                "bibliography_entry": e.bibliography_entry,
                "recommended_actions": list(e.recommended_actions),
            } for e in self.entries],
        }


def _biblio_for_id(sid: str, biblio: Mapping[str, str]) -> str:
    needle = sid.lower()
    return next((v for v in biblio.values() if needle in v.lower()), "")


def compute_repair_plan(
    receipt: SentinelRecallReceipt, pack: TopicPack,
) -> SentinelRepairPlan:
    """Emit repair entries for sentinels that aren't terminal-good and
    aren't manually resolved-to-final-state."""
    entries: list[SentinelRepairEntry] = []
    for st in receipt.statuses:
        if st.eligibility in _DONE:
            continue
        if st.manually_resolved and st.eligibility in {"excluded", "unavailable"}:
            continue
        entries.append(SentinelRepairEntry(
            sentinel_id=st.sentinel_id, role=st.role,
            failure_mode=st.eligibility,
            bibliography_entry=_biblio_for_id(
                st.sentinel_id, pack.references_bibliography,
            ),
            recommended_actions=_ACTIONS.get(st.eligibility, ("manual-upload",)),
        ))
    return SentinelRepairPlan(entries=tuple(entries))
