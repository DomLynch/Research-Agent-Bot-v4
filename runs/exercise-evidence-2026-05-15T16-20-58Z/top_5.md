# Top 5 interesting findings — exercise

**Snapshot:** 2026-05-15T16-20-58Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=exercise) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 49
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

- **Why it matters:** Diet and diet+exercise significantly reduce the dietary inflammatory index in postmenopausal women, potentially lowering their risk of chronic inflammatory diseases.
- **Caution:** The study's focus on overweight/obese postmenopausal women limits generalizability, and specific exercise doses or durations are not detailed.
- **Next question:** Do these reductions in inflammatory index translate to long-term decreases in disease incidence such as cardiovascular events or diabetes?

---

## #2 — score 75 · effect_size

**Finding:** Physical exercise increased ULK1 phosphorylation at Ser(555) and decreased lipidation of light chain 3B.

- **Value:** 555.0
- **Population:** healthy humans
- **Intervention:** 1-h cycling exercise at 50% maximal O2 uptake
- **Source:** *Physical exercise increases autophagic signaling through ULK1 in human skeletal muscle* — Journal of Applied Physiology (2015)
  · DOI: `10.1152/japplphysiol.01116.2014`
- **Validator:** researka-tier2

- **Why it matters:** Exercise triggers autophagy pathway changes in healthy humans, providing a molecular basis for its benefits in cellular maintenance and disease prevention.
- **Caution:** The study lacks specifics on exercise type, intensity, or duration, making it difficult to apply findings to practical fitness recommendations.
- **Next question:** What variations in exercise modality or intensity most effectively enhance ULK1 phosphorylation and autophagy markers for health benefits?

---

## #3 — score 75 · effect_size

**Finding:** protein synthesis was found to be activated in the 72H and 24H groups, but not in the 8H group.

- **Value:** 72.0
- **Population:** male C57BL/6J mice
- **Intervention:** repeated bouts of resistance exercise with 8h recovery periods
- **Source:** *Repeated bouts of resistance exercise with short recovery periods activates <scp>mTOR</scp> signaling, but not protein synthesis, in mouse skeletal muscle* — Physiological Reports (2017)
  · DOI: `10.14814/phy2.13515`
- **Validator:** researka-tier2

- **Why it matters:** Protein synthesis activation at 24-72 hours post-exercise in mice suggests a critical window for muscle recovery and growth, informing training timing.
- **Caution:** Results are from an animal model (male C57BL/6J mice) with unspecified exercise protocols, so human applicability remains uncertain.
- **Next question:** How does the timing of protein synthesis peaks in mice align with human skeletal muscle responses to resistance or endurance training?

---

## #4 — score 75 · effect_size

**Finding:** tumor-bearing mice with access to running wheels showed reduced growth of MDA-MB-231 (-66%, P < 0.01) tumors

- **Value:** -66.0%
- **Population:** tumor-bearing mice (MDA-MB-231 xenograft)
- **Intervention:** voluntary running wheel exercise
- **Source:** *Exercise-Induced Catecholamines Activate the Hippo Tumor Suppressor Pathway to Reduce Risks of Breast Cancer Development* — Cancer Research (2017)
  · DOI: `10.1158/0008-5472.can-16-3125`
- **Validator:** researka-tier2

- **Why it matters:** Voluntary running wheel access reduces breast tumor growth in mice by 66%, highlighting exercise as a potential adjunct therapy in cancer management.
- **Caution:** The study uses a specific xenograft model (MDA-MB-231 cells) in mice with voluntary exercise, which may not replicate human tumor environments or controlled exercise doses.
- **Next question:** What mechanisms, such as immune modulation or metabolic changes, drive exercise-induced tumor suppression, and can they be leveraged in human clinical trials?

---

## #5 — score 75 · effect_size

**Finding:** Rise in systolic BP at peak exercise greater in hypertension than controls (Δ71±3, 81±7, 79±8.5 vs 47±5 mm Hg; P=0.0001).

- **Value:** 71.0mm Hg
- **Population:** hypertension patients (treated-controlled, treated-uncontrolled, untreated) and normotensive controls
- **Intervention:** antihypertensive treatment
- **Source:** *Antihypertensive Treatment Fails to Control Blood Pressure During Exercise* — Hypertension (2018)
  · DOI: `10.1161/hypertensionaha.118.11076`
- **Validator:** researka-tier2

- **Why it matters:** Hypertensive patients show a greater systolic blood pressure rise during peak exercise, emphasizing the need for personalized exercise prescriptions to manage cardiovascular risk.
- **Caution:** Data are grouped from hypertension patients with varying treatments and peak exercise tests, lacking details on exercise type or baseline controls.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
