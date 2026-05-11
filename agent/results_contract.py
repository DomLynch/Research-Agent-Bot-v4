"""Results-prose contract gate.

Every numeric, comparative, or magnitude claim in Section 3 must cite a
`[PACKET:<id>]` that resolves to an available packet, and the cited packet
must structurally support the claim:

  - Magnitude adjectives ("robust", "significant", "larger", ...) require a
    `ResultsPacket` with both `estimate` and `ci_low` populated.
  - Pooled statements require a `ResultsPacket` with `k_studies` and
    `k_effects` both >= 1.
  - Bare numeric literals (%, p-value, k=N) require any packet citation.

A single `[RESULTS_BLOCKED:<reason>]` marker as the entire body is the
sanctioned refusal output (zero violations). This gate is what blocks
ungrounded Results prose at compile time.

Universal: this module is domain-agnostic. Packet IDs are the unit of
provenance.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from agent.claim_gates import GateViolation
from agent.results_compiler import InformationalPacket, PacketLike
from agent.results_packets import ResultsPacket

_PACKET_REF = re.compile(r"\[PACKET:([^\]]+)\]")
_REFUSAL = re.compile(r"^\s*\[RESULTS_BLOCKED:[^\]]+\]\s*$")
_NUMERIC = re.compile(r"\b\d+(?:\.\d+)?\s*%|\bp\s*[<=>]\s*0?\.\d+|\bk\s*=\s*\d+")
_MAGNITUDE = re.compile(
    r"\b(?:robust(?:ly)?|significant(?:ly)?|substantial(?:ly)?|consistent(?:ly)?|"
    r"larger|smaller|stronger|weaker|greater)\b",
    re.IGNORECASE,
)
_POOLED = re.compile(
    r"\bpooled\s+(?:estimate|effect|mean)\b|\bmeta-?analytic\s+(?:mean|estimate)\b",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", text)
    return [s.strip() for s in raw if s.strip()]


def _record(
    violations: list[GateViolation], rule: str, sent: str
) -> None:
    excerpt = sent if len(sent) <= 140 else sent[:137] + "…"
    violations.append(
        GateViolation(
            gate="results_contract",
            location="RESULTS",
            message=f"{rule}: {excerpt!r}",
        )
    )


def validate_results_text(
    text: str, packets: Sequence[PacketLike]
) -> list[GateViolation]:
    """Police a Results section against the available packets."""
    if _REFUSAL.match(text.strip()):
        return []

    available: dict[str, PacketLike] = {p.packet_id: p for p in packets}
    violations: list[GateViolation] = []

    for cited in set(_PACKET_REF.findall(text)):
        if cited not in available:
            violations.append(
                GateViolation(
                    gate="results_contract",
                    location="RESULTS",
                    message=f"[PACKET:{cited}] not in available packets",
                )
            )

    for sent in _split_sentences(text):
        ids = _PACKET_REF.findall(sent)
        cited_packets = [available[c] for c in ids if c in available]

        if _NUMERIC.search(sent) and not ids:
            _record(violations, "numeric claim without [PACKET:] citation", sent)

        if _MAGNITUDE.search(sent):
            backed = any(
                isinstance(p, ResultsPacket)
                and p.estimate is not None
                and p.ci_low is not None
                for p in cited_packets
            )
            if not backed:
                _record(
                    violations,
                    "magnitude claim without ResultsPacket (effect + CI)",
                    sent,
                )

        if _POOLED.search(sent):
            backed = any(
                isinstance(p, ResultsPacket) and p.k_studies >= 1 and p.k_effects >= 1
                for p in cited_packets
            )
            if not backed:
                _record(
                    violations,
                    "pooled statement without backing ResultsPacket",
                    sent,
                )

    return violations


def is_refusal(text: str) -> bool:
    return bool(_REFUSAL.match(text.strip()))


__all__ = [
    "InformationalPacket",
    "is_refusal",
    "validate_results_text",
]
