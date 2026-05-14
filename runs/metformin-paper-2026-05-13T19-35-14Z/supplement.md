# Supplementary Materials — Metformin

Auto-generated from the run-directory receipts that accompany the main manuscript. Every count, identifier, and quote below is read verbatim from a JSON receipt; the supplement does not mint new numbers and cannot drift from the main paper.

## S1 — Search Strategy

- **Topic pack**: `metformin` (Metformin)
- **Retrieval sources**: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka
- **Primary interventions (PICO `E`)**: metformin
- **Translational-only interventions** (excluded from primary corpus; retained for sensitivity layer): buformin, phenformin, biguanide, biguanides
- **Endpoint vocabulary**: lifespan, survival, longevity, mortality, median survival, maximum lifespan, kaplan-meier, log-rank
- **Control vocabulary**: control, vehicle, placebo, untreated, wild-type, wild type
- **Excluded designs**: systematic review, meta-analysis, narrative review, scoping review, in vitro, cell line, cell culture, case report, editorial, commentary
- **Pre-specified parsed-text minimum**: 2000 chars

## S2 — Screening Counts (PRISMA-style)

- records identified: **684**
- title/abstract candidates: **167**
- open-access full-text located: **113**
- full-text parsed: **57**
- eligibility decisions: **{'exclude': 44, 'include': 7, 'unclear': 6}**
- eligible after merge: **7**
- judge model: `google/gemma-4-31b-it`

## S3 — Eligibility Receipts (per-study auto-judge verdicts)

Aggregate eligibility counts are embedded above from `eligibility_summary.json`. Per-study eligibility receipts are not packaged in this final paper folder; regenerate or inspect the upstream eligibility run directory for the full receipt table.

## S4 — Strict A-core Corpus (k = 1)

| study_id | title | year | venue | doi |
| --- | --- | --- | --- | --- |
| s049 | Metformin potentiates nephrotoxicity by promoting NETosis in response... | 2023 | Cell discovery | 10.1038/s41421-023-00595-3 |


## S5 — Effect Extraction Receipts (n = 1)

| study_id | status | metric | T_value | C_value | n_T | n_C | HR | % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s049 | no_numerics | median_survival | None | None | 10 | 10 | None | None |


### S5b — Inverse-variance pool (k_effects = 0, skipped = 1)

_(no pooling-ready effects in this run)_

Skipped (no inverse-variance numerics): `s049`


## S6 — Risk-of-Bias Notes

Automated rule-based screen per the pre-specified eligibility ladder (rule_triage → LLM judge → deterministic merge → include-contract). The universal evidence contract requires (a) parsed_text_adequate, (b) char_count above the topic-pack minimum, (c) at least two non-title evidence quotes, (d) endpoint-term coverage, and (e) intervention or control term coverage. Strict A-core additionally demands quote-level evidence that the CURRENT experiment used the preferred species + primary intervention + control + endpoint. Each demotion is recorded with its violation list in `primary_effect_input_set_strict.json`. **A pre-publication submission would require an explicit human risk-of-bias adjudication step** (e.g. SYRCLE for animal studies, Cochrane RoB 2 for human RCTs) on top of this automated screen.

## S7 — Sentinel Recall Audit

Topic-pack-declared sentinels are: **primary** = `10.1038/ncomms3192`, `10.1111/acel.12496`, `10.1111/acel.12880`; **prior_meta** = `10.1111/acel.70131`.

Per-sentinel resolution (auto verdict + manual status overlay) is recorded in the upstream eligibility run directory's QA report (not packaged in this final paper folder) under the _Sentinel resolution status (manual overlay)_ table. The gate passes only when every primary sentinel either auto-contract-passes or is documented as resolved_unavailable / resolved_excluded.

## S8 — Excluded / Demoted Studies (with reasons)

| study_id | title | demoted_from | reasons |
| --- | --- | --- | --- |
| s011 | The Gehan test identifies life-extending compounds overlook... | A_direct_lifespan | no quote names a control term |
| s046 | Metformin improves healthspan and lifespan in mice. | A_direct_lifespan | no quote names a control term |
| s124 | Biological and biophysics aspects of metformin-induced effe... | A_direct_lifespan | no quote names a control term |
| s131 | Metformin extends the lifespan of iMSUD mice by rescuing ph... | A_direct_lifespan | no quote names a control term |
| s140 | Effect of Metformin on Cardiac Metabolism and Longevity in ... | A_direct_lifespan | no quote names a primary intervention term |


## S9 — Code and Data Availability

- Pipeline source: see the project repository under `agent/`, `scripts/`, and `tests/`. All counts and effect estimates are computed from the JSON receipts filed in this paper folder; no number in the main manuscript originates outside those receipts.
- Topic pack: `topic_packs/metformin.toml` (search vocabulary, sentinels, anchors, bibliography, strict A-core terms).
- Manual full-text overrides (if any): `topic_packs/manual_full_text/metformin/`. No manual-full-text audit sidecar is packaged in this final paper folder.
- Receipts present in this folder: `cite_audit.json`, `dual_agent_extraction_audit.json`, `effect_extractions.json`, `effect_pool.json`, `eligibility_summary.json`, `extraction_confidence.json`, `paper_type_decision.json`, `primary_effect_input_set_strict.json`, `readiness_report.json`, `sentinel_repair_plan.json`.

