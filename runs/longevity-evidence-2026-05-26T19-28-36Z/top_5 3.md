# Top 5 interesting findings — longevity

**Snapshot:** 2026-05-26T19-28-36Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=longevity) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 31
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1, model_context=3, regimen_or_dose=1)

---

## #1 — score 92 · effect_size

**Finding:** We observed genome-wide significant association with longevity, as reflected by survival to ages beyond 90 years, at a novel locus, rs2149954, on chromosome 5q33.3 (OR = 1.10, P = 1.74 × 10(-8)).

- **Value:** 1.1OR
- **Population:** 7729 long-lived individuals of European descent (≥85 years) and 16,121 younger controls (<65 years), replication in 13,060 long-lived individuals and 61,156 controls
- **Intervention:** rs2149954 minor allele (T) on chromosome 5q33.3
- **Alpha cues:** translation_context, functional_endpoint
- **Source:** *Genome-wide association meta-analysis of human longevity identifies a novel locus conferring survival beyond 90 years of age* — Human Molecular Genetics (2014)
  · DOI: `10.1093/hmg/ddu139`
- **Validator:** researka-tier2

- **Why it matters:** This genetic variant on chromosome 5q33.3 could guide research into biological mechanisms of aging and potential longevity interventions.
- **Caution:** The association is specific to individuals of European descent aged 85 and older, limiting generalizability to other populations.
- **Next question:** What is the functional role of rs2149954 in cellular pathways that influence survival to extreme ages?

---

## #2 — score 90 · effect_size

**Finding:** youthful brains and immune systems were uniquely associated with longevity (youthful both, HR = 0.44)

- **Value:** 0.44HR
- **Population:** UK Biobank participants
- **Intervention:** Youthful brain and immune system (plasma proteomics organ age)
- **Alpha cues:** functional_endpoint
- **Source:** *Plasma proteomics links brain and immune system aging with healthspan and longevity* — Nature Medicine (2025)
  · DOI: `10.1038/s41591-025-03798-1`
- **Validator:** researka-tier2

- **Why it matters:** Maintaining youthful brain and immune systems halves mortality risk, offering targets for preventive healthcare to extend lifespan.
- **Caution:** The UK Biobank participants may not represent global diversity, and unmeasured confounders like socioeconomic status could influence results.
- **Next question:** Can specific behaviors or treatments sustain youthful brain and immune functions to enhance longevity?

---

## #3 — score 80 · effect_size

**Finding:** The combination of the warmest winter and the high insecticide dose resulted in a 70% longevity decrease.

- **Value:** 70.0%
- **Population:** solitary bee Osmia cornuta
- **Intervention:** combination of warmest winter (distant-future temperature scenario) and high insecticide dose (11.64 ng a.i./bee sulfoxaflor)
- **Alpha cues:** baseline
- **Source:** *Bees exposed to climate change are more sensitive to pesticides* — Global Change Biology (2023)
  · DOI: `10.1111/gcb.16928`
- **Validator:** researka-tier2

- **Why it matters:** Combined climate and pesticide stressors drastically reduce bee lifespans, jeopardizing pollination and ecosystem stability.
- **Caution:** The study uses a solitary bee model under controlled doses, so findings may not apply to humans or natural environments with variable conditions.
- **Next question:** How do different environmental stressors synergistically affect longevity in diverse species, including humans?

---

## #4 — score 80 · effect_size

**Finding:** Older adults with lower Mediterranean diet adherence had a significantly higher prevalence of probable sarcopenia (25.9%)

- **Value:** 25.9%
- **Population:** community-dwelling older adults from the Longevity Check-Up 7+ project
- **Intervention:** low Mediterranean diet adherence (Medi-Lite score ≤8)
- **Alpha cues:** translation_context
- **Source:** *Low Adherence to Mediterranean Diet Is Associated with Probable Sarcopenia in Community-Dwelling Older Adults: Results from the Longevity Check-Up (Lookup) 7+ Project* — Nutrients (2023)
  · DOI: `10.3390/nu15041026`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 15.5% (those with good (19.1%) or high (15.5%) adherence)

- **Why it matters:** Low adherence to the Mediterranean diet is tied to higher sarcopenia risk, underscoring diet's impact on muscle health in aging.
- **Caution:** The observational design from the Longevity Check-Up 7+ project cannot confirm that diet causes reduced muscle mass.
- **Next question:** Does increased Mediterranean diet intake prevent sarcopenia, and what molecular pathways are involved?

---

## #5 — score 75 · effect_size

**Finding:** about 25 % of the variation in human longevity is due to genetic factors.

- **Value:** 25.0%
- **Population:** human families
- **Intervention:** genetic factors
- **Alpha cues:** translation_context
- **Source:** *Human longevity: Genetics or Lifestyle? It takes two to tango* — Immunity & Ageing (2016)
  · DOI: `10.1186/s12979-016-0066-z`
- **Validator:** researka-tier2

- **Why it matters:** Genetics explain only 25% of longevity differences, highlighting the greater influence of lifestyle and environmental factors.
- **Caution:** The estimate is derived from family studies, which might not account for shared environments or genetic heterogeneity across populations.
- **Next question:** Which specific non-genetic factors, such as diet or exercise, most significantly contribute to longevity, and how can they be optimized?

---
