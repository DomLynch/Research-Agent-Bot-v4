# Top 5 interesting findings — autophagy

**Snapshot:** 2026-05-15T16-26-24Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=autophagy) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 48
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 75 · effect_size

**Finding:** 14,15-EET inhibited CSC-induced autophagy in Beas-2B cells.

- **Value:** 1415.0
- **Population:** Beas-2B cells
- **Intervention:** 14,15-EET
- **Source:** *14,15-Epoxyeicosatrienoic acid suppresses cigarette smoke condensate-induced inflammation in lung epithelial cells by inhibiting autophagy* — American Journal of Physiology-Lung Cellular and Molecular Physiology (2016)
  · DOI: `10.1152/ajplung.00161.2016`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1415.0 (14,15-EET treatment resulted in a significant reduction in I)

- **Why it matters:** 14,15-EET could be developed as a therapeutic agent to protect lung cells from autophagy-induced damage caused by cigarette smoke.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 64 · effect_size

**Finding:** Ulk1 knockouts had contractile weakness compared with littermate controls (-27%, P < 0.02).

- **Value:** -27.0%
- **Population:** Ulk1 knockout mice and littermate controls
- **Intervention:** Ulk1 deficiency
- **Source:** *Mitochondrial-specific autophagy linked to mitochondrial dysfunction following traumatic freeze injury in mice* — American Journal of Physiology-Cell Physiology (2019)
  · DOI: `10.1152/ajpcell.00123.2019`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -26.0% (autophagy flux was significantly less in injured versus unin); 2.0fold (there is a significant increase in several mitochondrial-spe)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 60 · effect_size

**Finding:** 1.215 (1.149-1.286) (P < .001) in multivariate Cox regression analysis

- **Value:** 1.215HR
- **Population:** patients with lung adenocarcinoma
- **Intervention:** autophagy-related lncRNA survival model
- **Source:** *A novel autophagy‐related lncRNA survival model for lung adenocarcinoma* — Journal of Cellular and Molecular Medicine (2021)
  · DOI: `10.1111/jcmm.16582`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.256HR (1.256 (1.196-1.320) (P < .001) in univariate Cox regression )

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #4 — score 60 · effect_size

**Finding:** perinatal loss of both ULK1 and ULK2 in cU1/2-DKO mice impaired autophagy causing age-related cardiomyopathy and reduced survival.

- **Value:** 2.0
- **Population:** cU1/2-DKO mice with perinatal loss of both ULK1 and ULK2
- **Intervention:** loss of ULK1 and ULK2 perinatally
- **Source:** *Perinatal versus adult loss of ULK1 and ULK2 distinctly influences cardiac autophagy and function* — Autophagy (2022)
  · DOI: `10.1080/15548627.2021.2022289`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `duration`


## #5 — score 66 · duration

**Finding:** At 48 hours following the combinatorial treatment, the level of LC3-II began to decrease but Bim was significantly elevated, suggesting a switch from autophagy to apoptosis

- **Value:** 48.0hours
- **Population:** glioma cells
- **Intervention:** MK-2206 + gefitinib
- **Source:** *MK-2206, a Novel Allosteric Inhibitor of Akt, Synergizes with Gefitinib against Malignant Glioma via Modulating Both Autophagy and Apoptosis* — Molecular Cancer Therapeutics (2011)
  · DOI: `10.1158/1535-7163.mct-11-0606`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `duration` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
