"""Sprint 49 — frontier-model research-strategist layer.

Deterministic top-N is the truth floor. This module is the INSIGHT
ceiling: passes the scored fact set + paper metadata to MiMo v2.5 Pro
and asks for non-obvious lens, tensions, gaps, paper theses, reviewer
objections. Fact leaderboard -> research opportunity engine.
Universal: no domain literals. JSON-only response; tolerant parser
returns an empty review on any failure so callers never crash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.llm_client import call_writer_with_fallback
from agent.settings import Settings


@dataclass(frozen=True, slots=True)
class PaperThesis:
    title: str
    paper_type: str
    novelty: int
    evidence_strength: int
    reviewer_risk: int
    rationale: str

    @property
    def opportunity_score(self) -> int:
        risk = max(self.reviewer_risk, 10)
        return min(100, int(self.evidence_strength * self.novelty / risk))

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "paper_type": self.paper_type,
                "novelty": self.novelty,
                "evidence_strength": self.evidence_strength,
                "reviewer_risk": self.reviewer_risk,
                "opportunity_score": self.opportunity_score,
                "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class FrontierReview:
    topic: str
    snapshot_utc: str
    model: str
    lens: str
    known_to_ignore: tuple[str, ...]
    tensions: tuple[str, ...]
    gaps: tuple[str, ...]
    theses: tuple[PaperThesis, ...]
    reviewer_objections: tuple[str, ...]
    next_extractions: tuple[str, ...]
    raw_response: str

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "snapshot_utc": self.snapshot_utc,
                "model": self.model, "lens": self.lens,
                "known_to_ignore": list(self.known_to_ignore),
                "tensions": list(self.tensions), "gaps": list(self.gaps),
                "theses": [t.as_dict() for t in self.theses],
                "reviewer_objections": list(self.reviewer_objections),
                "next_extractions": list(self.next_extractions)}


_SCHEMA = """{
  "lens": "1-3 sentences. The non-obvious framing. NOT 'topic does X'.",
  "known_to_ignore": ["obvious fact 1 already in the literature", ...],
  "tensions": ["concrete tension between specific studies/subgroups", ...],
  "gaps": ["specific underexplored subgroup/dose/timing/species", ...],
  "theses": [{
    "title": "one-line publishable angle",
    "paper_type": "corpus-snapshot|evidence-gap|scoping-review|pilot-meta-analysis|meta-analysis-standard|meta-analysis-full",
    "novelty": 0-100, "evidence_strength": 0-100, "reviewer_risk": 0-100,
    "rationale": "1-2 sentences why this is publishable"
  }],
  "reviewer_objections": ["concrete attack a peer reviewer would make", ...],
  "next_extractions": ["specific subtopic/population/dose to harvest next", ...]
}"""


def _format_fact_line(i: int, f: dict[str, Any]) -> str:
    p = f.get("source_paper") or {}
    return (f"[{i+1}] {f.get('canonical_phrase', '')!r} "
            f"value={f.get('numeric_value')}{f.get('units', '') or ''} "
            f"pop={(f.get('population') or '?')!r} "
            f"intervention={(f.get('intervention') or '?')!r} "
            f"year={p.get('year', '?')} journal={p.get('journal', '?')!r} "
            f"validator={f.get('validator') or 'none'} "
            f"superseded={'yes' if f.get('superseded_by') else 'no'}")


def _build_messages(
    topic: str, facts: list[dict[str, Any]],
    papers: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    facts_block = "\n".join(_format_fact_line(i, f) for i, f in enumerate(facts[:25]))
    papers_block = ""
    if papers:
        lines = []
        for i, p in enumerate(papers[:15]):
            lines.append(
                f"[{i+1}] {p.get('journal_name', '?')!r} {p.get('publication_year', '?')} "
                f"cited={p.get('cited_by_count', 0)} fwci={p.get('fwci')} "
                f"quality={p.get('quality_score')} doi={p.get('doi', '?')}"
            )
        papers_block = "\n\nPAPER METADATA (sample):\n" + "\n".join(lines)
    sys_msg = (
        "You are a research strategist. Your output decides whether a "
        "research paper gets written. You are NOT summarising and you "
        "are NOT ranking facts. The deterministic layer already did "
        "that. Your job is the LENS: the non-obvious framing that "
        "would actually be publishable.\n\n"
        "Hard rules:\n"
        "1. Never restate the headline ('topic X does Y'). That is "
        "obvious — list it under known_to_ignore instead.\n"
        "2. Be specific: name studies, strains, doses, journals, "
        "subgroups. Generic prose is a failure.\n"
        "3. If the evidence pool is too noisy or too narrow for a "
        "publishable thesis, say so — return empty theses and explain "
        "in the lens why.\n"
        "4. Respond as VALID JSON only. No prose before or after."
    )
    user_msg = (
        f"TOPIC: {topic}\n"
        f"FACTS ({len(facts)} total, top 25 by deterministic score):\n"
        f"{facts_block}{papers_block}\n\n"
        f"Required JSON schema:\n{_SCHEMA}"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _parse_thesis(d: dict[str, Any]) -> PaperThesis | None:
    title = str(d.get("title", "")).strip()
    if not title:
        return None
    return PaperThesis(
        title=title, paper_type=str(d.get("paper_type", "")).strip(),
        novelty=_clamp_int(d.get("novelty")),
        evidence_strength=_clamp_int(d.get("evidence_strength")),
        reviewer_risk=_clamp_int(d.get("reviewer_risk")),
        rationale=str(d.get("rationale", "")).strip(),
    )


def _clamp_int(v: Any) -> int:
    try:
        return max(0, min(100, int(float(v))))
    except (TypeError, ValueError):
        return 0


def _str_list(v: Any) -> tuple[str, ...]:
    if not isinstance(v, list):
        return ()
    return tuple(str(x).strip() for x in v if str(x).strip())


def _parse(raw: str) -> dict[str, Any]:
    """Tolerant JSON parser — strips code fences, returns {} on failure."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def run_frontier_review(
    *, topic: str, snapshot_utc: str, facts: list[dict[str, Any]],
    papers: list[dict[str, Any]] | None, settings: Settings,
    max_tokens: int = 3000,
) -> FrontierReview:
    """Single MiMo call (Gemma fallback) -> structured review.

    Never raises. On config / HTTP / JSON failure returns an empty
    FrontierReview with model='error:<reason>' so the caller can write
    the artifact and audit it.
    """
    if not facts:
        return _empty(topic, snapshot_utc, "no_facts")
    if not settings.writer_configured:
        return _empty(topic, snapshot_utc, "writer_not_configured")
    messages = _build_messages(topic, facts, papers)
    try:
        resp = call_writer_with_fallback(
            settings, messages, temperature=0.4, max_tokens=max_tokens,
        )
    except (RuntimeError, OSError) as e:
        return _empty(topic, snapshot_utc, f"llm_call_failed:{type(e).__name__}")
    data = _parse(resp.content)
    theses_raw = data.get("theses", [])
    theses: list[PaperThesis] = []
    if isinstance(theses_raw, list):
        for item in theses_raw:
            if isinstance(item, dict):
                t = _parse_thesis(item)
                if t is not None:
                    theses.append(t)
    return FrontierReview(
        topic=topic, snapshot_utc=snapshot_utc, model=resp.model,
        lens=str(data.get("lens", "")).strip(),
        known_to_ignore=_str_list(data.get("known_to_ignore")),
        tensions=_str_list(data.get("tensions")),
        gaps=_str_list(data.get("gaps")), theses=tuple(theses),
        reviewer_objections=_str_list(data.get("reviewer_objections")),
        next_extractions=_str_list(data.get("next_extractions")),
        raw_response=resp.content,
    )


def _empty(topic: str, snapshot_utc: str, reason: str) -> FrontierReview:
    return FrontierReview(
        topic=topic, snapshot_utc=snapshot_utc, model=f"error:{reason}",
        lens="", known_to_ignore=(), tensions=(), gaps=(), theses=(),
        reviewer_objections=(), next_extractions=(), raw_response="",
    )
