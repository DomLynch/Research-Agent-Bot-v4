# Top 1 interesting findings — NAD

**Snapshot:** 2026-05-27T06-03-03Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=NAD) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 11
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: biomarker=1)

---

## #1 — score 66 · effect_size

**Finding:** Novel double-channel fluorescence lifetime imaging, approximating free mitochondrial matrix NADHF, indicated its ∼20% decrease

- **Value:** 20.0%
- **Population:** INS-1E cells and pancreatic islets
- **Intervention:** Glucose-stimulated insulin secretion (25 mM glucose)
- **Alpha cues:** baseline
- **Source:** *Mitochondrial Superoxide Production Decreases on Glucose-Stimulated Insulin Secretion in Pancreatic β Cells Due to Decreasing Mitochondrial Matrix NADH/NAD <sup>+</sup> Ratio* — Antioxidants and Redox Signaling (2020)
  · DOI: `10.1089/ars.2019.7800`
- **Validator:** researka-tier2

- **Why it matters:** A 20% decrease in mitochondrial NADH in insulin-secreting cells and islets suggests a direct metabolic link to impaired insulin secretion, offering a potential target for type 2 diabetes therapies.
- **Caution:** The novel double-channel fluorescence method was applied in a single experimental replicate (k=1) to specific in vitro models, which may not reflect in vivo complexity or validate against established techniques.
- **Next question:** How does this NADH decrease mechanistically alter mitochondrial function and insulin release under glucose stimulation in diabetic conditions?

---
