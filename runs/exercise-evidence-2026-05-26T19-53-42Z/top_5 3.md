# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-26T19-53-42Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=exercise) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 42
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=6, model_context=3)

---

## #1 — score 91 · effect_size

**Finding:** Impact exercise improved total vBMD at the proximal femur (MD = 3.11% [95% CI 1.07, 5.14%]).

- **Value:** 3.11%
- **Population:** all participants in included RCTs
- **Intervention:** impact exercise
- **Alpha cues:** functional_endpoint
- **Source:** *Effects of Moderate- to High-Impact Exercise Training on Bone Structure Across the Lifespan: A Systematic Review and Meta-Analysis of Randomized Controlled Trials* — Journal of Bone and Mineral Research (2023)
  · DOI: `10.1002/jbmr.4899`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.78% (Impact exercise improved cortical thickness at the mid/proxi); 0.54% (Impact exercise improved trabecular vBMD at the distal tibia)

- **Why it matters:** A 3.11% increase in bone density at the hip could lower fracture risk in aging populations, preserving mobility and reducing healthcare burdens.
- **Caution:** Aggregated RCT data may mask variability in exercise protocols, limiting dose-specific recommendations for clinical practice.
- **Next question:** What minimum exercise frequency and intensity are required to maintain these bone density gains long-term?

---

## #2 — score 90 · effect_size

**Finding:** exercise-based CR likely results in a slight reduction in all-cause mortality (risk ratio (RR) 0.87, 95% CI 0.73 to 1.04; 25 trials; moderate certainty evidence)

- **Value:** 0.87RR
- **Population:** adults with coronary heart disease (post-MI, post-revascularisation, angina)
- **Intervention:** exercise-based cardiac rehabilitation
- **Alpha cues:** functional_endpoint
- **Source:** *Exercise-based cardiac rehabilitation for coronary heart disease* — Cochrane Database of Systematic Reviews (2021)
  · DOI: `10.1002/14651858.cd001800.pub4`
- **Validator:** researka-tier2

- **Why it matters:** A 13% reduction in all-cause mortality for coronary heart disease patients could save lives if integrated into standard cardiac rehabilitation programs.
- **Caution:** The confidence interval includes values above 1, suggesting the effect may not be statistically significant, and moderate certainty stems from diverse trial designs.
- **Next question:** Does this mortality benefit persist beyond the intervention period, and which exercise types yield the most improvement?

---

## #3 — score 90 · effect_size

**Finding:** Exercise significantly reduced the risk of recurrence in cancer survivors (RR = 0.52, 95% CI = 0.29-0.92, P = .030).

- **Value:** 0.52RR
- **Population:** cancer survivors
- **Intervention:** exercise
- **Alpha cues:** functional_endpoint
- **Source:** *Effect of Exercise on Mortality and Recurrence in Patients With Cancer: A Systematic Review and Meta-Analysis* — Integrative Cancer Therapies (2020)
  · DOI: `10.1177/1534735420917462`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.76RR (Exercise significantly reduced the risk of mortality in pati)

- **Why it matters:** Halving cancer recurrence risk through exercise offers a cost-effective, accessible strategy to enhance survivorship and reduce treatment costs.
- **Caution:** The wide confidence interval indicates imprecision, and the evidence may not generalize across all cancer subtypes or stages.
- **Next question:** Is there a threshold of exercise volume or intensity that maximizes recurrence prevention across different cancers?

---

## #4 — score 85 · effect_size

**Finding:** exercise v anticoagulants 0.09, 95% credible intervals 0.01 to 0.70

- **Value:** 0.09OR
- **Population:** patients with stroke
- **Intervention:** exercise
- **Alpha cues:** functional_endpoint
- **Source:** *Comparative effectiveness of exercise and drug interventions on mortality outcomes: metaepidemiological study* — British Journal of Sports Medicine (2015)
  · DOI: `10.1136/bjsports-2015-f5577rep`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.1OR (exercise v antiplatelets 0.10, 0.01 to 0.62)

- **Why it matters:** Exercise matching anticoagulants' efficacy could provide a safer, non-pharmacological option for stroke recovery, minimizing bleeding risks.
- **Caution:** Credible intervals from a Bayesian model may reflect prior assumptions, and the comparison lacks detail on exercise duration or type.
- **Next question:** What specific exercise regimens are as effective as anticoagulants in preventing secondary strokes or improving outcomes?

---

## #5 — score 60 · effect_size

**Finding:** Pooled analysis showed small effect favoring exercise (SMD = 0.27, 95% CI [-0.58, 0.04], P = 0.09).

- **Value:** 0.27%
- **Population:** adults with major depressive disorder not on antidepressants or receiving psychological therapy
- **Intervention:** physical exercise modalities
- **Alpha cues:** baseline
- **Source:** *Physical exercise and major depressive disorder in adults: systematic review and meta-analysis* — Scientific Reports (2023)
  · DOI: `10.1038/s41598-023-39783-2`
- **Validator:** researka-tier2

- **Why it matters:** A small exercise effect on depression could supplement treatments for those avoiding medications or therapy, expanding mental health support options.
- **Caution:** The effect is not significant (P=0.09) with a confidence interval crossing zero, indicating high uncertainty and potential for no benefit.
- **Next question:** Does exercise benefit depression severity equally across symptom profiles, and how does adherence influence outcomes?

---
