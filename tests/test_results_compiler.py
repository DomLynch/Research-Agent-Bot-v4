"""Results-compiler tests."""
from __future__ import annotations

from agent.effect_sizes import EffectSizeRecord, ExtractedOutcome
from agent.evidence_state import EvidenceState
from agent.results_compiler import (
    InformationalPacket,
    compile_all,
    compile_corpus_characteristics,
    compile_moderator_effects,
    compile_primary_effect,
    compile_study_selection,
)
from agent.results_packets import ResultsPacket
from agent.retrieval.base import PaperHit
from agent.screening import IncludedStudy, ScreeningReceipt


def _hit(doi: str, year: int = 2020) -> PaperHit:
    return PaperHit(source="pubmed", title=f"t-{doi}", abstract="",
                    year=year, url="u", doi=doi, pmid=None, venue="Nature")


def _full_state(n_studies: int = 3) -> EvidenceState:
    hits = tuple(_hit(f"10.1/{i}", 2018 + i) for i in range(n_studies))
    receipts: tuple[ScreeningReceipt, ...] = tuple(
        r
        for h in hits
        for r in (
            ScreeningReceipt(h.dedupe_key, "include", "title-abstract", "ok"),
            ScreeningReceipt(h.dedupe_key, "include", "full-text", "ok"),
        )
    )
    included = tuple(
        IncludedStudy(
            study_id=f"s{i}", hit_key=h.dedupe_key, title=h.title, year=h.year,
            venue=h.venue, doi=h.doi,
        )
        for i, h in enumerate(hits)
    )
    outcomes = tuple(
        ExtractedOutcome(
            study_id=f"s{i}", outcome_id="o1", metric_name="median_lifespan_days",
            moderators={"sex": "female" if i % 2 == 0 else "male"},
            treated_value=1100.0 + i * 50, control_value=1000.0,
        )
        for i in range(n_studies)
    )
    effects = tuple(
        EffectSizeRecord(
            study_id=f"s{i}", outcome_id="o1", metric="log_lifespan_ratio",
            estimate=0.10 + i * 0.01, se=0.02,
            moderators={"sex": "female" if i % 2 == 0 else "male"},
        )
        for i in range(n_studies)
    )
    return EvidenceState.build(
        topic="t", hits=hits, receipts=receipts, included=included,
        outcomes=outcomes, effects=effects,
    )


# ---------- study_selection -------------------------------------------------

def test_study_selection_packet_on_empty_state() -> None:
    state = EvidenceState.build(topic="t")
    pkt = compile_study_selection(state)
    assert isinstance(pkt, InformationalPacket)
    assert pkt.packet_id == "study_selection"
    assert pkt.counts["identified"] == 0
    assert pkt.counts["included"] == 0


def test_study_selection_counts_from_state() -> None:
    state = _full_state(n_studies=3)
    pkt = compile_study_selection(state)
    assert pkt.counts["identified"] == 3
    assert pkt.counts["screened_title_abstract"] == 3
    assert pkt.counts["screened_full_text"] == 3
    assert pkt.counts["included"] == 3


# ---------- corpus_characteristics ------------------------------------------

def test_corpus_characteristics_year_range() -> None:
    state = _full_state(n_studies=3)
    pkt = compile_corpus_characteristics(state)
    assert pkt.counts["year_min"] == 2018
    assert pkt.counts["year_max"] == 2020
    assert pkt.counts["distinct_venues"] == 1
    assert len(pkt.source_study_ids) == 3


# ---------- primary_effect --------------------------------------------------

def test_primary_effect_none_when_no_effects() -> None:
    state = EvidenceState.build(topic="t")
    assert compile_primary_effect(state) is None


def test_primary_effect_pools_inverse_variance() -> None:
    state = _full_state(n_studies=3)
    pkt = compile_primary_effect(state)
    assert isinstance(pkt, ResultsPacket)
    assert pkt.packet_id == "primary_effect"
    assert pkt.k_studies == 3
    assert pkt.k_effects == 3
    assert pkt.metric == "log_lifespan_ratio"
    # All effects have se=0.02 so pooled mean equals arithmetic mean
    assert pkt.estimate is not None
    assert abs(pkt.estimate - 0.11) < 1e-9
    assert pkt.ci_low is not None and pkt.ci_high is not None
    assert pkt.ci_low < pkt.estimate < pkt.ci_high


# ---------- moderator_effects -----------------------------------------------

def test_moderator_effects_one_packet_per_level() -> None:
    state = _full_state(n_studies=3)
    packets = compile_moderator_effects(state, "sex")
    ids = {p.packet_id for p in packets}
    assert "moderator_effect.sex.female" in ids
    assert "moderator_effect.sex.male" in ids
    # female has 2 (i=0, 2), male has 1 (i=1)
    by_id = {p.packet_id: p for p in packets}
    assert by_id["moderator_effect.sex.female"].k_studies == 2
    assert by_id["moderator_effect.sex.male"].k_studies == 1


def test_moderator_effects_empty_when_no_effects() -> None:
    state = EvidenceState.build(topic="t")
    assert compile_moderator_effects(state, "sex") == []


# ---------- compile_all -----------------------------------------------------

def test_compile_all_emits_only_supportable_packets() -> None:
    state = _full_state(n_studies=2)
    packets = compile_all(state, moderators=("sex",))
    ids = {p.packet_id for p in packets}
    assert "study_selection" in ids
    assert "corpus_characteristics" in ids
    assert "primary_effect" in ids
    # 2 effects, 1 female + 1 male
    assert "moderator_effect.sex.female" in ids
    assert "moderator_effect.sex.male" in ids


def test_compile_all_skips_primary_when_no_effects() -> None:
    state = EvidenceState.build(topic="t")
    packets = compile_all(state, moderators=("sex",))
    ids = {p.packet_id for p in packets}
    assert "primary_effect" not in ids
    assert "study_selection" in ids
    assert "corpus_characteristics" in ids
