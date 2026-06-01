# Top 4 interesting findings — quercetin

**Snapshot:** 2026-05-26T19-55-42Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=quercetin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 36
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=3, molecular_mechanism=1)

---

## #1 — score 92 · effect_size

**Finding:** functions of 25 of 27 (93%) of SARS-CoV-2 proteins in human cells may be altered

- **Value:** 93.0%
- **Population:** SARS-CoV-2 proteins in human cells
- **Intervention:** quercetin and vitamin D
- **Alpha cues:** translation_context
- **Source:** *Tripartite Combination of Candidate Pandemic Mitigation Agents: Vitamin D, Quercetin, and Estradiol Manifest Properties of Medicinal Agents for Targeted Mitigation of the COVID-19 Pandemic Defined by Genomics-Guided Tracing of SARS-CoV-2 Targets in Human Cells* — Biomedicines (2020)
  · DOI: `10.3390/biomedicines8050129`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 30.0% (quercetin alters the expression of 98 of 332 (30%) of human ); 73.0% (A hypothetical tripartite combination consisting of querceti)

- **Why it matters:** Quercetin's ability to alter 93% of SARS-CoV-2 proteins suggests it could serve as a broad-spectrum antiviral targeting multiple viral functions in COVID-19.
- **Caution:** This finding relies on computational or in vitro protein interaction models, not actual viral infection assays, so clinical relevance is unproven.
- **Next question:** Does quercetin effectively inhibit SARS-CoV-2 replication in live human cells or animal models?

---

## #2 — score 87 · effect_size

**Finding:** Only quercetin and fisetin inhibited DENV-2 and DENV-3 infection in the absence or presence of enhancing antibody (>90%, p<0.001);

- **Value:** 90.0%
- **Population:** Human U937-DC-SIGN macrophages infected with dengue virus serotypes 2 or 3
- **Intervention:** quercetin and fisetin
- **Alpha cues:** translation_context
- **Source:** *&lt;p&gt;Antiviral and immunomodulatory effects of polyphenols on macrophages infected with dengue virus serotypes 2 and 3 enhanced or not with antibodies&lt;/p&gt;* — Infection and Drug Resistance (2019)
  · DOI: `10.2147/idr.s210890`
- **Validator:** researka-tier2

- **Why it matters:** Quercetin's over 90% inhibition of dengue virus serotypes in macrophages indicates strong potential for preventing or treating dengue infections.
- **Caution:** The study used only U937-DC-SIGN macrophages and enhancing antibody conditions, which may not replicate natural human infection dynamics.
- **Next question:** Can quercetin's antiviral efficacy against dengue be confirmed in animal models or human clinical trials?

---

## #3 — score 70 · effect_size

**Finding:** it significantly dampened the postprandial hyperglycemia by 64.0% in maltose loaded diabetic rats

- **Value:** 64.0%
- **Population:** STZ-induced diabetic rats
- **Intervention:** quercetin 600 mg/kg
- **Alpha cues:** baseline
- **Source:** *Effect of quercetin on postprandial glucose excursion after mono- and disaccharides challenge in normal and diabetic rats* — Journal of Diabetes Mellitus (2012)
  · DOI: `10.4236/jdm.2012.21013`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 30.3% (and 30.3% after 300 mg/kg dose in normal rats, compared to c); 32.0% (it significantly dampened the postprandial hyperglycemia by )

- **Why it matters:** A 64% reduction in postprandial hyperglycemia in diabetic rats suggests quercetin could help manage blood sugar spikes after carbohydrate intake.
- **Caution:** The study used STZ-induced diabetic rats with a specific maltose load, limiting direct translation to human diabetes and diet.
- **Next question:** How does quercetin perform in human diabetic patients with varied meal compositions?

---

## #4 — score 54 · effect_size

**Finding:** quercetin inhibited α-amylase activity (in vitro) up to 20.30 ± 0.49%

- **Value:** 20.3%
- **Population:** in vitro α-amylase assay
- **Intervention:** quercetin
- **Alpha cues:** low_signal_context
- **Source:** *Quercetin and Kaempferol as Multi-Targeting Antidiabetic Agents against Mouse Model of Chemically Induced Type 2 Diabetes* — Pharmaceuticals (2024)
  · DOI: `10.3390/ph17060757`
- **Validator:** researka-tier2

- **Why it matters:** Inhibiting α-amylase activity by 20% in vitro implies quercetin might modestly slow starch digestion to aid in blood sugar regulation.
- **Caution:** The inhibition percentage is derived from a cell-free assay with a single dose, so in vivo effects may be negligible or unconfirmed.
- **Next question:** What is the dose-dependent effect of quercetin on α-amylase activity and postprandial glucose in humans?

---
