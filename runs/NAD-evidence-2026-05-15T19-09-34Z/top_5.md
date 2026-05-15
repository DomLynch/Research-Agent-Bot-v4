# Top 5 interesting findings — NAD

**Snapshot:** 2026-05-15T19-09-34Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=NAD) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 28
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

- **Why it matters:** Depressed NAD+ in ArLD liver tissue highlights NAD+ depletion as a potential target for treating alcohol-related liver damage.
- **Caution:** The study only measured static concentrations in two groups, leaving causality between NAD+ levels and disease progression unclear.
- **Next question:** Can interventions that boost NAD+ mitigate liver injury in ArLD patients?

---

## #2 — score 75 · effect_size

**Finding:** measured the concentration distribution of breath EtOH without alcohol consumption using the improved sniff-cam and obtained a value of 116.2 ± 35.7 ppb

- **Value:** 116.2ppb
- **Population:** human subjects
- **Intervention:** ultrasensitive sniff-cam
- **Source:** *Ultrasensitive Sniff-Cam for Biofluorometric-Imaging of Breath Ethanol Caused by Metabolism of Intestinal Flora* — Analytical Chemistry (2019)
  · DOI: `10.1021/acs.analchem.8b05840`
- **Validator:** researka-tier2

- **Why it matters:** Oral NMN at 400 mg/kg in obese mice models a feasible approach for enhancing NAD+ metabolism, potentially informing human obesity therapies.
- **Caution:** Results are from a specific mouse model with diet-induced obesity, which may not reflect human responses or other obesity etiologies.
- **Next question:** How does chronic NMN supplementation at this dose affect insulin sensitivity and body weight in obese mice?

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

- **Why it matters:** Baseline breath ethanol measurements without alcohol consumption could serve as a non-invasive biomarker for metabolic disorders or alcohol abstinence monitoring.
- **Caution:** The novel sniff-cam method was tested on human subjects under controlled conditions, requiring broader validation for accuracy and real-world use.
- **Next question:** Do endogenous breath ethanol levels correlate with specific metabolic diseases or liver dysfunction?

---

## #4 — score 75 · regimen

**Finding:** A single dose (62.5 mg/kg) of NMN, administered to male mice

- **Value:** 62.5mg/kg
- **Population:** male mice
- **Intervention:** nicotinamide mononucleotide (NMN)
- **Source:** *Nicotinamide mononucleotide alters mitochondrial dynamics by SIRT3‐dependent mechanism in male mice* — Journal of Neuroscience Research (2019)
  · DOI: `10.1002/jnr.24397`
- **Validator:** researka-tier2

- **Why it matters:** The high turnover frequency of this complex in NADH regeneration enables efficient catalysis for industrial bioprocesses or synthetic biology applications.
- **Caution:** The study was conducted in vitro with a single chemical complex, leaving its stability and performance in biological environments unexplored.
- **Next question:** Can this complex be coupled with enzymes for in vivo NADH regeneration in cells or organisms?

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

- **Why it matters:** A single NMN dose in male mice provides acute NAD+ boosting data useful for designing short-term therapeutic trials.
- **Caution:** The study used only male mice and a single dose, ignoring gender differences and long-term efficacy or safety.
- **Next question:** What is the minimum effective dose for sustained NAD+ elevation in female mice, and does sex affect NMN metabolism?

---
