# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-16T14-05-51Z
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

- **Why it matters:** Diet and exercise significantly reduced the dietary inflammatory index in postmenopausal women, suggesting a practical approach to lower inflammation and associated chronic disease risks.
- **Caution:** The effect sizes are specific to overweight/obese, healthy postmenopausal women, which limits generalizability to other populations or health conditions.
- **Next question:** Do these inflammation reductions correlate with decreased long-term incidence of cardiovascular disease or cancer in this demographic?

---

## #2 — score 75 · effect_size

**Finding:** tumor-bearing mice with access to running wheels showed reduced growth of MDA-MB-231 (-66%, P < 0.01) tumors

- **Value:** -66.0%
- **Population:** tumor-bearing mice (MDA-MB-231 xenograft)
- **Intervention:** voluntary running wheel exercise
- **Source:** *Exercise-Induced Catecholamines Activate the Hippo Tumor Suppressor Pathway to Reduce Risks of Breast Cancer Development* — Cancer Research (2017)
  · DOI: `10.1158/0008-5472.can-16-3125`
- **Validator:** researka-tier2

- **Why it matters:** Exercise via running wheels markedly suppressed tumor growth in a mouse breast cancer model, pointing to exercise as a potential adjunctive therapy in oncology.
- **Caution:** The findings rely on an xenograft mouse model, which may not accurately reflect human tumor behavior or exercise responses.
- **Next question:** What specific molecular mechanisms drive exercise-induced tumor inhibition, and can they be replicated or enhanced in human patients?

---

## #3 — score 75 · effect_size

**Finding:** Leucine alone stimulated ribosomal protein s6 kinase 1 (S6K1) phosphorylation ∼280% more than placebo and EAA-Leu after exercise.

- **Value:** 280.0%
- **Population:** Nine male subjects
- **Intervention:** leucine alone
- **Source:** *Leucine does not affect mechanistic target of rapamycin complex 1 assembly but is required for maximal ribosomal protein s6 kinase 1 activity in human skeletal muscle following resistance exercise* — The FASEB Journal (2015)
  · DOI: `10.1096/fj.15-273474`
- **Validator:** researka-tier2

- **Why it matters:** Leucine alone post-exercise amplified S6K1 phosphorylation, a key driver of muscle protein synthesis, which could optimize muscle repair and growth strategies.
- **Caution:** The study involved only nine male subjects, so results may not extend to females, varied age groups, or long-term outcomes.
- **Next question:** How does this acute leucine-driven S6K1 stimulation translate into sustained improvements in muscle mass or athletic performance?

---

## #4 — score 73 · effect_size

**Finding:** patients with PAD had a greater reduction in SmO2 (-54 ± 10 vs. -12 ± 4%, P = 0.001)

- **Value:** -54.0%
- **Population:** patients with peripheral artery disease and age-matched healthy controls
- **Intervention:** fatiguing plantar flexion exercise (from 0.5 to 7 kg for up to 14 min)
- **Source:** *Blood pressure and calf muscle oxygen extraction during plantar flexion exercise in peripheral artery disease* — Journal of Applied Physiology (2017)
  · DOI: `10.1152/japplphysiol.01110.2016`
- **Validator:** researka-tier2

- **Why it matters:** The steep drop in muscle oxygen saturation during exercise in PAD patients underscores severe oxygen delivery issues, which could worsen symptoms like leg pain.
- **Caution:** The comparison lacks details on exercise type and intensity, and it contrasts PAD patients with healthy controls, limiting clinical applicability.
- **Next question:** Can tailored exercise regimens improve SmO2 responses in PAD patients and lead to measurable reductions in symptom severity?

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

- **Why it matters:** Exercise combined with metformin reduced inflammatory markers in cancer survivors, indicating a synergistic effect that may enhance post-treatment recovery and reduce complications.
- **Caution:** The study design does not separate the contributions of exercise and metformin, making it hard to assess individual efficacy.
- **Next question:** Does this inflammatory reduction from exercise and metformin correlate with improved cancer outcomes, such as lower recurrence rates or extended survival?

---
