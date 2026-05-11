"""Pass-3 deterministic eligibility merge.

`LLM proposes -> code disposes.`

Takes the Pass-1 `EligibilityTriage` + Pass-2 `EligibilityProposal` and
applies the merge rules to produce a final `EligibilityReceipt` with a
full audit trail.

Merge rules (user-specified):

  include if:
    triage.label != "exclude_likely"
    AND proposal.decision == "include"
    AND proposal.confidence >= CONF_FLOOR (default 0.75)
    AND every mandatory field in proposal.eligibility_fields is True

  exclude if:
    triage.label == "exclude_likely"  (hard rule excluder fired)
    OR proposal.decision == "exclude" with confidence >= CONF_FLOOR
    OR rapalog_only_intervention flag is True in either source
    OR combination_only_no_isolated_arm flag is True in the proposal

  unclear otherwise (rule/judge conflict, low confidence, missing evidence)

Universal: no domain literals. Merge logic only reads the structured
`EligibilityTriage` and `EligibilityProposal` records.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

from agent.eligibility_judge import EligibilityProposal
from agent.eligibility_rules import MANDATORY_KEYS, EligibilityTriage
from agent.full_text_parse import ParsedFullText
from agent.screening import EligibilityReceipt

CONF_FLOOR = 0.75
JUDGE_REVIEWER = "llm-judge"
RULE_REVIEWER = "rule-triage"


def _now_utc() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _every_mandatory_true(fields: dict[str, bool] | object) -> bool:
    if not isinstance(fields, dict):
        return False
    return all(bool(fields.get(k, False)) for k in MANDATORY_KEYS)


def adjudicate(
    triage: EligibilityTriage,
    proposal: EligibilityProposal,
    parsed: ParsedFullText,
) -> EligibilityReceipt:
    """Apply merge rules; return the final receipt with full audit trail."""
    merged_fields: dict[str, bool] = dict(triage.mandatory_fields)
    for k, v in proposal.eligibility_fields.items():
        # LLM verdict on a field beats the triage scan (more context).
        merged_fields[k] = bool(v)

    rapalog = bool(merged_fields.get("rapalog_only_intervention", False))
    combination_only = bool(
        merged_fields.get("combination_only_no_isolated_arm", False)
    )

    if triage.label == "exclude_likely":
        decision = "exclude"
        reviewer = RULE_REVIEWER
        reason = (
            "Pass-1 hard excluder fired: "
            + (triage.reasons[0] if triage.reasons else "see triage record")
        )
    elif rapalog or combination_only:
        decision = "exclude"
        reviewer = JUDGE_REVIEWER if proposal.parse_error == "" else RULE_REVIEWER
        flag = (
            "rapalog-only intervention" if rapalog
            else "combination-only without isolated intervention arm"
        )
        reason = f"hard-rule excluder via merged checklist: {flag}"
    elif (
        proposal.decision == "exclude"
        and proposal.confidence >= CONF_FLOOR
    ):
        decision = "exclude"
        reviewer = JUDGE_REVIEWER
        reason = (
            f"judge excluded with confidence {proposal.confidence:.2f}: "
            + (proposal.reasons[0] if proposal.reasons else "(no reason given)")
        )
    elif (
        proposal.decision == "include"
        and proposal.confidence >= CONF_FLOOR
        and _every_mandatory_true(merged_fields)
        and proposal.parse_error == ""
    ):
        decision = "include"
        reviewer = JUDGE_REVIEWER
        reason = (
            f"judge included with confidence {proposal.confidence:.2f}; "
            "all mandatory fields confirmed"
        )
    else:
        decision = "unclear"
        reviewer = JUDGE_REVIEWER if proposal.parse_error == "" else RULE_REVIEWER
        bits: list[str] = []
        if proposal.parse_error:
            bits.append(f"proposal parse error: {proposal.parse_error}")
        if proposal.confidence < CONF_FLOOR:
            bits.append(f"low judge confidence {proposal.confidence:.2f}")
        missing = [k for k in MANDATORY_KEYS if not merged_fields.get(k, False)]
        if missing:
            bits.append("missing mandatory: " + ", ".join(missing))
        if not bits:
            bits.append("rule/judge conflict; manual review required")
        reason = "; ".join(bits)

    return EligibilityReceipt(
        study_id=triage.study_id,
        decision=decision,  # type: ignore[arg-type]
        reason=reason,
        reviewer=reviewer,
        confidence=proposal.confidence,
        mandatory_fields=MappingProxyType(merged_fields),
        evidence_quotes=proposal.evidence_quotes,
        judge_model=proposal.model,
        rule_decision=triage.label,
        source_text_hash=parsed.sha256,
        timestamp_utc=_now_utc(),
    )
