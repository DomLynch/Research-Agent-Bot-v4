# Top 3 interesting findings — fasting

**Snapshot:** 2026-05-27T05-51-53Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=fasting) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 26
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: biomarker=1, clinical_outcome=1, regimen_or_dose=1)

---

## #1 — score 81 · effect_size

**Finding:** a daily fasting interval and circadian alignment of feeding acted together to extend life span by 35% in male C57BL/6J mice

- **Value:** 35.0%
- **Population:** male C57BL/6J mice
- **Intervention:** 30% CR with daily fasting interval and circadian alignment of feeding
- **Alpha cues:** subgroup
- **Source:** *Circadian alignment of early onset caloric restriction promotes longevity in male C57BL/6J mice* — Science (2022)
  · DOI: `10.1126/science.abk0297`
- **Validator:** researka-tier2

- **Why it matters:** Aligning daily fasting with circadian rhythms could inform human anti-aging interventions by extending lifespan through natural eating patterns.
- **Caution:** This study used only male C57BL/6J mice, so generalizability to humans or other genders is limited.
- **Next question:** Does this lifespan benefit from circadian-aligned fasting replicate in human trials, and do females show similar effects?

---

## #2 — score 60 · effect_size

**Finding:** The overall pooled estimate for fasting compared to non-fasting indicated no significant difference in side effects (RR = 1.10; 95% CI: 0.77-1.59).

- **Value:** 1.1RR
- **Population:** cancer patients receiving chemotherapy
- **Intervention:** therapeutic fasting regimens
- **Alpha cues:** baseline
- **Source:** *Therapeutic Fasting in Reducing Chemotherapy Side Effects in Cancer Patients: A Systematic Review and Meta-Analysis* — Nutrients (2023)
  · DOI: `10.3390/nu15122666`
- **Validator:** researka-tier2

- **Why it matters:** Fasting during chemotherapy appears safe with no increased side effects, offering reassurance for cancer patients considering dietary interventions.
- **Caution:** The pooled estimate may overlook heterogeneity in study designs and patient characteristics across included trials.
- **Next question:** How does fasting impact chemotherapy efficacy and long-term survival in specific cancer types?

---

## #3 — score 55 · effect_size

**Finding:** 1% increase in serum PFNA was significantly associated with 0.022% (95% CI: 0.007%, 0.037%) increment in fasting glucose levels.

- **Value:** 0.022%
- **Population:** Chinese adult men and women with normal blood glucose levels
- **Intervention:** 1% increase in serum PFNA concentration
- **Alpha cues:** baseline
- **Source:** *Distribution of novel and legacy per-/polyfluoroalkyl substances in serum and its associations with two glycemic biomarkers among Chinese adult men and women with normal blood glucose levels* — Environment International (2019)
  · DOI: `10.1016/j.envint.2019.105295`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.018% (1% increase in serum PFOA was significantly associated with )

- **Why it matters:** Even low-level PFNA exposure is linked to slightly higher fasting glucose, suggesting environmental pollutants may subtly affect metabolic health in healthy adults.
- **Caution:** This observational study cannot confirm causation, and the dose-response relationship is minimal with potential confounders.
- **Next question:** What mechanisms explain how serum PFNA influences fasting glucose, and can reducing exposure mitigate this effect?

---
