"""Render operator-facing alpha memos from existing evidence-run receipts.

No new model call. The memo is a product layer over `signal_post.md`,
`frontier_review.json`, `opportunities_gate.json`, `fact_lanes.json`,
`top_5.md`, and `all_facts.json`.
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PUB_PATH = _ROOT / "topic_packs" / "publication.toml"
_BINDABLE = frozenset({"A_core", "B_context"})


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _publication_defaults() -> dict[str, str]:
    defaults = {
        "author": "",
        "orcid": "",
        "venue": "Evidence Index",
        "license": "CC BY-NC 4.0",
        "version": "1.0",
        "canonical_url_base": "",
    }
    try:
        data = tomllib.loads(_PUB_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return defaults
    pub = data.get("publication")
    if not isinstance(pub, dict):
        return defaults
    for key in defaults:
        value = pub.get(key)
        if isinstance(value, str):
            defaults[key] = value.strip()
    return defaults


def _section(md: str, heading: str) -> str:
    m = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        md,
        flags=re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def _headline(signal_md: str, topic: str) -> str:
    matches = re.findall(r"^## (?!Why |Evidence|Confidence|Adjacent|Next)(.+)$",
                         signal_md, flags=re.M)
    return matches[0].strip() if matches else f"Open signal — {topic}"


def _label(signal_md: str) -> str:
    m = re.search(r"^## Confidence — `([^`]+)`", signal_md, flags=re.M)
    if m:
        return m.group(1)
    return "no_signal" if signal_md.startswith("# No signal") else "unknown"


def _top_cards(top_md: str, limit: int = 5) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = []
    for block in re.split(r"\n## #\d+ ", top_md)[1:]:
        finding = re.search(r"\*\*Finding:\*\* (.+)", block)
        cues = re.search(r"- \*\*Alpha cues:\*\* (.+)", block)
        if finding:
            cards.append((
                finding.group(1).strip()[:220],
                (cues.group(1).strip() if cues else "baseline"),
            ))
        if len(cards) >= limit:
            break
    return cards


def _lane_map(run_dir: Path) -> dict[str, str]:
    data = _json(run_dir / "fact_lanes.json", {})
    out: dict[str, str] = {}
    for item in data.get("verdicts", []) if isinstance(data, dict) else []:
        if isinstance(item, dict):
            out[str(item.get("fact_id") or "")] = str(item.get("lane") or "")
    return out


def _facts_by_id(run_dir: Path) -> dict[str, dict[str, Any]]:
    data = _json(run_dir / "all_facts.json", [])
    return {
        str(f.get("fact_id") or ""): f
        for f in data
        if isinstance(f, dict)
    } if isinstance(data, list) else {}


def _lead_audit(run_dir: Path) -> dict[str, Any]:
    gate = _json(run_dir / "opportunities_gate.json", {})
    audits = gate.get("audits", []) if isinstance(gate, dict) else []
    rank = {"survives": 3, "needs_source_audit": 2, "rejected": 1}
    valid = [a for a in audits if isinstance(a, dict)]
    if not valid:
        return {}
    return max(
        valid,
        key=lambda a: (
            rank.get(str(a.get("status") or ""), 0),
            int(a.get("capped_opportunity") or 0),
        ),
    )


def _receipt_lines(
    audit: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
) -> list[str]:
    out: list[str] = []
    for fid in [str(x) for x in audit.get("cited_fact_ids", [])]:
        if lanes.get(fid) not in _BINDABLE:
            continue
        fact = facts.get(fid) or {}
        phrase = str(fact.get("canonical_phrase") or "").strip()
        paper = fact.get("source_paper") or {}
        doi = str(paper.get("doi") or "").strip()
        lane = lanes.get(fid, "?")
        if phrase:
            out.append(
                f"- `fact_id={fid}` (`{lane}`) — {phrase[:240]}"
                + (f" DOI `{doi}`" if doi else "")
            )
    return out or ["- _No A_core/B_context receipts bind to this memo._"]


def _alpha_score(audit: dict[str, Any], label: str) -> int:
    base = int(audit.get("capped_opportunity")
               or audit.get("opportunity_score") or 0)
    shift = {
        "evidence_backed_signal": 10,
        "frontier_hypothesis": 0,
        "speculative_alpha": -10,
        "curation_needed": -20,
        "evidence_binding_failed": -35,
        "discard": -80,
        "no_signal": -100,
    }.get(label, -20)
    return max(0, min(100, base + shift))


def _weakening_lines(review: dict[str, Any], label: str) -> list[str]:
    raw = review.get("reviewer_objections") if isinstance(review, dict) else []
    lines = [f"- {str(x)[:240]}" for x in raw[:3]] if isinstance(raw, list) else []
    if lines:
        return lines
    if label in {"evidence_binding_failed", "curation_needed", "no_signal"}:
        return [
            "- The thesis stays weak until the missing receipts bind to A_core/B_context facts.",
            "- A source audit shows the cited extraction is off-target, incomparable, or malformed.",
        ]
    return [
        "- Independent receipts fail to reproduce the claimed contrast.",
        "- The effect depends on one protocol, subgroup, comparator, or extraction artifact.",
    ]


def _provenance_block(
    run_dir: Path, topic: str, snapshot: str, headline: str, memo_body: str,
) -> list[str]:
    pub = _publication_defaults()
    bundle_bits = []
    for name in (
        "signal_post.md", "frontier_review.json", "opportunities_gate.json",
        "fact_lanes.json", "top_5.md",
    ):
        text = _read(run_dir / name)
        if text:
            bundle_bits.append(f"{name}:{_sha256(text)}")
    bundle_hash = _sha256("\n".join(bundle_bits))
    base = pub["canonical_url_base"].rstrip("/")
    canonical = f"{base}/{run_dir.name}/alpha_memo" if base else ""
    citation = (
        f"{pub['author']}. ({snapshot[:4] or 'n.d.'}). {headline}. "
        f"{pub['venue']}. Version {pub['version']}."
    ).strip()
    return [
        "## Provenance / priority",
        "",
        f"- **Topic:** `{topic}`",
        f"- **Author:** {pub['author'] or '_not configured_'}",
        f"- **ORCID:** {pub['orcid'] or '_not configured_'}",
        f"- **Version:** {pub['version']}",
        f"- **License:** {pub['license']}",
        f"- **Canonical URL:** {canonical or '_not assigned_'}",
        f"- **Suggested citation:** {citation}",
        f"- **Run bundle SHA-256:** `{bundle_hash}`",
        f"- **Memo SHA-256:** `{_sha256(memo_body)}`",
        "- **Priority note:** This memo records the first published "
        "framing, source bundle, and evidence receipts for this run. "
        "Reuse should cite the canonical version.",
    ]


def render_signal_memo(run_dir: Path, signal_text: str | None = None) -> str:
    signal_md = signal_text if signal_text is not None else _read(
        run_dir / "signal_post.md")
    review = _json(run_dir / "frontier_review.json", {})
    top_md = _read(run_dir / "top_5.md")
    topic = str(review.get("topic") or run_dir.name.split("-evidence-")[0])
    snapshot = str(review.get("snapshot_utc") or run_dir.name)
    headline = _headline(signal_md, topic)
    label = _label(signal_md)
    audit = _lead_audit(run_dir)
    facts = _facts_by_id(run_dir)
    lanes = _lane_map(run_dir)
    thesis = str(audit.get("rationale") or _section(
        signal_md, "Why this is surprising") or headline).strip()
    next_extractions = review.get("next_extractions") if isinstance(review, dict) else []
    top_cards = _top_cards(top_md)

    lines = [
        f"# Alpha memo — {topic}",
        "",
        f"**Headline:** {headline}",
        f"**Alpha score:** {_alpha_score(audit, label)}/100",
        f"**Confidence:** `{label}`",
        f"**Snapshot:** `{snapshot}`",
        f"**Run:** `{run_dir.name}`",
        "",
        "## One-sentence thesis",
        "",
        thesis[:500],
        "",
        "## Why this is surprising",
        "",
        _section(signal_md, "Why this is surprising") or "_No frontier lens produced._",
        "",
        "## Evidence receipts",
        "",
        *_receipt_lines(audit, facts, lanes),
        "",
        "## What this changes",
        "",
        "Treat this as a focused working signal, not a broad topic claim. "
        "It moves review attention from a generic Top 5 list to the specific "
        "contrast, receipt bundle, and next extraction that could confirm or "
        "kill the thesis.",
        "",
        "## What would weaken this",
        "",
        *_weakening_lines(review if isinstance(review, dict) else {}, label),
        "",
        "## Next extraction",
        "",
    ]
    if isinstance(next_extractions, list) and next_extractions:
        lines.extend(f"- {str(x)[:240]}" for x in next_extractions[:5])
    else:
        lines.append("- Add independent A_core/B_context receipts that test the thesis directly.")
    if top_cards:
        lines.extend(["", "## Supporting Top cards", ""])
        lines.extend(f"- {finding} _(alpha cues: {cues})_"
                     for finding, cues in top_cards)
    body = "\n".join(lines) + "\n"
    lines.extend(["", *_provenance_block(run_dir, topic, snapshot, headline, body)])
    return "\n".join(lines) + "\n"


def write_signal_memo(run_dir: Path, signal_text: str | None = None) -> tuple[Path, str]:
    text = render_signal_memo(run_dir, signal_text)
    out = run_dir / "alpha_memo.md"
    out.write_text(text, encoding="utf-8")
    return out, text
