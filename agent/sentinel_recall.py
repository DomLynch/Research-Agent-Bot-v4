"""Sentinel-recall gate.

Audits whether retrieval surfaced the canonical anchor papers a topic pack
declares under `[sentinel_recall]`. Each sentinel is identified by DOI or
PMID. The gate emits a `SentinelRecallReceipt` recording, per sentinel,
whether it was retrieved + whether it was promoted to a candidate. The
results writer renders this as the audit line beneath Study Selection.

Why: 2 included studies covering 2021-2025 looks honest until you check
whether Harrison-2009 / Strong-2016 were ever in the candidate set. If
canonical anchors are silently missing, the corpus is biased even when
every receipt is well-formed. This gate exposes that gap.

Universal: keys come from the topic pack. No biomedical literal here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.evidence_state import EvidenceState
from agent.retrieval.base import PaperHit, normalize_doi
from agent.screening import CandidateStudy
from agent.topic_pack import TopicPack

Role = Literal["primary", "prior_meta"]


@dataclass(frozen=True, slots=True)
class SentinelStatus:
    sentinel_id: str
    role: Role
    retrieved: bool
    candidate: bool


@dataclass(frozen=True, slots=True)
class SentinelRecallReceipt:
    statuses: tuple[SentinelStatus, ...]
    expected_primary: int
    expected_prior_meta: int
    retrieved_primary: int
    retrieved_prior_meta: int
    candidate_primary: int
    candidate_prior_meta: int

    @property
    def gate_passes(self) -> bool:
        """Primary sentinels must all be retrieved (candidates is softer)."""
        return self.retrieved_primary == self.expected_primary


def _key_set(hit_or_cand: PaperHit | CandidateStudy) -> frozenset[str]:
    keys: list[str] = []
    if hit_or_cand.doi:
        norm = normalize_doi(hit_or_cand.doi)
        if norm:
            keys.append(norm)
    if hit_or_cand.pmid:
        keys.append(str(hit_or_cand.pmid))
    return frozenset(keys)


def _index(items: tuple[PaperHit | CandidateStudy, ...]) -> frozenset[str]:
    out: set[str] = set()
    for it in items:
        out.update(_key_set(it))
    return frozenset(out)


def _normalise_id(sentinel_id: str) -> str:
    """Sentinels may be listed as DOIs or PMIDs; normalise to lower-case DOI form."""
    if "/" not in sentinel_id:
        return sentinel_id
    return normalize_doi(sentinel_id) or sentinel_id


def audit_sentinel_recall(
    state: EvidenceState, pack: TopicPack,
) -> SentinelRecallReceipt:
    """Compare topic-pack sentinel IDs against retrieved hits + candidates."""
    primary = tuple(dict.fromkeys(_normalise_id(s) for s in pack.sentinel_primary))
    prior = tuple(dict.fromkeys(_normalise_id(s) for s in pack.sentinel_prior_meta))
    hit_keys = _index(tuple(state.hits))
    cand_keys = _index(tuple(state.candidates))

    statuses: list[SentinelStatus] = []
    for sid in primary:
        statuses.append(
            SentinelStatus(
                sentinel_id=sid, role="primary",
                retrieved=sid in hit_keys, candidate=sid in cand_keys,
            )
        )
    for sid in prior:
        statuses.append(
            SentinelStatus(
                sentinel_id=sid, role="prior_meta",
                retrieved=sid in hit_keys, candidate=sid in cand_keys,
            )
        )

    return SentinelRecallReceipt(
        statuses=tuple(statuses),
        expected_primary=len(primary),
        expected_prior_meta=len(prior),
        retrieved_primary=sum(1 for s in statuses if s.role == "primary" and s.retrieved),
        retrieved_prior_meta=sum(
            1 for s in statuses if s.role == "prior_meta" and s.retrieved
        ),
        candidate_primary=sum(1 for s in statuses if s.role == "primary" and s.candidate),
        candidate_prior_meta=sum(
            1 for s in statuses if s.role == "prior_meta" and s.candidate
        ),
    )
