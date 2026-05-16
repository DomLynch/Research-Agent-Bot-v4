# Top 5 interesting findings — metformin

**Snapshot:** 2026-05-16T15-19-54Z
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

- **Why it matters:** Achieving 97.23% removal of metformin using OPAC could enhance water treatment methods to reduce pharmaceutical pollution in aquatic environments.
- **Caution:** This is a single study (k=1) conducted in controlled laboratory settings with specific conditions, limiting immediate applicability to real-world water systems.
- **Next question:** How effective is OPAC in removing metformin from complex real-world wastewater with varying organic and inorganic components?

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

- **Why it matters:** The 38.7% reduction in inflammatory markers sTNFαR2 and IL6 could lower cancer recurrence risk and improve quality of life for breast and colorectal cancer survivors.
- **Caution:** The study combined exercise and metformin in a specific post-therapy cancer population, making it difficult to attribute effects solely to metformin or generalize to other groups.
- **Next question:** What is the independent contribution of metformin versus exercise in reducing inflammation, and how does this translate to clinical outcomes like survival rates?

---

## #3 — score 71 · effect_size

**Finding:** Metformin (150 mg/kg) as a single agent inhibits the growth of both PDX tumors by at least 50% (P < 0.05) when administered orally for 24 days.

- **Value:** 50.0%
- **Population:** colorectal cancer patient-derived xenografts (PDX)
- **Intervention:** metformin (150 mg/kg)
- **Source:** *Metformin Inhibits Cellular Proliferation and Bioenergetics in Colorectal Cancer Patient–Derived Xenografts* — Molecular Cancer Therapeutics (2017)
  · DOI: `10.1158/1535-7163.mct-16-0793`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's ability to inhibit colorectal cancer PDX tumor growth by at least 50% supports its potential as an anti-cancer agent in human-relevant models.
- **Caution:** This study used a single dose (150 mg/kg) in a mouse PDX model (k=1), which may not directly translate to human pharmacokinetics or efficacy.
- **Next question:** How do different dosing regimens of metformin affect tumor inhibition in PDX models, and are there biomarkers predicting response?

---

## #4 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** A 72% reduction in tumor burden in tobacco carcinogen-induced models suggests metformin could be repurposed for lung cancer prevention in high-risk individuals.
- **Caution:** The study was limited to A/J mice treated with NNK (k=1), a specific carcinogen, which may not fully mimic human lung cancer pathways or risk factors.
- **Next question:** Does metformin's mTOR inhibition mechanism prevent tumor recurrence or metastasis in this model, and how does it compare to targeted therapies?

---

## #5 — score 70 · effect_size

**Finding:** inhibition of cell proliferation with an effect of 80% for the combination with 0.3 mg/mL and 0.4 mg/mL and a constant concentration of metformin

- **Value:** 80.0%
- **Population:** pancreatic cancer cell line MiaPaCa-2
- **Intervention:** combination of metformin (20 mM) and boswellic acid nanoparticles (0.3 mg/mL or 0.4 mg/mL)
- **Source:** *Combination of Anti-Diabetic Drug Metformin and Boswellic Acid Nanoparticles: A Novel Strategy for Pancreatic Cancer Therapy* — Journal of Biomedical Nanotechnology (2014)
  · DOI: `10.1166/jbn.2015.1877`
- **Validator:** researka-tier2

- **Why it matters:** An 80% inhibition of pancreatic cancer cell proliferation with metformin combinations indicates promising synergy for enhancing treatment efficacy in a hard-to-treat cancer.
- **Caution:** This is an in vitro study on a single cell line (MiaPaCa-2) with fixed concentrations (k=1), lacking validation in animal models or human clinical settings.
- **Next question:** What specific molecular pathways are involved in the synergistic inhibition between metformin and the combined agents, and can this be replicated in vivo?

---
