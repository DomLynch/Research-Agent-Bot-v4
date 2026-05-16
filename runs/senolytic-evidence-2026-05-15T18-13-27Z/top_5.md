# Top 5 interesting findings — senolytic

**Snapshot:** 2026-05-15T18-13-27Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=senolytic) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 13
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

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 63 · effect_size

**Finding:** we found lower irisin levels (p = .0011) in patients with osteopenia/osteoporosis compared to healthy controls

- **Value:** 11.0
- **Population:** patients divided by T-score (osteopenia/osteoporosis vs healthy controls matched for age and sex)
- **Intervention:** endogenous irisin levels
- **Source:** *Irisin Correlates Positively With BMD in a Cohort of Older Adult Patients and Downregulates the Senescent Marker p21 in Osteoblasts* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.4192`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -0.515R (irisin serum levels negatively correlated with age (R = -0.5); 0.619R (irisin serum levels positively correlated with femoral BMD (); 0.765R (FNDC5 positive fibers positively correlate with BMD of total)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 60 · effect_size

**Finding:** D+Q treatment increased p53 gene expression (P = 0.041)

- **Value:** 0.041
- **Population:** mice, young and old females
- **Intervention:** dasatinib plus quercetin (D+Q)
- **Source:** *Dasatinib plus quercetin prevents uterine age-related dysfunction and fibrosis in mice* — Aging (2020)
  · DOI: `10.18632/aging.102772`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.016 (D+Q treatment decreased miR34a (P = 0.016)); 0.005 (Aging promoted downregulation of the Pi3k/Akt1/mTor signalin); 0.029 (reduction in expression of miR34c (P = 0.029), miR126a (P = )

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `adverse`


## #4 — score 76 · adverse

**Finding:** was associated with a > 50% mortality rate

- **Value:** 50.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `adverse` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `duration`


## #5 — score 62 · duration

**Finding:** BMAT was significantly elevated in radiated bones at day 7.

- **Value:** 7.0
- **Population:** radiated mice
- **Intervention:** radiation
- **Source:** *Bone Marrow Adiposity in Models of Radiation- and Aging-Related Bone Loss Is Dependent on Cellular Senescence* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.4537`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `duration` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
