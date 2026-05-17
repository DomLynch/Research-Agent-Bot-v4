# Top 5 interesting findings — metformin

**Snapshot:** 2026-05-16T16-13-59Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=metformin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 32
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=6, environmental_remediation=1, model_context=1, preclinical_cancer=4)

---

## #1 — score 72 · effect_size

**Finding:** exercise and metformin reduced sTNFαR2 and IL6 (-38.7%; 95% CI, -52.3, -18.9)

- **Value:** -38.7%
- **Population:** patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes
- **Intervention:** exercise and metformin
- **Source:** *Effect of Exercise or Metformin on Biomarkers of Inflammation in Breast and Colorectal Cancer: A Randomized Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0188`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -13.1% (exercise and metformin reduced sTNFαR2 (-13.1%; 95% CI, -22.); -13.9% (metformin alone did not change hs-CRP (-13.9%; 95% CI, -40.0)

- **Why it matters:** Combining exercise with metformin may reduce inflammation markers in cancer survivors, potentially lowering recurrence risk.
- **Caution:** This is from a single study (k=1) in human patients post-therapy, with unspecified exercise and metformin doses.
- **Next question:** Does this inflammation reduction translate to improved survival or reduced cancer recurrence in larger trials?

---

## #2 — score 71 · effect_size

**Finding:** Metformin (150 mg/kg) as a single agent inhibits the growth of both PDX tumors by at least 50% (P < 0.05) when administered orally for 24 days.

- **Value:** 50.0%
- **Population:** colorectal cancer patient-derived xenografts (PDX)
- **Intervention:** metformin (150 mg/kg)
- **Source:** *Metformin Inhibits Cellular Proliferation and Bioenergetics in Colorectal Cancer Patient–Derived Xenografts* — Molecular Cancer Therapeutics (2017)
  · DOI: `10.1158/1535-7163.mct-16-0793`
- **Validator:** researka-tier2

- **Why it matters:** Metformin inhibits colorectal cancer tumor growth in PDX models, supporting its potential as a therapeutic agent.
- **Caution:** PDX models are not human patients, and the high dose of 150 mg/kg may not be clinically feasible or safe.
- **Next question:** What is the optimal and tolerable metformin dose for inhibiting colorectal cancer in human patients?

---

## #3 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's 72% tumor reduction in a mouse model suggests it could help prevent lung cancer in tobacco-exposed individuals.
- **Caution:** This study uses a specific mouse strain (A/J) and carcinogen (NNK), limiting direct applicability to human lung cancer.
- **Next question:** Can metformin be tested in human trials for lung cancer prevention in high-risk populations, such as smokers?

---

## #4 — score 70 · effect_size

**Finding:** inhibition of cell proliferation with an effect of 80% for the combination with 0.3 mg/mL and 0.4 mg/mL and a constant concentration of metformin

- **Value:** 80.0%
- **Population:** pancreatic cancer cell line MiaPaCa-2
- **Intervention:** combination of metformin (20 mM) and boswellic acid nanoparticles (0.3 mg/mL or 0.4 mg/mL)
- **Source:** *Combination of Anti-Diabetic Drug Metformin and Boswellic Acid Nanoparticles: A Novel Strategy for Pancreatic Cancer Therapy* — Journal of Biomedical Nanotechnology (2014)
  · DOI: `10.1166/jbn.2015.1877`
- **Validator:** researka-tier2

- **Why it matters:** Metformin in combination with other agents shows 80% inhibition of pancreatic cancer cell proliferation, hinting at new treatment strategies.
- **Caution:** This is an in vitro study using the MiaPaCa-2 cell line, which doesn't account for whole-organism effects or tumor microenvironment.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #5 — score 70 · effect_size

**Finding:** leading to 96% inhibition of cell viability in LNCaP prostate cancer cells

- **Value:** 96.0%
- **Population:** LNCaP prostate cancer cells
- **Intervention:** combination of metformin and 2-deoxyglucose
- **Source:** *Targeting Cancer Cell Metabolism: The Combination of Metformin and 2-Deoxyglucose Induces p53-Dependent Apoptosis in Prostate Cancer Cells* — Cancer Research (2010)
  · DOI: `10.1158/0008-5472.can-09-2782`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
