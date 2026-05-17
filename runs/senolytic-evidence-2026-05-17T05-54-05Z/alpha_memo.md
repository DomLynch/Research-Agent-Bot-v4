# Alpha memo — senolytic

**Headline:** Senolytic-induced EndoMT as a maladaptive response in atherosclerotic plaque regression: implications for therapeutic window optimization
**Alpha score:** 83/100
**Confidence:** `evidence_backed_signal`
**Snapshot:** `2026-05-17T05-54-05Z`
**Run:** `senolytic-evidence-2026-05-17T05-54-05Z`

## One-sentence thesis

Senolytic-induced EndoMT as a maladaptive response in atherosclerotic plaque regression: implications for therapeutic window optimization

## Why this is surprising

The evidence exposes a paradoxical mechanism where senolytic ABT-263 in advanced atherosclerosis clears smooth muscle cells yet simultaneously triggers endothelial-to-mesenchymal transition, suggesting that plaque regression may compromise vascular integrity and survival, challenging the linear assumption that senescent cell removal is unambiguously beneficial.

Known / obvious (do not republish): Senolytics eliminate senescent cells via apoptosis; ABT-263 is a Bcl-2 family inhibitor used in senolytic therapy; Senescent cell accumulation contributes to age-related pathologies

Real tension: Between the 90% SMC reduction (fact_id=12623) and 60% EndoMT increase (fact_id=12624) in the same Apoe-/- mouse model, indicating conflicting effects on plaque stability

## Evidence receipts

- `fact_id=12623` (`A_core`) — reduced SMC by 90% DOI `10.1172/jci.insight.173863`
- `fact_id=12624` (`A_core`) — increased EC contributions to lesions via EC-to-mesenchymal transition (EndoMT) by 60% DOI `10.1172/jci.insight.173863`
- `fact_id=12622` (`A_core`) — was associated with a > 50% mortality rate DOI `10.1172/jci.insight.173863`

## What this changes

Treat this as a focused working signal, not a broad topic claim. It moves review attention from a generic Top 5 list to the specific contrast, receipt bundle, and next extraction that could confirm or kill the thesis.

## What would weaken this

- The study is limited to advanced atherosclerosis in Apoe-/- mice, which may not recapitulate human disease heterogeneity or early plaque stages
- The >50% mortality rate (fact_id=12622) could stem from off-target effects of ABT-263 rather than senolytic-specific mechanisms, weakening causal claims
- Lack of cellular or molecular data on how ABT-263 directly induces EndoMT, leaving mechanistic gaps

## Next extraction

- Explore p53 and miR34a expression dynamics in ABT-263-treated endothelial cells to link senolytic action to EndoMT pathways
- Measure irisin serum levels in senolytic-treated atherosclerotic models to assess metabolic cross-talk with vascular senescence
- Quantify bone marrow adipose tissue changes in atherosclerotic mice post-ABT-263 to examine systemic senolytic effects

## Supporting Top cards

- reduced SMC by 90% _(alpha cues: functional_endpoint)_
- was associated with a > 50% mortality rate _(alpha cues: functional_endpoint)_

## Provenance / priority

- **Topic:** `senolytic`
- **Author:** Dom Lynch
- **ORCID:** _not configured_
- **Version:** 1.0
- **License:** CC BY-NC 4.0
- **Canonical URL:** _not assigned_
- **Suggested citation:** Dom Lynch. (2026). Senolytic-induced EndoMT as a maladaptive response in atherosclerotic plaque regression: implications for therapeutic window optimization. ReseaRka Evidence Index. Version 1.0.
- **Run bundle SHA-256:** `4c5d69338a3b26f251f90acba701563f3899d85fa89a0f4daa2ebe50f0464f3a`
- **Memo SHA-256:** `5ae4dc6424fd56d807f1f4d58849b4724d407148c57863b1a5220fe9cae6d4fa`
- **Priority note:** This memo records the first published framing, source bundle, and evidence receipts for this run. Reuse should cite the canonical version.
