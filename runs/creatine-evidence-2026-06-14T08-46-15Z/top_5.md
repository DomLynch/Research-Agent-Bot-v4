# Top 5 interesting findings — creatine

**Snapshot:** 2026-06-14T08-46-15Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=creatine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 13
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=7, regimen_or_dose=1)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `adverse`


## #1 — score 77 · adverse

**Finding:** short and long-term supplementation (up to 30 g/day for 5 years) is safe and well-tolerated

- **Value:** 30.0g/day
- **Population:** healthy individuals and patient populations from infants to elderly
- **Intervention:** creatine supplementation
- **Alpha cues:** translation_context
- **Source:** *International Society of Sports Nutrition position stand: safety and efficacy of creatine supplementation in exercise, sport, and medicine* — Journal of the International Society of Sports Nutrition (2017)
  · DOI: `10.1186/s12970-017-0173-z`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties creatine supplementation in healthy individuals and patient populations from infants to elderly to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `threshold`


## #2 — score 73 · threshold

**Finding:** assuming a constant value for whole-body skeletal muscle creatine concentration of 4.3 g/kg wet weight.

- **Value:** 4.3g/kg
- **Population:** humans
- **Intervention:** deuterated-creatine dilution method
- **Alpha cues:** translation_context
- **Source:** *D<sub>3</sub>‐creatine dilution for skeletal muscle mass measurement: historical development and current status* — Journal of Cachexia Sarcopenia and Muscle (2022)
  · DOI: `10.1002/jcsm.13083`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 3.89g/kg (varies between muscles (e.g. 3.89-4.62 g/kg))

- **Why it matters:** This is worth checking because it ties deuterated-creatine dilution method in humans to a source-backed effect.
- **Caution:** Do not overread this as settled: k=2 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `rate`


## #3 — score 72 · rate

**Finding:** Not all tracer is distributed in skeletal muscle with non-muscle creatine sources ranging from 2% to 10%

- **Value:** 2.0%
- **Population:** humans
- **Intervention:** deuterated-creatine dilution method
- **Alpha cues:** translation_context
- **Source:** *D<sub>3</sub>‐creatine dilution for skeletal muscle mass measurement: historical development and current status* — Journal of Cachexia Sarcopenia and Muscle (2022)
  · DOI: `10.1002/jcsm.13083`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.0% (Not all tracer is retained with urinary isotope losses rangi)

- **Why it matters:** This is worth checking because it ties deuterated-creatine dilution method in humans to a source-backed effect.
- **Caution:** Do not overread this as settled: k=2 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `regimen`


## #4 — score 70 · regimen

**Finding:** Post-menopausal females may also experience benefits in skeletal muscle size and function when consuming high doses of creatine (0.3 g·kg⁻¹·d⁻¹)

- **Value:** 0.3g·kg⁻¹·d⁻¹
- **Population:** post-menopausal females
- **Intervention:** creatine supplementation
- **Alpha cues:** subgroup, functional_endpoint
- **Source:** *Creatine Supplementation in Women’s Health: A Lifespan Perspective* — Nutrients (2021)
  · DOI: `10.3390/nu13030877`
- **Validator:** —

- **Why it matters:** This is worth checking because it reaches a hard outcome rather than stopping at a proxy.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `effect_size`


## #5 — score 67 · effect_size

**Finding:** chest press strength (standardized mean difference [SMD] =0.35 [0.16–0.53]; p =0.0002)

- **Value:** 0.35SMD
- **Population:** older adults with mean age 57–70 years
- **Intervention:** creatine supplementation during resistance training
- **Alpha cues:** translation_context
- **Source:** *Effect of creatine supplementation during resistance training on lean tissue mass and muscular strength in older adults: a meta-analysis* — Open Access Journal of Sports Medicine (2017)
  · DOI: `10.2147/oajsm.s123529`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.24SMD (leg press strength (SMD =0.24 [0.05–0.43]; p =0.01)); 1.37kg (Creatine supplementation resulted in greater increases in le)

- **Why it matters:** This is worth checking because it ties creatine supplementation during resistance training in older adults with mean age 57–70 years to a source-backed effect.
- **Caution:** Do not overread this as settled: k=3 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
