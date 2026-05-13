"""Universal-no-hardcoding gates — fails if `agent/` core code embeds
domain-specific assumptions that should live in topic-pack data.

These are EXPECTED-FAIL tests that document known leaks. As each leak
is fixed by a refactor, the corresponding xfail decorator comes off and
the test becomes a permanent gate.

Universal-no-hardcoding contract (`AGENTS.md`):
    No LLM owns truth. No literal owns topic. No gate owns more than
    its rule. No section owns evidence outside its packet.

Concrete operationalisation:
    `agent/` source MAY contain:
      - generic meta-analysis methodology terms (random-effects pool,
        inverse-variance weight, etc.)
      - the project's universal receipt-schema field names
        (`treated_n`, `control_n`, `status`, `metric`)
      - documentation-example strings (in docstrings / comments)
      - test fixtures with domain-shaped data

    `agent/` source MUST NOT contain in actual logic:
      - lane keys that name a specific endpoint or system
        (`A_core_direct_lifespan` names "lifespan"; should be `A_primary`)
      - intervention names (rapamycin, metformin, sirolimus)
      - species names (mouse, murine) outside topic-pack-driven paths
      - hard-coded references to one domain's frameworks (SYRCLE per-
        domain only) absent the multi-domain alternative branch
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

# Lane keys currently hardcoded in agent/ that name a specific endpoint
# (lifespan, survival) instead of the lane FUNCTION (primary,
# sensitivity, secondary). These keys appear in actual logic — string
# literal arguments to `.get(...)` calls, Literal[...] type unions,
# etc. — not just in docstrings.
_LIFESPAN_LANE_KEYS = (
    "A_direct_lifespan",
    "A_core_direct_lifespan",
    "B_disease_model_survival",
    "C_secondary_molecular",
    "C_secondary_contextual",
)


def _strip_doc_and_comments(src: str) -> str:
    """Remove triple-quoted docstrings + `# ...` line comments so the
    universality scan only inspects executing logic, not documentation.
    Conservative: keeps anything inside single/double-quoted strings on
    a code line (those ARE logic — string-literal arguments)."""
    no_triple = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)
    lines = []
    for line in no_triple.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Strip trailing inline comment but keep code before it. Naive
        # split is fine here — we just want to drop `# foo` annotations.
        code_part = re.split(r"(?<!['\"])#", line, maxsplit=1)[0]
        lines.append(code_part)
    return "\n".join(lines)


@pytest.mark.xfail(
    reason=(
        "P1 #1 from Sprint-12.8.5 external audit: agent/include_contract.py "
        "and agent/placeholder_resolver.py hardcode lifespan-shaped lane keys "
        "(A_core_direct_lifespan, B_disease_model_survival, C_secondary_*). "
        "A topic with a non-lifespan endpoint still inherits these key names "
        "in its receipt schema. Refactor to generic A_primary / B_sensitivity "
        "/ C_secondary is a follow-up sprint — this test will flip from xfail "
        "to passing once the rename + back-compat shim lands."
    ),
    strict=True,
)
def test_agent_logic_has_no_lifespan_lane_keys() -> None:
    """Lane keys in `agent/` source must NOT name a specific endpoint.

    `A_core_direct_lifespan` etc. embed "lifespan" into the receipt
    schema. A non-lifespan topic (climate, materials, A/B test) still
    inherits these names. Fix: rename to `A_primary` /
    `B_sensitivity` / `C_secondary` (lane FUNCTION, not lane CONTENT).
    """
    leaks: list[tuple[str, str]] = []
    for py in _AGENT_DIR.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        src = _strip_doc_and_comments(py.read_text(encoding="utf-8"))
        for key in _LIFESPAN_LANE_KEYS:
            if key in src:
                leaks.append((str(py.relative_to(_AGENT_DIR.parent)), key))
    assert not leaks, (
        f"lifespan-shaped lane keys in agent/ logic: {leaks!r}. "
        "These should be generic A_primary / B_sensitivity / C_secondary."
    )
