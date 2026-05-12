"""Sprint 11.6 — ARIS-pattern skill loader tests.

Cover:
  - load_skill strips YAML frontmatter and returns the body verbatim
  - missing skill files raise FileNotFoundError (never silent fallback)
  - SYSTEM_WRITER is now sourced from topic_packs/skills/system_writer.md
    and content invariants from the original Python literal are preserved
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.prompts import SYSTEM_WRITER
from agent.skill_loader import load_skill


def test_load_skill_returns_body_without_frontmatter() -> None:
    body = load_skill("system_writer")
    assert "AAA-grade research-paper prose" in body
    # Frontmatter must not appear in the loaded body.
    assert "---" not in body.split("\n", 1)[0]
    assert "name: system_writer" not in body


def test_load_skill_missing_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="skill not found"):
        load_skill("definitely-not-a-real-skill-name-xyz")


def test_system_writer_constant_preserves_original_invariants() -> None:
    """SYSTEM_WRITER must still carry every hard rule from the original
    Python literal so downstream prompts behave identically."""
    invariants = (
        "AAA-grade research-paper prose",
        "LENGTH DISCIPLINE",
        "HOSTAGE-TO-FACT PHRASING",
        "FUTURE OUTCOMES",
        "[CIT:",
        "EVIDENCE SLOTS ARE MANDATORY",
        "PRE-RESULTS MANUSCRIPT",
        "NEVER erase prior literature",
        "FORBIDDEN NOVELTY PHRASES",
        "no synthesis has",
        "no comprehensive review",
        "anaphoric reference sentences",
        "scaffold language",
        "UNIVERSAL: this prompt must produce",
    )
    for needle in invariants:
        assert needle in SYSTEM_WRITER, f"missing invariant: {needle!r}"


def test_load_skill_caches_results() -> None:
    """load_skill is lru_cached; repeated calls return the same string
    object without re-reading the file."""
    a = load_skill("system_writer")
    b = load_skill("system_writer")
    assert a is b


def test_all_seven_writer_section_skills_exist_and_carry_their_invariants() -> None:
    """Sprint 11.6 + 12.1: every writer-section .md skill that
    agent/prompts.py loads must exist and preserve the content
    invariants from the original Python literals."""
    cases: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("writer_section_methods", (
            "800-1,200 words", "SEARCH STRATEGY", "TENSION-MATRIX CONSTRUCTION",
            "FORBIDDEN OVERCLAIMS", "[CIT:", "[PLACEHOLDER:databases]",
        )),
        ("writer_section_title", (
            "at most 15 words", "moderator-specific conclusion",
            "pre-registered",
        )),
        ("writer_section_abstract", (
            "250-300 words", "[N_SCREENED]", "[N_ACCEPTED]", "[K_STUDIES]",
            "FORBIDDEN: do NOT say 'pre-registered'",
        )),
        ("writer_section_introduction", (
            "HARD FLOOR: 800 words", "HARD CEILING: 1,000 words",
            "prior synthesis landscape",
        )),
        ("writer_section_discussion", (
            "600-900 words", "FORBIDDEN OVERCLAIMS",
            "[CIT:<key>|prior-meta-analysis]",
            "[CIT:<key>|mechanism-review]",
        )),
        ("writer_section_limitations", (
            "200-400 words", "metric-family discipline",
            "[PACKET:sentinel_recall]",
        )),
        ("writer_section_conclusion", (
            "120-180 words", "calibrated by k",
        )),
    )
    for name, invariants in cases:
        body = load_skill(name)
        for needle in invariants:
            assert needle in body, f"{name}: missing invariant {needle!r}"
