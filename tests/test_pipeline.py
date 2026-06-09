"""Pipeline report sidecar tests."""
from __future__ import annotations

import importlib.util
import json
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


def test_pipeline_stitch_writes_structured_report_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(_STITCH, "_RUNS", runs)
    _write_stage(runs, "s1", "# Rapamycin report\n\n## Abstract\n\nComplete.")
    _write_stage(runs, "s2", "## Methods\n\nComplete.")
    _write_stage(runs, "s6", "## Discussion\n\nComplete.")
    s7 = _write_stage(runs, "s7", "## Results\n\nEvidence includes study s086.")
    _write_receipts(s7)

    target = tmp_path / "out"
    paper = _STITCH.stitch("rapamycin", target=target)
    report = json.loads((target / "report.json").read_text(encoding="utf-8"))
    readiness = json.loads((target / "readiness_report.json").read_text(encoding="utf-8"))

    assert paper.name == "paper.md"
    assert paper.exists()
    assert report["markdown"]["path"] == "paper.md"
    assert "Evidence includes study s086." in paper.read_text(encoding="utf-8")
    assert set(report) >= {"Summary", "Evidence"}
    assert isinstance(report["Summary"], list)
    assert isinstance(report["Evidence"], list)
    assert report["Summary"][0]["label"] == readiness["label"] == "pilot-pool"
    assert any(row.get("study_id") == "s086" for row in report["Evidence"])
    assert any(
        row.get("source") == "effect_pool" and row.get("estimate") == 0.11
        for row in report["Evidence"]
    )


def _write_stage(runs: Path, short: str, body: str) -> Path:
    stage = runs / f"rapamycin-{short}-iter-01-2026-05-13T00-00-00Z"
    stage.mkdir()
    stage.joinpath("main_draft.md").write_text(body + "\n", encoding="utf-8")
    return stage


def _write_receipts(stage: Path) -> None:
    stage.joinpath("eligibility_summary.json").write_text(
        json.dumps({"k_eligible": 1}), encoding="utf-8",
    )
    stage.joinpath("primary_effect_input_set_strict.json").write_text(
        json.dumps({
            "A_core_direct_lifespan": [{
                "study_id": "s086",
                "title": "Rapamycin fed late in life extends lifespan",
                "doi": "10.1038/nature08221",
            }],
        }),
        encoding="utf-8",
    )
    stage.joinpath("effect_extractions.json").write_text(
        json.dumps({
            "receipts": [{
                "study_id": "s086",
                "status": "extracted",
                "metric": "log_median_ratio",
                "percent_change": 11.0,
            }],
        }),
        encoding="utf-8",
    )
    stage.joinpath("effect_pool.json").write_text(
        json.dumps({
            "effects": [{
                "study_id": "s086",
                "metric": "log_median_ratio",
                "estimate": 0.11,
                "se": 0.03,
            }],
        }),
        encoding="utf-8",
    )
