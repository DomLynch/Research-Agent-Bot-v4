<!-- AUTO-STITCHED — do not edit by hand. Bundles used:
  s1: (none)
  s2: (none)
  s6: (none)
  s7: (none)
  placeholders resolved: 0 (unresolved: 0)
  honesty rewrites applied: 0
  citations resolved: 0 (unresolved: 0)
  stamped: 2026-05-12T20:02:06+00:00
-->


[SECTIONS_PENDING:title_abstract_intro — run draft_main.py --section title_abstract_intro]

[SECTIONS_PENDING:methods — run draft_main.py --section methods]

[SECTIONS_PENDING:results — run run_eligibility.py + freeze_primary_set.py + regen_section3.py]

[SECTIONS_PENDING:discussion — run draft_main.py --section discussion]

## Data and Code Availability

All raw retrieval hits, screening receipts, parsed full-text bodies (where available), eligibility receipts, effect extraction receipts, the strict A-core primary-effect input set, and the rendered manuscript are filed under the run directory `runs/rapamycin-paper-2026-05-12T19-36-21Z` and are version-controlled in `(repository URL not configured)`. Retrieval sources configured for this topic pack: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka. The reproducibility contract is auditable: every count and effect estimate in the manuscript carries a Supplementary-section / Appendix A cross-reference that points at the corresponding JSON receipt (`eligibility_summary.json`, `primary_effect_input_set_strict.json`, `effect_extractions.json`, `effect_pool.json`, `extraction_crosscheck.json`) so downstream reviewers can re-validate without re-running the LLM stack. Manual full-text injections (when used to recover sentinel papers the auto retrieval cannot reach) are recorded with SHA-256 hashes in `manual_full_text_audit.json`.

## AI-Use and Automation Disclosure

This manuscript was assembled by an automated synthesis pipeline. The eligibility judge is `google/gemma-4-31b-it` (via OpenRouter); the writer (Title, Abstract, Introduction, Methods, Discussion, Limitations, Conclusion) is `mimo-v2.5-pro`. Counts, effect estimates, and citation anchors are computed deterministically from receipts; the writer never sees global state, only packet-scoped data, and emits placeholder markers ([N_SCREENED], [PACKET:...], [CIT:<key>|<role>]) that the pipeline resolves post-hoc. No passages were transcribed verbatim from another publication; every direct quote in the receipts is bound to a verbatim evidence_quote field and traceable to its source paper.

## Ethics Statement

This synthesis re-analyses published animal-research data. No new experiments on living animals were conducted. The included primary studies are responsible for their own institutional animal-care and ethical approvals; reviewers are referred to the primary references in this manuscript for those statements. The synthesis itself does not require additional ethical approval.

## Author Contributions

The synthesis pipeline (retrieval, screening, eligibility adjudication, full-text parsing, effect extraction, pooling, manuscript drafting) was executed end-to-end by an automated system. human-operator configured the topic pack, supplied manual full-text overrides when auto-retrieval failed for documented sentinel papers, and is responsible for the final manuscript content. All other steps (search, screen, extract, draft prose) were performed by the language models named in the AI-Use Disclosure under the constraints of the universal evidence contract.

## Conflicts of Interest

The operator declares no financial conflicts of interest related to mTOR-pathway pharmacology, geroprotective interventions, or the cited primary studies. The pipeline is open-source and reusable across topics; no commercial relationship influenced the eligibility rules or the manuscript framing for the present synthesis.

## Funding

No external funding was received for this synthesis. The computational cost of the language-model calls was borne directly by the operator under a personal API subscription to the writer model and a metered allowance to the judge model provider; no third-party sponsor influenced study selection, extraction, or interpretation.
