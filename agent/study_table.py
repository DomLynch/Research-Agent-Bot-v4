"""Render the journal-style study-characteristics table from receipts.

The reviewer-flagged single biggest credibility lift: a per-study table
in §Results that maps every strict A-core record to its strain, sex,
dose, age at treatment, metric, treated/control values, sample sizes,
and pool inclusion status. Pure deterministic transform over the
already-filed receipts (strict A-core + extraction + pool + demote
reasons). No LLM, no invention.

Universal: nothing biomedical hardcoded. Strain / sex / dose / age fields
come from the extraction receipt `moderators` dict (writer-emitted under
the contract). Empty fields render as em-dash so the table is still
visually parseable.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_DASH = "—"  # em-dash for "not reported"


def _md_cell(value: object) -> str:
    if value is None or value == "" or value == "None":
        return _DASH
    return str(value).replace("|", "/").replace("\n", " ")


def build_study_characteristics_table(
    strict: Mapping[str, Any],
    extractions: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> str:
    """Return a Markdown table or empty string when no A-core records."""
    a_core = strict.get("A_core_direct_lifespan") or []
    if not isinstance(a_core, list) or not a_core:
        return ""

    extr_by_id: dict[str, Any] = {}
    for r in extractions.get("receipts", []) or []:
        if isinstance(r, dict):
            extr_by_id[str(r.get("study_id", ""))] = r

    pooled_ids: set[str] = set()
    for e in pool.get("effects", []) or []:
        if isinstance(e, dict):
            pooled_ids.add(str(e.get("study_id", "")))
    skipped: set[str] = {
        str(s) for s in (pool.get("skipped_study_ids") or [])
    }

    headers = [
        "Study", "Strain / model", "Sex", "Dose", "Age started",
        "Metric", "Treated", "Control", "n_T", "n_C",
        "In pool?", "Reason",
    ]
    rows: list[list[str]] = []
    for s in a_core:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("study_id", ""))
        receipt = extr_by_id.get(sid, {})
        mods = receipt.get("moderators") or {}
        in_pool = sid in pooled_ids
        reason = (
            "" if in_pool
            else (
                "no inverse-variance numerics" if sid in skipped
                else _DASH
            )
        )
        rows.append([
            _md_cell(sid),
            _md_cell(mods.get("strain") or mods.get("model")),
            _md_cell(mods.get("sex")),
            _md_cell(mods.get("dose")),
            _md_cell(mods.get("age_initiation") or mods.get("age_started")),
            _md_cell(receipt.get("metric")),
            _md_cell(receipt.get("treated_value")),
            _md_cell(receipt.get("control_value")),
            _md_cell(receipt.get("treated_n")),
            _md_cell(receipt.get("control_n")),
            "Yes" if in_pool else "No",
            _md_cell(reason),
        ])

    lines = [
        "### Study Characteristics Table",
        "",
        "Per-study extraction summary across the strict A-core corpus. "
        "Fields are taken verbatim from the extraction receipts "
        "(`effect_extractions.json`) and the inverse-variance pool "
        "input (`effect_pool.json`); the pipeline does not mint new "
        "values. Empty cells (em-dash) signal that the source paper did "
        "not report the field at full-text screen or that the "
        "extraction prompt did not recover it.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(r) + " |" for r in rows)
    lines.append("")
    return "\n".join(lines)
