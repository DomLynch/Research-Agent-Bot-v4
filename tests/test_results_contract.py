"""Results-contract gate tests."""
from __future__ import annotations

from types import MappingProxyType

from agent.results_compiler import InformationalPacket
from agent.results_contract import is_refusal, validate_results_text
from agent.results_packets import ResultsPacket


def _info_packet() -> InformationalPacket:
    return InformationalPacket(
        packet_id="study_selection",
        description="counts",
        counts=MappingProxyType({"identified": 50, "included": 12}),
    )


def _effect_packet(packet_id: str = "primary_effect") -> ResultsPacket:
    return ResultsPacket(
        packet_id=packet_id,
        description="x",
        k_studies=3,
        k_effects=3,
        metric="log_lifespan_ratio",
        moderator_levels={},
        source_effect_ids=(("s1", "o1"), ("s2", "o1"), ("s3", "o1")),
        estimate=0.11,
        se=0.015,
        ci_low=0.08,
        ci_high=0.14,
    )


def _no_estimate_packet() -> ResultsPacket:
    return ResultsPacket(
        packet_id="primary_effect_no_estimate",
        description="x",
        k_studies=1,
        k_effects=1,
        metric="log_lifespan_ratio",
        moderator_levels={},
        source_effect_ids=(("s1", "o1"),),
        estimate=None,
        se=None,
        ci_low=None,
        ci_high=None,
    )


# ---------- refusal mode ----------------------------------------------------

def test_refusal_passes_with_zero_violations() -> None:
    text = "[RESULTS_BLOCKED:insufficient EffectSizeRecords]"
    assert validate_results_text(text, packets=[]) == []
    assert is_refusal(text) is True


def test_non_refusal_text_is_not_refusal() -> None:
    assert is_refusal("Across studies, the pooled estimate was X.") is False


# ---------- unknown packet id ----------------------------------------------

def test_cited_unknown_packet_id_fires() -> None:
    text = "See [PACKET:ghost_packet] for details."
    v = validate_results_text(text, packets=[_info_packet()])
    assert any("ghost_packet" in x.message for x in v)


# ---------- numeric-without-citation rule ----------------------------------

def test_bare_numeric_claim_without_packet_fires() -> None:
    text = "The included corpus represented 30% of identified records."
    v = validate_results_text(text, packets=[_info_packet()])
    assert any("numeric claim without" in x.message for x in v)


def test_numeric_claim_with_packet_passes() -> None:
    text = "The included corpus represented 30% of identified records [PACKET:study_selection]."
    assert validate_results_text(text, packets=[_info_packet()]) == []


# ---------- magnitude-without-effect rule ----------------------------------

def test_magnitude_word_without_packet_fires() -> None:
    text = "Rapamycin produced a robust extension of survival."
    v = validate_results_text(text, packets=[_effect_packet()])
    assert any("magnitude claim without" in x.message for x in v)


def test_magnitude_word_with_effect_packet_passes() -> None:
    text = "Rapamycin produced a robust extension of survival [PACKET:primary_effect]."
    assert validate_results_text(text, packets=[_effect_packet()]) == []


def test_magnitude_word_with_no_estimate_packet_fires() -> None:
    # Even though packet is cited, it has no effect/CI -> can't back magnitude claim
    text = "Rapamycin produced a robust extension [PACKET:primary_effect_no_estimate]."
    v = validate_results_text(text, packets=[_no_estimate_packet()])
    assert any("magnitude claim without ResultsPacket (effect + CI)" in x.message for x in v)


# ---------- pooled-statement rule ------------------------------------------

def test_pooled_statement_without_results_packet_fires() -> None:
    text = "The pooled estimate suggested a positive trend [PACKET:study_selection]."
    v = validate_results_text(text, packets=[_info_packet()])
    assert any("pooled statement without" in x.message for x in v)


def test_pooled_statement_with_results_packet_passes() -> None:
    text = "The pooled estimate suggested a positive trend [PACKET:primary_effect]."
    assert validate_results_text(text, packets=[_effect_packet()]) == []


# ---------- clean prose passes ---------------------------------------------

def test_clean_prose_with_proper_citations_passes() -> None:
    text = (
        "Of 50 identified records, 12 met inclusion criteria [PACKET:study_selection]. "
        "Across these studies the pooled estimate was 0.11 (95% CI 0.08 to 0.14) "
        "[PACKET:primary_effect]."
    )
    v = validate_results_text(text, packets=[_info_packet(), _effect_packet()])
    assert v == []
