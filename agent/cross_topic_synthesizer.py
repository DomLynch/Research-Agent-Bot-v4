"""Cross-topic alpha synthesis from existing alpha memo artifacts.

The density gate is structural: a lead synthesis can publish only when
multiple topic memos share one alpha cue and each supporting topic has
bound receipts. The model may sharpen prose, but it cannot create
evidence density.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agent.frontier_review import _parse as _parse_jsonish
from agent.llm_client import call_writer_with_fallback
from agent.settings import Settings
from agent.signal_memo_writer import _publication_defaults, _sha256

_PUBLISHABLE_LABELS = frozenset({
    "evidence_backed_signal", "frontier_hypothesis", "speculative_alpha",
})
_STOP_CUES = frozenset({"baseline", "context_fragment"})
_REQUIRED_KEYS = (
    "cross_topic_thesis",
    "why_surprising",
    "strongest_counter_thesis",
    "what_this_changes",
    "what_would_falsify_it",
    "next_extraction_campaign",
)


@dataclass(frozen=True, slots=True)
class TopicMemo:
    topic: str
    run_dir: Path
    headline: str
    label: str
    alpha_score: int
    receipts: tuple[str, ...]
    cues: tuple[str, ...]
    why_surprising: str
    weakens: tuple[str, ...]
    next_extractions: tuple[str, ...]

    @property
    def can_support_synthesis(self) -> bool:
        return bool(self.receipts) and self.label in _PUBLISHABLE_LABELS

    @property
    def speculative(self) -> bool:
        return self.label == "speculative_alpha"


@dataclass(frozen=True, slots=True)
class SynthesisGate:
    passed: bool
    pattern: str
    supporting: tuple[TopicMemo, ...]
    reason: str


def _section(md: str, heading: str) -> str:
    m = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)",
        md,
        flags=re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def _field(md: str, name: str) -> str:
    m = re.search(rf"^\*\*{re.escape(name)}:\*\* (.+)$", md, flags=re.M)
    return m.group(1).strip() if m else ""


def _bullets(section: str) -> tuple[str, ...]:
    return tuple(
        line.removeprefix("- ").strip()
        for line in section.splitlines()
        if line.startswith("- ") and line.removeprefix("- ").strip()
    )


def _cues(md: str) -> tuple[str, ...]:
    out: list[str] = []
    for raw in re.findall(r"_\(alpha cues: ([^)]+)\)_", md):
        for cue in raw.split(","):
            clean = cue.strip()
            if clean and clean not in _STOP_CUES:
                out.append(clean)
    return tuple(dict.fromkeys(out))


def load_topic_memo(run_dir: Path) -> TopicMemo | None:
    path = run_dir / "alpha_memo.md"
    try:
        md = path.read_text(encoding="utf-8")
    except OSError:
        return None
    topic = run_dir.name.split("-evidence-", 1)[0]
    score_raw = _field(md, "Alpha score").split("/", 1)[0]
    try:
        score = int(score_raw)
    except ValueError:
        score = 0
    receipts = tuple(
        line.strip()
        for line in _section(md, "Evidence receipts").splitlines()
        if line.startswith("- `fact_id=")
    )
    return TopicMemo(
        topic=topic,
        run_dir=run_dir,
        headline=_field(md, "Headline") or f"Open signal — {topic}",
        label=_field(md, "Confidence").strip("`") or "unknown",
        alpha_score=score,
        receipts=receipts,
        cues=_cues(md),
        why_surprising=_section(md, "Why this is surprising"),
        weakens=_bullets(_section(md, "What would weaken this")),
        next_extractions=_bullets(_section(md, "Next extraction")),
    )


def select_cross_topic_pattern(
    memos: list[TopicMemo], min_topics: int = 3,
) -> SynthesisGate:
    eligible = [m for m in memos if m.can_support_synthesis]
    cue_map: dict[str, list[TopicMemo]] = {}
    for memo in eligible:
        for cue in memo.cues:
            cue_map.setdefault(cue, []).append(memo)
    candidates = [
        (cue, tuple(sorted(rows, key=lambda m: m.alpha_score, reverse=True)))
        for cue, rows in cue_map.items()
        if len(rows) >= min_topics and sum(m.speculative for m in rows) <= 1
    ]
    if not candidates:
        return SynthesisGate(
            passed=False,
            pattern="",
            supporting=(),
            reason=(
                f"Need >= {min_topics} topics sharing one alpha cue, each "
                "with bound receipts, and no more than one speculative topic."
            ),
        )
    cue, rows = max(
        candidates,
        key=lambda item: (len(item[1]), sum(m.alpha_score for m in item[1])),
    )
    return SynthesisGate(
        passed=True,
        pattern=cue,
        supporting=rows,
        reason="density gate passed",
    )


def _fallback_sections(gate: SynthesisGate) -> dict[str, Any]:
    topics = ", ".join(m.topic for m in gate.supporting)
    return {
        "cross_topic_thesis": (
            f"Multiple independent topic memos converge on `{gate.pattern}` "
            f"as the shared publishable signal across {topics}."
        ),
        "why_surprising": (
            "The shared pattern appears across separate topic runs rather "
            "than inside one isolated evidence pool, making it a higher-level "
            "lead candidate instead of another Top 5 item."
        ),
        "strongest_counter_thesis": (
            "The overlap may reflect broad scoring vocabulary rather than "
            "a true field-level pattern; each topic still needs its own "
            "causal interpretation."
        ),
        "what_this_changes": (
            "Treat the next review cycle as a cross-topic extraction campaign: "
            "test the shared pattern directly instead of publishing each topic "
            "in isolation."
        ),
        "what_would_falsify_it": (
            "The synthesis weakens if one or more supporting topics lose their "
            "bound receipts or if source audit shows the shared cue was only "
            "a wording artifact."
        ),
        "next_extraction_campaign": [
            item
            for memo in gate.supporting
            for item in memo.next_extractions[:1]
        ] or ["Add independent bound receipts for the shared pattern."],
    }


def _messages(gate: SynthesisGate) -> list[dict[str, str]]:
    rows = []
    for memo in gate.supporting:
        rows.append(
            f"TOPIC={memo.topic}\n"
            f"HEADLINE={memo.headline}\n"
            f"CONFIDENCE={memo.label} SCORE={memo.alpha_score}\n"
            f"CUES={', '.join(memo.cues) or 'none'}\n"
            f"RECEIPTS={len(memo.receipts)} bound\n"
            f"WHY={memo.why_surprising[:900]}\n"
            f"WEAKENS={' | '.join(memo.weakens[:2])}\n"
            f"NEXT={' | '.join(memo.next_extractions[:2])}"
        )
    schema: dict[str, Any] = {
        key: "string" for key in _REQUIRED_KEYS
        if key != "next_extraction_campaign"
    }
    schema["next_extraction_campaign"] = ["string"]
    return [
        {
            "role": "system",
            "content": (
                "You write cross-topic research-intelligence memos. "
                "Use only the provided topic memos. Do not invent source "
                "facts. Preserve caveats. Return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"SHARED_PATTERN={gate.pattern}\n\n"
                + "\n\n---\n\n".join(rows)
                + "\n\nRequired JSON schema:\n"
                + json.dumps(schema, indent=2)
            ),
        },
    ]


def _llm_sections(gate: SynthesisGate, settings: Settings | None) -> dict[str, Any]:
    if settings is None or not settings.writer_configured:
        return _fallback_sections(gate)
    try:
        resp = call_writer_with_fallback(
            settings, _messages(gate), temperature=0.2, max_tokens=1800,
        )
    except (RuntimeError, OSError, httpx.HTTPError):
        return _fallback_sections(gate)
    parsed = _parse_jsonish(resp.content)
    if not isinstance(parsed, dict):
        return _fallback_sections(gate)
    if not all(str(parsed.get(key) or "").strip() for key in _REQUIRED_KEYS[:-1]):
        return _fallback_sections(gate)
    next_raw = parsed.get("next_extraction_campaign")
    if not isinstance(next_raw, list) or not next_raw:
        parsed["next_extraction_campaign"] = _fallback_sections(gate)[
            "next_extraction_campaign"
        ]
    return parsed


def _provenance(
    output_path: Path, memos: list[TopicMemo], body: str,
) -> list[str]:
    pub = _publication_defaults()
    bundle_parts: list[str] = []
    for memo in memos:
        path = memo.run_dir / "alpha_memo.md"
        if path.exists():
            bundle_parts.append(
                f"{memo.run_dir.name}:{_sha256(path.read_text(encoding='utf-8'))}"
            )
    citation = (
        f"{pub['author']}. Cross-topic alpha synthesis. "
        f"{pub['venue']}. Version {pub['version']}."
    ).strip()
    return [
        "## Provenance / priority",
        "",
        f"- **Author:** {pub['author'] or '_not configured_'}",
        f"- **ORCID:** {pub['orcid'] or '_not configured_'}",
        f"- **Version:** {pub['version']}",
        f"- **License:** {pub['license']}",
        f"- **Suggested citation:** {citation}",
        f"- **Output file:** `{output_path.name}`",
        f"- **Input bundle SHA-256:** `{_sha256(chr(10).join(bundle_parts))}`",
        f"- **Memo SHA-256:** `{_sha256(body)}`",
        "- **Priority note:** This cross-topic memo records the first "
        "published synthesis over the listed alpha memo bundle. Reuse "
        "should cite the canonical version.",
    ]


def render_cross_topic_memo(
    run_dirs: list[Path],
    output_path: Path,
    *,
    settings: Settings | None = None,
    min_topics: int = 3,
) -> str:
    memos = [m for p in run_dirs if (m := load_topic_memo(p))]
    gate = select_cross_topic_pattern(memos, min_topics=min_topics)
    if not gate.passed:
        lines = [
            "# Cross-topic alpha memo",
            "",
            "**Status:** `insufficient_density`",
            f"**Reason:** {gate.reason}",
            f"**Memos inspected:** {len(memos)}",
            "",
            "## Supporting signals by topic",
            "",
        ]
        for memo in memos:
            lines.append(
                f"- `{memo.topic}` — `{memo.label}`, receipts={len(memo.receipts)}, "
                f"cues={', '.join(memo.cues) or 'none'}"
            )
        body = "\n".join(lines) + "\n"
        return "\n".join([body, *_provenance(output_path, memos, body)]) + "\n"

    sections = _llm_sections(gate, settings)
    support = [
        f"- `{m.topic}` — {m.headline} "
        f"(`{m.label}`, {len(m.receipts)} bound receipts)"
        for m in gate.supporting
    ]
    lines = [
        "# Cross-topic alpha memo",
        "",
        "**Status:** `publishable_cross_topic_signal`",
        f"**Shared pattern:** `{gate.pattern}`",
        f"**Topics supporting:** {len(gate.supporting)}",
        "",
        "## Cross-topic thesis",
        "",
        str(sections["cross_topic_thesis"]).strip(),
        "",
        "## Why this is surprising",
        "",
        str(sections["why_surprising"]).strip(),
        "",
        "## Supporting signals by topic",
        "",
        *support,
        "",
        "## Strongest counter-thesis",
        "",
        str(sections["strongest_counter_thesis"]).strip(),
        "",
        "## What this changes",
        "",
        str(sections["what_this_changes"]).strip(),
        "",
        "## What would falsify it",
        "",
        str(sections["what_would_falsify_it"]).strip(),
        "",
        "## Next extraction campaign",
        "",
    ]
    lines.extend(
        f"- {str(item)[:240]}"
        for item in sections.get("next_extraction_campaign", [])[:6]
    )
    body = "\n".join(lines) + "\n"
    return "\n".join(
        [body, *_provenance(output_path, list(gate.supporting), body)]
    ) + "\n"


def write_cross_topic_memo(
    run_dirs: list[Path],
    output_path: Path,
    *,
    settings: Settings | None = None,
    min_topics: int = 3,
) -> tuple[Path, str]:
    text = render_cross_topic_memo(
        run_dirs, output_path, settings=settings, min_topics=min_topics,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return output_path, text
