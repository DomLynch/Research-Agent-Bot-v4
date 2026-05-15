"""Sprint 61 — Tier-2 PICO enrichment.

Sprint 59 sends facts with empty population OR intervention to
`D_bad_extraction`. Many Tier-2 facts have empty PICO even though
canonical_phrase + paper title contain enough text to recover both.
This module runs batched MiMo extraction to fill missing slots,
pushing facts D_bad -> A_core / B_context.

Hard rules: only run on facts where pop OR intv is empty; never
override a non-empty original; empty stays empty if MiMo cannot
ground a value in source text; original fact preserved on any error.
Universal — no biomedical literals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from agent.frontier_review import (
    _parse as _frontier_parse,
)
from agent.llm_client import call_writer_with_fallback
from agent.settings import Settings

_DEFAULT_BATCH = 10  # facts per MiMo call


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    facts_inspected: int
    facts_changed: int
    facts_population_filled: int
    facts_intervention_filled: int
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {"facts_inspected": self.facts_inspected,
                "facts_changed": self.facts_changed,
                "facts_population_filled": self.facts_population_filled,
                "facts_intervention_filled": self.facts_intervention_filled,
                "model": self.model}


def _needs_enrichment(fact: dict[str, Any]) -> bool:
    """True when fact has phrase context AND missing pop or intv."""
    if not str(fact.get("canonical_phrase") or "").strip():
        return False
    has_pop = bool(str(fact.get("population") or "").strip())
    has_intv = bool(str(fact.get("intervention") or "").strip())
    return not (has_pop and has_intv)


def _build_messages(
    candidates: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, str]]:
    """Universal prompt — no domain literals injected."""
    rows = []
    for idx, f in candidates:
        paper = f.get("source_paper") or {}
        rows.append(
            f"[{idx}] phrase={str(f.get('canonical_phrase') or '')[:300]!r} "
            f"| title={str(paper.get('title') or '')[:120]!r} "
            f"| current_population={str(f.get('population') or '')!r} "
            f"| current_intervention={str(f.get('intervention') or '')!r}"
        )
    sys_msg = (
        "Extract PICO from research phrases. Rules: "
        "(1) Only values EXPLICITLY in the phrase/title; never infer. "
        "(2) If a field is already populated, return UNCHANGED. "
        "(3) Empty string when not stated in source text. "
        "(4) Population = subjects (species/age/condition/sex/n). "
        "Intervention = treatment/exposure/compound/dose. "
        "(5) Respond as VALID JSON only."
    )
    user_msg = (
        "FACTS:\n" + "\n".join(rows) + "\n\n"
        "For each fact index, return the population and intervention "
        "as JSON:\n"
        '{"0": {"population": "...", "intervention": "..."}, '
        '"1": {...}, ...}'
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _apply_enrichment(
    f: dict[str, Any], extracted: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    """New fact + (pop_filled, intv_filled). Never overrides existing values."""
    out = dict(f)
    pop_new = str(extracted.get("population") or "").strip()
    intv_new = str(extracted.get("intervention") or "").strip()
    pop_filled = bool(pop_new) and not str(f.get("population") or "").strip()
    intv_filled = bool(intv_new) and not str(f.get("intervention") or "").strip()
    if pop_filled:
        out["population"] = pop_new
    if intv_filled:
        out["intervention"] = intv_new
    if pop_filled or intv_filled:
        out["_pico_inferred"] = True
    return out, pop_filled, intv_filled


def enrich_facts_pico(
    facts: list[dict[str, Any]], *, settings: Settings,
    batch_size: int = _DEFAULT_BATCH,
) -> tuple[list[dict[str, Any]], EnrichmentResult]:
    """Fill missing population/intervention via batched MiMo calls.

    Returns (enriched_facts, result). Facts are returned in input
    order. On any error the original fact dict is preserved untouched.
    """
    if not facts:
        return [], EnrichmentResult(0, 0, 0, 0, "skipped_empty")
    if not settings.writer_configured:
        return list(facts), EnrichmentResult(
            len(facts), 0, 0, 0, "skipped_writer_not_configured",
        )

    needs: list[tuple[int, dict[str, Any]]] = [
        (i, f) for i, f in enumerate(facts)
        if isinstance(f, dict) and _needs_enrichment(f)
    ]
    if not needs:
        return list(facts), EnrichmentResult(
            len(facts), 0, 0, 0, "skipped_no_candidates",
        )

    out_facts = [dict(f) if isinstance(f, dict) else f for f in facts]
    model_used = "unknown"
    pop_filled_total = 0
    intv_filled_total = 0
    changed_total = 0

    for start in range(0, len(needs), batch_size):
        batch = needs[start:start + batch_size]
        msgs = _build_messages(batch)
        try:
            resp = call_writer_with_fallback(
                settings, msgs, temperature=0.0, max_tokens=2500,
            )
        except (RuntimeError, OSError, httpx.HTTPError):
            continue  # leave this batch unchanged
        model_used = resp.model
        parsed = _frontier_parse(resp.content)
        if not isinstance(parsed, dict):
            continue
        for idx, _f in batch:
            extracted = parsed.get(str(idx))
            if not isinstance(extracted, dict):
                continue
            current = out_facts[idx]
            if not isinstance(current, dict):
                continue
            new_fact, pf, iff = _apply_enrichment(current, extracted)
            out_facts[idx] = new_fact
            pop_filled_total += int(pf)
            intv_filled_total += int(iff)
            if pf or iff:
                changed_total += 1

    return out_facts, EnrichmentResult(
        facts_inspected=len(facts), facts_changed=changed_total,
        facts_population_filled=pop_filled_total,
        facts_intervention_filled=intv_filled_total,
        model=model_used,
    )


