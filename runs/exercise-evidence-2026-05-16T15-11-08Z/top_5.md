# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-16T15-11-08Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=exercise) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 38
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

- **Why it matters:** This finding supports diet and exercise as effective strategies to reduce inflammation in postmenopausal women, which can help manage obesity-related health conditions.
- **Caution:** The results are from a randomized controlled trial but are specific to overweight/obese postmenopausal women, limiting generalizability to other demographics.
- **Next question:** Future research should investigate if similar inflammation reduction occurs with different exercise types or intensities in this population.

---

## #2 — score 75 · effect_size

**Finding:** tumor-bearing mice with access to running wheels showed reduced growth of MDA-MB-231 (-66%, P < 0.01) tumors

- **Value:** -66.0%
- **Population:** tumor-bearing mice (MDA-MB-231 xenograft)
- **Intervention:** voluntary running wheel exercise
- **Source:** *Exercise-Induced Catecholamines Activate the Hippo Tumor Suppressor Pathway to Reduce Risks of Breast Cancer Development* — Cancer Research (2017)
  · DOI: `10.1158/0008-5472.can-16-3125`
- **Validator:** researka-tier2

- **Why it matters:** This suggests that regular exercise, such as running, could be a complementary therapy to inhibit tumor growth in breast cancer models, offering hope for non-drug treatments.
- **Caution:** As a mouse xenograft study, it may not directly translate to human cancer due to species differences and controlled lab conditions.
- **Next question:** Further studies are needed to explore whether exercise has similar tumor-suppressive effects in human breast cancer patients through analogous mechanisms.

---

## #3 — score 75 · effect_size

**Finding:** Leucine alone stimulated ribosomal protein s6 kinase 1 (S6K1) phosphorylation ∼280% more than placebo and EAA-Leu after exercise.

- **Value:** 280.0%
- **Population:** Nine male subjects
- **Intervention:** leucine alone
- **Source:** *Leucine does not affect mechanistic target of rapamycin complex 1 assembly but is required for maximal ribosomal protein s6 kinase 1 activity in human skeletal muscle following resistance exercise* — The FASEB Journal (2015)
  · DOI: `10.1096/fj.15-273474`
- **Validator:** researka-tier2

- **Why it matters:** This indicates that leucine supplementation post-exercise can significantly boost muscle protein synthesis pathways, potentially enhancing recovery and muscle growth in active individuals.
- **Caution:** The small sample size of nine male subjects reduces statistical reliability and applicability to broader populations like females or older adults.
- **Next question:** Additional research should determine the optimal leucine dosage and timing for maximizing benefits across diverse groups, including those with muscle-wasting conditions.

---

## #4 — score 73 · effect_size

**Finding:** patients with PAD had a greater reduction in SmO2 (-54 ± 10 vs. -12 ± 4%, P = 0.001)

- **Value:** -54.0%
- **Population:** patients with peripheral artery disease and age-matched healthy controls
- **Intervention:** fatiguing plantar flexion exercise (from 0.5 to 7 kg for up to 14 min)
- **Source:** *Blood pressure and calf muscle oxygen extraction during plantar flexion exercise in peripheral artery disease* — Journal of Applied Physiology (2017)
  · DOI: `10.1152/japplphysiol.01110.2016`
- **Validator:** researka-tier2

- **Why it matters:** This reveals that PAD patients experience severe oxygen desaturation in muscles during exercise, which could guide tailored exercise programs to improve their mobility and reduce symptoms.
- **Caution:** The study may not account for variations in exercise protocols or patient severity, which could influence SmO2 reduction outcomes.
- **Next question:** Next steps involve testing interventions, such as graded exercise or pharmacological aids, to stabilize oxygen levels in PAD patients during physical activity.

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

- **Why it matters:** This shows that exercise combined with metformin can lower inflammatory markers in cancer survivors, suggesting a potential strategy to reduce recurrence risk and improve post-treatment well-being.
- **Caution:** The population is limited to survivors who completed standard therapy, and details like 'low b' are ambiguous, which may confound the findings.
- **Next question:** It is important to explore whether these anti-inflammatory effects hold during active cancer treatment or in other cancer types for broader clinical application.

---
