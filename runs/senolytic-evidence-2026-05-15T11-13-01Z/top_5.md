# Top 5 interesting findings — senolytic

**Snapshot:** 2026-05-15T11-13-01Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=senolytic) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 17
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 80 · effect_size

**Finding:** reduced SMC by 90%

- **Value:** 90.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 60.0% (reduced α-SMA+ fibrous cap thickness by 60%); 60.0% (increased EC contributions to lesions via EC-to-mesenchymal )

- **Why it matters:** The 90% reduction in senescent cells in atherosclerotic mice suggests senolytics could halt plaque progression in human cardiovascular disease.
- **Caution:** The Apoe-/- mouse model on a western diet may not mimic human atherosclerosis complexity, and the senolytic dose used is unspecified.
- **Next question:** Does this senolytic treatment reduce atherosclerotic plaque burden or inflammation in these mice over longer periods?

---

## #2 — score 74 · effect_size

**Finding:** Accumulation of senescent cells and SASP markers were correlated with a significant reduction in bone architecture at 42 days post-FRT.

- **Value:** 42.0days
- **Population:** C57BL/6 male mice with focal radiotherapy
- **Intervention:** focal radiotherapy
- **Source:** *Targeted Reduction of Senescent Cell Burden Alleviates Focal Radiotherapy-Related Bone Loss* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.3978`
- **Validator:** researka-tier2

- **Why it matters:** A mortality rate over 50% in treated mice signals severe safety risks for senolytic use in advanced atherosclerosis, warranting caution in human trials.
- **Caution:** The adverse effect is observed in the same mouse model, with potential confounding factors like dose or treatment duration not detailed.
- **Next question:** What specific toxicities or off-target effects caused the mortality, and can dosing adjustments mitigate them?

---

## #3 — score 74 · effect_size

**Finding:** miR-27a was elevated in radiated and aged bones, and downregulated by D + Q at 42 days post-radiation.

- **Value:** 42.0days
- **Population:** radiated and aged mice
- **Intervention:** D + Q
- **Source:** *Bone Marrow Adiposity in Models of Radiation- and Aging-Related Bone Loss Is Dependent on Cellular Senescence* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.4537`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 6.0 (BMAT-related genes were the most upregulated gene subset in )

- **Why it matters:** Linking senescent cells and SASP to bone loss post-radiotherapy implies that senolytics could protect bone integrity in cancer patients undergoing treatment.
- **Caution:** The study used only male C57BL/6 mice with focal radiotherapy, which may not translate to female mice or other radiation modalities.
- **Next question:** Can senolytic therapy administered post-radiotherapy reverse or prevent the observed bone architecture deterioration?

---

## #4 — score 63 · effect_size

**Finding:** we found lower irisin levels (p = .0011) in patients with osteopenia/osteoporosis compared to healthy controls

- **Value:** 11.0
- **Population:** patients divided by T-score (osteopenia/osteoporosis vs healthy controls matched for age and sex)
- **Intervention:** endogenous irisin levels
- **Source:** *Irisin Correlates Positively With BMD in a Cohort of Older Adult Patients and Downregulates the Senescent Marker p21 in Osteoblasts* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.4192`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -0.515R (irisin serum levels negatively correlated with age (R = -0.5); 0.619R (irisin serum levels positively correlated with femoral BMD (); 0.765R (FNDC5 positive fibers positively correlate with BMD of total)

- **Why it matters:** Senolytics downregulating miR-27a in radiated bones reveals a potential mechanism for combating radiation-induced bone aging, relevant to osteoporosis prevention.
- **Caution:** Findings are from radiated and aged mice, so the effect may not apply to non-radiated bone aging or different senolytic regimens.
- **Next question:** Does miR-27a downregulation by senolytics correlate with functional improvements in bone strength or density in these mice?

---

### Lane — `adverse`


## #5 — score 76 · adverse

**Finding:** was associated with a > 50% mortality rate

- **Value:** 50.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2

- **Why it matters:** Lower irisin levels in osteoporosis patients identify it as a potential biomarker for bone disease, guiding diagnostic or therapeutic strategies in humans.
- **Caution:** This is a cross-sectional observational study, so causation between irisin levels and osteoporosis cannot be inferred.
- **Next question:** Can interventions like senolytics or exercise elevate irisin levels, and does this lead to improved bone mineral density?

---
