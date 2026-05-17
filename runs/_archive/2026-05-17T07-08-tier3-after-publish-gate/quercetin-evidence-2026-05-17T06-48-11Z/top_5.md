# Top 3 interesting findings — quercetin

**Snapshot:** 2026-05-17T06-48-11Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=quercetin) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 29
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=1, molecular_mechanism=2)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


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

- **Why it matters:** Quercetin's ability to alter SARS-CoV-2 protein functions in human cells highlights its potential as a broad-spectrum antiviral, which could inform COVID-19 therapeutic strategies.
- **Caution:** This effect was observed in vitro with isolated human cells, limiting direct inference to whole-organism antiviral efficacy or safety.
- **Next question:** Do these protein alterations translate to reduced viral replication or clinical outcomes in live animal models or human infections?

---

## #2 — score 75 · effect_size

**Finding:** Quercetin notably inhibited both mRNA and protein expression of CD36 (reduced by 53% and 71%, resp.)

- **Value:** 71.0%
- **Population:** high-fat diet-induced animal model
- **Intervention:** quercetin supplementation
- **Alpha cues:** baseline
- **Source:** *Quercetin Alleviates High-Fat Diet-Induced Oxidized Low-Density Lipoprotein Accumulation in the Liver: Implication for Autophagy Regulation* — BioMed Research International (2015)
  · DOI: `10.1155/2015/607531`
- **Validator:** researka-tier2
- **Same-trial supporting numerics:** 57.0% (p62 and mTOR was downregulated by 57% and 63% by quercetin t); 45.0% (and MSR1 (reduced by 25% and 45%, resp.))

- **Why it matters:** Quercetin's significant suppression of CD36 in an animal model suggests it may mitigate obesity-related pathologies by limiting fatty acid uptake, relevant for metabolic disease management.
- **Caution:** The findings stem from a high-fat diet-induced animal model, which may not replicate human metabolic physiology or the bioavailability of quercetin in humans.
- **Next question:** Can quercetin achieve comparable CD36 inhibition in human trials without compromising essential lipid metabolism or causing side effects?

---

### Lane — `subgroup`


## #3 — score 25 · subgroup

**Finding:** Quercetin + resveratrol at the ratio of 1:1 performed better than when used at ratios of either 3:1 or 1:3.

- **Value:** 1.0OR
- **Population:** etched dentin samples
- **Intervention:** dentin pretreatment with quercetin and resveratrol mixture at ratio 1:1
- **Alpha cues:** baseline
- **Source:** *Use of polyphenols as a strategy to prevent bond degradation in the dentin–resin interface* — European Journal Of Oral Sciences (2018)
  · DOI: `10.1111/eos.12403`
- **Validator:** —

- **Why it matters:** The superior performance of quercetin and resveratrol at a 1:1 ratio in etched dentin samples could optimize dental adhesive formulations or remineralization agents for improved clinical durability.
- **Caution:** This study used etched dentin samples, a controlled ex vivo system that may not reflect the complex mechanical and microbial challenges of the oral environment.
- **Next question:** How does the 1:1 ratio of quercetin and resveratrol influence the long-term bond strength, biocompatibility, and resistance to degradation in vivo dental applications?

---
