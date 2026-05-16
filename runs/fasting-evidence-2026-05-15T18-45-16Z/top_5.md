# Top 5 interesting findings — fasting

**Snapshot:** 2026-05-15T18-45-16Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=fasting) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 34
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 80 · effect_size

**Finding:** The glycoNOE signal was reduced by 88 ± 16% (n = 5) after 24 h of fasting

- **Value:** 88.0%
- **Population:** mice
- **Intervention:** 24 h fasting
- **Source:** *Magnetic resonance imaging of glycogen using its magnetic coupling with water* — Proceedings of the National Academy of Sciences (2020)
  · DOI: `10.1073/pnas.1909921117`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 75 · effect_size

**Finding:** ΔGH: lean, 647 ± 280 vs. obese, 544 ± 220%; P = 0.76

- **Value:** 544.0%
- **Population:** obese and lean men
- **Intervention:** 72 h of fasting
- **Source:** *Growth hormone signaling and action in obese versus lean human subjects* — American Journal of Physiology-Endocrinology and Metabolism (2018)
  · DOI: `10.1152/ajpendo.00431.2018`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 70 · effect_size

**Finding:** Patients in the fasting group had significantly higher global health status scores (81.5 ± 16.7 versus 68.3 ± 20.1, P = 0.030)

- **Value:** 81.5
- **Population:** patients with a cancer-related fecal stoma
- **Intervention:** fasting group
- **Source:** *Ramadan fasting in patients with a stoma: a prospective study of quality of life and nutritional status.* — PubMed (2013)

- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 27.6 (Patients in the fasting group had significantly higher preal); 4.6 (Patients in the fasting group had significantly higher album)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `rate`


## #4 — score 70 · rate

**Finding:** Most patients in the fasting group (13, 92.9%) stated they would feel sad if they were not fasting.

- **Value:** 92.9%
- **Population:** patients in the fasting group
- **Intervention:** Ramadan fasting
- **Source:** *Ramadan fasting in patients with a stoma: a prospective study of quality of life and nutritional status.* — PubMed (2013)

- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `rate` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `adverse`


## #5 — score 67 · adverse

**Finding:** The proportion of patients who experienced hypoglycemia during Ramadan was higher in Group A than Group B (36% vs 11%, P<0.001)

- **Value:** 36.0%
- **Population:** high-risk diabetes patients who fasted against medical advice during Ramadan
- **Intervention:** fasting against medical advice (Group A)
- **Source:** *“Ramadan challenges: Fasting against medical advice* — SHILAP Revista de lepidopterología (2017)
  · DOI: `10.22038/jfh.2018.27312.1100`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `adverse` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
