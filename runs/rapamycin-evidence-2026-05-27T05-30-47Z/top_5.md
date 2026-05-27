# Top 3 interesting findings — rapamycin

**Snapshot:** 2026-05-27T05-30-47Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=rapamycin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 6
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1, regimen_or_dose=2)

---

## #1 — score 100 · lifespan

**Finding:** 3 months of rapamycin extended remaining lifespan by ~60% in middle-aged mice

- **Value:** 60.0%
- **Population:** middle-aged C57BL/6 mice (20 months at start)
- **Intervention:** transient rapamycin (8 mg/kg/day i.p.) for 3 months
- **Alpha cues:** translation_context, functional_endpoint, timing_or_reversal
- **Source:** *Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice* — eLife (2016)
  · DOI: `10.7554/eLife.16351`
- **Validator:** source-cross-check-claude-2026-05-14

- **Why it matters:** A 3-month rapamycin regimen in middle-aged mice extended remaining lifespan by ~60%, suggesting short-term anti-aging interventions could be viable in humans to prolong healthy life.
- **Caution:** The study used only C57BL/6 mice, a single inbred strain, which may not reflect genetic diversity in humans or other populations, limiting generalizability.
- **Next question:** Does a brief rapamycin treatment produce similar lifespan extensions in genetically diverse mouse models or during earlier/later life stages?

---

## #2 — score 100 · lifespan

**Finding:** rapamycin reduced 90th-percentile mortality by 14% in females (Harrison 2009 NIA-ITP, 14 ppm)

- **Value:** 14.0%
- **Population:** female heterogeneous-stock mice (UM-HET3); 4-site NIA Interventions Testing Program cohort
- **Intervention:** encapsulated rapamycin in feed (~14 ppm); started at 600 days of age
- **Alpha cues:** subgroup, translation_context, functional_endpoint
- **Source:** *Rapamycin fed late in life extends lifespan in genetically heterogeneous mice* — Nature (2009)
  · DOI: `10.1038/nature08221`
- **Validator:** source-cross-check-user-2026-05-14

- **Why it matters:** Rapamycin reduced 90th-percentile mortality by 14% in female mice, indicating it could delay age-related diseases and extend healthspan in women, who often experience longer but less healthy lives.
- **Caution:** The effect was observed only in female UM-HET3 mice at 14 ppm, with no data on males or other doses, so sex-specific responses and dose effects are unresolved.
- **Next question:** Is the mortality reduction in females linked to sex-specific mTOR inhibition pathways, and how does this translate to human clinical trials?

---

## #3 — score 100 · lifespan

**Finding:** rapamycin at 42 ppm extended female median lifespan by 26%

- **Value:** 26.0%
- **Population:** female heterogeneous-stock mice (UM-HET3); ITP
- **Intervention:** encapsulated rapamycin in feed at 42 ppm (3x standard ITP dose)
- **Alpha cues:** subgroup, functional_endpoint
- **Source:** *Rapamycin-mediated lifespan increase in mice is dose and sex dependent and metabolically distinct from dietary restriction* — Aging Cell (2014)
  · DOI: `10.1111/acel.12194`
- **Validator:** source-cross-check-claude-2026-05-14
- **Same-trial supporting numerics:** 23.0% (rapamycin at 42 ppm extended male median lifespan by 23%)

- **Why it matters:** Rapamycin at 42 ppm extended median lifespan by 26% in female mice, highlighting its dose-dependent efficacy that could inform optimal dosing for anti-aging therapies in humans.
- **Caution:** This finding comes from a single dose tested only in female mice within the ITP, so sex differences, long-term safety, and effects in diverse genetic backgrounds remain unknown.
- **Next question:** What is the minimum effective dose and duration of rapamycin for lifespan extension across both sexes, and what are the potential side effects in translational models?

---
