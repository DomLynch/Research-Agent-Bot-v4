# Systematic Synthesis of Rapamycin Effects on Murine Lifespan Across Heterogeneous Experimental Parameters

## Abstract

To what extent does rapamycin consistently extend murine lifespan across varying experimental conditions, and how do study-level moderators—such as genetic background, sex, dose, treatment initiation timing, and route of administration—shape this effect? Prior quantitative syntheses have aggregated data on mTOR inhibitors [CIT:fok-2023-meta-rapamycin|prior-meta-analysis] [CIT:swindell-2017-meta|prior-meta-analysis], yet substantial heterogeneity remains unresolved, limiting confident translation. This work addresses that gap through a reproducible-pipeline meta-analysis (reported against PRISMA 2020 where applicable, with no external registry record claimed) designed to partition variance by these key moderators.

The planned analysis will systematically screen the literature to derive a corpus of primary murine lifespan studies involving rapamycin or its prodrug sirolimus. All screening and extraction stages will be reported using PRISMA 2020 guidelines [CIT:page-2020-prisma|method-citation], yielding quantifiable counts for [N_SCREENED], [N_ACCEPTED], and [K_STUDIES]. Eligibility is restricted to murine models; translational-only agents like everolimus or RTB101 are excluded from primary pooled synthesis but may inform sensitivity layers [CIT:mannick-2014-everolimus|clinical-trial] [CIT:mannick-2018-rtb101|clinical-trial].

The core analysis employs a random-effects framework to estimate the pooled effect of rapamycin on lifespan extension, acknowledging expected between-study variance [CIT:viechtbauer-2010-metafor|method-citation]. Mixed-effects meta-regression models are specified to test pre-specified moderators as categorical or continuous covariates. A tension matrix is designed to quantify interaction effects, such as whether the impact of dose differs between sexes or whether early-onset treatment yields a larger effect than late-onset treatment.

This framework is designed to estimate several boundary conditions. Does the effect magnitude depend on mouse strain or genetic model (e.g., heterogeneous vs. inbred cohorts)? How does lifespan extension differ between male and female mice? Is there a dose-response relationship, and does it plateau or diminish at higher doses? Furthermore, does initiating rapamycin treatment early in life produce a distinct effect profile compared to treatment beginning in later adulthood?

The planned findings will provide the most detailed moderator landscape to date. However, their definitive interpretation would be strengthened by future studies explicitly designed as factorial experiments to test interaction hypotheses suggested by this synthesis, particularly around sex-by-dose and timing-by-strain interactions.

## Introduction

The mechanistic target of rapamycin (mTOR) pathway is a central integrator of nutrient sensing, growth, and cellular metabolism. Its pharmacological inhibition by rapamycin has emerged as one of the most consistent interventions to extend lifespan in murine models [CIT:harrison-2009-rapamycin|primary-study] [CIT:strong-2008-itp|primary-study] [CIT:strong-2016-rapamycin|primary-study]. This finding has catalyzed extensive research into rapamycin as a potential geroprotective agent. However, the magnitude of the effect reported across studies is not uniform, exhibiting considerable heterogeneity. Understanding the sources of this heterogeneity is critical for evaluating the intervention's robustness, defining its translational potential, and guiding future mechanistic and preclinical work.

The research landscape includes prior quantitative syntheses that have begun to address this variability. Swindell (2017) conducted a meta-analysis focusing on the effect of rapamycin on lifespan in mice, reporting a positive overall effect but noting significant variation across studies [CIT:swindell-2017-meta|prior-meta-analysis]. More recently, Fok et al. (2023) performed a meta-analysis encompassing a broader set of mTOR inhibitors, confirming the lifespan extension in murine models while highlighting the need for subgroup analyses [CIT:fok-2023-meta-rapamycin|prior-meta-analysis]. These prior syntheses have established the foundational evidence for rapamycin's efficacy. Nonetheless, specific moderator variables—particularly the interplay between genetic background, biological sex, and treatment regimen—have not been fully characterized in a single, powered framework.

The present work extends and refines these prior syntheses. Its contribution is a pre-specified, joint moderator analysis designed to map the effect of rapamycin on murine lifespan across a multi-dimensional parameter space. This approach moves beyond main-effect estimation to model interactions among key experimental covariates. For instance, it is designed to test whether the efficacy of rapamycin is moderated by mouse strain, a variable linked to baseline healthspan and drug metabolism [CIT:miller-2011-rapamycin|primary-study]. Similarly, it will estimate the consistency of effects between sexes, an important variable for translational assessment [CIT:bitto-2016-rapamycin|primary-study]. The analysis also scrutinizes treatment parameters, including dose and the timing of initiation relative to the mouse lifespan, which prior narrative reviews have identified as critical but variably reported factors [CIT:arriola-apelo-2016-review|narrative-review].

The scope of this synthesis is explicitly focused on the direct lifespan endpoint in murine models treated with rapamycin or its prodrug sirolimus. It employs rigorous methodological standards, including adherence to PRISMA 2020 [CIT:page-2020-prisma|method-citation] and SYRCLE risk-of-bias tools for animal studies [CIT:hooijmans-2014-syrcle|method-citation]. The meta-analytic models will utilize methods robust to small-study effects, such as the Hartung-Knapp-Sidik-Jonkman adjustment [CIT:hartung-knapp|method-citation], and assess publication bias via funnel plot asymmetry tests [CIT:egger-1997-funnel|method-citation]. The strength of evidence will be evaluated following frameworks for preclinical research [CIT:schunemann-grade|method-citation].

Several explicit non-goals define the boundaries of this work. It does not encompass secondary endpoints such as tumor incidence, cognitive decline, or frailty scores unless they are reported alongside lifespan. It excludes human clinical trial data on immune or functional outcomes, though such trials provide important context [CIT:mannick-2014-everolimus|clinical-trial] [CIT:mannick-2018-rtb101|clinical-trial]. The synthesis also excludes studies on other rapalogs not directly compared in the primary murine lifespan corpus. Finally, while the mechanistic rationale involves mTOR complex inhibition [CIT:lamming-2013-mtor|mechanism-review] [CIT:saxton-2017-mtor|mechanism-review], this work does not directly measure pathway biomarkers; it is an analysis of the ultimate phenotypic outcome. By concentrating on a well-defined set of pre-specified moderator questions within a murine rapamycin corpus, this synthesis is designed to quantify the landscape of heterogeneity and provide a more precise foundation for subsequent experimental designs.

## Methods

This synthesis will be implemented using a reproducible evidence-contract pipeline and is reported against PRISMA 2020 where applicable [CIT:page-2020-prisma|method-citation]. The search strategy will query [PLACEHOLDER:databases] from [PLACEHOLDER:date-range]. The query-term structure will combine intervention terms (e.g., rapamycin, sirolimus, mTOR inhibitor) with lifespan-related outcomes and model organisms (e.g., survival, longevity, mouse, mice). The full query syntax is available as a [PLACEHOLDER:query-terms].

Eligibility will be defined using a PECO framework. The population is adult or aged mice (Mus musculus). The eligible interventions for the primary pooled analysis are limited to rapamycin and its synonym sirolimus. Translational-only interventions, specifically everolimus, RTB101, rapalogs, and rapalogues, are explicitly excluded from the primary corpus. The comparator is any control group (e.g., vehicle, standard diet). The primary outcome is lifespan, quantified as median or mean survival, survival curves, or mortality risk ratios. Studies must be primary experimental research [CIT:strong-2009-rapamycin|primary-study] [CIT:strong-2016-rapamycin|primary-study].

Data extraction will target original reported units for key variables: lifespan effect (e.g., percent change in median lifespan, hazard ratio), drug dose (mg/kg/day or dietary concentration in ppm), administration route, duration of treatment, mouse strain, sex, and age at treatment initiation. Extraction will be performed with independent dual extraction; disagreements will be resolved by consensus or, if necessary, by consulting a third party. Any post-hoc categorization of continuous variables (e.g., dose) will be justified a priori and validated with sensitivity analyses using the original continuous data.

Moderator coding will map pre-specified variables to explain heterogeneity. The moderators are [MODERATOR_P:intervention] (rapamycin vs. sirolimus), [MODERATOR_P:dose] (using original reported units), [MODERATOR_P:sex] (male, female, mixed), [MODERATOR_P:genetic_background] (inbred strain, hybrid, other), and [MODERATOR_P:treatment_initiation_age] (young, adult, aged). Each moderator is chosen based on prior mechanistic [CIT:lamming-2013-mtor|mechanism-review] and empirical [CIT:harrison-2009-rapamycin|primary-study] evidence suggesting potential interaction with rapamycin's effects on lifespan.

Risk of bias for each included animal-intervention study will be assessed using the SYRCLE risk-of-bias tool [CIT:hooijmans-2014-syrcle|method-citation]. Domains include sequence generation, baseline characteristics, allocation concealment, random housing, blinding of caregivers and outcome assessors, incomplete outcome data, and selective outcome reporting. Each domain will be rated as low, high, or unclear risk of bias. Disagreements in assessment will be resolved through discussion.

The statistical synthesis will employ a multi-level random-effects meta-regression model. The model will include random intercepts for study-ID and outcome-measure-within-study to account for dependency. Fixed-effects terms will include the pre-specified moderators. The restricted maximum likelihood (REML) estimator will be used for between-study variance, with the Hartung-Knapp adjustment for confidence intervals to address potential small-sample bias [CIT:hartung-knapp|method-citation]. The analysis will be conducted in R using the metafor package [CIT:viechtbauer-2010-metafor|method-citation]. Heterogeneity will be quantified using the I² statistic and prediction intervals [CIT:higgins-2003-i2|method-citation].

Sensitivity analyses will include leave-one-out analysis, influence diagnostics (e.g., Cook's distance), and the inspection of funnel plots for asymmetry, with Egger's regression test to formally assess publication bias [CIT:egger-1997-funnel|method-citation]. A pre-specified translational sensitivity layer will map the evidence for translational-only interventions (e.g., everolimus, RTB101) on relevant healthspan or survival endpoints in mouse models, but will not pool these estimates with the primary rapamycin/sirolimus corpus.

The tension-matrix construction will use the moderator combinations to define analytical cells. For example, a cell might represent "male mice, adult treatment initiation, high-dose rapamycin." The matrix will plot the estimated effect size against the moderator levels for populated cells. Sparsely populated cells (e.g., [PLACEHOLDER:minimum-studies-per-cell]) will be flagged to indicate low confidence in those specific estimates and to guide recommendations for future empirical work.

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
counts and effect estimates below come directly from the receipts filed
alongside this document; the prose above does NOT mint new numbers.

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

- Discussion / Conclusion / Limitations / References sections have no
  writer yet; out of scope for this pipeline pass.
- Sentinel-recall gate is WARN: Harrison 2009 / Bitto 2016 retrieval
  gaps remain. Miller 2011 is manually resolved as unavailable.
- k_studies = 1 for the primary effect; single-study extracted effect,
  not a pooled meta-analysis.
- Risk-of-bias adjudication is automated; pre-publication submission
  requires explicit human review.
