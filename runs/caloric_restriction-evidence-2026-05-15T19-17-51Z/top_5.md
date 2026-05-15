# Top 5 interesting findings — caloric_restriction

**Snapshot:** 2026-05-15T19-17-51Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=caloric_restriction) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 29
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 75 · effect_size

**Finding:** inguinal fat was significantly increased by CR at 66 weeks and 106 weeks.

- **Value:** 66.0weeks
- **Population:** Ins1(+/-):Ins2(-/-) mice
- **Intervention:** 60% caloric restriction (CR)
- **Source:** *Caloric Restriction Paradoxically Increases Adiposity in Mice With Genetically Reduced Insulin* — Endocrinology (2016)
  · DOI: `10.1210/en.2016-1102`
- **Validator:** researka-tier2

- **Why it matters:** Increased inguinal fat under CR in insulin-deficient mice could signal regional fat redistribution that may offset metabolic benefits in humans.
- **Caution:** The insulin mutant mouse model limits direct translation to human physiology with normal insulin function.
- **Next question:** Does this inguinal fat increase persist long-term and affect insulin resistance or inflammation?

---

## #2 — score 73 · effect_size

**Finding:** Mice under 40% caloric restriction showed reversal in weight gain and recovered insulin sensitivity, fasting glucose, and insulin levels.

- **Value:** 40.0%
- **Population:** mice fed high-fat diet
- **Intervention:** 40% caloric restriction
- **Source:** *Caloric restriction recovers impaired β-cell-β-cell gap junction coupling, calcium oscillation coordination, and insulin secretion in prediabetic mice* — American Journal of Physiology-Endocrinology and Metabolism (2020)
  · DOI: `10.1152/ajpendo.00132.2020`
- **Validator:** researka-tier2

- **Why it matters:** A 70% CR regimen in rats establishes a severe restriction benchmark for studying extreme dietary impacts on healthspan.
- **Caution:** Fisher 344 rats are a specific inbred model, and such high CR levels are impractical and risky for human trials.
- **Next question:** How does this CR level influence biomarkers of aging like telomere length or oxidative stress?

---

## #3 — score 67 · effect_size

**Finding:** CR mice had 52% and 88% lower serum leptin at 6 and 12 weeks of age

- **Value:** 52.0%
- **Population:** male C57Bl/6J mice
- **Intervention:** 30% caloric restriction
- **Source:** *Caloric restriction leads to high marrow adiposity and low bone mass in growing mice* — Journal of Bone and Mineral Research (2010)
  · DOI: `10.1002/jbmr.82`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 33.0% (CR mice had 33% and 39% lower serum IGF-1 at 6 and 12 weeks ); 5.0 (bone marrow adiposity was elevated dramatically in CR versus); 1.0 (Bone-formation indices were lower, whereas bone-resorption i)

- **Why it matters:** 40% CR reversing metabolic dysfunction in obese mice suggests strong potential for dietary interventions to treat human metabolic syndrome.
- **Caution:** High-fat diet-induced obesity in mice may not replicate the multifactorial causes of human obesity, and 40% CR is a drastic reduction.
- **Next question:** Are the metabolic improvements from CR sustainable without continuous restriction, or do they require lifestyle changes?

---

### Lane — `regimen`


## #4 — score 75 · regimen

**Finding:** CR conditions (70%)

- **Value:** 70.0%
- **Population:** Fisher 344 rats
- **Intervention:** caloric restriction
- **Source:** *Caloric restriction promotes rapid expansion and long-lasting increase of <i>Lactobacillus</i> in the rat fecal microbiota* — Gut Microbes (2017)
  · DOI: `10.1080/19490976.2017.1371894`
- **Validator:** researka-tier2

- **Why it matters:** Short-term 40% CR with controlled HFD intake demonstrates rapid metabolic benefits, guiding time-limited human diet strategies.
- **Caution:** The one-month duration and specific HFD dose (2 g/day) in mice may not account for human variability in adherence and diet composition.
- **Next question:** What are the long-term effects on gut microbiota or energy expenditure after ceasing this brief CR period?

---

## #5 — score 73 · regimen

**Finding:** mice were submitted to 1 mo of 40% caloric restriction (2 g/day of HFD).

- **Value:** 40.0%
- **Population:** mice
- **Intervention:** caloric restriction
- **Source:** *Caloric restriction recovers impaired β-cell-β-cell gap junction coupling, calcium oscillation coordination, and insulin secretion in prediabetic mice* — American Journal of Physiology-Endocrinology and Metabolism (2020)
  · DOI: `10.1152/ajpendo.00132.2020`
- **Validator:** researka-tier2

- **Why it matters:** Significant serum leptin reduction under CR highlights hormonal adaptations that could influence hunger and weight regain in dieting humans.
- **Caution:** Studies on young male C57Bl/6J mice may not generalize to females, older adults, or other ethnicities with differing leptin responses.
- **Next question:** How do these leptin changes coordinate with other appetite hormones to affect long-term diet compliance and metabolic health?

---
