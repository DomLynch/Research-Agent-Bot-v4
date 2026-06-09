"""Sprint 11.2 — stitch section bundles into one publish-ready paper.md.

The pipeline writes section bundles into independent run directories:

  runs/<topic>-s1-iter-NN-<ts>/main_draft.md   Title + Abstract + Introduction
  runs/<topic>-s2-iter-NN-<ts>/main_draft.md   Methods
  runs/<topic>-s6-iter-NN-<ts>/main_draft.md   Discussion + Limitations + Conclusion
  runs/<topic>-s7-iter-NN-<ts>/main_draft.md   Results (study selection -> primary
                                                effect -> heterogeneity -> sensitivity)

This stitcher composes the canonical publish-ready manuscript:

  1. Concatenate s1 + s2 + s7 + s6 bundles in journal order.
  2. Resolve [N_SCREENED] / [N_ACCEPTED] / [K_STUDIES] count placeholders
     from receipts and [PLACEHOLDER:<key>] markers from the topic-pack
     `[placeholders]` table.
  3. Apply the topic-pack `[methods_honesty_rewrites]` table so writer
     overclaim verbs (dual extraction, full SYRCLE adjudication, Egger's
     test, leave-one-out, etc.) are rewritten to the honest tense that
     matches what the pipeline actually executed.
  4. Run `resolve_citations` over the body so [CIT:<key>|<role>] markers
     become [N] inline + a numbered References section sourced from the
     topic-pack bibliography. Unknown anchors surface as [UNRESOLVED].
  5. Append the honest back-matter sections (Data and Code Availability,
     AI-Use Disclosure, Ethics, Author Contributions, Conflicts of
     Interest, Funding) built from pipeline-known facts.

No LLM, no retrieval. Pure file IO + deterministic transforms. Universal:
every domain choice (placeholders, honesty rewrites, bibliography,
ethics framing) lives in the topic pack, not in code.

Usage:
    python scripts/stitch_paper.py --topic rapamycin
    python scripts/stitch_paper.py --topic rapamycin --target runs/<paper-dir>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.back_matter import build_back_matter
from agent.maturity_router import PaperType, select_paper_type
from agent.methods_honesty import apply_honesty_rewrites
from agent.placeholder_resolver import resolve_placeholders
from agent.readiness import ReadinessReport, classify_readiness
from agent.reference_resolver import CiteAudit, audit_citations, resolve_citations
from agent.settings import load_settings
from agent.study_table import build_study_characteristics_table
from agent.topic_pack import load_topic_pack

_RUNS = Path(__file__).resolve().parent.parent / "runs"
Json = dict[str, object]


def _latest_bundle(topic: str, section_short: str) -> Path | None:
    candidates = sorted(
        _RUNS.glob(f"{topic}-{section_short}-iter-*"), reverse=True,
    )
    return candidates[0] if candidates else None


def _read(path: Path | None) -> str:
    if path is None:
        return ""
    f = path / "main_draft.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _pending(label: str, hint: str) -> str:
    return f"[SECTIONS_PENDING:{label} — {hint}]"


_TERMINAL_PUNCT: frozenset[str] = frozenset(".!?:)]}`")


def _ends_cleanly(section_body: str) -> bool:
    """True iff the section's last non-blank line ends with a terminal-
    punctuation character or a list/code-block closer. Used by the
    Sprint 31 mid-sentence-truncation hard gate."""
    for line in reversed(section_body.splitlines()):
        stripped = line.rstrip()
        if not stripped:
            continue
        return stripped[-1] in _TERMINAL_PUNCT
    return True  # empty body — caught by a different gate (SECTIONS_PENDING)


def _find_truncated_sections(
    intro: str, methods: str, results: str, discussion: str,
) -> list[str]:
    """Return labels of sections that look truncated mid-sentence."""
    return [
        label for label, body in (
            ("title_abstract_intro", intro), ("methods", methods),
            ("results", results), ("discussion", discussion),
        )
        if "[SECTIONS_PENDING:" not in body and not _ends_cleanly(body)
    ]


def _load_receipts(
    run_dir: Path | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    """Pull eligibility_summary, strict A-core, extractions, and pool JSON.

    Empty dicts mean the corresponding tokens / table rows surface as
    `[UNRESOLVED]` / em-dashes rather than being silently dropped.
    """
    if run_dir is None:
        return {}, {}, {}, {}
    out: list[dict[str, object]] = []
    for fname in (
        "eligibility_summary.json",
        "primary_effect_input_set_strict.json",
        "effect_extractions.json",
        "effect_pool.json",
    ):
        path = run_dir / fname
        out.append(
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
    return out[0], out[1], out[2], out[3]


def _dict_rows(value: object) -> list[Json]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _report_evidence_rows(
    strict: dict[str, object],
    extractions: dict[str, object],
    pool: dict[str, object],
) -> list[Json]:
    rows: list[Json] = []
    for lane, value in strict.items():
        for row in _dict_rows(value):
            rows.append({"source": "primary_effect_input_set_strict", "lane": lane, **row})
    for row in _dict_rows(extractions.get("receipts") or extractions.get("extractions")):
        rows.append({"source": "effect_extractions", **row})
    for row in _dict_rows(pool.get("effects")):
        rows.append({"source": "effect_pool", **row})
    for key, value in pool.items():
        if key.endswith("_summary") and isinstance(value, dict):
            rows.append({"source": "effect_pool", "summary": key, **value})
    return rows


def _build_report_json(
    *,
    topic: str,
    paper_path: Path,
    summary: dict[str, object],
    strict: dict[str, object],
    extractions: dict[str, object],
    pool: dict[str, object],
    readiness: ReadinessReport,
    cite_audit: CiteAudit,
    paper_type: PaperType,
) -> Json:
    readiness_dict = readiness.as_dict()
    cite_audit_dict = cite_audit.as_dict()
    paper_type_dict = paper_type.as_dict()
    return {
        "topic": topic,
        "markdown": {"path": paper_path.name},
        "Summary": [
            {"section": "Readiness", **readiness_dict},
            {"section": "Citation audit", **cite_audit_dict},
            {"section": "Paper type", **paper_type_dict},
            {"section": "Eligibility", **summary},
        ],
        "Evidence": _report_evidence_rows(strict, extractions, pool),
    }


def _inject_study_table(
    body: str,
    strict: dict[str, object],
    extr: dict[str, object],
    pool: dict[str, object],
) -> str:
    """Insert the study-characteristics table before `## Discussion`.

    No-op if the body has no Discussion heading or no A-core records.
    Universal: anchor is the journal-standard Discussion header.
    """
    table = build_study_characteristics_table(strict, extr, pool)
    if not table:
        return body
    anchor = "## Discussion"
    if anchor not in body:
        return body
    return body.replace(anchor, f"{table}\n{anchor}", 1)


def stitch(
    topic: str,
    *,
    target: Path | None = None,
    repository_url: str = "",
    allow_pending: bool = False,
) -> Path:
    pack = load_topic_pack(topic)
    if pack is None:
        raise RuntimeError(f"no topic pack: {topic}")
    settings = load_settings()

    s1 = _latest_bundle(topic, "s1")
    s2 = _latest_bundle(topic, "s2")
    s3 = _latest_bundle(topic, "s3")
    s6 = _latest_bundle(topic, "s6")
    s7 = _latest_bundle(topic, "s7")

    intro = _read(s1).rstrip() or _pending(
        "title_abstract_intro",
        "run draft_main.py --section title_abstract_intro",
    )
    methods = _read(s2).rstrip() or _pending(
        "methods", "run draft_main.py --section methods",
    )
    results = _read(s7).rstrip() or _pending(
        "results",
        "run run_eligibility.py + freeze_primary_set.py + regen_section3.py",
    )
    discussion = _read(s6).rstrip() or _pending(
        "discussion", "run draft_main.py --section discussion",
    )

    raw_body = "\n\n".join([intro, methods, results, discussion]) + "\n"

    # Sprint 14 hard gate: refuse to stitch a paper.md that still carries
    # SECTIONS_PENDING markers. The writer fallback chain (MiMo -> Gemma)
    # should have eliminated these upstream; if any remain, the operator
    # skipped a section. Default = fail loud; --allow-pending preserves
    # the partial-staging workflow but logs the deficit.
    if not allow_pending and "[SECTIONS_PENDING:" in raw_body:
        missing = [
            tok for tok, src in (
                ("title_abstract_intro", s1), ("methods", s2),
                ("results", s7), ("discussion", s6),
            ) if src is None
        ]
        raise RuntimeError(
            f"refusing to stitch paper.md with missing section(s): {missing}. "
            f"Run scripts/draft_main.py for each section first, or pass "
            f"--allow-pending to stage a partial draft."
        )

    # Sprint 31 hard gate: every drafted section must end in terminal
    # punctuation (.!?:)]}` or a list/code-block closer). Mid-sentence
    # truncation is a writer-side failure mode (max_tokens cap hit, JSON
    # parse trimmed prose, etc.) and is desk-rejection grounds. Universal
    # — check is content-shape only, no topic literals.
    if not allow_pending:
        truncated = _find_truncated_sections(intro, methods, results, discussion)
        if truncated:
            raise RuntimeError(
                f"refusing to stitch paper.md with mid-sentence section "
                f"truncation: {truncated}. Re-run the affected draft_main.py "
                f"stage(s) (likely max_tokens too low for the prompt size), "
                f"or pass --allow-pending to stage anyway."
            )

    summary, strict, extr, pool = _load_receipts(s7)
    # Pass 1: resolve raw writer-emitted count + topic-pack placeholders.
    ph = resolve_placeholders(
        raw_body, summary=summary, strict=strict, pack=pack,
        extractions=extr, pool=pool,
    )
    # Honesty rewrites may inject NEW corpus-derived tokens (e.g.
    # [STRICT_A_CORE_IDS], [INCOMPLETE_RECOVERY_IDS]) into the body.
    hon = apply_honesty_rewrites(ph.body, pack)
    # Pass 2: resolve any tokens introduced by honesty rewrites.
    ph2 = resolve_placeholders(
        hon.body, summary=summary, strict=strict, pack=pack,
        extractions=extr, pool=pool,
    )
    with_table = _inject_study_table(ph2.body, strict, extr, pool)
    resolved = resolve_citations(with_table, pack)
    cite_audit = audit_citations(resolved, pack)
    # Sprint 17 hard gate: refuse to stitch when citations don't reconcile.
    # In-text [N] without a matching reference, or unresolved anchor keys,
    # mean reviewers would see broken numbering or [UNRESOLVED] tags in
    # the shipped paper. --allow-pending bypasses for staging workflows.
    if not allow_pending and not cite_audit.clean:
        raise RuntimeError(
            f"refusing to stitch paper.md with citation defects: "
            f"unresolved={list(cite_audit.unresolved_anchors)}, "
            f"in_text_without_entry={list(cite_audit.in_text_without_entry)}, "
            f"entry_without_in_text={list(cite_audit.entry_without_in_text)}. "
            f"Fix the topic-pack bibliography or rerun the writer, or pass "
            f"--allow-pending to stage anyway."
        )

    if target is None:
        stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        target = _RUNS / f"{topic}-paper-{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    # Sprint 33: stitch copies the canonical receipts from the s7 run
    # directory into the paper folder so downstream consumers
    # (build_supplement, regen_receipts, research_object) all read from
    # the same place. Previously build_supplement read receipts from
    # the paper folder and got empty values when stitch hadn't copied
    # them — producing supplements that claimed 0 records even when
    # eligibility found 500+. Universal: receipt filenames are
    # canonical (no topic literals).
    if s7 is not None:
        import shutil as _sh
        for _name in (
            "eligibility_summary.json",
            "primary_effect_input_set_strict.json",
            "effect_extractions.json",
            "effect_pool.json",
            "extraction_confidence.json",
            "dual_agent_extraction_audit.json",
            "extraction_crosscheck.json",
            "sentinel_repair_plan.json",
            "manual_full_text_audit.json",
        ):
            _src = s7 / _name
            if _src.exists():
                _sh.copyfile(_src, target / _name)

    back_matter = build_back_matter(
        pack, settings,
        run_dir=target,
        run_dir_name=str(target.relative_to(target.parent.parent))
            if target.is_relative_to(target.parent.parent) else target.name,
        repository_url=repository_url,
    )

    stamp_iso = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    header = (
        "<!-- AUTO-STITCHED — do not edit by hand. Bundles used:\n"
        f"  s1: {s1.name if s1 else '(none)'}\n"
        f"  s2: {s2.name if s2 else '(none)'}\n"
        f"  s6: {s6.name if s6 else '(none)'}\n"
        f"  s7: {s7.name if s7 else '(none)'}\n"
        f"  placeholders resolved: {len(ph.resolved)} "
        f"(unresolved: {len(ph.unresolved)})\n"
        f"  honesty rewrites applied: {len(hon.rewrites_applied)}\n"
        f"  citations resolved: {len(resolved.citations_used)} "
        f"(unresolved: {len(resolved.unresolved)})\n"
        f"  stamped: {stamp_iso}\n"
        "-->\n\n"
    )

    parts: list[str] = [header, resolved.body.rstrip()]
    if resolved.references_section:
        parts.append("")
        parts.append(resolved.references_section.rstrip())
    parts.append("")
    parts.append(back_matter.as_markdown().rstrip())

    out = "\n".join(parts) + "\n"
    target_path = target / "paper.md"
    target_path.write_text(out, encoding="utf-8")

    # Sprint 16: emit readiness_report.json next to paper.md so the
    # one-glance reviewer signal travels with every shipped artifact.
    import json
    readiness = classify_readiness(
        summary=summary, strict=strict, extractions=extr, pool=pool,
    )
    (target / "readiness_report.json").write_text(
        json.dumps(readiness.as_dict(), indent=2), encoding="utf-8",
    )
    # Sprint 17: cite_audit.json captures the citation/reference sanity
    # state — clean=True is journal-shippable; clean=False (only reachable
    # via --allow-pending) keeps the deficit visible to reviewers.
    (target / "cite_audit.json").write_text(
        json.dumps(cite_audit.as_dict(), indent=2), encoding="utf-8",
    )
    # Sprint 23: paper-type decision from readiness + pool count. The
    # writer-prompt builder + reviewer should both consult this to
    # enforce evidence-ladder-appropriate prose (k=1 → scoping review,
    # not meta-analysis claims).
    paper_type = select_paper_type(readiness)
    (target / "paper_type_decision.json").write_text(
        json.dumps(paper_type.as_dict(), indent=2), encoding="utf-8",
    )

    # Sprint 38: move the stage bundles (s1/s2/s3/s6/s7) INTO the paper
    # folder's `.stages/` subdir so `runs/` stops looking like a junk
    # drawer (one paper = one folder, audit trail preserved inside).
    # Skipped under --allow-pending so partial-staging workflows don't
    # consume the bundles they may still want to re-use.
    if not allow_pending:
        import shutil as _sh
        stages_subdir = target / ".stages"
        stages_subdir.mkdir(exist_ok=True)
        for _stage in (s1, s2, s3, s6, s7):
            if _stage is not None and _stage.exists() and _stage.is_dir():
                _dest = stages_subdir / _stage.name
                if not _dest.exists():
                    _sh.move(str(_stage), str(_dest))

    print(
        f"[stitch] wrote {target_path} "
        f"(ph_resolved={len(ph.resolved)}, ph_unresolved={len(ph.unresolved)}, "
        f"honesty_rewrites={len(hon.rewrites_applied)}, "
        f"cites_used={len(resolved.citations_used)}, "
        f"cites_unresolved={len(resolved.unresolved)}, "
        f"cite_audit_clean={cite_audit.clean}, "
        f"readiness=L{readiness.level} {readiness.label})"
    )
    return target_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="rapamycin")
    parser.add_argument(
        "--target", type=Path, default=None,
        help="Destination paper-folder. Defaults to "
             "runs/<topic>-paper-<utc-stamp>.",
    )
    parser.add_argument(
        "--repository-url", default="",
        help="Public repository URL for the Data and Code Availability "
             "back-matter section.",
    )
    parser.add_argument(
        "--allow-pending", action="store_true",
        help="Sprint 14: bypass the SECTIONS_PENDING hard gate. Use only "
             "when intentionally staging a partial draft.",
    )
    args = parser.parse_args()
    stitch(
        args.topic,
        target=args.target,
        repository_url=args.repository_url,
        allow_pending=args.allow_pending,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
