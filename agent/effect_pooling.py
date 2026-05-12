"""Sprint 8 - effect-size pooling.

Takes contract-passing ExtractionReceipts and converts each to an
ExtractedOutcome + EffectSizeRecord pair so the existing
results_compiler.compile_primary_effect can pool them via inverse
variance.

Two metrics are supported in v0:

  1. log_hazard_ratio  (when hazard_ratio + CI bounds are reported)
       estimate = ln(HR)
       se       = (ln(HR_hi) - ln(HR_lo)) / (2 * 1.96)

  2. log_median_ratio  (when treated/control medians + sample sizes are
                        reported but no HR)
       estimate = ln(treated_value / control_value)
       se       ≈ sqrt(1/treated_n + 1/control_n)   [normal approx]

Receipts that report neither bucket cannot be pooled honestly and are
omitted (returned as None). The caller documents this as an extraction
failure for the receipt; the receipt itself stays in the bundle.

Universal: no biomedical literals; the metric vocabulary comes from
agent.topic_pack.eligibility_endpoint_terms via the contract gate.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from types import MappingProxyType

from agent.effect_extraction import ExtractionReceipt, validate_extraction
from agent.effect_sizes import EffectSizeRecord, ExtractedOutcome
from agent.topic_pack import TopicPack

_Z_95 = 1.959963984540054  # two-sided 95% normal critical value


def compute_effect(
    receipt: ExtractionReceipt, pack: TopicPack,
) -> tuple[ExtractedOutcome, EffectSizeRecord] | None:
    """Return (outcome, effect) for a contract-passing receipt, or None
    when the numerics do not let us compute a pooling-ready effect."""
    if not validate_extraction(receipt, pack).passes:
        return None

    outcome_id = f"{receipt.study_id}.primary"

    hr = receipt.hazard_ratio
    hr_lo = receipt.hazard_ratio_ci_low
    hr_hi = receipt.hazard_ratio_ci_high
    if hr is not None and hr > 0 and hr_lo and hr_hi and hr_lo > 0 and hr_hi > 0:
        log_hr = math.log(hr)
        se = (math.log(hr_hi) - math.log(hr_lo)) / (2 * _Z_95)
        ci_low = log_hr - _Z_95 * se
        ci_high = log_hr + _Z_95 * se
        outcome = ExtractedOutcome(
            study_id=receipt.study_id, outcome_id=outcome_id,
            metric_name="log_hazard_ratio",
            moderators=ExtractedOutcome.freeze_moderators(receipt.moderators),
            treated_value=hr, control_value=1.0,
            treated_n=receipt.treated_n, control_n=receipt.control_n,
            raw_unit="hazard_ratio",
        )
        return outcome, EffectSizeRecord(
            study_id=receipt.study_id, outcome_id=outcome_id,
            metric="log_hazard_ratio",
            estimate=log_hr, se=se, ci_low=ci_low, ci_high=ci_high,
            moderators=ExtractedOutcome.freeze_moderators(receipt.moderators),
        )

    t_val = receipt.treated_value
    c_val = receipt.control_value
    t_n = receipt.treated_n
    c_n = receipt.control_n
    if (t_val and c_val and t_val > 0 and c_val > 0
            and t_n and c_n and t_n > 0 and c_n > 0):
        log_ratio = math.log(t_val / c_val)
        se = math.sqrt(1.0 / t_n + 1.0 / c_n)
        ci_low = log_ratio - _Z_95 * se
        ci_high = log_ratio + _Z_95 * se
        # Metric family discipline: derive the pooled metric name from
        # the receipt's metric so 90th-percentile-lifespan values aren't
        # pooled with median-lifespan values under a single
        # "log_median_ratio" label. The pool compiler still groups by
        # modal metric name, so different families end up in different
        # buckets automatically.
        outcome_metric = _log_ratio_metric_name(receipt.metric)
        outcome = ExtractedOutcome(
            study_id=receipt.study_id, outcome_id=outcome_id,
            metric_name=outcome_metric,
            moderators=ExtractedOutcome.freeze_moderators(receipt.moderators),
            treated_value=t_val, control_value=c_val,
            treated_n=t_n, control_n=c_n,
            raw_unit=receipt.metric,
        )
        return outcome, EffectSizeRecord(
            study_id=receipt.study_id, outcome_id=outcome_id,
            metric=outcome_metric,
            estimate=log_ratio, se=se, ci_low=ci_low, ci_high=ci_high,
            moderators=ExtractedOutcome.freeze_moderators(receipt.moderators),
        )

    return None


def _log_ratio_metric_name(receipt_metric: str) -> str:
    """Map a receipt-level metric (e.g. "median_lifespan_days",
    "maximum_lifespan_90th_percentile_days") to a pooled log-ratio
    label that keeps incompatible measurement families apart.

    Universal: works off topic-pack vocabulary tokens (median, mean,
    max, 90th, percentile, survival, mortality, hazard). No biomedical
    literals beyond those neutral tokens; any topic that uses
    different measurement families would extend the token list here."""
    m = receipt_metric.casefold()
    if "90th" in m or "percentile" in m or "max" in m:
        return "log_max_or_percentile_lifespan_ratio"
    if "mean" in m and "median" not in m:
        return "log_mean_lifespan_ratio"
    return "log_median_ratio"


def compile_pool(
    receipts: Sequence[ExtractionReceipt], pack: TopicPack,
) -> tuple[tuple[ExtractedOutcome, ...], tuple[EffectSizeRecord, ...],
           tuple[str, ...]]:
    """Convert receipts to (outcomes, effects, skipped_ids).

    Receipts that fail validate_extraction or that lack numerics needed
    for pooling are recorded in skipped_ids but kept out of the pool."""
    outcomes: list[ExtractedOutcome] = []
    effects: list[EffectSizeRecord] = []
    skipped: list[str] = []
    metric_seen: set[str] = set()
    for r in receipts:
        pair = compute_effect(r, pack)
        if pair is None:
            skipped.append(r.study_id)
            continue
        outcome, effect = pair
        # Sprint 8 v0: mix metrics is meaningless under inverse-variance
        # because log_HR and log_median_ratio are different scales. Pool
        # only the modal metric; skip the rest with documented reason.
        metric_seen.add(effect.metric)
        outcomes.append(outcome)
        effects.append(effect)
    if len(metric_seen) > 1:
        # Pick the most common metric; demote the rest to skipped.
        from collections import Counter
        modal = Counter(e.metric for e in effects).most_common(1)[0][0]
        kept_outcomes = [o for o in outcomes if o.metric_name == modal]
        kept_effects = [e for e in effects if e.metric == modal]
        dropped = [e.study_id for e in effects if e.metric != modal]
        outcomes, effects = kept_outcomes, kept_effects
        skipped.extend(dropped)
    return tuple(outcomes), tuple(effects), tuple(skipped)


def freeze_moderators_dict(d: dict[str, str]) -> MappingProxyType[str, str]:
    """Convenience: same as ExtractedOutcome.freeze_moderators but
    exposed at module level so callers don't need to import the dataclass."""
    return MappingProxyType(dict(d))
