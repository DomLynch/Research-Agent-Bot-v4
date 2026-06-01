# Top 1 interesting findings — mtor

**Snapshot:** 2026-05-26T18-45-19Z
**Source:** Researka DB Tier-2 search (`POST /api/v1/tier2/facts/search`, filter topic=mtor) — LLM-extracted, no Tier-1 canonical facts loaded for this topic yet; findings may be off-target (e.g. chemistry papers using the molecule name) until canonical curation.
**Facts inspected:** 19
**Ranking:** validation * magnitude * precision * recency (deterministic, no LLM), then one coherent broad theme is selected by aggregate score. Same-paper + same-sub_topic findings are collapsed; extra biomarkers from the same trial appear as supporting numerics under the headline.

**Selected theme:** `intervention_signal` (facet counts: clinical_outcome=1)

---

## #1 — score 59 · effect_size

**Finding:** for combination of anti-estrogenic treatment with mammalian target of rapamycin (mTOR) inhibitors 14-31%

- **Value:** 14.0%
- **Population:** patients with advanced stage and recurrent endometrial cancer
- **Intervention:** anti-estrogenic treatment with mTOR inhibitors
- **Alpha cues:** baseline
- **Source:** *Anti-estrogen Treatment in Endometrial Cancer: A Systematic Review* — Frontiers in Oncology (2019)
  · DOI: `10.3389/fonc.2019.00359`
- **Validator:** researka-tier2

- **Why it matters:** A 14-31% effect size from combining anti-estrogenic treatment with mTOR inhibitors presents a viable therapeutic option for patients with advanced endometrial cancer, where few effective treatments exist.
- **Caution:** The effect size is based on a single study (k=1) using specific drug doses and a defined patient cohort, limiting its applicability to broader clinical scenarios.
- **Next question:** How do different doses of mTOR inhibitors affect the combination therapy's efficacy and safety in diverse endometrial cancer patient populations?

---
