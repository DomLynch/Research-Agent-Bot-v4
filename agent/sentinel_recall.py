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
from agent.manual_resolution import ManualResolutionReceipt
from agent.retrieval.base import PaperHit, normalize_doi
from agent.screening import CandidateStudy
from agent.topic_pack import TopicPack

Role = Literal["primary", "prior_meta"]


EligibilityOutcome = Literal[
    "included", "excluded", "unclear", "unavailable",
    "no_parse", "no_oa", "not_retrieved",
    # Sprint 7.11.1: sentinel resolved by human overlay, but the auto
    # pipeline has not yet contract-passed it. The system needs to fix
    # retrieval/parsing; the manual is a status assertion only.
    "resolved_available_pending",
    "resolved_needs_review",
]


@dataclass(frozen=True, slots=True)
class SentinelStatus:
    sentinel_id: str
    role: Role
    retrieved: bool
    candidate: bool
    eligibility: EligibilityOutcome
    manually_resolved: bool = False
    action_required: str = ""


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
        """Three-level gate. Sprint 7.11.1: a sentinel is RESOLVED only
        when (a) the auto-judge confirmed it as INCLUDE (passing the
        universal evidence contract) OR (b) the manual overlay declared
        it 'resolved_unavailable' / 'resolved_excluded'. A manual
        'resolved_available' alone does NOT resolve the sentinel —
        availability is a status assertion, not a contract-pass, so the
        gate stays WARN until the system actually retrieves+parses+
        contract-passes the bytes. This is intentional: the engine must
        report 'WARN: sentinel located but retrieval/parser failed'
        rather than launder the paper into the corpus via human shortcut.

          PASS: every primary sentinel either auto-included or manually
                marked resolved_unavailable / resolved_excluded.
          WARN: any primary sentinel is unresolved or only
                resolved_available_pending (system-bug surface area).
          FAIL: any primary sentinel was never retrieved at all.
        """
        primaries = [s for s in self.statuses if s.role == "primary"]
        if any(s.eligibility == "not_retrieved" for s in primaries):
            return "FAIL"

        def _resolved(s: SentinelStatus) -> bool:
            if s.eligibility == "included":
                return True
            # Only documented-final states count. resolved_available
            # alone is NOT enough — the system still owes a real parse.
            return bool(s.manually_resolved and s.eligibility in {
                "excluded", "unavailable",
            })

        if primaries and all(_resolved(s) for s in primaries):
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


def _candidate_id_for(state: EvidenceState, sid_norm: str) -> str | None:
    """Map a normalised sentinel id (DOI or PMID) back to a study_id."""
    for c in state.candidates:
        if c.doi:
            norm = normalize_doi(c.doi)
            if norm and norm == sid_norm:
                return c.study_id
        if c.pmid and c.pmid == sid_norm:
            return c.study_id
    return None


def _manual_status_for(
    sid_norm: str, state: EvidenceState,
    manual_overlay: dict[str, ManualResolutionReceipt],
) -> ManualResolutionReceipt | None:
    sid = _candidate_id_for(state, sid_norm)
    if sid is not None and sid in manual_overlay:
        return manual_overlay[sid]
    return None


def _sentinel_eligibility(
    sid_norm: str, state: EvidenceState, retrieved: bool, candidate: bool,
    manual_overlay: dict[str, ManualResolutionReceipt],
) -> tuple[EligibilityOutcome, bool, str]:
    """Map a sentinel id to (eligibility outcome, manually_resolved,
    action_required). Pure: no IO, no LLM."""
    manual = _manual_status_for(sid_norm, state, manual_overlay)
    if not retrieved:
        # Even when the manual asserts availability, "not retrieved" by
        # the pipeline is FAIL-worthy because the engine did not find
        # the paper. The manual is informational, not authoritative.
        if manual is not None and manual.status == "resolved_unavailable":
            return "unavailable", True, manual.action_required
        return "not_retrieved", False, manual.action_required if manual else ""
    study_id = _candidate_id_for(state, sid_norm)
    if study_id is None:
        outcome: EligibilityOutcome = "not_retrieved" if not candidate else "no_oa"
        return outcome, False, manual.action_required if manual else ""
    ft = next((r for r in state.full_text_receipts if r.study_id == study_id), None)
    parsed = next((p for p in state.parsed_receipts if p.study_id == study_id), None)
    elig = next((r for r in state.eligibility_receipts if r.study_id == study_id), None)

    # Manual resolved_excluded / resolved_unavailable are documented
    # final states; they trump pipeline noise. resolved_available is a
    # status assertion only and does NOT short-circuit the contract.
    if manual is not None:
        if manual.status == "resolved_excluded":
            return "excluded", True, manual.action_required
        if manual.status == "resolved_unavailable":
            return "unavailable", True, manual.action_required

    if ft is None or not ft.retrieved:
        if manual is not None and manual.status == "resolved_available":
            return "resolved_available_pending", True, manual.action_required
        if manual is not None and manual.status == "needs_review":
            return "resolved_needs_review", True, manual.action_required
        return "no_oa", False, ""
    if parsed is None or not parsed.parsed:
        if manual is not None and manual.status == "resolved_available":
            return "resolved_available_pending", True, manual.action_required
        if manual is not None and manual.status == "needs_review":
            return "resolved_needs_review", True, manual.action_required
        return "no_parse", False, ""
    if elig is None:
        if manual is not None and manual.status == "resolved_available":
            return "resolved_available_pending", True, manual.action_required
        if manual is not None and manual.status == "needs_review":
            return "resolved_needs_review", True, manual.action_required
        return "unclear", False, ""
    if elig.decision == "include":
        # The auto pipeline already contract-passed this. Even with a
        # manual present, this is genuinely resolved.
        return "included", manual is not None, manual.action_required if manual else ""
    if elig.decision == "exclude":
        return "excluded", manual is not None, manual.action_required if manual else ""
    if elig.decision == "unavailable":
        return "unavailable", manual is not None, manual.action_required if manual else ""
    # Auto-judge said unclear — the manual overlay (if any) provides
    # context but doesn't promote.
    if manual is not None and manual.status == "resolved_available":
        return "resolved_available_pending", True, manual.action_required
    if manual is not None and manual.status == "needs_review":
        return "resolved_needs_review", True, manual.action_required
    return "unclear", False, ""


def audit_sentinel_recall(
    state: EvidenceState, pack: TopicPack,
    manual_overlay: dict[str, ManualResolutionReceipt] | None = None,
) -> SentinelRecallReceipt:
    """Compare topic-pack sentinel IDs against state. Tracks retrieval,
    candidate promotion, AND eligibility outcome per sentinel.

    `manual_overlay` is the status-only overlay produced by
    agent.manual_resolution.build_manual_status_overlay(). When omitted,
    no manual status is consulted (pure auto-pipeline view)."""
    overlay: dict[str, ManualResolutionReceipt] = manual_overlay or {}
    primary = tuple(dict.fromkeys(_normalise_id(s) for s in pack.sentinel_primary))
    prior = tuple(dict.fromkeys(_normalise_id(s) for s in pack.sentinel_prior_meta))
    hit_keys = _index(tuple(state.hits))
    cand_keys = _index(tuple(state.candidates))

    statuses: list[SentinelStatus] = []
    for sid in primary:
        retrieved = sid in hit_keys
        candidate = sid in cand_keys
        elig, manual_flag, action = _sentinel_eligibility(
            sid, state, retrieved, candidate, overlay,
        )
        statuses.append(SentinelStatus(
            sentinel_id=sid, role="primary",
            retrieved=retrieved, candidate=candidate,
            eligibility=elig, manually_resolved=manual_flag,
            action_required=action,
        ))
    for sid in prior:
        retrieved = sid in hit_keys
        candidate = sid in cand_keys
        elig, manual_flag, action = _sentinel_eligibility(
            sid, state, retrieved, candidate, overlay,
        )
        statuses.append(SentinelStatus(
            sentinel_id=sid, role="prior_meta",
            retrieved=retrieved, candidate=candidate,
            eligibility=elig, manually_resolved=manual_flag,
            action_required=action,
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
