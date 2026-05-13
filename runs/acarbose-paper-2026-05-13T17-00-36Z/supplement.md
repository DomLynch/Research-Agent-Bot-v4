# Supplementary Materials — Acarbose

Auto-generated from the run-directory receipts that accompany the main manuscript. Every count, identifier, and quote below is read verbatim from a JSON receipt; the supplement does not mint new numbers and cannot drift from the main paper.

## S1 — Search Strategy

- **Topic pack**: `acarbose` (Acarbose)
- **Retrieval sources**: pubmed, crossref, openalex, europepmc, semantic_scholar, core, biorxiv, osf, ctgov, researka
- **Primary interventions (PICO `E`)**: acarbose, alpha-glucosidase inhibitor
- **Translational-only interventions** (excluded from primary corpus; retained for sensitivity layer): (none)
- **Endpoint vocabulary**: lifespan, survival, longevity, mortality, median survival
- **Control vocabulary**: control, vehicle, placebo, untreated, wild-type
- **Excluded designs**: systematic review, meta-analysis, narrative review, scoping review, in vitro, cell line, case report
- **Pre-specified parsed-text minimum**: 2000 chars

## S2 — Screening Counts (PRISMA-style)

- records identified: **0**
- title/abstract candidates: **0**
- open-access full-text located: **0**
- full-text parsed: **0**
- eligibility decisions: **{}**
- eligible after merge: **0**
- judge model: `(unknown)`

## S3 — Eligibility Receipts (per-study auto-judge verdicts)

Aggregate eligibility counts are embedded above from `eligibility_summary.json`. Per-study eligibility receipts are not packaged in this final paper folder; regenerate or inspect the upstream eligibility run directory for the full receipt table.

## S4 — Strict A-core Corpus (k = 0)

_(no strict A-core records in this run)_


## S5 — Effect Extraction Receipts (n = 0)

_(no extraction receipts)_


### S5b — Inverse-variance pool (k_effects = 0, skipped = 0)

_(no pooling-ready effects in this run)_


## S6 — Risk-of-Bias Notes

Automated rule-based screen per the pre-specified eligibility ladder (rule_triage → LLM judge → deterministic merge → include-contract). The universal evidence contract requires (a) parsed_text_adequate, (b) char_count above the topic-pack minimum, (c) at least two non-title evidence quotes, (d) endpoint-term coverage, and (e) intervention or control term coverage. Strict A-core additionally demands quote-level evidence that the CURRENT experiment used the preferred species + primary intervention + control + endpoint. Each demotion is recorded with its violation list in `primary_effect_input_set_strict.json`. **A pre-publication submission would require an explicit human risk-of-bias adjudication step** (e.g. SYRCLE for animal studies, Cochrane RoB 2 for human RCTs) on top of this automated screen.

## S7 — Sentinel Recall Audit

Topic-pack-declared sentinels are: **primary** = `10.1093/gerona/glaa302`, `10.1111/acel.12264`, `10.1021/np300204p`; **prior_meta** = .

Per-sentinel resolution (auto verdict + manual status overlay) is recorded in the upstream eligibility run directory's QA report (not packaged in this final paper folder) under the _Sentinel resolution status (manual overlay)_ table. The gate passes only when every primary sentinel either auto-contract-passes or is documented as resolved_unavailable / resolved_excluded.

## S8 — Excluded / Demoted Studies (with reasons)

_(no demoted records in this run)_


## S9 — Code and Data Availability

- Pipeline source: see the project repository under `agent/`, `scripts/`, and `tests/`. All counts and effect estimates are computed from the JSON receipts filed in this paper folder; no number in the main manuscript originates outside those receipts.
- Topic pack: `topic_packs/acarbose.toml` (search vocabulary, sentinels, anchors, bibliography, strict A-core terms).
- Manual full-text overrides (if any): `topic_packs/manual_full_text/acarbose/`. No manual-full-text audit sidecar is packaged in this final paper folder.
- Receipts present in this folder: `cite_audit.json`, `paper_type_decision.json`, `readiness_report.json`.

