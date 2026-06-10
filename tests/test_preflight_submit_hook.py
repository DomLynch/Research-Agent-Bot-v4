from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

import scripts.daily_alpha_publish_cycle as daily


def _payload(body: str) -> dict[str, Any]:
    return {
        "artifact_type": "alpha_memo",
        "title": "Bounded memo",
        "abstract": "This may be limited.",
        "markdown": body,
        "source_bundle": [
            {"title": "Limited trial", "doi": "10.1000/abc", "excerpt": "limited signal"},
        ],
        "evidence_bundle": {},
        "content_hash": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def _enable_preflight(monkeypatch: MonkeyPatch) -> None:
    polish_root = Path(__file__).resolve().parents[2] / "researka-preflight-qa"
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(polish_root))


def test_preflight_enforce_cleans_payload_and_updates_hash(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    _enable_preflight(monkeypatch)
    body = "## Result\n\nThis may be limited.\n\nThis may be limited."

    checked, report = daily._run_preflight_qa(_payload(body), tmp_path)

    assert checked is not None
    assert report is not None
    assert report["status"] == "pass"
    assert checked["markdown"].count("This may be limited.") == 1
    assert checked["content_hash"] == (
        "sha256:" + hashlib.sha256(str(checked["markdown"]).encode("utf-8")).hexdigest()
    )
    assert checked["evidence_bundle"]["preflight_qa"]["status"] == "pass"
    assert (tmp_path / "researka_preflight_report.json").exists()
    assert (tmp_path / "researka_preflight_cleaned_payload.json").exists()


def test_preflight_enforce_blocks_before_submit(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _enable_preflight(monkeypatch)

    checked, report = daily._run_preflight_qa(
        _payload("## Result\n\nThis cites DOI 10.9999/missing."),
        tmp_path,
    )

    assert checked is None
    assert report is not None
    assert report["status"] == "block"
    assert "doi_not_in_source_bundle" in {
        row["code"] for row in report["blocked_reasons"] if isinstance(row, dict)
    }
