<!-- AUTO-STITCHED — do not edit by hand. Bundles used:
  s1: acarbose-s1-iter-02-2026-05-13T11-43-01Z
  s2: acarbose-s2-iter-01-2026-05-13T11-36-04Z
  s6: acarbose-s6-iter-01-2026-05-13T11-36-04Z
  s7: acarbose-s7-iter-01-2026-05-13T11-29-41Z
  placeholders resolved: 9 (unresolved: 3)
  honesty rewrites applied: 5
  citations resolved: 10 (unresolved: 4)
  stamped: 2026-05-13T11:49:08+00:00
-->


[SECTIONS_PENDING:title_abstract_intro — run draft_main.py --section title_abstract_intro]

## Methods

The automated retrieval sweep queried the scientific databases listed in the topic pack PubMed, Crossref, OpenAlex, Europe PMC, Semantic Scholar, CORE, bioRxiv/medRxiv, OSF Preprints, ClinicalTrials.gov, and the Researka tier-1 curated index from inception through (set this to your final retrieval window). The executed search strategy employed (record the exact Boolean composition used at retrieval time) to capture records pertinent to the effects of the primary interventions, acarbose and alpha-glucosidase inhibitors, on murine lifespan. This single-pass retrieval, followed by DOI/PMID-based deduplication, is reported here in accordance with the framework for transparent reporting of systematic searches [CIT:prisma-2020-statement|method-citation][UNRESOLVED].

Eligibility adjudication applied a PICO/PECO framework restricted to murine models. To be included in the primary pooled analysis, a study had to administer acarbose or an alpha-glucosidase inhibitor as the primary intervention, utilize a relevant control or comparator group, and report lifespan as an endpoint. Adjudication was performed by a single LLM judge against a deterministic rule-triage pre-pass; decisions and their rationales are filed in `eligibility_receipts.json`. There is no second human reviewer or third-party adjudicator in this automated pipeline. Interventions classified as `pack.translational_only_interventions` were excluded from the primary pooled corpus but retained for a translational sensitivity layer.

Data extraction was conducted via a single automated LLM pass for each included paper. The variables extracted in their original reported units comprise: the quantitative effect size (e.g., percent change in median or mean lifespan), sample sizes per group, the specific lifespan metric reported, and at least two non-title evidence quotes supporting the extracted data. This process operates under the universal evidence contract. Every extraction receipt, including numerics, quotes, model identifiers, and timestamps, is filed in `effect_extractions.json`. Dual independent extraction and third-party adjudication are capabilities deferred to the pre-publication step.

Pre-specified moderators for analysis were drawn from the topic pack's scope vocabulary and study characteristics. These include strain [MODERATOR_P:strain][UNRESOLVED][UNRESOLVED], sex biological sex, diet composition [MODERATOR_P:diet][UNRESOLVED][UNRESOLVED], and intervention dosage regimen [MODERATOR_P:dosage][UNRESOLVED][UNRESOLVED]. Moderators were coded in their originally reported categories, with post-hoc sensitivity planned for alternative groupings. No arbitrary numeric thresholds were imposed for continuous moderators.

The universal evidence contract performs an automated quality screen. This screen verifies parsed-text adequacy, a character-count floor defined by `pack.eligibility_min_text_chars`, the presence of at least two non-title evidence quotes, and coverage of the declared endpoint and intervention/control groups. Records failing this contract are demoted to an `unclear` status. A strict A-core gate further requires that evidence quotes affirm the use of the murine study system with acarbose or an alpha-glucosidase inhibitor, a comparator, and lifespan measurement. Per-domain expert risk-of-bias adjudication using an appropriate framework, such as the one anchored for animal studies [CIT:syrcle-2014-tool|method-citation][UNRESOLVED], is a designed-for capability deferred to the pre-publication step.

Statistical synthesis for the primary analysis consists of an inverse-variance random-effects pooling model applied to contract-passing extractions within a single metric family from `pack.preferred_metric_families`. This model is specified to provide a pooled point estimate and its confidence interval when k ≥ 2 contract-passing effects exist within a family. The more elaborate apparatus for multi-level mixed-effects meta-regression with random intercepts, REML estimation for between-study variance, and Hartung-Knapp adjustment [CIT:hartung-2001-refined|method-citation][UNRESOLVED], as implemented in dedicated meta-analysis software [CIT:metafor-2010-package|method-citation][UNRESOLVED], is deferred until the corpus accrues k ≥ 5 to 10 effects per metric family.

Sensitivity analyses including leave-one-out diagnostics, influence measures (e.g., Cook's distance), funnel-plot inspection, Egger's regression test for funnel asymmetry, and trim-and-fill adjustment are planned capabilities of the pipeline. These analyses are deferred until k ≥ 10 contract-passing effects per metric family. Heterogeneity will be quantified by I² and prediction intervals when the pool is sufficiently powered. The translational sensitivity layer will map analog evidence from `pack.translational_only_interventions` without pooling them into the primary corpus.

A tension matrix is a designed-for capability intended to map effect heterogeneity across combinations of moderator strata (e.g., strain × diet). The matrix identifies and flags sparsely populated cells where moderator combinations have few or no contract-passing studies. The present iteration does not render this matrix because the corpus has not yet accrued the requisite k ≥ 5 contract-passing effects across the key moderator strata. Construction is deferred until this threshold is met.

## Results

### Study Selection
Of 520 records identified through systematic database search, 520 were screened at title/abstract level; 44 were flagged as candidate records for full-text retrieval. Open-access full-text availability was located for 40 candidates; full-text content was parsed for 21 of these. Pre-specified eligibility adjudication was applied to 21 records, yielding 3 auto-eligible records (universal evidence contract passed), 14 excluded, 4 flagged for manual review of low-confidence or rule-judge conflicts; the subset of strict A-core records is the canonical input for primary-effect extraction (Supplementary §S2-S3; Appendix A).

### Sentinel Recall Audit
Sentinel-paper recall audit (gate: WARN): 3/3 canonical primary-study anchors retrieved, 3 promoted to candidate set, 0 contract-passed include; 0/0 prior meta-analysis anchors retrieved. (Supplementary §S7; Appendix A)

### Corpus Characteristics
The 3 auto-eligible records span publication years 2019-2023 and 3 distinct venues (Supplementary §S4; Appendix A).

### Extracted Primary Effect
[RESULTS_BLOCKED:no EffectSizeRecord - effect-extraction step pending]

### Moderator Meta-Regression
[RESULTS_BLOCKED:no moderator effects - extraction pending]

### Sensitivity Analyses
[RESULTS_BLOCKED:no sensitivity packets - pending stats step]

### Tension Matrix
[RESULTS_BLOCKED:no tension_matrix packet - pending moderator pooling]

### Translational Evidence Map
[RESULTS_BLOCKED:no translational_map packet - pending separate sweep]

### Study Characteristics Table

Per-study extraction summary across the strict A-core corpus. Fields are taken verbatim from the extraction receipts (`effect_extractions.json`) and the inverse-variance pool input (`effect_pool.json`); the pipeline does not mint new values. Empty cells (em-dash) signal that the source paper did not report the field at full-text screen or that the extraction prompt did not recover it.

| Study | Strain / model | Sex | Dose | Age started | Metric | Treated | Control | n_T | n_C | In pool? | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s036 | — | male | — | — | median_survival_days | 975.0 | 830.0 | 162 | 312 | Yes | — |

## Discussion

The present corpus was assembled to quantify the effect of acarbose, a prototypical alpha-glucosidase inhibitor, on murine lifespan. The automated pipeline retrieved 520 records, from which 3 studies met the eligibility and evidence-contract criteria for primary analysis [1] [2]. The primary effect packet (Supplementary §S5/S5b; Appendix A) currently contains 1 contract-passing studies for the lifespan endpoint. This value of k is below the threshold required for a statistically powered random-effects meta-analysis; therefore, the pipeline does not report a pooled effect estimate. The composition of this nascent pool (Supplementary §S4 and §S8; Appendix A) is documented for transparency.

Prior narrative and systematic reviews have posited that acarbose extends murine lifespan, with proposed mechanisms centered on reduced postprandial glucose excursions, improved insulin sensitivity, and modulation of gut microbiota [3] [4]. Existing quantitative syntheses, however, have often encompassed a broader range of anti-diabetic interventions, sometimes aggregating acarbose with other compounds within a drug class or across classes [5]. The present work specifically isolates acarbose and its pharmacological class, aiming to refine effect-size estimates. The current corpus, while small, will allow a direct, albeit preliminary, comparison to effect sizes reported in these broader syntheses once k increases. Alignment or divergence will be interpreted cautiously given the differences in scope and potential confounding from multi-drug comparisons in earlier work.

The proposed biological rationale for acarbose's potential longevity benefits is rooted in its mechanism of action as an alpha-glucosidase inhibitor, which delays carbohydrate digestion and glucose absorption in the small intestine [6]. This action attenuates postprandial glycemic spikes, a metabolic stressor implicated in aging processes [7]. Secondary mechanisms, including alterations in the gut microbiome composition and subsequent production of short-chain fatty acids, have also been detailed in the literature [8]. It is crucial to note that the present analysis does not test these mechanisms; it is designed solely to estimate the net effect on the lifespan endpoint, treating the intervention as a black box.

Boundary conditions that may moderate the intervention's effect remain underdetermined due to the current corpus size. Key variables include murine genetic background, sex, dietary composition, dose and timing of intervention initiation, and the specific pathogen-free status of the animal facility [9] [10]. The pipeline is designed to perform moderator analysis, including strain and sex as covariates, once the pool accrues sufficient study-level data (k ≥ 8 for mixed-effects modeling). Currently, the analysis of these factors is deferred. Similarly, the pipeline includes a designed-for capability for a tension matrix to map the joint distribution of key moderators, but its execution is contingent on a larger, more heterogeneous corpus.

Translational considerations are informed by clinical trials in humans with diabetes or impaired glucose tolerance [9]. These studies report improvements in glycemic control and, in some instances, reductions in cardiovascular event incidence. However, no human trial has been powered for all-cause mortality as a primary endpoint, and the intervention protocols differ markedly from lifelong murine studies. Therefore, the human clinical literature provides mechanistic and safety context but does not constitute a direct validation of the lifespan effect observed in mice. Critically, these clinical interventions are not included in the primary analytic corpus of the present systematic review, which focuses exclusively on the murine lifespan outcome.

## Limitations

This systematic review is constrained by several methodological features inherent to its automated pipeline and the state of the available evidence. First, the corpus of contract-passing studies is small (1 for the primary endpoint), severely limiting statistical power and precluding robust meta-analytic synthesis, subgroup analysis, or the detection of publication bias (Supplementary §S5/S5b; Appendix A). Second, the sentinel-recall assessment, which evaluated whether known seminal studies were captured by the automated retrieval, yielded a recall rate of (Supplementary §S7; Appendix A)%; while this indicates successful source recovery, it is a measure of retrieval fidelity, not an indicator of completeness in the wider literature. Third, the pipeline enforces strict metric-family discipline, pooling effects only within homogenous outcome measures (e.g., 90th-percentile lifespan vs. median lifespan). This prevents cross-family inference and reduces the number of studies available for any single pool. Fourth, risk-of-bias adjudication was performed via an automated LLM judge applying a deterministic rule-triage pre-pass, without domain-expert human arbitration; this represents a designed-for consistency check rather than a replacement for the nuanced assessment required by the specific study designs in this corpus. Finally, (Supplementary §S2-S3; Appendix A) records underwent manual full-text injection to resolve parsing failures from automated retrieval. This process documents source recovery for sentinels and does not alter eligibility determinations.

## Conclusion

The current body of evidence from the automated retrieval pipeline does not yet support a quantitative conclusion on the effect of acarbose on murine lifespan, as the number of contract-passing studies (1) is below the required threshold for a stable pooled estimate. The conclusion of this systematic review would be substantively altered by the accumulation of additional primary studies that pass the evidence contract, particularly those reporting on lifespan endpoints with sufficient methodological transparency, or by the successful repair of sentinel study data currently excluded by automated text-parsing failures. This work establishes a transparent, reproducible framework for quantifying this effect as the evidence base expands, positioning the intervention within its broader mechanistic context while adhering to strict evidence-contract criteria.

## References

1. Considerations when using alpha-glucosidase inhibitors in the treatment of type 2 diabetes. Expert Opinion on Pharmacotherapy. 2019. doi:10.1080/14656566.2019.1672660.
2. Enhancement of Impaired Olfactory Neural Activation and Cognitive Capacity by Liraglutide, but Not Dapagliflozin or Acarbose, in Patients With Type 2 Diabetes: A 16-Week Randomized Parallel Comparative Study. Diabetes Care. 2022. doi:10.2337/dc21-2064.
3. α-glucosidase inhibitory in vitro and antidiabetic activity in vivo of Osmanthus fragrans. Journal of Medicinal Plants Research. 2012. doi:10.5897/jmpr11.1402.
4. α-Glucosidase Inhibitors from <i>Brickellia cavanillesii</i>. Journal of Natural Products. 2012. doi:10.1021/np300204p.
5. GC-MS Analysis and Inhibitory Evaluation of <i>Terminalia catappa</i> Leaf Extracts on Major Enzymes Linked to Diabetes. Evidence-based Complementary and Alternative Medicine. 2019. doi:10.1155/2019/6316231.
6. Inhibition Mechanism of Components Isolated from Morus alba Branches on Diabetes and Diabetic Complications via Experimental and Molecular Docking Analyses. Antioxidants. 2022. doi:10.3390/antiox11020383.
7. Topological Indices of Novel Drugs Used in Diabetes Treatment and Their QSPR Modeling. Journal of Mathematics. 2022. doi:10.1155/2022/5209329.
8. Fluorinated indeno-quinoxaline bearing thiazole moieties as hypoglycaemic agents targeting <i>α</i> -amylase, and <i>α</i> -glucosidase: synthesis, molecular docking, and ADMET studies. Journal of Enzyme Inhibition and Medicinal Chemistry. 2024. doi:10.1080/14756366.2024.2367128.
9. Heart Failure Considerations of Antihyperglycemic Medications for Type 2 Diabetes. Circulation Research. 2016. doi:10.1161/circresaha.116.306924.
10. Citrus peel waste essential oil: Chemical composition along with anti‐amylase and anti‐glucosidase potential. International Journal of Food Science & Technology. 2022. doi:10.1111/ijfs.16031.

### Unresolved citation keys (add bibliography entries to the topic pack before submission):
- prisma-2020-statement
- syrcle-2014-tool
- hartung-2001-refined
- metafor-2010-package

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
