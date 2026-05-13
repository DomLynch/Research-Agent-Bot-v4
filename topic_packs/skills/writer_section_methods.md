---
name: writer_section_methods
description: User-prompt spec for the Methods section. Describes WHAT THE PIPELINE ACTUALLY DOES (single-pass automated extraction, inverse-variance pool, universal evidence contract). Idealised-systematic-review methodology is named explicitly as deferred until k thresholds are met. Topic-pack supplies anchor keys + length caps.
allowed-tools: none
---
800-1,200 words. Write a Methods section that describes WHAT THIS PIPELINE ACTUALLY DOES, not an idealised Cochrane-style systematic-review protocol. Every method named must correspond to a step the automated pipeline actually performs; capabilities that require human review or larger k must be named as deferred-until-threshold, never claimed as performed.

Write as ordered paragraphs (no markdown headers), one paragraph per component below. Each paragraph must contain at least one `[CIT:<method-key>|method-citation]` anchor drawn from the topic pack's anchor list (shown in the TOPIC-PACK CONSTRAINTS block above) when a published method is being cited, OR a `[PLACEHOLDER:...]` slot when the operational detail is filled from receipts. The prompt is DOMAIN-NEUTRAL: select method anchors that match the topic's study designs; the topic-pack anchors are the only source of specific method-citation keys.

PIPELINE GROUND TRUTH (write this; do not invent methodology beyond it):

* Search across the databases listed in `pack.retrieval_sources` runs in a single automated sweep; dedup is by DOI/PMID; the search-strategy section reports the executed query, not a planned one.
* Eligibility is adjudicated by ONE LLM judge (`pack.judge_model` is named in the AI-Use Disclosure, not in Methods) against a deterministic rule-triage pre-pass. There is no second human reviewer and no third-reviewer adjudicator. Decisions are filed in `eligibility_receipts.json`.
* The universal evidence contract gates includes: parsed-text adequate, char-count above `pack.eligibility_min_text_chars`, at least two non-title evidence quotes, endpoint coverage, intervention/control coverage. Failures demote to `unclear`.
* The strict A-core gate additionally requires per-quote evidence that the CURRENT experiment used the preferred species + primary intervention + control + endpoint. Demoted records go to B-sensitivity or C-secondary lanes documented in `primary_effect_input_set_strict.json`.
* Extraction is performed by ONE LLM pass per included paper. Numerics, evidence quotes, model name, timestamps are filed in `effect_extractions.json`.
* The inverse-variance pool runs over contract-passing extractions within a single metric family (from `pack.preferred_metric_families`). Reported only at k ≥ 2.
* A Researka Tier-2 canonical-fact cross-check overlay runs on every extraction with percent-change numerics; verdicts (matched / discrepant / no_canonical_fact / no_receipt_numerics) are filed in `extraction_crosscheck.json`.
* Manual full-text injections (when used to recover sentinel papers the auto retrieval cannot reach) are SHA-256-hashed and recorded as a side-car.

FORBIDDEN OVERCLAIMS (these contradict the pipeline ground truth above and will fail downstream contract gates):

* Do NOT claim PROSPERO / OSF / external-registry registration. The protocol is implemented in this pipeline only.
* Do NOT claim dual independent extraction, two-reviewer extraction, second-reviewer extraction, or third-reviewer adjudication.
* Do NOT claim a SYRCLE-by-domain (or Cochrane-RoB-2-by-domain) human risk-of-bias adjudication. The pipeline performs an automated rule-based screen; per-domain expert adjudication is deferred.
* Do NOT claim a multi-level mixed-effects meta-regression with random intercepts for study-ID and outcome-within-study, REML between-study variance, Hartung-Knapp adjustment, or metafor execution AS PERFORMED. The pipeline reports an inverse-variance point estimate at k ≥ 2; the full meta-regression apparatus is deferred until k ≥ 5–10 within a single metric family.
* Do NOT claim leave-one-out, influence diagnostics (Cook's distance), funnel-plot inspection, Egger's regression, or trim-and-fill AS PERFORMED. All of these require larger k than the inverse-variance point estimate; defer them with the same k-threshold framing.
* Do NOT claim a tension-matrix construction AS PERFORMED if the corpus has not accrued enough moderator-stratum cells. The tension matrix is a designed-for capability of the pipeline; describe it conditionally.

Honest substitution patterns for any capability above:

* "is implemented in this pipeline as [actual step]"
* "is deferred until the corpus accrues k ≥ [threshold] contract-passing effects per metric family"
* "is planned for the pre-publication step"
* "is a designed-for capability of the pipeline; the present iteration does not execute it because [k condition]"

Components, in order (each one paragraph):

1. SEARCH STRATEGY — name the databases queried (use `[PLACEHOLDER:databases]`), the date range (`[PLACEHOLDER:date-range]`), and the query shape (`[PLACEHOLDER:query-terms]`). Cite the topic-pack-supplied reporting framework anchor (PRISMA-shaped or domain-equivalent). Describe the search as EXECUTED, not planned, because by the time Methods is rendered the retrieval step has already run.
2. ELIGIBILITY — inclusion / exclusion criteria framed in PICO / PECO terms appropriate to the domain. State that adjudication is by an LLM judge against the universal evidence contract, with a deterministic rule-triage pre-pass. Restrict the primary pooled corpus to `pack.primary_interventions`; explicitly exclude `pack.translational_only_interventions` from the primary pool (retain as a translational sensitivity layer).
3. DATA EXTRACTION — variables extracted from each included study (effect size, sample sizes, metric, evidence quotes), in their ORIGINAL reported units. State explicitly: extraction is performed by a single automated pass under the universal evidence contract; every receipt is filed in `effect_extractions.json`. Dual independent extraction and third-party adjudication are deferred to the pre-publication step.
4. MODERATOR CODING — the pre-specified moderators (drawn from topic-pack scope), their levels, and the rationale. Use `[MODERATOR_P:<name>]` for each. Original-unit extraction with post-hoc category sensitivity; no arbitrary numeric thresholds.
5. RISK-OF-BIAS / QUALITY — describe the automated screen the universal evidence contract performs (parsed-text adequacy, char-count floor, ≥ 2 non-title evidence quotes, endpoint coverage, intervention / control coverage). Name the appropriate per-domain framework anchor (SYRCLE for animal studies, Cochrane RoB 2 for human RCTs, etc.) and state that per-domain expert adjudication is deferred to the pre-publication step.
6. STATISTICAL SYNTHESIS — state that the pipeline runs an inverse-variance random-effects pool over contract-passing effects within a single metric family from `pack.preferred_metric_families`. The pool reports a point estimate at k ≥ 2. Name the full multi-level meta-regression apparatus (REML, Hartung-Knapp, metafor) as DEFERRED until k ≥ 5–10 per metric family; cite the topic-pack method-citation anchors for completeness.
7. SENSITIVITY ANALYSES — name leave-one-out, influence diagnostics, funnel-plot / Egger, trim-and-fill, and heterogeneity quantification (I², prediction intervals) as DEFERRED until k ≥ 10. Cite the relevant topic-pack method anchors. If the pack lists translational-only interventions, mention the translational sensitivity layer (analog-evidence map without pooling into the primary corpus).
8. TENSION-MATRIX CONSTRUCTION — describe the matrix as a designed-for capability of the pipeline; how moderator combinations would define cells; how sparsely-populated cells would be flagged. Frame the present iteration as not-yet-rendered (the corpus has not accrued enough moderator-stratum cells) and the matrix as deferred until k ≥ 5 contract-passing effects accumulate across moderator strata.
