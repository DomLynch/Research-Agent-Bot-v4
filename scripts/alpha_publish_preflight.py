"""Preflight QA helpers for alpha publish submissions."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

Json = dict[str, Any]
RunSubprocess = Callable[..., subprocess.CompletedProcess[str]]

PREFLIGHT_MODE_ENV = "RESEARKA_PREFLIGHT_QA"
PREFLIGHT_ROOT_ENV = "RESEARKA_PREFLIGHT_QA_ROOT"
PREFLIGHT_USE_M3_ENV = "RESEARKA_PREFLIGHT_USE_M3"
PREFLIGHT_TIMEOUT_SECONDS = 90.0


def preflight_mode() -> str:
    mode = os.environ.get(PREFLIGHT_MODE_ENV, "off").strip().lower()
    return mode if mode in {"shadow", "enforce"} else "off"


def preflight_summary(report: Json) -> Json:
    reasons = report.get("blocked_reasons")
    reason_rows = reasons if isinstance(reasons, list) else []
    advisories = report.get("advisories")
    advisory_rows = advisories if isinstance(advisories, list) else []
    m3 = report.get("m3_result")
    return {
        "status": str(report.get("status") or "unknown"),
        "qa_version": str(report.get("qa_version") or ""),
        "safe_fixes_applied": report.get("safe_fixes_applied")
        if isinstance(report.get("safe_fixes_applied"), list) else [],
        "blocked_reason_codes": [
            str(row.get("code")) for row in reason_rows
            if isinstance(row, dict) and row.get("code")
        ],
        "advisory_codes": [
            str(row.get("code")) for row in advisory_rows
            if isinstance(row, dict) and row.get("code")
        ],
        "m3_status": str(m3.get("status") or "") if isinstance(m3, dict) else "",
    }


def attach_preflight_summary(payload: Json, report: Json) -> None:
    evidence = payload.get("evidence_bundle")
    if not isinstance(evidence, dict):
        evidence = {}
        payload["evidence_bundle"] = evidence
    evidence["preflight_qa"] = preflight_summary(report)


def refresh_content_hash(payload: Json) -> None:
    markdown = str(payload.get("markdown") or payload.get("body_markdown") or "")
    if markdown:
        payload["content_hash"] = "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run_preflight_qa(
    payload: Json,
    run_dir: Path,
    *,
    root: Path,
    read_json: Callable[[Path, Any], Any],
    write_json: Callable[[Path, Any], None],
    run_subprocess: RunSubprocess,
) -> tuple[Json | None, Json | None]:
    mode = preflight_mode()
    if mode == "off":
        return payload, None

    tool_root = Path(
        os.environ.get(PREFLIGHT_ROOT_ENV, str(root.parent / "researka-preflight-qa")),
    ).expanduser()
    input_path = run_dir / "researka_preflight_input.json"
    report_path = run_dir / "researka_preflight_report.json"
    clean_path = run_dir / "researka_preflight_cleaned_payload.json"
    write_json(input_path, payload)

    cmd = [
        sys.executable, "-m", "preflight_qa", "check",
        "--input", str(input_path),
        "--out", str(report_path),
        "--clean-out", str(clean_path),
    ]
    if _env_truthy(PREFLIGHT_USE_M3_ENV):
        cmd.append("--use-m3")
    try:
        proc = run_subprocess(cmd, timeout=PREFLIGHT_TIMEOUT_SECONDS, cwd=tool_root)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report: Json = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "safe_fixes_applied": [],
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_runtime_error",
                "severity": "minor",
                "message": f"{type(exc).__name__}: {exc}",
            }],
        }
        write_json(report_path, report)
    else:
        raw_report = read_json(report_path, {})
        report = raw_report if isinstance(raw_report, dict) else {}
        if proc.returncode not in {0, 2}:
            report = {
                "status": "pass",
                "qa_version": "preflight-v2",
                "safe_fixes_applied": [],
                "blocked_reasons": [],
                "advisories": [{
                    "code": "preflight_runtime_error",
                    "severity": "minor",
                    "message": (proc.stderr or proc.stdout or "preflight process failed")[:500],
                }],
            }
            write_json(report_path, report)

    if mode == "shadow":
        attach_preflight_summary(payload, report)
        return payload, report
    if report.get("status") != "pass":
        attach_preflight_summary(payload, report)
        return payload, report
    cleaned = read_json(clean_path, {})
    if not isinstance(cleaned, dict) or not cleaned:
        report = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "safe_fixes_applied": [],
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_missing_cleaned_payload",
                "severity": "minor",
                "message": "Preflight passed but did not write a cleaned payload.",
            }],
        }
        write_json(report_path, report)
        attach_preflight_summary(payload, report)
        return payload, report
    attach_preflight_summary(cleaned, report)
    refresh_content_hash(cleaned)
    return cleaned, report
