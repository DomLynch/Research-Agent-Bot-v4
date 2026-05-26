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


def _memo_min_source_papers() -> int:
    try:
        data = tomllib.loads(_PUB_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return 5
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    try:
        return int((alpha or {}).get("min_source_papers", 5))
    except (TypeError, ValueError):
        return 5


def _section(md: str, heading: str) -> str:
    m = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        md,
        flags=re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def _headline(signal_md: str, topic: str) -> str:
    if signal_md.startswith("# No signal"):
        first = signal_md.splitlines()[0].lstrip("# ").strip()
        return first or f"No publishable signal — {topic}"
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


def _first_sentence(text: str, fallback: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return fallback
    m = re.search(r"(.+?[.!?])(?:\s|$)", cleaned)
    return (m.group(1) if m else cleaned).strip()[:360]


def _clip(text: Any, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


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


def _source_key(fact: dict[str, Any]) -> str:
    paper = fact.get("source_paper") or {}
    if not isinstance(paper, dict):
        return ""
    return str(paper.get("doi") or paper.get("pmid") or paper.get("title") or "").strip()


def _expanded_receipt_ids(
    audit: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    *,
    min_sources: int,
) -> list[str]:
    selected: list[str] = []
    seen_ids: set[str] = set()
    sources: set[str] = set()

    def add(fid: str) -> None:
        if fid in seen_ids or lanes.get(fid) not in _BINDABLE or fid not in facts:
            return
        selected.append(fid)
        seen_ids.add(fid)
        key = _source_key(facts[fid])
        if key:
            sources.add(key)

    for fid in [str(x) for x in audit.get("cited_fact_ids", [])]:
        add(fid)
    for fid, fact in facts.items():
        if len(sources) >= min_sources:
            break
        key = _source_key(fact)
        if key and key not in sources:
            add(fid)
    for fid in facts:
        if len(sources) >= min_sources:
            break
        add(fid)
    return selected


def _source_count_for_ids(ids: list[str], facts: dict[str, dict[str, Any]]) -> int:
    return len({
        _source_key(facts[fid])
        for fid in ids if fid in facts and _source_key(facts[fid])
    })


def _receipt_lines(
    audit: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    receipt_ids: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    ids = receipt_ids if receipt_ids is not None else [
        str(x) for x in audit.get("cited_fact_ids", [])
    ]
    for fid in ids:
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


def _score_band(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _weakening_lines(review: dict[str, Any], label: str) -> list[str]:
    if label in {"evidence_binding_failed", "curation_needed", "no_signal"}:
        return [
            "- The thesis stays weak until the missing receipts bind to A_core/B_context facts.",
            "- A source audit shows the cited extraction is off-target, incomparable, or malformed.",
        ]
    return [
        "- Independent receipts fail to reproduce the claimed contrast.",
        "- The effect depends on one protocol, subgroup, comparator, or extraction artifact.",
    ]


def _surface_line(verdict: dict[str, Any] | None) -> str:
    if not verdict:
        return "unclassified"
    surface = str(verdict.get("surface_type") or "unclassified")
    if surface == "publish_alpha_memo":
        return "alpha memo"
    return surface.replace("_", " ")


def _topic_title(topic: str) -> str:
    label = " ".join(part for part in topic.replace("-", "_").split("_") if part)
    return label[:1].upper() + label[1:]


def _public_headline(topic: str, headline: str, verdict: dict[str, Any] | None) -> str:
    if verdict and verdict.get("surface_type") == "context_dependence_memo":
        return f"{_topic_title(topic)} may be context-specific, not broadly generalizable"
    return headline


def _context_subline(verdict: dict[str, Any] | None, fallback: str) -> str:
    if not verdict or verdict.get("surface_type") != "context_dependence_memo":
        return fallback
    expansion = verdict.get("receipt_expansion")
    candidates = expansion.get("candidate_receipts", []) if isinstance(expansion, dict) else []
    contexts: list[str] = []
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            context = str(item.get("population") or item.get("sub_topic") or "").strip()
            if context and context not in contexts:
                contexts.append(context)
            if len(contexts) >= 3:
                break
    if contexts:
        joined = (
            contexts[0] if len(contexts) == 1 else
            ", ".join(contexts[:-1]) + f", and {contexts[-1]}"
        )
        return (
            "The lead signal sits beside A/B receipts across "
            + joined
            + "; publish it as a context-dependence signal rather than a broad claim."
        )
    return (
        "The lead signal cites fewer receipts than the run contains, so publish it "
        "as a context-dependence signal rather than a broad claim."
    )


def _same_phrase(left: str, right: str) -> bool:
    norm = r"[^a-z0-9]+"
    return re.sub(norm, " ", left.lower()).strip() == re.sub(
        norm, " ", right.lower(),
    ).strip()


def _fact_phrase(fact: dict[str, Any]) -> str:
    return str(fact.get("canonical_phrase") or "").strip().rstrip(".")


def _receipt_thesis(
    headline: str,
    audit: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    receipt_ids: list[str],
    verdict: dict[str, Any] | None,
) -> str:
    fallback = _first_sentence(str(audit.get("rationale") or ""), "")
    if verdict and verdict.get("surface_type") == "context_dependence_memo":
        return _context_subline(verdict, fallback or headline)
    if fallback and not _same_phrase(fallback, headline):
        return fallback
    phrases = [_fact_phrase(facts.get(fid) or {}) for fid in receipt_ids[:2]]
    joined = "; ".join(p for p in phrases if p)
    if joined:
        return f"The cited A/B receipts support a specific working claim: {joined}."
    return f"The memo advances a bounded evidence signal under this headline: {headline}."


def _counter_lines(verdict: dict[str, Any] | None) -> list[str]:
    if not verdict:
        return ["- _Counter-evidence not classified yet._"]
    counter = verdict.get("counter_evidence")
    items = counter.get("items", []) if isinstance(counter, dict) else []
    if not isinstance(items, list) or not items:
        return [
            "- _No A_core/B_context counter-evidence found in this run; "
            "treat this as a single-direction signal until a broader receipt "
            "expansion finds a real opposing fact._",
        ]
    out = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        raw_paper = item.get("source_paper")
        paper = raw_paper if isinstance(raw_paper, dict) else {}
        source = str(paper.get("title") or paper.get("doi") or "").strip()
        phrase = str(item.get("phrase") or "").strip()
        out.append(
            f"- `fact_id={item.get('fact_id')}` (`{item.get('lane')}`) — "
            f"{phrase[:240].rstrip()}"
            + (f" Source: {source[:140].rstrip()}" if source else "")
        )
    return out or ["- _No A_core/B_context counter-evidence found in this run._"]


def _receipt_expansion_lines(verdict: dict[str, Any] | None) -> list[str]:
    if not verdict:
        return []
    expansion = verdict.get("receipt_expansion")
    if not isinstance(expansion, dict) or not expansion.get("needed"):
        return []
    items = expansion.get("candidate_receipts", [])
    if not isinstance(items, list) or not items:
        return ["- More receipts are needed, but no unused A/B candidates were found in this run."]
    lines = [
        "- The lead thesis is thinner than the available corpus: it cites "
        f"{len(expansion.get('cited_bound_fact_ids') or [])} bound receipt(s) "
        f"while {len(expansion.get('available_bound_fact_ids') or [])} A/B "
        "receipt(s) exist in this run.",
    ]
    for item in items[:5]:
        if isinstance(item, dict):
            phrase = str(item.get("phrase") or "").strip()
            lines.append(
                f"- Candidate `fact_id={item.get('fact_id')}` "
                f"(`{item.get('lane')}`) — {phrase[:220].rstrip()}"
            )
    return lines


def _subtopic_lines(verdict: dict[str, Any] | None) -> list[str]:
    if not verdict:
        return []
    rec = verdict.get("subtopic_recommendations")
    if not isinstance(rec, dict) or not rec.get("recommended"):
        return []
    clusters = rec.get("clusters", [])
    lines = [
        "- This topic looks broad/noisy enough that the next run should split it "
        "before trying to force one public thesis.",
    ]
    if isinstance(clusters, list):
        for cluster in clusters[:5]:
            if not isinstance(cluster, dict):
                continue
            raw_paper = cluster.get("source_paper")
            paper = raw_paper if isinstance(raw_paper, dict) else {}
            label_text = str(
                paper.get("title") or cluster.get("example_phrase") or ""
            ).strip()
            lines.append(
                f"- `{cluster.get('label')}` — "
                f"{label_text[:180].rstrip()}"
            )
    return lines


def _limitations_lines(weakening: list[str]) -> list[str]:
    return [
        "- This is an alpha memo, not a settled review, guideline, or broad "
        "consensus claim.",
        "- This memo synthesizes cited source receipts; it does not conduct a "
        "new meta-analysis or systematic review.",
        "- Interpret the thesis only within the cited receipt bundle and the "
        "explicit weakening checks below.",
        *weakening[:3],
    ]


def _why_surprising(
    fallback: str,
    context_ids: list[str],
) -> str:
    if context_ids:
        return (
            "The useful signal is narrower than the topic label: the lead receipts "
            "support the core claim, while the added A/B context receipts define "
            "where that claim may generalize, fail, or need a separate extraction."
        )
    return fallback or "_No frontier lens produced._"


def _next_extraction_lines(context_ids: list[str]) -> list[str]:
    lines = [
        "- Extract independent A_core/B_context receipts that test the lead contrast directly.",
        "- Audit whether each direct receipt remains comparable on population, endpoint, comparator, and measurement method.",
    ]
    if context_ids:
        lines.append(
            "- Run a follow-up pass that either connects each context receipt to the lead claim or splits it into a separate memo.",
        )
    return lines


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


def render_signal_memo(
    run_dir: Path,
    signal_text: str | None = None,
    publish_verdict: dict[str, Any] | None = None,
) -> str:
    signal_md = signal_text if signal_text is not None else _read(
        run_dir / "signal_post.md")
    review = _json(run_dir / "frontier_review.json", {})
    topic = str(review.get("topic") or run_dir.name.split("-evidence-")[0])
    snapshot = str(review.get("snapshot_utc") or run_dir.name)
    raw_headline = _headline(signal_md, topic)
    headline = _public_headline(topic, raw_headline, publish_verdict)
    label = _label(signal_md)
    audit = _lead_audit(run_dir)
    facts = _facts_by_id(run_dir)
    lanes = _lane_map(run_dir)
    min_sources = _memo_min_source_papers()
    receipt_ids = _expanded_receipt_ids(
        audit, facts, lanes, min_sources=min_sources,
    )
    lead_ids = [
        str(x) for x in audit.get("cited_fact_ids", [])
        if lanes.get(str(x)) in _BINDABLE and str(x) in facts
    ]
    if not lead_ids:
        lead_ids = receipt_ids[:1]
    context_ids = [fid for fid in receipt_ids if fid not in set(lead_ids)]
    source_count = _source_count_for_ids(receipt_ids, facts)
    thesis = _receipt_thesis(headline, audit, facts, receipt_ids, publish_verdict)
    weakening = _weakening_lines(review if isinstance(review, dict) else {}, label)
    why_surprising = _why_surprising(
        _section(signal_md, "Why this is surprising"),
        context_ids,
    )

    lines = [
        f"# Alpha memo — {topic}",
        "",
        f"**Headline:** {headline}",
        f"**Alpha triage:** `{_score_band(_alpha_score(audit, label))}` (internal ranking; not a certainty claim)",
        f"**Confidence:** `{label}`",
        f"**Memo surface:** `{_surface_line(publish_verdict)}`",
        f"**Snapshot:** `{snapshot}`",
        f"**Run:** `{run_dir.name}`",
        *([f"**Source thesis:** {raw_headline}"]
          if raw_headline != headline else []),
        f"**Source breadth:** `{source_count}/{min_sources}` unique cited source(s)",
        "",
        "## One-sentence thesis",
        "",
        thesis[:500],
        "",
        "## Why this is surprising",
        "",
        why_surprising,
        "",
        "## Evidence receipts",
        "",
        *_receipt_lines(audit, facts, lanes, lead_ids),
    ]
    if context_ids:
        lines.extend([
            "",
            "## Context receipts",
            "",
            *_receipt_lines(audit, facts, lanes, context_ids),
        ])
    lines.extend([
        "",
        "## What this changes",
        "",
        (
            "Treat this as a focused working signal, not a broad topic claim. "
            "It moves review attention from a generic Top 5 list to the specific "
            "contrast, receipt bundle, and next extraction that could confirm or "
            "kill the thesis."
        ),
        "",
        "## Limitations",
        "",
        *_limitations_lines(weakening),
        "",
        "## What would weaken this",
        "",
        *weakening,
        "",
        "## Strongest counter-evidence",
        "",
        *_counter_lines(publish_verdict),
        "",
        "## Next extraction",
        "",
    ])
    lines.extend(_next_extraction_lines(context_ids))
    expansion_lines = _receipt_expansion_lines(publish_verdict)
    if expansion_lines:
        lines.extend(["", "## Receipt expansion candidates", "", *expansion_lines])
    subtopic_lines = _subtopic_lines(publish_verdict)
    if subtopic_lines:
        lines.extend(["", "## Subtopic recommendations", "", *subtopic_lines])
    body = "\n".join(lines) + "\n"
    lines.extend(["", *_provenance_block(run_dir, topic, snapshot, headline, body)])
    return "\n".join(lines) + "\n"


def write_signal_memo(
    run_dir: Path,
    signal_text: str | None = None,
    publish_verdict: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    text = render_signal_memo(run_dir, signal_text, publish_verdict)
    out = run_dir / "alpha_memo.md"
    out.write_text(text, encoding="utf-8")
    return out, text
