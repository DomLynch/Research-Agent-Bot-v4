# Top 5 interesting findings — resveratrol

**Snapshot:** 2026-05-17T06-59-01Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=resveratrol) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 38
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=2, model_context=3)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 92 · effect_size

**Finding:** Liver fat content decreased in placebo group (-0.7%) but not in resveratrol group (-0.03%), P=.018 for ITT population.

- **Value:** -0.7%
- **Population:** overweight and insulin-resistant subjects
- **Intervention:** resveratrol supplementation
- **Alpha cues:** contrast, translation_context
- **Source:** *Effects of resveratrol supplementation on liver fat content in overweight and insulin‐resistant subjects: A randomized, double‐blind, placebo‐controlled clinical trial* — Diabetes Obesity and Metabolism (2018)
  · DOI: `10.1111/dom.13268`
- **Validator:** researka-tier2

- **Why it matters:** Resveratrol did not reduce liver fat in overweight, insulin-resistant subjects, questioning its efficacy for fatty liver disease.
- **Caution:** The study's fixed dose and intention-to-treat analysis may not capture optimal effects or individual variability.
- **Next question:** Would varying resveratrol doses or longer treatment periods yield different outcomes for liver fat reduction?

---

## #2 — score 76 · effect_size

**Finding:** fetal pancreatic mass was enlarged by 42%,

- **Value:** 42.0%
- **Population:** pregnant nonhuman primates
- **Intervention:** resveratrol supplementation (WSD supplemented with 0.37% resveratrol)
- **Alpha cues:** translation_context
- **Source:** *Beneficial and cautionary outcomes of resveratrol supplementation in pregnant nonhuman primates* — The FASEB Journal (2014)
  · DOI: `10.1096/fj.13-245472`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 30.0% (resveratrol resulted in 30% maternal weight loss)

- **Why it matters:** Enlarged fetal pancreatic mass in primates suggests potential developmental risks of resveratrol during pregnancy.
- **Caution:** Nonhuman primate models may not directly translate to human fetal effects due to physiological differences.
- **Next question:** Does fetal pancreatic enlargement in primates lead to functional changes in insulin production or metabolic health postnatally?

---

## #3 — score 62 · effect_size

**Finding:** a 7.24% reduction in C-terminal telopeptide type-1 collagen levels, a bone resorption marker

- **Value:** 7.24%
- **Population:** postmenopausal women
- **Intervention:** resveratrol 75 mg twice daily
- **Alpha cues:** baseline
- **Source:** *Regular Supplementation With Resveratrol Improves Bone Mineral Density in Postmenopausal Women: A Randomized, Placebo-Controlled Trial* — Journal of Bone and Mineral Research (2020)
  · DOI: `10.1002/jbmr.4115`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.07 (an improvement in T-score (+0.070 ± 0.018))

- **Why it matters:** Lowering bone resorption markers could help mitigate osteoporosis risk in postmenopausal women.
- **Caution:** Short-term biomarker changes may not reflect long-term bone density improvements or fracture prevention.
- **Next question:** Is the reduction in C-terminal telopeptide type-1 collagen linked to sustained increases in bone mineral density?

---

## #4 — score 58 · effect_size

**Finding:** Significantly higher (90%) bioconversion of resveratrol was achieved with α-d-glucose as the sugar donor

- **Value:** 90.0%
- **Population:** in vitro enzymatic reaction
- **Intervention:** α-d-glucose as sugar donor
- **Alpha cues:** low_signal_context
- **Source:** *Enzymatic Biosynthesis of Novel Resveratrol Glucoside and Glycoside Derivatives* — Applied and Environmental Microbiology (2014)
  · DOI: `10.1128/aem.02076-14`
- **Validator:** researka-tier2

- **Why it matters:** Higher bioconversion with α-d-glucose could enhance resveratrol's effectiveness in biological applications.
- **Caution:** In vitro enzymatic conditions may not replicate the complexity of human metabolism or bioavailability.
- **Next question:** Can this bioconversion efficiency be achieved in vivo through dietary intake or supplement formulation?

---

### Lane — `rate`


## #5 — score 56 · rate

**Finding:** Tumor incidence is reduced from 80% in mice treated with azoxymethane (AOM) + DSS to 20% in mice treated with AOM + DSS + resveratrol (300 ppm).

- **Value:** 20.0%
- **Population:** AOM + DSS mouse model of colitis
- **Intervention:** resveratrol (300 ppm)
- **Alpha cues:** baseline
- **Source:** *Resveratrol Suppresses Colitis and Colon Cancer Associated with Colitis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-09-0117`
- **Validator:** researka-tier2

- **Why it matters:** Resveratrol sharply reduced tumor incidence in a colitis-associated cancer model, indicating chemopreventive potential.
- **Caution:** The AOM + DSS mouse model represents a specific colitis type that may not encompass all human colorectal cancer mechanisms.
- **Next question:** What specific pathways does resveratrol target in this model, and are they conserved in human colorectal cancer?

---
