"""Deterministic Results writer.

Consumes packets (InformationalPacket + ResultsPacket) and emits Section 3
Markdown. Each subsection is either:
  - real prose anchored to packets via [PACKET:id], OR
  - a `[RESULTS_BLOCKED:<reason>]` refusal marker.

Refusal markers are the sanctioned alternative to prose when packets are
missing — the contract gate accepts them. No LLM, no invention: every
sentence reads from packet fields.

Universal: domain-agnostic. Domain-specific subsections (e.g. translational
evidence map) only render when their packet exists; absent packets refuse
silently.
"""
from __future__ import annotations

from collections.abc import Sequence

from agent.results_compiler import InformationalPacket, PacketLike
from agent.results_packets import ResultsPacket


def _find(packets: Sequence[PacketLike], packet_id: str) -> PacketLike | None:
    for p in packets:
        if p.packet_id == packet_id:
            return p
    return None


def _filter_prefix(
    packets: Sequence[PacketLike], prefix: str
) -> list[ResultsPacket]:
    return [
        p for p in packets if isinstance(p, ResultsPacket) and p.packet_id.startswith(prefix)
    ]


def _render_study_selection(p: InformationalPacket) -> str:
    c = p.counts
    return (
        f"Of {c.get('identified', 0)} records identified through systematic "
        f"database search, {c.get('screened_title_abstract', 0)} were screened at "
        f"title and abstract, {c.get('screened_full_text', 0)} were assessed at "
        f"full text, and {c.get('included', 0)} met all inclusion criteria for the "
        f"primary pooled analysis [PACKET:study_selection]."
    )


def _render_corpus(p: InformationalPacket) -> str:
    c = p.counts
    return (
        f"The {c.get('included', 0)} included studies span publication years "
        f"{c.get('year_min', 0)}-{c.get('year_max', 0)} and {c.get('distinct_venues', 0)} "
        f"distinct venues [PACKET:corpus_characteristics]."
    )


def _render_effect(p: ResultsPacket) -> str:
    if p.estimate is None or p.ci_low is None or p.ci_high is None:
        return (
            f"[RESULTS_BLOCKED:packet {p.packet_id} has no estimate — "
            f"upstream stats step pending]"
        )
    return (
        f"The pooled estimate ({p.metric}) was {p.estimate:.3f} "
        f"(95% CI {p.ci_low:.3f} to {p.ci_high:.3f}; k_studies={p.k_studies}, "
        f"k_effects={p.k_effects}) [PACKET:{p.packet_id}]."
    )


def _refuse(reason: str) -> str:
    return f"[RESULTS_BLOCKED:{reason}]"


def write_results_section(packets: Sequence[PacketLike]) -> str:
    """Assemble the Section 3 Markdown body from packets only."""
    parts: list[str] = ["## Results", ""]

    parts.append("### Study Selection")
    ss = _find(packets, "study_selection")
    parts.append(
        _render_study_selection(ss)
        if isinstance(ss, InformationalPacket)
        else _refuse("no study_selection packet")
    )
    parts.append("")

    parts.append("### Corpus Characteristics")
    cc = _find(packets, "corpus_characteristics")
    parts.append(
        _render_corpus(cc)
        if isinstance(cc, InformationalPacket)
        else _refuse("no corpus_characteristics packet")
    )
    parts.append("")

    parts.append("### Primary Pooled Effect")
    pe = _find(packets, "primary_effect")
    parts.append(
        _render_effect(pe)
        if isinstance(pe, ResultsPacket)
        else _refuse("no EffectSizeRecord — effect-extraction step pending")
    )
    parts.append("")

    parts.append("### Moderator Meta-Regression")
    mods = _filter_prefix(packets, "moderator_effect.")
    if mods:
        for m in mods:
            parts.append(_render_effect(m))
    else:
        parts.append(_refuse("no moderator effects — extraction pending"))
    parts.append("")

    parts.append("### Sensitivity Analyses")
    parts.append(_refuse("no sensitivity packets — pending stats step"))
    parts.append("")

    parts.append("### Tension Matrix")
    parts.append(_refuse("no tension_matrix packet — pending moderator pooling"))
    parts.append("")

    parts.append("### Translational Evidence Map")
    parts.append(_refuse("no translational_map packet — pending separate sweep"))
    parts.append("")

    return "\n".join(parts).rstrip() + "\n"
