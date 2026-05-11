"""PDF-parse tests — mock pymupdf/pdfminer.

Verifies the cascade logic: PyMuPDF first, pdfminer.six fallback when
PyMuPDF returns empty/short text, hard failure when both fail.
"""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from agent.pdf_parse import _pdfminer_extract, _pymupdf_extract, extract_pdf_text


def _fake_pymupdf(pages: list[str]) -> ModuleType:
    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_text(self, _: str) -> str:
            return self._text

    class _Doc:
        def __init__(self, page_texts: list[str]) -> None:
            self._pages = [_Page(t) for t in page_texts]
            self.page_count = len(page_texts)

        def __getitem__(self, i: int) -> _Page:
            return self._pages[i]

        def close(self) -> None:
            return None

    mod = ModuleType("pymupdf")
    mod.open = lambda **_: _Doc(pages)  # type: ignore[attr-defined]
    return mod


def _fake_pdfminer(text: str) -> ModuleType:
    high_level = ModuleType("pdfminer.high_level")
    high_level.extract_text = lambda *_, **__: text  # type: ignore[attr-defined]
    pkg = ModuleType("pdfminer")
    pkg.high_level = high_level  # type: ignore[attr-defined]
    return pkg


def test_pymupdf_extract_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _fake_pymupdf(["page one text", "page two text"])
    monkeypatch.setitem(sys.modules, "pymupdf", mod)
    text, err = _pymupdf_extract(b"%PDF-1.4 fake")
    assert err == ""
    assert "page one text" in text
    assert "page two text" in text


def test_pymupdf_missing_returns_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    text, err = _pymupdf_extract(b"%PDF-1.4")
    assert text == ""
    assert "not installed" in err


def test_pdfminer_extract_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = _fake_pdfminer("decoded body text")
    monkeypatch.setitem(sys.modules, "pdfminer", pkg)
    monkeypatch.setitem(sys.modules, "pdfminer.high_level", pkg.high_level)
    text, err = _pdfminer_extract(b"%PDF-1.4")
    assert text == "decoded body text"
    assert err == ""


def test_extract_pdf_text_uses_pymupdf_when_it_returns_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pymupdf", _fake_pymupdf(["primary path text"]))
    # pdfminer should NOT be consulted because pymupdf returned content
    called: dict[str, bool] = {"pdfminer": False}

    def fail_pdfminer(*_: Any, **__: Any) -> str:
        called["pdfminer"] = True
        return "fallback"

    pkg = _fake_pdfminer("fallback")
    pkg.high_level.extract_text = fail_pdfminer
    monkeypatch.setitem(sys.modules, "pdfminer", pkg)
    monkeypatch.setitem(sys.modules, "pdfminer.high_level", pkg.high_level)

    text, err = extract_pdf_text(b"%PDF-1.4 abc")
    assert "primary path text" in text
    assert err == ""
    assert called["pdfminer"] is False


def test_extract_pdf_text_falls_back_when_pymupdf_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pymupdf", _fake_pymupdf([""]))  # empty pages
    pkg = _fake_pdfminer("recovered by pdfminer")
    monkeypatch.setitem(sys.modules, "pdfminer", pkg)
    monkeypatch.setitem(sys.modules, "pdfminer.high_level", pkg.high_level)
    text, err = extract_pdf_text(b"%PDF-1.4 abc")
    assert text == "recovered by pdfminer"
    assert err == ""


def test_extract_pdf_text_reports_both_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pymupdf", _fake_pymupdf([""]))
    pkg = _fake_pdfminer("")
    monkeypatch.setitem(sys.modules, "pdfminer", pkg)
    monkeypatch.setitem(sys.modules, "pdfminer.high_level", pkg.high_level)
    text, err = extract_pdf_text(b"%PDF-1.4 abc")
    assert text == ""
    assert "pymupdf" in err and "pdfminer" in err


def test_extract_pdf_text_rejects_empty_bytes() -> None:
    text, err = extract_pdf_text(b"")
    assert text == ""
    assert "empty" in err
