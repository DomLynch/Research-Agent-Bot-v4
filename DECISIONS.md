# DECISIONS.md — dependency + design log

Per AGENTS.md: every new dependency must be justified here.

## 2026-05-11 — Sprint 7.5: PDF parsing deps

**Added**:
- `pymupdf` (AGPL-3.0, primary): fast, layout-preserving PDF text extraction.
  Used as the first attempt because publisher PDFs (Nature, eLife, Cell)
  extract cleanly with `page.get_text()`.
- `pdfminer.six` (MIT, fallback): used when PyMuPDF returns empty/garbled
  output. Slower but more permissive on malformed PDFs.

**Why both**:
- Sprint 7 live-run surfaced 12 OA candidates whose URLs were direct PDFs
  (Nature, eLife, PMC nihms, escholarship). Without a PDF parser, every
  such candidate failed eligibility with `parse_error="PDF extraction not
  supported"`, capping the corpus at HTML-only papers.
- PyMuPDF first because most journal PDFs are well-formed; pdfminer.six
  fallback for the long tail.

**License note**: PyMuPDF is AGPL-3.0. This is acceptable for an internal
research tool whose outputs are the manuscript text, not the engine. If
this repo is ever open-sourced under a non-AGPL licence, PyMuPDF must be
replaced with pdfminer.six only.

**Footprint**: pymupdf ~23 MB wheel; pdfminer.six ~6.6 MB + cryptography
~8 MB. Total ~40 MB added to `.venv`.

**Alternative considered**: tika (Apache PDFBox via JVM bridge). Rejected
because of JVM dependency.
