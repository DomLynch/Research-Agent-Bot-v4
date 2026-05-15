# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-15T18-51-41Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=exercise) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 43
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

- **Why it matters:** Diet combined with exercise significantly reduces dietary inflammation in overweight postmenopausal women, aiding weight management and chronic disease prevention.
- **Caution:** The study's focus on healthy postmenopausal women limits generalizability to other demographics or health conditions.
- **Next question:** Does this reduction in dietary inflammation translate to lower incidence of cardiovascular events or diabetes in this population?

---

## #2 — score 75 · effect_size

**Finding:** Physical exercise increased ULK1 phosphorylation at Ser(555) and decreased lipidation of light chain 3B.

- **Value:** 555.0
- **Population:** healthy humans
- **Intervention:** 1-h cycling exercise at 50% maximal O2 uptake
- **Source:** *Physical exercise increases autophagic signaling through ULK1 in human skeletal muscle* — Journal of Applied Physiology (2015)
  · DOI: `10.1152/japplphysiol.01116.2014`
- **Validator:** researka-tier2

- **Why it matters:** Exercise promotes autophagy in healthy humans, enhancing cellular repair mechanisms that could mitigate age-related diseases.
- **Caution:** Likely based on a small sample under controlled lab conditions, which may not reflect varied real-world exercise patterns.
- **Next question:** How do these molecular changes in autophagy from exercise correlate with long-term health outcomes like reduced chronic inflammation?

---

## #3 — score 75 · effect_size

**Finding:** tumor-bearing mice with access to running wheels showed reduced growth of MDA-MB-231 (-66%, P < 0.01) tumors

- **Value:** -66.0%
- **Population:** tumor-bearing mice (MDA-MB-231 xenograft)
- **Intervention:** voluntary running wheel exercise
- **Source:** *Exercise-Induced Catecholamines Activate the Hippo Tumor Suppressor Pathway to Reduce Risks of Breast Cancer Development* — Cancer Research (2017)
  · DOI: `10.1158/0008-5472.can-16-3125`
- **Validator:** researka-tier2

- **Why it matters:** Wheel running in tumor-bearing mice markedly slows breast cancer growth, suggesting exercise as a potential adjuvant cancer therapy.
- **Caution:** Results from an MDA-MB-231 xenograft mouse model may not directly apply to human cancer biology or treatment.
- **Next question:** What specific exercise regimens can replicate tumor growth inhibition in human breast cancer patients, and through what mechanisms?

---

## #4 — score 75 · effect_size

**Finding:** Leucine alone stimulated ribosomal protein s6 kinase 1 (S6K1) phosphorylation ∼280% more than placebo and EAA-Leu after exercise.

- **Value:** 280.0%
- **Population:** Nine male subjects
- **Intervention:** leucine alone
- **Source:** *Leucine does not affect mechanistic target of rapamycin complex 1 assembly but is required for maximal ribosomal protein s6 kinase 1 activity in human skeletal muscle following resistance exercise* — The FASEB Journal (2015)
  · DOI: `10.1096/fj.15-273474`
- **Validator:** researka-tier2

- **Why it matters:** Leucine alone enhances muscle protein synthesis pathways more than other amino acids post-exercise, supporting muscle recovery and growth.
- **Caution:** Limited to a small study of nine male subjects, with acute effects that may not reflect long-term outcomes across diverse populations.
- **Next question:** Does leucine's superior effect on S6K1 phosphorylation lead to measurable improvements in muscle mass or strength in broader exercise contexts?

---

## #5 — score 74 · effect_size

**Finding:** 6MWD was greater in the intervention group (MD 57 m, 95% CI 34 to 80).

- **Value:** 57.0m
- **Population:** people following lung resection for non-small cell lung cancer
- **Intervention:** exercise training including aerobic, resistance, or combination
- **Source:** *Exercise training undertaken by people within 12 months of lung resection for non-small cell lung cancer* — Cochrane Database of Systematic Reviews (2019)
  · DOI: `10.1002/14651858.cd009955.pub3`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 2.97mL/kg/min (VO2peak was greater in the intervention group (MD 2.97 mL/kg)

- **Why it matters:** Exercise interventions improve six-minute walk distance in lung cancer surgery patients, boosting functional recovery and quality of life.
- **Caution:** The intervention's specifics, such as type and intensity, are unspecified, affecting reproducibility and clinical application.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
