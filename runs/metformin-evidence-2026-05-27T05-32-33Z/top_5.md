# Top 5 interesting findings — metformin

**Snapshot:** 2026-05-27T05-32-33Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=metformin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 32
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=8, regimen_or_dose=1)

---

## #1 — score 100 · effect_size

**Finding:** preadmission metformin use was associated with 39% lower of 30-day mortality (HR = 0.61, 95% CI: 0.46-0.81, p = 0.007)

- **Value:** 0.61HR
- **Population:** sepsis patients with type 2 diabetes
- **Intervention:** preadmission metformin use
- **Alpha cues:** translation_context, functional_endpoint
- **Source:** *Association Between Preadmission Metformin Use and Outcomes in Intensive Care Unit Patients With Sepsis and Type 2 Diabetes: A Cohort Study* — Frontiers in Medicine (2021)
  · DOI: `10.3389/fmed.2021.640785`
- **Validator:** researka-tier2

- **Why it matters:** For diabetic patients hospitalized with sepsis, prior metformin use may cut short-term mortality nearly in half, offering a potential protective benefit during acute infection.
- **Caution:** This finding relies on observational data from a single study, which may not fully control for confounders like diabetes severity or metformin dosage variations.
- **Next question:** Should metformin be actively maintained or started in septic diabetic patients to improve survival, and what are the risks?

---

## #2 — score 90 · effect_size

**Finding:** metformin is associated with 34% lower COVID-19 mortality [odds ratio (OR), 0.66; 95% confidence interval (CI), 0.56-0.78]

- **Value:** 0.66OR
- **Population:** COVID-19 patients
- **Intervention:** metformin
- **Alpha cues:** functional_endpoint
- **Source:** *Metformin in Patients With COVID-19: A Systematic Review and Meta-Analysis* — Frontiers in Medicine (2021)
  · DOI: `10.3389/fmed.2021.704666`
- **Validator:** researka-tier2

- **Why it matters:** Metformin could serve as an accessible, low-cost treatment to reduce COVID-19 deaths, particularly in regions with high diabetes rates.
- **Caution:** The odds ratio is aggregated from diverse studies with potential biases, limiting causal certainty and ignoring dosage effects.
- **Next question:** What specific mechanisms allow metformin to lower COVID-19 mortality, and is timing of administration critical?

---

## #3 — score 85 · effect_size

**Finding:** Use of metformin was associated with a significantly better overall and progression-free survival of patients with WHO grade III glioma (HR for OS = 0.30; 95% CI = 0.11-0.81)

- **Value:** 0.3HR
- **Population:** patients with WHO grade III glioma (high-grade glioma)
- **Intervention:** use of metformin
- **Alpha cues:** functional_endpoint
- **Source:** *Use of metformin and survival of patients with high‐grade glioma* — International Journal of Cancer (2018)
  · DOI: `10.1002/ijc.31783`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.29HR (HR for PFS = 0.29; 95% CI = 0.11-0.78); 0.85HR (there were no significant relations with PFS (HR = 0.85; 95%); 0.83HR (there were no significant relations with OS (HR = 0.83; 95% )

- **Why it matters:** Integrating metformin with standard glioma treatments might significantly extend survival for patients with high-grade brain tumors, a condition with poor prognosis.
- **Caution:** Results stem from a focused cohort study, which may not account for glioma molecular subtypes or variations in concurrent therapies.
- **Next question:** Can metformin effectively reach glioma tissue to exert its effects, and how does it interact with current chemoradiation regimens?

---

## #4 — score 80 · effect_size

**Finding:** Cancer mortality was reduced by 34% (SRR, 0.66; 95% CI, 0.54-0.81; I(2) = 21%).

- **Value:** 0.66RR
- **Population:** patients with diabetes
- **Intervention:** metformin
- **Alpha cues:** functional_endpoint
- **Source:** *Metformin and Cancer Risk and Mortality: A Systematic Review and Meta-analysis Taking into Account Biases and Confounders* — Cancer Prevention Research (2014)
  · DOI: `10.1158/1940-6207.capr-13-0424`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.69RR (Overall cancer incidence was reduced by 31% [summary relativ)

- **Why it matters:** Diabetic patients on metformin may see a substantial drop in cancer-related deaths, suggesting metformin's role extends beyond glucose control to cancer prevention.
- **Caution:** This summary risk ratio aggregates heterogeneous studies, potentially overlooking confounders like cancer stage or other diabetes medications.
- **Next question:** Does metformin's cancer mortality benefit apply to specific cancer types, or is it a broad effect linked to metabolic improvements?

---

## #5 — score 72 · effect_size

**Finding:** adjusted hazard ratio of 0.34 (95% confidence interval: 0.33 to 0.36)

- **Value:** 0.34HR
- **Population:** elderly patients with type 2 diabetes mellitus (≥60 years old)
- **Intervention:** metformin use
- **Alpha cues:** translation_context
- **Source:** *Metformin in elderly type 2 diabetes mellitus: dose-dependent dementia risk reduction* — Brain (2023)
  · DOI: `10.1093/brain/awad366`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties metformin use in elderly patients with type 2 diabetes mellitus (≥60 years old) to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
