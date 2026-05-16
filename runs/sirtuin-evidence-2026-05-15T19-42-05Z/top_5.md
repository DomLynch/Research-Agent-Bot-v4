# Top 5 interesting findings — sirtuin

**Snapshot:** 2026-05-15T19-42-05Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=sirtuin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 21
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

---

## #1 — score 80 · effect_size

**Finding:** Here we describe potent cambinol-based SIRT2 inhibitors, several of which show potency of ~600 nM with >300 to >800-fold selectivity over SIRT1 and 3, respectively.

- **Value:** 600.0nM
- **Population:** lymphoma and epithelial cancer cell lines
- **Intervention:** cambinol-based SIRT2 inhibitors
- **Source:** *Discovery of Selective SIRT2 Inhibitors as Therapeutic Agents in B-Cell Lymphoma and Other Malignancies* — Molecules (2020)
  · DOI: `10.3390/molecules25030455`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.25µM (compound 55 (IC50 SIRT2 0.25 µM and <25% inhibition at 50 µM); 0.78µM (compound 56 (IC50 SIRT2 0.78 µM and <25% inhibition at 50 µM)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 70 · effect_size

**Finding:** reduced hepatic tumorigenesis (65% reduction in volume)

- **Value:** 65.0%
- **Population:** C57Bl/6J mice
- **Intervention:** APO10LA supplementation (10 mg/kg diet)
- **Source:** *Lycopene Metabolite, Apo-10′-Lycopenoic Acid, Inhibits Diethylnitrosamine-Initiated, High Fat Diet–Promoted Hepatic Inflammation and Tumorigenesis in Mice* — Cancer Prevention Research (2013)
  · DOI: `10.1158/1940-6207.capr-13-0178`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 85.0% (reduced lung tumor incidence (85% reduction)); 50.0% (APO10LA supplementation (10 mg/kg diet) for 24 weeks signifi)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=3 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #3 — score 66 · effect_size

**Finding:** knockdown of SIRT1 resulted in 50% fewer animals developing tumors

- **Value:** 50.0%
- **Population:** orthotopic xenograft model
- **Intervention:** knockdown of SIRT1
- **Source:** *Antitumor Effect of SIRT1 Inhibition in Human HCC Tumor Models <i>In Vitro</i> and <i>In Vivo</i>* — Molecular Cancer Therapeutics (2013)
  · DOI: `10.1158/1535-7163.mct-12-0700`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #4 — score 64 · effect_size

**Finding:** deacetylase sirtuin (SIRT)-1 (-29%) in desynchronized young rats.

- **Value:** -29.0%
- **Population:** desynchronized young grass rats
- **Intervention:** circadian desynchronization
- **Source:** *Circadian desynchronization triggers premature cellular aging in a diurnal rodent* — The FASEB Journal (2015)
  · DOI: `10.1096/fj.14-266817`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #5 — score 60 · effect_size

**Finding:** PA negatively modulated SIRT3 expression (p < 0.001).

- **Value:** 0.001
- **Population:** human endothelial cells (TeloHAEC)
- **Intervention:** palmitic acid (PA) treatment at 0.5 mM for 48 h
- **Source:** *SIRT3 Modulates Endothelial Mitochondrial Redox State during Insulin Resistance* — Antioxidants (2022)
  · DOI: `10.3390/antiox11081611`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 0.01 (SIRT3 restoration suppressed pyroptosis (p < 0.01).); 0.01 (SIRT3 restoration suppressed PA-induced autophagy (p < 0.01)); 0.001 (PA imbalanced the oxidative status (p < 0.001).)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=4 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
