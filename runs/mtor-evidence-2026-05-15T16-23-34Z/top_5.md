# Top 5 interesting findings — mtor

**Snapshot:** 2026-05-15T16-23-34Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=mtor) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 28
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `rate`


## #1 — score 80 · rate

**Finding:** Bladder cancer shows high levels of mTOR activity in approximately 70% of urothelial carcinomas

- **Value:** 70.0%
- **Population:** urothelial carcinomas
- **Intervention:** —
- **Source:** *Emerging Roles for Mammalian Target of Rapamycin (mTOR) Complexes in Bladder Cancer Progression and Therapy* — Cancers (2022)
  · DOI: `10.3390/cancers14061555`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `rate` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `effect_size`


## #2 — score 75 · effect_size

**Finding:** RPPA analysis of an independent cohort of 154 tumors confirmed the relationship between pathway activation and hepatic metastasis.

- **Value:** 154.0
- **Population:** Breast cancer metastatic lesions
- **Intervention:** —
- **Source:** *Enrichment of PI3K-AKT–mTOR Pathway Activation in Hepatic Metastases from Breast Cancer* — Clinical Cancer Research (2017)
  · DOI: `10.1158/1078-0432.ccr-16-2656`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.01 (PIK3CA mutation was detected more frequently among liver met); 0.056 (Activation of AKT (S473) was detected more frequently among ); 0.053 (Activation of p70S6K (T389) was detected more frequently amo)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 75 · effect_size

**Finding:** improving long-term cures (0-30% improved to 78-100%)

- **Value:** 78.0%
- **Population:** murine model of recurrent/metastatic HPV+ HNSCC
- **Intervention:** rapamycin as adjuvant to cisplatin/radiation therapy (CRT)
- **Source:** *mTOR inhibition as an adjuvant therapy in a metastatic model of HPV+ HNSCC* — Oncotarget (2016)
  · DOI: `10.18632/oncotarget.8286`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 43.0% (decreasing proliferation (43%)); 32.0% (limiting lymph node metastasis (32%)); 30.0fold (lung metastatic burden (30 fold)); 3.3fold (enhanced CRT-induced cytotoxicity (3.3 fold) in clonogenic a)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=5 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #4 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #5 — score 70 · effect_size

**Finding:** Torin2 inhibited mTORC1-dependent T389 phosphorylation on S6K with an EC50 of 250 pmol/L and 800-fold selectivity for mTOR versus PI3K.

- **Value:** 250.0pmol/L
- **Population:** cancer cells
- **Intervention:** Torin2
- **Source:** *Characterization of Torin2, an ATP-Competitive Inhibitor of mTOR, ATM, and ATR* — Cancer Research (2013)
  · DOI: `10.1158/0008-5472.can-12-1702`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 118.0nmol/L (Torin2 exhibited potent activity against DNA-PK (EC50, 118 n); 35.0nmol/L (Torin2 exhibited potent activity against ATR (EC50, 35 nmol/); 28.0nmol/L (Torin2 exhibited potent activity against ATM (EC50, 28 nmol/)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
