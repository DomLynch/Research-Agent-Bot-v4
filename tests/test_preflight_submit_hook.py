from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

import scripts.daily_alpha_publish_cycle as daily

_ROOT_CANDIDATES = [
    Path(os.environ["RESEARKA_PREFLIGHT_QA_ROOT"]) if os.environ.get("RESEARKA_PREFLIGHT_QA_ROOT") else None,
    Path("/Users/domininclynch/Desktop/Business/Polish - Research agent"),
    Path("/opt/researka-preflight-qa"),
    Path(__file__).resolve().parents[2] / "Polish - Research agent",
]
PREFLIGHT_ROOT = next(path for path in _ROOT_CANDIDATES if path and path.is_dir())


def _payload(body: str) -> dict[str, Any]:
    return {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "title": "Alpha memo",
        "abstract": "This may be limited.",
        "markdown": body,
        "source_bundle": [{"title": "Limited source", "doi": "10.1000/abc", "excerpt": "limited"}],
        "evidence_bundle": {},
        "content_hash": "sha256:old",
    }


def test_final_preflight_hook_cleans_payload_in_enforce_mode(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = daily._run_preflight_qa(
        _payload("## Result\n\nThis may be limited.\n\nThis may be limited."),
        run,
    )

    assert report and report["status"] == "pass"
    assert payload is not None
    assert payload["markdown"].count("This may be limited.") == 1
    assert payload["evidence_bundle"]["preflight_qa"]["status"] == "pass"
    assert payload["content_hash"] != "sha256:old"


def test_final_preflight_hook_reports_bad_payload_in_enforce_mode(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = daily._run_preflight_qa(
        _payload("This may cite DOI 10.9999/missing."),
        run,
    )

    assert payload is not None
    assert report and report["status"] == "pass"
    assert "doi_not_in_source_bundle" in {r["code"] for r in report["advisories"]}
    assert "doi_not_in_source_bundle" in payload["evidence_bundle"]["preflight_qa"]["advisory_codes"]
