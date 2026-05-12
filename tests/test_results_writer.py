"""Results-writer tests — deterministic prose + refusal handling."""
from __future__ import annotations

from types import MappingProxyType

from agent.results_compiler import InformationalPacket, PacketLike
from agent.results_contract import validate_results_text
from agent.results_packets import ResultsPacket
from agent.results_writer import write_results_section


def _study_selection_packet() -> InformationalPacket:
    return InformationalPacket(
        packet_id="study_selection",
        description="x",
        counts=MappingProxyType({
            "identified": 50,
            "screened_title_abstract": 50,
            "candidates_after_title_abstract": 12,
            "full_text_availability_located": 0,
            "full_text_parsed": 0,
            "eligibility_decisions_made": 0,
            "eligibility_included": 0,
            "eligibility_excluded": 0,
            "eligibility_unclear": 0,
            "eligible_after_full_text": 0,
        }),
    )


def _selection_with(parsed: int, decisions: int, inc: int, exc: int, unc: int) -> InformationalPacket:
    return InformationalPacket(
        packet_id="study_selection",
        description="x",
        counts=MappingProxyType({
            "identified": 500, "screened_title_abstract": 500,
            "candidates_after_title_abstract": 65,
            "full_text_availability_located": 59,
            "full_text_parsed": parsed,
            "eligibility_decisions_made": decisions,
            "eligibility_included": inc,
            "eligibility_excluded": exc,
            "eligibility_unclear": unc,
            "eligible_after_full_text": inc,
        }),
    )


def test_writer_renders_parsed_pending_branch() -> None:
    pkt = _selection_with(parsed=0, decisions=0, inc=0, exc=0, unc=0)
    text = write_results_section([pkt])
    assert "Open-access full-text availability was located for 59 candidates" in text
    assert "full-text content has not yet been parsed" in text


def test_writer_renders_eligibility_pending_branch() -> None:
    pkt = _selection_with(parsed=45, decisions=0, inc=0, exc=0, unc=0)
    text = write_results_section([pkt])
    assert "full-text content was parsed for 45 of these" in text
    assert "Eligibility assessment has not yet been performed" in text


def test_writer_renders_eligibility_breakdown_when_decisions_made() -> None:
    pkt = _selection_with(parsed=45, decisions=45, inc=18, exc=20, unc=7)
    text = write_results_section([pkt])
    assert "full-text content was parsed for 45 of these" in text
    assert "applied to 45 records" in text
    assert "18 auto-eligible records" in text
    assert "20 excluded" in text
    assert "7 flagged for manual review" in text
    assert "strict A-core" in text and "primary-effect extraction" in text


def _corpus_packet() -> InformationalPacket:
    return InformationalPacket(
        packet_id="corpus_characteristics",
        description="x",
        counts=MappingProxyType({
            "eligible": 12,
            "year_min": 2009,
            "year_max": 2024,
            "distinct_venues": 8,
        }),
    )


def _primary_effect_packet() -> ResultsPacket:
    return ResultsPacket(
        packet_id="primary_effect",
        description="x",
        k_studies=12,
        k_effects=12,
        metric="log_lifespan_ratio",
        moderator_levels={},
        source_effect_ids=tuple((f"s{i}", "o1") for i in range(12)),
        estimate=0.11,
        se=0.02,
        ci_low=0.07,
        ci_high=0.15,
    )


def test_writer_emits_all_subsections() -> None:
    text = write_results_section([_study_selection_packet(), _corpus_packet()])
    for header in (
        "### Study Selection",
        "### Corpus Characteristics",
        "### Primary Pooled Effect",
        "### Moderator Meta-Regression",
        "### Sensitivity Analyses",
        "### Tension Matrix",
        "### Translational Evidence Map",
    ):
        assert header in text


def test_writer_refuses_when_packet_missing() -> None:
    text = write_results_section([_study_selection_packet()])
    assert "[RESULTS_BLOCKED:corpus characterization requires full-text-eligible" in text
    assert "[RESULTS_BLOCKED:no EffectSizeRecord" in text


def test_writer_renders_study_selection_counts() -> None:
    text = write_results_section([_study_selection_packet()])
    assert "50 records identified" in text
    assert "12 were flagged as candidate records for full-text retrieval" in text
    assert "Full-text retrieval has not yet been performed" in text
    assert "[PACKET:study_selection]" in text


def test_writer_refuses_study_selection_when_zero_identified() -> None:
    from types import MappingProxyType
    pkt = InformationalPacket(
        packet_id="study_selection",
        description="x",
        counts=MappingProxyType({
            "identified": 0, "screened_title_abstract": 0,
            "candidates_after_title_abstract": 0,
            "full_text_availability_located": 0,
            "eligibility_decisions_made": 0,
            "eligible_after_full_text": 0,
        }),
    )
    text = write_results_section([pkt])
    assert "[RESULTS_BLOCKED:retrieval returned zero records" in text


def test_writer_renders_primary_effect_when_available() -> None:
    text = write_results_section([
        _study_selection_packet(), _corpus_packet(), _primary_effect_packet()
    ])
    assert "0.110" in text
    assert "95% CI 0.070 to 0.150" in text
    assert "[PACKET:primary_effect]" in text


def test_writer_output_passes_contract_when_packets_exist() -> None:
    packets: list[PacketLike] = [
        _study_selection_packet(), _corpus_packet(), _primary_effect_packet()
    ]
    text = write_results_section(packets)
    violations = validate_results_text(text, packets)
    assert violations == [], f"unexpected violations: {violations}"


def test_writer_minimal_output_passes_contract_with_refusals() -> None:
    packets: list[PacketLike] = [_study_selection_packet(), _corpus_packet()]
    text = write_results_section(packets)
    violations = validate_results_text(text, packets)
    assert violations == [], (
        f"refusal markers should pass silently; got: {violations}"
    )
