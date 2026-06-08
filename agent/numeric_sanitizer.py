"""Sprint 64 — numeric-artifact detector.

The DB's Tier-2 extraction sometimes parses identifier embeds as
numeric values:
    '14,15-EET inhibited autophagy'     -> numeric_value = 1415
    'Ser555 phosphorylation'             -> numeric_value = 555
    'UOK 257-1 cell line'                -> numeric_value = 257
These are not effect sizes. They are parts of chemical formulas,
amino-acid positions, cell-line identifiers, or hyphenated tokens
the extractor mishandled. Including them as 'top findings' is the
single biggest source of garbage in the Researka Top 5 output.

This module provides one universal syntactic detector:
    is_numeric_artifact(value, canonical_phrase) -> bool

Rules — purely on character context around the value in the phrase:
    1. value adjacent to an alphanumeric character (Ser555, COX2)
    2. value preceded or followed by hyphenated digits (14,15-EET)
    3. value embedded in identifier-suffix pattern (257-1)

Universal: no biomedical literals. The same detector flags any
domain's identifier-embed style (e.g. 'Article 5(b)' policy refs).
"""
from __future__ import annotations

import re
from typing import Any

# Walk-stop chars: whitespace + sentence-end punctuation. Stops the
# "look for adjacent letters" walk. Brackets/parens are NOT stops —
# Ser(555) and Ser[555] are still identifier embeds.
_WALK_STOP = frozenset(" \t\n\r;:!?\"'")
# Pure-numeric range or comma-list (1-5, 14,15, 1-2-3)
_PURE_NUMERIC_RANGE = re.compile(r"^\d+(?:[-,]\d+)+$")

# Sprint 69 — extended walk-stop rules for space-separated patterns
# the rule-1 walk misses.
#
# Rule 3: capitalized 1-4 letter prefix immediately before the value
# with ONE space or hyphen between. Catches cell-line / compound
# codes that rule 1 misses because the space breaks the token
# (Cal 27, HCT 116, T47 D). Lowercased English words ("over", "by",
# "in") do not match because the leading char must be uppercase.
_ID_PREFIX_SPACE = re.compile(r"[A-Z][A-Za-z0-9]{0,3}[-\s]$")
# Rule 4: bare time-unit suffix when value is immediately followed
# by a time token (72 h, 24 hours, 30 min, 8 days). Catches the
# duration-treated-as-effect case when the extractor leaves the
# units field empty. Universal — any domain.
_TIME_SUFFIX = re.compile(
    r"^\s+(?:s|sec|secs|seconds?|min|mins|minutes?|h|hr|hrs|hours?|"
    r"d|days?|wk|wks|weeks?|mo|months?|y|yr|yrs|years?)\b",
    re.IGNORECASE,
)
# Rule-3 guard: when a measurement unit immediately follows the
# value, the value is a real effect — do NOT flag as identifier.
# Catches "SIRT2 0.25 µM" (IC50) where the gene name precedes the
# concentration but the concentration is the actual finding.
# Universal: %, masses, concentrations, fold-changes, temperature.
_UNIT_FOLLOWS = re.compile(
    r"^\s*(?:%|°[CF]|degrees?\b|"
    r"[mµμnkp]?[gmlL]\b|"
    r"[mµμnp][MmLl]\b|"
    r"\$?\\times\$?|\u00d7|"
    r"fold\b|x\b|times?\b|"
    r"iu\b|U\b)",
    re.IGNORECASE,
)


def _format_value(v: Any) -> str | None:
    """Render value as it would appear in a phrase."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return f"{int(v)}" if v == int(v) else f"{v:g}"
    return None


def _walk(phrase: str, start: int, end: int) -> tuple[str, bool]:
    """Walk outward from [start:end] until whitespace/sentence-stop.
    Returns (token, has_adjacent_letter). One pass, both signals."""
    has_letter = False
    s = start
    while s > 0 and phrase[s - 1] not in _WALK_STOP:
        if phrase[s - 1].isalpha():
            has_letter = True
        s -= 1
    e = end
    while e < len(phrase) and phrase[e] not in _WALK_STOP:
        if phrase[e].isalpha():
            has_letter = True
        e += 1
    return phrase[s:e], has_letter


def is_numeric_artifact(value: Any, phrase: str) -> bool:
    """True when the value is likely an identifier embed, not an effect.
    Three rules: (0) value absent from phrase (concat parse artifact),
    (1) letter adjacent w/o whitespace (Ser(555), ABT-263, 14,15-EET),
    (2) token is pure-numeric range/list (257-1, 1-5)."""
    if not phrase:
        return False
    val_str = _format_value(value)
    if not val_str:
        return False
    matches = list(re.finditer(re.escape(val_str), phrase))
    if not matches:
        return True
    for match in matches:
        token, has_letter = _walk(phrase, match.start(), match.end())
        if token.isdigit() and token != val_str:
            continue  # value is a fragment of a longer pure number
        if has_letter:
            return True
        if _PURE_NUMERIC_RANGE.match(token.strip("()[]{}")):
            return True
        # Sprint 69 — space-separated identifier / inline time suffix
        before = phrase[max(0, match.start() - 5):match.start()]
        after = phrase[match.end():match.end() + 12]
        if _TIME_SUFFIX.match(after):
            return True
        # Identifier prefix only when no unit follows the value; a
        # trailing unit (µM, %, mg, fold) means the value is a real
        # measurement even if a capitalized prefix sits before it.
        if (_ID_PREFIX_SPACE.search(before)
                and not _UNIT_FOLLOWS.match(after)):
            return True
    return False


def filter_artifacts(
    facts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split facts into (kept, filtered). Universal — operates over
    the fact dict's numeric_value + canonical_phrase only."""
    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        if is_numeric_artifact(
            f.get("numeric_value"),
            str(f.get("canonical_phrase") or ""),
        ):
            filtered.append(f)
        else:
            kept.append(f)
    return kept, filtered
