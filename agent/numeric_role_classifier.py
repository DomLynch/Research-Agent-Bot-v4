"""Sprint 59 (Evidence Opportunities Gate) — numeric role classifier.

Given a fact's numeric_value, units string, and canonical_phrase
context, return one of:
  effect_size | fold_change | correlation | p_value | dose |
  concentration | duration | sample_size | regimen | unknown

Universal: rules are unit-cluster + verb/preposition-driven; no
biomedical domain literals. Used by fact_lanes to demote facts where
the numeric is a regimen / timepoint / dose pretending to be an
effect-size finding (e.g. '66 weeks' or '70% CR conditions').
"""
from __future__ import annotations

import re

# Time units → duration (covers both treatment-length and timepoint)
_TIME_UNITS = frozenset([
    "day", "days", "hour", "hours", "min", "minute", "minutes",
    "week", "weeks", "month", "months", "year", "years",
])

# Dose-shape mass/quantity units
_DOSE_UNITS = frozenset([
    "mg/kg", "mg/kg/day", "mg/kg/d", "ppm", "mg", "kg", "µg", "μg",
    "ug", "ng", "g", "mg/ml", "iu", "u",
])

# In-vitro concentration units
_CONC_UNITS = frozenset([
    "mm", "µm", "μm", "nm", "pm", "ng/ml", "µg/ml", "μg/ml",
    "mol/l", "mmol/l", "μmol/l", "nmol/l",
])

# Regimen markers — sentence describes a treatment protocol, not an outcome
_REGIMEN_MARKERS = frozenset([
    "restriction", "restricted", "feeding", "feed", "diet",
    "conditions", "regimen", "of ad lib", "of ad libitum", "protocol",
])

# Sample-size markers — verbose forms of n=
_SAMPLE_SIZE_MARKERS = ("n=", "n =", "participants", "subjects",
                         "patients", "volunteers")

# Paired-comparison markers (Sprint 67) — universal stats syntax
# indicating a measured effect-style comparison ('1.33 vs 2.50' or
# '1.71 ± 0.26 vs 2.35 ± 0.25'). When a unitless positive number
# appears alongside these markers, treat it as effect_size — not
# unknown. Fixes the auditor's Apc(1638N/+) binding case.
_PAIRED_COMP_MARKERS = (" vs ", " vs. ", " versus ", "±", " ± ")

# Ratio units (Sprint 68) — universal epi statistics. OR, HR, RR,
# AOR, AHR, IRR, ROR, SMR, IPR. When `units` field is one of these,
# the value is an effect-size ratio. Auditor: OR=15.5 retrospective
# vs OR=1.58 prospective was being demoted to 'unknown'.
_RATIO_UNITS = frozenset([
    "or", "hr", "rr", "aor", "ahr", "irr", "ror", "smr", "ipr",
])

# P-value prefix markers (Sprint 68) — when ANY of these appear
# immediately before the value in the phrase, override paired-
# comparison and call it p_value regardless of magnitude. Auditor:
# 'p = 2.98e-9 for highest vs lowest quintile' was promoted to
# effect_size because 'vs' fired before p-prefix was checked.
_PVALUE_PREFIX_MARKERS = ("p=", "p =", "p<", "p <", "p<=", "p <=")

# Roles that actually constitute a research finding
_REAL_FINDING_ROLES = frozenset(["effect_size", "fold_change", "correlation"])


def classify_numeric_role(
    value: float | None, units: str, context: str,
) -> str:
    """Return the role of a numeric token. Universal."""
    u = (units or "").lower().strip()
    ctx = (context or "").lower()

    if u in _TIME_UNITS:
        return "duration"
    if u in _DOSE_UNITS:
        return "dose"
    if u in _CONC_UNITS:
        return "concentration"
    if u in _RATIO_UNITS:
        return "effect_size"
    if u == "%":
        return "regimen" if any(m in ctx for m in _REGIMEN_MARKERS) \
            else "effect_size"
    if value is not None and "fold" in ctx and u in ("", "x"):
        return "fold_change"
    if value is not None and -1.0 <= value <= 1.0 and u == "":
        if any(m in ctx for m in ("correlation", "r=", "r =")):
            return "correlation"
        if 0.0 <= value <= 1.0 and (
            "p=" in ctx or "p =" in ctx or "p<" in ctx or "p <" in ctx
        ):
            return "p_value"
    if (value is not None and value == int(value)
            and any(m in ctx for m in _SAMPLE_SIZE_MARKERS)):
        return "sample_size"
    # P-value prefix check (Sprint 68): a p-prefix counts ONLY when
    # IMMEDIATELY adjacent to the value being classified (within 5
    # chars before the match), not anywhere in the phrase. Prevents
    # the Apc(1638N/+) effect-size case 'macroadenoma count was 1.33
    # vs 2.50 (P<0.01)' from being mis-classified as p_value because
    # the P< marker applies to a different stat in the same phrase.
    if value is not None:
        val_str = (f"{int(value)}" if value == int(value)
                   else f"{value:g}")
        for m in re.finditer(re.escape(val_str), ctx):
            before = ctx[max(0, m.start() - 5):m.start()]
            if any(p in before for p in _PVALUE_PREFIX_MARKERS):
                return "p_value"
    # Paired-comparison fallback (Sprint 67): a unitless positive
    # number appearing alongside 'vs' / 'versus' / '±' is an effect-
    # style comparison (e.g. macroadenoma count 1.33 vs 2.50).
    if (value is not None and value > 0 and u == ""
            and any(m in ctx for m in _PAIRED_COMP_MARKERS)):
        return "effect_size"
    return "unknown"


def is_real_finding(role: str) -> bool:
    """Only effect_size / fold_change / correlation count as findings."""
    return role in _REAL_FINDING_ROLES
