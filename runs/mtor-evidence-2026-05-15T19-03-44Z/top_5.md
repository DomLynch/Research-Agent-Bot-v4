# Top 5 interesting findings — mtor

**Snapshot:** 2026-05-15T19-03-44Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=mtor) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 30
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

- **Why it matters:** High mTOR activity in 70% of urothelial carcinomas suggests bladder cancer patients may benefit from targeted mTOR inhibitor therapies.
- **Caution:** The rate is derived from a specific study cohort, and may not generalize across all bladder cancer subtypes or populations.
- **Next question:** Is mTOR activity linked to specific genetic mutations or clinical outcomes in bladder cancer, enabling personalized treatment?

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

- **Why it matters:** Confirming pathways associated with hepatic metastasis in breast cancer can inform targeted therapies to prevent liver spread, improving patient survival.
- **Caution:** The cohort of 154 tumors is independent but may not encompass all breast cancer subtypes, limiting broader applicability.
- **Next question:** Which specific pathways are most critical for hepatic metastasis, and can they be therapeutically targeted in clinical settings?

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

- **Why it matters:** In a mouse model, achieving 78-100% cure rates for recurrent/metastatic HPV+ HNSCC offers hope for translating this treatment to human patients with similar cancers.
- **Caution:** Results are from a murine model, which may not replicate human biology or treatment responses accurately.
- **Next question:** What mechanisms drive the improved cure rates in mice, and does this treatment show efficacy in human clinical trials?

---

## #4 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** Metformin reducing tumor burden by 72% in a mouse model suggests its potential repurposing for cancer prevention, especially in smokers at risk for lung cancer.
- **Caution:** The study used a specific mouse strain and carcinogen dose, so human effects could differ due to biological and exposure variations.
- **Next question:** Does metformin effectively reduce tumors in human smokers, and what is the optimal dose regimen for cancer prevention?

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

- **Why it matters:** Torin2's high selectivity for mTOR over PI3K could enable more potent mTOR inhibitors with reduced off-target side effects in cancer treatment.
- **Caution:** The data is from in vitro cancer cell studies, lacking in vivo validation for efficacy, safety, and pharmacokinetics.
- **Next question:** How does Torin2 perform in animal models, and what are its metabolic properties and potential for clinical development?

---
