"""PDF text extraction with PyMuPDF primary + pdfminer.six fallback.

Sprint 7 left 12 OA candidates unparseable because the OA URL was a PDF.
This module reads PDF bytes and returns plain text, fail-soft: any
extraction failure returns ("", error) so the caller can record a parsed
receipt with parsed=False.

Universal: no biomedical literals; only PDF byte handling.
"""
from __future__ import annotations

import io
from typing import Any


def _pymupdf_extract(data: bytes) -> tuple[str, str]:
    """PyMuPDF primary path. Returns (text, error_msg)."""
    try:
        import pymupdf
    except ImportError:
        return "", "pymupdf not installed"
    pm: Any = pymupdf  # PyMuPDF has loose typing; one cast keeps mypy quiet.
    try:
        doc = pm.open(stream=data, filetype="pdf")
    except Exception as e:
        return "", f"pymupdf open failed: {e.__class__.__name__}"
    try:
        parts: list[str] = []
        for i in range(doc.page_count):
            parts.append(doc[i].get_text("text"))
        text = "\n".join(parts).strip()
    except Exception as e:
        return "", f"pymupdf extract failed: {e.__class__.__name__}"
    finally:
        doc.close()
    return text, ""


def _pdfminer_extract(data: bytes) -> tuple[str, str]:
    """pdfminer.six fallback path. Returns (text, error_msg)."""
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        return "", "pdfminer.six not installed"
    try:
        text = extract_text(io.BytesIO(data)).strip()
    except Exception as e:
        return "", f"pdfminer extract failed: {e.__class__.__name__}"
    return text, ""


def extract_pdf_text(data: bytes, *, min_chars: int = 1) -> tuple[str, str]:
    """Try PyMuPDF; fall back to pdfminer.six if the primary path returns
    too little text. Returns (text, error). On full failure, text="" and
    error names the last failure.
    """
    if not data:
        return "", "empty PDF bytes"
    text, err1 = _pymupdf_extract(data)
    if len(text) >= min_chars:
        return text, ""
    text2, err2 = _pdfminer_extract(data)
    if len(text2) >= min_chars:
        return text2, ""
    return "", f"pymupdf: {err1 or 'short text'} | pdfminer: {err2 or 'short text'}"
