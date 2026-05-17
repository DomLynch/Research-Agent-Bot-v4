# Top 1 interesting findings — creatine

**Snapshot:** 2026-05-17T06-54-30Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=creatine) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 2
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `technical_signal` (facet counts: assay_or_detection=1)

---

## #1 — score 68 · threshold

**Finding:** Changes of <5% in NAA, choline, creatine and <10% in mI and Glx detectable in a group of 20 subjects.

- **Value:** 5.0%
- **Population:** group of 20 subjects
- **Intervention:** MRS measurements
- **Alpha cues:** translation_context
- **Source:** *Single‐voxel <sup>1</sup>H spectroscopy in the human hippocampus at 3 T using the LASER sequence: characterization of neurochemical profile and reproducibility* — NMR in Biomedicine (2015)
  · DOI: `10.1002/nbm.3364`
- **Validator:** researka-tier2

- **Why it matters:** Detecting small changes in creatine and other brain metabolites with MRS enables precise monitoring of energy metabolism in neurological research and clinical trials.
- **Caution:** The study involved only 20 subjects, limiting statistical power, and did not vary detection models or doses to validate thresholds.
- **Next question:** Can these detection thresholds be confirmed in larger, diverse populations to ensure their applicability across different clinical scenarios?

---
