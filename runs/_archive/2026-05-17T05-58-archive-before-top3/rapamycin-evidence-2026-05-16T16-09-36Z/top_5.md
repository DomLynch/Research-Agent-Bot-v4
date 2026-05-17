# Top 3 interesting findings — rapamycin

**Snapshot:** 2026-05-16T16-09-36Z
**Source:** Researka DB Tier-1 canonical (`GET /api/v1/topics/rapamycin/facts`) — hand-curated, validated.
**Facts inspected:** 6
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1, regimen_or_dose=2)

---

## #1 — score 76 · lifespan

**Finding:** 3 months of rapamycin extended remaining lifespan by ~60% in middle-aged mice

- **Value:** 60.0%
- **Population:** middle-aged C57BL/6 mice (20 months at start)
- **Intervention:** transient rapamycin (8 mg/kg/day i.p.) for 3 months
- **Source:** *Transient rapamycin treatment can increase lifespan and healthspan in middle-aged mice* — eLife (2016)
  · DOI: `10.7554/eLife.16351`
- **Validator:** source-cross-check-claude-2026-05-14
- **Same-trial supporting numerics:** 52.0% (3 months of rapamycin extended median lifespan by 52% in mal)

- **Why it matters:** This indicates that even brief rapamycin treatment in middle age can dramatically extend lifespan, hinting at feasible anti-aging interventions for humans later in life.
- **Caution:** The study relied on a single inbred mouse strain (C57BL/6), limiting generalizability, and the dose and 3-month regimen may not be directly applicable to human biology.
- **Next question:** Does the lifespan benefit from short-term rapamycin persist post-treatment, and what cellular pathways are driving this extension?

---

## #2 — score 70 · lifespan

**Finding:** rapamycin at 42 ppm extended female median lifespan by 26%

- **Value:** 26.0%
- **Population:** female heterogeneous-stock mice (UM-HET3); ITP
- **Intervention:** encapsulated rapamycin in feed at 42 ppm (3x standard ITP dose)
- **Source:** *Rapamycin-mediated lifespan increase in mice is dose and sex dependent and metabolically distinct from dietary restriction* — Aging Cell (2014)
  · DOI: `10.1111/acel.12194`
- **Validator:** source-cross-check-claude-2026-05-14
- **Same-trial supporting numerics:** 23.0% (rapamycin at 42 ppm extended male median lifespan by 23%)

- **Why it matters:** Rapamycin's efficacy in genetically diverse mice supports its potential as a broad anti-aging therapy, particularly for females, highlighting sex-specific responses.
- **Caution:** The high dose (42 ppm) may cause unexamined side effects, and the study's focus on median lifespan in females alone restricts insights into male or other demographics.
- **Next question:** What explains the sex-specific lifespan extension, and how can dosing be optimized to enhance benefits while mitigating risks?

---

## #3 — score 66 · lifespan

**Finding:** rapamycin reduced 90th-percentile mortality by 14% in females (Harrison 2009 NIA-ITP, 14 ppm)

- **Value:** 14.0%
- **Population:** female heterogeneous-stock mice (UM-HET3); 4-site NIA Interventions Testing Program cohort
- **Intervention:** encapsulated rapamycin in feed (~14 ppm); started at 600 days of age
- **Source:** *Rapamycin fed late in life extends lifespan in genetically heterogeneous mice* — Nature (2009)
  · DOI: `10.1038/nature08221`
- **Validator:** source-cross-check-user-2026-05-14

- **Why it matters:** Reducing late-life mortality by 14% suggests rapamycin could compress frailty periods and improve healthspan in aging populations, offering practical quality-of-life gains.
- **Caution:** The effect was measured only on 90th-percentile mortality in controlled lab conditions, which may not capture real-world aging complexity or individual variability.
- **Next question:** How does rapamycin influence other aging indicators, such as cognitive function or disease incidence, beyond mortality reduction?

---
