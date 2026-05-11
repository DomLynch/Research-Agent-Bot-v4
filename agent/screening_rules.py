"""Rule-based screening: PaperHit -> title-abstract ScreeningReceipts + CandidateStudy.

Universal: all rules read from the topic pack. The screener checks for
preferred-scope terms, primary-intervention terms, and translational-only
disqualifiers. A study is screened-include at the title/abstract stage
only — full-text retrieval and full-text eligibility are downstream
sprints. Each surviving hit becomes a `CandidateStudy` with
`screening_stage = "title_abstract_candidate"`.

Truth discipline: this module never emits a `full-text` include receipt
and never marks a study as `full_text_eligible`. Those upgrades must come
from a real full-text screening pass.

This module contains zero biomedical literals. All term lists come from
the topic pack.
"""
from __future__ import annotations

from typing import Literal

from agent.retrieval.base import PaperHit
from agent.screening import CandidateStudy, ScreeningReceipt
from agent.topic_pack import TopicPack

_Decision = Literal["include", "exclude"]


def _any_match(text: str, terms: tuple[str, ...]) -> bool:
    return any(t.casefold() in text for t in terms if t)


def screen_hit(hit: PaperHit, pack: TopicPack) -> ScreeningReceipt:
    """Emit a single title-abstract receipt for one hit."""
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

    return ScreeningReceipt(hit.dedupe_key, decision, "title-abstract", reason)


def screen_hits(
    hits: tuple[PaperHit, ...], pack: TopicPack
) -> tuple[ScreeningReceipt, ...]:
    return tuple(screen_hit(hit, pack) for hit in hits)


def build_candidate_studies(
    hits: tuple[PaperHit, ...], receipts: tuple[ScreeningReceipt, ...]
) -> tuple[CandidateStudy, ...]:
    """Materialise CandidateStudy records from title-abstract include receipts."""
    ta_includes = {
        r.hit_key
        for r in receipts
        if r.decision == "include" and r.stage == "title-abstract"
    }
    hits_by_key: dict[str, PaperHit] = {h.dedupe_key: h for h in hits}
    candidates: list[CandidateStudy] = []
    for idx, key in enumerate(sorted(ta_includes)):
        h = hits_by_key.get(key)
        if h is None:
            continue
        candidates.append(
            CandidateStudy(
                study_id=f"s{idx + 1:03d}",
                hit_key=h.dedupe_key,
                title=h.title,
                year=h.year,
                venue=h.venue,
                screening_stage="title_abstract_candidate",
                pmid=h.pmid,
                doi=h.doi,
            )
        )
    return tuple(candidates)
