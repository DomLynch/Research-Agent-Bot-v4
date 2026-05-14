"""Sprint 57 — correction-proposal generator tests.

Locks the contract:
  - non-dies verdicts -> None (no proposal)
  - dies with no source -> None (can't propose)
  - dies with target value not in source -> None
  - dies + source with the right value + subgroup -> proposal with high confidence
  - sex-flip case (Harrison 2009): source quotes same value but for opposite sex
  - batch helper aggregates only the dies verdicts
  - universal: non-biomedical fixture works structurally identically
"""
from __future__ import annotations

from agent.correction_proposer import (
    CorrectionProposal,
    propose_correction,
    propose_corrections_for_run,
)
from agent.source_audit import FactVerdict


def _verdict(verdict: str = "dies", *, db_value: str = "9.0%",
             source_quote: str = "") -> FactVerdict:
    return FactVerdict(
        fact_id="rapamycin/itp/harrison_2009/lifespan_female",
        verdict=verdict, db_value=db_value, pmid="19587680",
        source_quote=source_quote,
        reason="abstract attributes 9% to males, not females", judge="gemma",
    )


def _fact(value: float = 9.0, pop: str = "female mice",
          intv: str = "rapamycin in feed") -> dict[str, object]:
    return {
        "fact_id": "rapamycin/itp/harrison_2009/lifespan_female",
        "source_paper": {"pmid": "19587680", "pmcid": "PMC2786175"},
        "numeric_value": value, "units": "%",
        "population": pop, "intervention": intv,
    }


def test_non_dies_verdict_returns_none() -> None:
    v = _verdict("survives")
    assert propose_correction(v, _fact(), abstract="anything") is None


def test_no_source_returns_none() -> None:
    v = _verdict("dies")
    assert propose_correction(v, _fact(), abstract="") is None


def test_no_target_value_returns_none() -> None:
    fact = _fact()
    fact["numeric_value"] = None
    assert propose_correction(_verdict("dies"), fact,
                              abstract="14% effect") is None


def test_proposal_built_for_sex_flip_case() -> None:
    """Harrison 2009: DB says female=9%, abstract says 9% is males +
    14% is females. Proposed correction should surface 14% in the
    female-populated context."""
    abstract = (
        "On the basis of age at 90% mortality, rapamycin led to an "
        "increase of 14% for females and 9% for males when fed in "
        "the diet."
    )
    proposal = propose_correction(
        _verdict("dies", source_quote="14% for females and 9% for males"),
        _fact(value=9.0, pop="female mice"), abstract,
    )
    assert proposal is not None
    assert proposal.fact_id == "rapamycin/itp/harrison_2009/lifespan_female"
    assert proposal.current_value == "9.0%"
    # The strongest female-subgroup anchor has value 14
    assert proposal.proposed_value == "14%"
    assert proposal.confidence > 0
    assert "female" in proposal.proposed_population.lower()


def test_proposal_uses_verdict_source_quote_when_present() -> None:
    abstract = "rapamycin increased lifespan by 14% in females, 9% in males"
    proposal = propose_correction(
        _verdict("dies", source_quote="14% in females, 9% in males"),
        _fact(value=9.0, pop="female"), abstract,
    )
    assert proposal is not None
    assert "14% in females" in proposal.evidence_quote


def test_proposal_no_numeric_match_in_source_returns_none() -> None:
    """If no value within tolerance of target exists in source, can't
    propose anything reliably."""
    abstract = "totally unrelated text without any numbers"
    assert propose_correction(_verdict("dies"), _fact(),
                              abstract=abstract) is None


def test_propose_corrections_for_run_filters_dies_only() -> None:
    facts = [_fact()]
    verdicts = [
        _verdict("survives"),  # skipped
        FactVerdict(
            fact_id="other/fact", verdict="dies", db_value="9.0%",
            pmid="1", source_quote="", reason="r", judge="gemma",
        ),  # no matching fact -> skipped
        _verdict("dies", source_quote="14% in females"),  # included
    ]
    abstract = "14% in females, 9% in males"
    proposals = propose_corrections_for_run(
        verdicts, facts, abstracts={"19587680": abstract}, fulltexts={},
    )
    assert len(proposals) == 1
    assert proposals[0].fact_id == \
        "rapamycin/itp/harrison_2009/lifespan_female"


def test_correction_proposal_round_trips() -> None:
    p = CorrectionProposal(
        fact_id="x/y", current_value="9%", proposed_value="14%",
        current_population="female", proposed_population="female span",
        evidence_quote="14% in females", confidence=0.85,
        rationale="sex flip",
    )
    d = p.as_dict()
    assert d["proposed_value"] == "14%"
    assert d["confidence"] == 0.85


def test_universal_non_biomedical_fixture() -> None:
    """Climate-policy 'dies' verdict: DB says 8%, source says 12%."""
    fact = {
        "fact_id": "carbon_tax/sweden",
        "source_paper": {"pmid": "", "pmcid": ""},
        "numeric_value": 8.0, "units": "%",
        "population": "Sweden 1991-2020",
        "intervention": "carbon tax",
    }
    v = FactVerdict(
        fact_id="carbon_tax/sweden", verdict="dies", db_value="8.0%",
        pmid="", source_quote="12% emissions cut over 1991-2020",
        reason="value mismatch", judge="gemma",
    )
    abstract = ("Sweden's carbon tax cut emissions by 12% over "
                "1991-2020 in covered sectors.")
    proposal = propose_correction(v, fact, abstract)
    assert proposal is not None
    assert proposal.proposed_value == "12%"
