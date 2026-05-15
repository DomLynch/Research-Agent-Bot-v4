# Top 3 interesting findings — berberine

**Snapshot:** 2026-05-15T08-51-53Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=berberine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 6
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 75 · effect_size

**Finding:** the glucose consumption of HepG2 cells were promoted and reached 96.1%

- **Value:** 96.1%
- **Population:** HepG2 cells
- **Intervention:** berberine
- **Source:** *Antihyperglycemia and Antihyperlipidemia Effect of Protoberberine Alkaloids From Rhizoma Coptidis in HepG2 Cell and Diabetic KK‐Ay Mice* — Drug Development Research (2016)
  · DOI: `10.1002/ddr.21302`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 17.6% (reached 17.6% for coptisine)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 75 · effect_size

**Finding:** There was also a significant decrease from 425.7 ± 139.7 micromoles per liter to 344.9± 126.1 micromoles per liter in fructoseamine

- **Value:** 80.8micromoles per liter
- **Population:** patients with type 2 diabetes
- **Intervention:** Berberine capsules 500 mg twice daily
- **Source:** *The Effects of Active Ingredients of Barberry Root (Berberine) on Glycemic Control and Insulin Resistance in Type 2 Diabetic Patients* — Jundishapur Journal of Natural Pharmaceutical Products (2018)
  · DOI: `10.5812/jjnpp.64180`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 43.6mg/dl (There was a significant decrease from 266.1 ± 93.7 mg dl to ); 24.3mg/dl (average blood sugar (FBS) in the Berberine group decreased f)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `subgroup`


## #3 — score 53 · subgroup

**Finding:** low dose berberine (10 mg/kg per day) showed higher left ventricular ejection fraction and fractional shortening than high-dose berberine (50 mg/kg per day)

- **Value:** 10.0mg/kg
- **Population:** MI rats
- **Intervention:** low dose berberine (10 mg/kg per day)
- **Source:** *Berberine attenuates adverse left ventricular remodeling and cardiac dysfunction after acute myocardial infarction in rats: Role of autophagy* — Clinical and Experimental Pharmacology and Physiology (2014)
  · DOI: `10.1111/1440-1681.12309`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `subgroup` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
