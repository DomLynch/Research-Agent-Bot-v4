# Top 3 interesting findings — autophagy

**Snapshot:** 2026-05-16T18-09-59Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=autophagy) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 16
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: model_context=2, molecular_mechanism=1)

**Sub-topic lanes detected:** facts grouped by `sub_topic` below — read each lane independently.

---

### Lane — `effect_size`


## #1 — score 63 · effect_size

**Finding:** autophagy flux was significantly less in injured versus uninjured muscles (-26%, P < 0.02).

- **Value:** -26.0%
- **Population:** mice
- **Intervention:** traumatic freeze injury
- **Alpha cues:** baseline
- **Source:** *Mitochondrial-specific autophagy linked to mitochondrial dysfunction following traumatic freeze injury in mice* — American Journal of Physiology-Cell Physiology (2019)
  · DOI: `10.1152/ajpcell.00123.2019`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties traumatic freeze injury in mice to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `mechanism`


## #2 — score 50 · mechanism

**Finding:** Inhibition of autophagy by silencing of the key autophagy gene, beclin 1 or 3-MA, further increased the cytotoxicity of this combinatorial treatment, suggesting that autophagy plays a cytoprotective role

- **Value:** 1.0OR
- **Population:** glioma cells
- **Intervention:** MK-2206 + gefitinib with autophagy inhibition (beclin 1 silencing or 3-MA)
- **Alpha cues:** baseline
- **Source:** *MK-2206, a Novel Allosteric Inhibitor of Akt, Synergizes with Gefitinib against Malignant Glioma via Modulating Both Autophagy and Apoptosis* — Molecular Cancer Therapeutics (2011)
  · DOI: `10.1158/1535-7163.mct-11-0606`
- **Validator:** researka-tier2

- **Why it matters:** This is worth checking because it ties MK-2206 + gefitinib with autophagy inhibition (beclin 1 silencing or 3-MA) in glioma cells to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---

### Lane — `rate`


## #3 — score 40 · rate

**Finding:** a population (∼30%) of intracellular Mtb is tagged with ubiquitin and targeted to selective autophagy

- **Value:** 30.0%
- **Population:** intracellular Mtb in macrophages
- **Intervention:** ESX-1 secretion system perturbation
- **Alpha cues:** baseline
- **Source:** *Galectin-8 Senses Phagosomal Damage and Recruits Selective Autophagy Adapter TAX1BP1 To Control <i>Mycobacterium tuberculosis</i> Infection in Macrophages* — mBio (2021)
  · DOI: `10.1128/mbio.01871-20`
- **Validator:** —

- **Why it matters:** This is worth checking because it ties ESX-1 secretion system perturbation in intracellular Mtb in macrophages to a source-backed effect.
- **Caution:** Do not overread this as settled: k=1 from this paper; confirm extraction, comparator, and repeatability before treating it as a broad claim.
- **Next question:** What independent receipt would confirm this signal and what specific result would falsify it?

---
