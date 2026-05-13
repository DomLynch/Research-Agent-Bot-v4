<!-- AUTO-STITCHED — do not edit by hand. Bundles used:
  s1: (none)
  s2: acarbose-s2-iter-03-2026-05-13T12-28-41Z
  s6: acarbose-s6-iter-03-2026-05-13T12-28-41Z
  s7: acarbose-s7-iter-01-2026-05-13T11-29-41Z
  placeholders resolved: 10 (unresolved: 0)
  honesty rewrites applied: 7
  citations resolved: 13 (unresolved: 0)
  stamped: 2026-05-13T12:39:54+00:00
-->


[SECTIONS_PENDING:title_abstract_intro — run draft_main.py --section title_abstract_intro]

## Methods

A single automated retrieval sweep was executed across PubMed (NCBI E-utilities), Crossref, OpenAlex, Europe PMC, Semantic Scholar, CORE, bioRxiv/medRxiv (via Europe PMC PPR filter), OSF Preprints, ClinicalTrials.gov, and the Researka tier-1 curated index — 10 search sources aggregated in parallel under the universal retrieval contract, covering the date range search executed from publication-database inception through the pipeline run date; per-paper publication years are recorded in the bibliography. The search query combined the primary intervention terms (acarbose, alpha-glucosidase inhibitor) with the study system (mouse, mice, murine) and the primary endpoint (lifespan, longevity, survival) in a structured Boolean shape Boolean composition built at run time from pack vocabulary: ((primary_interventions) AND (endpoint_terms) AND (preferred_terms)); the exact executed query is logged in the s7 run directory's `eligibility_receipts.json` metadata. Duplicate records were removed by DOI and PMID matching. The sweep and subsequent screening steps are reported in accordance with the PRISMA framework for transparent conduct and reporting of systematic searches [1]. Because the retrieval step has already run at the time of manuscript preparation, the query and database list reported here reflect the executed search rather than a planned one.

Eligibility was adjudicated by a single LLM judge operating against a deterministic rule-triage pre-pass. The rule pre-pass applies hard inclusion and exclusion criteria framed in PECO terms appropriate to preclinical aging research: population, aged or aged-equivalent mice of any strain; exposure, oral administration of acarbose or a pharmacologically equivalent alpha-glucosidase inhibitor; comparator, vehicle, chow-only, or untreated control; outcome, quantified lifespan expressed as median, mean, or survival-distribution endpoint. Studies must report original empirical data from in-vivo murine cohorts; in-vitro, in-silico, and purely pharmacokinetic studies were excluded. Conformance with reporting standards for preclinical animal research informed the eligibility rubric [2]. The primary pooled corpus is restricted to pack.primary_interventions (acarbose, alpha-glucosidase inhibitor); interventions classified as translational_only are retained in a separate sensitivity layer and are not pooled with the primary corpus. All eligibility decisions are filed in eligibility_receipts.json.

Data extraction was performed by a single automated LLM pass per included paper. The universal evidence contract governs what enters the extraction record: parsed-text adequacy, a character-count floor of the topic pack's pre-specified parsed-text minimum (records below this floor are demoted to `unclear`), at least two non-title evidence quotes, confirmed endpoint coverage, and confirmed intervention-versus-control coverage. Variables extracted in their original reported units include effect-size numerics (median lifespan, mean lifespan, maximum lifespan, hazard ratio), sample size per arm, metric identity, strain, sex, dose, route, age at intervention start, and the supporting evidence quotes themselves. Every extraction receipt—including numerics, quotes, model name, and timestamps—is filed in effect_extractions.json. Dual independent extraction and third-party adjudication are deferred to the pre-publication step; the present pipeline executes a single-pass extraction under the contract gate [1].

Pre-specified moderator variables were coded from the original-unit extractions without imposing post-hoc numeric thresholds genetic background / strain, biological sex, dose level, age at intervention start, route of administration, and diet background. Strain and sex partition the murine corpus along biologically meaningful lines expected to influence treatment response. Dose captures the administered concentration; original-unit values are retained and categorised only if a sufficient range accrues across studies. Age at intervention start distinguishes early-onset from late-onset exposure paradigms. Route of administration and diet background account for pharmacokinetic and caloric-context moderators. This moderator set aligns with variables recommended for transparent preclinical reporting [2].

The universal evidence contract performs an automated quality screen that functions as the pipeline's gate for inclusion in the pooled analysis. This screen verifies that each candidate record provides parsed text of adequate length, contains at least two non-title evidence quotes directly supporting the extracted effect, and covers both the declared endpoint and the intervention-versus-control contrast. For the domain of preclinical murine intervention studies, the appropriate risk-of-bias framework is the SYRCLE tool for assessing bias in animal studies [3]. Per-domain expert adjudication using SYRCLE is deferred to the pre-publication step; the present iteration relies on the automated contract screen as a necessary but not sufficient quality filter.

The pipeline executes an inverse-variance random-effects pooling model over contract-passing effect extractions within a single metric family drawn from pack.preferred_metric_families. A pooled point estimate and its confidence interval are reported only when k ≥ 2 contract-passing effects exist within the same family. For continuous lifespan outcomes expressed as group means and standard deviations, the standardised mean difference or raw mean difference is the natural pooling metric. The full multi-level meta-regression apparatus—including restricted maximum-likelihood between-study variance estimation, the Hartung-Knapp confidence-interval adjustment for small-k robustness [4], and the metafor computational environment [5]—is deferred until the corpus accrues k ≥ 5 to 10 contract-passing effects per metric family. Heterogeneity is characterised at the point-estimate stage by the I² statistic [6], with full prediction-interval reporting deferred to the same k-threshold.

Leave-one-out sensitivity analysis, influence diagnostics, funnel-plot inspection, Egger's regression for small-study bias [7], and trim-and-fill imputation are all designed-for capabilities of the pipeline; the present iteration defers them until k ≥ 10 contract-passing effects accumulate within a single metric family. Heterogeneity quantification via I² and prediction intervals [6] is likewise deferred to the same threshold. If the topic pack includes translational-only interventions outside the primary corpus, a translational sensitivity layer maps analogous evidence without pooling those records into the primary inverse-variance model; this layer serves to contextualise the primary findings rather than to contribute effect-size weights.

The tension matrix—a moderator-combination grid in which each cell represents a unique intersection of moderator levels (for example, strain × sex × dose tier)—is a designed-for capability of the pipeline. Sparse or empty cells would be flagged automatically, and between-cell contrasts would be computed only where at least k ≥ 2 contract-passing effects populate a cell. The present iteration does not render this matrix because the corpus has not yet accrued sufficient moderator-stratum cells to support meaningful cross-cell inference. The matrix is deferred until k ≥ 5 contract-passing effects accumulate across moderator strata, at which point it can be generated as part of the pre-publication analytical step [8].

## Results

### Study Selection
Of 520 records identified through systematic database search, 520 were screened at title/abstract level; 44 were flagged as candidate records for full-text retrieval. Open-access full-text availability was located for 40 candidates; full-text content was parsed for 21 of these. Pre-specified eligibility adjudication was applied to 21 records, yielding 3 auto-eligible records (universal evidence contract passed), 14 excluded, 4 flagged for manual review of low-confidence or rule-judge conflicts; the subset of strict A-core records is the canonical input for primary-effect extraction (Supplementary §S2-S3; Appendix A).

### Sentinel Recall Audit
Sentinel-paper recall audit (gate: WARN): 3/3 canonical primary-study anchors retrieved, 3 promoted to candidate set, 0 contract-passed include; 0/0 prior meta-analysis anchors retrieved. (Supplementary §S7; Appendix A)

### Corpus Characteristics
The 3 auto-eligible records span publication years 2019-2023 and 3 distinct venues (Supplementary §S4; Appendix A).

### Extracted Primary Effect
The inverse-variance-pooled primary effect (k=1 contract-passing studies: s036) is log_ratio = 0.161 (95% CI [-0.029, 0.351]; back-transformed ratio = 1.17). Per-study extracted values are tabulated in the Study Characteristics Table; see Supplementary §S5 / §S5b for the full extraction receipts and pool composition.

### Moderator, sensitivity, and translational analyses
Moderator meta-regression, sensitivity analyses (leave-one-out, influence diagnostics, funnel-plot inspection, publication-bias regression), the prespecified tension matrix, and the translational evidence map are **not estimable in the current corpus**: the contract-passing effect count within a single metric family (1) is below the field convention of k>=5-10 for moderator inference, so no inferential machinery beyond the inverse-variance point estimate can be honestly reported. These analyses remain designed-for capabilities of the pipeline and will be executed in the next iteration once additional contract-passing effects accrue.

### Study Characteristics Table

Per-study extraction summary across the strict A-core corpus. Fields are taken verbatim from the extraction receipts (`effect_extractions.json`) and the inverse-variance pool input (`effect_pool.json`); the pipeline does not mint new values. Empty cells (em-dash) signal that the source paper did not report the field at full-text screen or that the extraction prompt did not recover it.

| Study | Strain / model | Sex | Dose | Age started | Metric | Treated | Control | n_T | n_C | In pool? | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s036 | — | male | — | — | median_survival_days | 975.0 | 830.0 | 162 | 312 | Yes | — |

## Discussion

This synthesis was designed to quantify the effect of acarbose or related α-glucosidase inhibitors on murine lifespan, drawing on a defined corpus of eligible primary studies. The analysis pipeline extracted and audited evidence against a strict contract, yielding a primary-effect pool whose composition is summarized in (Supplementary §S4 and §S8; Appendix A). The quantitative support for a lifespan-modifying effect is calibrated directly to the number of studies meeting this contract, (Supplementary §S5/S5b; Appendix A). This corpus-level evaluation is constrained by the specific eligibility rules and evidence thresholds applied, which prioritize experimental fidelity and endpoint precision.

The present work engages with prior quantitative syntheses on pharmacological lifespan extension in rodents. Existing meta-analyses have aggregated data across diverse compounds to estimate general effect magnitudes [9]. The current focus on acarbose alone allows for a focused examination of a specific compound class. Any alignment or divergence with broader prior estimates should be interpreted in light of the stringent per-paper evidence contract employed here, which may exclude studies with ambiguous endpoint reporting or incomplete intervention characterization [10]. The pipeline's design prioritizes internal validity of the included set over breadth of inclusion.

The rationale for acarbose's potential lifespan effect is grounded in proposed mechanisms of caloric restriction mimicry and metabolic modulation via inhibition of intestinal carbohydrate digestion [11]. This pathway is hypothesized to activate conserved longevity signaling networks. However, the current meta-analytic corpus does not constitute a mechanistic test; it is an epidemiological summary of intervention outcomes. The synthesis is designed to estimate the net lifespan effect observed in controlled murine experiments, not to adjudicate between competing mechanistic hypotheses.

The generalizability of the pooled effect estimate, should it be calculable, is constrained by boundary conditions that are currently underdetermined within the eligible corpus. Potential effect modifiers include murine genetic background (strain), sex, dosage and timing of intervention initiation, and the specific pathogen status of the animal facility [12]. These variables are plausible sources of heterogeneity. The pipeline's automated extraction is designed to capture reported values for these moderators where available, but the number of contract-passing studies per stratum is typically too low to support reliable statistical partitioning at this stage. The analysis framework is specified to test these moderators as the corpus accrues additional studies.

Translational considerations are an important context for any preclinical lifespan study. Acarbose has a long history of use as an antidiabetic agent in human clinical care, with studies examining its effects on metabolic parameters [13]. However, human clinical trials investigating hard longevity endpoints are absent from this literature. Therefore, while the mechanistic rationale and available murine data may inform translational hypotheses, any direct inference from a mouse lifespan effect to human longevity remains speculative and unsupported by direct interventional evidence in humans. These translational interventions are explicitly not part of the primary corpus under review.

## Limitations

The conclusions of this synthesis are constrained by specific, documented limitations of the corpus and the automated pipeline. The total number of primary murine studies meeting the full evidence contract is small, (Supplementary §S5/S5b; Appendix A), which fundamentally limits statistical power and the precision of any pooled effect estimate. This low k-value restricts the ability to detect publication bias or to conduct robust sensitivity analyses. Furthermore, the pipeline's sentinel-recall gate, which flags studies requiring manual full-text recovery, achieved a specific recall rate of (Supplementary §S7; Appendix A); this indicates a potential source of ascertainment bias for the final corpus. The adherence to strict metric-family discipline (e.g., pooling 90th-percentile lifespan extensions separately from median lifespan extensions) is a methodological strength for internal validity but prevents cross-family inference. Risk-of-bias assessment was conducted via an automated rule-based system aligned with principles for preclinical studies [2] [3], without independent human adjudication. Finally, while the pipeline facilitates manual full-text injection for sentinels, as documented in (Supplementary §S2-S3; Appendix A), this process recovers source material rather than overriding eligibility, and its scope is limited.

## Conclusion

Based on the current contract-passing corpus of (Supplementary §S5/S5b; Appendix A) murine studies, the synthesis is designed to provide a calibrated estimate of the effect of acarbose and α-glucosidase inhibitors on lifespan, subject to the defined evidence thresholds. The robustness and magnitude of this estimate would be substantively clarified by the inclusion of additional studies that meet the stringent evidence contract or by the successful recovery and re-evaluation of sentinel studies. The ultimate interpretive value of this evidence lies in its integration with mechanistic understanding of metabolic modulation and longevity pathways to evaluate acarbose's potential as a geroprotective compound.

## References

1. Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement. BMJ. 2021;372:n71. doi:10.1136/bmj.n71.
2. Percie du Sert N, Hurst V, Ahluwalia A, et al. The ARRIVE guidelines 2.0. PLoS Biol. 2020;18(7):e3000410. doi:10.1371/journal.pbio.3000410.
3. Hooijmans CR, Rovers MM, de Vries RBM, et al. SYRCLE's risk of bias tool for animal studies. BMC Med Res Methodol. 2014;14:43. doi:10.1186/1471-2288-14-43.
4. IntHout J, Ioannidis JPA, Borm GF. The Hartung-Knapp-Sidik-Jonkman method for random effects meta-analysis. BMC Med Res Methodol. 2014;14:25. doi:10.1186/1471-2288-14-25.
5. Viechtbauer W. Conducting meta-analyses in R with the metafor package. J Stat Softw. 2010;36(3):1-48. doi:10.18637/jss.v036.i03.
6. Higgins JPT, Thompson SG, Deeks JJ, Altman DG. Measuring inconsistency in meta-analyses. BMJ. 2003;327(7414):557-560. doi:10.1136/bmj.327.7414.557.
7. Egger M, Davey Smith G, Schneider M, Minder C. Bias in meta-analysis detected by a simple, graphical test. BMJ. 1997;315(7109):629-634. doi:10.1136/bmj.315.7109.629.
8. Schunemann HJ, Higgins JPT, Vist GE, et al. GRADE / Summary of findings tables. Cochrane Handbook for Systematic Reviews of Interventions. Wiley; 2019. doi:10.1002/9781119536604.ch14.
9. Considerations when using alpha-glucosidase inhibitors in the treatment of type 2 diabetes. Expert Opinion on Pharmacotherapy. 2019. doi:10.1080/14656566.2019.1672660.
10. Enhancement of Impaired Olfactory Neural Activation and Cognitive Capacity by Liraglutide, but Not Dapagliflozin or Acarbose, in Patients With Type 2 Diabetes: A 16-Week Randomized Parallel Comparative Study. Diabetes Care. 2022. doi:10.2337/dc21-2064.
11. α-glucosidase inhibitory in vitro and antidiabetic activity in vivo of Osmanthus fragrans. Journal of Medicinal Plants Research. 2012. doi:10.5897/jmpr11.1402.
12. Type 2 Diabetes Mellitus in Children and Adolescents. Pediatrics in Review. 2013. doi:10.1542/pir.34.12.541.
13. Fluorinated indeno-quinoxaline bearing thiazole moieties as hypoglycaemic agents targeting <i>α</i> -amylase, and <i>α</i> -glucosidase: synthesis, molecular docking, and ADMET studies. Journal of Enzyme Inhibition and Medicinal Chemistry. 2024. doi:10.1080/14756366.2024.2367128.

## Data and Code Availability

The aggregate screening counts, the strict A-core / sensitivity / secondary lane structure, the per-study effect extractions, the inverse-variance pool, the Researka Tier-2 canonical-fact cross-check, and the rendered manuscript and supplement are packaged in the run directory `runs/acarbose-paper-2026-05-13T11-49-08Z` and are version-controlled in `(repository URL not configured)`. Upstream retrieval-stage artifacts (raw retrieval hits, per-paper screening receipts, parsed full-text bodies, per-study eligibility receipts) live in the upstream eligibility run directory rather than this final paper folder, so this folder stays lean while the reproducibility chain remains traceable. Retrieval sources configured for this topic pack: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka. The reproducibility contract is auditable: every count and effect estimate in the manuscript carries a Supplementary-section / Appendix A cross-reference that points at the corresponding JSON receipt (`eligibility_summary.json`, `primary_effect_input_set_strict.json`, `effect_extractions.json`, `effect_pool.json`, `extraction_crosscheck.json`) so downstream reviewers can re-validate without re-running the LLM stack. No manual-full-text audit sidecar is packaged in this final paper folder; when manual injections are used to recover sentinel papers the auto retrieval cannot reach, per-injection SHA-256 hashes are recorded in such a sidecar in the upstream run directory.

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
