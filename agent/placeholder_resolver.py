"""Resolve count + topic-pack-driven placeholder markers.

The writer emits several classes of placeholder in body prose:

  [N_SCREENED]            -> eligibility_summary.k_hits
  [N_ACCEPTED]            -> eligibility_summary.k_eligible
  [K_STUDIES]             -> length of strict A-core (canonical primary set)
  [STRICT_A_CORE_COUNT]   -> len(strict.A_core_direct_lifespan) — alias
  [STRICT_A_CORE_IDS]     -> comma-joined study_ids from strict A-core
  [K_POOLABLE]            -> len(pool.effects) — contract-passing pool size
  [INCOMPLETE_RECOVERY_IDS] -> comma-joined study_ids whose extraction
                              status != "extracted" (parse_failed,
                              no_numerics, llm_refused, etc.)
  [PLACEHOLDER:<key>]     -> topic_pack.placeholders["<key>"]
  [MODERATOR_P:<key>]     -> topic_pack.placeholders["MODERATOR_P:<key>"]

The count tokens + corpus-derived tokens are pipeline-derived; the
PLACEHOLDER / MODERATOR_P families are topic-pack values. All resolve
deterministically against receipts + topic-pack data — no LLM, no
invention. Unknown tokens are surfaced as `[<token>][UNRESOLVED]` so
the auditor sees the gap rather than silent omission. `[CIT:...]` and
`[PACKET:...]` markers are intentionally left alone — citations are
handled by `reference_resolver`, and packet anchors are audit
references the manuscript keeps verbatim.

Universal: this module is topic-agnostic. The corpus-derived tokens
(STRICT_A_CORE_*, K_POOLABLE, INCOMPLETE_RECOVERY_IDS) compute from
receipts only — adding a new domain = adding receipts; no code change.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent.topic_pack import TopicPack

_TOKEN_RE = re.compile(
    r"\[(N_SCREENED|N_ACCEPTED|K_STUDIES"
    r"|STRICT_A_CORE_COUNT|STRICT_A_CORE_IDS"
    r"|K_POOLABLE|INCOMPLETE_RECOVERY_IDS"
    r"|PLACEHOLDER:[a-zA-Z0-9_\-]+"
    r"|MODERATOR_P:[a-zA-Z0-9_\-]+)\]"
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
    extractions: Mapping[str, Any] | None = None,
    pool: Mapping[str, Any] | None = None,
) -> ResolvedPlaceholders:
    """Substitute count + topic-pack + corpus-derived placeholders.

    `summary` is the parsed `eligibility_summary.json`; `strict` is the
    parsed `primary_effect_input_set_strict.json`. `extractions` and
    `pool` are optional — when supplied, the corpus-derived tokens
    (STRICT_A_CORE_IDS, K_POOLABLE, INCOMPLETE_RECOVERY_IDS) resolve
    from real receipts; when None, those tokens surface as UNRESOLVED.
    Missing values short-circuit to `[UNRESOLVED]` so the auditor sees
    the gap.
    """
    a_core_list = strict.get("A_core_direct_lifespan", []) or []
    if not isinstance(a_core_list, list):
        a_core_list = []
    a_core_ids = [
        str(s.get("study_id", "")) for s in a_core_list
        if isinstance(s, dict) and s.get("study_id")
    ]
    pool_effects = (pool or {}).get("effects", []) or []
    if not isinstance(pool_effects, list):
        pool_effects = []
    extr_receipts = (extractions or {}).get("receipts", []) or []
    if not isinstance(extr_receipts, list):
        extr_receipts = []
    incomplete_ids = [
        str(r.get("study_id", "")) for r in extr_receipts
        if isinstance(r, dict)
        and r.get("study_id")
        and r.get("status") not in {"extracted"}
    ]
    counts: dict[str, str] = {
        "N_SCREENED": _str_or_empty(summary.get("k_hits")),
        "N_ACCEPTED": _str_or_empty(summary.get("k_eligible")),
        "K_STUDIES": str(len(a_core_list)),
        "STRICT_A_CORE_COUNT": str(len(a_core_list)),
        "STRICT_A_CORE_IDS": ", ".join(a_core_ids) if a_core_ids else "",
        "K_POOLABLE": str(len(pool_effects)) if pool is not None else "",
        "INCOMPLETE_RECOVERY_IDS": (
            ", ".join(incomplete_ids) if incomplete_ids
            else ("(none)" if extractions is not None else "")
        ),
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
        if token.startswith("MODERATOR_P:"):
            # MODERATOR_P keys are stored verbatim (prefix + name) so a
            # single `[placeholders]` table covers both families.
            if token in pack.placeholders:
                resolved.append(token)
                return pack.placeholders[token]
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
