# Top 5 interesting findings — caloric_restriction

**Snapshot:** 2026-05-15T18-54-38Z
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

- **Why it matters:** Increased inguinal fat under caloric restriction in insulin-deficient mice may signal unintended fat redistribution, complicating CR-based diabetes therapies.
- **Caution:** The study uses a specific genetic model with a single CR dose, limiting applicability to other mouse strains or human contexts.
- **Next question:** Does inguinal fat expansion improve or worsen metabolic function in these mice under CR?

---

## #2 — score 73 · effect_size

**Finding:** Mice under 40% caloric restriction showed reversal in weight gain and recovered insulin sensitivity, fasting glucose, and insulin levels.

- **Value:** 40.0%
- **Population:** mice fed high-fat diet
- **Intervention:** 40% caloric restriction
- **Source:** *Caloric restriction recovers impaired β-cell-β-cell gap junction coupling, calcium oscillation coordination, and insulin secretion in prediabetic mice* — American Journal of Physiology-Endocrinology and Metabolism (2020)
  · DOI: `10.1152/ajpendo.00132.2020`
- **Validator:** researka-tier2

- **Why it matters:** A 70% CR regimen in rats provides a benchmark for standardized research on caloric restriction's effects on aging and disease.
- **Caution:** Findings are based on Fisher 344 rats, which may not translate directly to humans due to species-specific metabolic differences.
- **Next question:** How does this 70% CR regimen compare to lower or higher restrictions in terms of healthspan and lifespan?

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

- **Why it matters:** 40% CR can reverse high-fat diet-induced obesity and metabolic issues, suggesting CR as a viable treatment for metabolic syndrome.
- **Caution:** The model involves mice on a high-fat diet, so results may not apply to CR in lean or normally fed individuals.
- **Next question:** Are the metabolic benefits of CR sustained after the restriction period, or do they revert upon resuming normal diet?

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

- **Why it matters:** A one-month 40% CR protocol demonstrates feasibility for short-term studies, aiding mechanistic research on CR's acute effects.
- **Caution:** The short duration and fixed dose (2 g/day HFD) may not reflect long-term outcomes or dose-response dynamics.
- **Next question:** How do extended CR durations beyond one month influence metabolic adaptations and health markers?

---

## #5 — score 73 · regimen

**Finding:** mice were submitted to 1 mo of 40% caloric restriction (2 g/day of HFD).

- **Value:** 40.0%
- **Population:** mice
- **Intervention:** caloric restriction
- **Source:** *Caloric restriction recovers impaired β-cell-β-cell gap junction coupling, calcium oscillation coordination, and insulin secretion in prediabetic mice* — American Journal of Physiology-Endocrinology and Metabolism (2020)
  · DOI: `10.1152/ajpendo.00132.2020`
- **Validator:** researka-tier2

- **Why it matters:** Dramatic reductions in serum leptin under CR indicate altered appetite and energy regulation, with implications for weight loss interventions.
- **Caution:** The study is limited to male C57Bl/6J mice, overlooking sex differences and genetic diversity.
- **Next question:** Do these leptin decreases correlate with measurable changes in hunger, energy expenditure, or fat storage?

---
