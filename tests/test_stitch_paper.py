"""Sprint 14 — stitch_paper hard gate tests.

The MiMo→Gemma writer fallback (Sprint 14) should eliminate
`[SECTIONS_PENDING]` markers upstream. If any remain, the stitcher
must refuse to write paper.md by default; --allow-pending preserves
the legacy partial-staging workflow.

Universal: tests load the script via importlib (it lives outside the
agent/ import path) and reuse the topic_pack loader against a real
on-disk pack to avoid mocking the entire pack contract.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


def _load_stitch_module() -> Any:
    path = Path(__file__).resolve().parent.parent / "scripts" / "stitch_paper.py"
    spec = importlib.util.spec_from_file_location("stitch_paper", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_STITCH = _load_stitch_module()


def test_stitch_refuses_when_any_section_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No s1/s2/s6/s7 bundles on disk → stitch() raises rather than
    write a paper.md littered with SECTIONS_PENDING markers."""
    monkeypatch.setattr(_STITCH, "_RUNS", tmp_path)
    with pytest.raises(RuntimeError, match=r"missing section"):
        _STITCH.stitch("rapamycin", target=tmp_path / "out")


def test_stitch_allow_pending_writes_partial_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--allow-pending bypasses the hard gate so the operator can stage
    a partial draft. The written paper.md retains SECTIONS_PENDING tokens
    transparently — never silently dropped."""
    monkeypatch.setattr(_STITCH, "_RUNS", tmp_path)
    out = _STITCH.stitch(
        "rapamycin", target=tmp_path / "out", allow_pending=True,
    )
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "[SECTIONS_PENDING:title_abstract_intro" in body
    assert "[SECTIONS_PENDING:methods" in body


def test_stitch_allow_pending_emits_readiness_and_cite_audit_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprints 16 + 17: every stitched paper folder must carry
    readiness_report.json + cite_audit.json alongside paper.md, even
    when --allow-pending is used (so reviewers see the L-level + cite
    state on partial drafts too)."""
    monkeypatch.setattr(_STITCH, "_RUNS", tmp_path)
    target = tmp_path / "out"
    _STITCH.stitch("rapamycin", target=target, allow_pending=True)
    assert (target / "readiness_report.json").exists()
    assert (target / "cite_audit.json").exists()
    import json
    readiness = json.loads((target / "readiness_report.json").read_text())
    assert readiness["level"] == 1  # no receipts present
    assert readiness["label"] == "scaffold"
    cite_audit = json.loads((target / "cite_audit.json").read_text())
    # No body cites and no resolved references when scaffolding empty
    # → audit is structurally clean (no defects to flag).
    assert cite_audit["clean"] is True


# ---------------------------------------------------------------------------
# Sprint 31 — mid-sentence truncation hard gate.
# ---------------------------------------------------------------------------


def test_ends_cleanly_accepts_terminal_punctuation() -> None:
    """Sections ending with `.`, `!`, `?`, `:`, `)`, `]`, `}`, or
    backtick are considered complete — matches the writer's natural
    end-of-paragraph patterns + Markdown list/code-block closers."""
    for ending in (".", "!", "?", ":", ")", "]", "}", "`"):
        body = f"## Methods\n\nThis is the last sentence{ending}\n"
        assert _STITCH._ends_cleanly(body), f"failed for {ending!r}"


def test_ends_cleanly_rejects_alphanumeric_truncation() -> None:
    """A section that ends mid-word (no terminal punctuation) is
    flagged — this is the exact failure mode seen in the acarbose
    Methods cut-off: '...the metric family to which the outcome'."""
    body = (
        "## Methods\n\nFrom each included study the pipeline extracted "
        "the reported effect size and the metric family to which the outcome"
    )
    assert not _STITCH._ends_cleanly(body)


def test_ends_cleanly_ignores_trailing_blank_lines() -> None:
    """Trailing newlines / whitespace don't fool the check — the LAST
    non-blank line is what matters."""
    body = "## Discussion\n\nFinal sentence.\n\n\n   \n"
    assert _STITCH._ends_cleanly(body)


def test_find_truncated_sections_skips_pending_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sections that carry the SECTIONS_PENDING marker are flagged by a
    DIFFERENT gate (Sprint 14); the Sprint 31 gate should NOT double-
    flag them as truncated."""
    intro = "[SECTIONS_PENDING:title_abstract_intro — run …]"
    methods = "## Methods\n\nIncomplete sentence missing terminal"
    results = "## Results\n\nFinal sentence."
    discussion = "## Discussion\n\nAnother final sentence."
    flagged = _STITCH._find_truncated_sections(intro, methods, results, discussion)
    assert "title_abstract_intro" not in flagged  # SECTIONS_PENDING gate's job
    assert "methods" in flagged  # this is the real truncation
    assert "results" not in flagged
    assert "discussion" not in flagged


def test_stitch_refuses_when_section_truncates_mid_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full integration: a stage bundle whose main_draft.md ends
    mid-sentence is rejected by stitch unless --allow-pending."""
    runs = tmp_path
    monkeypatch.setattr(_STITCH, "_RUNS", runs)
    for short, body in (
        ("s1", "# Title\n\n## Abstract\n\nDone here.\n"),
        ("s2", "## Methods\n\nThe pipeline extracted the metric family to which the outcome"),
        ("s6", "## Discussion\n\nFinal."),
        ("s7", "## Results\n\nFinal."),
    ):
        d = runs / f"rapamycin-{short}-iter-01-2026-05-13T00-00-00Z"
        d.mkdir()
        (d / "main_draft.md").write_text(body, encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"mid-sentence section truncation"):
        _STITCH.stitch("rapamycin", target=tmp_path / "out")
