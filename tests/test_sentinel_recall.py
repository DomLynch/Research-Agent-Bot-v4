"""Sentinel-recall audit tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.evidence_state import EvidenceState
from agent.results_compiler import compile_sentinel_recall
from agent.retrieval.base import PaperHit
from agent.screening import CandidateStudy, ScreeningReceipt
from agent.sentinel_recall import audit_sentinel_recall
from agent.topic_pack import TopicPack


def _pack(primary: tuple[str, ...] = (), prior_meta: tuple[str, ...] = ()) -> TopicPack:
    return TopicPack(
        topic="t", display_name="T", primary_system="",
        preferred_terms=("mouse",), discouraged_terms=(),
        endpoint="", cite_role_default="", cite_roles_allowed=(),
        anchors=MappingProxyType({}), length_caps=MappingProxyType({}),
        min_words_per_citation=0,
        outcome_nouns_extra=(), direction_verbs_extra=(), subjects_extra=(),
        primary_interventions=(), translational_only_interventions=(),
        retrieval_sources=(),
        eligibility_endpoint_terms=(), eligibility_control_terms=(),
        eligibility_exclude_design_terms=(), eligibility_combination_terms=(),
        eligibility_min_text_chars=0,
        sentinel_primary=primary, sentinel_prior_meta=prior_meta,
    )


def _hit(doi: str, pmid: str = "") -> PaperHit:
    return PaperHit(
        source="pubmed", title="t", abstract="", year=2020, url="u",
        doi=doi, pmid=pmid or None, venue="J",
    )


def _state_with(hits: tuple[PaperHit, ...], cand_hit_keys: frozenset[str]) -> EvidenceState:
    receipts = tuple(
        ScreeningReceipt(h.dedupe_key, "include", "title-abstract", "ok") for h in hits
    )
    cands = tuple(
        CandidateStudy(
            study_id=f"s{i}", hit_key=h.dedupe_key, title=h.title,
            year=h.year, venue=h.venue, doi=h.doi, pmid=h.pmid,
        )
        for i, h in enumerate(hits) if h.dedupe_key in cand_hit_keys
    )
    return EvidenceState.build(
        topic="t", hits=hits, receipts=receipts, candidates=cands,
    )


def test_no_sentinels_yields_no_packet() -> None:
    state = EvidenceState.build(topic="t")
    pack = _pack()
    assert compile_sentinel_recall(state, pack) is None


def test_all_primary_sentinels_retrieved_passes_gate() -> None:
    h1 = _hit("10.1038/nature08221")
    h2 = _hit("10.1111/acel.12476")
    state = _state_with((h1, h2), frozenset({h1.dedupe_key, h2.dedupe_key}))
    pack = _pack(primary=("10.1038/nature08221", "10.1111/acel.12476"))
    r = audit_sentinel_recall(state, pack)
    assert r.gate_passes
    assert r.expected_primary == 2
    assert r.retrieved_primary == 2
    assert r.candidate_primary == 2


def test_missing_primary_sentinel_fails_gate() -> None:
    h1 = _hit("10.1038/nature08221")
    state = _state_with((h1,), frozenset({h1.dedupe_key}))
    pack = _pack(primary=("10.1038/nature08221", "10.1111/acel.12476"))
    r = audit_sentinel_recall(state, pack)
    assert not r.gate_passes
    assert r.retrieved_primary == 1
    assert r.expected_primary == 2


def test_prior_meta_retrieved_but_not_candidate_is_ok() -> None:
    h1 = _hit("10.1111/acel.12674")
    # Retrieved (in hits) but NOT promoted to candidate
    state = _state_with((h1,), frozenset())
    pack = _pack(prior_meta=("10.1111/acel.12674",))
    r = audit_sentinel_recall(state, pack)
    assert r.gate_passes  # primary expectations are 0/0
    assert r.retrieved_prior_meta == 1
    assert r.candidate_prior_meta == 0


def test_normalises_doi_case() -> None:
    h1 = _hit("10.1038/NATURE08221")  # upper-case DOI in hit
    state = _state_with((h1,), frozenset({h1.dedupe_key}))
    pack = _pack(primary=("10.1038/nature08221",))  # lower-case in pack
    r = audit_sentinel_recall(state, pack)
    assert r.retrieved_primary == 1


def test_pmid_only_sentinel_matches_by_pmid() -> None:
    h1 = _hit("", pmid="19587680")
    state = _state_with((h1,), frozenset({h1.dedupe_key}))
    pack = _pack(primary=("19587680",))
    r = audit_sentinel_recall(state, pack)
    assert r.retrieved_primary == 1


def test_compile_sentinel_recall_packet_shape() -> None:
    h1 = _hit("10.1038/nature08221")
    state = _state_with((h1,), frozenset({h1.dedupe_key}))
    pack = _pack(primary=("10.1038/nature08221",), prior_meta=("10.1111/acel.12674",))
    pkt = compile_sentinel_recall(state, pack)
    assert pkt is not None
    assert pkt.packet_id == "sentinel_recall"
    assert pkt.counts["retrieved_primary"] == 1
    assert pkt.counts["retrieved_prior_meta"] == 0
    assert pkt.counts["gate_passes"] == 1
    assert any("primary:" in n for n in pkt.notes)
