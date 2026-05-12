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
    r"|B_LANE_COUNT|B_LANE_IDS|C_LANE_COUNT|C_LANE_IDS"
    r"|K_POOLABLE|INCOMPLETE_RECOVERY_IDS"
    # Sprint 12.6: pool-effect tokens (what's IN the pool, not just
    # A-core). Critical to keep pool prose from naming A-core members
    # that aren't actually contributing effects.
    r"|POOL_EFFECT_IDS|POOL_EFFECT_COUNT|SKIPPED_IDS"
    r"|POOL_ESTIMATE|POOL_CI_LOW|POOL_CI_HIGH"
    r"|POOL_RATIO_BACK|POOL_PERCENT_EXT"
    # Count-aware noun-agreement: e.g. [B_LANE_COUNT:study] -> "1 study"
    # at n=1 or "3 studies" at n=3. Universal English pluralisation.
    r"|A_CORE_COUNT:[a-z]+|B_LANE_COUNT:[a-z]+|C_LANE_COUNT:[a-z]+"
    r"|K_POOLABLE_COUNT:[a-z]+|POOL_EFFECT_COUNT:[a-z]+"
    r"|PLACEHOLDER:[a-zA-Z0-9_\-]+"
    r"|MODERATOR_P:[a-zA-Z0-9_\-]+)\]"
)


def _pluralise(noun: str, n: int) -> str:
    """Universal English pluralisation: study -> studies, record -> records,
    effect -> effects, etc. Used by [<LANE>_COUNT:<noun>] tokens for
    grammatical agreement (count + noun) in receipt-driven prose."""
    if n == 1:
        return noun
    if noun.endswith("y") and (len(noun) < 2 or noun[-2] not in "aeiou"):
        return noun[:-1] + "ies"
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return noun + "es"
    return noun + "s"


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
    def _lane_ids(key: str) -> tuple[list[dict[str, Any]], list[str]]:
        raw = strict.get(key, []) or []
        items = raw if isinstance(raw, list) else []
        ids = [
            str(s.get("study_id", "")) for s in items
            if isinstance(s, dict) and s.get("study_id")
        ]
        return items, ids

    a_core_list, a_core_ids = _lane_ids("A_core_direct_lifespan")
    b_lane_list, b_lane_ids = _lane_ids("B_disease_model_survival")
    c_lane_list, c_lane_ids = _lane_ids("C_secondary_contextual")
    pool_effects = (pool or {}).get("effects", []) or []
    if not isinstance(pool_effects, list):
        pool_effects = []
    pool_effect_ids = [
        str(e.get("study_id", "")) for e in pool_effects
        if isinstance(e, dict) and e.get("study_id")
    ]
    pool_skipped_ids: list[str] = []
    if pool is not None:
        raw_skip = pool.get("skipped_study_ids") or []
        if isinstance(raw_skip, list):
            pool_skipped_ids = [str(s) for s in raw_skip if s]
    extr_receipts = (extractions or {}).get("receipts", []) or []
    if not isinstance(extr_receipts, list):
        extr_receipts = []
    # "Incomplete recovery" = any study that DIDN'T contribute to the
    # pool. That's the union of:
    #   - parse_failed / no_numerics / llm_refused receipts (no numerics)
    #   - extracted receipts that the pool compiler skipped (e.g. wrong
    #     metric family — off-modal-metric demotion)
    # pool.skipped_study_ids is the canonical "no contribution" list
    # produced by compile_pool; we fall back to status-based detection
    # when no pool was supplied.
    pool_skipped: list[str] = []
    if pool is not None:
        raw_skip = pool.get("skipped_study_ids") or []
        if isinstance(raw_skip, list):
            pool_skipped = [str(s) for s in raw_skip if s]
    status_failed = [
        str(r.get("study_id", "")) for r in extr_receipts
        if isinstance(r, dict)
        and r.get("study_id")
        and r.get("status") not in {"extracted"}
    ]
    # Deduplicate while preserving first-seen order from pool_skipped
    # (pool order is more meaningful than receipt order for the prose).
    seen: set[str] = set()
    incomplete_ids: list[str] = []
    for sid in [*pool_skipped, *status_failed]:
        if sid and sid not in seen:
            seen.add(sid)
            incomplete_ids.append(sid)
    # Pool point-estimate tokens — derived from the meta-analytic summary
    # that compile_pool produces (or a callers can supply equivalent).
    # Universal: every topic's pool emits the same numeric shape, so the
    # tokens drift with the receipts and never with the topic.
    import math
    pool_summary = (pool or {}).get("pooled_a_core_summary")
    if isinstance(pool_summary, dict):
        try:
            est = float(pool_summary.get("estimate", 0.0))
            ci_low = float(pool_summary.get("ci_low", 0.0))
            ci_high = float(pool_summary.get("ci_high", 0.0))
            ratio_back = float(
                pool_summary.get("median_ratio_back") or math.exp(est)
            )
            pct_ext = (ratio_back - 1.0) * 100.0
            pool_tokens: dict[str, str] = {
                "POOL_ESTIMATE": f"{est:.3f}",
                "POOL_CI_LOW": f"{ci_low:.3f}",
                "POOL_CI_HIGH": f"{ci_high:.3f}",
                "POOL_RATIO_BACK": f"{ratio_back:.2f}",
                "POOL_PERCENT_EXT": f"~{pct_ext:.0f}%",
            }
        except (TypeError, ValueError):
            pool_tokens = dict.fromkeys(
                ("POOL_ESTIMATE", "POOL_CI_LOW", "POOL_CI_HIGH",
                 "POOL_RATIO_BACK", "POOL_PERCENT_EXT"), "",
            )
    else:
        pool_tokens = dict.fromkeys(
            ("POOL_ESTIMATE", "POOL_CI_LOW", "POOL_CI_HIGH",
             "POOL_RATIO_BACK", "POOL_PERCENT_EXT"), "",
        )

    counts: dict[str, str] = {
        "N_SCREENED": _str_or_empty(summary.get("k_hits")),
        "N_ACCEPTED": _str_or_empty(summary.get("k_eligible")),
        "K_STUDIES": str(len(a_core_list)),
        "STRICT_A_CORE_COUNT": str(len(a_core_list)),
        "STRICT_A_CORE_IDS": ", ".join(a_core_ids) if a_core_ids else "",
        "B_LANE_COUNT": str(len(b_lane_list)),
        "B_LANE_IDS": ", ".join(b_lane_ids) if b_lane_ids else "(none)",
        "C_LANE_COUNT": str(len(c_lane_list)),
        "C_LANE_IDS": ", ".join(c_lane_ids) if c_lane_ids else "(none)",
        "K_POOLABLE": str(len(pool_effects)) if pool is not None else "",
        # Pool-effect tokens — only studies that actually contributed to
        # the inverse-variance pool (NOT the full A-core list). Critical
        # to keep pool prose from naming parse_failed / off-modal studies.
        "POOL_EFFECT_IDS": ", ".join(pool_effect_ids) if pool_effect_ids else "(none)",
        "POOL_EFFECT_COUNT": str(len(pool_effect_ids)) if pool is not None else "",
        "SKIPPED_IDS": (
            ", ".join(pool_skipped_ids) if pool_skipped_ids
            else ("(none)" if pool is not None else "")
        ),
        "INCOMPLETE_RECOVERY_IDS": (
            ", ".join(incomplete_ids) if incomplete_ids
            else ("(none)" if extractions is not None else "")
        ),
        **pool_tokens,
    }

    resolved: list[str] = []
    unresolved: list[str] = []

    # Count-aware noun-agreement counts keyed by lane.
    lane_counts: dict[str, int] = {
        "A_CORE_COUNT": len(a_core_list),
        "B_LANE_COUNT": len(b_lane_list),
        "C_LANE_COUNT": len(c_lane_list),
        "K_POOLABLE_COUNT": len(pool_effects) if pool is not None else 0,
        "POOL_EFFECT_COUNT": len(pool_effect_ids) if pool is not None else 0,
    }

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        # Count-aware noun-agreement: e.g. "B_LANE_COUNT:study".
        for prefix, n in lane_counts.items():
            cf_prefix = f"{prefix}:"
            if token.startswith(cf_prefix):
                noun = token[len(cf_prefix):]
                if noun:
                    resolved.append(token)
                    return f"{n} {_pluralise(noun, n)}"
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
