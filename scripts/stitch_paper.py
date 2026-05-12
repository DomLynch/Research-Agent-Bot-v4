"""Sprint 11.1 — stitch section bundles into one publish-ready paper.md.

The pipeline writes section bundles into independent run directories:

  runs/<topic>-s1-iter-NN-<ts>/main_draft.md   Title + Abstract + Introduction
  runs/<topic>-s2-iter-NN-<ts>/main_draft.md   Methods
  runs/<topic>-s6-iter-NN-<ts>/main_draft.md   Discussion + Limitations + Conclusion
  runs/<topic>-s7-iter-NN-<ts>/main_draft.md   Results (study selection -> primary
                                                effect -> heterogeneity -> sensitivity)

This stitcher composes the canonical publish-ready manuscript:

  1. Concatenate s1 + s2 + s7 + s6 bundles in journal order.
  2. Run `resolve_citations` over the body so [CIT:<key>|<role>] markers
     become [N] inline + a numbered References section sourced from the
     topic-pack bibliography. Unknown anchors surface as [UNRESOLVED].
  3. Append the honest back-matter sections (Data and Code Availability,
     AI-Use Disclosure, Ethics, Author Contributions, Conflicts of
     Interest, Funding) built from pipeline-known facts.

No LLM, no retrieval. Pure file IO + deterministic transforms. Universal:
the bibliography and ethics framing come from the topic pack, not code.

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
from agent.reference_resolver import resolve_citations
from agent.settings import load_settings
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


def stitch(
    topic: str,
    *,
    target: Path | None = None,
    repository_url: str = "",
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

    body = "\n\n".join([intro, methods, results, discussion]) + "\n"
    resolved = resolve_citations(body, pack)

    if target is None:
        stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        target = _RUNS / f"{topic}-paper-{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    back_matter = build_back_matter(
        pack, settings,
        run_dir_name=str(target.relative_to(target.parent.parent))
            if target.is_relative_to(target.parent.parent) else target.name,
        repository_url=repository_url,
        operator_handle="human-operator",
    )

    stamp_iso = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    header = (
        "<!-- AUTO-STITCHED — do not edit by hand. Bundles used:\n"
        f"  s1: {s1.name if s1 else '(none)'}\n"
        f"  s2: {s2.name if s2 else '(none)'}\n"
        f"  s6: {s6.name if s6 else '(none)'}\n"
        f"  s7: {s7.name if s7 else '(none)'}\n"
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
    print(
        f"[stitch] wrote {target_path} "
        f"(cites_used={len(resolved.citations_used)}, "
        f"unresolved={len(resolved.unresolved)})"
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
    args = parser.parse_args()
    stitch(
        args.topic,
        target=args.target,
        repository_url=args.repository_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
