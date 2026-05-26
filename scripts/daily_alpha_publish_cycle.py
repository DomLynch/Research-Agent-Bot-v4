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
import re
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
DecisionFetcher = Callable[[str], Json]
Submitter = Callable[[Json], Json]
MemoRefresher = Callable[[Path, Json], bool]
_SUBMIT_TOKEN_ENVS = (
    "RESEARKA_API_KEY_V4",
    "RESEARKA_API_TOKEN_V4",
    "RESEARKA_AGENT_TOKEN_V4",
    "RESEARCH_API_KEY_V4",
)
_DEFAULT_MIN_SUBMIT_SOURCES = 5


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
    axes_raw = verdict.get("axes")
    axes = axes_raw if isinstance(axes_raw, dict) else {}
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


def _refresh_alpha_memo(run_dir: Path, verdict: Json) -> bool:
    if not (run_dir / "signal_post.md").exists():
        return False
    from agent.signal_memo_writer import write_signal_memo

    write_signal_memo(run_dir, publish_verdict=verdict)
    return True


def _seen_submission_fingerprints(path: Path) -> set[str]:
    data = _json(path, [])
    if isinstance(data, list):
        return {str(x.get("fingerprint")) for x in data if isinstance(x, dict)}
    return set()


def _source_count(verdict: Json, root: Path | None = None) -> int:
    if root is not None:
        papers = _memo_source_papers(verdict, root)
        if papers:
            return len(papers)
    return _source_count_from_verdict(verdict)


def _memo_receipt_ids(text: str) -> list[str]:
    match = re.search(
        r"^## Evidence receipts\n\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.M | re.S,
    )
    section = match.group(1) if match else ""
    seen: set[str] = set()
    out: list[str] = []
    for fid in re.findall(r"`fact_id=([^`\s]+)`", section):
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def _source_key_from_fact(fact: Json) -> str:
    paper = fact.get("source_paper") or {}
    if not isinstance(paper, dict):
        return ""
    return _norm(paper.get("doi") or paper.get("pmid") or paper.get("title"))


def _memo_source_papers(verdict: Json, root: Path) -> list[Json]:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    ids = _memo_receipt_ids(memo)
    if not ids:
        return []
    facts = _json(run_dir / "all_facts.json", [])
    if not isinstance(facts, list):
        return []
    by_id = {
        str(f.get("fact_id") or ""): f
        for f in facts if isinstance(f, dict)
    }
    seen: set[str] = set()
    papers: list[Json] = []
    for fid in ids:
        fact = by_id.get(fid) or {}
        key = _source_key_from_fact(fact)
        if not key or key in seen:
            continue
        seen.add(key)
        paper = fact.get("source_paper") or {}
        if isinstance(paper, dict):
            papers.append({
                "doi": str(paper.get("doi") or ""),
                "title": str(paper.get("title") or ""),
                "journal": str(paper.get("journal") or ""),
                "url": paper.get("url") or paper.get("source_url"),
                "year": paper.get("year"),
                "is_retracted": bool(paper.get("is_retracted")),
            })
    return papers


def _memo_headline(memo: str) -> str:
    match = re.search(r"^\*\*Headline:\*\*\s*(.+?)\s*$", memo, flags=re.M)
    return match.group(1).strip() if match else ""


def _year(value: Any) -> int | None:
    try:
        year = int(str(value))
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 3000 else None


def _evidence_type(paper: Json) -> str:
    title = _norm(paper.get("title"))
    if "review" in title or "meta-analysis" in title or "meta analysis" in title:
        return "review"
    return "primary"


def _source_bundle(papers: list[Json]) -> list[Json]:
    bundle: list[Json] = []
    for paper in papers:
        title = str(paper.get("title") or "").strip()
        if not title:
            continue
        bundle.append({
            "title": title,
            "url": paper.get("url") or None,
            "doi": str(paper.get("doi") or "").strip() or None,
            "year": _year(paper.get("year")),
            "evidence_type": _evidence_type(paper),
        })
    return bundle


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _source_count_from_verdict(verdict: Json) -> int:
    axes_raw = verdict.get("axes")
    axes = axes_raw if isinstance(axes_raw, dict) else {}
    papers = axes.get("source_papers") or []
    if isinstance(papers, list):
        keys = {
            _norm((p or {}).get("doi") or (p or {}).get("title"))
            for p in papers if isinstance(p, dict)
        }
        if keys:
            return len([k for k in keys if k])
    for count in (axes.get("source_count"), axes.get("selected_count")):
        if count is None:
            continue
        with suppress(TypeError, ValueError):
            return int(str(count))
    return 0


def _corpus_source_count(verdict: Json, root: Path) -> int:
    run_dir = _run_path(root, verdict.get("run_dir"))
    facts = _json(run_dir / "all_facts.json", [])
    lanes_raw = _json(run_dir / "fact_lanes.json", {})
    if not isinstance(facts, list) or not isinstance(lanes_raw, dict):
        return _source_count_from_verdict(verdict)
    lanes = {
        str(row.get("fact_id") or ""): str(row.get("lane") or "")
        for row in lanes_raw.get("verdicts", [])
        if isinstance(row, dict)
    }
    sources = {
        _source_key_from_fact(fact)
        for fact in facts
        if isinstance(fact, dict)
        and lanes.get(str(fact.get("fact_id") or "")) in {"A_core", "B_context"}
    }
    return len({s for s in sources if s})


def select_candidate(
    queue: Json,
    *,
    runs_root: Path,
    submitted_path: Path,
    allow_tier2: bool = False,
    min_source_count: int = 0,
    memo_refresher: MemoRefresher | None = None,
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
        source_count = _source_count(verdict, runs_root)
        corpus_source_count = _corpus_source_count(verdict, runs_root)
        status = "eligible"
        memo_refreshed = False
        if fp in seen:
            status = "duplicate_submission_fingerprint"
        elif not _has_memo(verdict, runs_root):
            status = "missing_alpha_memo"
        elif not _approved(verdict, runs_root):
            status = "needs_operator_approval"
        elif source_count < min_source_count:
            if corpus_source_count >= min_source_count and memo_refresher:
                run_dir = _run_path(runs_root, verdict.get("run_dir"))
                memo_refreshed = memo_refresher(run_dir, verdict)
                if memo_refreshed:
                    source_count = _source_count(verdict, runs_root)
            status = (
                "corpus_source_floor_below_min"
                if corpus_source_count < min_source_count else
                "memo_source_floor_below_min"
            )
            if source_count >= min_source_count:
                status = "eligible"
        row = {
            "topic": verdict.get("topic"),
            "decision": verdict.get("decision"),
            "publish_tier": verdict.get("publish_tier"),
            "alpha_score": verdict.get("alpha_score"),
            "run_dir": verdict.get("run_dir"),
            "fingerprint": fp,
            "source_count": source_count,
            "corpus_ab_paper_count": corpus_source_count,
            "min_source_count": min_source_count,
            "status": status,
        }
        if memo_refreshed:
            row["memo_refreshed"] = True
        considered.append(row)
        if status == "eligible":
            return verdict | {"memo_fingerprint": fp}, considered
    return None, considered


def _cited_dois(verdict: Json, runs_root: Path | None = None) -> list[str]:
    memo_papers = (
        _memo_source_papers(verdict, runs_root)
        if runs_root is not None else
        []
    )
    papers = memo_papers or ((verdict.get("axes") or {}).get("source_papers") or [])
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


def _decision_fetch(submission_id: str) -> Json:
    base = os.environ.get("RESEARKA_DECISION_URL_BASE", "https://api.researka.org/submissions")
    url = base.rstrip("/") + "/" + urllib.parse.quote(submission_id, safe="") + "/decision"
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _submission_id(payload: Json) -> str:
    direct = payload.get("submission_id")
    if direct:
        return str(direct)
    submission = payload.get("submission")
    if isinstance(submission, dict) and submission.get("id"):
        return str(submission.get("id"))
    for attempt in payload.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        response = attempt.get("response")
        if isinstance(response, dict):
            found = _submission_id(response)
            if found:
                return found
    nested = payload.get("submission")
    return str(nested.get("id") if isinstance(nested, dict) else "")


def sync_submission_decisions(
    runs_root: Path = _RUNS,
    *,
    fetcher: DecisionFetcher = _decision_fetch,
) -> Json:
    ledger_dir = runs_root / "_daily_ledger"
    summary: Json = {"checked": 0, "updated": 0, "pending": 0, "errors": []}
    for path in sorted(ledger_dir.glob("*.json")):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or ledger.get("status") != "submitted_to_researka":
            continue
        if ledger.get("final_verdict") in {"accepted", "rejected"}:
            continue
        submission_id = _submission_id(ledger.get("submission", {}))
        if not submission_id:
            continue
        summary["checked"] += 1
        try:
            decision = fetcher(submission_id)
        except Exception as exc:  # pragma: no cover - network defensive path
            summary["errors"].append({
                "ledger": path.name,
                "submission_id": submission_id,
                "error": type(exc).__name__,
                "detail": str(exc)[:180],
            })
            continue
        final = "pending"
        if decision.get("status") == "complete":
            final = "accepted" if decision.get("decision") == "accept" else "rejected"
        summary["pending"] += int(final == "pending")
        ledger["submission_id"] = submission_id
        ledger["researka_decision"] = decision
        ledger["final_verdict"] = final
        if final != "pending":
            summary["updated"] += 1
        _write_json(path, ledger)
    return summary


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
    runs_root: Path | None = None,
) -> Json:
    dois = _cited_dois(verdict, runs_root)
    if mode == "skip":
        return {"status": "skipped", "checked_dois": dois, "retracted": []}
    if mode == "metadata":
        memo_papers = (
            _memo_source_papers(verdict, runs_root)
            if runs_root is not None else
            []
        )
        papers = memo_papers or ((verdict.get("axes") or {}).get("source_papers") or [])
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
    title = str(
        _memo_headline(memo)
        or verdict.get("headline")
        or verdict.get("topic")
        or "Alpha memo"
    )
    source_papers = _memo_source_papers(verdict, root)
    source_bundle = _source_bundle(source_papers)
    receipt_count = len(_memo_receipt_ids(memo))
    return {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": "agent-v4-alpha-memo",
        "agent_id": "agent-v4-alpha-memo",
        "title": title,
        "topic": verdict.get("topic"),
        "markdown": memo,
        "citations": source_bundle,
        "source_bundle": source_bundle,
        "novelty_score": verdict.get("alpha_score"),
        "confidence_score": verdict.get("maturity_level"),
        "evidence_bundle": {
            "publish_verdict": verdict,
            "run_dir": verdict.get("run_dir"),
            "source_papers": source_papers,
            "bound_receipt_count": receipt_count,
            "bound_source_count": len(source_bundle),
            "source_bundle_count": len(source_bundle),
            "context_sources_are_not_direct_support": False,
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
    min_submit_sources: int = _DEFAULT_MIN_SUBMIT_SOURCES,
    submitter: Submitter | None = None,
    fetcher: Fetcher = _crossref_fetch,
    decision_fetcher: DecisionFetcher = _decision_fetch,
    memo_refresher: MemoRefresher = _refresh_alpha_memo,
) -> Json:
    ledger_path = runs_root / "_daily_ledger" / f"{date}.json"
    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    decision_sync = sync_submission_decisions(runs_root, fetcher=decision_fetcher)
    ledger: Json = {
        "date": date,
        "dry_run": not submit,
        "decision_sync": decision_sync,
        "estimated_cost_usd": estimated_cost_usd,
        "max_cost_usd": max_cost_usd,
        "min_submit_sources": min_submit_sources,
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
        min_source_count=min_submit_sources if submit else 0,
        memo_refresher=memo_refresher if submit else None,
    )
    ledger["considered"] = considered
    if candidate is None:
        ledger.update({"status": "no_publishable_candidate", "reason": "no eligible non-duplicate memo"})
        _write_json(ledger_path, ledger)
        return ledger
    check_mode = "crossref" if submit and retraction_mode == "metadata" else retraction_mode
    retraction = retraction_check(
        candidate, mode=check_mode, fetcher=fetcher, runs_root=runs_root,
    )
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
        submission_id = _submission_id(result)
        records = _json(submitted_path, [])
        if not isinstance(records, list):
            records = []
        records.append({
            "date": date,
            "topic": candidate.get("topic"),
            "run_dir": candidate.get("run_dir"),
            "fingerprint": candidate.get("memo_fingerprint"),
            "submission_id": submission_id,
        })
        _write_json(submitted_path, records)
        ledger.update({
            "final_verdict": "pending",
            "status": "submitted_to_researka",
            "submitted": 1,
            "submitted_topic": candidate.get("topic"),
            "submission_id": submission_id,
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
    parser.add_argument("--min-submit-sources", type=int, default=_DEFAULT_MIN_SUBMIT_SOURCES)
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
        min_submit_sources=args.min_submit_sources,
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
