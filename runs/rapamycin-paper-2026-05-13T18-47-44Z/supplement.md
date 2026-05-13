# Supplementary Materials — Rapamycin

Auto-generated from the run-directory receipts that accompany the main manuscript. Every count, identifier, and quote below is read verbatim from a JSON receipt; the supplement does not mint new numbers and cannot drift from the main paper.

## S1 — Search Strategy

- **Topic pack**: `rapamycin` (Rapamycin)
- **Retrieval sources**: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka
- **Primary interventions (PICO `E`)**: rapamycin, sirolimus
- **Translational-only interventions** (excluded from primary corpus; retained for sensitivity layer): everolimus, rtb101, rapalog, rapalogs
- **Endpoint vocabulary**: lifespan, survival, longevity, mortality, median survival, maximum lifespan, kaplan-meier, log-rank
- **Control vocabulary**: control, vehicle, placebo, untreated, wild-type, wild type
- **Excluded designs**: systematic review, meta-analysis, narrative review, scoping review, in vitro, cell line, cell culture, case report, editorial, commentary
- **Pre-specified parsed-text minimum**: 2000 chars

## S2 — Screening Counts (PRISMA-style)

- records identified: **1000**
- title/abstract candidates: **374**
- open-access full-text located: **297**
- full-text parsed: **150**
- eligibility decisions: **{'exclude': 112, 'unclear': 12, 'include': 26}**
- eligible after merge: **26**
- judge model: `google/gemma-4-31b-it`

## S3 — Eligibility Receipts (per-study auto-judge verdicts)

Aggregate eligibility counts are embedded above from `eligibility_summary.json`. Per-study eligibility receipts are not packaged in this final paper folder; regenerate or inspect the upstream eligibility run directory for the full receipt table.

## S4 — Strict A-core Corpus (k = 4)

| study_id | title | year | venue | doi |
| --- | --- | --- | --- | --- |
| s098 | Rapamycin fed late in life extends lifespan in genetically heterogene... | 2009 | Nature | 10.1038/nature08221 |
| s246 | Rapamycin extends murine lifespan but has limited effects on aging. | 2013 | The Journal of clinical investigation | 10.1172/jci67674 |
| s279 | Health Effects of Long-Term Rapamycin Treatment: The Impact on Mouse ... | 2015 | PloS one | 10.1371/journal.pone.0126644 |
| s327 | Effect of Combined Mycophenolate and Rapamycin Treatment on Kidney Fi... | 2022 | Frontiers in Pharmacology | 10.3389/fphar.2022.866077 |


## S5 — Effect Extraction Receipts (n = 4)

| study_id | status | metric | T_value | C_value | n_T | n_C | HR | % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s098 | parse_failed |  | None | None | None | None | None | None |
| s246 | no_numerics | median_survival | None | None | 68 | 68 | None | None |
| s279 | no_numerics | survival | None | None | None | None | None | None |
| s327 | extracted | survival | 88.78 | 48.53 | 6 | 6 | None | None |


### S5b — Inverse-variance pool (k_effects = 0, skipped = 4)

_(no pooling-ready effects in this run)_

Skipped (no inverse-variance numerics): `s098`, `s246`, `s279`, `s327`


## S6 — Risk-of-Bias Notes

Automated rule-based screen per the pre-specified eligibility ladder (rule_triage → LLM judge → deterministic merge → include-contract). The universal evidence contract requires (a) parsed_text_adequate, (b) char_count above the topic-pack minimum, (c) at least two non-title evidence quotes, (d) endpoint-term coverage, and (e) intervention or control term coverage. Strict A-core additionally demands quote-level evidence that the CURRENT experiment used the preferred species + primary intervention + control + endpoint. Each demotion is recorded with its violation list in `primary_effect_input_set_strict.json`. **A pre-publication submission would require an explicit human risk-of-bias adjudication step** (e.g. SYRCLE for animal studies, Cochrane RoB 2 for human RCTs) on top of this automated screen.

## S7 — Sentinel Recall Audit

Topic-pack-declared sentinels are: **primary** = `10.1038/nature08221`, `10.1093/gerona/glq178`, `10.7554/elife.16351`; **prior_meta** = `10.1093/gerona/glw153`.

Per-sentinel resolution (auto verdict + manual status overlay) is recorded in the upstream eligibility run directory's QA report (not packaged in this final paper folder) under the _Sentinel resolution status (manual overlay)_ table. The gate passes only when every primary sentinel either auto-contract-passes or is documented as resolved_unavailable / resolved_excluded.

Manual full-text overrides applied during this run (SHA-256-hashed; verifiable byte-for-byte):

| study_id | source_path | bytes | sha256[0:18] | reason |
| --- | --- | --- | --- | --- |
| s098 | topic_packs/manual_full_text/rapamycin/10.1038-nature08221.... | 33468 | 0cc965049100615bc... | auto retrieval (PMC/Unpaywall) failed or returned junk for this sentinel; verba... |
| s142 | topic_packs/manual_full_text/rapamycin/10.1093-gerona-glq17... | 4391 | b2d1dcbd2935357fa... | auto retrieval (PMC/Unpaywall) failed or returned junk for this sentinel; verba... |
| s284 | topic_packs/manual_full_text/rapamycin/10.15252-embr.202255... | 4067 | 5301b0b1e3e53ddf4... | auto retrieval (PMC/Unpaywall) failed or returned junk for this sentinel; verba... |
| s355 | topic_packs/manual_full_text/rapamycin/10.7554-elife.16351.... | 80239 | b08668c0e5db7c191... | auto retrieval (PMC/Unpaywall) failed or returned junk for this sentinel; verba... |


## S8 — Excluded / Demoted Studies (with reasons)

| study_id | title | demoted_from | reasons |
| --- | --- | --- | --- |
| s104 | Metformin potentiates nephrotoxicity by promoting NETosis i... | originally C | manual:resolved_excluded: Off-topic for primary lifespan corpus. Paper studies ... |
| s111 | High-content screening identifies ganoderic acid A as a sen... | A_direct_lifespan | no quote names a mouse term / no quote names a control term / quotes mention on... |
| s115 | Lifespan-extending interventions induce consistent patterns... | A_direct_lifespan | no quote names a primary intervention term |
| s119 | Long-lasting geroprotection from brief rapamycin treatment ... | A_direct_lifespan | no quote names a control term |
| s124 | The geroprotectors trametinib and rapamycin combine additiv... | A_direct_lifespan | no quote names a control term |
| s254 | Rapamycin up-regulation of autophagy reduces infarct size a... | A_direct_lifespan | no quote names a control term |
| s259 | Rapamycin, Acarbose and 17α-estradiol share common mechanis... | A_direct_lifespan | no quote names a control term |
| s261 | Diverse interventions that extend mouse lifespan suppress s... | originally C | no quote names a mouse term / no quote names a control term |
| s262 | Epigenetic aging signatures in mice livers are slowed by dw... | originally C | quotes signal secondary/omics design |
| s275 | Mice fed rapamycin have an increase in lifespan associated ... | originally C | — |
| s293 | Rapamycin doses sufficient to extend lifespan do not compro... | originally C | manual:resolved_excluded: Side-effect / mechanism study, not a primary lifespan... |
| s309 | p53 and rapamycin are additive. | A_direct_lifespan | no quote names a primary intervention term |
| s314 | SRN-901, a Novel Longevity Drug, Extends Lifespan and Healt... | originally C | manual:resolved_excluded: SRN-901 (a novel compound) is the primary interventio... |
| s323 | Rapamycin is highly effective in murine models of immune-me... | A_direct_lifespan | no quote names a mouse term / no quote names a control term |
| s343 | Immune memory-boosting dose of rapamycin impairs macrophage... | A_direct_lifespan | no quote names a primary intervention term |
| s355 | Transient rapamycin treatment can increase lifespan and hea... | A_direct_lifespan | no quote names a primary intervention term |


## S9 — Code and Data Availability

- Pipeline source: see the project repository under `agent/`, `scripts/`, and `tests/`. All counts and effect estimates are computed from the JSON receipts filed in this paper folder; no number in the main manuscript originates outside those receipts.
- Topic pack: `topic_packs/rapamycin.toml` (search vocabulary, sentinels, anchors, bibliography, strict A-core terms).
- Manual full-text overrides (if any): `topic_packs/manual_full_text/rapamycin/` (per-injection SHA-256 hashes are recorded in `manual_full_text_audit.json` alongside this supplement).
- Receipts present in this folder: `cite_audit.json`, `dual_agent_extraction_audit.json`, `effect_extractions.json`, `effect_pool.json`, `eligibility_summary.json`, `extraction_confidence.json`, `manual_full_text_audit.json`, `paper_type_decision.json`, `primary_effect_input_set_strict.json`, `readiness_report.json`, `sentinel_repair_plan.json`.

