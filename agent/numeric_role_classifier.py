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
import tomllib
from functools import lru_cache
from pathlib import Path

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

# Sprint 72 — marker vocabulary lives in topic_packs/role_markers.toml.
# Code is now pure logic; the universal-English research vocabulary
# is data. The auditor's strictest reading of "no hardcoding" treats
# any in-code word list as domain-leaning; moving them out closes
# that contract. See _load_role_markers() below.
_ROLE_MARKERS_TOML = (Path(__file__).resolve().parent.parent
                      / "topic_packs" / "role_markers.toml")


@lru_cache(maxsize=1)
def _load_role_markers() -> dict[str, frozenset[str]]:
    """Load universal numeric-role markers from data. Cached per-
    process. Degrades to empty sets on missing/malformed file
    (classifier still works; just won't promote regimen / sample
    size cases). No domain literals in code — see role_markers.toml
    header for the contract."""
    try:
        data = tomllib.loads(
            _ROLE_MARKERS_TOML.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    if not isinstance(data, dict):
        return {"regimen": frozenset(), "sample_size": frozenset()}
    return {
        "regimen": frozenset(
            str(m).lower() for m in (data.get("regimen") or [])),
        "sample_size": frozenset(
            str(m).lower() for m in (data.get("sample_size") or [])),
    }

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
_EFFECT_ESTIMATE_RE = re.compile(
    r"\b(?:wmd|smd|md)\s*[:=]|"
    r"\b(?:weighted|standardized)\s+mean\s+difference\b|"
    r"\bmean\s+difference\b"
)
_MULTIPLICATIVE_AFTER_RE = re.compile(
    r"^\s*(?:\$?\\times\$?|\u00d7|x\b|times?\b|fold\b)",
    re.IGNORECASE,
)

# Roles that actually constitute a research finding
_REAL_FINDING_ROLES = frozenset(["effect_size", "fold_change", "correlation"])


def _value_matches(value: float) -> list[str]:
    base = f"{int(value)}" if value == int(value) else f"{value:g}"
    return [base] if value >= 0 else [base, base.lstrip("-")]


def _has_pvalue_prefix(value: float, ctx: str) -> bool:
    for val_str in _value_matches(value):
        for m in re.finditer(re.escape(val_str), ctx):
            before = ctx[max(0, m.start() - 5):m.start()]
            if any(p in before for p in _PVALUE_PREFIX_MARKERS):
                return True
    return False


def _has_effect_estimate_marker(value: float, ctx: str) -> bool:
    for val_str in _value_matches(value):
        for m in re.finditer(re.escape(val_str), ctx):
            window = ctx[max(0, m.start() - 45):m.end() + 25]
            if _EFFECT_ESTIMATE_RE.search(window):
                return True
    return False


def _has_multiplicative_marker(value: float, ctx: str) -> bool:
    for val_str in _value_matches(value):
        for m in re.finditer(re.escape(val_str), ctx):
            after = ctx[m.end():m.end() + 16]
            if _MULTIPLICATIVE_AFTER_RE.match(after):
                return True
    return False


def classify_numeric_role(
    value: float | None, units: str, context: str,
) -> str:
    """Return the role of a numeric token. Universal."""
    u = (units or "").lower().strip()
    ctx = (context or "").lower()

    if value is not None and _has_pvalue_prefix(value, ctx):
        return "p_value"
    if value is not None and _has_effect_estimate_marker(value, ctx):
        return "effect_size"
    if value is not None and _has_multiplicative_marker(value, ctx):
        return "fold_change"
    if u in _TIME_UNITS:
        return "duration"
    if u in _DOSE_UNITS:
        return "dose"
    if u in _CONC_UNITS:
        return "concentration"
    if u in _RATIO_UNITS:
        return "effect_size"
    if u == "%":
        # Sprint 73 — regimen markers must sit IMMEDIATELY around the
        # value, not anywhere in the phrase. Window: 15 chars before
        # the value start, 25 chars after its end. Tuned so that
        # genuine modifiers ('40% caloric restriction', 'conditions
        # (70%)') still fire, but distant subjects ('Mediterranean
        # diet reduced LDL by 30%', 'training regimen improved
        # VO2max by 12%') no longer false-positive. Auditor's
        # locality fix.
        markers = _load_role_markers()["regimen"]
        if value is not None and markers:
            val_str = (f"{int(value)}" if value == int(value)
                       else f"{value:g}")
            for m in re.finditer(re.escape(val_str), ctx):
                window = ctx[max(0, m.start() - 15):m.end() + 25]
                if any(marker in window for marker in markers):
                    return "regimen"
        return "effect_size"
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
            and any(m in ctx
                    for m in _load_role_markers()["sample_size"])):
        return "sample_size"
    # P-value prefix check (Sprint 68): a p-prefix counts ONLY when
    # IMMEDIATELY adjacent to the value being classified (within 5
    # chars before the match), not anywhere in the phrase. Prevents
    # the Apc(1638N/+) effect-size case 'macroadenoma count was 1.33
    # vs 2.50 (P<0.01)' from being mis-classified as p_value because
    # the P< marker applies to a different stat in the same phrase.
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
