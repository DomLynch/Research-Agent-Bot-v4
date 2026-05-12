# Systematic Synthesis of Rapamycin Effects on Murine Lifespan Across Preclinical Variables

## Abstract

To what extent does rapamycin consistently extend lifespan in murine models, and what study-level factors moderate this effect? Prior syntheses have identified a generally positive effect but report substantial heterogeneity, with uncertainty remaining about the precise roles of genetic background, sex, dose, and treatment timing [CIT:fok-2023-meta-rapamycin|prior-meta-analysis] [CIT:swindell-2017-meta|prior-meta-analysis]. The present systematic review and meta-analysis is designed to provide a more granular mapping of this heterogeneity. The corpus was assembled through a reproducible-pipeline search and screening process (no external registry record claimed), yielding [N_SCREENED] identified records, which after title/abstract and full-text screening resulted in [N_ACCEPTED] independent studies meeting inclusion criteria for the [K_STUDIES] distinct experiments included in the quantitative synthesis. The analysis will employ mixed-effects meta-regression models to partition variance in the standardized mean difference (SMD) of lifespan extension between studies. This framework is specified to test the moderating influence of murine strain, sex, drug dose, route of administration, and age at treatment initiation. A central component of this work is the construction of a tension matrix to evaluate consistency of effects across these key subgroups. The research questions guiding the moderator analysis are: Do effects differ between inbred and outbred strains? Is there evidence for sex-specific efficacy? Does the dose-response relationship plateau or attenuate? Does the timing of intervention initiation—whether in early, middle, or later life—alter the magnitude of the effect? The implications of the planned findings are intended to inform the design of future primary studies by identifying critical sources of variability and potential knowledge gaps, thereby strengthening the translational evidence base.

## Introduction

The mechanistic target of rapamycin (mTOR) signaling pathway integrates nutrient and growth factor cues to regulate fundamental cellular processes, and its inhibition has emerged as a robust experimental intervention to modulate healthspan and lifespan across species [CIT:lamming-2013-mtor|mechanism-review] [CIT:saxton-2017-mtor|mechanism-review]. In murine models, the macrolide compound rapamycin, an allosteric inhibitor of mTOR complex 1 (mTORC1), has been a cornerstone of aging research since its initial demonstration to extend mouse lifespan [CIT:harrison-2009-rapamycin|primary-study]. This finding has since been replicated in numerous studies under varying conditions [CIT:miller-2011-rapamycin|primary-study] [CIT:strong-2016-rapamycin|primary-study], solidifying rapamycin as a leading pharmacological tool for probing the biology of aging. The translational significance of this work is further underscored by investigations into rapamycin's analogs, such as everolimus and RTB101, in human immune function and aging biomarkers [CIT:mannick-2014-everolimus|clinical-trial] [CIT:mannick-2018-rtb101|clinical-trial]. However, the preclinical evidence base exhibits considerable variability in reported effect sizes, raising questions about the precise boundary conditions of rapamycin's efficacy in mice.

Prior quantitative syntheses have been instrumental in moving the field beyond narrative interpretation. The seminal meta-analysis by Swindell (2017) aggregated early studies and confirmed a statistically significant average increase in murine lifespan, while also highlighting substantial heterogeneity across experiments [CIT:swindell-2017-meta|prior-meta-analysis]. More recently, Fok et al. (2023) updated this synthesis, incorporating newer data and performing exploratory moderator analyses on variables like genetic background and sex [CIT:fok-2023-meta-rapamycin|prior-meta-analysis]. A broader cross-taxa synthesis has also examined rapamycin's effects in vertebrates, placing murine results within a comparative context [CIT:tyshkovskiy-2025-vertebrate-meta|prior-meta-analysis]. These works collectively establish that rapamycin generally extends murine lifespan, but they also note that a significant portion of the heterogeneity remains unexplained by the moderators examined. Methodological diversity in study design—including differences in housing, diet, and drug formulation—likely contributes to this variability [CIT:arriola-apelo-2016-review|narrative-review].

The present work extends this prior synthesis landscape by applying a pre-specified, multi-level meta-regression framework. Prior syntheses have provided valuable estimates of the overall effect and explored some moderators; this analysis is designed to simultaneously model a broader set of critical preclinical variables and their potential interactions within a single, powered statistical framework. The aim is to move from identifying heterogeneity to systematically mapping its sources. This is achieved by implementing a mixed-effects model that treats study-specific effects as nested within larger research contexts, allowing for a more nuanced partitioning of variance [CIT:viechtbauer-2010-metafor|method-citation]. The analysis is specifically structured to test the independent and joint moderating roles of murine strain, sex, dose, and age at intervention start—factors hypothesized a priori to be key determinants of effect size based on biological plausibility and prior empirical suggestions.

The scope of this synthesis is explicitly limited to the primary pooled analysis of rapamycin and its synonym sirolimus on the endpoint of lifespan in murine models. Translational-adjacent interventions (everolimus, RTB101, rapalogs) are retained only for contextual discussion and are not included in the quantitative pooled analysis, thereby maintaining a focused inference on the parent compound's preclinical profile. The analysis does not seek to elucidate molecular mechanisms but rather to provide the most precise estimate of effect heterogeneity contingent on study design parameters. Furthermore, this work does not evaluate lifespan extension in non-murine models or attempt to synthesize data on other healthspan metrics. By focusing on murine lifespan data, this synthesis is designed to generate clear, quantitative hypotheses for future testing and to identify where primary experimental evidence remains insufficient for confident inference.

The next step from this synthesis will be the strategic design of future primary studies. The findings are intended to highlight which specific combinations of variables have been most and least tested, thereby revealing critical gaps. For instance, if the planned moderator analysis indicates significant effect modification by age at treatment, it would justify a new generation of lifespan studies that systematically vary this parameter within a single, controlled strain. Conversely, if an expected moderator shows no influence, resources could be redirected. The ultimate goal is to refine the translational pathway by ensuring that the preclinical evidence base for rapamycin's geroprotective potential is both comprehensive and precisely understood [CIT:percie-du-sert-2020-arrive|method-citation] [CIT:hooijmans-2014-syrcle|method-citation].

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
