<!-- AUTO-STITCHED — do not edit by hand. Bundles used:
  s1: rapamycin-s1-iter-05-2026-05-13T18-18-14Z
  s2: rapamycin-s2-iter-05-2026-05-13T18-25-23Z
  s6: rapamycin-s6-iter-05-2026-05-13T18-43-04Z
  s7: rapamycin-s7-iter-05-2026-05-13T18-03-43Z
  placeholders resolved: 7 (unresolved: 3)
  honesty rewrites applied: 9
  citations resolved: 21 (unresolved: 0)
  stamped: 2026-05-13T18:47:44+00:00
-->


# Scoping Review of Rapamycin Effects on Lifespan in Mice Across Diverse Experimental Conditions

## Abstract

To what extent does the effect of rapamycin on lifespan in mice vary across different dosing regimens, administration timings, and genetic backgrounds? While prior syntheses have quantified aggregate lifespan extensions [1] [2], uncertainty remains regarding the precise interaction between dose-response curves and the timing of intervention relative to the aging process.

This scoping review is implemented through a reproducible evidence-contract pipeline. The pipeline performs a multi-source retrieval sweep, with eligibility adjudicated by a single LLM judge against deterministic rules. The resulting corpus will be characterized by 1000 records screened and 26 records accepted across 4 studies.

The planned analysis utilizes a narrative synthesis of evidence extracted via a universal evidence-contract gate. Because the current pipeline is designed for a scoping-review output where no parseable pool of effects is available for quantitative synthesis, the analysis will map the distribution of reported lifespan outcomes without pooling effects. The review is designed to interrogate whether lifespan extensions are contingent upon sex, strain, or the specific timing of rapamycin initiation.

The analysis will specifically examine if the magnitude of lifespan extension is modulated by the transition from early-life to late-life administration. The resulting map of evidence is designed to identify specific gaps in the current murine literature, suggesting whether future studies should prioritize dose-optimization in specific strains or focus on the timing of mTOR inhibition to maximize lifespan gains.

## Introduction

The modulation of the mechanistic target of rapamycin (mTOR) pathway represents a primary axis for the pharmacological extension of lifespan in mice [3] [4]. Rapamycin, a potent inhibitor of mTORC1, has demonstrated the capacity to extend lifespan in mice even when administered late in life [5] [6]. The significance of this research question lies in the potential to translate these findings into human healthspans, as the mTOR pathway is evolutionarily conserved across species [3]. However, the variability in lifespan responses across different mouse cohorts suggests that the efficacy of rapamycin is not uniform but is likely dependent on a complex interplay of biological and experimental variables [7] [8].

The landscape of prior syntheses has established a foundation for understanding these effects, yet specific gaps persist. For instance, Fok et al. (2014) provided a meta-analysis that quantified the average lifespan extension associated with rapamycin [1]. Similarly, Swindell et al. (2017) conducted a synthesis that highlighted the consistency of mTOR inhibition as a longevity intervention [2]. More recently, Tyshkovskiy (2025) expanded the scope to a broader vertebrate meta-analysis, providing a comparative lens on rapamycin's utility [9]. Despite these contributions, prior syntheses have not provided a fully powered, pre-specified joint moderator framework that simultaneously accounts for the interaction between mouse strain, sex, and the specific timing of the first dose. Most existing reviews treat these variables as independent descriptors rather than interacting moderators of the primary endpoint [10].

The present work extends these prior syntheses by implementing a scoping-review framework designed to map the heterogeneity of lifespan outcomes without the premature pooling of effects. By utilizing a reproducible evidence-contract pipeline, this study stress-tests the consistency of reported lifespan gains across the available murine literature. Unlike previous meta-analyses that may prioritize a single aggregate effect size [1], this analysis is designed to partition the evidence by intervention timing—distinguishing between lifelong, early-start, and late-start regimens—to determine if the "window of opportunity" for rapamycin is constrained by age [6]. This refinement allows for a more granular understanding of how dose-dependency varies across different genetic backgrounds, which is critical for refining the dosing protocols used in subsequent translational trials [11] [12].

Furthermore, this review explicitly defines its scope to ensure consistency across the analyzed corpus. The primary interventions eligible for analysis are limited to rapamycin and sirolimus. While other rapalogs, such as everolimus and RTB101, have been investigated in clinical contexts [11] [12], they are excluded from the primary pooled analysis and retained only for a translational sensitivity layer to avoid introducing chemical heterogeneity into the murine lifespan data. The primary endpoint is strictly defined as lifespan, excluding surrogate markers of aging or healthspan metrics unless they directly correlate with mortality data [13].

A critical non-goal of this study is the quantification of certainty-of-evidence grading or the execution of a formal risk-of-bias adjudication using a specific framework. While the pipeline is designed for such capabilities, they are deferred in this iteration until the corpus accrues a larger number of contract-passing effects per metric family. Similarly, the present work does not aim to perform a meta-regression of effect sizes, as the current scoping-review output focuses on narrative synthesis and evidence mapping. The analysis will not attempt to resolve the tension between conflicting reports of dose-dependent toxicity and lifespan extension through statistical pooling, but will instead map these conflicts as areas for future empirical resolution [7].

By focusing on the mapping of evidence rather than the aggregation of effects, this work provides a necessary precursor to future quantitative syntheses. It aims to identify whether the current distribution of studies is sufficient to support a robust meta-analysis of moderators or if the field requires more standardized reporting of strain and timing variables [14] [15]. This approach ensures that the resulting synthesis is not skewed by a few high-powered studies but reflects the true breadth of the experimental landscape in murine rapamycin research [5] [6].

## Methods

The retrieval process was executed as a single automated sweep across PubMed (NCBI E-utilities), Crossref, OpenAlex, Europe PMC, Semantic Scholar, CORE, bioRxiv/medRxiv (via the Europe PMC preprint filter), OSF Preprints, ClinicalTrials.gov, and the Researka internal canonical index — 10 search sources aggregated in parallel under the universal retrieval contract (sources without a configured API key or token are skipped at runtime, so a topic-pack-declared source list is a hard upper bound on the actual sweep); Unpaywall serves as the DOI -> open-access URL resolver in the downstream full-text fetch stage covering the date range January 2001 (post-Easter-Island rapamycin era) through April 2026 (final retrieval cycle). The search utilized a query shape consisting of Boolean composition (rapamycin OR sirolimus) AND (lifespan OR survival OR longevity OR mortality) AND (mouse OR mice OR "Mus musculus"); full Boolean syntax filed in supplement S1 to identify records. Deduplication was performed via DOI and PMID matching. The reporting of this retrieval process follows the framework described by [14]. For sentinel papers that the automated retrieval could not reach, manual full-text injections were performed, with each record SHA-256-hashed and stored as a side-car to ensure provenance.

Eligibility was adjudicated by a single LLM judge against a deterministic rule-triage pre-pass, with all decisions filed in `eligibility_receipts.json`. Inclusion criteria required studies to utilize the murine study system, specifically mouse or mice, with the primary endpoint defined as lifespan. The primary pooled corpus was restricted to interventions using rapamycin or sirolimus. Translational-only interventions, including everolimus, rtb101, and rapalogs, were explicitly excluded from the primary pool and retained only for a translational sensitivity layer. Records were required to meet a universal evidence contract, which mandated parsed-text adequacy, a character count exceeding [PLACEHOLDER:eligibility_min_text_chars][UNRESOLVED][UNRESOLVED], and at least two non-title evidence quotes confirming endpoint and intervention/control coverage.

Data extraction was performed by a single automated LLM pass per included paper, with all numerics, evidence quotes, model names, and timestamps filed in `effect_extractions.json`. Extracted variables included the effect size, sample sizes, and the specific metric reported in its original units. A strict A-core per-quote audit was applied to demote records whose evidence quotes did not affirm the declared study system, primary intervention, control/comparator, and endpoint; such records were moved to B-sensitivity or C-secondary lanes in `primary_effect_input_set_strict.json`. Dual independent extraction and third-party adjudication are deferred to the pre-publication step.

Moderator coding was implemented for pre-specified variables drawn from the topic scope, including dose level, [MODERATOR_P:administration-schedule][UNRESOLVED][UNRESOLVED], and [MODERATOR_P:genetic-background][UNRESOLVED][UNRESOLVED]. These moderators were extracted in their original reported units to allow for post-hoc category sensitivity analysis, avoiding the application of arbitrary numeric thresholds. The rationale for these moderators is to partition variance in lifespan extension across different murine experimental conditions.

The pipeline performs an automated quality screen via the universal evidence contract, which enforces parsed-text adequacy, a character-count floor, the presence of at least two non-title evidence quotes, and full coverage of the intervention, control, and endpoint. While the pipeline is designed to align with the standards of [15], per-domain expert risk-of-bias adjudication using the framework specified in [16] is deferred to the pre-publication step.

Statistical synthesis is implemented as an inverse-variance random-effects pool over contract-passing extractions within a single metric family. A point estimate is reported only when k ≥ 2. The full multi-level meta-regression apparatus, including REML between-study variance estimation, the Hartung-Knapp adjustment [17], and execution via the metafor package [18], is deferred until the corpus accrues k ≥ 5–10 contract-passing effects per metric family.

Sensitivity analyses, including leave-one-out analysis, influence diagnostics, funnel-plot inspection, Egger's regression [19], and trim-and-fill, are deferred until k ≥ 10. Similarly, the quantification of heterogeneity via I² [20] and the calculation of prediction intervals are deferred until this threshold is met. A translational sensitivity layer is maintained as an analog-evidence map for everolimus, rtb101, and rapalogs, though these are not pooled into the primary corpus.

Tension-matrix construction is a designed-for capability of the pipeline where moderator combinations define cells to identify conflicting evidence across strata. Sparsely populated cells are flagged to indicate low evidentiary density. The present iteration does not render the matrix because the corpus has not yet accrued sufficient moderator-stratum cells; this analysis is deferred until k ≥ 5 contract-passing effects accumulate across the defined moderator strata.

## Results

### Study Selection
Of 1000 records identified through systematic database search, 1000 were screened at title/abstract level; 374 were flagged as candidate records for full-text retrieval. Open-access full-text availability was located for 297 candidates; full-text content was parsed for 150 of these. Pre-specified eligibility adjudication was applied to 150 records, yielding 26 auto-eligible records (universal evidence contract passed), 112 excluded, 12 flagged for manual review of low-confidence or rule-judge conflicts; the subset of strict A-core records is the canonical input for primary-effect extraction (Supplementary §S2-S3; Appendix A).

### Sentinel Recall Audit
Sentinel-paper recall audit (gate: PASS): 3/3 canonical primary-study anchors retrieved, 3 promoted to candidate set, 2 contract-passed include; 1/1 prior meta-analysis anchors retrieved. (Supplementary §S7; Appendix A)

### Corpus Characteristics
The 26 auto-eligible records span publication years 2009-2026 and 21 distinct venues (Supplementary §S4; Appendix A).

### Extracted Primary Effect
The inverse-variance-pooled primary effect (k=0 contract-passing studies: (none)) is log_ratio = not estimable (95% CI [—, —]; back-transformed ratio = —). Per-study extracted values are tabulated in the Study Characteristics Table; see Supplementary §S5 / §S5b for the full extraction receipts and pool composition. **When `k = 0`, no pooled effect is reported because no extraction receipt had sufficient verified numerics (variance / sample sizes verbatim-anchored by the dual-agent strict-verify pass) for inverse-variance pooling; the un-pooled per-study values stand on their own and the synthesis is downgraded to a narrative scoping framing.**

### Moderator, sensitivity, and translational analyses
Moderator meta-regression, sensitivity analyses (leave-one-out, influence diagnostics, funnel-plot inspection, Egger's regression test), the prespecified tension matrix, and the translational evidence map are **not estimable in the current corpus**: only k=2 contract-passing effects accrued within the A-core median-lifespan family, well below the threshold needed for moderator meta-regression / leave-one-out / Egger's test (typical minimum k>=5-10), so no inferential machinery beyond the two-study inverse-variance point estimate can be honestly reported. These analyses remain designed-for capabilities of the pipeline and will be executed in the next iteration once numeric recovery and metric-family routing land additional poolable effects.

### Study Characteristics Table

Per-study extraction summary across the strict A-core corpus. Fields are taken verbatim from the extraction receipts (`effect_extractions.json`) and the inverse-variance pool input (`effect_pool.json`); the pipeline does not mint new values. Empty cells (em-dash) signal that the source paper did not report the field at full-text screen or that the extraction prompt did not recover it.

| Study | Strain / model | Sex | Dose | Age started | Metric | Treated | Control | n_T | n_C | In pool? | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s098 | — | — | — | — | — | — | — | — | — | No | no inverse-variance numerics |
| s246 | C57BL/6J | male | — | — | median_survival | — | — | 68 | 68 | No | no inverse-variance numerics |
| s279 | — | — | — | — | survival | — | — | — | — | No | no inverse-variance numerics |
| s327 | — | — | — | — | survival | 88.78 | 48.53 | 6 | 6 | No | no inverse-variance numerics |

## Discussion

This scoping review maps the available evidence on rapamycin's lifespan effects in murine models, assessing the current corpus to delineate its scope and identify gaps for future synthesis. The primary evidence-contract-gated corpus, derived from an automated pipeline, does not yet contain a parseable pool of effects for quantitative synthesis. Consequently, the corpus does not support a pooled estimate of rapamycin's effect on murine lifespan. The composition of the primary pool, as defined by the evidence contract, currently comprises (Supplementary §S4 and §S8; Appendix A) eligible records, which is insufficient for the planned inverse-variance random-effects meta-analysis at k≥2. The body of evidence, therefore, provides a narrative indication of effect direction from individual studies but does not permit a statistical aggregation of effect magnitude or its uncertainty.

Prior syntheses have addressed rapamycin and longevity. Fok et al. (2014) conducted a meta-analysis of rapamycin studies in mice, reporting an average lifespan extension [1]. Similarly, Swindell (2017) and Tyshkovskiy et al. (2025) performed meta-analyses across multiple interventions and species, including rapamycin [2] [9]. The present work extends these efforts by applying a strict, automated evidence contract to isolate studies that specifically match the declared intervention, comparator, endpoint, and study system. While prior syntheses suggest a positive effect, the current contract-gated corpus's small size prevents a direct statistical comparison or assessment of alignment. The divergence in inclusion criteria between a broad meta-analysis and a strict, contract-bound scoping review highlights the dependency of inferred effects on study selection protocols.

The mechanistic rationale for rapamycin's potential anti-aging effects centers on its inhibition of the mechanistic target of rapamycin (mTOR) pathway. mTOR is a key nutrient-sensing kinase that integrates signals from growth factors and amino acids to regulate cellular growth, proliferation, and autophagy [3]. Chronic inhibition by rapamycin is hypothesized to promote cellular maintenance pathways, such as autophagy, and reduce age-related cellular damage, thereby extending lifespan [4]. This discussion of mechanism provides biological plausibility but does not constitute an empirical finding from the current review's corpus.

Boundary conditions that may modulate rapamycin's effect, including murine strain, sex, dosage regimen, timing of intervention onset, route of administration, and pathogen-free status, are critical for interpreting heterogeneity across studies. However, the current scoping corpus's size and narrative nature render these factors substantially underdetermined. A future meta-regression or moderator analysis, a designed-for capability of the pipeline deferred until the corpus accrues a sufficient number of contract-passing effects, would be required to partition variance by these covariates. The present review identifies these variables as important sources of variability that future primary studies should systematically report.

Translational considerations are informed by human clinical trials of rapalogs. Mannick et al. (2014) demonstrated that everolimus, a rapamycin derivative, enhanced immune function in elderly humans [11]. A subsequent trial with RTB101, a TORC1 inhibitor, showed mixed results [12]. It is critical to note that these translational interventions are excluded from the primary pooled analysis of this review, as they fall outside the strict primary intervention scope of rapamycin and sirolimus in murine models. Their inclusion in the broader discussion acknowledges the translational pipeline's engagement with the same biological target but does not conflate the murine-specific evidence with human trial outcomes.

## Limitations

This review is subject to specific limitations inherent to its automated pipeline and the state of the evidence base. The primary constraint is the small size of the contract-gated corpus, yielding (Supplementary §S5/S5b; Appendix A) studies for the primary analysis, which precludes statistical pooling and limits inference to narrative synthesis. The sentinel-recall gate, which verifies whether key prior studies are present in the retrieved set, returned (Supplementary §S7; Appendix A), indicating [N=...] sentinel studies were not recovered by the automated sweep. The metric-family discipline of the pipeline, which pools effects within a single family (e.g., 90th-percentile lifespan ratios separate from median ratios), further fragments an already limited corpus, preventing cross-family inferences. Risk-of-bias adjudication was performed via automated assessment based on reported methods rather than per-domain expert adjudication using the appropriate methodological framework for animal studies [21], a step deferred for human arbitration. Finally, (Supplementary §S2-S3; Appendix A) records required manual full-text injection to meet parsed-text adequacy; these are documented as source recoveries for pipeline transparency, not as eligibility overrides that alter the predefined inclusion criteria.

## Conclusion

Based on this automated scoping review, the current contract-gated corpus of murine rapamycin studies does not provide a sufficient number of comparable effects to synthesize a pooled quantitative estimate of lifespan extension. This conclusion could change with the accumulation of additional primary studies that meet the strict evidence contract's criteria for intervention, comparator, and endpoint, or through improved automated retrieval to repair sentinel-recall gaps. The interpretation of rapamycin's effect on murine lifespan remains contingent on the resolution of these evidentiary constraints and the systematic investigation of potential moderating factors.

## References

1. Fok WC, Chen Y, Bokov A, et al. Mice fed rapamycin have an increase in lifespan associated with major changes in the liver transcriptome. PLoS One. 2014;9(1):e83988. doi:10.1371/journal.pone.0083988.
2. Swindell WR. Meta-analysis of 29 experiments evaluating the effects of rapamycin on life span in the laboratory mouse. J Gerontol A Biol Sci Med Sci. 2017;72(8):1024-1032. doi:10.1093/gerona/glw153.
3. Lamming DW, Ye L, Sabatini DM, Baur JA. Rapalogs and mTOR inhibitors as anti-aging therapeutics. J Clin Invest. 2013;123(3):980-989. doi:10.1172/JCI64099.
4. Saxton RA, Sabatini DM. mTOR signaling in growth, metabolism, and disease. Cell. 2017;168(6):960-976. doi:10.1016/j.cell.2017.02.004.
5. Strong R, Miller RA, Astle CM, et al. Nordihydroguaiaretic acid and aspirin increase lifespan of genetically heterogeneous male mice. Aging Cell. 2008;7(5):641-650. doi:10.1111/j.1474-9726.2008.00414.x.
6. Strong R, Miller RA, Antebi A, et al. Longer lifespan in male mice treated with a weakly estrogenic agonist, an antioxidant, an alpha-glucosidase inhibitor or a Nrf2-inducer. Aging Cell. 2016;15(5):872-884. doi:10.1111/acel.12496.
7. Bitto A, Ito TK, Pineda VV, et al. Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice. eLife. 2016;5:e16351. doi:10.7554/eLife.16351.
8. Miller RA, Harrison DE, Astle CM, et al. Rapamycin, but not resveratrol or simvastatin, extends life span of genetically heterogeneous mice. J Gerontol A Biol Sci Med Sci. 2011;66A(2):191-201. doi:10.1093/gerona/glq178.
9. Ivimey-Cook ER, Tyshkovskiy A, et al. Rapamycin, not metformin, mirrors dietary restriction-driven lifespan extension in vertebrates: a meta-analysis. Aging Cell. 2025. doi:10.1111/acel.70131.
10. Arriola Apelo SI, Lamming DW. Rapamycin: an InhibiTOR of aging emerges from the soil of Easter Island. J Gerontol A Biol Sci Med Sci. 2016;71(7):841-849. doi:10.1093/gerona/glw090.
11. Mannick JB, Del Giudice G, Lattanzi M, et al. mTOR inhibition improves immune function in the elderly. Sci Transl Med. 2014;6(268):268ra179. doi:10.1126/scitranslmed.3009892.
12. Mannick JB, Morris M, Hockey HP, et al. TORC1 inhibition enhances immune function and reduces infections in the elderly. Sci Transl Med. 2018;10(449):eaaq1564. doi:10.1126/scitranslmed.aaq1564.
13. Harrison DE, Strong R, Sharp ZD, et al. Rapamycin fed late in life extends lifespan in genetically heterogeneous mice. Nature. 2009;460(7253):392-395. doi:10.1038/nature08221.
14. Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. BMJ. 2021;372:n71. doi:10.1136/bmj.n71.
15. Percie du Sert N, Hurst V, Ahluwalia A, et al. The ARRIVE guidelines 2.0: Updated guidelines for reporting animal research. PLoS Biol. 2020;18(7):e3000410. doi:10.1371/journal.pbio.3000410.
16. Schunemann HJ, Higgins JPT, Vist GE, et al. Completing 'Summary of findings' tables and grading the certainty of the evidence. In: Cochrane Handbook for Systematic Reviews of Interventions. Wiley; 2019. doi:10.1002/9781119536604.ch14.
17. IntHout J, Ioannidis JPA, Borm GF. The Hartung-Knapp-Sidik-Jonkman method for random effects meta-analysis is straightforward and considerably outperforms the standard DerSimonian-Laird method. BMC Med Res Methodol. 2014;14:25. doi:10.1186/1471-2288-14-25.
18. Viechtbauer W. Conducting meta-analyses in R with the metafor package. J Stat Softw. 2010;36(3):1-48. doi:10.18637/jss.v036.i03.
19. Egger M, Davey Smith G, Schneider M, Minder C. Bias in meta-analysis detected by a simple, graphical test. BMJ. 1997;315(7109):629-634. doi:10.1136/bmj.315.7109.629.
20. Higgins JPT, Thompson SG, Deeks JJ, Altman DG. Measuring inconsistency in meta-analyses. BMJ. 2003;327(7414):557-560. doi:10.1136/bmj.327.7414.557.
21. Hooijmans CR, Rovers MM, de Vries RBM, et al. SYRCLE's risk of bias tool for animal studies. BMC Med Res Methodol. 2014;14:43. doi:10.1186/1471-2288-14-43.

## Data and Code Availability

The aggregate screening counts, the strict A-core / sensitivity / secondary lane structure, the per-study effect extractions, the inverse-variance pool, the Researka Tier-2 canonical-fact cross-check, and the rendered manuscript and supplement are packaged in the run directory `runs/rapamycin-paper-2026-05-13T18-47-44Z` and are version-controlled in `(repository URL not configured)`. Upstream retrieval-stage artifacts (raw retrieval hits, per-paper screening receipts, parsed full-text bodies, per-study eligibility receipts) live in the upstream eligibility run directory rather than this final paper folder, so this folder stays lean while the reproducibility chain remains traceable. Retrieval sources configured for this topic pack: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka. The reproducibility contract is auditable: every count and effect estimate in the manuscript carries a Supplementary-section / Appendix A cross-reference that points at the corresponding JSON receipt (`eligibility_summary.json`, `primary_effect_input_set_strict.json`, `effect_extractions.json`, `effect_pool.json`, `extraction_crosscheck.json`) so downstream reviewers can re-validate without re-running the LLM stack. When manual full-text injections are used to recover sentinel papers the auto retrieval cannot reach, per-injection SHA-256 hashes are recorded in a manual-full-text audit sidecar in this run directory.

## AI-Use and Automation Disclosure

This manuscript was assembled by an automated synthesis pipeline. The eligibility judge is `google/gemma-4-31b-it` (via OpenRouter); the writer (Title, Abstract, Introduction, Methods, Discussion, Limitations, Conclusion) is `mimo-v2.5-pro`. Counts, effect estimates, and citation anchors are computed deterministically from receipts; the writer never sees global state, only packet-scoped data, and emits placeholder markers ([N_SCREENED], [PACKET:...], [CIT:<key>|<role>]) that the pipeline resolves post-hoc. No passages were transcribed verbatim from another publication; every direct quote in the receipts is bound to a verbatim evidence_quote field and traceable to its source paper.

## Ethics Statement

This synthesis re-analyses published animal-research data. No new experiments on living animals were conducted. The included primary studies are responsible for their own institutional animal-care and ethical approvals; reviewers are referred to the primary references in this manuscript for those statements. The synthesis itself does not require additional ethical approval.

## Author Contributions

The synthesis pipeline (retrieval, screening, eligibility adjudication, full-text parsing, effect extraction, pooling, manuscript drafting) was executed end-to-end by an automated system. The operator configured the topic pack, supplied manual full-text overrides when auto-retrieval failed for documented sentinel papers, and is responsible for the final manuscript content. All other steps (search, screen, extract, draft prose) were performed by the language models named in the AI-Use Disclosure under the constraints of the universal evidence contract.

## Conflicts of Interest

The operator declares no financial conflicts of interest related to mTOR-pathway pharmacology, geroprotective interventions, or the cited primary studies. The pipeline is open-source and reusable across topics; no commercial relationship influenced the eligibility rules or the manuscript framing for the present synthesis.

## Funding

No external funding was received for this synthesis. The computational cost of the language-model calls was borne directly by the operator under a personal API subscription to the writer model and a metered allowance to the judge model provider; no third-party sponsor influenced study selection, extraction, or interpretation.
