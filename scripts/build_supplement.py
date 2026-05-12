"""Sprint 11.1 — Supplementary Materials generator.

Reads a paper-folder run directory and emits supplement.md with the
nine canonical supplement blocks expected by mid-tier journals:

  S1 Search strategy
  S2 Screening receipts (PRISMA flow counts)
  S3 Eligibility receipts (per-study verdicts)
  S4 Strict A-core corpus
  S5 Effect extraction receipts
  S6 Risk-of-bias notes
  S7 Sentinel audit
  S8 Excluded / demoted studies with reasons
  S9 Code and data availability pointers

No LLM. Pure read-only consumer of the receipts already filed by the
upstream pipeline. Universal: nothing biomedical hardcoded; section
labels and counts come straight from the topic pack and receipts.

Usage:
    python scripts/build_supplement.py <paper_dir> --topic <topic>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.topic_pack import load_topic_pack


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return head + "\n" + sep + ("\n" + body if rows else "")


def _truncate(s: str, n: int = 200) -> str:
    s = (s or "").replace("\n", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "..."


def build(pd: Path, topic: str, *, qa_report_path: Path | None = None) -> str:
    """Render supplement.md from the receipts in `pd`.

    The four JSON receipts (eligibility_summary, primary_effect_input_set_strict,
    effect_extractions, effect_pool) are read from `pd` so the final paper folder
    is self-describing. `qa_report.md` is the only large textual receipt; by
    default it is read from `pd` (legacy layout), but callers can pass
    `qa_report_path` to point at the upstream s7 run dir — keeping the final
    paper folder lean (paper.md + supplement.md + 4 JSON receipts only).
    """
    pack = load_topic_pack(topic)
    if pack is None:
        raise RuntimeError(f"no topic pack: {topic}")

    summary = _read_json(pd / "eligibility_summary.json") or {}
    strict = _read_json(pd / "primary_effect_input_set_strict.json") or {}
    extr = _read_json(pd / "effect_extractions.json") or {}
    pool = _read_json(pd / "effect_pool.json") or {}
    audit = _read_json(pd / "manual_full_text_audit.json") or []
    qa_p = qa_report_path or (pd / "qa_report.md")
    qa = qa_p.read_text(encoding="utf-8") if qa_p.exists() else ""

    parts: list[str] = [
        f"# Supplementary Materials — {pack.display_name}",
        "",
        "Auto-generated from the run-directory receipts that accompany "
        "the main manuscript. Every count, identifier, and quote below "
        "is read verbatim from a JSON receipt; the supplement does not "
        "mint new numbers and cannot drift from the main paper.",
        "",
    ]

    parts += ["## S1 — Search Strategy", ""]
    parts += [
        "- **Topic pack**: "
        f"`{pack.topic}` ({pack.display_name})",
        "- **Retrieval sources**: " + (
            ", ".join(pack.retrieval_sources) or "(none declared)"
        ),
        "- **Primary interventions (PICO `E`)**: "
        + (", ".join(pack.primary_interventions) or "(none declared)"),
        "- **Translational-only interventions** (excluded from primary "
        "corpus; retained for sensitivity layer): "
        + (", ".join(pack.translational_only_interventions) or "(none)"),
        "- **Endpoint vocabulary**: "
        + (", ".join(pack.eligibility_endpoint_terms) or "(none)"),
        "- **Control vocabulary**: "
        + (", ".join(pack.eligibility_control_terms) or "(none)"),
        "- **Excluded designs**: "
        + (", ".join(pack.eligibility_exclude_design_terms) or "(none)"),
        "- **Pre-specified parsed-text minimum**: "
        f"{pack.eligibility_min_text_chars} chars",
        "",
    ]

    parts += ["## S2 — Screening Counts (PRISMA-style)", ""]
    parts += [
        f"- records identified: **{summary.get('k_hits', 0)}**",
        f"- title/abstract candidates: **{summary.get('k_candidates', 0)}**",
        f"- open-access full-text located: **{summary.get('k_full_text_located', 0)}**",
        f"- full-text parsed: **{summary.get('k_parsed_with_text', 0)}**",
        f"- eligibility decisions: **{summary.get('final_decisions', {})}**",
        f"- eligible after merge: **{summary.get('k_eligible', 0)}**",
        f"- judge model: `{summary.get('judge_model', '(unknown)')}`",
        "",
    ]

    parts += ["## S3 — Eligibility Receipts (per-study auto-judge verdicts)", ""]
    parts += [
        "Full receipts (decision, reviewer, confidence, mandatory "
        "fields, evidence quotes, model, timestamps) are filed in "
        "`eligibility_receipts.json` alongside this supplement. The "
        "block above lists aggregate counts; per-study rows are "
        "available in the run directory.",
        "",
    ]

    a_core = strict.get("A_core_direct_lifespan", [])
    parts += ["## S4 — Strict A-core Corpus "
              f"(k = {len(a_core)})", ""]
    if a_core:
        rows = [
            [
                str(s.get("study_id", "?")),
                _truncate(str(s.get("title", "")), 70),
                str(s.get("year", "?")),
                str(s.get("venue", "?")),
                str(s.get("doi", "?")),
            ]
            for s in a_core
        ]
        parts.append(_md_table(
            ["study_id", "title", "year", "venue", "doi"], rows,
        ))
    else:
        parts.append("_(no strict A-core records in this run)_")
    parts += ["", ""]

    receipts = extr.get("receipts", [])
    parts += [f"## S5 — Effect Extraction Receipts (n = {len(receipts)})", ""]
    if receipts:
        rows = [
            [
                str(r.get("study_id", "?")),
                str(r.get("status", "?")),
                _truncate(str(r.get("metric", "")), 30),
                str(r.get("treated_value")),
                str(r.get("control_value")),
                str(r.get("treated_n")),
                str(r.get("control_n")),
                str(r.get("hazard_ratio")),
                str(r.get("percent_change")),
            ]
            for r in receipts
        ]
        parts.append(_md_table(
            ["study_id", "status", "metric", "T_value", "C_value",
             "n_T", "n_C", "HR", "%"],
            rows,
        ))
    else:
        parts.append("_(no extraction receipts)_")
    parts += ["", ""]

    pool_effects = pool.get("effects", []) if isinstance(pool, dict) else []
    pool_skipped = pool.get("skipped_study_ids", []) if isinstance(pool, dict) else []
    parts += [
        "### S5b — Inverse-variance pool "
        f"(k_effects = {len(pool_effects)}, "
        f"skipped = {len(pool_skipped)})",
        "",
    ]
    if pool_effects:
        rows = [
            [
                str(e.get("study_id", "?")),
                str(e.get("metric", "?")),
                f"{float(e.get('estimate', 0.0)):.4f}",
                f"{float(e.get('se', 0.0)):.4f}",
                f"{float(e.get('ci_low', 0.0)):.4f}",
                f"{float(e.get('ci_high', 0.0)):.4f}",
            ]
            for e in pool_effects
        ]
        parts.append(_md_table(
            ["study_id", "metric", "estimate", "SE", "CI_low", "CI_high"],
            rows,
        ))
    else:
        parts.append("_(no pooling-ready effects in this run)_")
    if pool_skipped:
        parts.append("")
        parts.append(
            "Skipped (no inverse-variance numerics): "
            + ", ".join(f"`{s}`" for s in pool_skipped)
        )
    parts += ["", ""]

    # S5c: Researka Tier 2 canonical-fact crosscheck (Sprint 12.0).
    crosscheck = _read_json(pd / "extraction_crosscheck.json")
    if isinstance(crosscheck, dict) and crosscheck.get("results"):
        parts += [
            "### S5c — Researka Canonical-Fact Cross-Check",
            "",
            "Third-party-validation overlay. For every extraction receipt "
            f"with `percent_change` numerics, the Researka Tier 2 facts "
            f"index (POST `/api/v1/tier2/facts/search`) was queried and "
            f"filtered to facts whose paper DOI matches the receipt. The "
            f"verdict is computed against a "
            f"{crosscheck.get('tolerance_percent', 25.0):.0f}% tolerance "
            "band on the canonical %-value.",
            "",
        ]
        rows = [
            [
                str(r.get("study_id", "?")),
                _truncate(str(r.get("doi") or "—"), 32),
                str(r.get("verdict", "?")),
                _truncate(
                    f"{r['receipt_percent_change']:.1f}%"
                    if r.get("receipt_percent_change") is not None else "—",
                    8,
                ),
                _truncate(str(r.get("best_match_fact_id") or "—"), 40),
                _truncate(
                    f"{r['delta_percent']:.1f}"
                    if r.get("delta_percent") is not None else "—",
                    6,
                ),
            ]
            for r in crosscheck["results"]
        ]
        parts.append(_md_table(
            ["study_id", "doi", "verdict", "receipt%",
             "best_match_fact_id", "Δ%"],
            rows,
        ))
        verdicts = [r.get("verdict") for r in crosscheck["results"]]
        parts += [
            "",
            f"Crosscheck distribution: matched="
            f"{verdicts.count('matched')}, "
            f"discrepant={verdicts.count('discrepant')}, "
            f"no_canonical_fact={verdicts.count('no_canonical_fact')}, "
            f"no_receipt_numerics={verdicts.count('no_receipt_numerics')}.",
            "",
        ]

    parts += ["## S6 — Risk-of-Bias Notes", ""]
    parts += [
        "Automated rule-based screen per the pre-specified eligibility "
        "ladder (rule_triage → LLM judge → deterministic merge → "
        "include-contract). The universal evidence contract requires "
        "(a) parsed_text_adequate, (b) char_count above the topic-pack "
        "minimum, (c) at least two non-title evidence quotes, (d) "
        "endpoint-term coverage, and (e) intervention or control term "
        "coverage. Strict A-core additionally demands quote-level "
        "evidence that the CURRENT experiment used the preferred "
        "species + primary intervention + control + endpoint. Each "
        "demotion is recorded with its violation list in "
        "`primary_effect_input_set_strict.json`. **A pre-publication "
        "submission would require an explicit human risk-of-bias "
        "adjudication step** (e.g. SYRCLE for animal studies, Cochrane "
        "RoB 2 for human RCTs) on top of this automated screen.",
        "",
    ]

    parts += ["## S7 — Sentinel Recall Audit", ""]
    parts += [
        "Topic-pack-declared sentinels are: **primary** = "
        + ", ".join(f"`{s}`" for s in pack.sentinel_primary)
        + "; **prior_meta** = "
        + ", ".join(f"`{s}`" for s in pack.sentinel_prior_meta)
        + ".",
        "",
        "Per-sentinel resolution (auto verdict + manual status overlay) "
        "is rendered in `qa_report.md` under the "
        "_Sentinel resolution status (manual overlay)_ table. The gate "
        "passes only when every primary sentinel either auto-contract-"
        "passes or is documented as resolved_unavailable / "
        "resolved_excluded.",
        "",
    ]
    if audit:
        parts.append("Manual full-text overrides applied during this run "
                     "(SHA-256-hashed; verifiable byte-for-byte):")
        parts.append("")
        rows = [
            [
                str(a.get("study_id", "?")),
                _truncate(str(a.get("source_path", "")), 60),
                str(a.get("byte_count", "?")),
                _truncate(str(a.get("file_hash_sha256", "")), 18),
                _truncate(str(a.get("reason", "")), 80),
            ]
            for a in audit
        ]
        parts.append(_md_table(
            ["study_id", "source_path", "bytes", "sha256[0:18]", "reason"],
            rows,
        ))
        parts += ["", ""]

    parts += ["## S8 — Excluded / Demoted Studies (with reasons)", ""]
    c_lane = strict.get("C_secondary_contextual", [])
    demote_reasons = strict.get("demote_reasons", {})
    if c_lane:
        rows = []
        for s in c_lane:
            sid = str(s.get("study_id", "?"))
            from_lane = str(s.get("demoted_from") or "originally C")
            reasons = demote_reasons.get(sid) or s.get("demote_reasons", [])
            rows.append([
                sid,
                _truncate(str(s.get("title", "")), 60),
                from_lane,
                _truncate(" / ".join(str(r) for r in reasons) or "—", 80),
            ])
        parts.append(_md_table(
            ["study_id", "title", "demoted_from", "reasons"], rows,
        ))
    else:
        parts.append("_(no demoted records in this run)_")
    parts += ["", ""]

    parts += ["## S9 — Code and Data Availability", ""]
    parts += [
        "- Pipeline source: see the project repository under "
        "`agent/`, `scripts/`, and `tests/`. All counts and effect "
        "estimates are computed from the JSON receipts filed in this "
        "paper folder; no number in the main manuscript originates "
        "outside those receipts.",
        "- Topic pack: `topic_packs/" f"{pack.topic}.toml`"
        " (search vocabulary, sentinels, anchors, bibliography, "
        "strict A-core terms).",
        "- Manual full-text overrides (if any): "
        "`topic_packs/manual_full_text/" f"{pack.topic}/`"
        " with audit hashes in `manual_full_text_audit.json`.",
        "- Receipts in this folder: `candidates.json`, "
        "`eligibility_receipts.json`, `parsed_receipts.json`, "
        "`primary_effect_input_set_strict.json`, "
        "`effect_extractions.json`, `effect_pool.json`, "
        "`eligibility_summary.json`, `qa_report.md`.",
        "",
    ]

    if qa:
        parts += ["## S10 — QA Report (verbatim)", "", qa, ""]

    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_dir", type=Path)
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    body = build(args.paper_dir, args.topic)
    target = args.out or (args.paper_dir / "supplement.md")
    target.write_text(body, encoding="utf-8")
    print(f"[supplement] wrote {target} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
