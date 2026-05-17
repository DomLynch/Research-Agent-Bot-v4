# Top 5 interesting findings — metformin

**Snapshot:** 2026-05-16T18-01-51Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=metformin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 32
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=6, environmental_remediation=1, model_context=1, preclinical_cancer=4)

---

## #1 — score 80 · effect_size

**Finding:** Cancer mortality was reduced by 34% (SRR, 0.66; 95% CI, 0.54-0.81; I(2) = 21%).

- **Value:** 0.66RR
- **Population:** patients with diabetes
- **Intervention:** metformin
- **Alpha cues:** functional_endpoint
- **Source:** *Metformin and Cancer Risk and Mortality: A Systematic Review and Meta-analysis Taking into Account Biases and Confounders* — Cancer Prevention Research (2014)
  · DOI: `10.1158/1940-6207.capr-13-0424`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.69RR (Overall cancer incidence was reduced by 31% [summary relativ)

- **Why it matters:** This is worth checking because it reaches a hard outcome rather than stopping at a proxy.
- **Caution:** Do not overread this as settled: k=2 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #2 — score 72 · effect_size

**Finding:** exercise and metformin reduced sTNFαR2 and IL6 (-38.7%; 95% CI, -52.3, -18.9)

- **Value:** -38.7%
- **Population:** patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes
- **Intervention:** exercise and metformin
- **Alpha cues:** baseline
- **Source:** *Effect of Exercise or Metformin on Biomarkers of Inflammation in Breast and Colorectal Cancer: A Randomized Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0188`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -13.9% (metformin alone did not change hs-CRP (-13.9%; 95% CI, -40.0); -13.1% (exercise and metformin reduced sTNFαR2 (-13.1%; 95% CI, -22.)

- **Why it matters:** This is worth checking because it ties exercise and metformin in patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes to a source-backed effect.
- **Caution:** Do not overread this as settled: k=3 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #3 — score 71 · effect_size

**Finding:** Metformin (150 mg/kg) as a single agent inhibits the growth of both PDX tumors by at least 50% (P < 0.05) when administered orally for 24 days.

- **Value:** 50.0%
- **Population:** colorectal cancer patient-derived xenografts (PDX)
- **Intervention:** metformin (150 mg/kg)
- **Alpha cues:** baseline
- **Source:** *Metformin Inhibits Cellular Proliferation and Bioenergetics in Colorectal Cancer Patient–Derived Xenografts* — Molecular Cancer Therapeutics (2017)
  · DOI: `10.1158/1535-7163.mct-16-0793`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties metformin (150 mg/kg) in colorectal cancer patient-derived xenografts (PDX) to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #4 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Alpha cues:** baseline
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties intraperitoneal metformin in A/J mice treated with tobacco carcinogen NNK to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #5 — score 70 · effect_size

**Finding:** leading to 96% inhibition of cell viability in LNCaP prostate cancer cells

- **Value:** 96.0%
- **Population:** LNCaP prostate cancer cells
- **Intervention:** combination of metformin and 2-deoxyglucose
- **Alpha cues:** baseline
- **Source:** *Targeting Cancer Cell Metabolism: The Combination of Metformin and 2-Deoxyglucose Induces p53-Dependent Apoptosis in Prostate Cancer Cells* — Cancer Research (2010)
  · DOI: `10.1158/0008-5472.can-09-2782`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties combination of metformin and 2-deoxyglucose in LNCaP prostate cancer cells to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
