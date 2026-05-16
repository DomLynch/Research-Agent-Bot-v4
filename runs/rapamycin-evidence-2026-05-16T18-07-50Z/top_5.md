# Top 3 interesting findings — rapamycin

**Snapshot:** 2026-05-16T18-07-50Z
**Source:** Researka DB Tier-1 canonical (`GET /api/v1/topics/rapamycin/facts`) — hand-curated, validated.
**Facts inspected:** 6
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1, regimen_or_dose=2)

---

## #1 — score 100 · lifespan

**Finding:** 3 months of rapamycin extended remaining lifespan by ~60% in middle-aged mice

- **Value:** 60.0%
- **Population:** middle-aged C57BL/6 mice (20 months at start)
- **Intervention:** transient rapamycin (8 mg/kg/day i.p.) for 3 months
- **Alpha cues:** subgroup, translation_context, functional_endpoint, timing_or_reversal
- **Source:** *Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice* — eLife (2016)
  · DOI: `10.7554/eLife.16351`
- **Validator:** source-cross-check-claude-2026-05-14
- **Same-trial supporting numerics:** 52.0% (3 months of rapamycin extended median lifespan by 52% in mal)

- **Why it matters:** Direct evidence in the `lifespan` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

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

- **Why it matters:** Direct evidence in the `lifespan` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

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

- **Why it matters:** Direct evidence in the `lifespan` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
