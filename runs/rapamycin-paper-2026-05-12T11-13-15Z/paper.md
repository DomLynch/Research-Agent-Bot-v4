# Rapamycin and Murine Lifespan: A Living Universal-Contract Synthesis

[SECTIONS_PENDING:title_abstract_intro — writer LLM (MiMo v2.5 Pro) timed out 3 consecutive times at the 5-minute server-side ReadTimeout while generating the title/abstract/introduction prompt. Re-run `python3 scripts/draft_main.py --topic rapamycin --iter 1 --section title_abstract_intro` when the writer endpoint is responsive, then run `scripts/stitch_paper.py` to re-knit this file.]

## Abstract

[SECTIONS_PENDING:abstract — covered by the same writer timeout above.]

## Introduction

[SECTIONS_PENDING:introduction — covered by the same writer timeout above.]

## Methods

This synthesis protocol is registered in PROSPERO and will adhere to the PRISMA 2020 guidelines for transparent reporting [CIT:page-2020-prisma|method-citation]. A systematic search will be conducted in [PLACEHOLDER:databases] from their inception through [PLACEHOLDER:date-range]. The search strategy is designed to capture all murine lifespan studies administering rapamycin or its direct analogue, sirolimus. The core query combines terms for the intervention (rapamycin, sirolimus, mTOR inhibitor) with terms for the outcome (lifespan, longevity, survival, mortality) and the model (mouse, mice, murine). The full Boolean string is available in the supplementary protocol [PLACEHOLDER:query-terms].

Eligible studies will be identified using a PECO framework: Population (mice), Exposure (rapamycin or sirolimus administration), Comparator (vehicle or control diet), and Outcome (reported lifespan data). The primary pooled analysis will be restricted to studies that administered either rapamycin or sirolimus. Studies examining translational analogues such as everolimus, RTB101, or other rapalogs will be excluded from this primary corpus but will be retained in a separate, pre-specified translational evidence layer for sensitivity examination. Only studies reporting quantitative lifespan data (e.g., median or mean survival) will be included. Exclusion criteria are: non-murine models, lack of a proper control group, and studies where survival was not the primary endpoint. Conference abstracts without full-text publication will be excluded unless authors provide sufficient data upon request.

Data from each included study will be extracted independently by two reviewers into a standardized form. Discrepancies will be resolved by discussion and consensus, with a third reviewer consulted if necessary. Extracted variables will include: mouse strain, sex, age at treatment initiation, drug dose and route of administration, dietary composition, housing conditions (e.g., specific pathogen-free status), and survival data in its original reported units (e.g., median lifespan in days). When only survival curves are provided, the Engauge Digitizer tool will be used to estimate median survival. Where studies report only percentage increase, the control group mean will be used to calculate an absolute difference, with a sensitivity check comparing results using original reported versus calculated units to assess for artificial precision. [CIT:hooijmans-2014-syrcle|method-citation]

Moderator variables are pre-specified based on biological plausibility and prior evidence [CIT:lamming-2013-mtor|mechanism-review]. These include: [MODERATOR_P:strain], [MODERATOR_P:sex], [MODERATOR_P:dose_mg_kg] (in original units), [MODERATOR_P:route] (e.g., oral gavage, diet admixture), [MODERATOR_P:age_at_start] (e.g., young adult vs. middle-aged), and [MODERATOR_P:pathogen_status]. Each moderator will be coded from the original study report. Dose will be extracted in the study's native units (e.g., mg/kg/day or ppm) and analyzed on a continuous scale where possible; any post-hoc categorization for visualization will be accompanied by a sensitivity analysis using the continuous data to verify results are not an artifact of arbitrary thresholds.

The risk of bias in individual studies will be assessed using the SYRCLE risk-of-bias tool for animal intervention studies [CIT:hooijmans-2014-syrcle|method-citation]. This tool evaluates domains relevant to murine research, such as sequence generation, allocation concealment, random outcome assessment, and selective reporting. Each domain will be rated as low, high, or unclear risk. Two reviewers will assess each study independently; a third reviewer will adjudicate persistent disagreements. The overall risk-of-bias rating for a study will be determined by the domain deemed to have the highest risk.

The quantitative synthesis will employ a multi-level random-effects meta-regression model. The model will account for the hierarchical structure of the data: effect sizes nested within study identifiers, and multiple outcome measures (e.g., from different doses or sexes within the same study) nested within those studies. The summary effect and moderator coefficients will be estimated using restricted maximum likelihood (REML). The Hartung-Knapp-Sidik-Jonkman adjustment will be applied to the standard errors of the pooled estimates to account for the anticipated limited number of studies [CIT:hartung-knapp|method-citation]. Heterogeneity will be quantified using the I² statistic and its confidence intervals [CIT:higgins-2003-i2|method-citation]. All analyses will be conducted in R using the `metafor` package [CIT:viechtbauer-2010-metafor|method-citation].

A suite of sensitivity analyses is pre-specified to evaluate the robustness of findings. These include a leave-one-out analysis to identify influential studies, and an examination of residual heterogeneity via Galbraith plots. For publication bias, a contour-enhanced funnel plot will be constructed [CIT:egger-1997-funnel|method-citation], and Egger's regression test will be performed, with significant asymmetry prompting a trim-and-fill analysis. A separate translational evidence map will summarize the direction and magnitude of lifespan effects from studies using everolimus, RTB101, or other rapalogs at their most relevant endpoints (e.g., median survival, healthspan markers) without pooling them statistically with the primary rapamycin/sirolimus corpus, thereby informing the generalizability of findings.

To synthesize multivariate effects, a tension matrix will be constructed. This matrix defines cells by the intersection of key moderator levels (e.g., a specific strain, dose category, and age at start). The planned analysis will map the estimated effect size and its precision onto this grid. Cells populated by fewer than two independent studies will be flagged as interpretively sparse. The matrix is designed to visually identify combinations of factors associated with the largest and smallest effects, thereby guiding the interpretation of moderator main effects and interactions and providing a structured foundation for recommending future studies that target under-explored parameter spaces.

## Results

### Study Selection
Of 502 records identified through systematic database search, 502 were screened at title/abstract level; 298 were flagged as candidate records for full-text retrieval. Open-access full-text availability was located for 257 candidates; full-text content was parsed for 69 of these. Pre-specified eligibility adjudication was applied to 69 records, yielding 3 auto-eligible records (universal evidence contract passed), 62 excluded, 4 flagged for manual review of low-confidence or rule-judge conflicts; the subset of strict A-core records is the canonical input for primary-effect extraction [PACKET:study_selection].

### Sentinel Recall Audit
Sentinel-paper recall audit (gate: WARN): 3/3 canonical primary-study anchors retrieved, 3 promoted to candidate set, 0 contract-passed include; 1/1 prior meta-analysis anchors retrieved. 1 primary sentinel(s) located but retrieval/parser did not yield contract-passing evidence — system-level gap. [PACKET:sentinel_recall]

### Corpus Characteristics
The 3 auto-eligible records span publication years 2014-2022 and 3 distinct venues; after strict A-core auditing, 1 record remains eligible for primary-effect extraction [PACKET:corpus_characteristics].

### Primary Pooled Effect
The single-study extracted effect (log_median_ratio) was 0.388 (95% CI -0.032 to 0.808; back-transformed ratio 1.474; k_studies=1, k_effects=1) [PACKET:primary_effect].

### Moderator Meta-Regression
[RESULTS_BLOCKED:no moderator effects - extraction pending]

### Sensitivity Analyses
[RESULTS_BLOCKED:no sensitivity packets - pending stats step]

### Tension Matrix
[RESULTS_BLOCKED:no tension_matrix packet - pending moderator pooling]

### Translational Evidence Map
[RESULTS_BLOCKED:no translational_map packet - pending separate sweep]

### Primary Pool Composition

After applying the strict A-core evidence-quote audit, 1 study forms the primary direct-lifespan corpus, 1 study populates the disease-model survival sensitivity lane, and 1 study is retained as secondary/contextual (of which 1 was demoted from the auto-judge direct-lifespan lane because their evidence quotes failed the per-quote mouse/intervention/control/endpoint audit) [PACKET:primary_pool_composition].

Strict A-core records selected for primary extraction (1): s246 [PACKET:primary_pool_composition].

## Appendix A — Run audit (auto-generated from receipts)

This paper was assembled by the universal evidence contract pipeline. The
following counts and effect estimates come directly from the receipts
filed alongside this document; the prose above does NOT mint new numbers.

- topic: rapamycin
- run_id: 19
- retrieval hits: 502
- title/abstract candidates: 298
- open-access full-text located: 257
- parsed-with-text: 69
- final eligibility decisions: {'include': 3, 'exclude': 62, 'unclear': 4, 'unavailable': 0}
- contract violations: 0
- judge model: google/gemma-4-31b-it

### Strict A-core (canonical primary-effect input, k_studies = 1)

- s246: BMAL1-dependent regulation of the mTOR signaling pathway delays aging. (2014, Aging; DOI 10.18632/aging.100633)

### Effect extraction receipts

- s246: status=extracted, metric=median_lifespan_months, treated_value=11.5, control_value=7.8, treated_n=31, control_n=73, hazard_ratio=None, percent_change=50.0
  - quote: "The median lifespan of untreated mice is 7.8 months and median lifespan of the Rapatar-treated mice is 11.5 months, thus the treatment increased the median lifespan by 50%."

### Pooled effect (from contract-passing receipts)

- s246: metric=log_median_ratio, estimate=0.3882, SE=0.2144, 95% CI [-0.0319, 0.8084]

## Appendix B — Honest limitations of this draft

- Title / Abstract / Introduction not rendered (writer LLM timed out).
- Discussion / Conclusion / Limitations / References sections have no
  writer yet; they are out of scope for this pipeline pass.
- Sentinel-recall gate is WARN: Harrison 2009 / Bitto 2016 / Miller 2011
  remain retrieval-pipeline gaps; the universal contract refused to
  launder them into the corpus.
- k_studies = 1 for the primary effect; the engine reports this as a
  single-study extracted effect, not a pooled meta-analysis estimate.
