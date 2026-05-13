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
    # Sprint 12.7: A-core records that didn't contribute to the pool —
    # set difference A_core \\ pool.effects. Distinct from SKIPPED_IDS
    # (which is the full pool.skipped, including C-lane records).
    r"|A_CORE_NOT_POOLED_IDS|A_CORE_NOT_POOLED_COUNT"
    r"|A_CORE_NOT_POOLED_COUNT:[a-z]+"
    # Sprint 12.8.3: per-study skip-reason annotation. Derived from
    # the extraction receipts + pack.preferred_metric_families so the
    # prose never claims a record failed for a reason that doesn't
    # apply to it (e.g. labelling s288 with off-modal-metric when the
    # actual failure is parse_failed).
    r"|A_CORE_NOT_POOLED_REASONS"
    r"|POOL_ESTIMATE|POOL_CI_LOW|POOL_CI_HIGH"
    r"|POOL_RATIO_BACK|POOL_PERCENT_EXT"
    # Count-aware noun-agreement: e.g. [B_LANE_COUNT:study] -> "1 study"
    # at n=1 or "3 studies" at n=3. Universal English pluralisation.
    r"|A_CORE_COUNT:[a-z]+|B_LANE_COUNT:[a-z]+|C_LANE_COUNT:[a-z]+"
    r"|K_POOLABLE_COUNT:[a-z]+|POOL_EFFECT_COUNT:[a-z]+"
    r"|PLACEHOLDER:[a-zA-Z0-9_\-]+"
    r"|MODERATOR_P:[a-zA-Z0-9_\-]+)\]"
)


def _classify_skip_reason(
    receipt: Mapping[str, Any], preferred_families: tuple[str, ...],
) -> str:
    """Derive a single per-receipt skip-reason label from the extraction
    receipt + the pack's preferred metric families.

    Universal: every topic's extractor emits the same receipt shape
    (`status`, `metric`, `treated_n`, `control_n`), so the same
    classifier maps any pack's receipts to one of the four labels.

    Labels (priority order — earlier wins):
      * 'parse_failed' / 'llm_refused' / 'no_extracted' — receipt
        status said extraction never produced numerics
      * 'off-modal-metric' — extraction succeeded but the chosen metric
        family is outside the pack's preferred_metric_families list
        (so the inverse-variance pool intentionally skipped it to
        keep the pool within one metric family)
      * 'no_numerics' — extraction succeeded on a preferred metric
        family but the inverse-variance pool needs treated_n /
        control_n and the receipt lacks either
      * 'unpoolable' — fallback when none of the above fire
    """
    status = str(receipt.get("status", "") or "").strip()
    if status and status != "extracted":
        return status
    metric = str(receipt.get("metric", "") or "").strip()
    if (
        preferred_families
        and metric
        and not any(metric.startswith(f) or f.startswith(metric)
                    for f in preferred_families)
    ):
        return "off-modal-metric"
    if receipt.get("treated_n") is None or receipt.get("control_n") is None:
        return "no_numerics"
    return "unpoolable"


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
    pool_effect_id_set = set(pool_effect_ids)
    # A-core records that didn't make the pool (parse_failed / off-modal
    # / no_numerics). Preserves first-seen order from strict.A_core list.
    a_core_not_pooled_ids = [
        sid for sid in a_core_ids if sid not in pool_effect_id_set
    ]
    # Build per-study skip-reason annotation by looking up each
    # unpooled A-core ID in the extraction receipts. Universal — the
    # classifier reads the pack's preferred_metric_families to decide
    # what counts as off-modal, so adding a new topic with a different
    # metric vocabulary needs no code change.
    receipts_by_id: dict[str, Mapping[str, Any]] = {
        str(r.get("study_id", "")): r
        for r in (extractions or {}).get("receipts", []) or []
        if isinstance(r, dict) and r.get("study_id")
    }
    a_core_not_pooled_reasons_parts: list[str] = []
    for sid in a_core_not_pooled_ids:
        r = receipts_by_id.get(sid, {})
        reason = _classify_skip_reason(r, pack.preferred_metric_families)
        a_core_not_pooled_reasons_parts.append(f"{sid}: {reason}")
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
    # 12.9.E/G: POOL_* from legacy summary OR effects[]; k=0 renders prose.
    import math
    _ps = (pool or {}).get("pooled_a_core_summary")
    _keys = ("POOL_ESTIMATE", "POOL_CI_LOW", "POOL_CI_HIGH", "POOL_RATIO_BACK", "POOL_PERCENT_EXT")
    pool_tokens: dict[str, str] = dict(zip(_keys, ("not estimable", "—", "—", "—", "k=0"), strict=True))
    _est: float | None = None
    if isinstance(_ps, dict):
        try:
            _est = float(_ps.get("estimate", 0.0))
            _ci_low = float(_ps.get("ci_low", 0.0))
            _ci_high = float(_ps.get("ci_high", 0.0))
            _ratio_back = float(_ps.get("median_ratio_back") or math.exp(_est))
        except (TypeError, ValueError):
            _est = None
    else:
        _valid: list[tuple[float, float]] = [
            (float(e["estimate"]), float(e.get("se") or 0.0))
            for e in (pool_effects or ())
            if isinstance(e, dict) and e.get("estimate") is not None
            and isinstance(e.get("se"), int | float) and float(e["se"]) > 0
        ]
        if _valid:
            if len(_valid) == 1:
                _est, _se = _valid[0]
            else:
                _w = [1.0 / (s * s) for _, s in _valid]
                _est = sum(w * e for w, (e, _) in zip(_w, _valid, strict=True)) / sum(_w)
                _se = math.sqrt(1.0 / sum(_w))
            _ci_low, _ci_high = _est - 1.96 * _se, _est + 1.96 * _se
            _ratio_back = math.exp(_est)
    if _est is not None:
        pool_tokens = dict(zip(_keys, (
            f"{_est:.3f}", f"{_ci_low:.3f}", f"{_ci_high:.3f}",
            f"{_ratio_back:.2f}", f"~{(_ratio_back - 1.0) * 100.0:.0f}%",
        ), strict=True))

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
        "A_CORE_NOT_POOLED_IDS": (
            ", ".join(a_core_not_pooled_ids) if a_core_not_pooled_ids
            else ("(none)" if pool is not None else "")
        ),
        "A_CORE_NOT_POOLED_COUNT": (
            str(len(a_core_not_pooled_ids)) if pool is not None else ""
        ),
        "A_CORE_NOT_POOLED_REASONS": (
            ", ".join(a_core_not_pooled_reasons_parts)
            if a_core_not_pooled_reasons_parts
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
        "A_CORE_NOT_POOLED_COUNT": (
            len(a_core_not_pooled_ids) if pool is not None else 0
        ),
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
