# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-16T16-07-56Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=exercise) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 37
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=6, model_context=2, molecular_mechanism=1, preclinical_cancer=1)

---

## #1 — score 80 · effect_size

**Finding:** Participants randomized to diet and diet+exercise arms had greater reductions in E-DII (-104.4% and -84.4%), versus controls (-34.8%, both P < 0.001).

- **Value:** -104.4%
- **Population:** overweight/obese, healthy, postmenopausal women
- **Intervention:** caloric-restriction diet
- **Source:** *Changes in Dietary Inflammatory Index Patterns with Weight Loss in Women: A Randomized Controlled Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0181`
- **Validator:** researka-tier2

- **Why it matters:** Diet combined with exercise drastically reduces inflammatory markers in postmenopausal women, potentially mitigating risks of age-related chronic conditions.
- **Caution:** The study focused solely on postmenopausal women, limiting generalizability to other populations or genders.
- **Next question:** Do these inflammation reductions lead to tangible decreases in cardiovascular or metabolic disease incidence over time?

---

## #2 — score 75 · effect_size

**Finding:** tumor-bearing mice with access to running wheels showed reduced growth of MDA-MB-231 (-66%, P < 0.01) tumors

- **Value:** -66.0%
- **Population:** tumor-bearing mice (MDA-MB-231 xenograft)
- **Intervention:** voluntary running wheel exercise
- **Source:** *Exercise-Induced Catecholamines Activate the Hippo Tumor Suppressor Pathway to Reduce Risks of Breast Cancer Development* — Cancer Research (2017)
  · DOI: `10.1158/0008-5472.can-16-3125`
- **Validator:** researka-tier2

- **Why it matters:** Voluntary running in mice markedly suppresses breast cancer tumor growth, suggesting exercise as a viable adjunct therapy for cancer management.
- **Caution:** Findings are from a mouse xenograft model, which may not replicate human tumor dynamics or exercise responses.
- **Next question:** Can specific exercise modalities or doses replicate this tumor-inhibiting effect in human cancer patients?

---

## #3 — score 73 · effect_size

**Finding:** patients with PAD had a greater reduction in SmO2 (-54 ± 10 vs. -12 ± 4%, P = 0.001)

- **Value:** -54.0%
- **Population:** patients with peripheral artery disease and age-matched healthy controls
- **Intervention:** fatiguing plantar flexion exercise (from 0.5 to 7 kg for up to 14 min)
- **Source:** *Blood pressure and calf muscle oxygen extraction during plantar flexion exercise in peripheral artery disease* — Journal of Applied Physiology (2017)
  · DOI: `10.1152/japplphysiol.01110.2016`
- **Validator:** researka-tier2

- **Why it matters:** PAD patients experience severe oxygen depletion during exercise, underscoring the need for customized rehab to avoid symptom exacerbation.
- **Caution:** The study compared two groups without testing interventions, so causal links to exercise adaptations remain unclear.
- **Next question:** Could targeted aerobic training improve skeletal muscle oxygen utilization in PAD patients?

---

## #4 — score 72 · effect_size

**Finding:** exercise and metformin reduced sTNFαR2 and IL6 (-38.7%; 95% CI, -52.3, -18.9)

- **Value:** -38.7%
- **Population:** patients with breast and colorectal cancer who completed standard therapy, low baseline physical activity, without type 2 diabetes
- **Intervention:** exercise and metformin
- **Source:** *Effect of Exercise or Metformin on Biomarkers of Inflammation in Breast and Colorectal Cancer: A Randomized Trial* — Cancer Prevention Research (2020)
  · DOI: `10.1158/1940-6207.capr-20-0188`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -30.9% (exercise alone reduced hs-CRP and IL6 (-30.9%; 95% CI, -47.3); -30.2% (Compared with control, exercise alone reduced hs-CRP [-30.2%); -13.1% (exercise and metformin reduced sTNFαR2 (-13.1%; 95% CI, -22.)

- **Why it matters:** Post-cancer therapy, pairing exercise with metformin lowers inflammation, potentially enhancing recovery and reducing recurrence risks.
- **Caution:** The combined treatment obscures individual contributions of exercise versus metformin, weakening causal attribution.
- **Next question:** What exercise intensity or frequency optimizes anti-inflammatory benefits when co-administered with metformin?

---

## #5 — score 70 · effect_size

**Finding:** Mixed-muscle protein fractional synthetic rate increased by 42% at 3 h postexercise and 69% at 24 h postexercise in CON.

- **Value:** 69.0%
- **Population:** sixteen healthy young men (CON group)
- **Intervention:** BFR exercise (control)
- **Source:** *Activation of mTORC1 signaling and protein synthesis in human muscle following blood flow restriction exercise is inhibited by rapamycin* — American Journal of Physiology-Endocrinology and Metabolism (2014)
  · DOI: `10.1152/ajpendo.00600.2013`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 42.0% (Mixed-muscle protein fractional synthetic rate increased by )

- **Why it matters:** Exercise rapidly enhances muscle protein synthesis, informing post-workout nutrition and training strategies for optimal muscle repair and growth.
- **Caution:** Participants were limited to healthy young men, so results may not apply to older adults, women, or those with health conditions.
- **Next question:** How do variables like age, gender, or protein supplementation influence the timing and magnitude of exercise-induced muscle synthesis?

---
