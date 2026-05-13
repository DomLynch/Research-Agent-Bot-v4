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
