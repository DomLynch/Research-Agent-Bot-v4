# Top 5 interesting findings — NAD

**Snapshot:** 2026-05-15T08-53-15Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=NAD) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 43
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM). Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 80 · effect_size

**Finding:** ArLD liver tissue showed markedly depressed concentrations of NAD+ (432 μM vs. 616 μM in normal liver)

- **Value:** 432.0μM
- **Population:** Patients with alcohol-related liver disease (ArLD) and normal liver
- **Intervention:** ArLD
- **Source:** *Nicotinamide Adenine Dinucleotide Metabolome Is Functionally Depressed in Patients Undergoing Liver Transplantation for Alcohol‐Related Liver Disease* — Hepatology Communications (2020)
  · DOI: `10.1002/hep4.1530`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 462.0μM (a significant difference for individual components of the me); 0.31 (NAD+ concentration was ... positively correlated with myelop); -0.127 (NAD+ concentration was inversely related to serum bilirubin ); 0.018 (There was a significant overall difference in the NAD+ metab)

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=5 biomarkers from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #2 — score 75 · effect_size

**Finding:** measured the concentration distribution of breath EtOH without alcohol consumption using the improved sniff-cam and obtained a value of 116.2 ± 35.7 ppb

- **Value:** 116.2ppb
- **Population:** human subjects
- **Intervention:** ultrasensitive sniff-cam
- **Source:** *Ultrasensitive Sniff-Cam for Biofluorometric-Imaging of Breath Ethanol Caused by Metabolism of Intestinal Flora* — Analytical Chemistry (2019)
  · DOI: `10.1021/acs.analchem.8b05840`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `effect_size` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `regimen`


## #3 — score 80 · regimen

**Finding:** Mice received NMN in drinking water (400 mg/kg).

- **Value:** 400.0mg/kg
- **Population:** female C57BL/6J mice with diet-induced obesity
- **Intervention:** NMN in drinking water
- **Source:** *Exercise-induced benefits on glucose handling in a model of diet-induced obesity are reduced by concurrent nicotinamide mononucleotide* — American Journal of Physiology-Endocrinology and Metabolism (2021)
  · DOI: `10.1152/ajpendo.00446.2020`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `regimen` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

## #4 — score 75 · regimen

**Finding:** A single dose (62.5 mg/kg) of NMN, administered to male mice

- **Value:** 62.5mg/kg
- **Population:** male mice
- **Intervention:** nicotinamide mononucleotide (NMN)
- **Source:** *Nicotinamide mononucleotide alters mitochondrial dynamics by SIRT3‐dependent mechanism in male mice* — Journal of Neuroscience Research (2019)
  · DOI: `10.1002/jnr.24397`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `regimen` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---

### Lane — `rate`


## #5 — score 75 · rate

**Finding:** The 5,5'-substituted bipyridine Cp*Rh<sup>III</sup> complex, which had the lowest reduction potential, most effectively regenerated NADH with a turnover frequency of 1100 h<sup>-1</sup>.

- **Value:** 1100.0h⁻1
- **Population:** 5,5'-substituted bipyridine Cp*Rh complex
- **Intervention:** 5,5'-substituted bipyridine Cp*Rh complex for NADH regeneration
- **Source:** *Correlation between the Structure and Catalytic Activity of [Cp*Rh(Substituted Bipyridine)] Complexes for NADH Regeneration* — Inorganic Chemistry (2017)
  · DOI: `10.1021/acs.inorgchem.6b02474`
- **Validator:** researka-tier2

- **Why it matters:** Direct evidence in the `rate` sub-topic; informs whether the finding generalises beyond a single study.
- **Caution:** Single trial / single subgroup (k=1 biomarker from one paper); replication across independent cohorts required.
- **Next question:** What sub-populations, doses, or timepoints remain underexplored for this finding?

---
