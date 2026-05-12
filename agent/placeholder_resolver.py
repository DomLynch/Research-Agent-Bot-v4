"""Resolve [N_SCREENED] / [N_ACCEPTED] / [K_STUDIES] / [PLACEHOLDER:<key>] markers.

The writer emits four classes of placeholder in body prose:

  [N_SCREENED]            -> eligibility_summary.k_hits
  [N_ACCEPTED]            -> eligibility_summary.k_eligible
  [K_STUDIES]             -> length of strict A-core (canonical primary set)
  [PLACEHOLDER:<key>]     -> topic_pack.placeholders[<key>]

The first three are pipeline-derived counts; the fourth is a topic-pack value
(databases, date-range, query syntax, threshold parameters). All four are
resolved deterministically against receipts + topic-pack data — no LLM, no
invention. Unknown tokens are surfaced as `[<token>][UNRESOLVED]` so the
auditor sees the gap rather than silent omission.

Universal: this module is topic-agnostic. Adding a new domain = adding
`[placeholders]` entries to that topic's TOML. No code change.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent.topic_pack import TopicPack

_TOKEN_RE = re.compile(
    r"\[(N_SCREENED|N_ACCEPTED|K_STUDIES|PLACEHOLDER:[a-zA-Z0-9_\-]+)\]"
)


@dataclass(frozen=True, slots=True)
class ResolvedPlaceholders:
    body: str
    resolved: tuple[str, ...]
    unresolved: tuple[str, ...]


def resolve_placeholders(
    body: str,
    *,
    summary: Mapping[str, Any],
    strict: Mapping[str, Any],
    pack: TopicPack,
) -> ResolvedPlaceholders:
    """Substitute count + topic-pack placeholders.

    `summary` is the parsed `eligibility_summary.json`; `strict` is the parsed
    `primary_effect_input_set_strict.json`. Missing values short-circuit to
    `[UNRESOLVED]` so the auditor can see the gap.
    """
    a_core = strict.get("A_core_direct_lifespan", []) or []
    counts: dict[str, str] = {
        "N_SCREENED": _str_or_empty(summary.get("k_hits")),
        "N_ACCEPTED": _str_or_empty(summary.get("k_eligible")),
        "K_STUDIES": str(len(a_core)) if isinstance(a_core, list) else "",
    }

    resolved: list[str] = []
    unresolved: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in counts:
            val = counts[token]
            if val:
                resolved.append(token)
                return val
            if token not in unresolved:
                unresolved.append(token)
            return match.group(0) + "[UNRESOLVED]"
        if token.startswith("PLACEHOLDER:"):
            key = token[len("PLACEHOLDER:") :]
            if key in pack.placeholders:
                resolved.append(token)
                return pack.placeholders[key]
            if token not in unresolved:
                unresolved.append(token)
            return match.group(0) + "[UNRESOLVED]"
        if token not in unresolved:
            unresolved.append(token)
        return match.group(0) + "[UNRESOLVED]"

    new_body = _TOKEN_RE.sub(_sub, body)
    return ResolvedPlaceholders(
        body=new_body,
        resolved=tuple(resolved),
        unresolved=tuple(unresolved),
    )


def _str_or_empty(value: object) -> str:
    """Map None / missing receipt fields to '' so they surface as UNRESOLVED.

    A legitimate zero count (e.g. k_hits=0) still resolves to "0" — silence
    is reserved for missing keys, not empty results.
    """
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s in {"", "None"} else s
