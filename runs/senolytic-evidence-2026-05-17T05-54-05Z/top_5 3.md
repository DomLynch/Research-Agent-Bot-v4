# Top 2 interesting findings — senolytic

**Snapshot:** 2026-05-17T05-54-05Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=senolytic) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 13
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1, model_context=1)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 100 · effect_size

**Finding:** reduced SMC by 90%

- **Value:** 90.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Alpha cues:** functional_endpoint
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 60.0% (reduced α-SMA+ fibrous cap thickness by 60%); 60.0% (increased EC contributions to lesions via EC-to-mesenchymal )

- **Why it matters:** A 90% reduction in senescent cells could significantly slow atherosclerosis progression by decreasing inflammation and plaque instability, offering a new therapeutic avenue for heart disease.
- **Caution:** This effect was demonstrated in a single study using Apoe-/- mice on a western diet, which may not accurately represent human atherosclerosis biology or immune responses.
- **Next question:** Can senolytics achieve similar senescent cell reductions in human atherosclerotic plaques without causing harmful side effects?

---

### Lane — `adverse`


## #2 — score 100 · adverse

**Finding:** was associated with a > 50% mortality rate

- **Value:** 50.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Alpha cues:** functional_endpoint
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2

- **Why it matters:** The association with over 50% mortality raises urgent safety concerns for senolytic use in advanced cardiovascular disease, potentially limiting clinical application.
- **Caution:** The mortality was observed in a specific mouse model with advanced atherosclerosis, and the dose used might not be safe or applicable to human patients.
- **Next question:** What are the underlying mechanisms of this mortality, and can senolytic dosing be adjusted to mitigate risks while preserving efficacy?

---
