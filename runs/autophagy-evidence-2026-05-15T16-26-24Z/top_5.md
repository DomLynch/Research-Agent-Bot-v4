# Top 5 interesting findings — autophagy

**Snapshot:** 2026-05-15T16-26-24Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=autophagy) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 14
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 64 · effect_size

**Finding:** Ulk1 knockouts had contractile weakness compared with littermate controls (-27%, P < 0.02).

- **Value:** -27.0%
- **Population:** Ulk1 knockout mice and littermate controls
- **Intervention:** Ulk1 deficiency
- **Source:** *Mitochondrial-specific autophagy linked to mitochondrial dysfunction following traumatic freeze injury in mice* — American Journal of Physiology-Cell Physiology (2019)
  · DOI: `10.1152/ajpcell.00123.2019`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** -26.0% (autophagy flux was significantly less in injured versus unin)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 60 · effect_size

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

## #3 — score 55 · effect_size

**Finding:** These findings show that beclin 1 plays a constitutive, autophagy-independent role in the regulation of intestinal TJ barrier function via endocytosis of occludin.

- **Value:** 1.0
- **Population:** intestinal epithelial cells and mouse colon
- **Intervention:** beclin 1
- **Source:** *Intestinal epithelial tight junction barrier regulation by autophagy-related protein ATG6/beclin 1* — American Journal of Physiology-Cell Physiology (2019)
  · DOI: `10.1152/ajpcell.00246.2018`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 1.0 (Perfusion of mouse colon with beclin 1 peptide caused an inc); 1.0 (beclin 1 siRNA transfection enhanced Caco-2 TJ barrier funct); 1.0 (Activation of beclin 1 increased occludin endocytosis and re)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `threshold`


## #4 — score 56 · threshold

**Finding:** TXA1 induced autophagy of melanoma cells at the GI50 concentration (3.6 μM)

- **Value:** 3.6μM
- **Population:** A375-C5 melanoma cells
- **Intervention:** TXA1
- **Source:** *Modulation of Autophagy by a Thioxanthone Decreases the Viability of Melanoma Cells* — Molecules (2016)
  · DOI: `10.3390/molecules21101343`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `threshold` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #5 — score 56 · threshold

**Finding:** APP-CTF (apparent EC(50) of ∼20 μM)

- **Value:** 20.0μM
- **Population:** cell lines and primary neuronal cultures
- **Intervention:** SMER28
- **Source:** *A small‐molecule enhancer of autophagy decreases levels of Aβ and APP‐CTF <b> <i>via</i> Atg5‐dependent autophagy pathway </b>* — The FASEB Journal (2011)
  · DOI: `10.1096/fj.10-175158`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 10.0μM (Aβ peptide (apparent EC(50) of ∼10 μM))

- **Why it matters:** Direct evidence in the `threshold` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=2 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
