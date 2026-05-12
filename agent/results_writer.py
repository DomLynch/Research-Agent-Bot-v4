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
    identified = c.get("identified", 0)
    if identified == 0:
        return _refuse(
            "retrieval returned zero records - query or source configuration "
            "may be broken"
        )
    ta_screened = c.get("screened_title_abstract", 0)
    candidates = c.get("candidates_after_title_abstract", 0)
    availability = c.get("full_text_availability_located", 0)
    parsed = c.get("full_text_parsed", 0)
    decisions = c.get("eligibility_decisions_made", 0)
    included = c.get("eligibility_included", 0)
    excluded = c.get("eligibility_excluded", 0)
    unclear = c.get("eligibility_unclear", 0)

    prefix = (
        f"Of {identified} records identified through systematic database "
        f"search, {ta_screened} were screened at title/abstract level; "
        f"{candidates} were flagged as candidate records for full-text retrieval."
    )

    if availability == 0:
        return (
            f"{prefix} Full-text retrieval has not yet been performed; therefore, "
            f"no studies are currently classified as full-text eligible for the "
            f"primary pooled analysis [PACKET:study_selection]."
        )

    if parsed == 0:
        return (
            f"{prefix} Open-access full-text availability was located for "
            f"{availability} candidates; however, full-text content has not yet "
            f"been parsed, so no studies are currently classified as full-text "
            f"eligible for the primary pooled analysis [PACKET:study_selection]."
        )

    if decisions == 0:
        return (
            f"{prefix} Open-access full-text availability was located for "
            f"{availability} candidates; full-text content was parsed for "
            f"{parsed} of these. Eligibility assessment has not yet been "
            f"performed; therefore, no studies are currently classified as "
            f"full-text eligible for the primary pooled analysis "
            f"[PACKET:study_selection]."
        )

    return (
        f"{prefix} Open-access full-text availability was located for "
        f"{availability} candidates; full-text content was parsed for "
        f"{parsed} of these. Pre-specified eligibility adjudication was "
        f"applied to {decisions} parsed records, yielding {included} included, "
        f"{excluded} excluded, and {unclear} flagged for manual review of "
        f"low-confidence or rule-judge conflicts for the primary pooled "
        f"analysis [PACKET:study_selection]."
    )


def _render_corpus(p: InformationalPacket) -> str:
    c = p.counts
    return (
        f"The {c.get('eligible', 0)} eligible studies span publication years "
        f"{c.get('year_min', 0)}-{c.get('year_max', 0)} and {c.get('distinct_venues', 0)} "
        f"distinct venues [PACKET:corpus_characteristics]."
    )


def _render_sentinel_recall(p: InformationalPacket) -> str:
    c = p.counts
    pri_n = c.get("expected_primary", 0)
    pri_r = c.get("retrieved_primary", 0)
    pri_c = c.get("candidate_primary", 0)
    pri_inc = c.get("included_primary", 0)
    meta_n = c.get("expected_prior_meta", 0)
    meta_r = c.get("retrieved_prior_meta", 0)
    # Three-level gate: PASS only if every primary sentinel is auto-
    # contract-passed OR manually marked resolved_unavailable/excluded;
    # WARN if retrieved but unresolved (system retrieval/parser owes
    # work); FAIL if any primary was never retrieved at all.
    if c.get("gate_passes", 0):
        gate = "PASS"
    elif pri_r < pri_n:
        gate = "FAIL"
    else:
        gate = "WARN"
    # Surface unresolved-pending sentinels in the audit line so the
    # prose doesn't pretend everything is fine; these are system-bug
    # surface area (retrieval/parser owes the bytes).
    pending = [n for n in p.notes if "resolved_available_pending" in n]
    pending_note = (
        f" {len(pending)} primary sentinel(s) located but retrieval/parser"
        " did not yield contract-passing evidence — system-level gap."
        if pending else ""
    )
    return (
        f"Sentinel-paper recall audit (gate: {gate}): "
        f"{pri_r}/{pri_n} canonical primary-study anchors retrieved, "
        f"{pri_c} promoted to candidate set, {pri_inc} contract-passed include; "
        f"{meta_r}/{meta_n} prior meta-analysis anchors retrieved.{pending_note} "
        f"[PACKET:sentinel_recall]"
    )


def _render_effect(p: ResultsPacket) -> str:
    if p.estimate is None or p.ci_low is None or p.ci_high is None:
        return (
            f"[RESULTS_BLOCKED:packet {p.packet_id} has no estimate - "
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

    sr = _find(packets, "sentinel_recall")
    if isinstance(sr, InformationalPacket):
        parts.append("### Sentinel Recall Audit")
        parts.append(_render_sentinel_recall(sr))
        parts.append("")

    parts.append("### Corpus Characteristics")
    cc = _find(packets, "corpus_characteristics")
    parts.append(
        _render_corpus(cc)
        if isinstance(cc, InformationalPacket)
        else _refuse(
            "corpus characterization requires full-text-eligible studies; "
            "current state has only title/abstract candidates"
        )
    )
    parts.append("")

    parts.append("### Primary Pooled Effect")
    pe = _find(packets, "primary_effect")
    parts.append(
        _render_effect(pe)
        if isinstance(pe, ResultsPacket)
        else _refuse("no EffectSizeRecord - effect-extraction step pending")
    )
    parts.append("")

    parts.append("### Moderator Meta-Regression")
    mods = _filter_prefix(packets, "moderator_effect.")
    if mods:
        for m in mods:
            parts.append(_render_effect(m))
    else:
        parts.append(_refuse("no moderator effects - extraction pending"))
    parts.append("")

    parts.append("### Sensitivity Analyses")
    parts.append(_refuse("no sensitivity packets - pending stats step"))
    parts.append("")

    parts.append("### Tension Matrix")
    parts.append(_refuse("no tension_matrix packet - pending moderator pooling"))
    parts.append("")

    parts.append("### Translational Evidence Map")
    parts.append(_refuse("no translational_map packet - pending separate sweep"))
    parts.append("")

    return "\n".join(parts).rstrip() + "\n"
