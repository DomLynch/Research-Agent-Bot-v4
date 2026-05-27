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
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from agent.alpha_selector import accepted_shape_bonus

_ROOT = Path(__file__).resolve().parent.parent
_RUNS = _ROOT / "runs"
_PUBLICATION_PATH = _ROOT / "topic_packs" / "publication.toml"

Json = dict[str, Any]
Fetcher = Callable[[str], Json]
DecisionFetcher = Callable[[str], Json]
Submitter = Callable[[Json], Json]
MemoRefresher = Callable[[Path, Json], bool]
QueueBuilder = Callable[[Path, bool], Json]
PageFetcher = Callable[[str], Json]
_SUBMIT_TOKEN_ENVS = (
    "RESEARKA_API_KEY_V4",
    "RESEARKA_API_TOKEN_V4",
    "RESEARKA_AGENT_TOKEN_V4",
    "RESEARCH_API_KEY_V4",
)
def _alpha_memo_int(name: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUBLICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    if not isinstance(alpha, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(alpha.get(name))))
    return default


_DEFAULT_MIN_SUBMIT_SOURCES = _alpha_memo_int("min_source_papers", 5)
_DEFAULT_MIN_DIRECT_SUBMIT_SOURCES = _alpha_memo_int("min_direct_source_papers", 2)
_DEFAULT_REFRESH_TOP = 20
_DEFAULT_MAX_REFRESH_BATCHES = 5
_REFRESH_TIMEOUT_SECONDS = 5400
_MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT = 4
_EXHAUSTED_STATUSES = {
    "duplicate_submission_fingerprint",
    "missing_alpha_memo",
    "needs_operator_approval",
    "corpus_source_floor_below_min",
    "memo_source_floor_below_min",
    "direct_source_floor_below_min",
    "cycle_failed_submission",
    "held_retraction_check",
}
_REPAIRABLE_REJECTION_REASONS = {
    "minimum_citations",
    "public_page_not_rendered",
    "recency_ratio",
    "reviewer_revise",
    "source_bundle_schema",
}


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _ledger_stamp(now: dt.datetime | None = None) -> str:
    current = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z").replace(":", "-")


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


def _with_repairable_candidates(queue: Json, runs_root: Path) -> Json:
    repairable = _repairable_candidate_verdicts(runs_root)
    if not repairable:
        return queue
    existing = {
        memo_fingerprint(row)
        for bucket in queue.values() if isinstance(bucket, list)
        for row in bucket if isinstance(row, dict)
    }
    additions = [row for row in repairable if memo_fingerprint(row) not in existing]
    if not additions:
        return queue
    merged = dict(queue)
    merged["ready_to_publish"] = additions + list(queue.get("ready_to_publish") or [])
    return merged


def _approved(verdict: Json, root: Path) -> bool:
    if verdict.get("decision") == "ready_to_publish":
        return True
    run_dir = _run_path(root, verdict.get("run_dir"))
    return (run_dir / "approved.flag").exists()


def _has_memo(verdict: Json, root: Path) -> bool:
    run_dir = _run_path(root, verdict.get("run_dir"))
    return (run_dir / "alpha_memo.md").exists()


def _refresh_alpha_memo(run_dir: Path, verdict: Json) -> bool:
    if "_archive" in run_dir.parts:
        return False
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


def _memo_sha256(verdict: Json, root: Path) -> str:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    return hashlib.sha256(memo.encode("utf-8")).hexdigest() if memo else ""


def _fingerprint_attempt_count(path: Path, fingerprint: str, memo_sha256: str) -> int:
    data = _json(path, [])
    if not isinstance(data, list):
        return 0
    return sum(
        1
        for row in data
        if isinstance(row, dict)
        and row.get("fingerprint") == fingerprint
        and (
            not memo_sha256
            or row.get("memo_sha256") == memo_sha256
        )
    )


def _repairable_rejected_fingerprints(ledger_dir: Path) -> set[str]:
    retryable: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or ledger.get("final_verdict") not in {"rejected", "revise"}
        ):
            continue
        if not _repairable_ledger(ledger):
            continue
        fp = str((ledger.get("candidate") or {}).get("fingerprint") or "")
        if fp:
            retryable.add(fp)
    return retryable


def _repairable_candidate_verdicts(runs_root: Path) -> list[Json]:
    verdicts: list[Json] = []
    seen: set[str] = set()
    for path in sorted((runs_root / "_daily_ledger").glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if (
            not isinstance(ledger, dict)
            or ledger.get("final_verdict") not in {"rejected", "revise"}
        ):
            continue
        if not _repairable_ledger(ledger):
            continue
        run_dir = _run_path(runs_root, (ledger.get("candidate") or {}).get("run_dir"))
        verdict = _json(run_dir / "publish_verdict.json", {})
        if not isinstance(verdict, dict) or not verdict:
            continue
        fp = memo_fingerprint(verdict)
        if fp in seen:
            continue
        seen.add(fp)
        verdicts.append(verdict)
    return verdicts


def _accepted_shape_profiles(runs_root: Path, *, limit: int = 25) -> list[Json]:
    profiles: list[Json] = []
    ledger_dir = runs_root / "_daily_ledger"
    for path in sorted(ledger_dir.glob("*.json"), reverse=True):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or ledger.get("final_verdict") != "accepted":
            continue
        candidate = ledger.get("candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        fp = str(candidate.get("fingerprint") or "")
        profile: Json = {}
        run_dir = _run_path(runs_root, candidate.get("run_dir"))
        verdict = _json(run_dir / "publish_verdict.json", {})
        if isinstance(verdict, dict):
            profile.update(verdict)
        for row in ledger.get("considered") or []:
            if isinstance(row, dict) and (not fp or row.get("fingerprint") == fp):
                profile.update(row)
                break
        if profile:
            profiles.append(profile)
        if len(profiles) >= limit:
            break
    return profiles


def _repairable_rejection(decision: Json) -> bool:
    if decision.get("decision") == "revise":
        return True
    reasons = {
        str(decision.get("failure_category") or ""),
        *(str(x) for x in decision.get("failed_checks") or []),
    }
    for gate in decision.get("gate_failures") or []:
        if isinstance(gate, dict):
            reasons.add(str(gate.get("name") or ""))
            reasons.add(str(gate.get("reason") or ""))
    text = " ".join(reasons).lower()
    return any(reason in text for reason in _REPAIRABLE_REJECTION_REASONS)


def _repairable_ledger(ledger: Json) -> bool:
    decision = ledger.get("researka_decision")
    if isinstance(decision, dict) and _repairable_rejection(decision):
        return True
    page = ledger.get("public_page_check")
    return (
        isinstance(page, dict)
        and str(page.get("status") or "") in {"missing_public_url", "not_rendered", "error"}
    )


def _source_count(verdict: Json, root: Path | None = None) -> int:
    if root is not None:
        papers = _memo_source_papers(verdict, root)
        if papers:
            return len(papers)
    return _source_count_from_verdict(verdict)


def _memo_receipt_ids(
    text: str,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
) -> list[str]:
    names = "|".join(re.escape(name) for name in section_names)
    sections = re.findall(
        rf"^## (?:{names}) receipts\n\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.M | re.S,
    )
    section = "\n".join(sections)
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


def _memo_source_papers(
    verdict: Json,
    root: Path,
    section_names: tuple[str, ...] = ("Evidence", "Context"),
    lane_names: set[str] | None = None,
) -> list[Json]:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = _read_text(run_dir / "alpha_memo.md")
    ids = _memo_receipt_ids(memo, section_names)
    if not ids:
        return []
    facts = _json(run_dir / "all_facts.json", [])
    if not isinstance(facts, list):
        return []
    by_id = {
        str(f.get("fact_id") or ""): f
        for f in facts if isinstance(f, dict)
    }
    lanes: dict[str, str] = {}
    if lane_names is not None:
        lanes_raw = _json(run_dir / "fact_lanes.json", {})
        if isinstance(lanes_raw, dict):
            lanes = {
                str(row.get("fact_id") or ""): str(row.get("lane") or "")
                for row in lanes_raw.get("verdicts", [])
                if isinstance(row, dict)
            }
    seen: set[str] = set()
    papers: list[Json] = []
    for fid in ids:
        if lane_names is not None and lanes.get(fid) not in lane_names:
            continue
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


def _direct_source_count(verdict: Json, root: Path) -> int:
    return len(_memo_source_papers(verdict, root, ("Evidence",), {"A_core"}))


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
    min_direct_source_count: int = 0,
    memo_refresher: MemoRefresher | None = None,
    blocked_fingerprints: set[str] | None = None,
    blocked_topics: set[str] | None = None,
    accepted_shape_profiles: list[Json] | None = None,
) -> tuple[Json | None, list[Json]]:
    seen = _seen_submission_fingerprints(submitted_path)
    retryable = _repairable_rejected_fingerprints(submitted_path.parent)
    blocked = blocked_fingerprints or set()
    topic_blocked = blocked_topics or set()
    shape_profiles = accepted_shape_profiles or []
    considered: list[Json] = []
    candidates = sorted(
        _rows(queue, allow_tier2=allow_tier2),
        key=lambda r: (
            0 if r.get("decision") == "ready_to_publish" else 1,
            -(int(r.get("alpha_score") or 0) + accepted_shape_bonus(r, shape_profiles)),
            str(r.get("topic") or ""),
        ),
    )
    for verdict in candidates:
        fp = memo_fingerprint(verdict)
        source_count = _source_count(verdict, runs_root)
        direct_source_count = _direct_source_count(verdict, runs_root)
        corpus_source_count = _corpus_source_count(verdict, runs_root)
        shape_bonus = accepted_shape_bonus(verdict, shape_profiles)
        status = "eligible"
        memo_refreshed = False
        has_memo = _has_memo(verdict, runs_root)
        memo_sha256 = _memo_sha256(verdict, runs_root) if has_memo else ""
        approved = _approved(verdict, runs_root) if has_memo else False
        cycle_blocked = fp in blocked
        exhausted_topic = str(verdict.get("topic") or "") in topic_blocked
        attempt_count = _fingerprint_attempt_count(submitted_path, fp, memo_sha256)
        retry_after_rejection = (
            fp in retryable
            and attempt_count < _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT
        )
        if (
            not cycle_blocked
            and has_memo
            and approved
            and (
                source_count < min_source_count
                or direct_source_count < min_direct_source_count
            )
            and (
                corpus_source_count >= min_source_count
                or source_count >= min_source_count
            )
            and memo_refresher
        ):
            run_dir = _run_path(runs_root, verdict.get("run_dir"))
            memo_refreshed = memo_refresher(run_dir, verdict)
            if memo_refreshed:
                source_count = _source_count(verdict, runs_root)
                direct_source_count = _direct_source_count(verdict, runs_root)
                corpus_source_count = _corpus_source_count(verdict, runs_root)
                memo_sha256 = _memo_sha256(verdict, runs_root)
                attempt_count = _fingerprint_attempt_count(submitted_path, fp, memo_sha256)
                retry_after_rejection = (
                    fp in retryable
                    and attempt_count < _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT
                )
        if exhausted_topic:
            status = "cycle_exhausted_topic"
        elif cycle_blocked:
            status = "cycle_failed_submission"
        elif fp in seen and not retry_after_rejection:
            status = "duplicate_submission_fingerprint"
        elif not has_memo:
            status = "missing_alpha_memo"
        elif not approved:
            status = "needs_operator_approval"
        else:
            if retry_after_rejection and memo_refresher and not memo_refreshed:
                run_dir = _run_path(runs_root, verdict.get("run_dir"))
                memo_refreshed = memo_refresher(run_dir, verdict)
                if memo_refreshed:
                    source_count = _source_count(verdict, runs_root)
                    direct_source_count = _direct_source_count(verdict, runs_root)
                    corpus_source_count = _corpus_source_count(verdict, runs_root)
                    memo_sha256 = _memo_sha256(verdict, runs_root)
                    attempt_count = _fingerprint_attempt_count(submitted_path, fp, memo_sha256)
                    retry_after_rejection = (
                        fp in retryable
                        and attempt_count < _MAX_SUBMISSION_ATTEMPTS_PER_FINGERPRINT
                    )
            if source_count < min_source_count:
                status = (
                    "corpus_source_floor_below_min"
                    if corpus_source_count < min_source_count else
                    "memo_source_floor_below_min"
                )
                if source_count >= min_source_count:
                    status = "eligible"
            elif direct_source_count < min_direct_source_count:
                status = "direct_source_floor_below_min"
        row = {
            "topic": verdict.get("topic"),
            "decision": verdict.get("decision"),
            "publish_tier": verdict.get("publish_tier"),
            "alpha_score": verdict.get("alpha_score"),
            "run_dir": verdict.get("run_dir"),
            "fingerprint": fp,
            "source_count": source_count,
            "direct_source_count": direct_source_count,
            "corpus_ab_paper_count": corpus_source_count,
            "min_source_count": min_source_count,
            "min_direct_source_count": min_direct_source_count,
            "accepted_shape_bonus": shape_bonus,
            "status": status,
        }
        if memo_refreshed:
            row["memo_refreshed"] = True
        if retry_after_rejection:
            row["retry_after_rejection"] = True
            row["retry_attempt_count"] = attempt_count
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


def _public_alpha_base() -> str:
    return os.environ.get("RESEARKA_ALPHA_BASE_URL", "https://researka.org/alpha").rstrip("/")


def _public_alpha_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    return _public_alpha_base() + "/" + urllib.parse.quote(raw, safe="")


def _public_alpha_urls(payload: Any) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        url = _public_alpha_url(value)
        if url and url not in urls:
            urls.append(url)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_l = str(key).lower()
                if key_l in {
                    "alpha_url",
                    "canonical_url",
                    "public_url",
                    "publication_url",
                    "url",
                }:
                    if "url" not in key_l or "/alpha/" in str(item):
                        add(item)
                elif "id" in key_l and any(
                    token in key_l for token in ("alpha", "artifact", "public", "publication")
                ):
                    add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return urls


def _fetch_public_page(url: str) -> Json:
    req = urllib.request.Request(url, headers={"User-Agent": "researka-v4/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {"ok": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read(512).decode("utf-8", errors="replace")}
    except Exception as exc:  # pragma: no cover - network defensive path
        return {"ok": False, "status": 0, "error": type(exc).__name__, "detail": str(exc)[:180]}


def _page_rendered(result: Json) -> bool:
    body = str(result.get("body") or "").lower()
    title_404 = re.search(r"<title>[^<]*(404|not found)[^<]*</title>", body)
    return bool(result.get("ok")) and int(result.get("status") or 0) == 200 and not title_404


def _public_page_check(decision: Json, *, page_fetcher: PageFetcher) -> Json:
    urls = _public_alpha_urls(decision)
    if not urls:
        return {"ok": False, "status": "missing_public_url", "urls": []}
    checks: list[Json] = []
    for url in urls:
        result = page_fetcher(url)
        check = {
            "url": url,
            "http_status": result.get("status"),
            "ok": _page_rendered(result),
        }
        if result.get("error"):
            check["error"] = result.get("error")
        checks.append(check)
        if check["ok"]:
            return {"ok": True, "status": "rendered", "url": url, "checks": checks}
    return {"ok": False, "status": "not_rendered", "urls": urls, "checks": checks}


def _apply_submission_decision(
    ledger: Json,
    *,
    submission_id: str,
    decision: Json,
    page_fetcher: PageFetcher,
) -> str:
    final = "pending"
    if decision.get("status") == "complete":
        if decision.get("decision") == "accept":
            page = _public_page_check(decision, page_fetcher=page_fetcher)
            ledger["public_page_check"] = page
            if page.get("ok"):
                final = "accepted"
                ledger["status"] = "published"
                ledger["published"] = 1
                ledger["published_topic"] = (
                    ledger.get("submitted_topic")
                    or (ledger.get("candidate") or {}).get("topic")
                )
                ledger["public_url"] = page.get("url")
            else:
                final = "rejected"
                ledger["status"] = "public_page_not_rendered"
                ledger["published"] = 0
                ledger["publish_failure_reason"] = "public_page_not_rendered"
        elif decision.get("decision") == "revise":
            final = "revise"
            ledger["status"] = "reviewer_revise"
        else:
            final = "rejected"
            ledger["status"] = "reviewer_rejected"
    ledger["submission_id"] = submission_id
    ledger["researka_decision"] = decision
    ledger["final_verdict"] = final
    return final


def sync_submission_decisions(
    runs_root: Path = _RUNS,
    *,
    fetcher: DecisionFetcher = _decision_fetch,
    page_fetcher: PageFetcher = _fetch_public_page,
) -> Json:
    ledger_dir = runs_root / "_daily_ledger"
    summary: Json = {"checked": 0, "updated": 0, "published": 0, "pending": 0, "errors": []}
    for path in sorted(ledger_dir.glob("*.json")):
        ledger = _json(path, {})
        if not isinstance(ledger, dict) or ledger.get("status") != "submitted_to_researka":
            continue
        if ledger.get("final_verdict") in {"accepted", "rejected", "revise"}:
            continue
        submission_id = str(ledger.get("submission_id") or "") or _submission_id(
            ledger.get("submission", {}),
        )
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
        final = _apply_submission_decision(
            ledger,
            submission_id=submission_id,
            decision=decision,
            page_fetcher=page_fetcher,
        )
        summary["pending"] += int(final == "pending")
        summary["published"] += int(final == "accepted")
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


def _refresh_candidate_batch(
    refresh_top: int, excluded_topics: set[str] | None = None,
) -> Json:
    exclusions = sorted(t for t in (excluded_topics or set()) if t)
    args = [
        sys.executable, "scripts/run_curator_cycle.py",
        "--top", str(refresh_top), "--cooldown-hours", "24",
    ]
    for topic in exclusions:
        args.extend(["--exclude-topic", topic])
    ok, note = _run_step(args, timeout=_REFRESH_TIMEOUT_SECONDS)
    return {"ok": ok, "note": note, "top": refresh_top, "excluded_topics": exclusions}


def _queue_counts(queue: Json) -> Json:
    return {
        key: len(queue.get(key) or [])
        for key in ("ready_to_publish", "needs_operator_review", "curation_needed")
    }


def _public_submission_markdown(memo: str) -> str:
    lines = [
        line for line in memo.splitlines()
        if not line.startswith("**Alpha score:**")
        and not line.startswith("**Alpha triage:**")
    ]
    text = "\n".join(lines).strip() + "\n"
    note = (
        "**Interpretation note:** This is a hypothesis-generating alpha memo, "
        "not confirmatory evidence; subgroup or context-derived claims require "
        "independent replication.\n"
    )
    if "## Why this is surprising" in text and note not in text:
        text = text.replace("\n## Why this is surprising", f"\n\n{note}\n## Why this is surprising", 1)
    return text.replace(
        "## Context receipts\n\n",
        "## Context receipts\n\n"
        "_Boundary evidence only; these receipts broaden source context but do "
        "not independently prove the lead claim._\n\n",
    )


def _submission_payload(verdict: Json, root: Path) -> Json:
    run_dir = _run_path(root, verdict.get("run_dir"))
    memo = ""
    with suppress(OSError):
        memo = (run_dir / "alpha_memo.md").read_text(encoding="utf-8")
    public_memo = _public_submission_markdown(memo)
    title = str(
        _memo_headline(memo)
        or verdict.get("headline")
        or verdict.get("topic")
        or "Alpha memo"
    )
    source_papers = _memo_source_papers(verdict, root)
    direct_source_papers = _memo_source_papers(verdict, root, ("Evidence",), {"A_core"})
    source_bundle = _source_bundle(source_papers)
    direct_source_count = len(direct_source_papers)
    receipt_count = len(_memo_receipt_ids(memo))
    return {
        "artifact_type": "alpha_memo",
        "article_type": "alpha_memo",
        "author_agent_id": "agent-v4-alpha-memo",
        "agent_id": "agent-v4-alpha-memo",
        "title": title,
        "topic": verdict.get("topic"),
        "markdown": public_memo,
        "citations": source_bundle,
        "source_bundle": source_bundle,
        "novelty_score": verdict.get("alpha_score"),
        "confidence_score": verdict.get("maturity_level"),
        "evidence_bundle": {
            "publish_verdict": verdict,
            "run_dir": verdict.get("run_dir"),
            "source_papers": source_papers,
            "direct_source_papers": direct_source_papers,
            "bound_receipt_count": receipt_count,
            "bound_source_count": len(source_bundle),
            "source_bundle_count": len(source_bundle),
            "direct_source_count": direct_source_count,
            "context_source_count": max(0, len(source_bundle) - direct_source_count),
            "context_sources_are_not_direct_support": "## Context receipts" in memo,
        },
        "content_hash": "sha256:" + hashlib.sha256(public_memo.encode("utf-8")).hexdigest(),
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
    refresh_top: int = _DEFAULT_REFRESH_TOP,
    max_refresh_batches: int = _DEFAULT_MAX_REFRESH_BATCHES,
    submit: bool = False,
    retraction_mode: str = "metadata",
    min_submit_sources: int = _DEFAULT_MIN_SUBMIT_SOURCES,
    min_direct_submit_sources: int = _DEFAULT_MIN_DIRECT_SUBMIT_SOURCES,
    submitter: Submitter | None = None,
    fetcher: Fetcher = _crossref_fetch,
    decision_fetcher: DecisionFetcher = _decision_fetch,
    page_fetcher: PageFetcher = _fetch_public_page,
    memo_refresher: MemoRefresher = _refresh_alpha_memo,
    queue_builder: QueueBuilder = _build_queue,
) -> Json:
    ledger_path = runs_root / "_daily_ledger" / f"{date}.json"
    submitted_path = runs_root / "_daily_ledger" / "_submitted_fingerprints.json"
    decision_sync = sync_submission_decisions(
        runs_root, fetcher=decision_fetcher, page_fetcher=page_fetcher,
    )
    ledger: Json = {
        "date": date,
        "dry_run": not submit,
        "decision_sync": decision_sync,
        "estimated_cost_usd": estimated_cost_usd,
        "max_cost_usd": max_cost_usd,
        "refresh_top": refresh_top,
        "max_refresh_batches": max_refresh_batches,
        "min_submit_sources": min_submit_sources,
        "min_direct_submit_sources": min_direct_submit_sources,
        "refresh_batches": [],
        "cycle_attempts": [],
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
    blocked_fingerprints: set[str] = set()
    blocked_topics: set[str] = set()
    accepted_shape_profiles = _accepted_shape_profiles(runs_root)
    all_considered: list[Json] = []
    batch_limit = max(1, max_refresh_batches if refresh_candidates else 1)
    if submit and submitter is None:
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
    for batch in range(1, batch_limit + 1):
        if refresh_candidates:
            refresh = _refresh_candidate_batch(refresh_top, blocked_topics)
            refresh["batch"] = batch
            ledger["refresh_batches"].append(refresh)
            ledger["refresh_candidates"] = refresh
            if not refresh["ok"]:
                ledger["considered"] = all_considered
                ledger.update({"status": "candidate_refresh_failed"})
                _write_json(ledger_path, ledger)
                return ledger
        current_queue = queue if queue is not None else queue_builder(runs_root, include_archive)
        current_queue = _with_repairable_candidates(current_queue, runs_root)
        ledger["queue_counts"] = _queue_counts(current_queue)
        candidate, considered = select_candidate(
            current_queue, runs_root=runs_root, submitted_path=submitted_path,
            allow_tier2=allow_tier2,
            min_source_count=min_submit_sources if submit else 0,
            min_direct_source_count=min_direct_submit_sources if submit else 0,
            memo_refresher=memo_refresher if submit else None,
            blocked_fingerprints=blocked_fingerprints,
            blocked_topics=blocked_topics,
            accepted_shape_profiles=accepted_shape_profiles,
        )
        for row in considered:
            if refresh_candidates:
                row["batch"] = batch
            if row.get("status") in _EXHAUSTED_STATUSES:
                fingerprint = str(row.get("fingerprint") or "")
                topic = str(row.get("topic") or "")
                if fingerprint:
                    blocked_fingerprints.add(fingerprint)
                if topic:
                    blocked_topics.add(topic)
        all_considered.extend(considered)
        ledger["considered"] = all_considered
        if candidate is None:
            continue
        check_mode = "crossref" if submit and retraction_mode == "metadata" else retraction_mode
        retraction = retraction_check(
            candidate, mode=check_mode, fetcher=fetcher, runs_root=runs_root,
        )
        attempt = {
            "batch": batch,
            "topic": candidate.get("topic"),
            "run_dir": candidate.get("run_dir"),
            "fingerprint": candidate.get("memo_fingerprint"),
            "retraction_check": retraction,
        }
        ledger["retraction_check"] = retraction
        ledger["candidate"] = {
            "topic": candidate.get("topic"),
            "run_dir": candidate.get("run_dir"),
            "fingerprint": candidate.get("memo_fingerprint"),
        }
        if retraction.get("status") != "clean":
            attempt["status"] = "held_retraction_check"
            for row in reversed(all_considered):
                if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                    row["pre_attempt_status"] = row.get("status")
                    row["status"] = "held_retraction_check"
                    break
            ledger["cycle_attempts"].append(attempt)
            blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
            _write_json(
                runs_root / "_retracted_holds" / f"{candidate.get('topic')}-{date}.json",
                ledger,
            )
            if not refresh_candidates or batch == batch_limit:
                ledger.update({
                    "status": "held_retraction_check",
                    "candidate": candidate.get("topic"),
                })
                _write_json(ledger_path, ledger)
                return ledger
            continue
        if not submit:
            ledger["cycle_attempts"].append(attempt | {"status": "dry_run_selected"})
            ledger.update({"status": "dry_run_selected"})
            _write_json(ledger_path, ledger)
            return ledger
        assert submitter is not None
        result = submit_with_backoff(_submission_payload(candidate, runs_root), submitter)
        attempt["submission"] = result
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
                "memo_sha256": _memo_sha256(candidate, runs_root),
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
            if submission_id:
                try:
                    decision = decision_fetcher(submission_id)
                except Exception as exc:  # pragma: no cover - network defensive path
                    ledger["decision_check_error"] = {
                        "error": type(exc).__name__,
                        "detail": str(exc)[:180],
                    }
                else:
                    final = _apply_submission_decision(
                        ledger,
                        submission_id=submission_id,
                        decision=decision,
                        page_fetcher=page_fetcher,
                    )
                    if final == "accepted":
                        attempt["public_page_check"] = ledger.get("public_page_check")
                        ledger["cycle_attempts"].append(attempt | {"status": "published"})
                        _write_json(ledger_path, ledger)
                        return ledger
                    if final in {"rejected", "revise"}:
                        attempt["status"] = (
                            str(ledger.get("publish_failure_reason") or "")
                            or ("reviewer_revise" if final == "revise" else "reviewer_rejected")
                        )
                        attempt["researka_decision"] = decision
                        attempt["public_page_check"] = ledger.get("public_page_check")
                        for row in reversed(all_considered):
                            if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                                row["pre_attempt_status"] = row.get("status")
                                row["status"] = "cycle_failed_submission"
                                row["submit_status"] = attempt["status"]
                                break
                        ledger["cycle_attempts"].append(attempt)
                        blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
                        topic = str(candidate.get("topic") or "")
                        if topic:
                            blocked_topics.add(topic)
                        if not refresh_candidates or batch == batch_limit:
                            ledger.update({"status": attempt["status"], "published": 0})
                            _write_json(ledger_path, ledger)
                            return ledger
                        continue
            ledger["cycle_attempts"].append(attempt | {"status": "submitted_to_researka"})
            _write_json(ledger_path, ledger)
            return ledger
        attempt["status"] = result["status"]
        for row in reversed(all_considered):
            if row.get("fingerprint") == candidate.get("memo_fingerprint"):
                row["pre_attempt_status"] = row.get("status")
                row["status"] = "cycle_failed_submission"
                row["submit_status"] = result["status"]
                break
        ledger["cycle_attempts"].append(attempt)
        blocked_fingerprints.add(str(candidate.get("memo_fingerprint") or ""))
        topic = str(candidate.get("topic") or "")
        if topic:
            blocked_topics.add(topic)
        if not refresh_candidates or batch == batch_limit:
            ledger.update({"status": result["status"], "published": 0})
            _write_json(ledger_path, ledger)
            return ledger
    if ledger["cycle_attempts"]:
        last_status = str(ledger["cycle_attempts"][-1].get("status") or "failed")
        ledger.update({
            "status": "submit_retry_exhausted",
            "reason": f"no candidate accepted after {batch_limit} batch(es)",
            "last_attempt_status": last_status,
            "published": 0,
        })
    else:
        ledger.update({
            "status": "no_publishable_candidate",
            "reason": "no eligible non-duplicate memo",
        })
    _write_json(ledger_path, ledger)
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=_ledger_stamp())
    parser.add_argument("--include-archive", action="store_true")
    parser.add_argument("--refresh-candidates", action="store_true")
    parser.add_argument("--allow-tier2", action="store_true")
    parser.add_argument("--estimated-cost-usd", type=float, default=0.0)
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--refresh-top", type=int, default=_DEFAULT_REFRESH_TOP)
    parser.add_argument("--max-refresh-batches", type=int, default=_DEFAULT_MAX_REFRESH_BATCHES)
    parser.add_argument("--min-submit-sources", type=int, default=_DEFAULT_MIN_SUBMIT_SOURCES)
    parser.add_argument("--min-direct-submit-sources", type=int, default=_DEFAULT_MIN_DIRECT_SUBMIT_SOURCES)
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
        refresh_top=args.refresh_top,
        max_refresh_batches=args.max_refresh_batches,
        min_submit_sources=args.min_submit_sources,
        min_direct_submit_sources=args.min_direct_submit_sources,
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
