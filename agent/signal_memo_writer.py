from __future__ import annotations

import hashlib
import json
import re
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PUB_PATH = _ROOT / "topic_packs" / "publication.toml"
_DIRECT = frozenset({"A_core"})
_BINDABLE = frozenset({"A_core", "B_context"})

_CLAIM_FIELDS = ("canonical_phrase",)
_CLAIM_MIN_OVERLAP = 1
_WORD = re.compile(r"[a-z][a-z0-9]*")  # alpha-led: pure numbers aren't claim signal
_GENERIC_TOKENS = frozenset({
    "the", "of", "to", "in", "and", "or", "for", "with", "from", "by", "on", "at", "an",
    "as", "is", "are", "was", "were", "be", "not", "than", "that", "this", "study", "trial",
    "group", "groups", "patients", "subjects", "adults", "participants", "risk", "effect",
    "effects", "increased", "decreased", "reduced", "change", "results", "significant",
    "versus", "compared", "control", "treated", "ci", "rr", "hr", "nnt", "rct", "rcts",
})
_NULL_MARKERS = ("no effect", "null", "unchanged", "failed", "did not", "without")
_ADVERSE_MARKERS = ("mortality", "adverse", "toxicity", "harm", "worsen", "risk")
_DOSE_MARKERS = ("dose", "low-dose", "high-dose", "threshold")
_SUBGROUP_MARKERS = ("subgroup", "strata", "sex", "male", "female", "baseline")
_MODEL_MARKERS = ("mouse", "mice", "rat", "animal", "cell", "in vitro", "human")
_ENDPOINT_MARKERS = ("biomarker", "surrogate", "mortality", "survival", "endpoint")

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


def _memo_alpha_int(name: str, default: int) -> int:
    try:
        data = tomllib.loads(_PUB_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return default
    alpha = data.get("alpha_memo") if isinstance(data, dict) else {}
    try:
        return int((alpha or {}).get(name, default))
    except (TypeError, ValueError):
        return default


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
    return str(paper.get("doi") or paper.get("pmid") or paper.get("pmcid")
               or paper.get("paper_id") or paper.get("id")
               or paper.get("title") or "").strip()


def _claim_token_set(*values: Any) -> set[str]:
    return {t for value in values for t in _WORD.findall(str(value or "").lower()) if len(t) >= 2}


def _claim_fit_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    left_roots = {t[:6] for t in left if len(t) >= 6}
    right_roots = {t[:6] for t in right if len(t) >= 6}
    exact = len(left & right) * 2
    rooted = len(left_roots & right_roots)
    return (exact + rooted) / max(1, len(left) + len(right))


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        if value:
            out[value] = out.get(value, 0) + 1
    return out


def _claim_signal(
    seed_ids: list[str], facts: dict[str, dict[str, Any]], topic: str,
) -> set[str]:
    sig: set[str] = set()
    for fid in seed_ids:
        fact = facts.get(fid) or {}
        sig |= _claim_token_set(*(fact.get(k) for k in _CLAIM_FIELDS))
    return sig - _claim_token_set(topic) - _GENERIC_TOKENS


def _fact_coheres(fact: dict[str, Any], claim: set[str], topic: str) -> bool:
    if not claim:
        return True
    cand = _claim_token_set(*(fact.get(k) for k in _CLAIM_FIELDS))
    cand -= _claim_token_set(topic) | _GENERIC_TOKENS
    return (
        len(cand & claim) >= _CLAIM_MIN_OVERLAP
        or _claim_fit_score(cand, claim) >= 0.2
    )


def _expanded_receipt_ids(
    audit: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    lanes: dict[str, str],
    *,
    min_sources: int,
    allowed_lanes: frozenset[str] = _BINDABLE,
    claim: set[str] | None = None,
    topic: str = "",
    preferred_ids: list[str] | None = None,
) -> list[str]:
    selected: list[str] = []
    seen_ids: set[str] = set()
    sources: set[str] = set()

    def add(fid: str) -> None:
        if fid in seen_ids or lanes.get(fid) not in allowed_lanes or fid not in facts:
            return
        selected.append(fid)
        seen_ids.add(fid)
        key = _source_key(facts[fid])
        if key:
            sources.add(key)

    for fid in [str(x) for x in audit.get("cited_fact_ids", [])]:
        add(fid)
    for fid in preferred_ids or []:
        if len(sources) >= min_sources:
            break
        add(str(fid))
    ranked_facts = sorted(
        facts.items(),
        key=lambda item: (
            -_claim_fit_score(
                _claim_token_set(*(item[1].get(k) for k in _CLAIM_FIELDS))
                - _claim_token_set(topic) - _GENERIC_TOKENS,
                claim or set(),
            ),
            item[0],
        ),
    )
    for fid, fact in ranked_facts:
        if len(sources) >= min_sources:
            break
        if claim is not None and not _fact_coheres(fact, claim, topic):
            continue
        key = _source_key(fact)
        if key and key not in sources:
            add(fid)
    for fid in facts:
        if len(sources) >= min_sources:
            break
        if claim is not None and not _fact_coheres(facts[fid], claim, topic):
            continue
        add(fid)
    return selected


def _preferred_receipt_ids(
    verdict: dict[str, Any] | None,
    lanes: dict[str, str],
    allowed_lanes: frozenset[str],
) -> list[str]:
    expansion = (verdict or {}).get("receipt_expansion")
    if not isinstance(expansion, dict) or not expansion.get("needed"):
        return []
    ids: list[str] = []

    def add(value: Any) -> None:
        fid = str(value or "").strip()
        if fid and fid not in ids and lanes.get(fid) in allowed_lanes:
            ids.append(fid)

    for key in ("available_bound_fact_ids", "cited_bound_fact_ids"):
        values = expansion.get(key)
        if isinstance(values, list):
            for fid in values:
                add(fid)
    candidates = expansion.get("candidate_receipts")
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                add(item.get("fact_id"))
    return ids


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
        source = str(doi or paper.get("pmid") or paper.get("title") or "").strip()
        lane = lanes.get(fid, "?")
        if phrase:
            out.append(
                f"- `fact_id={fid}` (`{lane}`) — {phrase[:240]}"
                + (f" doi={doi}" if doi else "")
                + (f" source={source[:120]}" if source and not doi else "")
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


def _recent_angle_kinds(run_dir: Path, *, limit: int = 8) -> dict[str, int]:
    """Novelty archive: count angle kinds used by recent sibling memos so a
    repeated angle flavor is penalized in _select_angle and runs stay varied."""
    counts: dict[str, int] = {}
    try:
        sibs = sorted(
            (p for p in run_dir.parent.glob("*/alpha_memo.md") if p.parent != run_dir),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
    except OSError:
        return counts
    for path in sibs[:limit]:
        m = re.search(r"\*\*Selected angle:\*\*\s*`([a-z_]+)`", _read(path))
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def journal_quality(facts: dict[str, dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    """paper-qa-style source-quality signal over cited papers: how many name a
    journal and the mean curated quality_score (0..100). A signal for review,
    not a hard gate — venue metadata is sparse in the corpus."""
    seen: dict[str, dict[str, Any]] = {}
    for fid in ids:
        paper = facts.get(fid, {}).get("source_paper")
        key = _source_key(facts.get(fid, {}))
        if isinstance(paper, dict) and key and key not in seen:
            seen[key] = paper
    papers = list(seen.values())
    named = [p for p in papers if str(p.get("journal_name") or p.get("journal") or "").strip()]
    scores: list[float] = []
    for p in papers:
        with suppress(TypeError, ValueError):
            raw = p.get("quality_score")
            if raw is not None and not isinstance(raw, bool):
                scores.append(float(raw))
    profiles = [_source_profile(p, facts.get(fid, {})) for fid in ids
                for p in [facts.get(fid, {}).get("source_paper")]
                if isinstance(p, dict)]
    source_types = _counts([p["source_type"] for p in profiles])
    study_designs = _counts([p["study_design"] for p in profiles])
    return {
        "sources": len(papers),
        "with_journal": len(named),
        "journal_named_ratio": round(len(named) / len(papers), 2) if papers else 0.0,
        "mean_quality_score": round(sum(scores) / len(scores), 1) if scores else None,
        "source_types": source_types,
        "study_designs": study_designs,
        "source_profiles": profiles[:5],
    }


def _source_profile(paper: dict[str, Any], fact: dict[str, Any]) -> dict[str, str]:
    text = " ".join(str(paper.get(k) or "") for k in ("title", "journal", "journal_name"))
    text += " " + _fact_phrase(fact)
    lower = text.lower()
    if "meta-analysis" in lower or "systematic review" in lower:
        design = "meta_analysis"
    elif any(w in lower for w in ("randomized", "trial", "rct")):
        design = "clinical_trial"
    elif any(w in lower for w in ("cohort", "observational", "participants", "patients")):
        design = "observational"
    elif any(w in lower for w in ("mouse", "mice", "rat", "animal")):
        design = "preclinical"
    elif any(w in lower for w in ("cell", "in vitro", "assay")):
        design = "mechanistic"
    else:
        design = "unknown"
    if design in {"clinical_trial", "observational"}:
        source_type = "human"
    elif design == "preclinical":
        source_type = "preclinical"
    elif design == "mechanistic":
        source_type = "mechanistic"
    elif design == "meta_analysis":
        source_type = "review"
    else:
        source_type = "unknown"
    return {
        "source": str(paper.get("title") or paper.get("doi") or "")[:140],
        "source_type": source_type,
        "study_design": design,
    }


def build_claim_receipt_matrix(
    claim: set[str], lead_ids: list[str],
    receipt_ids: list[str], facts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Claim -> receipts -> support level, as an auditable structure. Surfaces
    what the coherence filter + direct-source floor already enforce at submit
    time: direct>=5 strong, >=2 moderate, else weak (pure; no side effects).
    Carries a paper-qa-style journal_quality signal over the cited sources."""
    direct = _source_count_for_ids(lead_ids, facts)
    return {
        "claim_tokens": sorted(claim),
        "lead_fact_ids": lead_ids,
        "coherent_receipt_ids": [
            fid for fid in receipt_ids if _fact_coheres(facts.get(fid, {}), claim, "")
        ],
        "direct_sources": direct,
        "total_sources": _source_count_for_ids(receipt_ids, facts),
        "support_level": "strong" if direct >= 5 else "moderate" if direct >= 2 else "weak",
        "journal_quality": journal_quality(facts, receipt_ids),
    }


def _counter_items(verdict: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Structured contradiction receipts (fact_id + snippet + source) — the data
    behind the rendered 'Strongest counter-evidence' lines."""
    counter = (verdict or {}).get("counter_evidence")
    raw = counter.get("items", []) if isinstance(counter, dict) else []
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        paper = item.get("source_paper")
        paper = paper if isinstance(paper, dict) else {}
        ctype, strength = _counter_type(str(item.get("phrase") or ""), paper)
        out.append({
            "fact_id": str(item.get("fact_id") or ""),
            "lane": str(item.get("lane") or ""),
            "type": ctype,
            "opposition_strength": strength,
            "snippet": _clip(item.get("phrase"), 240),
            "source": str(paper.get("title") or paper.get("doi") or "").strip()[:140],
        })
    return out


def _counter_type(phrase: str, paper: dict[str, Any]) -> tuple[str, int]:
    text = f"{phrase} {paper.get('title') or ''}".lower()
    if any(m in text for m in _ADVERSE_MARKERS):
        return "adverse_signal", 85
    if any(m in text for m in _NULL_MARKERS):
        return "null_result", 80
    if any(m in text for m in _DOSE_MARKERS):
        return "dose_response_inversion", 70
    if any(m in text for m in _SUBGROUP_MARKERS):
        return "subgroup_reversal", 65
    if any(m in text for m in _MODEL_MARKERS):
        return "model_translation_gap", 60
    if any(m in text for m in _ENDPOINT_MARKERS):
        return "endpoint_mismatch", 55
    return "direction_reversal", 50


def _nearest_known_claims(
    claim: set[str],
    facts: dict[str, dict[str, Any]],
    receipt_ids: list[str],
    run_dir: Path | None,
) -> list[dict[str, Any]]:
    current = set(receipt_ids)
    rows: list[dict[str, Any]] = []

    def add(source: str, text: str, ref: str) -> None:
        tokens = _claim_token_set(text) - _GENERIC_TOKENS
        score = round(_claim_fit_score(tokens, claim), 3)
        if score >= 0.08:
            rows.append({"source": source, "score": score, "reference": ref, "claim": _clip(text, 240)})

    for fid, fact in facts.items():
        if fid not in current:
            add("all_facts", _fact_phrase(fact), fid)
        paper = fact.get("source_paper")
        if isinstance(paper, dict):
            title = str(paper.get("title") or "")
            if title:
                add("source_title", title, _source_key(fact))
    if run_dir:
        siblings = sorted(
            (p for p in run_dir.parent.glob("*-evidence-*/alpha_memo.md")
             if p.parent != run_dir),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:50]
        for path in siblings:
            add("prior_alpha_memo", _read(path)[:900], path.parent.name)
    rows.sort(key=lambda r: (-float(r["score"]), str(r["reference"])))
    return rows[:5]


def _novelty_delta(
    nearest: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    novelty: dict[str, Any],
    direct_sources: int,
) -> dict[str, Any]:
    top = float(nearest[0]["score"]) if nearest else 0.0
    repeats = int(novelty.get("repeats", 0))
    prior_repeat = any(
        row.get("source") == "prior_alpha_memo" and float(row.get("score") or 0) >= 0.55
        for row in nearest
    )
    if repeats or prior_repeat:
        label = "repeated"
    elif contradictions:
        label = "contradictory"
    elif top >= 0.28:
        label = "incremental"
    elif direct_sources >= 5:
        label = "high-novelty"
    else:
        label = "under-discussed"
    return {
        "label": label,
        "nearest_score": round(top, 3),
        "counter_evidence_types": sorted({str(c.get("type")) for c in contradictions}),
        "rationale": (
            "Prior/current claims are close." if label == "repeated"
            else "Claim is defined by an opposing receipt." if label == "contradictory"
            else "Nearby literature exists but does not fully cover the claim." if label == "incremental"
            else "Direct support exists with low nearest-claim overlap." if label == "high-novelty"
            else "Weak direct support; treat as curation until better receipts arrive."
        ),
    }


def _risk_of_bias_signal(source_hygiene: dict[str, Any]) -> str:
    types = source_hygiene.get("source_types")
    humanish = isinstance(types, dict) and any(types.get(k, 0) for k in ("human", "review"))
    return "missing_for_human_claim" if humanish else "not_required"


def _memo_verdict(direct_sources: int, conflicts: int, min_direct: int) -> str:
    """FactReview-style verdict from signals v4 already computes: a live
    contradiction -> in_conflict; >=floor direct sources -> supported; >=2 ->
    partially_supported; else inconclusive."""
    if conflicts:
        return "in_conflict"
    if direct_sources >= min_direct:
        return "supported"
    if direct_sources >= 2:
        return "partially_supported"
    return "inconclusive"


def build_memo_audit(
    claim: set[str], lead_ids: list[str], receipt_ids: list[str],
    facts: dict[str, dict[str, Any]], verdict: dict[str, Any] | None,
    *, falsifier: bool, novelty: dict[str, Any], min_direct: int = 5,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """FactReview-style audit pack: claim units + evidence + contradictions +
    novelty + source hygiene + a derived verdict. Aggregates signals v4 already
    computes; pure, no LLM/network."""
    matrix = build_claim_receipt_matrix(claim, lead_ids, receipt_ids, facts)
    contradictions = _counter_items(verdict)
    nearest = _nearest_known_claims(claim, facts, receipt_ids, run_dir)
    delta = _novelty_delta(nearest, contradictions, novelty, matrix["direct_sources"])
    risk = _risk_of_bias_signal(matrix["journal_quality"])
    lead = set(lead_ids)
    units = [
        {
            "fact_id": fid,
            "snippet": _fact_phrase(facts.get(fid, {}))[:240],
            "source": _source_key(facts.get(fid, {})),
            "source_span": _source_profile(
                facts.get(fid, {}).get("source_paper", {})
                if isinstance(facts.get(fid, {}).get("source_paper"), dict) else {},
                facts.get(fid, {}),
            ),
            "support": "direct" if fid in lead else "context",
        }
        for fid in receipt_ids if _fact_coheres(facts.get(fid, {}), claim, "")
    ]
    repeats = int(novelty.get("repeats", 0))
    gate_failures = [
        *([] if delta["label"] != "repeated" else ["novelty_delta_repeated"]),
        *([] if falsifier else ["memo_missing_falsifier"]),
        *([] if matrix["direct_sources"] else ["no_direct_source"]),
        *([] if risk != "missing_for_human_claim" else ["risk_of_bias_missing_for_human_claim"]),
    ]
    return {
        "schema_version": 1,
        "claim_tokens": sorted(claim),
        "verdict": (
            "inconclusive" if gate_failures
            else _memo_verdict(matrix["direct_sources"], len(contradictions), min_direct)
        ),
        "support_level": matrix["support_level"],
        "claim_units": units,
        "contradiction_receipts": contradictions,
        "novelty": {
            "selected_angle": str(novelty.get("selected") or ""),
            "recent_repeats": repeats,
            "signal": "repeated" if repeats else "fresh",
        },
        "nearest_literature": nearest,
        "novelty_delta": delta,
        "source_hygiene": matrix["journal_quality"],
        "falsifier_present": falsifier,
        "risk_of_bias": risk,
        "audit_gate": {"passed": not gate_failures, "failures": gate_failures},
    }


def validate_memo_audit_schema(audit: dict[str, Any]) -> list[str]:
    expected = {
        "schema_version": int,
        "claim_tokens": list,
        "verdict": str,
        "support_level": str,
        "claim_units": list,
        "contradiction_receipts": list,
        "novelty": dict,
        "source_hygiene": dict,
        "falsifier_present": bool,
        "risk_of_bias": str,
        "nearest_literature": list,
        "novelty_delta": dict,
        "audit_gate": dict,
    }
    errors: list[str] = []
    for key, typ in expected.items():
        if not isinstance(audit.get(key), typ):
            errors.append(key)
    return errors


def falsifier_present(memo_text: str) -> bool:
    """A memo must say what would disprove it: True iff 'What would weaken this'
    has at least one concrete (non-placeholder) bullet."""
    section = _section(memo_text, "What would weaken this")
    return any(
        ln.strip().startswith("-") and not ln.strip().lstrip("- ").startswith("_")
        for ln in section.splitlines()
    )


def _select_angle(
    topic: str,
    headline: str,
    thesis: str,
    why: str,
    facts: dict[str, dict[str, Any]],
    lead_ids: list[str],
    context_ids: list[str],
    verdict: dict[str, Any] | None,
    source_count: int,
    recent_kinds: dict[str, int] | None = None,
) -> dict[str, str]:
    lead = _clip(_fact_phrase(facts.get(lead_ids[0]) or {}), 220) if lead_ids else ""
    context = _clip(_fact_phrase(facts.get(context_ids[0]) or {}), 220) if context_ids else ""
    raw = verdict.get("counter_evidence") if verdict else None
    raw_items = raw.get("items", []) if isinstance(raw, dict) else []
    counter = next((
        _clip(item.get("phrase"), 220) for item in raw_items
        if isinstance(item, dict)
    ), "") if isinstance(raw_items, list) else ""
    base = {"kind": "source", "headline": headline, "thesis": thesis, "why": why}
    candidates: list[tuple[int, dict[str, str]]] = [(source_count * 8, base)]
    if lead and context:
        candidates.append((source_count * 8 + 40, {
            "kind": "boundary_condition",
            "headline": f"{_topic_title(topic)} may hinge on a boundary condition",
            "thesis": f"{lead}. Boundary receipts add a second constraint: {context}.",
            "why": (
                "The interesting signal is where the evidence stops generalizing: "
                "the memo is not a broad topic summary, but a testable boundary condition."
            ),
        }))
    if lead and counter:
        candidates.append((source_count * 8 + 44, {
            "kind": "counter_signal",
            "headline": f"{_topic_title(topic)} has a live counter-signal",
            "thesis": f"{lead}. The strongest opposing receipt says: {counter}.",
            "why": (
                "The value is the collision between receipts, not the isolated positive "
                "finding; this is the branch worth testing next."
            ),
        }))
    limit = max(1, min(5, _memo_alpha_int("angle_candidates", 5)))
    floor = max(0, min(100, _memo_alpha_int("min_angle_score", 45)))
    penalty = max(0, min(80, _memo_alpha_int("angle_repeat_penalty", 20)))
    recent = recent_kinds or {}
    score, winner = max(
        candidates[:limit],
        key=lambda item: item[0] - penalty * recent.get(item[1]["kind"], 0),
    )
    return winner if score >= floor else base


def _receipt_thesis(
    headline: str,
    audit: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    receipt_ids: list[str],
    context_ids: list[str],
    verdict: dict[str, Any] | None,
) -> str:
    fallback = _first_sentence(str(audit.get("rationale") or ""), "")
    stream_note = (
        " The cited receipts are separate evidence streams; this memo maps a "
        "testable contrast, not one integrated analysis."
    )
    if verdict and verdict.get("surface_type") == "context_dependence_memo":
        return _context_subline(verdict, fallback or headline)
    if fallback and not _same_phrase(fallback, headline):
        return fallback + stream_note
    phrases = [_fact_phrase(facts.get(fid) or {}) for fid in receipt_ids[:2]]
    joined = "; ".join(p for p in phrases if p)
    if joined:
        if context_ids:
            return (
                f"The direct receipts support a narrow working claim: {joined}. "
                "The context receipts provide source breadth and boundary checks, "
                "not independent confirmation of the lead claim."
            )
        return f"The cited A/B receipts support a specific working claim: {joined}.{stream_note}"
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


def _limitations_lines(
    weakening: list[str],
    *,
    lead_source_count: int,
    context_ids: list[str],
) -> list[str]:
    lines = [
        "- This is an alpha memo, not a settled review, guideline, or broad "
        "consensus claim.",
        "- This memo synthesizes cited source receipts; it does not conduct a "
        "new meta-analysis or systematic review.",
        "- Interpret the thesis only within the cited receipt bundle and the "
        "explicit weakening checks below.",
    ]
    if context_ids:
        lines.append(
            f"- The core claim rests on {lead_source_count} direct source paper(s); "
            "context receipts broaden the source bundle but are not convergent proof.",
        )
    return [*lines, *weakening[:3]]


def _why_surprising(
    fallback: str,
    context_ids: list[str],
) -> str:
    if context_ids:
        return (
            "Real tension: the useful signal is narrower than the topic label. "
            "The lead receipts support the core claim, while the added A/B "
            "context receipts define where that claim may generalize, fail, "
            "or need a separate extraction."
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
    *,
    grounded: bool = False,
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
    min_sources = _memo_alpha_int("min_source_papers", 5)
    min_direct_sources = _memo_alpha_int("min_direct_source_papers", 5)
    claim = _claim_signal(
        [str(x) for x in audit.get("cited_fact_ids", [])], facts, topic,
    )
    preferred_bound_ids = _preferred_receipt_ids(publish_verdict, lanes, _BINDABLE)
    preferred_direct_ids = _preferred_receipt_ids(publish_verdict, lanes, _DIRECT)
    expanded_ids = _expanded_receipt_ids(
        audit, facts, lanes, min_sources=min_sources, claim=claim, topic=topic,
        preferred_ids=preferred_bound_ids,
    )
    lead_ids = _expanded_receipt_ids(
        audit, facts, lanes,
        min_sources=min_direct_sources,
        allowed_lanes=_DIRECT,
        claim=claim, topic=topic,
        preferred_ids=preferred_direct_ids,
    )
    if not lead_ids:
        lead_ids = expanded_ids[:1]
    lead_set = set(lead_ids)
    receipt_ids = lead_ids + [fid for fid in expanded_ids if fid not in lead_set]
    context_ids = [fid for fid in receipt_ids if fid not in lead_set]
    with suppress(OSError):  # sidecar: claim -> receipts -> support, for audit
        (run_dir / "claim_receipt_matrix.json").write_text(
            json.dumps(build_claim_receipt_matrix(claim, lead_ids, receipt_ids, facts),
                       indent=2, sort_keys=True),
            encoding="utf-8")
    lead_source_count = _source_count_for_ids(lead_ids, facts)
    source_count = _source_count_for_ids(receipt_ids, facts)
    thesis = _receipt_thesis(
        headline, audit, facts, receipt_ids, context_ids, publish_verdict,
    )
    weakening = _weakening_lines(review if isinstance(review, dict) else {}, label)
    why_surprising = _why_surprising(
        _section(signal_md, "Why this is surprising"),
        context_ids,
    )
    recent_kinds = _recent_angle_kinds(run_dir)
    angle = _select_angle(
        topic, headline, thesis, why_surprising, facts, lead_ids,
        context_ids, publish_verdict, source_count,
        recent_kinds=recent_kinds,
    )
    if grounded:
        # Repair mode for scope/grounding rejects: drop the speculative
        # boundary/counter angle and tie title + thesis back to the cited
        # direct-source receipts, so the memo provably matches its bundle.
        angle = {"kind": "source", "headline": headline,
                 "thesis": thesis, "why": why_surprising}
    if publish_verdict and publish_verdict.get("surface_type") == "publish_alpha_memo":
        headline = angle["headline"]
    thesis = angle["thesis"]
    why_surprising = angle["why"]

    score = _alpha_score(audit, label)
    lines = [
        f"# Alpha memo — {topic}",
        "",
        f"**Headline:** {headline}",
        f"**Alpha score:** {score}/100",
        f"**Alpha triage:** `{_score_band(score)}` (internal ranking; not a certainty claim)",
        f"**Confidence:** `{label}`",
        f"**Memo surface:** `{_surface_line(publish_verdict)}`",
        f"**Selected angle:** `{angle['kind']}`",
        f"**Snapshot:** `{snapshot}`",
        f"**Run:** `{run_dir.name}`",
        f"**Direct source breadth:** `{lead_source_count}` direct cited source(s)",
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
            "contrast, receipt bundle, and matched direct-receipt table by "
            "population, model, endpoint, comparator, and effect direction that "
            "could confirm or kill the thesis."
        ),
        "",
        "## Limitations",
        "",
        *_limitations_lines(
            weakening,
            lead_source_count=lead_source_count,
            context_ids=context_ids,
        ),
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
    with suppress(OSError):  # FactReview-style consolidated audit pack
        memo_audit = build_memo_audit(
            claim, lead_ids, receipt_ids, facts, publish_verdict,
            falsifier=falsifier_present(body),
            novelty={"selected": angle["kind"],
                     "repeats": recent_kinds.get(angle["kind"], 0)},
            min_direct=min_direct_sources,
            run_dir=run_dir,
        )
        (run_dir / "typed_counter_evidence.json").write_text(
            json.dumps({"items": memo_audit["contradiction_receipts"]},
                       indent=2, sort_keys=True),
            encoding="utf-8")
        (run_dir / "novelty_delta.json").write_text(
            json.dumps({
                "novelty_delta": memo_audit["novelty_delta"],
                "nearest_literature": memo_audit["nearest_literature"],
            }, indent=2, sort_keys=True),
            encoding="utf-8")
        (run_dir / "memo_audit.json").write_text(
            json.dumps(memo_audit, indent=2, sort_keys=True),
            encoding="utf-8")
    lines.extend(["", *_provenance_block(run_dir, topic, snapshot, headline, body)])
    return "\n".join(lines) + "\n"


def write_signal_memo(
    run_dir: Path,
    signal_text: str | None = None,
    publish_verdict: dict[str, Any] | None = None,
    *,
    grounded: bool = False,
) -> tuple[Path, str]:
    text = render_signal_memo(
        run_dir, signal_text, publish_verdict, grounded=grounded)
    out = run_dir / "alpha_memo.md"
    out.write_text(text, encoding="utf-8")
    return out, text
