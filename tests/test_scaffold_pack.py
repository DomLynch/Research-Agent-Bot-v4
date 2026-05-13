"""Sprint 12.9 Task D tests: scaffold_pack auto-generates a draft
topic-pack TOML from a topic keyword + Researka curated papers.

Universal: the scaffold reads only Researka's /api/v1/papers/topic
response shape + operator CLI flags. The tests exercise:
  - sentinel + anchor selection from the curated paper list
  - bibliography emission from paper metadata
  - the produced TOML loads cleanly via load_topic_pack()
  - the scaffold works with non-default vocabulary (climate-like
    flags) -> proves no biomedical hardcoding in core logic
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_scaffold_module() -> Any:
    """Load scripts/scaffold_pack.py as a module (it lives outside
    the agent/ package import path)."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "scaffold_pack.py"
    spec = importlib.util.spec_from_file_location("scaffold_pack", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SCAFFOLD = _load_scaffold_module()


def _curated_papers_fixture() -> list[dict[str, Any]]:
    """Mock Researka /api/v1/papers/topic response — 5 tier-1 hits."""
    return [
        {
            "id": "10.1038/nature08221", "doi": "10.1038/nature08221",
            "title": "Rapamycin fed late in life extends lifespan",
            "journal_name": "Nature", "publication_year": 2009,
            "tier": 1, "topic_score": 1.0, "quality_score": 0.95,
        },
        {
            "id": "10.1093/gerona/glq178", "doi": "10.1093/gerona/glq178",
            "title": "Rapamycin extends life span of mice",
            "journal_name": "J Gerontol A", "publication_year": 2011,
            "tier": 1, "topic_score": 1.0, "quality_score": 0.90,
        },
        {
            "id": "10.7554/eLife.16351", "doi": "10.7554/eLife.16351",
            "title": "Transient rapamycin treatment increases lifespan",
            "journal_name": "eLife", "publication_year": 2016,
            "tier": 1, "topic_score": 0.95, "quality_score": 0.88,
        },
        {
            "id": "10.1111/acel.12194", "doi": "10.1111/acel.12194",
            "title": "Rapamycin lifespan increase is dose-dependent",
            "journal_name": "Aging Cell", "publication_year": 2014,
            "tier": 1, "topic_score": 0.90, "quality_score": 0.80,
        },
        {
            "id": "10.1093/gerona/glw153", "doi": "10.1093/gerona/glw153",
            "title": "Meta-analysis of rapamycin lifespan studies",
            "journal_name": "J Gerontol A", "publication_year": 2017,
            "tier": 1, "topic_score": 0.85, "quality_score": 0.75,
        },
    ]


def test_anchor_key_derives_from_paper_metadata() -> None:
    """Anchor keys must be stable + derived from the paper's title +
    year + DOI suffix. Universal — no biomedical literals required."""
    key = _SCAFFOLD._anchor_key("10.1038/nature08221", 2009, "Rapamycin fed late in life")
    assert "2009" in key
    assert key.startswith("rapamycin-2009-")
    # Stability: identical input -> identical key.
    assert key == _SCAFFOLD._anchor_key("10.1038/nature08221", 2009, "Rapamycin fed late in life")


def test_render_emits_sentinels_anchors_and_bibliography(tmp_path: Path) -> None:
    """Given curated papers, the rendered TOML carries DOIs as
    sentinel_primary, the next-tier as [anchors], and bibliography
    entries with title / journal / year / DOI."""
    out = _SCAFFOLD._render(
        topic="rapamycin", display_name="Rapamycin",
        primary_interventions=["rapamycin", "sirolimus"],
        species_terms=["mouse", "mice", "murine"],
        endpoint="lifespan",
        papers=_curated_papers_fixture(),
        sentinel_n=3, anchor_n=2,
    )
    # Sentinels: top 3 DOIs.
    assert '"10.1038/nature08221"' in out
    assert '"10.1093/gerona/glq178"' in out
    assert '"10.7554/eLife.16351"' in out
    # Anchors: next 2 papers (positions 4-5). Anchor keys derive from
    # the first alphabetical word of the title — position-4 is
    # "Rapamycin lifespan increase..." (key starts "rapamycin-2014-")
    # and position-5 is "Meta-analysis of rapamycin lifespan..." which
    # produces "meta-2017-" because the first \\w+ word is "Meta".
    assert "rapamycin-2014-" in out
    assert "meta-2017-" in out
    # Bibliography lines reference journal + DOI.
    assert "Aging Cell" in out
    assert "doi:10.1111/acel.12194" in out


def test_render_output_parses_as_loadable_topic_pack(tmp_path: Path) -> None:
    """The rendered TOML must round-trip through load_topic_pack(...)
    without TOML or schema errors. Locks the scaffold's structural
    contract to whatever the loader needs."""
    out = _SCAFFOLD._render(
        topic="nmn", display_name="NMN",
        primary_interventions=["nicotinamide mononucleotide", "NMN"],
        species_terms=["mouse"],
        endpoint="lifespan",
        papers=_curated_papers_fixture(),
        sentinel_n=3, anchor_n=2,
    )
    pack_path = tmp_path / "nmn.toml"
    pack_path.write_text(out, encoding="utf-8")
    from agent.topic_pack import load_topic_pack
    p = load_topic_pack("nmn", pack_dir=tmp_path)
    assert p is not None
    assert p.topic == "nmn"
    assert p.display_name == "NMN"
    assert "nicotinamide mononucleotide" in p.primary_interventions
    assert "mouse" in p.preferred_terms
    assert p.endpoint == "lifespan"
    assert "10.1038/nature08221" in p.sentinel_primary
    # Sprint 12.9.E: every scaffolded pack now includes 8 universal
    # method-citation anchors (PRISMA, SYRCLE, Cochrane GRADE, ARRIVE,
    # Egger, metafor, I², Hartung-Knapp) so writer-emitted
    # [CIT:|method-citation] markers resolve cleanly. Plus the 2
    # paper-derived anchors from this fixture = 10 total.
    assert len(p.anchors) == 10
    assert "page-2020-prisma" in p.anchors  # universal method anchor
    assert "rapamycin-2014-2194" in p.anchors  # paper-derived anchor
    # Each anchor must have a matching bibliography entry.
    for key in p.anchors:
        assert key in p.references_bibliography


def test_render_is_universal_for_non_biomedical_vocab(tmp_path: Path) -> None:
    """Scaffold must work with arbitrary topic + intervention + species
    vocabulary — proves no biomedical literals are hardcoded in the
    render function. Here we feed a climate-style topic."""
    climate_papers = [
        {
            "id": "10.1/climate-a", "doi": "10.1/climate-a",
            "title": "Carbon tax adoption and emissions trajectory",
            "journal_name": "Nature Climate", "publication_year": 2022,
            "tier": 1, "topic_score": 0.98, "quality_score": 0.92,
        },
        {
            "id": "10.1/climate-b", "doi": "10.1/climate-b",
            "title": "Subnational carbon pricing review",
            "journal_name": "Climate Policy", "publication_year": 2023,
            "tier": 1, "topic_score": 0.95, "quality_score": 0.90,
        },
    ]
    out = _SCAFFOLD._render(
        topic="carbon_tax", display_name="Carbon Tax",
        primary_interventions=["carbon tax", "carbon pricing"],
        species_terms=["municipality", "state", "country"],
        endpoint="emissions_reduction",
        papers=climate_papers,
        sentinel_n=2, anchor_n=0,
    )
    # Topic-specific values survive into the rendered TOML.
    assert 'topic = "carbon_tax"' in out
    assert "carbon tax" in out
    assert "carbon pricing" in out
    assert "municipality" in out
    assert "emissions_reduction" in out
    # The rendered TOML still loads through load_topic_pack — universal.
    pack_path = tmp_path / "carbon_tax.toml"
    pack_path.write_text(out, encoding="utf-8")
    from agent.topic_pack import load_topic_pack
    p = load_topic_pack("carbon_tax", pack_dir=tmp_path)
    assert p is not None
    assert p.endpoint == "emissions_reduction"
    assert "carbon tax" in p.primary_interventions
    # Sentinels carry both climate DOIs.
    assert "10.1/climate-a" in p.sentinel_primary
    assert "10.1/climate-b" in p.sentinel_primary


def test_render_handles_empty_curated_paper_list(tmp_path: Path) -> None:
    """When Researka returns 0 papers for a topic, the scaffold still
    emits a syntactically valid (but sentinel-less + anchor-less)
    pack — the operator can run the pipeline and the sentinel-recall
    gate will surface the missing-curation case explicitly."""
    out = _SCAFFOLD._render(
        topic="brand_new_topic", display_name="Brand New Topic",
        primary_interventions=["unknown_intervention"],
        species_terms=["mouse"], endpoint="lifespan",
        papers=[], sentinel_n=3, anchor_n=15,
    )
    pack_path = tmp_path / "brand_new_topic.toml"
    pack_path.write_text(out, encoding="utf-8")
    from agent.topic_pack import load_topic_pack
    p = load_topic_pack("brand_new_topic", pack_dir=tmp_path)
    assert p is not None
    assert p.sentinel_primary == ()
    # Sprint 12.9.E: scaffold always seeds 8 universal method-citation
    # anchors so writer [CIT:|method-citation] markers resolve cleanly
    # even when the curated index returns 0 papers for the topic. Paper-
    # derived anchors are 0 in this case, but method anchors are 8.
    assert len(p.anchors) == 8
    for key in ("page-2020-prisma", "hooijmans-2014-syrcle",
                "egger-1997-funnel", "viechtbauer-2010-metafor"):
        assert key in p.anchors
        assert key in p.references_bibliography
