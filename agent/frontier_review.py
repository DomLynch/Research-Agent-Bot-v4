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

import httpx

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
    cited_fact_ids: tuple[str, ...] = ()  # Sprint 67: explicit fact-id binding

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
                "rationale": self.rationale,
                "cited_fact_ids": list(self.cited_fact_ids)}


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
                "next_extractions": list(self.next_extractions),
                "raw_response": self.raw_response}


_SCHEMA = """{
  "lens": "1-3 sentences. The non-obvious framing. NOT 'topic does X'.",
  "known_to_ignore": ["obvious fact 1 already in the literature", ...],
  "tensions": ["concrete tension between specific studies/subgroups", ...],
  "gaps": ["specific underexplored subgroup/dose/timing/species", ...],
  "theses": [{
    "title": "one-line publishable angle",
    "paper_type": "corpus-snapshot|evidence-gap|scoping-review|pilot-meta-analysis|meta-analysis-standard|meta-analysis-full",
    "novelty": 0-100, "evidence_strength": 0-100, "reviewer_risk": 0-100,
    "rationale": "1-2 sentences why this is publishable",
    "cited_fact_ids": ["EXACT fact_id strings from the FACTS block",
                       "...at minimum 2-3 IDs that directly support this thesis"]
  }],
  "reviewer_objections": ["concrete attack a peer reviewer would make", ...],
  "next_extractions": ["specific subtopic/population/dose to harvest next", ...]
}"""


def _format_fact_line(i: int, f: dict[str, Any]) -> str:
    p = f.get("source_paper") or {}
    # Sprint 67: include fact_id so MiMo can return exact citations
    # (cited_fact_ids array per thesis) instead of paraphrased prose.
    return (f"[{i+1}] fact_id={f.get('fact_id', '')!r} "
            f"{f.get('canonical_phrase', '')!r} "
            f"value={f.get('numeric_value')}{f.get('units', '') or ''} "
            f"pop={(f.get('population') or '?')!r} "
            f"intervention={(f.get('intervention') or '?')!r} "
            f"year={p.get('year', '?')} journal={p.get('journal', '?')!r}")


def _build_messages(
    topic: str, evidence_facts: list[dict[str, Any]],
    alpha_hints: list[dict[str, Any]],
    papers: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    # Sprint 75 — evidence vs hints boundary. Theses may cite ONLY
    # ids that appear in EVIDENCE FACTS (A_core / B_context lane).
    # ALPHA HINTS (C_noise / D_bad_extraction) are inspiration only;
    # MiMo may use them to populate next_extractions but never
    # cited_fact_ids. This keeps the creative layer working inside
    # the binding boundary instead of producing rejected theses.
    evidence_block = "\n".join(
        _format_fact_line(i, f) for i, f in enumerate(evidence_facts[:25]))
    hints_block = ""
    if alpha_hints:
        # Hints get NO fact-id tag — only the canonical phrase + paper
        # — so the model cannot accidentally cite them as evidence.
        hint_lines = [
            f"- {str(f.get('canonical_phrase') or '')[:200]} "
            f"(paper={(f.get('source_paper') or {}).get('doi') or '?'})"
            for f in alpha_hints[:25]
        ]
        hints_block = (
            "\n\nALPHA HINTS (untagged — INSPIRATION ONLY, MAY NOT "
            "BE CITED):\n" + "\n".join(hint_lines)
        )
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
        "4. **cited_fact_ids must reference only ids from EVIDENCE "
        "FACTS.** ALPHA HINTS are inspiration for `next_extractions` "
        "only — never cite them. A thesis whose citations are all "
        "hints will be rejected at the binding gate.\n"
        "5. Respond as VALID JSON only. No prose before or after."
    )
    user_msg = (
        f"TOPIC: {topic}\n"
        f"EVIDENCE FACTS ({len(evidence_facts)} A/B-bound, top 25; "
        f"these are the ONLY ids you may cite):\n"
        f"{evidence_block}{hints_block}{papers_block}\n\n"
        f"Required JSON schema:\n{_SCHEMA}"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _parse_thesis(d: dict[str, Any]) -> PaperThesis | None:
    title = str(d.get("title", "")).strip()
    if not title:
        return None
    cited_raw = d.get("cited_fact_ids", [])
    cited = tuple(str(fid).strip() for fid in cited_raw
                  if isinstance(cited_raw, list)
                  and isinstance(fid, (str, int)) and str(fid).strip())
    return PaperThesis(
        title=title, paper_type=str(d.get("paper_type", "")).strip(),
        novelty=_clamp_int(d.get("novelty")),
        evidence_strength=_clamp_int(d.get("evidence_strength")),
        reviewer_risk=_clamp_int(d.get("reviewer_risk")),
        rationale=str(d.get("rationale", "")).strip(),
        cited_fact_ids=cited,
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


def _bracket_stack(text: str) -> tuple[list[str], bool]:
    """Return (open-bracket stack, in_string_at_eof) for `text`."""
    stack: list[str] = []
    in_str, esc = False, False
    for ch in text:
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    return stack, in_str


def _try_repair_json(text: str) -> str:
    """Repair MiMo responses truncated mid-stream. Strategy: collect
    cut points (after `]`/`}`, before `,`), try each from latest back,
    close any open brackets, return the first valid candidate."""
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    cuts: list[int] = []
    in_str, esc = False, False
    for i, ch in enumerate(text):
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "}]":
            cuts.append(i + 1)
        elif ch == ",":
            cuts.append(i)
    closers = {"{": "}", "[": "]"}
    for cut in reversed(cuts):
        prefix = text[:cut].rstrip().rstrip(",").rstrip()
        stack, mid_str = _bracket_stack(prefix)
        if mid_str:
            continue
        candidate = prefix + "".join(closers[s] for s in reversed(stack))
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return text


def _parse(raw: str) -> dict[str, Any]:
    """Tolerant JSON parser — strips code fences, repairs MiMo
    truncation, returns {} on irrecoverable failure."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    repaired = _try_repair_json(text)
    try:
        loaded = json.loads(repaired)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def run_frontier_review(
    *, topic: str, snapshot_utc: str,
    evidence_facts: list[dict[str, Any]],
    alpha_hints: list[dict[str, Any]] | None = None,
    papers: list[dict[str, Any]] | None, settings: Settings,
    max_tokens: int = 4000,
) -> FrontierReview:
    """Single MiMo call (Gemma fallback) -> structured review.

    Sprint 75: evidence/hints boundary. `evidence_facts` are
    A_core/B_context lane facts MiMo may cite. `alpha_hints` are
    C_noise/D_bad facts surfaced for inspiration only — they may
    inform `next_extractions` but never `cited_fact_ids`.

    Never raises. On config / HTTP / JSON failure returns an empty
    FrontierReview with model='error:<reason>' so the caller can write
    the artifact and audit it.
    """
    hints = list(alpha_hints or [])
    if not evidence_facts and not hints:
        return _empty(topic, snapshot_utc, "no_facts")
    if not settings.writer_configured:
        return _empty(topic, snapshot_utc, "writer_not_configured")
    messages = _build_messages(topic, evidence_facts, hints, papers)
    try:
        resp = call_writer_with_fallback(
            settings, messages, temperature=0.4, max_tokens=max_tokens,
        )
    except (RuntimeError, OSError, httpx.HTTPError) as e:
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
