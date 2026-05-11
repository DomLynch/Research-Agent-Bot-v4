"""Rule-based screening: PaperHit -> ScreeningReceipts + IncludedStudy.

Universal: all rules read from the topic pack. The screener checks for
preferred-scope terms, primary-intervention terms, and translational-only
disqualifiers. A study is included only when it carries at least one
preferred-scope token AND at least one primary-intervention token, with
no discouraged-scope term and no translational-only-without-primary
override. Title-abstract and full-text receipts are emitted; in this MVP
the full-text receipt mirrors the title-abstract receipt — when full-text
retrieval is wired the receipt can re-decide.

This module contains zero biomedical literals. All term lists come from
the topic pack.
"""
from __future__ import annotations

from typing import Literal

from agent.retrieval.base import PaperHit
from agent.screening import IncludedStudy, ScreeningReceipt
from agent.topic_pack import TopicPack

_Decision = Literal["include", "exclude"]


def _any_match(text: str, terms: tuple[str, ...]) -> bool:
    return any(t.casefold() in text for t in terms if t)


def screen_hit(hit: PaperHit, pack: TopicPack) -> tuple[ScreeningReceipt, ScreeningReceipt]:
    """Emit (title-abstract receipt, full-text receipt) for one hit."""
    text = f"{hit.title} {hit.abstract}".casefold()

    has_preferred = (
        _any_match(text, pack.preferred_terms) if pack.preferred_terms else True
    )
    has_primary = (
        _any_match(text, pack.primary_interventions)
        if pack.primary_interventions
        else True
    )
    has_translational_only = _any_match(text, pack.translational_only_interventions)
    has_discouraged = _any_match(text, pack.discouraged_terms)

    decision: _Decision
    if has_discouraged:
        decision, reason = "exclude", "contains discouraged scope term"
    elif not has_preferred:
        decision, reason = "exclude", "no preferred-scope term in title/abstract"
    elif not has_primary:
        decision, reason = "exclude", "no primary intervention term in title/abstract"
    elif has_translational_only and not has_primary:
        decision, reason = "exclude", "translational-only intervention without primary"
    else:
        decision, reason = "include", "scope + primary intervention match"

    return (
        ScreeningReceipt(hit.dedupe_key, decision, "title-abstract", reason),
        ScreeningReceipt(hit.dedupe_key, decision, "full-text", reason),
    )


def screen_hits(
    hits: tuple[PaperHit, ...], pack: TopicPack
) -> tuple[ScreeningReceipt, ...]:
    receipts: list[ScreeningReceipt] = []
    for hit in hits:
        ta, ft = screen_hit(hit, pack)
        receipts.append(ta)
        receipts.append(ft)
    return tuple(receipts)


def build_included_studies(
    hits: tuple[PaperHit, ...], receipts: tuple[ScreeningReceipt, ...]
) -> tuple[IncludedStudy, ...]:
    """Materialise IncludedStudy records from hits with full-text include receipts."""
    full_text_includes = {
        r.hit_key
        for r in receipts
        if r.decision == "include" and r.stage == "full-text"
    }
    hits_by_key: dict[str, PaperHit] = {h.dedupe_key: h for h in hits}
    included: list[IncludedStudy] = []
    for idx, key in enumerate(sorted(full_text_includes)):
        h = hits_by_key.get(key)
        if h is None:
            continue
        included.append(
            IncludedStudy(
                study_id=f"s{idx + 1:03d}",
                hit_key=h.dedupe_key,
                title=h.title,
                year=h.year,
                venue=h.venue,
                pmid=h.pmid,
                doi=h.doi,
            )
        )
    return tuple(included)
