"""Resolve [CIT:<key>|<role>] markers into numbered references.

The writer emits citation markers of the form `[CIT:<anchor-key>|<role>]`
in body prose. This module:
  - finds every marker in a paper body,
  - resolves each `<anchor-key>` against `TopicPack.references_bibliography`,
  - assigns a stable numeric label in first-appearance order,
  - returns the body with markers replaced by `[N]` and a separate
    rendered References section.

Universal: bibliography entries live in `topic_packs/<topic>.toml`, not
in Python. Domain-agnostic; adding a new topic = adding a TOML section.
Unknown anchor keys are surfaced as `[CIT:<key>|<role>][UNRESOLVED]` so
auditors see the gap rather than silently dropping the citation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.topic_pack import TopicPack

_CIT_RE = re.compile(r"\[CIT:([a-zA-Z0-9_\-\.]+)\|([a-zA-Z0-9_\-]+)\]")


@dataclass(frozen=True, slots=True)
class ResolvedReferences:
    """Body text with [N] markers in place of [CIT:...] markers, plus the
    rendered References section."""

    body: str
    references_section: str
    citations_used: tuple[str, ...]  # anchor keys in first-appearance order
    unresolved: tuple[str, ...]      # anchor keys missing from bibliography


def resolve_citations(body: str, pack: TopicPack) -> ResolvedReferences:
    """Walk every [CIT:<key>|<role>] in `body`, assign first-seen numbers,
    rewrite inline as [N], and emit a References section.

    Multiple markers with the same key collapse to a single number.
    Unknown keys are preserved with an [UNRESOLVED] tag so reviewers can
    see what would need to be added to the topic-pack bibliography
    before submission. The function never silently drops a citation.
    """
    biblio = pack.references_bibliography
    seen: dict[str, int] = {}     # key -> assigned number
    order: list[str] = []
    unresolved: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in biblio:
            if key not in seen:
                order.append(key)
                seen[key] = len(order)
            return f"[{seen[key]}]"
        if key not in unresolved:
            unresolved.append(key)
        return match.group(0) + "[UNRESOLVED]"

    new_body = _CIT_RE.sub(_sub, body)

    if not order and not unresolved:
        return ResolvedReferences(
            body=new_body, references_section="",
            citations_used=(), unresolved=(),
        )

    lines: list[str] = ["## References", ""]
    for n, key in enumerate(order, start=1):
        entry = biblio[key]
        lines.append(f"{n}. {entry}")
    if unresolved:
        lines.append("")
        lines.append(
            "### Unresolved citation keys "
            "(add bibliography entries to the topic pack before submission):"
        )
        for key in unresolved:
            lines.append(f"- {key}")
    references_section = "\n".join(lines) + "\n"

    return ResolvedReferences(
        body=new_body, references_section=references_section,
        citations_used=tuple(order), unresolved=tuple(unresolved),
    )
