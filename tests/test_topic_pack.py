"""Topic-pack loader tests."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agent.topic_pack import load_topic_pack


def _write_pack(tmp_path: Path, name: str, body: str) -> Path:
    (tmp_path / f"{name}.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_load_rapamycin_pack_from_default_dir() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    assert pack.topic == "rapamycin"
    assert "murine" in pack.preferred_terms
    assert "mammalian" in pack.discouraged_terms
    assert "primary-study" in pack.cite_roles_allowed
    assert pack.anchors["harrison-2009-rapamycin"] == "primary-study"
    assert pack.anchors["swindell-2017-meta"] == "prior-meta-analysis"
    assert pack.anchors["tyshkovskiy-2025-vertebrate-meta"] == "prior-meta-analysis"
    assert pack.length_caps["abstract"] == 300
    assert pack.length_caps["introduction"] == 1000
    assert pack.min_words_per_citation == 45


def test_load_missing_pack_returns_none(tmp_path: Path) -> None:
    assert load_topic_pack("nonexistent", pack_dir=tmp_path) is None


def test_load_minimal_pack(tmp_path: Path) -> None:
    _write_pack(tmp_path, "demo", 'topic = "demo"\ndisplay_name = "Demo"\n')
    pack = load_topic_pack("demo", pack_dir=tmp_path)
    assert pack is not None
    assert pack.topic == "demo"
    assert pack.preferred_terms == ()
    assert pack.discouraged_terms == ()
    assert pack.has_scope_rules is False
    assert pack.has_cite_roles is False


def test_pack_has_scope_rules(tmp_path: Path) -> None:
    _write_pack(
        tmp_path,
        "demo",
        'topic = "demo"\n[scope]\npreferred_terms = ["x"]\n',
    )
    pack = load_topic_pack("demo", pack_dir=tmp_path)
    assert pack is not None
    assert pack.has_scope_rules is True


def test_pack_immutable() -> None:
    pack = load_topic_pack("rapamycin")
    assert pack is not None
    with pytest.raises(FrozenInstanceError):
        pack.topic = "mutated"  # type: ignore[misc]
