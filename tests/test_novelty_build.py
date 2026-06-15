"""Tests for the online novelty producer (agent/novelty_build.py).

Corpus left unconfigured so no network is hit for prior-art counts; citation
existence is stubbed via monkeypatch.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import agent.novelty_build as nb
from agent.novelty_gate import (
    CITATION_HALLUCINATED,
    INSUFFICIENT_NOVELTY,
    NoveltyConfig,
)
from agent.settings import load_settings

CFG = NoveltyConfig()


def _settings(url: str = "", token: str = "") -> Any:  # unconfigured by default
    return replace(load_settings(), researka_database_url=url, researka_database_token=token)


def _write_run(tmp: Path, facts: list[dict[str, Any]], lanes: list[dict[str, Any]]) -> Path:
    run = tmp / "rapamycin-evidence-20260615"
    run.mkdir()
    (run / "all_facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (run / "fact_lanes.json").write_text(json.dumps({"verdicts": lanes}), encoding="utf-8")
    return run


def _fact(fid: str, **kw: Any) -> dict[str, Any]:
    f = {
        "fact_id": fid, "canonical_phrase": "rapamycin extends lifespan in mice",
        "intervention": "rapamycin", "outcome": "lifespan", "_domain": "longevity",
        "source_paper": {"doi": f"10.1/{fid}", "title": "Rapamycin paper", "year": 2025},
    }
    f.update(kw)
    return f


@pytest.fixture(autouse=True)
def _no_citation_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default: citations exist (no hallucination). Individual tests override.
    monkeypatch.setattr(nb, "verify_sources", lambda *_a, **_k: {"has_hallucinated": False, "checked": 1})


def test_clean_recent_distinct_run_scores_high(tmp_path: Path) -> None:
    run = _write_run(tmp_path, [_fact("a1")], [{"fact_id": "a1", "lane": "A_core"}])
    rep = nb.build_novelty_report(run, settings=_settings(), now_year=2026, cfg=CFG)
    assert rep["corpus_prior_art_count"] is None      # unconfigured -> neutral scarcity
    assert rep["score"] >= CFG.min_score
    assert rep["blockers"] == []
    assert rep["a_core_count"] == 1


def test_hallucinated_citation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nb, "verify_sources", lambda *_a, **_k: {"has_hallucinated": True, "checked": 1})
    run = _write_run(tmp_path, [_fact("a1")], [{"fact_id": "a1", "lane": "A_core"}])
    rep = nb.build_novelty_report(run, settings=_settings(), now_year=2026, cfg=CFG)
    assert CITATION_HALLUCINATED in rep["blockers"]
    assert rep["citation_report"]["has_hallucinated"] is True


def test_crowded_stale_claim_is_insufficiently_novel(tmp_path: Path) -> None:
    # 3 identical-shape, old A_core facts -> distinctiveness 0, recency 0,
    # scarcity 0.5 (unconfigured) -> score 25 < 45. (Tokens must be >=3 chars
    # to survive the tokenizer, else shapes are empty and distinctiveness->1.0.)
    shape = dict(canonical_phrase="metformin lowers glucose", intervention="metformin", outcome="glucose")
    facts = [_fact(f"a{i}", source_paper={"doi": f"10.1/a{i}", "title": "t", "year": 2004}, **shape) for i in range(3)]
    lanes = [{"fact_id": f"a{i}", "lane": "A_core"} for i in range(3)]
    run = _write_run(tmp_path, facts, lanes)
    rep = nb.build_novelty_report(run, settings=_settings(), now_year=2026, cfg=CFG)
    assert INSUFFICIENT_NOVELTY in rep["blockers"]


def test_corpus_saturation_drives_scarcity_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Configured corpus returning a saturated count -> scarcity 0.
    monkeypatch.setattr(nb, "tier2_source_count", lambda *_a, **_k: CFG.saturation_count)
    run = _write_run(tmp_path, [_fact("a1", source_paper={"doi": "10.1/a1", "title": "t", "year": 2004})],
                     [{"fact_id": "a1", "lane": "A_core"}])
    rep = nb.build_novelty_report(
        run, settings=_settings(url="https://db", token="t"),
        now_year=2026, cfg=CFG,
    )
    assert rep["corpus_prior_art_count"] == CFG.saturation_count
    assert rep["scarcity"] == 0.0


def test_empty_run_is_neutral_non_blocking(tmp_path: Path) -> None:
    run = _write_run(tmp_path, [], [])
    rep = nb.build_novelty_report(run, settings=_settings(), now_year=2026, cfg=CFG)
    assert rep["blockers"] == []
    assert rep.get("note") == "no_a_core_facts"
