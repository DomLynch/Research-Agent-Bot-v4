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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.back_matter import build_back_matter
from agent.methods_honesty import apply_honesty_rewrites
from agent.placeholder_resolver import resolve_placeholders
from agent.readiness import classify_readiness
from agent.reference_resolver import resolve_citations
from agent.settings import load_settings
from agent.study_table import build_study_characteristics_table
from agent.topic_pack import load_topic_pack

_RUNS = Path(__file__).resolve().parent.parent / "runs"


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


def _load_receipts(
    run_dir: Path | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    """Pull eligibility_summary, strict A-core, extractions, and pool JSON.

    Empty dicts mean the corresponding tokens / table rows surface as
    `[UNRESOLVED]` / em-dashes rather than being silently dropped.
    """
    if run_dir is None:
        return {}, {}, {}, {}
    import json
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

    if target is None:
        stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        target = _RUNS / f"{topic}-paper-{stamp}"
    target.mkdir(parents=True, exist_ok=True)

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

    print(
        f"[stitch] wrote {target_path} "
        f"(ph_resolved={len(ph.resolved)}, ph_unresolved={len(ph.unresolved)}, "
        f"honesty_rewrites={len(hon.rewrites_applied)}, "
        f"cites_used={len(resolved.citations_used)}, "
        f"cites_unresolved={len(resolved.unresolved)}, "
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
