"""Render Appendix A — Run audit deterministically from receipts.

The writer LLM emitted an Appendix A block at draft time; if the corpus
or extraction layer is later re-run, that block goes stale (wrong study
IDs, wrong metric, wrong pool). This module replaces it with fresh,
receipt-derived prose at stitch time so the in-paper audit trail can
never drift from the current run-dir receipts.

Universal: no biomedical literals. Counts come from eligibility_summary;
A-core list + extraction receipts + pool composition come from
primary_effect_input_set_strict.json, effect_extractions.json, and
effect_pool.json respectively.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def render_appendix_a(
    summary: Mapping[str, Any],
    strict: Mapping[str, Any],
    extractions: Mapping[str, Any],
    pool: Mapping[str, Any],
    *,
    judge_model: str = "",
) -> str:
    a_core = strict.get("A_core_direct_lifespan") or []
    receipts = extractions.get("receipts") or []
    a_effects = pool.get("effects") or []
    b_effects = pool.get("sensitivity_effects") or []
    skipped = pool.get("skipped_study_ids") or []
    decisions = summary.get("final_decisions") or {}

    lines = [
        "## Appendix A — Run audit (auto-generated from receipts)",
        "",
        "This paper was assembled by the universal evidence contract pipeline.",
        "The counts and effect estimates below come directly from the receipts",
        "filed alongside this document; the prose above does NOT mint new",
        "numbers.",
        "",
        f"- topic: {summary.get('topic', '?')}",
        f"- run_id: {summary.get('iter', '?')}",
        f"- retrieval hits: {summary.get('k_hits', '?')}",
        f"- title/abstract candidates: {summary.get('k_candidates', '?')}",
        f"- open-access full-text located: {summary.get('k_full_text_located', '?')}",
        f"- parsed-with-text: {summary.get('k_parsed_with_text', '?')}",
        f"- final eligibility decisions: {dict(decisions)}",
        f"- contract violations: {summary.get('contract_violations', 0)}",
        f"- judge model: `{judge_model or summary.get('judge_model', '?')}`",
        "",
        f"### Strict A-core (k_studies = {len(a_core)})",
        "",
    ]
    if a_core:
        for s in a_core:
            sid = s.get("study_id", "?")
            title = s.get("title", "")
            year = s.get("year", "?")
            venue = s.get("venue", "?")
            doi = s.get("doi", "?")
            lines.append(f"- {sid}: {title} ({year}, {venue}; DOI {doi})")
    else:
        lines.append("- (none)")

    lines += ["", "### Effect extraction receipts", ""]
    if receipts:
        for r in receipts:
            sid = r.get("study_id", "?")
            status = r.get("status", "?")
            metric = r.get("metric", "")
            tv = r.get("treated_value")
            cv = r.get("control_value")
            tn = r.get("treated_n")
            cn = r.get("control_n")
            mods = r.get("moderators") or {}
            lines.append(
                f"- {sid}: status={status}, metric={metric}, "
                f"treated_value={tv}, control_value={cv}, "
                f"treated_n={tn}, control_n={cn}, moderators={dict(mods)}"
            )
    else:
        lines.append("- (none)")

    lines += ["", "### Primary pool (A-core, wild-type direct-lifespan)", ""]
    if a_effects:
        for e in a_effects:
            lines.append(
                f"- {e.get('study_id', '?')}: metric={e.get('metric', '?')}, "
                f"estimate={float(e.get('estimate', 0.0)):.4f}, "
                f"SE={float(e.get('se', 0.0)):.4f}, "
                f"95% CI [{float(e.get('ci_low', 0.0)):.4f}, "
                f"{float(e.get('ci_high', 0.0)):.4f}]"
            )
    else:
        lines.append("- (no A-core contract-passing effects)")

    lines += ["", "### Sensitivity pool (B disease-model / genotype-modified)", ""]
    if b_effects:
        for e in b_effects:
            lines.append(
                f"- {e.get('study_id', '?')}: metric={e.get('metric', '?')}, "
                f"estimate={float(e.get('estimate', 0.0)):.4f}, "
                f"SE={float(e.get('se', 0.0)):.4f}, "
                f"95% CI [{float(e.get('ci_low', 0.0)):.4f}, "
                f"{float(e.get('ci_high', 0.0)):.4f}]"
            )
    else:
        lines.append("- (no B-lane contract-passing effects)")

    if skipped:
        lines += [
            "",
            f"- skipped (no inverse-variance numerics): {list(skipped)}",
        ]

    return "\n".join(lines) + "\n"


def replace_appendix_a(body: str, rendered: str) -> str:
    """Replace the body's existing Appendix A...References block with the
    freshly rendered appendix. No-op if the anchors are missing.
    """
    start = body.find("## Appendix A")
    if start < 0:
        return body
    # End at the next top-level section (References, Data and Code, etc.)
    # so we don't gobble downstream prose.
    rest = body[start:]
    next_header_offsets = [
        rest.find(h, 1) for h in (
            "\n## References", "\n## Data and Code", "\n## AI-Use",
            "\n## Ethics", "\n## Author Contributions",
            "\n## Conflicts", "\n## Funding",
        )
    ]
    valid = [o for o in next_header_offsets if o > 0]
    end = (start + min(valid)) if valid else len(body)
    return body[:start] + rendered + "\n" + body[end:].lstrip("\n")
