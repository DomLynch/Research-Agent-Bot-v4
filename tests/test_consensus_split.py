"""Tests for agent.consensus_split — deterministic, no LLM, no network."""
from __future__ import annotations

from agent.consensus_split import (
    Direction,
    classify_direction,
    partition,
    render_markdown,
)


def test_direction_lexicon() -> None:
    assert classify_direction("NAD was significantly increased") is Direction.UP
    assert classify_direction("all-cause mortality was reduced") is Direction.DOWN
    assert classify_direction("no significant difference vs placebo") is Direction.NULL
    assert classify_direction("did not increase lifespan") is Direction.NULL
    assert classify_direction("the protocol was double-blind") is Direction.UNCLEAR
    assert classify_direction("") is Direction.UNCLEAR


def test_negation_flips_to_null() -> None:
    # a negated effect verb is conservatively null, not the bare direction
    assert classify_direction("treatment failed to improve survival") is Direction.NULL
    assert classify_direction("no reduction in tumour size") is Direction.NULL


def test_consensus_when_clear_majority() -> None:
    facts = [
        {"fact_id": "a", "canonical_phrase": "marker increased"},
        {"fact_id": "b", "canonical_phrase": "marker rose"},
        {"fact_id": "c", "canonical_phrase": "marker was elevated"},
    ]
    r = partition(facts)
    assert r.consensus_direction == "up"
    assert r.has_disagreement is False
    assert r.total == 3


def test_disagreement_when_both_sides_have_support() -> None:
    facts = [
        {"fact_id": "1", "canonical_phrase": "lifespan increased"},
        {"fact_id": "2", "canonical_phrase": "lifespan was longer"},
        {"fact_id": "3", "canonical_phrase": "lifespan decreased"},
        {"fact_id": "4", "canonical_phrase": "lifespan was shorter"},
    ]
    r = partition(facts)
    assert r.has_disagreement is True
    assert r.consensus_direction is None  # 50/50 split -> no consensus
    assert "Conflicting" in r.summary


def test_strong_majority_with_minor_dissent_is_consensus_not_conflict() -> None:
    # 8 up vs 2 down: a 20% minority is minor dissent, not a conflict.
    # consensus and disagreement must be mutually exclusive.
    facts = (
        [{"fact_id": f"u{i}", "canonical_phrase": "marker increased"} for i in range(8)]
        + [{"fact_id": f"d{i}", "canonical_phrase": "marker decreased"} for i in range(2)]
    )
    r = partition(facts)
    assert r.consensus_direction == "up"
    assert r.has_disagreement is False
    assert "Conflicting" not in r.summary


def test_distant_negator_does_not_null_a_real_finding() -> None:
    # negator in a different clause must not flip the primary direction
    assert classify_direction(
        "increased mortality; the effect was not dose-dependent",
    ) is Direction.UP


def test_open_questions_capture_unclear_and_sparse_null() -> None:
    facts = [
        {"fact_id": "x", "canonical_phrase": "the cohort was randomised"},  # unclear
        {"fact_id": "y", "canonical_phrase": "no effect observed"},          # null, sparse
    ]
    r = partition(facts)
    assert "x" in r.open_question_ids
    assert r.consensus_direction is None


def test_render_markdown_and_empty() -> None:
    assert render_markdown(partition([])) == ""
    facts = [
        {"fact_id": "1", "canonical_phrase": "increased"},
        {"fact_id": "2", "canonical_phrase": "increased"},
        {"fact_id": "3", "canonical_phrase": "decreased"},
        {"fact_id": "4", "canonical_phrase": "decreased"},
    ]
    md = render_markdown(partition(facts))
    assert "Evidence agreement" in md
    assert "Disagreement" in md


def test_partition_never_raises_on_garbage() -> None:
    r = partition([{}, {"fact_id": "z"}, {"canonical_phrase": 123}])
    assert r.total == 3
