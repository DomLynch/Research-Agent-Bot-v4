# Supplementary Materials — Acarbose

Auto-generated from the run-directory receipts that accompany the main manuscript. Every count, identifier, and quote below is read verbatim from a JSON receipt; the supplement does not mint new numbers and cannot drift from the main paper.

## S1 — Search Strategy

- **Topic pack**: `acarbose` (Acarbose)
- **Retrieval sources**: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka
- **Primary interventions (PICO `E`)**: acarbose, alpha-glucosidase inhibitor
- **Translational-only interventions** (excluded from primary corpus; retained for sensitivity layer): (none)
- **Endpoint vocabulary**: lifespan, survival, longevity, mortality, median survival
- **Control vocabulary**: control, vehicle, placebo, untreated, wild-type
- **Excluded designs**: systematic review, meta-analysis, narrative review, scoping review, in vitro, cell line, case report
- **Pre-specified parsed-text minimum**: 2000 chars

## S2 — Screening Counts (PRISMA-style)

- records identified: **520**
- title/abstract candidates: **44**
- open-access full-text located: **40**
- full-text parsed: **21**
- eligibility decisions: **{'exclude': 14, 'unclear': 4, 'include': 3}**
- eligible after merge: **3**
- judge model: `google/gemma-4-31b-it`

## S3 — Eligibility Receipts (per-study auto-judge verdicts)

Aggregate eligibility counts are embedded above from `eligibility_summary.json`. Per-study eligibility receipts are not packaged in this final paper folder; regenerate or inspect the upstream eligibility run directory for the full receipt table.

## S4 — Strict A-core Corpus (k = 1)

| study_id | title | year | venue | doi |
| --- | --- | --- | --- | --- |
| s036 | Changes in the gut microbiome and fermentation products concurrent wi... | 2019 | BMC microbiology | 10.1186/s12866-019-1494-7 |


## S5 — Effect Extraction Receipts (n = 1)

| study_id | status | metric | T_value | C_value | n_T | n_C | HR | % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s036 | extracted | median_survival_days | 975.0 | 830.0 | 162 | 312 | None | 17.0 |


### S5b — Inverse-variance pool (k_effects = 1, skipped = 0)

| study_id | metric | estimate | SE | CI_low | CI_high |
| --- | --- | --- | --- | --- | --- |
| s036 | log_median_ratio | 0.1610 | 0.0968 | -0.0288 | 0.3508 |


## S6 — Risk-of-Bias Notes

Automated rule-based screen per the pre-specified eligibility ladder (rule_triage → LLM judge → deterministic merge → include-contract). The universal evidence contract requires (a) parsed_text_adequate, (b) char_count above the topic-pack minimum, (c) at least two non-title evidence quotes, (d) endpoint-term coverage, and (e) intervention or control term coverage. Strict A-core additionally demands quote-level evidence that the CURRENT experiment used the preferred species + primary intervention + control + endpoint. Each demotion is recorded with its violation list in `primary_effect_input_set_strict.json`. **A pre-publication submission would require an explicit human risk-of-bias adjudication step** (e.g. SYRCLE for animal studies, Cochrane RoB 2 for human RCTs) on top of this automated screen.

## S7 — Sentinel Recall Audit

Topic-pack-declared sentinels are: **primary** = `10.1111/acel.13345`, `10.1093/gerona/glaa302`, `10.1111/acel.12264`; **prior_meta** = .

Per-sentinel resolution (auto verdict + manual status overlay) is recorded in the upstream eligibility run directory's QA report (not packaged in this final paper folder) under the _Sentinel resolution status (manual overlay)_ table. The gate passes only when every primary sentinel either auto-contract-passes or is documented as resolved_unavailable / resolved_excluded.

## S8 — Excluded / Demoted Studies (with reasons)

| study_id | title | demoted_from | reasons |
| --- | --- | --- | --- |
| s012 | Lifespan-extending interventions induce consistent patterns... | A_direct_lifespan | no quote names a control term / quotes signal secondary/omics design |


## S9 — Code and Data Availability

- Pipeline source: see the project repository under `agent/`, `scripts/`, and `tests/`. All counts and effect estimates are computed from the JSON receipts filed in this paper folder; no number in the main manuscript originates outside those receipts.
- Topic pack: `topic_packs/acarbose.toml` (search vocabulary, sentinels, anchors, bibliography, strict A-core terms).
- Manual full-text overrides (if any): `topic_packs/manual_full_text/acarbose/`. No manual-full-text audit sidecar is packaged in this final paper folder.
- Receipts present in this folder: `effect_extractions.json`, `effect_pool.json`, `eligibility_summary.json`, `primary_effect_input_set_strict.json`.

