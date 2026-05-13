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

from agent.retrieval.base import PaperHit, normalize_doi
from agent.screening import CandidateStudy, ScreeningReceipt
from agent.topic_pack import TopicPack

_Decision = Literal["include", "exclude"]


def _any_match(text: str, terms: tuple[str, ...]) -> bool:
    return any(t.casefold() in text for t in terms if t)


def _sentinel_keys(pack: TopicPack) -> frozenset[str]:
    """Normalised identifiers (DOI lower / PMID) of declared sentinels."""
    out: set[str] = set()
    for sid in tuple(pack.sentinel_primary) + tuple(pack.sentinel_prior_meta):
        if "/" in sid:
            norm = normalize_doi(sid)
            if norm:
                out.add(norm)
        else:
            out.add(sid)
    return frozenset(out)


def _is_sentinel(hit: PaperHit, sentinel_keys: frozenset[str]) -> bool:
    if not sentinel_keys:
        return False
    if hit.doi and (normalize_doi(hit.doi) or "") in sentinel_keys:
        return True
    return bool(hit.pmid and hit.pmid in sentinel_keys)


def screen_hit(
    hit: PaperHit, pack: TopicPack, *, sentinel_keys: frozenset[str] = frozenset(),
) -> ScreeningReceipt:
    """Emit a single title-abstract receipt for one hit.

    Declared sentinels bypass exclusion - they are explicit "must include"
    anchors that the user has staked the recall gate on. Discouraged-scope
    terms are checked against the TITLE only because abstracts of canonical
    mouse papers (e.g. Harrison-2009) routinely mention "mammalian species"
    or "rodent" in framing without being rat/rodent studies; using the
    abstract over-rejects valid candidates.
    """
    if _is_sentinel(hit, sentinel_keys):
        return ScreeningReceipt(
            hit.dedupe_key, "include", "title-abstract",
            "sentinel-anchored bypass",
        )

    title = hit.title.casefold()
    body = f"{hit.title} {hit.abstract}".casefold()

    has_preferred = (
        _any_match(body, pack.preferred_terms) if pack.preferred_terms else True
    )
    has_primary = (
        _any_match(body, pack.primary_interventions)
        if pack.primary_interventions
        else True
    )
    has_translational_only = _any_match(body, pack.translational_only_interventions)
    has_discouraged_in_title = _any_match(title, pack.discouraged_terms)

    decision: _Decision
    if has_discouraged_in_title:
        decision, reason = "exclude", "contains discouraged scope term in title"
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
    sentinel_keys = _sentinel_keys(pack)
    return tuple(screen_hit(hit, pack, sentinel_keys=sentinel_keys) for hit in hits)


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
                source=h.source,
            )
        )
    return tuple(candidates)
