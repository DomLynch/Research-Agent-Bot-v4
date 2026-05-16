"""Sprint 70 — run-folder top_N.md integrity gate.

The auditor caught the on-disk sirtuin top_5.md still showing
`72 h whey` and `Cal 27 betaine` as effect-size findings even after
the sanitizer fix. The code path that filters them was correct, but
the rendered artifact was never regenerated.

This test closes the gap: walk every runs/*-evidence-*/top_*.md and
assert that no (Finding, Value) pair currently extractable from the
markdown would be filtered by the current numeric_sanitizer. If a
sanitizer rule lands AFTER a run was rendered, the test fails until
the operator regenerates the artifact via
`scripts/regen_top_from_run.py <run-dir>`.

Universal — operates on syntactic shape only, no domain literals.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent.numeric_sanitizer import is_numeric_artifact

_RUNS = Path(__file__).resolve().parent.parent / "runs"
_FINDING_RE = re.compile(r"^\*\*Finding:\*\*\s+(.+?)\s*$", re.MULTILINE)
_VALUE_RE = re.compile(r"^-\s*\*\*Value:\*\*\s*([-\d.]+)", re.MULTILINE)


def _top_n_files() -> list[Path]:
    """Every canonical top_N.md under runs/*-evidence-*/ where the
    matching all_facts.json exists (i.e. the run is regen-able via
    `scripts/regen_top_from_run.py`). Skips macOS Finder duplicates
    (e.g. `top_5 2.md`) and legacy runs without all_facts.json."""
    if not _RUNS.exists():
        return []
    out: list[Path] = []
    for run_dir in sorted(_RUNS.glob("*-evidence-*")):
        if not run_dir.is_dir():
            continue
        if not (run_dir / "all_facts.json").exists():
            continue
        for p in sorted(run_dir.glob("top_*.md")):
            # macOS Finder dupes look like `top_5 2.md`; canonical
            # files have no space before the extension.
            if " " in p.name:
                continue
            out.append(p)
    return out


def _pairs_in_card_order(text: str) -> list[tuple[float, str]]:
    """Pair each `Value` with the most recent `Finding` above it."""
    out: list[tuple[float, str]] = []
    finding = ""
    for line in text.splitlines():
        f = _FINDING_RE.match(line)
        if f:
            finding = f.group(1).strip()
            continue
        v = _VALUE_RE.match(line)
        if v and finding:
            try:
                val = float(v.group(1))
            except ValueError:
                continue
            out.append((val, finding))
            finding = ""  # one Value per Finding
    return out


@pytest.mark.parametrize("path", _top_n_files(),
                         ids=lambda p: f"{p.parent.name}/{p.name}")
def test_top_n_md_no_sanitizer_artifacts(path: Path) -> None:
    """For each rendered top_N.md, no (Finding, Value) pair may be
    flagged as artifact by the current sanitizer. If a sanitizer
    rule lands after a run was rendered, regenerate the artifact via
    `scripts/regen_top_from_run.py`."""
    text = path.read_text(encoding="utf-8")
    leaks: list[str] = []
    for value, finding in _pairs_in_card_order(text):
        if is_numeric_artifact(value, finding):
            leaks.append(f"value={value} in: {finding[:90]!r}")
    assert not leaks, (
        f"{path.relative_to(_RUNS.parent)} contains "
        f"{len(leaks)} fact(s) the current sanitizer would filter. "
        f"Regenerate via `scripts/regen_top_from_run.py "
        f"{path.parent}`. Leaks:\n  - "
        + "\n  - ".join(leaks)
    )
