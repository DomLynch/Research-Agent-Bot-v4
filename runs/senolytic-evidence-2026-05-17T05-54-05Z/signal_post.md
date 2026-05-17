# Signal — senolytic

_Snapshot:_ `2026-05-17T05-54-05Z`

## Senolytic-induced EndoMT as a maladaptive response in atherosclerotic plaque regression: implications for therapeutic window optimization

## Why this is surprising

The evidence exposes a paradoxical mechanism where senolytic ABT-263 in advanced atherosclerosis clears smooth muscle cells yet simultaneously triggers endothelial-to-mesenchymal transition, suggesting that plaque regression may compromise vascular integrity and survival, challenging the linear assumption that senescent cell removal is unambiguously beneficial.

Known / obvious (do not republish): Senolytics eliminate senescent cells via apoptosis; ABT-263 is a Bcl-2 family inhibitor used in senolytic therapy; Senescent cell accumulation contributes to age-related pathologies

Real tension: Between the 90% SMC reduction (fact_id=12623) and 60% EndoMT increase (fact_id=12624) in the same Apoe-/- mouse model, indicating conflicting effects on plaque stability

## Evidence

- reduced SMC by 90% **[90%]** (JCI Insight 2024)
- increased EC contributions to lesions via EC-to-mesenchymal transition (EndoMT) by 60% **[60%]** (JCI Insight 2024)
- was associated with a > 50% mortality rate **[50%]** (JCI Insight 2024)

## Confidence — `evidence_backed_signal`

**High — evidence-backed signal.** Cited facts pass source-audit lane gates with A_core density and matched metric families.

## Adjacent signals to consider

_These facts did NOT bind to the A_core/B_context lane this run — they are research prompts, NOT cited evidence. Triage and re-extract carefully before treating any of these as alpha:_

- we found lower irisin levels (p = .0011) in patients with osteopenia/osteoporosis compared to healthy controls
  - source: `10.1002/jbmr.4192` (fact_id=`7375`, lane=`D_bad_extraction`)
- BMAT was significantly elevated in radiated bones at day 7.
  - source: `10.1002/jbmr.4537` (fact_id=`22274`, lane=`D_bad_extraction`)
- FNDC5 positive fibers positively correlate with BMD of total femur (R = 0.765; p = .0014)
  - source: `10.1002/jbmr.4192` (fact_id=`7377`, lane=`D_bad_extraction`)

## Next question

Explore p53 and miR34a expression dynamics in ABT-263-treated endothelial cells to link senolytic action to EndoMT pathways
