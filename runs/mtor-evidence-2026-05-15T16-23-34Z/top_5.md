# Top 5 interesting findings — mtor

**Snapshot:** 2026-05-15T16-23-34Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=mtor) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 46
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

- **Why it matters:** High mTOR activity in most urothelial carcinomas highlights its potential as a therapeutic target for bladder cancer.
- **Caution:** This rate-based observation may not account for tumor heterogeneity or establish causality without intervention studies.
- **Next question:** Does pharmacological inhibition of mTOR in these tumors lead to improved patient survival?

---

### Lane — `effect_size`


## #2 — score 75 · effect_size

**Finding:** the mTOR pathway plays an important role in the growth of these Flcn-deficient allograft and human UOK 257-1 xenograft tumors

- **Value:** 257.0
- **Population:** Flcn-deficient allograft and human UOK 257-1 xenograft tumors
- **Intervention:** mTOR pathway
- **Source:** *Flcn-deficient renal cells are tumorigenic and sensitive to mTOR suppression* — Oncotarget (2015)
  · DOI: `10.18632/oncotarget.5018`
- **Validator:** researka-tier2

- **Why it matters:** mTOR's role in Flcn-deficient tumor growth underscores its importance in related renal cancer models.
- **Caution:** Allograft and xenograft models may not fully replicate human tumor microenvironments or immune responses.
- **Next question:** How do FLCN mutations modulate mTOR signaling in human renal cell carcinoma patients?

---

## #3 — score 75 · effect_size

**Finding:** noncancer cells showed up to 100-fold less sensitivity to ICSN3250

- **Value:** 100.0fold
- **Population:** cancer and noncancer cells
- **Intervention:** ICSN3250
- **Source:** *mTOR Inhibition via Displacement of Phosphatidic Acid Induces Enhanced Cytotoxicity Specifically in Cancer Cells* — Cancer Research (2018)
  · DOI: `10.1158/0008-5472.can-18-0232`
- **Validator:** researka-tier2

- **Why it matters:** The 100-fold lower sensitivity of noncancer cells to ICSN3250 suggests a favorable therapeutic window for selective cancer treatment.
- **Caution:** In vitro effect sizes may not translate to in vivo settings due to pharmacokinetic and dose variability.
- **Next question:** Can ICSN3250 maintain its selectivity and efficacy in clinical trials with diverse cancer types?

---

## #4 — score 75 · effect_size

**Finding:** RPPA analysis of an independent cohort of 154 tumors confirmed the relationship between pathway activation and hepatic metastasis.

- **Value:** 154.0
- **Population:** Breast cancer metastatic lesions
- **Intervention:** —
- **Source:** *Enrichment of PI3K-AKT–mTOR Pathway Activation in Hepatic Metastases from Breast Cancer* — Clinical Cancer Research (2017)
  · DOI: `10.1158/1078-0432.ccr-16-2656`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.01 (PIK3CA mutation was detected more frequently among liver met); 0.056 (Activation of AKT (S473) was detected more frequently among ); 0.053 (Activation of p70S6K (T389) was detected more frequently amo)

- **Why it matters:** Linking mTOR pathway activation to hepatic metastasis in breast cancer helps identify high-risk patients for early intervention.
- **Caution:** The cohort of 154 tumors may not encompass all breast cancer molecular subtypes or ethnic variations.
- **Next question:** Does targeting mTOR with inhibitors reduce hepatic metastasis incidence in breast cancer patients?

---

## #5 — score 75 · effect_size

**Finding:** improving long-term cures (0-30% improved to 78-100%)

- **Value:** 78.0%
- **Population:** murine model of recurrent/metastatic HPV+ HNSCC
- **Intervention:** rapamycin as adjuvant to cisplatin/radiation therapy (CRT)
- **Source:** *mTOR inhibition as an adjuvant therapy in a metastatic model of HPV+ HNSCC* — Oncotarget (2016)
  · DOI: `10.18632/oncotarget.8286`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 43.0% (decreasing proliferation (43%)); 32.0% (limiting lymph node metastasis (32%)); 30.0fold (lung metastatic burden (30 fold)); 3.3fold (enhanced CRT-induced cytotoxicity (3.3 fold) in clonogenic a)

- **Why it matters:** Improving cure rates from 0-30% to 78-100% in a murine model indicates potential for curative therapies in recurrent HPV+ HNSCC.
- **Caution:** Murine models often fail to predict human clinical outcomes due to biological differences and tumor evolution.
- **Next question:** What molecular mechanisms drive the enhanced cure rates, and how can they be sustained in human trials?

---
