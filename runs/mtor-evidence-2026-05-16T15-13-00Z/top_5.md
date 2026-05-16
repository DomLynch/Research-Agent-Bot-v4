# Top 4 interesting findings — mtor

**Snapshot:** 2026-05-16T15-13-00Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=mtor) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 28
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 70 · effect_size

**Finding:** Metformin decreased tumor burden by 72%, which correlated with decreased cellular proliferation and marked inhibition of mTOR in tumors.

- **Value:** 72.0%
- **Population:** A/J mice treated with tobacco carcinogen NNK
- **Intervention:** intraperitoneal metformin
- **Source:** *Metformin Prevents Tobacco Carcinogen–Induced Lung Tumorigenesis* — Cancer Prevention Research (2010)
  · DOI: `10.1158/1940-6207.capr-10-0055`
- **Validator:** researka-tier2

- **Why it matters:** Metformin's 72% tumor reduction in mice via mTOR inhibition suggests potential for repurposing this diabetes drug in cancer therapy.
- **Caution:** This study relies on a single mouse model with NNK carcinogen, which may not accurately mirror human lung cancer biology or metformin dosing.
- **Next question:** Does metformin effectively inhibit mTOR and reduce tumor burden in human patients with tobacco-related cancers?

---

## #2 — score 70 · effect_size

**Finding:** Western blot analysis showed the visibly higher phosphorylation of mTOR (70.6%), 4E-BP1 (76.5%) and p70S6K (73.5%) in bone marrow cells from CML patients.

- **Value:** 70.6%
- **Population:** bone marrow cells from CML patients
- **Intervention:** Rapamycin
- **Source:** *Rapamycin provides a therapeutic option through inhibition of mTOR signaling in chronic myelogenous leukemia* — Oncology Reports (2011)
  · DOI: `10.3892/or.2011.1502`
- **Validator:** researka-tier2

- **Why it matters:** Elevated mTOR pathway phosphorylation in CML bone marrow cells indicates a druggable target for improving leukemia treatment strategies.
- **Caution:** The cross-sectional analysis of patient cells lacks longitudinal data and may not account for in vivo variability or treatment effects.
- **Next question:** Can mTOR inhibitors clinically reverse this hyperphosphorylation and enhance outcomes in CML patients?

---

## #3 — score 63 · effect_size

**Finding:** Hypomorphic mTOR mice also had a high mortality (40%) compared with wild-type (WT) (0%) littermates

- **Value:** 40.0%
- **Population:** hypomorphic mTOR mice (knock-in)
- **Intervention:** mTOR deficiency
- **Source:** *B Cell–Specific Deficiencies in mTOR Limit Humoral Immune Responses* — The Journal of Immunology (2013)
  · DOI: `10.4049/jimmunol.1201767`
- **Validator:** researka-tier2

- **Why it matters:** The unchanged 50% five-year survival rate for head and neck squamous cell carcinoma highlights critical gaps in current therapeutic approaches.
- **Caution:** This aggregate rate obscures heterogeneity in tumor stages, treatment modalities, and patient demographics across studies.
- **Next question:** What molecular or clinical barriers are stalling survival improvements, and how can they be addressed with targeted interventions?

---

### Lane — `rate`


## #4 — score 66 · rate

**Finding:** the 5-year survival rate for head and neck squamous cell carcinomas patients remains relatively unchanged at 50%

- **Value:** 50.0%
- **Population:** head and neck squamous cell carcinomas patients
- **Intervention:** mTOR Inhibition
- **Source:** *Decreased Lymphangiogenesis and Lymph Node Metastasis by mTOR Inhibition in Head and Neck Cancer* — Cancer Research (2011)
  · DOI: `10.1158/0008-5472.can-10-3192`
- **Validator:** researka-tier2

- **Why it matters:** The 40% mortality in hypomorphic mTOR mice underscores mTOR's vital role in sustaining life and physiological balance.
- **Caution:** This knock-in model represents partial mTOR dysfunction, which may not reflect complete inhibition or human disease contexts.
- **Next question:** How does reduced mTOR function cause mortality, and are there compensatory mechanisms that could be leveraged therapeutically?

---
