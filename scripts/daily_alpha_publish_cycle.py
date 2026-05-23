"""Daily ReseaRka alpha memo publish cycle.

Safe by default: builds/reads the publish queue, selects at most one
publishable memo, writes a daily ledger, and only calls Researka when
`--submit` is explicit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"

Json = dict[str, Any]
Fetcher = Callable[[str], Json]
Submitter = Callable[[Json], Json]
_SUBMIT_TOKEN_ENVS = (
    "RESEARKA_API_KEY_V4",
    "RESEARKA_API_TOKEN_V4",
    "RESEARKA_AGENT_TOKEN_V4",
    "RESEARCH_API_KEY_V4",
)


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _submit_token() -> tuple[str, str]:
    for name in _SUBMIT_TOKEN_ENVS:
        token = os.environ.get(name, "").strip()
        if token:
            return token, name
    return "", ""


def _topic(run: Path) -> str:
    return run.name.split("-evidence-", 1)[0]


def _build_queue(runs_root: Path, include_archive: bool) -> Json:
    """Read existing verdicts; do not recompute or mutate run artifacts."""
    patterns = ["*-evidence-*/publish_verdict.json"]
    if include_archive:
        patterns.append("_archive/*/*-evidence-*/publish_verdict.json")
    latest: dict[str, Path] = {}
    for pattern in patterns:
        for path in runs_root.glob(pattern):
            run = path.parent
            topic = _topic(run)
            if topic not in latest or run.name > latest[topic].name:
                latest[topic] = run
    rows = [
        _json(run / "publish_verdict.json", {})
        for run in latest.values()
    ]
    valid = [r for r in rows if isinstance(r, dict)]
    rank = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2}
    valid.sort(key=lambda r: (
        rank.get(str(r.get("publish_tier")), 9),
        -int(r.get("alpha_score") or 0),
        str(r.get("topic") or ""),
    ))
    return {
        "ready_to_publish": [
            r for r in valid if r.get("decision") == "ready_to_publish"
        ],
        "needs_operator_review": [
            r for r in valid if r.get("decision") == "needs_operator_review"
        ],
        "curation_needed": [
            r for r in valid if r.get("decision") == "curation_needed"
        ],
    }


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _run_path(root: Path, run_ref: Any) -> Path:
    ref = Path(str(run_ref or ""))
    if ref.parts[:1] == ("runs",):
        return root.parent / ref if root.name == "runs" else root / ref
    return root / ref


def memo_fingerprint(verdict: Json) -> str:
    """Deterministic duplicate key, stable across headline rewording."""
    receipts = verdict.get("receipt_expansion") or {}
    axes = verdict.get("axes") or {}
    cited = sorted(str(x) for x in receipts.get("cited_bound_fact_ids", []))[:3]
    papers = axes.get("source_papers", [])
    dois = sorted(
        _norm((p or {}).get("doi") or (p or {}).get("title"))
        for p in papers if isinstance(p, dict)
    )[:2]
    direction = "|".join([
        _norm(verdict.get("topic")),
        _norm(verdict.get("surface_type")),
        _norm(verdict.get("confidence_label")),
        _norm(verdict.get("publish_tier")),
    ])
    raw = json.dumps({
        "cited": cited,
        "dois": dois,
        "direction": direction,
    }, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rows(queue: Json, *, allow_tier2: bool) -> list[Json]:
    out = list(queue.get("ready_to_publish") or [])
    if allow_tier2:
        out.extend(queue.get("needs_operator_review") or [])
    return [r for r in out if isinstance(r, dict)]


def _approved(verdict: Json, root: Path) -> bool:
    if verdict.get("decision") == "ready_to_publish":
        return True
    run_dir = _run_path(root, verdict.get("run_dir"))
    return (run_dir / "approved.flag").exists()


def _has_memo(verdict: Json, root: Path) -> bool:
    run_dir = _run_path(root, verdict.get("run_dir"))
    return (run_dir / "alpha_memo.md").exists()


def _seen_submission_fingerprints(path: Path) -> set[str]:
    data = _json(path, [])
    if isinstance(data, list):
        return {str(x.get("fingerprint")) for x in data if isinstance(x, dict)}
    return set()


def select_candidate(
    queue: Json,
    *,
    runs_root: Path,
    submitted_path: Path,
    allow_tier2: bool = False,
) -> tuple[Json | None, list[Json]]:
    seen = _seen_submission_fingerprints(submitted_path)
    considered: list[Json] = []
    candidates = sorted(
        _rows(queue, allow_tier2=allow_tier2),
        key=lambda r: (
            0 if r.get("decision") == "ready_to_publish" else 1,
            -int(r.get("alpha_score") or 0),
            str(r.get("topic") or ""),
        ),
    )
    for verdict in candidates:
        fp = memo_fingerprint(verdict)
        status = "eligible"
        if fp in seen:
            status = "duplicate_submission_fingerprint"
        elif not _has_memo(verdict, runs_root):
            status = "missing_alpha_memo"
        elif not _approved(verdict, runs_root):
            status = "needs_operator_approval"
        row = {
            "topic": verdict.get("topic"),
            "decision": verdict.get("decision"),
            "publish_tier": verdict.get("publish_tier"),
            "alpha_score": verdict.get("alpha_score"),
            "run_dir": verdict.get("run_dir"),
            "fingerprint": fp,
            "status": status,
        }
        considered.append(row)
        if status == "eligible":
            return verdict | {"memo_fingerprint": fp}, considered
    return None, considered


def _cited_dois(verdict: Json) -> list[str]:
    papers = ((verdict.get("axes") or {}).get("source_papers") or [])
    out: list[str] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        doi = _norm(paper.get("doi"))
        if doi and doi not in out:
            out.append(doi)
    return out


def _crossref_fetch(doi: str) -> Json:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _has_retraction_marker(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_l = str(key).lower()
            if (
                key_l in {"subtype", "type", "update-type"}
                and "retraction" in str(value).lower()
            ):
                return True
            if key_l in {"update-to", "update-from"} and _has_retraction_marker(value):
                return True
            if key_l == "relation":
                if any("retract" in str(k).lower() for k in value):
                    return True
                if _has_retraction_marker(value):
                    return True
            if key_l.startswith("is-retract"):
                return True
    elif isinstance(payload, list):
        return any(_has_retraction_marker(item) for item in payload)
    return False


def retraction_check(
    verdict: Json,
    *,
    mode: str,
    fetcher: Fetcher = _crossref_fetch,
) -> Json:
    dois = _cited_dois(verdict)
    if mode == "skip":
        return {"status": "skipped", "checked_dois": dois, "retracted": []}
    if mode == "metadata":
        papers = ((verdict.get("axes") or {}).get("source_papers") or [])
        hits = [
            p for p in papers
            if isinstance(p, dict) and bool(p.get("is_retracted"))
        ]
        return {
            "status": "blocked" if hits else "clean",
            "checked_dois": dois,
            "retracted": hits,
        }
    retracted: list[Json] = []
    errors: list[Json] = []
    for doi in dois:
        try:
            payload = fetcher(doi)
        except Exception as exc:  # pragma: no cover - network defensive path
            errors.append({"doi": doi, "error": type(exc).__name__, "detail": str(exc)[:180]})
            continue
        message = payload.get("message", payload) if isinstance(payload, dict) else payload
        if _has_retraction_marker(message):
            retracted.append({"doi": doi, "source": "crossref"})
    status = "blocked" if retracted else ("error" if errors else "clean")
    return {
        "status": status,
        "checked_dois": dois,
        "retracted": retracted,
        "errors": errors,
    }


def _run_step(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    lines = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().splitlines()
    return result.returncode == 0, (lines[-1] if lines else "")


def _submission_payload(verdict: Json, root: Path) -> Json:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = ""
    with suppress(OSError):
        memo = (run_dir / "alpha_memo.md").read_text(encoding="utf-8")
    title = str(verdict.get("headline") or verdict.get("topic") or "Alpha memo")
    return {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": "agent-v4-alpha-memo",
        "agent_id": "agent-v4-alpha-memo",
        "title": title,
        "topic": verdict.get("topic"),
        "markdown": memo,
        "novelty_score": verdict.get("alpha_score"),
        "confidence_score": verdict.get("maturity_level"),
        "evidence_bundle": {
            "publish_verdict": verdict,
            "run_dir": verdict.get("run_dir"),
        },
        "content_hash": "sha256:" + hashlib.sha256(memo.encode("utf-8")).hexdigest(),
    }


def _http_submitter(url: str, token: str) -> Submitter:
    def submit(payload: Json) -> Json:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "x-api-key": token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                text = response.read().decode("utf-8")
                return {"ok": True, "status": response.status, "response": json.loads(text)}
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "response": text[:1000]}
    return submit


def submit_with_backoff(
    payload: Json,
    submitter: Submitter,
    *,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Json:
    attempts: list[Json] = []
    for i in range(retries + 1):
        result = submitter(payload)
        attempts.append(result)
        status = int(result.get("status") or 0)
        if result.get("ok"):
            return {"status": "accepted", "attempts": attempts}
        text = json.dumps(result.get("response", "")).lower()
        if "duplicate" in text:
            return {"status": "rejected_duplicate", "attempts": attempts}
        if "evidence" in text or "curation" in text:
            return {"status": "rejected_needs_evidence", "attempts": attempts}
        if status < 500:
            return {"status": "rejected", "attempts": attempts}
        if i < retries:
            sleep(2**i)
    return {"status": "failed_retry_exhausted", "attempts": attempts}


def run_cycle(
    *,
    runs_root: Path = _RUNS,
    date: str,
    queue: Json | None = None,
    include_archive: bool = False,
    refresh_candidates: bool = False,
    allow_tier2: bool = False,
    estimated_cost_usd: float = 0.0,
    max_cost_usd: float = 5.0,
    submit: bool = False,
    retraction_mode: str = "metadata",
    submitter: Submitter | None = None,
    fetcher: Fetcher = _crossref_fetch,
) -> Json:
    ledger_path = runs_root / "_daily_ledger" / f"{date}.json"
    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    ledger: Json = {
        "date": date,
        "dry_run": not submit,
        "estimated_cost_usd": estimated_cost_usd,
        "max_cost_usd": max_cost_usd,
        "published": 0,
        "published_topic": None,
        "submitted": 0,
        "submitted_topic": None,
        "status": "started",
    }
    if estimated_cost_usd > max_cost_usd:
        ledger.update({"status": "cost_cap_exceeded", "reason": "estimated_cost_above_cap"})
        _write_json(ledger_path, ledger)
        return ledger
    if refresh_candidates:
        ok, note = _run_step([
            sys.executable, "scripts/run_curator_cycle.py",
            "--top", "5", "--cooldown-hours", "24",
        ])
        ledger["refresh_candidates"] = {"ok": ok, "note": note}
        if not ok:
            ledger.update({"status": "candidate_refresh_failed"})
            _write_json(ledger_path, ledger)
            return ledger
    queue = queue if queue is not None else _build_queue(runs_root, include_archive)
    ledger["queue_counts"] = {
        key: len(queue.get(key) or [])
        for key in ("ready_to_publish", "needs_operator_review", "curation_needed")
    }
    candidate, considered = select_candidate(
        queue, runs_root=runs_root, submitted_path=submitted_path,
        allow_tier2=allow_tier2,
    )
    ledger["considered"] = considered
    if candidate is None:
        ledger.update({"status": "no_publishable_candidate", "reason": "no eligible non-duplicate memo"})
        _write_json(ledger_path, ledger)
        return ledger
    check_mode = "crossref" if submit and retraction_mode == "metadata" else retraction_mode
    retraction = retraction_check(candidate, mode=check_mode, fetcher=fetcher)
    ledger["retraction_check"] = retraction
    if retraction.get("status") != "clean":
        ledger.update({"status": "held_retraction_check", "candidate": candidate.get("topic")})
        _write_json(
            runs_root / "_retracted_holds" / f"{candidate.get('topic')}-{date}.json",
            ledger,
        )
        _write_json(ledger_path, ledger)
        return ledger
    ledger["candidate"] = {
        "topic": candidate.get("topic"),
        "run_dir": candidate.get("run_dir"),
        "fingerprint": candidate.get("memo_fingerprint"),
    }
    if not submit:
        ledger.update({"status": "dry_run_selected"})
        _write_json(ledger_path, ledger)
        return ledger
    if submitter is None:
        url = os.environ.get("RESEARKA_SUBMIT_URL", "https://api.researka.org/submissions")
        token, token_env = _submit_token()
        if not token:
            ledger.update({
                "status": "submit_not_configured",
                "reason": "missing_submit_token",
                "accepted_env_vars": list(_SUBMIT_TOKEN_ENVS),
            })
            _write_json(ledger_path, ledger)
            return ledger
        ledger["submit_token_env"] = token_env
        submitter = _http_submitter(url, token)
    result = submit_with_backoff(_submission_payload(candidate, runs_root), submitter)
    ledger["submission"] = result
    if result["status"] == "accepted":
        records = _json(submitted_path, [])
        if not isinstance(records, list):
            records = []
        records.append({
            "date": date,
            "topic": candidate.get("topic"),
            "run_dir": candidate.get("run_dir"),
            "fingerprint": candidate.get("memo_fingerprint"),
        })
        _write_json(submitted_path, records)
        ledger.update({
            "status": "submitted_to_researka",
            "submitted": 1,
            "submitted_topic": candidate.get("topic"),
        })
    else:
        ledger.update({"status": result["status"], "published": 0})
    _write_json(ledger_path, ledger)
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat())
    parser.add_argument("--include-archive", action="store_true")
    parser.add_argument("--refresh-candidates", action="store_true")
    parser.add_argument("--allow-tier2", action="store_true")
    parser.add_argument("--estimated-cost-usd", type=float, default=0.0)
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--retraction-check",
        choices=("metadata", "crossref", "skip"),
        default="metadata",
    )
    args = parser.parse_args()
    ledger = run_cycle(
        date=args.date,
        include_archive=args.include_archive,
        refresh_candidates=args.refresh_candidates,
        allow_tier2=args.allow_tier2,
        estimated_cost_usd=args.estimated_cost_usd,
        max_cost_usd=args.max_cost_usd,
        submit=args.submit,
        retraction_mode=args.retraction_check,
    )
    print(
        "[daily-alpha] "
        f"status={ledger['status']} submitted={ledger.get('submitted', 0)} "
        f"published={ledger['published']} "
        f"topic={ledger.get('submitted_topic') or ledger.get('published_topic') or ledger.get('candidate', {}).get('topic') or '-'}"
    )
    return 2 if ledger["status"] == "candidate_refresh_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
