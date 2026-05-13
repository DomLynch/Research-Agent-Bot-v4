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

    def wait(self) -> int:
        """Mimic subprocess.Popen.wait() for Sprint 36 parallel block."""
        return self.returncode


def _install_subprocess_mocks(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]],
    *, fail_at: int | None = None,
) -> None:
    """Sprint 36: parallel runner uses subprocess.Popen for the draft
    block; sequential runner uses subprocess.run. Patch both so tests
    don't spawn real processes regardless of code path."""
    def fake_proc(cmd: list[str], **_: Any) -> _FakeProc:
        calls.append([str(c) for c in cmd])
        rc = 1 if fail_at is not None and len(calls) == fail_at else 0
        return _FakeProc(rc)

    monkeypatch.setattr(subprocess, "run", fake_proc)
    monkeypatch.setattr(subprocess, "Popen", fake_proc)


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
    _install_subprocess_mocks(monkeypatch, calls)
    _RUNNER.build("rapamycin", iter_n=1)
    stage_scripts = [Path(c[1]).name for c in calls]
    # Sprint 36: draft stages now run in parallel (intro / methods /
    # discussion / results), so their order within the parallel block
    # is non-deterministic. Lock the sequence of UNIQUE stages instead.
    assert stage_scripts[0:3] == [
        "run_eligibility.py", "freeze_primary_set.py", "extract_effects.py",
    ]
    parallel_block = set(stage_scripts[3:-2])
    assert parallel_block == {"draft_main.py", "build_results.py"}
    assert stage_scripts[-2:] == ["stitch_paper.py", "build_supplement.py"]
    # 3 draft_main.py invocations (intro, methods, discussion).
    assert stage_scripts.count("draft_main.py") == 3


def test_build_halts_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Sequential stages (eligibility, freeze, extract, stitch,
    supplement) halt the pipeline on non-zero exit."""
    _install_runs(monkeypatch, tmp_path, "rapamycin")
    calls: list[list[str]] = []
    _install_subprocess_mocks(monkeypatch, calls, fail_at=2)  # freeze fails
    with pytest.raises(RuntimeError, match=r"stage 'freeze' exited 1"):
        _RUNNER.build("rapamycin", iter_n=1)
    assert len(calls) == 2  # halt after the failing stage


def test_build_skip_set_bypasses_named_stages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_runs(monkeypatch, tmp_path, "carbon_tax")
    calls: list[list[str]] = []
    _install_subprocess_mocks(monkeypatch, calls)
    _RUNNER.build(
        "carbon_tax", iter_n=2,
        skip={"eligibility", "freeze", "extract", "supplement"},
    )
    scripts = [Path(c[1]).name for c in calls]
    assert "run_eligibility.py" not in scripts
    assert "freeze_primary_set.py" not in scripts
    assert "extract_effects.py" not in scripts
    assert "build_supplement.py" not in scripts
    # the drafting + stitching stages still ran (parallel + stitch)
    assert scripts.count("draft_main.py") == 3
    assert "stitch_paper.py" in scripts


def test_build_rejects_unknown_skip_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_runs(monkeypatch, tmp_path, "rapamycin")
    _install_subprocess_mocks(monkeypatch, [])
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
    _install_subprocess_mocks(monkeypatch, [])
    with pytest.raises(RuntimeError, match=r"no runs/.*s7-iter"):
        _RUNNER.build("rapamycin", iter_n=1)


def test_build_parallel_block_raises_on_any_stage_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Sprint 36: the parallel-draft block must raise if ANY of the
    concurrent stages return non-zero. We rig a Popen mock that fails
    only on the third call (= 1st parallel stage after sequential
    eligibility + freeze + extract)."""
    _install_runs(monkeypatch, tmp_path, "rapamycin")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> _FakeProc:
        calls.append([str(c) for c in cmd])
        return _FakeProc(0)  # sequential stages all OK

    def fake_popen(cmd: list[str], **_: Any) -> _FakeProc:
        calls.append([str(c) for c in cmd])
        # First parallel-block call fails — every other returns 0.
        return _FakeProc(1 if len(calls) == 4 else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError, match=r"parallel stages failed"):
        _RUNNER.build("rapamycin", iter_n=1)
