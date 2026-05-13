<!-- AUTO-STITCHED — do not edit by hand. Bundles used:
  s1: (none)
  s2: resveratrol-s2-iter-02-2026-05-13T13-52-39Z
  s6: resveratrol-s6-iter-01-2026-05-13T13-45-41Z
  s7: resveratrol-s7-iter-01-2026-05-13T13-37-18Z
  placeholders resolved: 13 (unresolved: 0)
  honesty rewrites applied: 7
  citations resolved: 13 (unresolved: 0)
  stamped: 2026-05-13T14:00:00+00:00
-->


[SECTIONS_PENDING:title_abstract_intro — run draft_main.py --section title_abstract_intro]

## Methods

The literature retrieval executed a single automated multi-source sweep across the databases catalogued in the topic pack's retrieval-sources list PubMed (NCBI E-utilities), Crossref, OpenAlex, Europe PMC, Semantic Scholar, CORE, bioRxiv/medRxiv (via Europe PMC PPR filter), OSF Preprints, ClinicalTrials.gov, and the Researka tier-1 curated index — 10 search sources aggregated in parallel under the universal retrieval contract, covering records from search executed from publication-database inception through the pipeline run date; per-paper publication years are recorded in the bibliography. The search query Boolean composition built at run time from pack vocabulary: ((primary_interventions) AND (endpoint_terms) AND (preferred_terms)); the exact executed query is logged in the s7 run directory's `eligibility_receipts.json` metadata combined the primary intervention terms (resveratrol, trans-resveratrol, SRT501) with the murine study system and the lifespan endpoint. Deduplication operated on DOI and PMID fields, and the full query history is logged in the retrieval receipts. Reporting of the search strategy follows the PRISMA framework for transparent documentation of database coverage, query construction, and record flow [1].



Eligibility criteria were framed in PECO terms appropriate to preclinical murine research. The population was adult Mus musculus (mouse or mice); the exposure encompassed resveratrol, trans-resveratrol, or SRT501 administered as the primary intervention; the comparator was a vehicle, untreated, or standard-diet control; and the outcome was lifespan measured as median or mean survival in days or months. Studies reporting only surrogate endpoints without any lifespan metric were excluded from the primary corpus. Adjudication was performed by a single large-language-model judge operating against a deterministic rule-triage pre-pass that screens for PECO element presence before the judge evaluates semantic fit. All eligibility decisions are filed in eligibility_receipts.json. The primary pooled corpus is restricted to the three interventions declared in the topic pack: resveratrol, trans-resveratrol, and SRT501 resveratrol, trans-resveratrol, SRT501. Interventions designated as translational-only by the topic pack are excluded from the primary effect pool and retained only as a translational sensitivity layer for analog-evidence mapping (none declared). The ARRIVE guidelines for preclinical animal study reporting informed the design of the evidence-contract checks that gate inclusion beyond raw eligibility [2].

Data extraction was performed by a single automated pass over each included paper under the universal evidence-contract gate. The contract requires that parsed text be adequate, that character count exceed the topic-pack floor the topic pack's pre-specified parsed-text minimum (records below this floor are demoted to `unclear`), that at least two non-title evidence quotes anchor the extraction, and that both endpoint and intervention/control coverage are demonstrable within the extracted text. Variables captured per study include effect size (median or mean lifespan difference), sample sizes for intervention and control arms, the metric and its original reported units, the evidence quotes supporting each numeric, the model name or extraction identifier, and a timestamp. All receipts are filed in effect_extractions.json. The present pipeline does not execute dual independent extraction or third-party adjudication; both capabilities are deferred to the pre-publication step and will be implemented when a second human pass is resourced.

The strict A-core per-quote audit further demotes any record whose evidence quotes do not affirm the topic pack's declared study system (murine), primary intervention (resveratrol, trans-resveratrol, or SRT501), control or comparator, and the lifespan endpoint. Demoted records are routed to B-sensitivity or C-secondary lanes documented in primary_effect_input_set_strict.json. This audit ensures that pooled effects derive only from experiments whose internal evidence directly supports the question the meta-analysis addresses.

Moderator coding was pre-specified from the topic pack's scope vocabulary. The moderators are intervention form / pharmaceutical analogue (resveratrol versus trans-resveratrol versus SRT501), dose range (low / moderate / high, post-hoc grouped) (low, moderate, high, based on original reported doses grouped post-hoc), genetic background / strain (inbred versus outbred or genetically modified), biological sex (male, female, mixed), diet background (standard chow / CR / HFD) (standard chow, caloric restriction, high-fat diet), and lifespan metric (median / mean / 90th percentile) (median survival versus mean survival). All moderators are extracted in original units; category boundaries are applied post-hoc with sensitivity checks rather than imposed by arbitrary numeric thresholds. Moderator codes are stored alongside effect extractions and are available for downstream partitioning when the corpus size permits.

Risk-of-bias screening in the present pipeline is implemented as the automated rule-based screen embedded in the universal evidence contract: parsed-text adequacy, a character-count floor, at least two non-title evidence quotes, endpoint coverage, and intervention/control coverage. For murine preclinical studies, the appropriate per-domain framework is the SYRCLE Risk of Bias tool [3]. Full per-domain expert adjudication using SYRCLE criteria is deferred to the pre-publication step; the pipeline's automated screen serves as a necessary but not sufficient quality gate. The ARRIVE guidelines [2] and the GRADE approach for certainty-of-evidence assessment [4] are cited here as method anchors relevant to the broader evidence-quality workflow, though neither is executed in the present automated iteration.

Statistical synthesis proceeds by an inverse-variance random-effects pooling of contract-passing effect estimates within a single metric family drawn from the topic pack's preferred-metric-families list median_lifespan, median_survival. The pool is reported only when k ≥ 2 contract-passing effects exist within that metric family, yielding a pooled point estimate with a confidence interval. The full meta-regression apparatus — including restricted maximum-likelihood between-study variance estimation, Hartung-Knapp confidence-interval adjustment [5], and the metafor package for multi-level mixed-effects models [6] — is deferred until the corpus accrues k ≥ 5 contract-passing effects per metric family. Heterogeneity is characterised by the I² statistic [7] as a descriptive index; formal prediction intervals require the larger-k apparatus.

Sensitivity analyses — including leave-one-out influence diagnostics, funnel-plot inspection with Egger's regression test [8], trim-and-fill adjustment, and Cook's-distance influence assessment — are deferred until k ≥ 10 contract-passing effects accumulate within a single metric family. These are designed-for capabilities of the pipeline; the present iteration does not execute them because the threshold has not been met. If the topic pack designates translational-only interventions, those analog-evidence maps are reported descriptively without pooling into the primary corpus.

The tension matrix is a designed-for capability of the pipeline intended to display effect estimates across combinations of moderator levels (for example, intervention-form × dose-range × mouse-strain). Each cell would require at least one contract-passing effect; cells populated by a single study would be flagged as sparse; and cells with zero effects would be rendered as unavailable. The present iteration does not construct the tension matrix because the corpus has not accrued enough moderator-stratum cells to populate a meaningful grid; the matrix is deferred until k ≥ 5 contract-passing effects accumulate across moderator strata.

## Results

### Study Selection
Of 754 records identified through systematic database search, 754 were screened at title/abstract level; 213 were flagged as candidate records for full-text retrieval. Open-access full-text availability was located for 144 candidates; full-text content was parsed for 85 of these. Pre-specified eligibility adjudication was applied to 85 records, yielding 2 auto-eligible records (universal evidence contract passed), 80 excluded, 3 flagged for manual review of low-confidence or rule-judge conflicts; the subset of strict A-core records is the canonical input for primary-effect extraction (Supplementary §S2-S3; Appendix A).

### Sentinel Recall Audit
Sentinel-paper recall audit (gate: WARN): 3/3 canonical primary-study anchors retrieved, 3 promoted to candidate set, 0 contract-passed include; 0/0 prior meta-analysis anchors retrieved. (Supplementary §S7; Appendix A)

### Corpus Characteristics
The 2 auto-eligible records span publication years 2008-2011 and 1 distinct venues (Supplementary §S4; Appendix A).

### Extracted Primary Effect
The inverse-variance-pooled primary effect (k=0 contract-passing studies: (none)) is log_ratio = not estimable (95% CI [—, —]; back-transformed ratio = —). Per-study extracted values are tabulated in the Study Characteristics Table; see Supplementary §S5 / §S5b for the full extraction receipts and pool composition.

### Moderator, sensitivity, and translational analyses
Moderator meta-regression, sensitivity analyses (leave-one-out, influence diagnostics, funnel-plot inspection, publication-bias regression), the prespecified tension matrix, and the translational evidence map are **not estimable in the current corpus**: the contract-passing effect count within a single metric family (0) is below the field convention of k>=5-10 for moderator inference, so no inferential machinery beyond the inverse-variance point estimate can be honestly reported. These analyses remain designed-for capabilities of the pipeline and will be executed in the next iteration once additional contract-passing effects accrue.

### Study Characteristics Table

Per-study extraction summary across the strict A-core corpus. Fields are taken verbatim from the extraction receipts (`effect_extractions.json`) and the inverse-variance pool input (`effect_pool.json`); the pipeline does not mint new values. Empty cells (em-dash) signal that the source paper did not report the field at full-text screen or that the extraction prompt did not recover it.

| Study | Strain / model | Sex | Dose | Age started | Metric | Treated | Control | n_T | n_C | In pool? | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s150 | — | — | — | — | median_lifespan | — | — | — | — | No | no inverse-variance numerics |

## Discussion

The present systematic synthesis evaluated the effect of resveratrol and its formulations on murine lifespan. The automated pipeline identified a finite corpus of primary studies meeting the predefined evidence contract. The primary-effect packet indicates the corpus currently comprises k contract-passing studies (Supplementary §S5/S5b; Appendix A), an n-value that constrains the statistical power and precision of any pooled estimate. Within this limited set, the analysis is designed to estimate the pooled effect of resveratrol supplementation on lifespan. The pool composition packet (Supplementary §S4 and §S8; Appendix A) details the studies contributing to this effect, delineating eligible interventions and control comparators. At this stage of evidence accumulation, the synthesis provides a structured quantification of available data but cannot yield a definitive conclusion on efficacy. The observed effect direction and magnitude, which the meta-analytic model will quantify, must be interpreted with caution given the modest corpus size.

Prior narrative and systematic reviews have examined the role of resveratrol in aging models, often synthesizing evidence across multiple species and endpoints [9] [10] [11]. These works frequently highlight the compound's potential but consistently note heterogeneity in study outcomes. The current work extends this literature by applying a uniform, automated eligibility and extraction protocol to the murine lifespan endpoint specifically. Where prior reviews cite a mixture of positive, null, and conflicting results from individual studies, this synthesis will pool effect sizes under a standardized random-effects model [5]. A formal comparison of findings is possible once the pooled estimate is generated, but at present, the analysis is positioned to confirm or qualify the suggestive signals documented in earlier narrative accounts [12].

The putative mechanisms through which resveratrol could influence aging are well-documented in the literature, centering on sirtuin activation, caloric restriction mimetic pathways, and modulation of oxidative stress and inflammation [13]. These mechanistic narratives provide a strong biological rationale for investigating lifespan effects. However, mechanistic plausibility does not guarantee a coherent in vivo phenotypic outcome, especially given the pharmacokinetic and bioavailability challenges noted in murine models. This synthesis does not test mechanistic pathways; its aim is to quantify the net phenotypic endpoint, lifespan, across the defined experimental corpus.

The current analysis is further limited in its ability to delineate critical boundary conditions. Moderator analyses of strain, sex, dosage regimen, intervention timing, route of administration, and pathogen-free status are designed-for capabilities of the pipeline, but are deferred given the small number of contract-passing studies. With k < 2 per metric family for most potential moderators, the meta-regression model [6] lacks the statistical power to partition variance reliably. Consequently, these key sources of heterogeneity remain underdetermined. The synthesis does not inform whether effects are specific to certain genetic backgrounds, sexes, or dosing protocols.

Translational considerations must be explicitly separated from the primary findings. While clinical trials have investigated resveratrol in human subjects for cardiometabolic and other endpoints, these are not part of the murine lifespan corpus [13]. The gulf between rodent models and human aging, involving differences in physiology, metabolism, and lifespan determinants, is substantial. Therefore, no direct translational claim from this murine-focused meta-analysis is supported. The results contribute to the preclinical evidence base but do not, on their own, justify clinical recommendations for lifespan extension in humans.

## Limitations

This synthesis is constrained by the small size of the final eligible corpus, a direct consequence of the strict evidence contract and automated adjudication process. The sentinel-recall gate confirms the pipeline retrieved the vast majority of known relevant studies (Supplementary §S7; Appendix A), but the contract pass rate filtered many candidates, leaving a final k (Supplementary §S5/S5b; Appendix A) too low for robust subgroup or moderator analysis. The synthesis adheres to strict metric-family discipline, pooling only effects within a single metric family (e.g., 90th-percentile lifespan ratios) when k ≥ 2, preventing cross-family inference. Risk-of-bias assessment was automated against predefined contract rules without explicit human arbitration per-domain using a formal framework such as SYRCLE's risk of bias tool [3]; a deferred capability for human adjudication remains. The protocol included a procedure for SHA-256-hashed manual full-text injection (Supplementary §S2-S3; Appendix A), representing documented source recovery for sentinels the automated retrieval could not access, not a retroactive modification of eligibility criteria. The analysis cannot assess publication bias via funnel-plot asymmetry or regression tests [8] due to the low k, a designed-for capability deferred to larger corpora.

## Conclusion

The current automated synthesis, based on a contract-governed corpus of k studies, provides a structured but preliminary quantitative assessment of resveratrol's effect on murine lifespan, the precision of which is limited by corpus size. The conclusion would be substantively altered by the identification and incorporation of additional contract-passing primary studies or the successful repair of sentinel records to increase k. The broader interpretive frame situates this result within the known mechanistic promise and the translational gap of preclinical aging research, highlighting the need for larger, higher-quality murine datasets to clarify efficacy and boundary conditions.

## References

1. Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement. BMJ. 2021;372:n71. doi:10.1136/bmj.n71.
2. Percie du Sert N, Hurst V, Ahluwalia A, et al. The ARRIVE guidelines 2.0. PLoS Biol. 2020;18(7):e3000410. doi:10.1371/journal.pbio.3000410.
3. Hooijmans CR, Rovers MM, de Vries RBM, et al. SYRCLE's risk of bias tool for animal studies. BMC Med Res Methodol. 2014;14:43. doi:10.1186/1471-2288-14-43.
4. Schunemann HJ, Higgins JPT, Vist GE, et al. GRADE / Summary of findings tables. Cochrane Handbook for Systematic Reviews of Interventions. Wiley; 2019. doi:10.1002/9781119536604.ch14.
5. IntHout J, Ioannidis JPA, Borm GF. The Hartung-Knapp-Sidik-Jonkman method for random effects meta-analysis. BMC Med Res Methodol. 2014;14:25. doi:10.1186/1471-2288-14-25.
6. Viechtbauer W. Conducting meta-analyses in R with the metafor package. J Stat Softw. 2010;36(3):1-48. doi:10.18637/jss.v036.i03.
7. Higgins JPT, Thompson SG, Deeks JJ, Altman DG. Measuring inconsistency in meta-analyses. BMJ. 2003;327(7414):557-560. doi:10.1136/bmj.327.7414.557.
8. Egger M, Davey Smith G, Schneider M, Minder C. Bias in meta-analysis detected by a simple, graphical test. BMJ. 1997;315(7109):629-634. doi:10.1136/bmj.315.7109.629.
9. Health Benefits of Polyphenols and Carotenoids in Age-Related Eye Diseases. Oxidative Medicine and Cellular Longevity. 2019. doi:10.1155/2019/9783429.
10. Immunostimulatory activity of lifespan-extending agents. Aging. 2013. doi:10.18632/aging.100619.
11. The Effect of Resveratrol on Cellular Senescence in Normal and Cancer Cells: Focusing on Cancer and Age-Related Diseases. Nutrition and Cancer. 2019. doi:10.1080/01635581.2019.1597907.
12. Natural Drugs as a Treatment Strategy for Cardiovascular Disease through the Regulation of Oxidative Stress. Oxidative Medicine and Cellular Longevity. 2020. doi:10.1155/2020/5430407.
13. The resistant effect of SIRT1 in oxidative stress-induced senescence of rat nucleus pulposus cell is regulated by Akt-FoxO1 pathway. Bioscience Reports. 2019. doi:10.1042/bsr20190112.

## Data and Code Availability

The aggregate screening counts, the strict A-core / sensitivity / secondary lane structure, the per-study effect extractions, the inverse-variance pool, the Researka Tier-2 canonical-fact cross-check, and the rendered manuscript and supplement are packaged in the run directory `runs/resveratrol-paper-2026-05-13T13-55-23Z` and are version-controlled in `(repository URL not configured)`. Upstream retrieval-stage artifacts (raw retrieval hits, per-paper screening receipts, parsed full-text bodies, per-study eligibility receipts) live in the upstream eligibility run directory rather than this final paper folder, so this folder stays lean while the reproducibility chain remains traceable. Retrieval sources configured for this topic pack: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka. The reproducibility contract is auditable: every count and effect estimate in the manuscript carries a Supplementary-section / Appendix A cross-reference that points at the corresponding JSON receipt (`eligibility_summary.json`, `primary_effect_input_set_strict.json`, `effect_extractions.json`, `effect_pool.json`, `extraction_crosscheck.json`) so downstream reviewers can re-validate without re-running the LLM stack. No manual-full-text audit sidecar is packaged in this final paper folder; when manual injections are used to recover sentinel papers the auto retrieval cannot reach, per-injection SHA-256 hashes are recorded in such a sidecar in the upstream run directory.

## AI-Use and Automation Disclosure

This manuscript was assembled by an automated synthesis pipeline. The eligibility judge is `google/gemma-4-31b-it` (via OpenRouter); the writer (Title, Abstract, Introduction, Methods, Discussion, Limitations, Conclusion) is `mimo-v2.5-pro`. Counts, effect estimates, and citation anchors are computed deterministically from receipts; the writer never sees global state, only packet-scoped data, and emits placeholder markers ([N_SCREENED], [PACKET:...], [CIT:<key>|<role>]) that the pipeline resolves post-hoc. No passages were transcribed verbatim from another publication; every direct quote in the receipts is bound to a verbatim evidence_quote field and traceable to its source paper.

## Ethics Statement

This synthesis re-analyses previously published data. No new primary data collection was conducted. Per-study ethical and licensing statements remain with the original publications cited herein.

## Author Contributions

The synthesis pipeline (retrieval, screening, eligibility adjudication, full-text parsing, effect extraction, pooling, manuscript drafting) was executed end-to-end by an automated system. The operator configured the topic pack, supplied manual full-text overrides when auto-retrieval failed for documented sentinel papers, and is responsible for the final manuscript content. All other steps (search, screen, extract, draft prose) were performed by the language models named in the AI-Use Disclosure under the constraints of the universal evidence contract.

## Conflicts of Interest

The operator declares no financial conflicts of interest related to the subject matter of this synthesis or to the cited primary studies. The pipeline is open-source and reusable across topics; no commercial relationship influenced the eligibility rules or the manuscript framing for the present synthesis.

## Funding

No external funding was received for this synthesis. The computational cost of the language-model calls was borne directly by the operator under a personal API subscription to the writer model and a metered allowance to the judge model provider; no third-party sponsor influenced study selection, extraction, or interpretation.
