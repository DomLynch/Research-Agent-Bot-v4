"""Draft sections of the main manuscript via the writer LLM, save to runs/.

Section-by-section iteration tool. Iteration N produces section(s) and
saves them under `runs/<topic>-iter-NN-<ts>/`. Cheap to re-run — change
the prompt or topic and bump the iter counter.

Usage:
    .venv/bin/python scripts/draft_main.py
    .venv/bin/python scripts/draft_main.py --topic metformin --iter 2
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.claim_gates import run_all_gates
from agent.llm_client import call_writer_with_fallback
from agent.maturity_router import select_paper_type, writer_preamble
from agent.prompts import (
    writer_discussion,
    writer_methods,
    writer_title_abstract_intro,
)
from agent.readiness import classify_readiness
from agent.settings import load_settings
from agent.topic_pack import load_topic_pack

_SECTION_PROMPTS = {
    "title_abstract_intro": (writer_title_abstract_intro, ["TITLE", "ABSTRACT", "INTRODUCTION"]),
    "methods": (writer_methods, ["METHODS"]),
    "discussion": (writer_discussion, ["DISCUSSION", "LIMITATIONS", "CONCLUSION"]),
}

_SECTION_RE = re.compile(r"^===\s*([A-Z][A-Z0-9 \-]*?)\s*===\s*$", re.MULTILINE)


def _writer_preamble_from_latest_s7(topic: str) -> str:
    """Sprint 32 — build the paper-type-aware writer preamble from
    receipts in the most recent `runs/<topic>-s7-iter-*` directory.

    Empty string when no s7 dir exists yet (first iteration before
    eligibility ran), or when receipt-loading fails — degrades to the
    pre-Sprint-32 prompt unchanged. Universal: reads canonical
    receipts only, no topic literals.
    """
    runs_dir = Path(__file__).resolve().parent.parent / "runs"
    s7_dirs = sorted(runs_dir.glob(f"{topic}-s7-iter-*"), reverse=True)
    if not s7_dirs:
        return ""
    s7 = s7_dirs[0]

    def _load(name: str) -> dict[str, object]:
        p = s7 / name
        if not p.exists():
            return {}
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    readiness = classify_readiness(
        summary=_load("eligibility_summary.json"),
        strict=_load("primary_effect_input_set_strict.json"),
        extractions=_load("effect_extractions.json"),
        pool=_load("effect_pool.json"),
    )
    paper_type = select_paper_type(readiness)
    return writer_preamble(paper_type)


def _parse_sections(raw: str) -> dict[str, str]:
    """Split MiMo output on `===NAME===` markers into a dict."""
    matches = list(_SECTION_RE.finditer(raw))
    if not matches:
        return {}
    parsed: dict[str, str] = {}
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        parsed[name] = raw[start:end].strip()
    return parsed


def _render_markdown(parsed: dict[str, str], order: list[str]) -> str:
    """Render parsed sections as a clean Markdown document."""
    lines: list[str] = []
    if "TITLE" in order:
        title = parsed.get("TITLE", "").strip()
        if title:
            lines.append(f"# {title}")
            lines.append("")
    for name in order:
        if name == "TITLE":
            continue
        body = parsed.get(name, "").strip()
        if not body:
            continue
        lines.append(f"## {name.title()}")
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="rapamycin", help="research topic")
    parser.add_argument("--iter", type=int, default=1, help="iteration number")
    parser.add_argument(
        "--section",
        default="title_abstract_intro",
        choices=sorted(_SECTION_PROMPTS),
        help="which manuscript section to draft",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.writer_configured:
        print("ERROR: writer not configured (MIMO_API_KEY missing)", file=sys.stderr)
        return 2

    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    _section_short_map = {
        "title_abstract_intro": "s1",
        "methods": "s2",
        "discussion": "s6",
    }
    section_short = _section_short_map.get(args.section, "sX")
    run_id = f"{args.topic}-{section_short}-iter-{args.iter:02d}-{ts}"
    out_dir = Path(settings.runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    pack = load_topic_pack(args.topic)
    prompt_fn, order = _SECTION_PROMPTS[args.section]
    messages = prompt_fn(args.topic, pack)
    # Sprint 32 — paper-type-aware writer preamble. Compute the engine
    # state (readiness + paper-type) from the most recent s7 run dir
    # and prepend the resulting framing constraints to the writer's
    # system message. Universal: derives entirely from canonical
    # receipts; no topic literals. When no s7 dir exists yet (first
    # iteration before eligibility ran), the preamble is empty and
    # behavior is identical to pre-Sprint-32.
    preamble = _writer_preamble_from_latest_s7(args.topic)
    if preamble and messages and messages[0].get("role") == "system":
        messages[0]["content"] = preamble + "\n" + messages[0]["content"]
        print(f"[draft] paper-type preamble injected ({len(preamble)} chars)")
    print(f"[draft] topic={args.topic} section={args.section} iter={args.iter} model={settings.mimo_model}")
    print(f"[draft] topic_pack={'loaded' if pack else 'none'}")
    print("[draft] calling writer…")
    # Sprint 31 follow-up: discussion + methods sections frequently
    # exceed the default 4000-token cap (acarbose discussion truncated
    # mid-sentence on iter-2). Bump to 5000 — still well below the
    # ~6000 MiMo runaway threshold (Sprint 14 calibration); the Sprint
    # 14 Gemma fallback handles the rare runaway edge case.
    resp = call_writer_with_fallback(settings, messages, max_tokens=5000)
    print(f"[draft] tokens: prompt={resp.prompt_tokens} completion={resp.completion_tokens}")

    parsed = _parse_sections(resp.content)
    rendered = _render_markdown(parsed, order) if parsed else f"# (parse failed)\n\n{resp.content}\n"

    violations = run_all_gates(parsed, pack) if parsed else []
    gates_by_type: dict[str, int] = {}
    for v in violations:
        gates_by_type[v.gate] = gates_by_type.get(v.gate, 0) + 1

    (out_dir / "raw_response.md").write_text(resp.content, encoding="utf-8")
    (out_dir / "main_draft.md").write_text(rendered, encoding="utf-8")
    (out_dir / "gates.json").write_text(
        json.dumps(
            {
                "summary": {"total": len(violations), "by_gate": gates_by_type},
                "violations": [v.as_dict() for v in violations],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "topic": args.topic,
                "iteration": args.iter,
                "timestamp_utc": ts,
                "model": resp.model,
                "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens,
                "section_key": args.section,
                "sections_requested": order,
                "sections_parsed": sorted(parsed.keys()),
                "parse_ok": bool(parsed),
                "gate_violations": len(violations),
                "gates_by_type": gates_by_type,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[draft] sections parsed: {sorted(parsed.keys())}")
    print(f"[draft] gates: {len(violations)} violations {gates_by_type or '(clean)'}")
    print(f"[draft] saved → {out_dir}/main_draft.md")
    print(f"[draft] raw   → {out_dir}/raw_response.md")
    print(f"[draft] gates → {out_dir}/gates.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
