"""Sprint 15 — one-command runner tests.

Exercises `scripts/build_topic_paper.py` without spawning real
subprocesses: we monkeypatch `subprocess.run` to record the command
sequence, and seed `_RUNS` with empty s7 + paper directories so the
glob-resolvers find something. The point is to lock the stage-ordering
contract (eligibility → freeze → extract → intro → methods → results →
discussion → stitch → supplement) and the --skip semantics.

Universal: no biomedical literals; every test uses generic topic
strings.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest


def _load_runner() -> Any:
    path = Path(__file__).resolve().parent.parent / "scripts" / "build_topic_paper.py"
    spec = importlib.util.spec_from_file_location("build_topic_paper", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RUNNER = _load_runner()


class _FakeProc:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


def _install_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, topic: str) -> Path:
    """Seed tmp_path with an s7 dir and a paper dir so the runner's
    glob-resolvers return real paths after each subprocess is faked."""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / f"{topic}-s7-iter-01-2026").mkdir()
    (runs / f"{topic}-paper-2026-05-13T00-00-00Z").mkdir()
    monkeypatch.setattr(_RUNNER, "_RUNS", runs)
    return runs


def test_build_runs_all_nine_stages_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_runs(monkeypatch, tmp_path, "rapamycin")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> _FakeProc:
        calls.append([str(c) for c in cmd])
        return _FakeProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    _RUNNER.build("rapamycin", iter_n=1)
    stage_scripts = [Path(c[1]).name for c in calls]
    assert stage_scripts == [
        "run_eligibility.py", "freeze_primary_set.py", "extract_effects.py",
        "draft_main.py", "draft_main.py", "build_results.py",
        "draft_main.py", "stitch_paper.py", "build_supplement.py",
    ]


def test_build_halts_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_runs(monkeypatch, tmp_path, "rapamycin")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> _FakeProc:
        calls.append([str(c) for c in cmd])
        return _FakeProc(1 if len(calls) == 2 else 0)  # freeze fails

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match=r"stage 'freeze' exited 1"):
        _RUNNER.build("rapamycin", iter_n=1)
    assert len(calls) == 2  # halt after the failing stage


def test_build_skip_set_bypasses_named_stages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_runs(monkeypatch, tmp_path, "carbon_tax")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> _FakeProc:
        calls.append([str(c) for c in cmd])
        return _FakeProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    _RUNNER.build(
        "carbon_tax", iter_n=2,
        skip={"eligibility", "freeze", "extract", "supplement"},
    )
    scripts = [Path(c[1]).name for c in calls]
    assert "run_eligibility.py" not in scripts
    assert "freeze_primary_set.py" not in scripts
    assert "extract_effects.py" not in scripts
    assert "build_supplement.py" not in scripts
    # but the drafting + stitching stages still ran
    assert scripts.count("draft_main.py") == 3
    assert "stitch_paper.py" in scripts


def test_build_rejects_unknown_skip_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_runs(monkeypatch, tmp_path, "rapamycin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_a, **_kw: _FakeProc(0),  # pragma: no cover — never reached
    )
    with pytest.raises(ValueError, match=r"unknown stage"):
        _RUNNER.build("rapamycin", skip={"polish_writer"})


def test_build_raises_when_eligibility_produces_no_s7_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """If the eligibility stage silently produces no s7 directory (e.g.
    Researka returns 0 hits), the runner must fail loudly rather than
    feed a None path to the freeze stage."""
    runs = tmp_path / "runs"
    runs.mkdir()  # no s7 dir seeded
    monkeypatch.setattr(_RUNNER, "_RUNS", runs)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: _FakeProc(0))
    with pytest.raises(RuntimeError, match=r"no runs/.*s7-iter"):
        _RUNNER.build("rapamycin", iter_n=1)
