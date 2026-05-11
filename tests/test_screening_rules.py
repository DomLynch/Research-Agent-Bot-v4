"""Screening-rules tests — pure logic, no network."""
from __future__ import annotations

from agent.retrieval.base import PaperHit
from agent.screening_rules import build_candidate_studies, screen_hit, screen_hits
from agent.topic_pack import load_topic_pack


def _hit(title: str, abstract: str = "", doi: str = "10.1/x") -> PaperHit:
    return PaperHit(
        source="pubmed", title=title, abstract=abstract, year=2020, url="u",
        doi=doi, pmid=None, venue=None,
    )


def test_include_when_preferred_and_primary_match() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    h = _hit("Rapamycin extends lifespan in mice", "Murine cohort study of sirolimus")
    receipt = screen_hit(h, pack)
    assert receipt.decision == "include"
    assert receipt.stage == "title-abstract"


def test_exclude_when_no_primary_intervention() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    h = _hit("Caloric restriction in murine lifespan studies")
    receipt = screen_hit(h, pack)
    assert receipt.decision == "exclude"
    assert "primary intervention" in receipt.reason


def test_exclude_when_no_preferred_scope_term() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    h = _hit("Rapamycin in human clinical trials", "Adult patients treated with sirolimus")
    receipt = screen_hit(h, pack)
    assert receipt.decision == "exclude"
    assert "preferred-scope" in receipt.reason


def test_exclude_when_discouraged_term_present() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    h = _hit("Rapamycin in mammalian models including mice")
    receipt = screen_hit(h, pack)
    assert receipt.decision == "exclude"
    assert "discouraged scope" in receipt.reason


def test_screen_hits_emits_one_ta_receipt_per_hit() -> None:
    """Truth discipline: no fake full-text receipts — only TA pass exists."""
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    h1 = _hit("Rapamycin in mice", doi="10.1/a")
    h2 = _hit("Unrelated topic", doi="10.1/b")
    receipts = screen_hits((h1, h2), pack)
    assert len(receipts) == 2
    assert {r.stage for r in receipts} == {"title-abstract"}


def test_build_candidate_studies_from_ta_includes() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    good = _hit("Rapamycin extends lifespan in mice", doi="10.1/good")
    bad = _hit("Off-topic study", doi="10.1/bad")
    receipts = screen_hits((good, bad), pack)
    candidates = build_candidate_studies((good, bad), receipts)
    assert len(candidates) == 1
    assert candidates[0].hit_key == good.dedupe_key
    assert candidates[0].study_id == "s001"
    assert candidates[0].screening_stage == "title_abstract_candidate"
    assert candidates[0].is_eligible is False
