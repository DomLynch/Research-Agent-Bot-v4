"""Integration: P9 novelty gate wired into publish_tier + build_signal_post.

Exercises novelty_overlay (off/advisory/enforce) against a novelty.json sidecar
and confirms build_signal_post's producer is dormant when the gate is off.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent.publish_tier as pt
import scripts.build_signal_post as bsp


def _run_with_novelty(tmp: Path, *, score: int, hallucinated: bool = False) -> Path:
    run = tmp / "run"
    run.mkdir(exist_ok=True)
    (run / "novelty.json").write_text(
        json.dumps({"score": score, "citation_hallucinated": hallucinated}),
        encoding="utf-8",
    )
    return run


def test_mode_env_overrides_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "enforce")
    assert pt.novelty_mode() == "enforce"
    monkeypatch.setenv("NOVELTY_GATE", "bogus")
    assert pt.novelty_mode() == "off"  # invalid env -> toml default (off)


def test_overlay_off_is_dormant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "off")
    run = _run_with_novelty(tmp_path, score=0, hallucinated=True)
    blockers: list[str] = []
    assert pt.novelty_overlay(run, blockers) == {}
    assert blockers == []  # decision untouched when dormant


def test_overlay_enforce_blocks_low_novelty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "enforce")
    run = _run_with_novelty(tmp_path, score=10)
    blockers: list[str] = []
    pt.novelty_overlay(run, blockers)
    assert "insufficient_novelty" in blockers


def test_overlay_enforce_blocks_hallucinated_even_if_novel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "enforce")
    run = _run_with_novelty(tmp_path, score=99, hallucinated=True)
    blockers: list[str] = []
    pt.novelty_overlay(run, blockers)
    assert "citation_hallucinated" in blockers


def test_overlay_advisory_records_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "advisory")
    run = _run_with_novelty(tmp_path, score=10)
    blockers: list[str] = []
    report = pt.novelty_overlay(run, blockers)
    assert blockers == []  # advisory never blocks
    assert "insufficient_novelty" in report["advisory_blockers"]


def test_overlay_missing_sidecar_has_no_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "enforce")
    run = tmp_path / "bare"
    run.mkdir()
    blockers: list[str] = []
    assert pt.novelty_overlay(run, blockers) == {}
    assert blockers == []


def test_signal_post_producer_is_noop_when_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVELTY_GATE", "off")
    run = tmp_path / "run"
    run.mkdir()
    bsp._write_novelty_sidecar(run)  # defined + importable + dormant
    assert not (run / "novelty.json").exists()
