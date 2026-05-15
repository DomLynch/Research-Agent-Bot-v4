# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-15T19-19-20Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=exercise) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 40
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 80 · effect_size

**Finding:** Participants randomized to diet and diet+exercise arms had greater reductions in E-DII (-104.4% and -84.4%), versus controls (-34.8%, both P < 0.001).

- **Value:** -104.4%
- **Population:** overweight/obese, healthy, postmenopausal women
- **Intervention:** caloric-restriction diet
- **Source:** *Changes in Dietary Inflammatory Index Patterns with Weight Loss in Women: A Randomized Controlled Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0181`
- **Validator:** researka-tier2

- **Why it matters:** Diet and exercise combined significantly reduce dietary inflammation in postmenopausal women, which could lower risks of chronic diseases like cardiovascular conditions.
- **Caution:** This is based on a single randomized trial, so findings may not generalize to other populations or long-term outcomes.
- **Next question:** Do these inflammation reductions translate to fewer cardiovascular events or improved metabolic health over time?

---

## #2 — score 75 · effect_size

**Finding:** tumor-bearing mice with access to running wheels showed reduced growth of MDA-MB-231 (-66%, P < 0.01) tumors

- **Value:** -66.0%
- **Population:** tumor-bearing mice (MDA-MB-231 xenograft)
- **Intervention:** voluntary running wheel exercise
- **Source:** *Exercise-Induced Catecholamines Activate the Hippo Tumor Suppressor Pathway to Reduce Risks of Breast Cancer Development* — Cancer Research (2017)
  · DOI: `10.1158/0008-5472.can-16-3125`
- **Validator:** researka-tier2

- **Why it matters:** Exercise access in mice reduces MDA-MB-231 tumor growth by 66%, suggesting physical activity could be an adjunct therapy in cancer treatment.
- **Caution:** This is an animal model using xenografts, and human exercise responses or tumor microenvironments may differ significantly.
- **Next question:** What exercise intensity and duration are required to achieve similar tumor inhibition in human cancer patients?

---

## #3 — score 74 · effect_size

**Finding:** 6MWD was greater in the intervention group (MD 57 m, 95% CI 34 to 80).

- **Value:** 57.0m
- **Population:** people following lung resection for non-small cell lung cancer
- **Intervention:** exercise training including aerobic, resistance, or combination
- **Source:** *Exercise training undertaken by people within 12 months of lung resection for non-small cell lung cancer* — Cochrane Database of Systematic Reviews (2019)
  · DOI: `10.1002/14651858.cd009955.pub3`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 2.97mL/kg/min (VO2peak was greater in the intervention group (MD 2.97 mL/kg)

- **Why it matters:** A 57-meter improvement in 6-minute walk distance post-lung cancer surgery enhances functional capacity and quality of life during recovery.
- **Caution:** The study may have limited sample size and short-term follow-up, and the intervention specifics (e.g., exercise type) are not detailed.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #4 — score 73 · effect_size

**Finding:** patients with PAD had a greater reduction in SmO2 (-54 ± 10 vs. -12 ± 4%, P = 0.001)

- **Value:** -54.0%
- **Population:** patients with peripheral artery disease and age-matched healthy controls
- **Intervention:** fatiguing plantar flexion exercise (from 0.5 to 7 kg for up to 14 min)
- **Source:** *Blood pressure and calf muscle oxygen extraction during plantar flexion exercise in peripheral artery disease* — Journal of Applied Physiology (2017)
  · DOI: `10.1152/japplphysiol.01110.2016`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 18.0mmHg (patients with PAD had a greater increase in mean arterial BP); 14.0beats/min (patients with PAD had a greater increase in HR (14 ± 2 vs. 6)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #5 — score 72 · effect_size

**Finding:** exercise and metformin reduced sTNFαR2 and IL6 (-38.7%; 95% CI, -52.3, -18.9)

- **Value:** -38.7%
- **Population:** patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes
- **Intervention:** exercise and metformin
- **Source:** *Effect of Exercise or Metformin on Biomarkers of Inflammation in Breast and Colorectal Cancer: A Randomized Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0188`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -30.2% (Compared with control, exercise alone reduced hs-CRP [-30.2%); -30.9% (exercise alone reduced hs-CRP and IL6 (-30.9%; 95% CI, -47.3); -13.1% (exercise and metformin reduced sTNFαR2 (-13.1%; 95% CI, -22.)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
