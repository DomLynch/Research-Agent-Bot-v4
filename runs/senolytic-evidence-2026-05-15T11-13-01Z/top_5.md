# Top 2 interesting findings — senolytic

**Snapshot:** 2026-05-15T11-13-01Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=senolytic) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 13
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 80 · effect_size

**Finding:** reduced SMC by 90%

- **Value:** 90.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 60.0% (reduced α-SMA+ fibrous cap thickness by 60%); 60.0% (increased EC contributions to lesions via EC-to-mesenchymal )

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `adverse`


## #2 — score 76 · adverse

**Finding:** was associated with a > 50% mortality rate

- **Value:** 50.0%
- **Population:** advanced atherosclerotic Apoe-/- mice fed western diet
- **Intervention:** ABT-263 at 100 mg/kg or 50 mg/kg
- **Source:** *Treatment of advanced atherosclerotic mice with ABT-263 reduced indices of plaque stability and increased mortality* — JCI Insight (2024)
  · DOI: `10.1172/jci.insight.173863`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `adverse` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
