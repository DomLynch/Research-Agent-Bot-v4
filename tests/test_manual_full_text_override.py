"""Sprint 9 - manual full-text override tests.

Operator drops a verbatim full-text file into
`topic_packs/manual_full_text/<topic>/<key>.txt` keyed by either
normalised DOI (e.g. `10.1038-nature08221.txt`) or PMID
(e.g. `19587680.txt`). The pipeline reads the file in place of the
auto-fetched bytes for that study_id.
"""
from __future__ import annotations

from pathlib import Path

from agent.full_text_parse import (
    ParsedFullText,
    apply_manual_overrides,
    load_manual_full_text_overrides,
)


def _doc(study_id: str, text: str = "", error: str = "") -> ParsedFullText:
    return ParsedFullText(
        study_id=study_id, source_url="auto",
        source_kind="html", text=text, char_count=len(text),
        sha256="autohash", fetched_at_utc="2026-05-12T00:00:00+00:00",
        error=error,
    )


def test_load_returns_empty_when_directory_missing(tmp_path: Path) -> None:
    overrides = load_manual_full_text_overrides(
        "rapamycin", {"s1": ("10.1/x", "")}, base_dir=str(tmp_path / "nope"),
    )
    assert overrides == {}


def test_load_matches_by_normalised_doi(tmp_path: Path) -> None:
    (tmp_path / "rapamycin").mkdir(parents=True)
    (tmp_path / "rapamycin" / "10.1038-nature08221.txt").write_text(
        "Real Harrison 2009 full text body.", encoding="utf-8",
    )
    overrides = load_manual_full_text_overrides(
        "rapamycin",
        {"s86": ("10.1038/nature08221", "19587680")},
        base_dir=str(tmp_path / "rapamycin"),
    )
    assert overrides == {"s86": "Real Harrison 2009 full text body."}


def test_load_falls_back_to_pmid_when_doi_file_missing(tmp_path: Path) -> None:
    (tmp_path / "rapamycin").mkdir(parents=True)
    (tmp_path / "rapamycin" / "19587680.txt").write_text(
        "Real Harrison 2009 by PMID.", encoding="utf-8",
    )
    overrides = load_manual_full_text_overrides(
        "rapamycin",
        {"s86": ("10.1038/nature08221", "19587680")},
        base_dir=str(tmp_path / "rapamycin"),
    )
    assert overrides == {"s86": "Real Harrison 2009 by PMID."}


def test_load_skips_unmatched(tmp_path: Path) -> None:
    (tmp_path / "rapamycin").mkdir(parents=True)
    (tmp_path / "rapamycin" / "10.9999-other.txt").write_text("x", encoding="utf-8")
    overrides = load_manual_full_text_overrides(
        "rapamycin",
        {"s86": ("10.1038/nature08221", "19587680")},
        base_dir=str(tmp_path / "rapamycin"),
    )
    assert overrides == {}


def test_apply_overrides_replaces_only_matched_studies() -> None:
    docs = (
        _doc("s1", text="auto-fetched body"),
        _doc("s2", text="", error="paywall"),
        _doc("s3", text="auto-fetched body 3"),
    )
    result = apply_manual_overrides(docs, {"s2": "Manual body for s2."})
    assert result[0].text == "auto-fetched body"      # untouched
    assert result[1].text == "Manual body for s2."    # replaced
    assert result[1].source_url == "manual:full_text"
    assert result[1].char_count == len("Manual body for s2.")
    assert result[1].error == ""                       # empty error now
    assert result[2].text == "auto-fetched body 3"    # untouched


def test_apply_overrides_marks_empty_override_with_error() -> None:
    docs = (_doc("s1", text="some body"),)
    result = apply_manual_overrides(docs, {"s1": "   "})
    assert result[0].source_url == "manual:full_text"
    assert result[0].error == "manual override empty"


def test_apply_overrides_no_op_when_overrides_empty() -> None:
    docs = (_doc("s1", text="auto body"),)
    assert apply_manual_overrides(docs, {}) == docs
