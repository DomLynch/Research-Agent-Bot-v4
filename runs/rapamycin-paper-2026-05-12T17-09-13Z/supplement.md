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

- records identified: **502**
- title/abstract candidates: **298**
- open-access full-text located: **256**
- full-text parsed: **75**
- eligibility decisions: **{'include': 8, 'exclude': 60, 'unclear': 7, 'unavailable': 0}**
- eligible after merge: **8**
- judge model: `google/gemma-4-31b-it`

## S3 — Eligibility Receipts (per-study auto-judge verdicts)

Full receipts (decision, reviewer, confidence, mandatory fields, evidence quotes, model, timestamps) are filed in `eligibility_receipts.json` alongside this supplement. The block above lists aggregate counts; per-study rows are available in the run directory.

## S4 — Strict A-core Corpus (k = 4)

| study_id | title | year | venue | doi |
| --- | --- | --- | --- | --- |
| s086 | Rapamycin fed late in life extends lifespan in genetically heterogene... | 2009 | Nature | 10.1038/nature08221 |
| s230 | Health Effects of Long-Term Rapamycin Treatment: The Impact on Mouse ... | 2015 | PloS one | 10.1371/journal.pone.0126644 |
| s235 | Transient rapamycin treatment during developmental stage extends life... | 2022 | EMBO reports | 10.15252/embr.202255299 |
| s246 | BMAL1-dependent regulation of the mTOR signaling pathway delays aging. | 2014 | Aging | 10.18632/aging.100633 |


## S5 — Effect Extraction Receipts (n = 4)

| study_id | status | metric | T_value | C_value | n_T | n_C | HR | % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s086 | extracted | maximum_lifespan_90th_percent... | 1245.0 | 1094.0 | None | None | None | 14.0 |
| s230 | no_numerics | survival | None | None | None | None | None | None |
| s235 | extracted | median_lifespan | None | None | None | None | None | 9.6 |
| s246 | extracted | median_lifespan_months | 11.5 | 7.8 | 31 | 73 | None | 50.0 |


### S5b — Inverse-variance pool (k_effects = 1, skipped = 3)

| study_id | metric | estimate | SE | CI_low | CI_high |
| --- | --- | --- | --- | --- | --- |
| s246 | log_median_ratio | 0.3882 | 0.2144 | -0.0319 | 0.8084 |

Skipped (no inverse-variance numerics): `s086`, `s230`, `s235`


## S6 — Risk-of-Bias Notes

Automated rule-based screen per the pre-specified eligibility ladder (rule_triage → LLM judge → deterministic merge → include-contract). The universal evidence contract requires (a) parsed_text_adequate, (b) char_count above the topic-pack minimum, (c) at least two non-title evidence quotes, (d) endpoint-term coverage, and (e) intervention or control term coverage. Strict A-core additionally demands quote-level evidence that the CURRENT experiment used the preferred species + primary intervention + control + endpoint. Each demotion is recorded with its violation list in `primary_effect_input_set_strict.json`. **A pre-publication submission would require an explicit human risk-of-bias adjudication step** (e.g. SYRCLE for animal studies, Cochrane RoB 2 for human RCTs) on top of this automated screen.

## S7 — Sentinel Recall Audit

Topic-pack-declared sentinels are: **primary** = `10.1038/nature08221`, `10.1093/gerona/glq178`, `10.7554/elife.16351`; **prior_meta** = `10.1093/gerona/glw153`.

Per-sentinel resolution (auto verdict + manual status overlay) is rendered in `qa_report.md` under the _Sentinel resolution status (manual overlay)_ table. The gate passes only when every primary sentinel either auto-contract-passes or is documented as resolved_unavailable / resolved_excluded.

## S8 — Excluded / Demoted Studies (with reasons)

| study_id | title | demoted_from | reasons |
| --- | --- | --- | --- |
| s244 | Rapamycin doses sufficient to extend lifespan do not compro... | originally C | manual:resolved_excluded: Side-effect / mechanism study, not a primary lifespan... |
| s288 | Transient rapamycin treatment can increase lifespan and hea... | A_direct_lifespan | no quote names a primary intervention term |


## S9 — Code and Data Availability

- Pipeline source: see the project repository under `agent/`, `scripts/`, and `tests/`. All counts and effect estimates are computed from the JSON receipts filed in this paper folder; no number in the main manuscript originates outside those receipts.
- Topic pack: `topic_packs/rapamycin.toml` (search vocabulary, sentinels, anchors, bibliography, strict A-core terms).
- Manual full-text overrides (if any): `topic_packs/manual_full_text/rapamycin/` with audit hashes in `manual_full_text_audit.json`.
- Receipts in this folder: `candidates.json`, `eligibility_receipts.json`, `parsed_receipts.json`, `primary_effect_input_set_strict.json`, `effect_extractions.json`, `effect_pool.json`, `eligibility_summary.json`, `qa_report.md`.

## S10 — QA Report (verbatim)

# Corpus QA Report - latest

Topic: rapamycin

## Topline counts
- candidates: 298
- parsed (parsed=True): 75
- eligibility decisions: 75
  - include: 8
  - exclude: 60
  - unclear: 7
  - unavailable: 0
- declared sentinels: 4 (3 primary + 1 prior_meta)

## Per-include audit

| study_id | lane | title | yr | spec | interv | endp | ctrl | conf | chars | first evidence quote |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s086 | A | Rapamycin fed late in life extends lifespan in genetically ... | 2009 | yes | yes | yes | yes | 1.00 | 33367 | We report here that rapamycin, an inhibitor of the mTOR pathway, extends median and maxim... |
| s105 | B | Acarbose suppresses symptoms of mitochondrial disease in a ... | 2023 | yes | yes | yes | yes | 1.00 | 80000 | Furthermore, rapamycin and acarbose have additive effects in delaying neurological sympto... |
| s230 | A | Health Effects of Long-Term Rapamycin Treatment: The Impact... | 2015 | yes | yes | yes | yes | 1.00 | 54286 | At four months of age 160 mice, 80 animals per sex, began receiving mouse chow (Purina 5L... |
| s235 | A | Transient rapamycin treatment during developmental stage ex... | 2022 | yes | yes | yes | yes | 1.00 | 80000 | Rapamycin (10 mg/kg) was administered daily in two distinct temporal windows, from postna... |
| s237 | B | Rapamycin Reduces Carcinogenesis and Enhances Survival in M... | 2024 | yes | yes | yes | yes | 1.00 | 43123 | Immediately after TBI, along with untreated control groups, animals were placed on chow c... |
| s244 | C | Rapamycin doses sufficient to extend lifespan do not compro... | 2013 | yes | yes | yes | yes | 1.00 | 80000 | we tested whether rapamycin, at the same doses used to extend lifespan, affects mitochond... |
| s246 | A | BMAL1-dependent regulation of the mTOR signaling pathway de... | 2014 | yes | yes | yes | yes | 1.00 | 80000 | treatment with the mTORC1 inhibitor rapamycin increased lifespan of Bmal1−/− mice by 50% |
| s288 | C | Transient rapamycin treatment can increase lifespan and hea... | 2016 | yes | yes | yes | yes | 1.00 | 80000 | we set out to investigate whether a single three-month treatment regimen can extend lifes... |

## Sentinel-stage audit

| sentinel_id | role | stage | parsed? | elig | conf | reason / failure |
| --- | --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glq178 | primary | retrieved+candidate | yes | unclear | 1.00 | include_contract failed: char_count 4041 < 5000 |
| 10.7554/elife.16351 | primary | retrieved+candidate | yes | include | 1.00 | judge included (conf 1.00); mandatory fields confirmed |
| 10.1093/gerona/glw153 | prior_meta | retrieved+candidate | no | no-parse | - | no parsed receipt |

## Sentinel resolution status (manual overlay)

| sentinel_id | role | study_id | auto_decision | manual_status | action_required |
| --- | --- | --- | --- | --- | --- |
| 10.1038/nature08221 | primary | s086 | include | resolved_available | wire stable OA mirror or supply verified Nature PDF; until ... |
| 10.1093/gerona/glq178 | primary | s126 | unclear | resolved_unavailable | supply institutional auth or licensed OUP feed |
| 10.7554/elife.16351 | primary | s288 | include | resolved_available | judge prompt stabilisation so this paper passes the univers... |
| 10.1093/gerona/glw153 | prior_meta | s136 | no-receipt | (no manual record) |  |

## Quality flags

- (none)


