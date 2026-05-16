# Top 5 interesting findings — metformin

**Snapshot:** 2026-05-16T14-16-16Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=metformin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 32
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 80 · effect_size

**Finding:** The highest percentage of MET removal using OPAC was 97.23%.

- **Value:** 97.23%
- **Population:** metformin in aqueous solutions
- **Intervention:** orange peel activated carbon (OPAC)
- **Source:** *Metformin adsorption onto activated carbon prepared by acid activation and carbonization of orange peel* — International Journal of Phytoremediation (2022)
  · DOI: `10.1080/15226514.2022.2064815`
- **Validator:** researka-tier2

- **Why it matters:** This high removal efficiency indicates OPAC could be a viable method for stripping metformin from water supplies, mitigating environmental drug pollution.
- **Caution:** The study was conducted on simplified aqueous solutions, not accounting for real-world wastewater complexity or competing substances.
- **Next question:** Can OPAC maintain this effectiveness in treating actual hospital effluent containing metformin and other pharmaceuticals?

---

## #2 — score 72 · effect_size

**Finding:** exercise and metformin reduced sTNFαR2 and IL6 (-38.7%; 95% CI, -52.3, -18.9)

- **Value:** -38.7%
- **Population:** patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes
- **Intervention:** exercise and metformin
- **Source:** *Effect of Exercise or Metformin on Biomarkers of Inflammation in Breast and Colorectal Cancer: A Randomized Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0188`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -13.1% (exercise and metformin reduced sTNFαR2 (-13.1%; 95% CI, -22.); -13.9% (metformin alone did not change hs-CRP (-13.9%; 95% CI, -40.0)

- **Why it matters:** Pairing exercise with metformin may provide a practical, dual-pronged strategy to lower inflammation in cancer survivors, potentially aiding recovery and reducing side effects.
- **Caution:** The findings are limited to cancer survivors with low baseline characteristics, so results might not extend to all cancer patients or treatment phases.
- **Next question:** Does this combination therapy lead to tangible improvements in long-term cancer outcomes, such as reduced recurrence or improved survival?

---

## #3 — score 71 · effect_size

**Finding:** Metformin (150 mg/kg) as a single agent inhibits the growth of both PDX tumors by at least 50% (P < 0.05) when administered orally for 24 days.

- **Value:** 50.0%
- **Population:** colorectal cancer patient-derived xenografts (PDX)
- **Intervention:** metformin (150 mg/kg)
- **Source:** *Metformin Inhibits Cellular Proliferation and Bioenergetics in Colorectal Cancer Patient–Derived Xenografts* — Molecular Cancer Therapeutics (2017)
  · DOI: `10.1158/1535-7163.mct-16-0793`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's strong inhibition of colorectal cancer growth in PDX models supports its potential as a repurposed anti-cancer drug, especially for targeted therapies.
- **Caution:** The effect was observed in mouse models with a fixed dose over 24 days, which may not translate directly to human efficacy or optimal dosing.
- **Next question:** How do metformin's anti-tumor effects in these PDX models compare to its performance in human colorectal cancer clinical trials?

---

## #4 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's dramatic reduction in tumor burden in mice exposed to tobacco carcinogens suggests a promising role in cancer prevention for high-risk individuals.
- **Caution:** The study used a specific mouse strain and carcinogen induction, which may not fully replicate human cancer development or metformin's preventive effects.
- **Next question:** Can metformin effectively prevent cancer in humans with significant tobacco exposure, and what are the long-term safety considerations?

---

## #5 — score 70 · effect_size

**Finding:** inhibition of cell proliferation with an effect of 80% for the combination with 0.3 mg/mL and 0.4 mg/mL and a constant concentration of metformin

- **Value:** 80.0%
- **Population:** pancreatic cancer cell line MiaPaCa-2
- **Intervention:** combination of metformin (20 mM) and boswellic acid nanoparticles (0.3 mg/mL or 0.4 mg/mL)
- **Source:** *Combination of Anti-Diabetic Drug Metformin and Boswellic Acid Nanoparticles: A Novel Strategy for Pancreatic Cancer Therapy* — Journal of Biomedical Nanotechnology (2014)
  · DOI: `10.1166/jbn.2015.1877`
- **Validator:** researka-tier2

- **Why it matters:** The synergistic inhibition of pancreatic cancer cell proliferation with metformin combinations opens new possibilities for combination therapies against this hard-to-treat cancer.
- **Caution:** This in vitro study on a single cell line used specific concentrations that may not be clinically achievable or reflective of in vivo tumor environments.
- **Next question:** What are the in vivo therapeutic benefits and toxicity risks of this metformin combination, and how does it compare to current pancreatic cancer treatments?

---
