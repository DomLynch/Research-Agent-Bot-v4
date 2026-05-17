# Top 2 interesting findings — mtor

**Snapshot:** 2026-05-16T17-08-58Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=mtor) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 28
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=1, preclinical_cancer=1)

---

## #1 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's mTOR inhibition in NNK-treated mice offers a promising avenue for lung cancer prevention, especially in tobacco-exposed populations.
- **Caution:** The effect was observed in a single mouse model (k=1) with a fixed carcinogen dose, limiting generalizability to human cancer etiology.
- **Next question:** What is the optimal metformin dosage and regimen for mTOR inhibition to achieve similar tumor reduction in humans?

---

## #2 — score 63 · effect_size

**Finding:** Hypomorphic mTOR mice also had a high mortality (40%) compared with wild-type (WT) (0%) littermates

- **Value:** 40.0%
- **Population:** hypomorphic mTOR mice (knock-in)
- **Intervention:** mTOR deficiency
- **Source:** *B Cell–Specific Deficiencies in mTOR Limit Humoral Immune Responses* — The Journal of Immunology (2013)
  · DOI: `10.4049/jimmunol.1201767`
- **Validator:** researka-tier2

- **Why it matters:** Severe mortality in mTOR-hypomorphic mice highlights the critical role of mTOR in physiological homeostasis, relevant for designing safe mTOR-targeted therapies.
- **Caution:** This study used a knock-in mouse model (k=1), which may not mimic the transient or partial mTOR inhibition seen in drug treatments.
- **Next question:** How can mTOR activity be modulated therapeutically without compromising survival, perhaps through tissue-specific targeting?

---
