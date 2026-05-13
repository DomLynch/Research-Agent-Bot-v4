"""Sprint 21 — universal risk-of-bias adapter (SYRCLE / Cochrane / ROBINS-I).

Framework definitions are canonical (live in tooling guides published
by the framework authors) and topic-agnostic, so they live in code as
typed tuples. Per-study judgments are operator-supplied via
`runs/<paper-dir>/risk_of_bias_assessments.json`; the loader returns
typed records and a renderer emits a markdown summary table the
supplement/back-matter can inline.

Universal: no biomedical literals; framework selection is via
TopicPack.risk_of_bias_framework (or the assessments JSON itself).
The framework registry is keyed by canonical name, not by domain.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_JUDGMENTS: frozenset[str] = frozenset({
    "low", "some-concerns", "high", "unclear",
})


@dataclass(frozen=True, slots=True)
class RobItem:
    item_id: str
    text: str


@dataclass(frozen=True, slots=True)
class RobFramework:
    name: str
    items: tuple[RobItem, ...]


# Canonical item lists. SYRCLE = animal-RoB (10 items, Hooijmans 2014).
# Cochrane-RoB-2 = randomized trials (5 domains, Sterne 2019). ROBINS-I
# = non-randomized intervention studies (7 domains, Sterne 2016). All
# items are framework-authoritative wording; no domain literal.
SYRCLE = RobFramework("SYRCLE", (
    RobItem("sequence_generation", "Was the allocation sequence adequately generated?"),
    RobItem("baseline_characteristics", "Were baseline characteristics similar between groups?"),
    RobItem("allocation_concealment", "Was allocation adequately concealed?"),
    RobItem("random_housing", "Were animals randomly housed during the experiment?"),
    RobItem("blinding_caregivers", "Were caregivers and/or investigators blinded?"),
    RobItem("random_outcome", "Were animals selected at random for outcome assessment?"),
    RobItem("blinding_assessor", "Was the outcome assessor blinded?"),
    RobItem("incomplete_outcome", "Were incomplete outcome data adequately addressed?"),
    RobItem("selective_reporting", "Are reports of the study free of selective outcome reporting?"),
    RobItem("other_sources", "Was the study apparently free of other problems that could result in high risk of bias?"),
))
COCHRANE_ROB2 = RobFramework("Cochrane-RoB-2", (
    RobItem("randomization", "Bias arising from the randomization process."),
    RobItem("deviations", "Bias due to deviations from intended interventions."),
    RobItem("missing_data", "Bias due to missing outcome data."),
    RobItem("measurement", "Bias in measurement of the outcome."),
    RobItem("reported_result", "Bias in selection of the reported result."),
))
ROBINS_I = RobFramework("ROBINS-I", (
    RobItem("confounding", "Bias due to confounding."),
    RobItem("selection", "Bias in selection of participants into the study."),
    RobItem("classification", "Bias in classification of interventions."),
    RobItem("deviations", "Bias due to deviations from intended interventions."),
    RobItem("missing_data", "Bias due to missing data."),
    RobItem("measurement", "Bias in measurement of outcomes."),
    RobItem("reported_result", "Bias in selection of the reported result."),
))
_REGISTRY: dict[str, RobFramework] = {
    f.name.casefold(): f for f in (SYRCLE, COCHRANE_ROB2, ROBINS_I)
}


def load_framework(name: str) -> RobFramework | None:
    return _REGISTRY.get(name.strip().casefold())


@dataclass(frozen=True, slots=True)
class RobAssessment:
    study_id: str
    framework: str
    judgments: tuple[tuple[str, str], ...]  # (item_id, judgment) pairs
    notes: tuple[tuple[str, str], ...]      # (item_id, note) pairs


def _parse_assessment(raw: dict[str, object]) -> RobAssessment | None:
    sid = str(raw.get("study_id") or "").strip()
    fw = str(raw.get("framework") or "").strip()
    if not sid or not load_framework(fw):
        return None
    judgments_raw = raw.get("judgments") if isinstance(raw.get("judgments"), dict) else {}
    notes_raw = raw.get("notes") if isinstance(raw.get("notes"), dict) else {}
    if not isinstance(judgments_raw, dict):
        judgments_raw = {}
    if not isinstance(notes_raw, dict):
        notes_raw = {}
    judgments = tuple(
        (str(k), str(v)) for k, v in judgments_raw.items()
        if str(v).strip() in _JUDGMENTS
    )
    notes = tuple((str(k), str(v)) for k, v in notes_raw.items())
    return RobAssessment(
        study_id=sid, framework=fw, judgments=judgments, notes=notes,
    )


def load_assessments(run_dir: Path) -> tuple[RobAssessment, ...]:
    """Load `risk_of_bias_assessments.json` if present; tolerate missing
    file / malformed JSON / unknown frameworks (those entries dropped)."""
    path = run_dir / "risk_of_bias_assessments.json"
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw_list = data.get("assessments") if isinstance(data, dict) else None
    if not isinstance(raw_list, list):
        return ()
    parsed = [
        a for r in raw_list if isinstance(r, dict)
        for a in (_parse_assessment(r),) if a is not None
    ]
    return tuple(parsed)


def render_summary_table(
    assessments: tuple[RobAssessment, ...], framework: RobFramework,
) -> str:
    """Markdown table: studies as rows, framework items as columns,
    judgments as cells. Empty input returns an empty string so the
    caller (supplement) can guard cleanly."""
    rows = [a for a in assessments if a.framework.casefold() == framework.name.casefold()]
    if not rows:
        return ""
    header = "| Study | " + " | ".join(it.item_id for it in framework.items) + " |"
    sep = "|---|" + "|".join("---" for _ in framework.items) + "|"
    lines = [f"### Risk of Bias ({framework.name})", "", header, sep]
    for a in rows:
        cell_by_id = dict(a.judgments)
        lines.append(
            f"| {a.study_id} | "
            + " | ".join(cell_by_id.get(it.item_id, "—") for it in framework.items)
            + " |"
        )
    return "\n".join(lines) + "\n"
