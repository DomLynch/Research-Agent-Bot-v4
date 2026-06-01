# Top 5 interesting findings — acarbose

**Snapshot:** 2026-05-27T09-58-52Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=acarbose) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 33
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=4, model_context=3, molecular_mechanism=1)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 97 · effect_size

**Finding:** Acarbose increased male median lifespan by 22% (P < 0.0001)

- **Value:** 22.0%
- **Population:** genetically heterogeneous mice
- **Intervention:** acarbose
- **Alpha cues:** subgroup, functional_endpoint
- **Source:** *Acarbose, 17-α-estradiol, and nordihydroguaiaretic acid extend mouse lifespan preferentially in males.* — Aging cell (2014)
  · DOI: `10.1111/acel.12170`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 5.0% (increased female median lifespan by only 5% (P = 0.01))

- **Why it matters:** Acarbose's 22% lifespan increase in male mice suggests potential as an anti-aging intervention, motivating human trials for longevity benefits.
- **Caution:** The study used genetically heterogeneous mice, which may not fully replicate human genetic diversity, and the dose was not specified for human equivalence.
- **Next question:** Is the lifespan extension effect consistent across sexes and doses, and what are the underlying biological mechanisms?

---

## #2 — score 96 · effect_size

**Finding:** significantly increased (3%) in females only at 1,000 ppm

- **Value:** 3.0%
- **Population:** female mice
- **Intervention:** acarbose at 1000 ppm
- **Alpha cues:** subgroup, functional_endpoint
- **Source:** *Acarbose improves health and lifespan in aging HET3 mice* — Aging Cell (2019)
  · DOI: `10.1111/acel.12898`
- **Validator:** researka-tier2

- **Why it matters:** The 3% lifespan increase in female mice only at 1,000 ppm indicates sex-specific dosing requirements for acarbose's anti-aging effects.
- **Caution:** The effect is modest and observed only at a high dose in female mice, so lower doses or different models might not show this benefit.
- **Next question:** What factors cause the sex-dependent response to acarbose, and how should doses be adjusted for gender in clinical applications?

---

## #3 — score 68 · effect_size

**Finding:** acarbose produced 54% decrease in normal rats loaded with maltose

- **Value:** 54.0%
- **Population:** normal rats loaded with maltose
- **Intervention:** acarbose
- **Alpha cues:** baseline
- **Source:** *Effect of quercetin on postprandial glucose excursion after mono- and disaccharides challenge in normal and diabetic rats* — Journal of Diabetes Mellitus (2012)
  · DOI: `10.4236/jdm.2012.21013`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 51.0% (acarbose produced 51% decrease in maltose loaded diabetic ra)

- **Why it matters:** This is worth checking because it ties acarbose in normal rats loaded with maltose to a source-backed effect.
- **Caution:** Do not overread this as settled: k=2 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

## #4 — score 60 · effect_size

**Finding:** The hazard ratio for ever users versus never users was 0.841 (95% confidence interval, 0.704-1.005)

- **Value:** 0.841HR
- **Population:** new-onset type 2 diabetes patients
- **Intervention:** acarbose
- **Alpha cues:** baseline
- **Source:** *Dementia Risk in Type 2 Diabetes Patients: Acarbose Use and Its Joint Effects with Metformin and Pioglitazone* — Aging and Disease (2020)
  · DOI: `10.14336/ad.2019.0621`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties acarbose in new-onset type 2 diabetes patients to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `rate`


## #5 — score 64 · rate

**Finding:** The most common medications used to treat diabetes and hypertension were metformin and acarbose, respectively, at 28.5 and 20.9% as first-line medication.

- **Value:** 28.5%
- **Population:** patients with type 2 diabetes in China
- **Intervention:** metformin as first-line medication
- **Alpha cues:** baseline
- **Source:** *Analysis of treatment pathways for three chronic diseases using OMOP CDM* — Journal of Medical Systems (2018)
  · DOI: `10.1007/s10916-018-1076-5`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 20.9% (The most common medications used to treat diabetes and hyper)

- **Why it matters:** This is worth checking because it ties metformin as first-line medication in patients with type 2 diabetes in China to a source-backed effect.
- **Caution:** Do not overread this as settled: k=2 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
