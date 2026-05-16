"""Sprint 79 — broad-theme selection for Top 5 curation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.alpha_selector import alpha_score
from agent.fact_facets import (
    classify_fact_facet,
    load_facet_markers,
    select_coherent_theme,
)


def _fact(
    fid: str,
    phrase: str,
    *,
    title: str = "",
    population: str = "",
    intervention: str = "",
) -> dict[str, Any]:
    return {
        "fact_id": fid,
        "canonical_phrase": phrase,
        "population": population,
        "intervention": intervention,
        "source_paper": {"title": title},
    }


def test_facet_vocab_loaded_from_topic_pack_data() -> None:
    markers = load_facet_markers()
    assert "environmental_remediation" in markers
    assert "preclinical_cancer" in markers
    assert "activated carbon" in markers["environmental_remediation"]


def test_facets_classify_auditor_examples() -> None:
    assert classify_fact_facet(_fact(
        "opac",
        "The highest percentage of MET removal using OPAC was 97.23%.",
        title="Metformin adsorption onto activated carbon",
        population="metformin in aqueous solutions",
        intervention="orange peel activated carbon",
    )) == "environmental_remediation"
    assert classify_fact_facet(_fact(
        "pdx",
        "Metformin inhibits the growth of both PDX tumors by at least 50%.",
        population="colorectal cancer patient-derived xenografts",
    )) == "preclinical_cancer"
    assert classify_fact_facet(_fact(
        "mtor",
        "Western blot analysis showed higher phosphorylation of mTOR.",
        population="bone marrow cells",
    )) == "molecular_mechanism"
    assert classify_fact_facet(_fact(
        "cr",
        "In males, caloric restriction reduced macroadenomas.",
        title="Abdominal obesity accounts for intestinal tumors",
    )) == "preclinical_cancer"


def test_theme_selection_prefers_coherent_cluster_over_single_high_card() -> None:
    scored = [
        (80, _fact("opac", "97.23% removal using activated carbon",
                   population="aqueous solution")),
        (72, _fact("pdx", "PDX tumor growth inhibited by 50%",
                   population="colorectal cancer xenografts")),
        (70, _fact("nnk", "Tumor burden reduced by 72%",
                   population="carcinogen-treated mice")),
        (70, _fact("cell", "Cell line proliferation inhibited by 80%",
                   population="pancreatic cancer cell line")),
    ]
    theme, top = select_coherent_theme(scored, top_n=5)
    assert theme == "intervention_signal"
    assert [f["fact_id"] for _score, f in top] == ["pdx", "nnk", "cell"]


def test_alpha_score_boosts_contrast_and_subgroup_markers() -> None:
    base = 50
    boosted = alpha_score(base, _fact(
        "contrast",
        "In one subgroup the intervention worked, but not in another.",
        population="male and female strata",
    ))
    generic = alpha_score(base, _fact("generic", "The biomarker changed by 52%."))
    assert boosted > generic
    assert boosted == 85


def test_fact_facets_code_has_no_domain_vocabulary() -> None:
    text = Path("agent/fact_facets.py").read_text(encoding="utf-8").lower()
    forbidden = {
        "metformin", "rapamycin", "mtor", "cancer", "tumor", "tumour",
        "mice", "mouse", "rat", "patients", "clinical", "xenograft",
        "phosphorylation", "wastewater", "activated carbon",
    }
    leaked = sorted(
        word for word in forbidden
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text)
    )
    assert leaked == []
