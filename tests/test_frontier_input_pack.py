"""Sprint 59 — frontier input pack tests."""
from __future__ import annotations

from typing import Any

from agent.frontier_input_pack import build_input_pack


def _fact(fid: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fact_id": fid,
        "canonical_phrase": "rapamycin extended lifespan by 60%",
        "population": "middle-aged mice",
        "intervention": "rapamycin",
        "numeric_value": 60.0, "units": "%",
    }
    base.update(kw)
    return base


def test_a_core_facts_only_in_a_core() -> None:
    pack = build_input_pack(
        [_fact("f/1"), _fact("f/2"), _fact("f/3")],
        topic="rapamycin",
    )
    assert len(pack.a_core) == 3
    assert pack.b_context == ()
    assert pack.has_minimum_a_core is True


def test_d_bad_extraction_excluded(monkeypatch: Any = None) -> None:
    # Genuine D_bad now means PICO essentially absent (both population AND
    # intervention empty). A single empty slot would bind as B_context instead.
    pack = build_input_pack([
        _fact("f/bad", intervention="", population="",
              canonical_phrase="rapamycin treated for 66 weeks"),
    ], topic="rapamycin")
    assert pack.a_core == ()
    assert pack.excluded_counts["D_bad_extraction"] == 1
    assert pack.has_minimum_a_core is False


def test_c_noise_excluded() -> None:
    pack = build_input_pack([
        _fact("f/off", canonical_phrase="glucose dropped 60%",
              intervention="insulin", population="diabetic patients"),
    ], topic="rapamycin")
    assert pack.a_core == ()
    assert pack.excluded_counts["C_noise"] == 1


def test_below_a_core_min_flips_has_minimum_false() -> None:
    pack = build_input_pack(
        [_fact("f/1"), _fact("f/2")],
        topic="rapamycin", a_core_min=3,
    )
    assert pack.has_minimum_a_core is False
    assert len(pack.a_core) == 2


def test_b_context_kept_separately() -> None:
    pack = build_input_pack([
        _fact("f/a"),
        _fact("f/b", intervention="vehicle",
              canonical_phrase="rapamycin pathway analysis showed 30% reduction"),
    ], topic="rapamycin")
    assert len(pack.a_core) == 1
    assert len(pack.b_context) == 1


def test_as_dict_round_trip() -> None:
    pack = build_input_pack([_fact("f/1")], topic="rapamycin")
    d = pack.as_dict()
    assert d["a_core_count"] == 1
    assert d["topic"] == "rapamycin"
    assert "excluded_counts" in d


def test_universal_non_biomedical() -> None:
    pack = build_input_pack([{
        "fact_id": "ct/swe",
        "canonical_phrase": "carbon_tax cut emissions 8% in Sweden",
        "population": "Sweden 1991-2020", "intervention": "carbon_tax",
        "numeric_value": 8.0, "units": "%",
    }], topic="carbon_tax")
    assert len(pack.a_core) == 1
