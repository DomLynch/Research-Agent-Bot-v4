# Top 5 interesting findings — metformin

**Snapshot:** 2026-05-15T18-52-55Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=metformin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 38
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

- **Why it matters:** OPAC's 97.23% removal efficiency for metformin from water demonstrates its strong potential for environmental cleanup of pharmaceutical pollutants.
- **Caution:** This high efficacy is based on controlled aqueous solutions, not real-world wastewater with complex contaminants.
- **Next question:** How does OPAC perform in scaling up to handle metformin-contaminated water sources with varying organic loads?

---

## #2 — score 75 · effect_size

**Finding:** Urine from >90 MF-treated T2DM patients was analyzed, with increased levels of MF directly correlating with elevations in IMZ.

- **Value:** 90.0
- **Population:** metformin-treated T2DM patients
- **Intervention:** metformin
- **Source:** *Metformin Scavenges Methylglyoxal To Form a Novel Imidazolinone Metabolite in Humans* — Chemical Research in Toxicology (2016)
  · DOI: `10.1021/acs.chemrestox.5b00497`
- **Validator:** researka-tier2

- **Why it matters:** The direct correlation between metformin and IMZ levels in diabetic patient urine could improve drug adherence monitoring and metabolic insight.
- **Caution:** The study is observational and only shows correlation in a specific T2DM population, not causation.
- **Next question:** What mechanistic links between metformin metabolism and IMZ elevation exist, and do they influence clinical outcomes?

---

## #3 — score 75 · effect_size

**Finding:** the NOAEL dose of metformin (200 mg/kg/day) showed a limited efficiency in the metabolic disruption caused by chronic Cd exposure.

- **Value:** 200.0mg/kg/day
- **Population:** Wistar rats exposed to cadmium
- **Intervention:** Metformin at 200 mg/kg/day
- **Source:** *The NOAEL Metformin Dose Is Ineffective against Metabolic Disruption Induced by Chronic Cadmium Exposure in Wistar Rats* — Toxics (2018)
  · DOI: `10.3390/toxics6030055`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's NOAEL dose fails to mitigate cadmium-induced metabolic disruption in rats, indicating it may not protect against heavy metal toxicity.
- **Caution:** Results are from a rat model with a fixed dose, limiting direct applicability to human exposures.
- **Next question:** Can adjusted metformin doses or combination therapies effectively counter cadmium toxicity in mammals?

---

## #4 — score 75 · effect_size

**Finding:** DM dams treated with 200 mg/kg metformin in drinking water ameliorated fasting hyperglycemia, glucose intolerance, and insulin resistance with consequent reduction of cellular stress, apoptosis, and NTDs in their embryos

- **Value:** 200.0mg/kg
- **Population:** type 2 diabetic dams (mouse model, HFD-induced) and their embryos
- **Intervention:** 200 mg/kg metformin in drinking water
- **Source:** *Cellular Stress, Excessive Apoptosis, and the Effect of Metformin in a Mouse Model of Type 2 Diabetic Embryopathy* — Diabetes (2015)
  · DOI: `10.2337/db14-1683`
- **Validator:** researka-tier2

- **Why it matters:** Metformin treatment in diabetic mouse dams reduces hyperglycemia and embryo stress, suggesting benefits for maternal and fetal health in diabetes.
- **Caution:** This is a mouse model; human pregnancy dynamics and fetal responses to metformin may differ significantly.
- **Next question:** Does metformin use during human pregnancy improve maternal outcomes without adverse effects on child development?

---

## #5 — score 72 · effect_size

**Finding:** exercise and metformin reduced sTNFαR2 and IL6 (-38.7%; 95% CI, -52.3, -18.9)

- **Value:** -38.7%
- **Population:** patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes
- **Intervention:** exercise and metformin
- **Source:** *Effect of Exercise or Metformin on Biomarkers of Inflammation in Breast and Colorectal Cancer: A Randomized Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0188`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -13.1% (exercise and metformin reduced sTNFαR2 (-13.1%; 95% CI, -22.); -13.9% (metformin alone did not change hs-CRP (-13.9%; 95% CI, -40.0)

- **Why it matters:** Exercise combined with metformin cuts inflammatory markers by nearly 40% in cancer survivors, potentially lowering recurrence risk and enhancing recovery.
- **Caution:** The study focuses on breast and colorectal cancer patients post-therapy, so effects on other cancers or long-term outcomes are unclear.
- **Next question:** Can this anti-inflammatory effect of exercise and metformin translate into measurable reductions in cancer recurrence or mortality?

---
