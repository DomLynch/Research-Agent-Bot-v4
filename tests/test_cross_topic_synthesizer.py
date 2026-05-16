"""Cross-topic alpha synthesis tests.

Fixtures are non-biomedical; the production code must work from
structural memo fields and alpha cues only.
"""
from __future__ import annotations

from pathlib import Path

from agent.cross_topic_synthesizer import (
    load_topic_memo,
    render_cross_topic_memo,
    select_cross_topic_pattern,
    write_cross_topic_memo,
)


def _memo(
    root: Path,
    topic: str,
    *,
    cue: str = "functional_endpoint",
    label: str = "evidence_backed_signal",
    receipt: bool = True,
) -> Path:
    run = root / f"{topic}-evidence-ts"
    run.mkdir()
    receipts = (
        "- `fact_id=1` (`A_core`) — Bound receipt DOI `10.x/y`"
        if receipt else
        "- _No A_core/B_context receipts bind to this memo._"
    )
    run.joinpath("alpha_memo.md").write_text(
        f"# Alpha memo — {topic}\n\n"
        f"**Headline:** {topic} changed a hard endpoint\n"
        "**Alpha score:** 80/100\n"
        f"**Confidence:** `{label}`\n"
        "**Snapshot:** `ts`\n"
        f"**Run:** `{run.name}`\n\n"
        "## One-sentence thesis\n\n"
        "A focused thesis.\n\n"
        "## Why this is surprising\n\n"
        "It appears outside one isolated pool.\n\n"
        "## Evidence receipts\n\n"
        f"{receipts}\n\n"
        "## What would weaken this\n\n"
        "- A stronger comparator explains the result.\n\n"
        "## Next extraction\n\n"
        "- Replicate the endpoint in a second source.\n\n"
        "## Supporting Top cards\n\n"
        f"- Top finding _(alpha cues: {cue})_\n",
        encoding="utf-8",
    )
    return run


def test_density_gate_requires_three_bound_topics(tmp_path: Path) -> None:
    runs = [_memo(tmp_path, f"topic{i}") for i in range(3)]
    memos = [m for run in runs if (m := load_topic_memo(run))]

    gate = select_cross_topic_pattern(memos)

    assert gate.passed
    assert gate.pattern == "functional_endpoint"
    assert [m.topic for m in gate.supporting] == ["topic0", "topic1", "topic2"]


def test_density_gate_fails_without_bound_receipts(tmp_path: Path) -> None:
    runs = [
        _memo(tmp_path, "topic0"),
        _memo(tmp_path, "topic1"),
        _memo(tmp_path, "topic2", receipt=False),
    ]
    memos = [m for run in runs if (m := load_topic_memo(run))]

    gate = select_cross_topic_pattern(memos)

    assert not gate.passed
    assert "Need >=" in gate.reason


def test_density_gate_allows_at_most_one_speculative_topic(tmp_path: Path) -> None:
    runs = [
        _memo(tmp_path, "topic0", label="speculative_alpha"),
        _memo(tmp_path, "topic1", label="speculative_alpha"),
        _memo(tmp_path, "topic2"),
    ]
    memos = [m for run in runs if (m := load_topic_memo(run))]

    assert not select_cross_topic_pattern(memos).passed


def test_render_cross_topic_memo_has_required_sections(tmp_path: Path) -> None:
    runs = [_memo(tmp_path, f"topic{i}") for i in range(3)]
    out = tmp_path / "cross_topic_alpha_memo.md"

    text = render_cross_topic_memo(runs, out, settings=None)

    assert "**Status:** `publishable_cross_topic_signal`" in text
    assert "## Cross-topic thesis" in text
    assert "## Strongest counter-thesis" in text
    assert "## What this changes" in text
    assert "## What would falsify it" in text
    assert "## Provenance / priority" in text
    assert "`topic0`" in text and "`topic2`" in text


def test_render_cross_topic_memo_writes_insufficient_density(tmp_path: Path) -> None:
    runs = [_memo(tmp_path, "topic0"), _memo(tmp_path, "topic1")]

    text = render_cross_topic_memo(
        runs, tmp_path / "cross_topic_alpha_memo.md", settings=None,
    )

    assert "**Status:** `insufficient_density`" in text
    assert "Memos inspected:** 2" in text


def test_write_cross_topic_memo_writes_file(tmp_path: Path) -> None:
    runs = [_memo(tmp_path, f"topic{i}") for i in range(3)]
    out = tmp_path / "cross_topic_alpha_memo.md"

    path, text = write_cross_topic_memo(runs, out, settings=None)

    assert path == out
    assert out.read_text(encoding="utf-8") == text
