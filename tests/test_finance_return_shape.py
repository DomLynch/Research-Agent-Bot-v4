"""P6: the finance-return shape collapse is data-driven.

Config lives in topic_packs/finance_research_claim_schema.toml ([finance_return]),
not in a hardcoded `if domain == "finance_research"` path in
agent/business_research.py. Locks the behavior that was captured byte-identical
during the lift-to-TOML refactor.
"""
from __future__ import annotations

from typing import Any

from agent.business_research import (
    _finance_return_config,
    _is_finance_return_fact,
    comparable_shape,
    normalize_business_fact,
)


def _finance_item() -> dict[str, Any]:
    return {
        "id": "fin-1", "topic": "asset pricing", "units": "%", "numeric_value": 3.2,
        "claim_type": "return_predictability",
        "canonical_phrase": "A momentum signal predicts higher portfolio returns vs benchmark.",
        "fact": {
            "intervention_detail": "momentum signal", "asset_class": "equities",
            "population": "US equities", "intervention": "momentum factor",
            "comparator": "market benchmark", "outcome": "excess return",
            "metric": "alpha", "study_design": "portfolio sort",
        },
        "paper": {"doi": "10.1/fin", "title": "Momentum", "journal_name": "JF",
                  "publication_year": 2023},
    }


def test_finance_return_config_loads_from_toml() -> None:
    cfg = _finance_return_config("finance_research")
    assert cfg is not None
    assert "asset pricing" in cfg["topics"]
    assert cfg["shape"]["population"] == "firms portfolios funds"


def test_non_finance_domain_has_no_return_config() -> None:
    # No domain literal in code: a domain opts in only via its claim-schema TOML.
    assert _finance_return_config("economics_research") is None
    assert _finance_return_config("") is None


def test_finance_return_normalizes_to_canonical_shape() -> None:
    out = normalize_business_fact(
        _finance_item(), topic="asset_pricing_anomalies", domain="finance_research",
    )
    assert _is_finance_return_fact(out) is True
    # Canonical shape applied from TOML.
    assert out["population"] == "firms portfolios funds"
    assert out["signal_family"] == "return predictive signal"
    assert out["study_design"] == "empirical asset pricing"
    # Original values preserved as *_detail (signal_family_detail auto-detected).
    assert out["comparator_detail"] == "market benchmark"
    assert out["study_design_detail"] == "portfolio sort"
    assert out["signal_family_detail"] == "momentum factor"


def test_comparable_shape_uses_signal_family_detail() -> None:
    out = normalize_business_fact(_finance_item(), topic="t", domain="finance_research")
    shape = comparable_shape(out)
    assert shape["signal_family"] == "momentum factor"
    assert shape["outcome"] == "risk adjusted portfolio returns"


def test_economics_fact_is_not_finance_return() -> None:
    out = normalize_business_fact(_finance_item(), topic="t", domain="economics_research")
    assert _is_finance_return_fact(out) is False
    assert out["population"] != "firms portfolios funds"
