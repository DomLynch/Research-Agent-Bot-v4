# Top 2 interesting findings — longevity

**Snapshot:** 2026-05-17T05-46-45Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=longevity) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 31
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1, model_context=1)

---

## #1 — score 90 · effect_size

**Finding:** offspring enjoy a 30% reduced standardized mortality rate

- **Value:** 30.0%
- **Population:** offspring in long-lived families from Leiden Longevity Study
- **Intervention:** genetic enrichment for longevity
- **Alpha cues:** functional_endpoint
- **Source:** *Hallmark Features of Immunosenescence Are Absent in Familial Longevity* — The Journal of Immunology (2010)
  · DOI: `10.4049/jimmunol.1001629`
- **Validator:** researka-tier2

- **Why it matters:** This suggests heritable factors in longevity, potentially guiding targeted interventions for age-related diseases.
- **Caution:** The study is based on the Leiden cohort's standardized mortality rates, which may not account for all genetic or environmental confounders.
- **Next question:** What specific genetic variants or epigenetic changes drive the 30% mortality reduction in these offspring?

---

## #2 — score 60 · effect_size

**Finding:** above 16.5%, relative longevity showed a positive relation with harvest moisture content

- **Value:** 16.5%
- **Population:** rice seeds from 20 accessions of five variety groups
- **Intervention:** drying at 45°C
- **Alpha cues:** baseline
- **Source:** *Improvement in rice seed storage longevity from high-temperature drying is a consistent positive function of harvest moisture content above a critical value* — Seed Science Research (2018)
  · DOI: `10.1017/s0960258518000211`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 16.5% (below 16.5%, relative longevity did not differ with harvest )

- **Why it matters:** Above 16.5% harvest moisture, enhanced seed longevity allows for extended storage, reducing agricultural waste and improving crop resilience.
- **Caution:** The finding relies on a limited sample of 20 rice accessions and a fixed moisture threshold, which may not generalize to other varieties or climates.
- **Next question:** How do factors like temperature or genetic diversity interact with moisture content to affect rice seed longevity over time?

---
