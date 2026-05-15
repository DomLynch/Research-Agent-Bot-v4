# Top 5 interesting findings — senolytic

**Snapshot:** 2026-05-15T08-59-21Z
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

- **Why it matters:** A 90% reduction in senescent cells in atherosclerotic mice suggests senolytics could powerfully target plaque-related senescence, potentially treating cardiovascular disease.
- **Caution:** The effect was observed in advanced Apoe-/- mice on a western diet, a model that may not fully capture human atherosclerosis dynamics.
- **Next question:** Does this senescent cell reduction lead to improved plaque stability and reduced cardiovascular events in humans?

---

## #2 — score 74 · effect_size

**Finding:** Accumulation of senescent cells and SASP markers were correlated with a significant reduction in bone architecture at 42 days post-FRT.

- **Value:** 42.0days
- **Population:** C57BL/6 male mice with focal radiotherapy
- **Intervention:** focal radiotherapy
- **Source:** *Targeted Reduction of Senescent Cell Burden Alleviates Focal Radiotherapy-Related Bone Loss* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.3978`
- **Validator:** researka-tier2

- **Why it matters:** Over 50% mortality in severe atherosclerotic mice treated with senolytics raises critical safety concerns for clinical translation in high-risk patients.
- **Caution:** The high mortality rate was specific to a mouse model with advanced disease, and human tolerance could differ significantly.
- **Next question:** Can senolytic doses or schedules be optimized to minimize mortality while maintaining therapeutic benefits?

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

- **Why it matters:** The correlation between senescent cells, SASP markers, and bone loss after radiotherapy in mice implies senolytics might prevent radiation-induced osteoporosis.
- **Caution:** The study used C57BL/6 male mice with focal radiotherapy, which may not reflect human bone changes from similar treatments.
- **Next question:** Are senescent cells direct causative agents in bone degradation, and can senolytics reverse post-radiation bone damage?

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

- **Why it matters:** Senolytic downregulation of elevated miR-27a in radiated and aged mouse bones highlights a molecular pathway that could be targeted to protect bone health.
- **Caution:** The findings are from radiated and aged mice, and miRNA regulation in human bones might vary due to species differences.
- **Next question:** Is miR-27a a reliable biomarker for senolytic efficacy, and does its modulation directly improve bone architecture in humans?

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

- **Why it matters:** Lower irisin levels in osteoporotic patients suggest this hormone is associated with bone density loss, indicating a potential diagnostic or therapeutic marker.
- **Caution:** This is an observational study showing correlation, not causation, and does not involve senolytic interventions.
- **Next question:** Can senolytics or other treatments increase irisin levels to ameliorate bone loss in osteoporosis?

---
