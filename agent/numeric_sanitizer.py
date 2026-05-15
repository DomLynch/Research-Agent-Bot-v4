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

# Whitespace + sentence-punctuation token boundaries. Chars INSIDE
# a token: alphanumerics, hyphens, commas, dots, slashes.
_TOKEN_BREAK = frozenset(" \t\n\r;:!?()[]{}\"'")
# Pure-numeric range or comma-list (1-5, 14,15, 1-2-3)
_PURE_NUMERIC_RANGE = re.compile(r"^\d+(?:[-,]\d+)+$")


def _format_value(v: Any) -> str | None:
    """Render value as it would appear in a phrase."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return f"{int(v)}" if v == int(v) else f"{v:g}"
    return None


def _word_containing(phrase: str, start: int, end: int) -> str:
    """Return the whitespace + sentence-punctuation-bounded word
    surrounding the [start:end] slice."""
    s = start
    while s > 0 and phrase[s - 1] not in _TOKEN_BREAK:
        s -= 1
    e = end
    while e < len(phrase) and phrase[e] not in _TOKEN_BREAK:
        e += 1
    return phrase[s:e]


def is_numeric_artifact(value: Any, phrase: str) -> bool:
    """True when the value is likely an identifier embed, not an effect.
    Universal: shape-based, no domain literals. Two rules:
      1. Word containing the value has any letter (Ser555, ABT-263)
      2. Word is a pure-numeric range/list (257-1, 14,15, 1-5)
    """
    if not phrase:
        return False
    val_str = _format_value(value)
    if not val_str:
        return False
    for match in re.finditer(re.escape(val_str), phrase):
        word = _word_containing(phrase, match.start(), match.end())
        # Skip when the match is a digit-fragment of a longer pure-digit
        # number (e.g. value=55 matching inside "5500"); not an artifact,
        # just a regex-substring quirk.
        if word.isdigit() and word != val_str:
            continue
        if any(c.isalpha() for c in word):
            return True
        if _PURE_NUMERIC_RANGE.match(word):
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
