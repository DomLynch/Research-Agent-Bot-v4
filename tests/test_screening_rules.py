"""Screening-rules tests — pure logic, no network."""
from __future__ import annotations

from agent.retrieval.base import PaperHit
from agent.screening_rules import build_included_studies, screen_hit, screen_hits
from agent.topic_pack import load_topic_pack


def _hit(title: str, abstract: str = "", doi: str = "10.1/x") -> PaperHit:
    return PaperHit(
        source="pubmed", title=title, abstract=abstract, year=2020, url="u",
        doi=doi, pmid=None, venue=None,
    )


def test_include_when_preferred_and_primary_match() -> None:
    pack = load_topic_pack("rapamycin")
    h = _hit("Rapamycin extends lifespan in mice", "Murine cohort study of sirolimus")
    ta, ft = screen_hit(h, pack)
    assert ta.decision == "include"
    assert ft.decision == "include"
    assert ta.stage == "title-abstract"
    assert ft.stage == "full-text"


def test_exclude_when_no_primary_intervention() -> None:
    pack = load_topic_pack("rapamycin")
    h = _hit("Caloric restriction in murine lifespan studies")
    ta, _ = screen_hit(h, pack)
    assert ta.decision == "exclude"
    assert "primary intervention" in ta.reason


def test_exclude_when_no_preferred_scope_term() -> None:
    pack = load_topic_pack("rapamycin")
    h = _hit("Rapamycin in human clinical trials", "Adult patients treated with sirolimus")
    ta, _ = screen_hit(h, pack)
    assert ta.decision == "exclude"
    assert "preferred-scope" in ta.reason


def test_exclude_when_discouraged_term_present() -> None:
    pack = load_topic_pack("rapamycin")
    # 'mammalian' is discouraged in the rapamycin pack
    h = _hit("Rapamycin in mammalian models including mice")
    ta, _ = screen_hit(h, pack)
    assert ta.decision == "exclude"
    assert "discouraged scope" in ta.reason


def test_screen_hits_emits_two_receipts_per_hit() -> None:
    pack = load_topic_pack("rapamycin")
    h1 = _hit("Rapamycin in mice", doi="10.1/a")
    h2 = _hit("Unrelated topic", doi="10.1/b")
    receipts = screen_hits((h1, h2), pack)
    assert len(receipts) == 4
    assert {r.stage for r in receipts} == {"title-abstract", "full-text"}


def test_build_included_studies_only_from_full_text_includes() -> None:
    pack = load_topic_pack("rapamycin")
    good = _hit("Rapamycin extends lifespan in mice", doi="10.1/good")
    bad = _hit("Off-topic study", doi="10.1/bad")
    receipts = screen_hits((good, bad), pack)
    included = build_included_studies((good, bad), receipts)
    assert len(included) == 1
    assert included[0].hit_key == good.dedupe_key
    assert included[0].study_id == "s001"
