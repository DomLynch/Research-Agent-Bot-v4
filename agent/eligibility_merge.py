"""Pass-3 deterministic eligibility merge. LLM proposes; code disposes.

Merge rules:
  include  : triage != exclude_likely AND proposal.include AND
             confidence >= CONF_FLOOR AND every mandatory field true
  exclude  : triage == exclude_likely OR proposal.exclude w/ confidence
             >= CONF_FLOOR OR rapalog-only / combination-only flag fires
  unclear  : otherwise (rule/judge conflict, low confidence, missing evidence)

Output is a single `EligibilityReceipt` with full audit trail.
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


def _every_mandatory_true(fields: dict[str, bool]) -> bool:
    return all(bool(fields.get(k, False)) for k in MANDATORY_KEYS)


def adjudicate(
    triage: EligibilityTriage,
    proposal: EligibilityProposal,
    parsed: ParsedFullText,
) -> EligibilityReceipt:
    # Symmetric OR-merge for ALL mandatory inclusion fields: if EITHER the
    # deterministic Pass-1 rule OR the Pass-2 judge finds positive evidence,
    # treat the field as satisfied. Reason: Gemma was rejecting Harrison-2009
    # because the Nature abstract opens with "mammalian species" framing;
    # the judge set species_match=False even though the title is "...in mice"
    # and the rule had already matched. OR-merge respects the rule's title
    # match without letting the judge whitewash it.
    merged: dict[str, bool] = {}
    all_keys = set(triage.mandatory_fields) | set(proposal.eligibility_fields)
    for k in all_keys:
        merged[k] = bool(
            triage.mandatory_fields.get(k, False)
            or proposal.eligibility_fields.get(k, False)
        )
    # Hard excluders also OR-merge (preserves existing behavior).
    rapalog = bool(merged.get("rapalog_only_intervention", False))
    combo_only = bool(merged.get("combination_only_no_isolated_arm", False))
    judge_reviewer = JUDGE_REVIEWER if not proposal.parse_error else RULE_REVIEWER

    if triage.label == "exclude_likely":
        decision, reviewer = "exclude", RULE_REVIEWER
        reason = "Pass-1 hard excluder: " + (triage.reasons[0] if triage.reasons else "see triage")
    elif rapalog or combo_only:
        decision, reviewer = "exclude", judge_reviewer
        reason = "merged checklist excluder: " + (
            "rapalog-only intervention" if rapalog
            else "combination-only without isolated intervention arm"
        )
    elif proposal.decision == "exclude" and proposal.confidence >= CONF_FLOOR:
        decision, reviewer = "exclude", JUDGE_REVIEWER
        reason = (
            f"judge excluded (conf {proposal.confidence:.2f}): "
            + (proposal.reasons[0] if proposal.reasons else "(no reason given)")
        )
    elif (
        proposal.decision == "include"
        and proposal.confidence >= CONF_FLOOR
        and _every_mandatory_true(merged)
        and not proposal.parse_error
    ):
        decision, reviewer = "include", JUDGE_REVIEWER
        reason = f"judge included (conf {proposal.confidence:.2f}); mandatory fields confirmed"
    else:
        decision, reviewer = "unclear", judge_reviewer
        bits: list[str] = []
        if proposal.parse_error:
            bits.append(f"proposal parse error: {proposal.parse_error}")
        if proposal.confidence < CONF_FLOOR:
            bits.append(f"low judge confidence {proposal.confidence:.2f}")
        missing = [k for k in MANDATORY_KEYS if not merged.get(k, False)]
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
        mandatory_fields=MappingProxyType(merged),
        evidence_quotes=proposal.evidence_quotes,
        judge_model=proposal.model,
        rule_decision=triage.label,
        source_text_hash=parsed.sha256,
        timestamp_utc=_now_utc(),
    )
