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


EligibilityOutcome = Literal[
    "included", "excluded", "unclear", "no_parse", "no_oa", "not_retrieved",
]


@dataclass(frozen=True, slots=True)
class SentinelStatus:
    sentinel_id: str
    role: Role
    retrieved: bool
    candidate: bool
    eligibility: EligibilityOutcome


@dataclass(frozen=True, slots=True)
class SentinelRecallReceipt:
    statuses: tuple[SentinelStatus, ...]
    expected_primary: int
    expected_prior_meta: int
    retrieved_primary: int
    retrieved_prior_meta: int
    candidate_primary: int
    candidate_prior_meta: int
    included_primary: int

    @property
    def gate_level(self) -> Literal["PASS", "WARN", "FAIL"]:
        """Three-level gate honest about the pipeline's actual recovery:

          PASS: every primary sentinel landed as INCLUDED in the corpus.
          WARN: primary sentinels were retrieved but at least one is in a
                validly-unresolved state (parse/HTTP fail, unclear).
          FAIL: at least one primary sentinel is not retrieved at all OR
                was actively excluded.
        """
        primaries = [s for s in self.statuses if s.role == "primary"]
        if any(s.eligibility == "not_retrieved" for s in primaries):
            return "FAIL"
        if any(s.eligibility == "excluded" for s in primaries):
            return "FAIL"
        if all(s.eligibility == "included" for s in primaries) and primaries:
            return "PASS"
        return "WARN"

    @property
    def gate_passes(self) -> bool:
        return self.gate_level == "PASS"


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


def _sentinel_eligibility(
    sid_norm: str, state: EvidenceState, retrieved: bool, candidate: bool,
) -> EligibilityOutcome:
    """Map a sentinel id to its eligibility outcome via the state's
    candidate index + receipts. Pure: no IO, no LLM."""
    if not retrieved:
        return "not_retrieved"
    cand_by_id_or_pmid: dict[str, str] = {}
    for c in state.candidates:
        if c.doi:
            norm = normalize_doi(c.doi)
            if norm:
                cand_by_id_or_pmid[norm] = c.study_id
        if c.pmid:
            cand_by_id_or_pmid[c.pmid] = c.study_id
    study_id = cand_by_id_or_pmid.get(sid_norm)
    if study_id is None:
        return "not_retrieved" if not candidate else "no_oa"
    ft = next((r for r in state.full_text_receipts if r.study_id == study_id), None)
    if ft is None or not ft.retrieved:
        return "no_oa"
    parsed = next((p for p in state.parsed_receipts if p.study_id == study_id), None)
    if parsed is None or not parsed.parsed:
        return "no_parse"
    elig = next((r for r in state.eligibility_receipts if r.study_id == study_id), None)
    if elig is None:
        return "unclear"
    if elig.decision == "include":
        return "included"
    if elig.decision == "exclude":
        return "excluded"
    return "unclear"


def audit_sentinel_recall(
    state: EvidenceState, pack: TopicPack,
) -> SentinelRecallReceipt:
    """Compare topic-pack sentinel IDs against state. Tracks retrieval,
    candidate promotion, AND eligibility outcome per sentinel."""
    primary = tuple(dict.fromkeys(_normalise_id(s) for s in pack.sentinel_primary))
    prior = tuple(dict.fromkeys(_normalise_id(s) for s in pack.sentinel_prior_meta))
    hit_keys = _index(tuple(state.hits))
    cand_keys = _index(tuple(state.candidates))

    statuses: list[SentinelStatus] = []
    for sid in primary:
        retrieved = sid in hit_keys
        candidate = sid in cand_keys
        statuses.append(SentinelStatus(
            sentinel_id=sid, role="primary",
            retrieved=retrieved, candidate=candidate,
            eligibility=_sentinel_eligibility(sid, state, retrieved, candidate),
        ))
    for sid in prior:
        retrieved = sid in hit_keys
        candidate = sid in cand_keys
        statuses.append(SentinelStatus(
            sentinel_id=sid, role="prior_meta",
            retrieved=retrieved, candidate=candidate,
            eligibility=_sentinel_eligibility(sid, state, retrieved, candidate),
        ))

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
        included_primary=sum(
            1 for s in statuses if s.role == "primary" and s.eligibility == "included"
        ),
    )
