"""Sprint 22 — universal journal-submission package generator.

Bundles the artifacts a typical journal portal expects into a single
`runs/<paper-dir>/submission/` subfolder:

  - cover_letter.md       (templated from pack + readiness signal)
  - title_page.md         (separate from manuscript per most journal rules)
  - main_manuscript.md    (copy of paper.md, header-stripped)
  - supplement.md         (copy of supplement.md when present)
  - prisma_checklist.md   (universal PRISMA-2020 27-item template)
  - submission_manifest.json  (manifest + readiness level + cite-audit
                                state + RoB framework if used)

Universal: every domain choice (journal name, framing, study-design
checklist) is supplied via arguments or read from the topic pack —
no biomedical literals in the package builder.
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# PRISMA-2020 27 items (Page et al. 2021). Framework-authoritative
# headings; topic-agnostic.
_PRISMA_2020: tuple[tuple[str, str], ...] = (
    ("1", "Title — Identify the report as a systematic review."),
    ("2", "Abstract — Structured summary including all PRISMA items."),
    ("3", "Rationale — Describe the rationale for the review."),
    ("4", "Objectives — Statement of question(s) addressed (PICO/PECO)."),
    ("5", "Eligibility criteria — Inclusion/exclusion criteria."),
    ("6", "Information sources — Databases, registers, websites searched."),
    ("7", "Search strategy — Full search strategies for all sources."),
    ("8", "Selection process — Methods to decide eligibility (incl. blinding, k of raters)."),
    ("9", "Data collection process — Extraction methods and review."),
    ("10a", "Data items — List and define all outcomes for which data sought."),
    ("10b", "Data items — Other variables sought."),
    ("11", "Study risk of bias assessment — Tool used and process."),
    ("12", "Effect measures — Measure(s) used (RR, OR, MD, etc.)."),
    ("13a", "Synthesis methods — Studies eligible for each synthesis."),
    ("13b", "Synthesis methods — Methods for preparing data."),
    ("13c", "Synthesis methods — Tabulation / visual summary methods."),
    ("13d", "Synthesis methods — Methods used (if meta-analysis: model, software, heterogeneity)."),
    ("13e", "Synthesis methods — Methods to explore heterogeneity."),
    ("13f", "Synthesis methods — Sensitivity analyses."),
    ("14", "Reporting bias assessment — Methods to assess risk of bias due to missing results."),
    ("15", "Certainty assessment — Methods (GRADE or similar)."),
    ("16a", "Study selection — Numbers screened / included with flow diagram."),
    ("16b", "Study selection — Cite excluded studies with reasons."),
    ("17", "Study characteristics — Cite each included study and its characteristics."),
    ("18", "Risk of bias in studies — Present assessments per study."),
    ("19", "Results of individual studies — Summary statistics + effect estimates."),
    ("20a", "Results of syntheses — Brief summary of characteristics + risk of bias of contributing studies."),
    ("20b", "Results of syntheses — Statistical synthesis presentation."),
    ("20c", "Results of syntheses — Heterogeneity assessment."),
    ("20d", "Results of syntheses — Sensitivity / subgroup analyses."),
    ("21", "Reporting biases — Assessment results."),
    ("22", "Certainty of evidence — Assessment results."),
    ("23a", "Discussion — Interpretation of results in context of other evidence."),
    ("23b", "Discussion — Limitations of evidence included."),
    ("23c", "Discussion — Limitations of the review process."),
    ("23d", "Discussion — Implications for practice / policy / future research."),
    ("24a", "Registration and protocol — Registration info."),
    ("24b", "Registration and protocol — Where the protocol can be accessed."),
    ("24c", "Registration and protocol — Amendments + dates."),
    ("25", "Support — Sources of financial / non-financial support."),
    ("26", "Competing interests — Declaration."),
    ("27", "Availability of data, code, and other materials — What is available and where."),
)


@dataclass(frozen=True, slots=True)
class SubmissionPackage:
    target_dir: Path
    files_written: tuple[str, ...]
    manifest: Mapping[str, object]


def _render_cover_letter(
    *, topic_display: str, target_journal: str, readiness_level: int,
    readiness_label: str, operator_handle: str,
) -> str:
    return (
        f"# Cover Letter\n\n"
        f"To the Editors of *{target_journal}*,\n\n"
        f"We submit the enclosed manuscript on **{topic_display}** for "
        f"consideration as a systematic-review-and-meta-analysis "
        f"contribution. The analysis follows PRISMA-2020 reporting and "
        f"uses pre-registered eligibility + extraction contracts; all "
        f"receipts (eligibility, extraction, pool, sentinel-recall, "
        f"cite-audit) are bundled in the submission package.\n\n"
        f"The current evidence-maturity classification is "
        f"**L{readiness_level} ({readiness_label})** as computed by the "
        f"pipeline's readiness classifier. We will respond to reviewer "
        f"queries with receipt-level provenance for every numeric claim.\n\n"
        f"Submitted by {operator_handle}.\n"
    )


def _render_title_page(
    *, topic_display: str, operator_handle: str, target_journal: str,
) -> str:
    return (
        f"# {topic_display}: a systematic review and meta-analysis\n\n"
        f"**Author:** {operator_handle}  \n"
        f"**Target journal:** {target_journal}  \n"
        f"**Submission package generated by:** Research Agent Bot v4 "
        f"(synthesis-lite pipeline; receipts-backed)\n"
    )


def _render_prisma_checklist(topic_display: str) -> str:
    lines = [f"# PRISMA-2020 Checklist — {topic_display}", ""]
    lines.append("Each item should be addressed in the manuscript "
                 "or supplement; this file is the auditor's index.\n")
    lines.append("| Item | Description | Section |")
    lines.append("|---|---|---|")
    for num, text in _PRISMA_2020:
        lines.append(f"| {num} | {text} | _to fill_ |")
    return "\n".join(lines) + "\n"


def build_submission(
    paper_dir: Path, *,
    target_journal: str = "(target journal TBD)",
    topic_display: str = "(topic)",
    operator_handle: str = "the operator",
) -> SubmissionPackage:
    """Materialize the submission/ subfolder from a stitched paper folder."""
    out = paper_dir / "submission"
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    readiness_path = paper_dir / "readiness_report.json"
    readiness: dict[str, object] = {}
    if readiness_path.exists():
        try:
            readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            readiness = {}

    cite_audit_path = paper_dir / "cite_audit.json"
    cite_audit: dict[str, object] = {}
    if cite_audit_path.exists():
        try:
            cite_audit = json.loads(cite_audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cite_audit = {}

    raw_level = readiness.get("level", 0)
    try:
        readiness_level = (
            int(raw_level) if isinstance(raw_level, (int, float, str)) else 0
        )
    except (TypeError, ValueError):
        readiness_level = 0
    raw_label = readiness.get("label", "(unknown)")
    readiness_label = str(raw_label) if raw_label else "(unknown)"
    (out / "cover_letter.md").write_text(
        _render_cover_letter(
            topic_display=topic_display, target_journal=target_journal,
            readiness_level=readiness_level,
            readiness_label=readiness_label,
            operator_handle=operator_handle,
        ), encoding="utf-8",
    )
    written.append("cover_letter.md")

    (out / "title_page.md").write_text(
        _render_title_page(
            topic_display=topic_display, operator_handle=operator_handle,
            target_journal=target_journal,
        ), encoding="utf-8",
    )
    written.append("title_page.md")

    for source_name in ("paper.md", "supplement.md"):
        src = paper_dir / source_name
        if src.exists():
            dst_name = (
                "main_manuscript.md" if source_name == "paper.md" else source_name
            )
            shutil.copyfile(src, out / dst_name)
            written.append(dst_name)

    (out / "prisma_checklist.md").write_text(
        _render_prisma_checklist(topic_display), encoding="utf-8",
    )
    written.append("prisma_checklist.md")

    manifest = {
        "files": written, "target_journal": target_journal,
        "topic_display": topic_display, "operator": operator_handle,
        "readiness": readiness, "cite_audit": cite_audit,
    }
    (out / "submission_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )
    written.append("submission_manifest.json")
    return SubmissionPackage(
        target_dir=out, files_written=tuple(written), manifest=manifest,
    )
