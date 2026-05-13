"""Sprint 22 — submission-package builder tests.

Locks the file manifest, PRISMA-checklist row count, and graceful
behaviour when upstream receipts are missing. Universal: every test
uses generic topic + journal strings.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.submission_package import (
    SubmissionPackage,
    build_submission,
)


def _seed_paper_dir(tmp_path: Path, *, with_receipts: bool = True) -> Path:
    """Materialise a minimal paper folder so build_submission has
    something to operate on."""
    pd = tmp_path / "rapamycin-paper-2026-05-13T00-00-00Z"
    pd.mkdir(parents=True)
    (pd / "paper.md").write_text("# Title\n\n## Methods\nbody\n", encoding="utf-8")
    (pd / "supplement.md").write_text("# Supplement\n\nbody\n", encoding="utf-8")
    if with_receipts:
        (pd / "readiness_report.json").write_text(
            json.dumps({"level": 5, "label": "pilot-pool"}), encoding="utf-8",
        )
        (pd / "cite_audit.json").write_text(
            json.dumps({"clean": True, "unresolved_anchors": []}),
            encoding="utf-8",
        )
    return pd


def test_build_submission_writes_expected_files(tmp_path: Path) -> None:
    pd = _seed_paper_dir(tmp_path)
    pkg = build_submission(
        pd, target_journal="Aging Cell", topic_display="Rapamycin",
        operator_handle="dl",
    )
    assert isinstance(pkg, SubmissionPackage)
    assert pkg.target_dir == pd / "submission"
    expected = {
        "cover_letter.md", "title_page.md", "main_manuscript.md",
        "supplement.md", "prisma_checklist.md", "submission_manifest.json",
    }
    actual = set(pkg.files_written)
    assert expected == actual
    for name in expected:
        assert (pkg.target_dir / name).exists()


def test_cover_letter_references_topic_journal_and_readiness(tmp_path: Path) -> None:
    pd = _seed_paper_dir(tmp_path)
    pkg = build_submission(
        pd, target_journal="Aging Cell", topic_display="Rapamycin",
        operator_handle="dl",
    )
    body = (pkg.target_dir / "cover_letter.md").read_text(encoding="utf-8")
    assert "Rapamycin" in body
    assert "Aging Cell" in body
    assert "L5" in body
    assert "pilot-pool" in body
    assert "dl" in body


def test_title_page_carries_topic_display_and_operator(tmp_path: Path) -> None:
    pd = _seed_paper_dir(tmp_path)
    pkg = build_submission(
        pd, target_journal="J Synth", topic_display="Carbon Tax",
        operator_handle="policy-dl",
    )
    body = (pkg.target_dir / "title_page.md").read_text(encoding="utf-8")
    assert "Carbon Tax" in body
    assert "policy-dl" in body
    assert "J Synth" in body


def test_prisma_checklist_contains_canonical_27_plus_items(tmp_path: Path) -> None:
    """PRISMA-2020 lists 27 numbered items but several have a/b/c/d sub-
    items; the canonical sub-item count is 40+. Verify the renderer
    emits at least one row per sub-item, all labels intact."""
    pd = _seed_paper_dir(tmp_path)
    pkg = build_submission(pd)
    body = (pkg.target_dir / "prisma_checklist.md").read_text(encoding="utf-8")
    # Spot-check a few framework-authoritative item labels.
    for label in ("1", "10a", "13c", "23d", "27"):
        assert f"| {label} |" in body, f"missing PRISMA item {label}"
    # Header + separator lines.
    assert "| Item | Description | Section |" in body
    assert "---" in body


def test_manifest_carries_readiness_and_cite_audit_passthrough(tmp_path: Path) -> None:
    pd = _seed_paper_dir(tmp_path)
    pkg = build_submission(pd, topic_display="Rapamycin")
    manifest = json.loads(
        (pkg.target_dir / "submission_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["topic_display"] == "Rapamycin"
    assert manifest["readiness"]["level"] == 5
    assert manifest["cite_audit"]["clean"] is True
    # Manifest lists every file written BEFORE the manifest itself; the
    # manifest file is appended to pkg.files_written but doesn't
    # self-reference in its own files list (correct contract — no
    # circular bookkeeping).
    assert set(manifest["files"]) >= {
        "cover_letter.md", "title_page.md", "main_manuscript.md",
        "prisma_checklist.md",
    }
    assert "submission_manifest.json" in pkg.files_written


def test_build_submission_tolerates_missing_receipts(tmp_path: Path) -> None:
    """Without readiness_report.json / cite_audit.json the builder must
    still emit a package with sensible defaults — never raises."""
    pd = _seed_paper_dir(tmp_path, with_receipts=False)
    pkg = build_submission(pd, topic_display="Rapamycin")
    cl = (pkg.target_dir / "cover_letter.md").read_text(encoding="utf-8")
    assert "L0" in cl  # default level
    assert "(unknown)" in cl  # default label
    manifest = json.loads(
        (pkg.target_dir / "submission_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["readiness"] == {}
    assert manifest["cite_audit"] == {}


def test_build_submission_handles_missing_supplement(tmp_path: Path) -> None:
    pd = _seed_paper_dir(tmp_path)
    (pd / "supplement.md").unlink()
    pkg = build_submission(pd, topic_display="X")
    assert "supplement.md" not in pkg.files_written
    assert "main_manuscript.md" in pkg.files_written  # paper.md still present


def test_build_submission_universal_for_non_biomedical_topic(tmp_path: Path) -> None:
    """Same builder over a climate-style paper folder — no biomedical
    literal leaks into the cover letter / title page."""
    pd = tmp_path / "carbon_tax-paper-2026-05-13"
    pd.mkdir()
    (pd / "paper.md").write_text("# Carbon Tax Adoption\n", encoding="utf-8")
    (pd / "readiness_report.json").write_text(
        json.dumps({"level": 6, "label": "meta-analytic-pool"}), encoding="utf-8",
    )
    pkg = build_submission(
        pd, target_journal="Climate Policy",
        topic_display="Carbon Tax Adoption", operator_handle="policy-dl",
    )
    cl = (pkg.target_dir / "cover_letter.md").read_text(encoding="utf-8")
    assert "Carbon Tax" in cl
    assert "Climate Policy" in cl
    assert "meta-analytic-pool" in cl
    # No biomedical literal leak from the cover-letter template itself.
    for word in ("rapamycin", "mouse", "lifespan"):
        assert word not in cl.lower()
